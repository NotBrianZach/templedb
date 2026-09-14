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
