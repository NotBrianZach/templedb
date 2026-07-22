"""Tests for the agent JSON-lines protocol."""
import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from tests.agent.conftest import setup_test_db, teardown_test_db


class TestProtocol(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def _run_protocol(self, requests):
        from agent.protocol import ProtocolServer
        input_lines = "\n".join(json.dumps(r) for r in requests) + "\n"
        input_stream = io.StringIO(input_lines)
        output_stream = io.StringIO()
        server = ProtocolServer(input_stream=input_stream, output_stream=output_stream)
        server.run()
        output_stream.seek(0)
        return [json.loads(line) for line in output_stream if line.strip()]

    def test_doctor(self):
        responses = self._run_protocol([
            {"id": 1, "method": "provider.doctor", "params": {"provider": "fake"}}
        ])
        result = next(r for r in responses if r.get('id') == 1)
        self.assertTrue(result['result']['ok'])

    def test_create_session(self):
        responses = self._run_protocol([
            {"id": 1, "method": "session.create", "params": {"provider": "fake"}}
        ])
        result = next(r for r in responses if r.get('id') == 1)
        self.assertEqual(result['result']['status'], 'created')

    def test_session_list(self):
        responses = self._run_protocol([
            {"id": 1, "method": "session.create", "params": {"provider": "fake"}},
            {"id": 2, "method": "session.list", "params": {}}
        ])
        result = next(r for r in responses if r.get('id') == 2)
        self.assertIsInstance(result['result'], list)

    def test_open_session_has_org(self):
        r1 = self._run_protocol([
            {"id": 1, "method": "session.create", "params": {"provider": "fake"}}
        ])
        sid = next(r for r in r1 if r.get('id') == 1)['result']['id']
        r2 = self._run_protocol([
            {"id": 2, "method": "session.open", "params": {"session_id": sid}}
        ])
        result = next(r for r in r2 if r.get('id') == 2)
        self.assertIn('org', result['result'])
        self.assertIn('#+TITLE: Temple Agent', result['result']['org'])

    def test_unknown_method(self):
        responses = self._run_protocol([
            {"id": 1, "method": "nonexistent.method", "params": {}}
        ])
        result = next(r for r in responses if r.get('id') == 1)
        self.assertIn('error', result)

    def test_notes(self):
        r1 = self._run_protocol([
            {"id": 1, "method": "session.create", "params": {"provider": "fake"}}
        ])
        sid = next(r for r in r1 if r.get('id') == 1)['result']['id']
        r2 = self._run_protocol([
            {"id": 2, "method": "notes.set", "params": {"session_id": sid, "goal": "Fix bug"}}
        ])
        result = next(r for r in r2 if r.get('id') == 2)
        self.assertEqual(result['result']['goal_org'], 'Fix bug')

    def test_fork(self):
        r1 = self._run_protocol([
            {"id": 1, "method": "session.create", "params": {"provider": "fake"}}
        ])
        sid = next(r for r in r1 if r.get('id') == 1)['result']['id']
        r2 = self._run_protocol([
            {"id": 2, "method": "session.fork", "params": {"session_id": sid}}
        ])
        result = next(r for r in r2 if r.get('id') == 2)
        self.assertNotEqual(result['result']['id'], sid)

    def test_queue_message(self):
        r1 = self._run_protocol([
            {"id": 1, "method": "session.create", "params": {"provider": "fake"}}
        ])
        sid = next(r for r in r1 if r.get('id') == 1)['result']['id']
        r2 = self._run_protocol([
            {"id": 2, "method": "message.queue", "params": {"session_id": sid, "content": "queued msg"}}
        ])
        result = next(r for r in r2 if r.get('id') == 2)
        self.assertTrue(result['result']['queued'])


if __name__ == '__main__':
    unittest.main()
