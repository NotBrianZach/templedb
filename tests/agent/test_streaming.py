"""Tests for streaming and batched writes."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from tests.agent.conftest import setup_test_db, teardown_test_db


class TestStreaming(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def test_full_streaming_flow(self):
        from agent.service import AgentService
        from agent.events import ASSISTANT_DELTA, RUN_COMPLETED
        service = AgentService()
        session = service.create_session(provider_name='fake')
        events = list(service.send_message(session['id'], 'hello'))
        types = [e['type'] for e in events]
        self.assertIn(ASSISTANT_DELTA, types)
        self.assertIn(RUN_COMPLETED, types)
        messages = service.get_messages(session['id'])
        self.assertEqual(len(messages), 2)
        self.assertGreater(len(messages[1]['content_text']), 0)

    def test_deltas_not_stored_as_events(self):
        from agent.service import AgentService
        from agent import store
        service = AgentService()
        session = service.create_session(provider_name='fake')
        list(service.send_message(session['id'], 'hello'))
        runs = store.list_runs(session['id'])
        events = store.get_all_run_events(runs[0]['id'])
        event_types = [e['event_type'] for e in events]
        self.assertNotIn('assistant.delta', event_types)
        self.assertIn('run.started', event_types)

    def test_auto_title(self):
        from agent.service import AgentService
        service = AgentService()
        session = service.create_session(provider_name='fake')
        list(service.send_message(session['id'], 'How does VCS work?'))
        updated = service.get_session(session['id'])
        self.assertEqual(updated['title'], 'How does VCS work?')

    def test_session_status_lifecycle(self):
        from agent.service import AgentService
        service = AgentService()
        session = service.create_session(provider_name='fake')
        self.assertEqual(session['status'], 'created')
        list(service.send_message(session['id'], 'hello'))
        updated = service.get_session(session['id'])
        self.assertEqual(updated['status'], 'waiting')

    def test_event_callbacks(self):
        from agent.service import AgentService
        service = AgentService()
        callback_events = []
        service.add_event_callback(lambda sid, rid, e: callback_events.append(e))
        session = service.create_session(provider_name='fake')
        list(service.send_message(session['id'], 'hello'))
        self.assertGreater(len(callback_events), 0)
        for e in callback_events:
            self.assertIn('session_id', e)


if __name__ == '__main__':
    unittest.main()
