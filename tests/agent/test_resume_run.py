"""Regression: resume_run must not duplicate the last user message.

Bug context: session 282 on 2026-09-13 had two orphan user messages
(seq 79 "cool after that…", seq 80 "hows it goin") with run_id=NULL
after run 181 was interrupted. Calling resume_run in the old
implementation invoked send_message with the last message's content,
which persisted a fresh copy of it — leaving Claude looking at the
same user turn twice in a row.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from tests.agent.conftest import setup_test_db, teardown_test_db


class TestResumeRun(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def setUp(self):
        setup_test_db()

    def _make_session_with_orphan_user(self):
        from agent import store
        session = store.create_session('fake')
        # Simulate a completed prior exchange
        run1 = store.create_run(session['id'])
        store.add_message(session['id'], 'user', 'earlier question')
        store.add_message(session['id'], 'assistant', 'earlier answer',
                          run_id=run1['id'])
        store.complete_run(run1['id'], status='completed')
        # Two orphan user messages, no run
        store.add_message(session['id'], 'user', 'orphan message A')
        store.add_message(session['id'], 'user', 'orphan message B')
        store.update_session_status(session['id'], 'interrupted')
        return session

    def test_resume_does_not_duplicate_last_user_message(self):
        from agent.service import AgentService
        from agent import store

        session = self._make_session_with_orphan_user()
        service = AgentService()
        service.open_session(session['id'])

        before = store.get_messages(session['id'])
        user_before = [m for m in before if m['role'] == 'user']
        self.assertEqual(len(user_before), 3)  # earlier + A + B

        list(service.resume_run(session['id']))

        after = store.get_messages(session['id'])
        user_after = [m for m in after if m['role'] == 'user']
        # Still 3 user messages — no duplication of "orphan message B"
        self.assertEqual(
            len(user_after), 3,
            f"resume_run added a duplicate user message; found: "
            f"{[m['content_text'] for m in user_after]}"
        )
        # And there should now be an assistant response after the orphans
        self.assertEqual(after[-1]['role'], 'assistant')

    def test_resume_refuses_when_no_pending_user_message(self):
        from agent.service import AgentService
        from agent import store

        session = store.create_session('fake')
        run = store.create_run(session['id'])
        store.add_message(session['id'], 'user', 'q')
        store.add_message(session['id'], 'assistant', 'a', run_id=run['id'])
        store.complete_run(run['id'], status='completed')
        # Tail is assistant — nothing to resume
        service = AgentService()
        service.open_session(session['id'])

        with self.assertRaises(ValueError):
            list(service.resume_run(session['id']))

    def test_resume_drops_an_empty_assistant_placeholder(self):
        """A provider that dies before emitting anything leaves the
        placeholder `send_message` wrote behind. That stub used to block
        resume on a question that was never answered — 6 sessions were
        stranded that way, including #331's "do we have the option of
        using deepseek".
        """
        from agent.service import AgentService
        from agent import store

        session = store.create_session('fake')
        run = store.create_run(session['id'])
        store.add_message(session['id'], 'user', 'do we have deepseek')
        # The placeholder, never filled because the provider died.
        store.add_message(session['id'], 'assistant', '', run_id=run['id'])
        store.complete_run(run['id'], status='failed')
        store.update_session_status(session['id'], 'interrupted')

        service = AgentService()
        service.open_session(session['id'])
        list(service.resume_run(session['id']))

        msgs = store.get_messages(session['id'])
        user_msgs = [m for m in msgs if m['role'] == 'user']
        # The question was not duplicated...
        self.assertEqual(len(user_msgs), 1)
        self.assertEqual(user_msgs[0]['content_text'], 'do we have deepseek')
        # ...and it now has a real answer, not two empty stubs.
        self.assertEqual(msgs[-1]['role'], 'assistant')
        self.assertTrue(msgs[-1]['content_text'].strip(),
                        "resume left an empty assistant tail behind")
        empties = [m for m in msgs
                   if m['role'] == 'assistant'
                   and not (m['content_text'] or '').strip()]
        self.assertEqual(empties, [], "stale placeholder was not discarded")

    def test_discard_helper_refuses_a_completed_answer(self):
        """The helper must not be able to eat a real answer."""
        from agent import store

        session = store.create_session('fake')
        run = store.create_run(session['id'])
        store.add_message(session['id'], 'user', 'q')
        store.add_message(session['id'], 'assistant', 'a real answer',
                          run_id=run['id'])
        store.complete_run(run['id'], status='completed')
        self.assertEqual(
            store.discard_incomplete_assistant_tail(session['id']), 0)
        self.assertEqual(len(store.get_messages(session['id'])), 2)

    def test_discard_helper_drops_a_truncated_reply(self):
        """A reply killed mid-stream has text but is not an answer.

        This is what stranded 308 and 286: backgrounded resumes died
        partway and left tails like "I'll pick up where we left off. Let
        me find the current stat", which read as finished.
        """
        from agent import store

        session = store.create_session('fake')
        run = store.create_run(session['id'])
        store.add_message(session['id'], 'user', 'the real question')
        store.add_message(session['id'], 'assistant',
                          "I'll pick up where we left off. Let me find",
                          run_id=run['id'])
        store.complete_run(run['id'], status='interrupted')

        self.assertEqual(
            store.discard_incomplete_assistant_tail(session['id']), 1)
        msgs = store.get_messages(session['id'])
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[-1]['role'], 'user')
        # ...and the session reads as resumable again.
        self.assertTrue(store.session_resumable(session['id']))

    def test_truncated_reply_reads_as_resumable(self):
        """The predicate, not just the deleter, must see through it."""
        from agent import store

        session = store.create_session('fake')
        run = store.create_run(session['id'])
        store.add_message(session['id'], 'user', 'q')
        store.add_message(session['id'], 'assistant', 'half a sent',
                          run_id=run['id'])
        store.complete_run(run['id'], status='interrupted')
        self.assertTrue(store.session_resumable(session['id']))

    def test_discard_helper_refuses_a_user_tail(self):
        from agent import store

        session = store.create_session('fake')
        store.add_message(session['id'], 'user', 'q')
        self.assertEqual(
            store.discard_incomplete_assistant_tail(session['id']), 0)
        self.assertEqual(len(store.get_messages(session['id'])), 1)

    def test_discard_helper_leaves_earlier_empties_alone(self):
        """Only the tail is fair game — an empty row mid-history belongs
        to a run that already moved on."""
        from agent import store

        session = store.create_session('fake')
        store.add_message(session['id'], 'user', 'q1')
        store.add_message(session['id'], 'assistant', '')
        store.add_message(session['id'], 'user', 'q2')
        self.assertEqual(
            store.discard_incomplete_assistant_tail(session['id']), 0)
        self.assertEqual(len(store.get_messages(session['id'])), 3)

    def test_tail_with_no_run_attached_is_trusted(self):
        """Pre-run_id history: content and no run means a real answer,
        not a wreck. Deleter and predicate must agree on this."""
        from agent import store

        session = store.create_session('fake')
        store.add_message(session['id'], 'user', 'q')
        store.add_message(session['id'], 'assistant', 'an old answer')
        self.assertEqual(
            store.discard_incomplete_assistant_tail(session['id']), 0)
        self.assertFalse(store.session_resumable(session['id']))

    def test_send_message_with_content_still_adds_message(self):
        """The pre-existing happy path must still work: passing content
        adds a fresh user message before running."""
        from agent.service import AgentService
        from agent import store

        session = store.create_session('fake')
        service = AgentService()
        service.open_session(session['id'])
        list(service.send_message(session['id'], 'hello'))

        msgs = store.get_messages(session['id'])
        user_msgs = [m for m in msgs if m['role'] == 'user']
        self.assertEqual(len(user_msgs), 1)
        self.assertEqual(user_msgs[0]['content_text'], 'hello')


if __name__ == '__main__':
    unittest.main()
