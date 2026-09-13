"""Regression: queued messages must actually get processed.

Before the fix (pre-2026-09-13 session 282 incident), AgentService kept
an in-memory `_queued_messages` dict. `queue_message` appended to it,
but `_process_queue` was never called from anywhere and it referenced
a nonexistent `_run_with_provider`. Any message that Emacs queued while
Claude appeared to be running was persisted to the DB with run_id=NULL
and then sat there forever.

Two-part fix under test:

1. `queue_message` with no active run for the session starts a run in a
   background thread so the message doesn't sit indefinitely (covers
   Emacs's local status flag going stale after a mid-run crash).

2. `send_message` gets a post-turn drain hook: after the run completes
   cleanly, if the DB tail is still user-authored (queued messages
   arrived during the turn), it recursively runs another turn to answer
   them.

Failed/cancelled turns must NOT trigger a drain — otherwise a
persistently-failing provider would busy-loop forever.
"""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from tests.agent.conftest import setup_test_db, teardown_test_db


class TestQueueMessage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def setUp(self):
        setup_test_db()

    def _wait_for(self, predicate, timeout=3.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return False

    def test_queue_when_no_active_run_kicks_off_a_run(self):
        """The 2026-09-13 session-282 case: Emacs called message.queue
        with no active run in-process, and the message rotted with
        run_id=NULL. queue_message must now start a run."""
        from agent import store
        from agent.service import AgentService

        session = store.create_session('fake')
        service = AgentService()
        service.open_session(session['id'])

        service.queue_message(session['id'], 'hello from the queue')

        # A background thread drives the drain — wait for the assistant
        # response to land in the DB.
        ok = self._wait_for(lambda: any(
            m['role'] == 'assistant'
            for m in store.get_messages(session['id'])
        ))
        self.assertTrue(
            ok, "queue_message did not produce an assistant response "
                "within the timeout — the queued message would sit "
                "forever like session 282's seq 79/80"
        )
        # And there's exactly one user message (no duplication).
        users = [m for m in store.get_messages(session['id'])
                 if m['role'] == 'user']
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]['content_text'], 'hello from the queue')

    def test_active_run_queue_only_persists_no_thread(self):
        """When a run is active, queue_message must ONLY persist and let
        the drain hook pick up — spawning a duplicate background run
        would produce two answers to the same message."""
        from agent import store
        from agent.service import AgentService

        session = store.create_session('fake')
        service = AgentService()
        service.open_session(session['id'])

        # Simulate "run is active"
        service._active_run[session['id']] = {'id': 999}
        service.queue_message(session['id'], 'queued during run')

        users = [m for m in store.get_messages(session['id'])
                 if m['role'] == 'user']
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]['content_text'], 'queued during run')

        # No background thread should have kicked off a run — after a
        # short pause there's still no assistant message.
        time.sleep(0.2)
        assistants = [m for m in store.get_messages(session['id'])
                      if m['role'] == 'assistant']
        self.assertEqual(len(assistants), 0)

    def test_post_turn_drain_processes_orphan_user_message(self):
        """If a user message lands in the DB while a run is in flight
        (queue_message just persisted it, drain hook didn't yet fire),
        the drain fires when the current run completes and issues a
        second turn to answer it."""
        from agent import store
        from agent.service import AgentService
        from agent.providers.fake import FakeProvider
        from agent.events import RUN_COMPLETED, ASSISTANT_DELTA

        # A provider that, after its first delta, injects an "orphan"
        # user message into the DB — mimicking what queue_message
        # would have done had it fired while this run was streaming.
        class QueueDuringStreamProvider(FakeProvider):
            def __init__(self, session_id):
                super().__init__()
                self.session_id = session_id
                self._injected = False
            def send(self, messages, context=None):
                for ev in super().send(messages, context):
                    yield ev
                    if not self._injected and ev.get("type") == ASSISTANT_DELTA:
                        store.add_message(
                            self.session_id, 'user', 'landed mid-stream'
                        )
                        self._injected = True

        session = store.create_session('fake')
        service = AgentService()
        service._providers[session['id']] = QueueDuringStreamProvider(
            session['id']
        )

        events = list(service.send_message(session['id'], 'first turn'))
        completed = [e for e in events if e['type'] == RUN_COMPLETED]
        self.assertEqual(
            len(completed), 2,
            f"expected 2 RUN_COMPLETED (turn 1 + drain of mid-stream "
            f"injected user msg), got {len(completed)}"
        )
        msgs = store.get_messages(session['id'])
        users = [m for m in msgs if m['role'] == 'user']
        self.assertEqual([m['content_text'] for m in users],
                         ['first turn', 'landed mid-stream'])
        assistants = [m for m in msgs if m['role'] == 'assistant']
        # Two runs → two assistant rows, both non-empty.
        self.assertEqual(len(assistants), 2)
        for m in assistants:
            self.assertTrue(m['content_text'])

    def test_no_infinite_loop_on_failed_run(self):
        """If the provider yields RUN_FAILED, the drain hook must NOT
        recurse — otherwise a bad provider would busy-loop the CPU."""
        from agent import store
        from agent.service import AgentService
        from agent.events import make_event, RUN_FAILED, RUN_STARTED

        class AlwaysFailProvider:
            def start(self, **kw): return {}
            def normalize_event(self, ev): return ev
            def send(self, messages, context=None):
                yield make_event(RUN_STARTED, summary="starting")
                yield make_event(RUN_FAILED, summary="boom", error="boom")
            def cancel(self): pass
            def cleanup(self): pass

        session = store.create_session('fake')
        service = AgentService()
        service._providers[session['id']] = AlwaysFailProvider()

        # Add an orphan user message that would ordinarily be drained.
        store.add_message(session['id'], 'user', 'first orphan')

        events = list(service.send_message(session['id'],
                                           content='trigger'))
        from agent.events import RUN_FAILED as _RF
        # Exactly one RUN_FAILED — no recursion.
        failed = [e for e in events if e['type'] == _RF]
        self.assertEqual(len(failed), 1)


if __name__ == '__main__':
    unittest.main()
