"""Tests for FakeProvider."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from agent.providers.fake import FakeProvider
from agent.events import (
    RUN_STARTED, RUN_COMPLETED,
    ASSISTANT_STARTED, ASSISTANT_DELTA, ASSISTANT_COMPLETED,
    TOOL_STARTED, TOOL_COMPLETED,
)


class TestFakeProvider(unittest.TestCase):

    def setUp(self):
        self.provider = FakeProvider()

    def test_doctor(self):
        result = self.provider.doctor()
        self.assertTrue(result['ok'])

    def test_start(self):
        result = self.provider.start()
        self.assertIn('external_session_id', result)
        self.assertTrue(result['external_session_id'].startswith('fake-'))

    def test_start_resume(self):
        result = self.provider.start(session_external_id='fake-42')
        self.assertEqual(result['external_session_id'], 'fake-42')

    def test_send_short_message(self):
        """Short messages should not trigger tool use."""
        self.provider.start()
        events = list(self.provider.send(
            [{'role': 'user', 'content_text': 'hello'}]))

        types = [e['type'] for e in events]
        self.assertIn(RUN_STARTED, types)
        self.assertIn(ASSISTANT_STARTED, types)
        self.assertIn(ASSISTANT_DELTA, types)
        self.assertIn(ASSISTANT_COMPLETED, types)
        self.assertIn(RUN_COMPLETED, types)
        # Short message = no tools
        self.assertNotIn(TOOL_STARTED, types)

    def test_send_long_message(self):
        """Long messages should trigger tool use."""
        self.provider.start()
        events = list(self.provider.send(
            [{'role': 'user', 'content_text': 'Tell me everything about TempleDB architecture'}]))

        types = [e['type'] for e in events]
        self.assertIn(TOOL_STARTED, types)
        self.assertIn(TOOL_COMPLETED, types)

    def test_streaming_text(self):
        """Verify delta events contain text."""
        self.provider.start()
        events = list(self.provider.send(
            [{'role': 'user', 'content_text': 'hello'}]))

        deltas = [e for e in events if e['type'] == ASSISTANT_DELTA]
        self.assertGreater(len(deltas), 0)
        for delta in deltas:
            self.assertIn('text', delta.get('data', {}))

    def test_cancel(self):
        """Cancellation should stop generation."""
        import threading
        self.provider.start()

        events_collected = []

        def collect():
            for e in self.provider.send(
                    [{'role': 'user', 'content_text': 'Tell me a very long story about everything'}]):
                events_collected.append(e)

        t = threading.Thread(target=collect)
        t.start()
        # Cancel quickly
        import time
        time.sleep(0.05)
        self.provider.cancel()
        t.join(timeout=2)

        # Should not have RUN_COMPLETED (cancelled mid-stream)
        types = [e['type'] for e in events_collected]
        self.assertNotIn(RUN_COMPLETED, types)

    def test_keyword_matching(self):
        """Provider should match keywords in messages."""
        self.provider.start()
        events = list(self.provider.send(
            [{'role': 'user', 'content_text': 'test'}]))
        completed = [e for e in events if e['type'] == ASSISTANT_COMPLETED]
        self.assertEqual(len(completed), 1)
        self.assertIn('tests passed', completed[0]['data']['full_text'])

    def test_empty_messages(self):
        """Empty message list should produce no events."""
        self.provider.start()
        events = list(self.provider.send([]))
        self.assertEqual(len(events), 0)


if __name__ == '__main__':
    unittest.main()
