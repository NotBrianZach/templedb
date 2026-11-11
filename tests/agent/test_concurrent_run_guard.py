"""Regression: `message.send` must not start a second run on one session.

Emacs chooses `message.queue` over `message.send` from its own local
status flag, but that check is per-client and incomplete —
`templedb-agent-guide` (, i) calls send unconditionally, and so do the
CLI and the roster. Nothing server-side stopped it: `send_message` read
`_active_run` nowhere, only wrote it.

A second run is not merely noisy. It:

  - overwrites `_cancel_flags[session_id]`, so the first run can no
    longer be cancelled at all;
  - overwrites the single per-session provider's `self._process`,
    orphaning the first subprocess with no handle left to kill it;
  - leaves both runs driving one `claude --resume <id>` conversation;
  - and pops `_active_run` when whichever finishes first ends — at which
    point `queue_message` sees no active run and starts a third.

The guard degrades to a queue rather than erroring, because a guide
message is a correction someone typed and delivering it late beats
discarding it.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from tests.agent.conftest import setup_test_db, teardown_test_db


class TestConcurrentRunGuard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def setUp(self):
        setup_test_db()

    def _service_with_active_run(self):
        from agent import store
        from agent.service import AgentService
        session = store.create_session('fake')
        service = AgentService()
        service.open_session(session['id'])
        run = store.create_run(session['id'])
        service._active_run[session['id']] = run
        return store, service, session['id'], run

    def test_send_during_a_run_queues_instead_of_starting_a_second(self):
        store, service, sid, run = self._service_with_active_run()

        events = list(service.send_message(sid, 'actually, use main'))

        # The message is persisted exactly once, so the post-turn drain
        # will answer it.
        users = [m for m in store.get_messages(sid) if m['role'] == 'user']
        self.assertEqual([m['content_text'] for m in users],
                         ['actually, use main'])
        # No assistant turn was produced — no second run ran.
        self.assertEqual(
            [m for m in store.get_messages(sid) if m['role'] == 'assistant'],
            [])
        # And the active run is still the original one.
        self.assertEqual(service._active_run[sid]['id'], run['id'])

    def test_the_queue_is_reported_rather_than_silent(self):
        """The user typed a correction expecting immediacy. Saying nothing
        would let them believe it was injected into the turn."""
        from agent import events as _events
        store, service, sid, _run = self._service_with_active_run()

        got = list(service.send_message(sid, 'stop touching migrations'))

        self.assertEqual([e['type'] for e in got],
                         [_events.AGENT_MESSAGE])
        self.assertIn('ueued', got[0]['summary'])

    def test_the_first_runs_cancel_flag_survives(self):
        """The sharp edge: service.py's `_cancel_flags[session_id] = ...`
        would replace the live run's event, and `cancel_run` would then
        set a flag nothing is reading."""
        import threading
        store, service, sid, _run = self._service_with_active_run()
        original = threading.Event()
        service._cancel_flags[sid] = original

        list(service.send_message(sid, 'second message'))

        self.assertIs(service._cancel_flags[sid], original)

    def test_no_new_run_row_is_created(self):
        store, service, sid, run = self._service_with_active_run()

        list(service.send_message(sid, 'another'))

        from db_utils import query_all
        rows = query_all(
            "SELECT id FROM agent_runs WHERE session_id = ?", (sid,))
        self.assertEqual([r['id'] for r in rows], [run['id']],
                         "a second agent_runs row means the guard let a "
                         "concurrent run through")

    def test_contentless_send_during_a_run_is_a_noop(self):
        """`content=None` is the resume/drain signature. There is nothing
        to queue, so it must not persist an empty message either."""
        store, service, sid, _run = self._service_with_active_run()

        before = len(store.get_messages(sid))
        self.assertEqual(list(service.send_message(sid, content=None)), [])
        self.assertEqual(len(store.get_messages(sid)), before)

    def test_an_idle_session_still_sends_normally(self):
        """The guard must not break the ordinary path."""
        from agent import store
        from agent.service import AgentService

        session = store.create_session('fake')
        service = AgentService()
        service.open_session(session['id'])

        list(service.send_message(session['id'], 'hello'))

        roles = [m['role'] for m in store.get_messages(session['id'])]
        self.assertIn('assistant', roles)

    def test_drain_after_a_guarded_queue_answers_the_message(self):
        """End to end: the queued correction must actually get answered
        when the turn it arrived during finishes."""
        from agent import store
        from agent.service import AgentService

        session = store.create_session('fake')
        sid = session['id']
        service = AgentService()
        service.open_session(sid)

        # A real turn, with a guarded send landing partway through it.
        def _queue_midway():
            time.sleep(0.01)
            list(service.send_message(sid, 'and also check the lock'))

        import threading
        t = threading.Thread(target=_queue_midway)
        t.start()
        list(service.send_message(sid, 'first turn'))
        t.join()

        msgs = store.get_messages(sid)
        users = [m['content_text'] for m in msgs if m['role'] == 'user']
        self.assertIn('and also check the lock', users)
        # The drain answered it: more assistant turns than one.
        assistants = [m for m in msgs if m['role'] == 'assistant']
        self.assertGreaterEqual(len(assistants), 1)


if __name__ == '__main__':
    unittest.main()
