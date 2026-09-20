"""Tests for agent store (database layer)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from tests.agent.conftest import setup_test_db, teardown_test_db


class TestStore(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def test_get_provider(self):
        from agent.store import get_provider
        p = get_provider('fake')
        self.assertIsNotNone(p)
        self.assertEqual(p['name'], 'fake')

    def test_get_provider_claude(self):
        from agent.store import get_provider
        p = get_provider('claude-code')
        self.assertIsNotNone(p)
        self.assertEqual(p['provider_kind'], 'claude_code')

    def test_list_providers(self):
        from agent.store import list_providers
        providers = list_providers()
        self.assertGreaterEqual(len(providers), 2)

    def test_create_session(self):
        from agent.store import create_session, get_session
        session = create_session('fake')
        self.assertIsNotNone(session)
        self.assertEqual(session['status'], 'created')
        fetched = get_session(session['id'])
        self.assertEqual(fetched['provider_name'], 'fake')

    def test_session_status_update(self):
        from agent.store import create_session, update_session_status, get_session
        session = create_session('fake')
        update_session_status(session['id'], 'running')
        fetched = get_session(session['id'])
        self.assertEqual(fetched['status'], 'running')

    def test_create_run(self):
        from agent.store import create_session, create_run
        session = create_session('fake')
        run = create_run(session['id'])
        self.assertIsNotNone(run)
        self.assertEqual(run['status'], 'running')

    def test_add_message(self):
        from agent.store import create_session, add_message, get_messages
        session = create_session('fake')
        msg = add_message(session['id'], 'user', 'Hello!')
        self.assertEqual(msg['sequence_number'], 1)
        msg2 = add_message(session['id'], 'assistant', 'Hi!')
        self.assertEqual(msg2['sequence_number'], 2)
        messages = get_messages(session['id'])
        self.assertEqual(len(messages), 2)

    def test_add_event(self):
        from agent.store import create_session, create_run, add_event, get_events_since
        session = create_session('fake')
        run = create_run(session['id'])
        evt = add_event(run['id'], 'tool.started', summary='Reading file')
        self.assertEqual(evt['event_type'], 'tool.started')
        events = get_events_since(run['id'], 0)
        self.assertEqual(len(events), 1)

    def test_add_event_records_tool_call_started(self):
        """Phase 3: add_event('tool.started') should also insert a
        tool_calls row with status='running'."""
        from agent.store import create_session, create_run, add_event
        import sqlite3
        session = create_session('fake')
        run = create_run(session['id'])
        add_event(run['id'], 'tool.started',
                  payload={'tool_name': 'Read file'})

        # tool_calls row exists
        conn = sqlite3.connect(os.environ.get('TEMPLEDB_PATH'))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM tool_calls WHERE run_id = ?",
            (run['id'],),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row, "tool_calls row not created")
        self.assertEqual(row['status'], 'running')
        self.assertEqual(row['tool_name'], 'Read file')
        self.assertEqual(row['session_id'], session['id'])

    def test_add_event_completes_tool_call(self):
        """Phase 3: tool.completed should close the most recent
        running tool_call in the same run."""
        from agent.store import create_session, create_run, add_event
        import sqlite3
        session = create_session('fake')
        run = create_run(session['id'])
        add_event(run['id'], 'tool.started',
                  payload={'tool_name': 'Read'})
        add_event(run['id'], 'tool.completed', payload={})

        conn = sqlite3.connect(os.environ.get('TEMPLEDB_PATH'))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status, finished_at FROM tool_calls WHERE run_id = ?",
            (run['id'],),
        ).fetchone()
        conn.close()
        self.assertEqual(row['status'], 'completed')
        self.assertIsNotNone(row['finished_at'])

    def test_add_event_tool_failed_marks_failed(self):
        """tool.failed should mark status='failed'."""
        from agent.store import create_session, create_run, add_event
        import sqlite3
        session = create_session('fake')
        run = create_run(session['id'])
        add_event(run['id'], 'tool.started',
                  payload={'tool_name': 'Bash'})
        add_event(run['id'], 'tool.failed', payload={})

        conn = sqlite3.connect(os.environ.get('TEMPLEDB_PATH'))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM tool_calls WHERE run_id = ?",
            (run['id'],),
        ).fetchone()
        conn.close()
        self.assertEqual(row['status'], 'failed')

    def test_session_notes(self):
        from agent.store import create_session, set_notes, get_notes
        session = create_session('fake')
        set_notes(session['id'], goal_org='Fix bug', notes_org='Check logs')
        notes = get_notes(session['id'])
        self.assertEqual(notes['goal_org'], 'Fix bug')
        set_notes(session['id'], goal_org='Fix bug v2')
        notes = get_notes(session['id'])
        self.assertEqual(notes['goal_org'], 'Fix bug v2')
        self.assertEqual(notes['notes_org'], 'Check logs')

    def test_fork_session(self):
        from agent.store import create_session, add_message, fork_session, get_messages
        session = create_session('fake', title='Original')
        add_message(session['id'], 'user', 'Hello')
        add_message(session['id'], 'assistant', 'Hi')
        forked = fork_session(session['id'])
        self.assertNotEqual(forked['id'], session['id'])
        self.assertIn('Fork of', forked['title'])
        msgs = get_messages(forked['id'])
        self.assertEqual(len(msgs), 2)

    def test_recover_interrupted(self):
        from agent.store import create_session, create_run, recover_interrupted_sessions, get_run
        session = create_session('fake')
        run = create_run(session['id'])
        recovered = recover_interrupted_sessions()
        self.assertIn(session['id'], recovered)
        run = get_run(run['id'])
        self.assertEqual(run['status'], 'interrupted')


if __name__ == '__main__':
    unittest.main()
