"""Tests for crash recovery."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from tests.agent.conftest import setup_test_db, teardown_test_db


class TestRecovery(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def test_recover_orphaned_run(self):
        from agent import store
        from agent.service import AgentService
        session = store.create_session('fake')
        run = store.create_run(session['id'])
        store.update_session_status(session['id'], 'running')
        service = AgentService()
        recovered = service.recover()
        self.assertIn(session['id'], recovered)
        updated_run = store.get_run(run['id'])
        self.assertEqual(updated_run['status'], 'interrupted')

    def test_open_running_session_recovers(self):
        from agent import store
        from agent.service import AgentService
        session = store.create_session('fake')
        store.create_run(session['id'])
        store.update_session_status(session['id'], 'running')
        service = AgentService()
        opened = service.open_session(session['id'])
        self.assertEqual(opened['status'], 'interrupted')

    def test_partial_message_survives(self):
        from agent import store
        session = store.create_session('fake')
        run = store.create_run(session['id'])
        store.add_message(session['id'], 'user', 'hello')
        store.add_message(session['id'], 'assistant', 'partial text...', run_id=run['id'])
        messages = store.get_messages(session['id'])
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[1]['content_text'], 'partial text...')

    def test_resume_after_recovery(self):
        from agent import store
        from agent.service import AgentService
        from agent.events import RUN_COMPLETED
        session = store.create_session('fake')
        store.add_message(session['id'], 'user', 'hello')
        store.add_message(session['id'], 'assistant', 'partial...')
        store.create_run(session['id'])
        store.update_session_status(session['id'], 'running')
        service = AgentService()
        service.recover()
        service.open_session(session['id'])
        events = list(service.send_message(session['id'], 'continue please'))
        types = [e['type'] for e in events]
        self.assertIn(RUN_COMPLETED, types)
        messages = store.get_messages(session['id'])
        self.assertEqual(len(messages), 4)


if __name__ == '__main__':
    unittest.main()
