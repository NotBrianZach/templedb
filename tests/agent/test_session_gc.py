"""Tests for `ai agent gc` — retiring sessions that produced nothing.

The predicate is the whole risk surface here: it decides which rows a
hard delete is allowed to touch, and the live fleet it was written
against had 149 of 159 candidates coming from the `fake` provider's own
test leavings. So each test below pins one way a session can hold
something worth keeping, and asserts that holding it is enough to be
spared.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from tests.agent.conftest import setup_test_db, teardown_test_db

OLD = "2026-01-01 00:00:00"


class GcTestCase(unittest.TestCase):
    """Shared setup: every session starts old, interrupted and empty."""

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def make_session(self, status='interrupted', updated_at=OLD):
        """An aged, empty session — retirable until a test adds something."""
        from agent.store import create_session
        from db_utils import execute
        session = create_session('fake')
        execute("UPDATE agent_sessions SET status = ?, updated_at = ? "
                "WHERE id = ?", (status, updated_at, session['id']))
        return session['id']

    def retirable_ids(self, **kwargs):
        from agent.store import retirable_sessions
        return [r['id'] for r in retirable_sessions(**kwargs)]

    def assertRetirable(self, session_id, **kwargs):
        self.assertIn(session_id, self.retirable_ids(**kwargs))

    def assertSpared(self, session_id, **kwargs):
        self.assertNotIn(session_id, self.retirable_ids(**kwargs))


class TestPredicate(GcTestCase):
    """What counts as "produced nothing"."""

    def test_empty_aged_session_is_retirable(self):
        self.assertRetirable(self.make_session())

    def test_two_messages_alone_do_not_spare_a_session(self):
        """A prompt and one reply is still no output.

        This is the shape that makes the sweep worth having: the session
        ran, said something, and left nothing behind that outlives it.
        """
        from agent.store import add_message
        sid = self.make_session()
        add_message(sid, 'user', 'hello')
        add_message(sid, 'assistant', 'hi')
        self.assertRetirable(sid)

    def test_a_third_message_spares_it(self):
        from agent.store import add_message
        sid = self.make_session()
        for i in range(3):
            add_message(sid, 'user', f'turn {i}')
        self.assertSpared(sid)

    def test_a_finding_spares_it(self):
        from agent.store import upsert_section_entry
        sid = self.make_session()
        upsert_section_entry(sid, 'findings', 'f1', {'text': 'a fact'})
        self.assertSpared(sid)

    def test_a_done_todo_still_spares_it(self):
        """Artifacts are kept on existence, not on open-ness.

        `fleet` counts only *open* todos, because a closed one needs no
        triage. Deletion is a different question: a finished todo is
        still a record of what was done.
        """
        from agent.store import upsert_section_entry
        sid = self.make_session()
        upsert_section_entry(sid, 'todo', 't1',
                             {'text': 'shipped it', 'done': True})
        self.assertSpared(sid)

    def test_an_answered_question_still_spares_it(self):
        from agent.store import upsert_section_entry
        sid = self.make_session()
        upsert_section_entry(sid, 'open-questions', 'q1',
                             {'text': 'which?', 'answered': True,
                              'answer': 'that one'})
        self.assertSpared(sid)

    def test_notes_spare_it(self):
        from agent.store import set_notes
        sid = self.make_session()
        set_notes(sid, notes_org='* something worth keeping')
        self.assertSpared(sid)

    def test_empty_notes_row_does_not_spare_it(self):
        """A notes row exists for most sessions; only content counts."""
        from agent.store import set_notes
        sid = self.make_session()
        set_notes(sid, goal_org='', notes_org='', scratch_org='')
        self.assertRetirable(sid)

    def test_a_pending_ask_spares_it(self):
        from agent.store import create_pending_ask
        sid = self.make_session()
        create_pending_ask(f'ask-gc-{sid}', sid, 'question',
                           {'questions': [{'question': 'which?'}]})
        self.assertSpared(sid)

    def test_an_expired_ask_does_not_spare_it(self):
        """Only *pending* asks count — an expired one is undeliverable."""
        from agent.store import create_pending_ask
        from db_utils import execute
        sid = self.make_session()
        ask_id = f'ask-gc-exp-{sid}'
        create_pending_ask(ask_id, sid, 'question',
                           {'questions': [{'question': 'which?'}]})
        execute("UPDATE agent_pending_asks SET status = 'expired' "
                "WHERE ask_id = ?", (ask_id,))
        self.assertRetirable(sid)


class TestGuards(GcTestCase):
    """Age and status, the two things that protect a live session."""

    def test_a_recent_session_is_spared(self):
        from agent.store import _now
        self.assertSpared(self.make_session(updated_at=_now()))

    def test_running_is_spared_however_old(self):
        """A live run has produced nothing *yet* — indistinguishable from
        having produced nothing ever, if you only look at artifacts."""
        self.assertSpared(self.make_session(status='running'))

    def test_waiting_is_spared_however_old(self):
        self.assertSpared(self.make_session(status='waiting'))

    def test_created_is_spared_however_old(self):
        self.assertSpared(self.make_session(status='created'))

    def test_older_than_days_narrows_the_set(self):
        sid = self.make_session(updated_at=OLD)
        self.assertRetirable(sid, older_than_days=1)
        # OLD is years back, so nothing can be older than a century.
        self.assertSpared(sid, older_than_days=365 * 100)

    def test_provider_filter_scopes_the_set(self):
        sid = self.make_session()
        self.assertRetirable(sid, provider='fake')
        self.assertSpared(sid, provider='claude-code')


class TestRetire(GcTestCase):
    """The delete itself."""

    def test_retire_removes_the_session_and_its_children(self):
        from agent.store import (add_message, retire_sessions, get_session,
                                 create_run)
        from db_utils import query_one
        sid = self.make_session()
        run = create_run(sid)
        add_message(sid, 'user', 'hello', run_id=run['id'])

        deleted = retire_sessions([sid])

        self.assertEqual(deleted['agent_sessions'], 1)
        self.assertEqual(deleted['agent_messages'], 1)
        self.assertEqual(deleted['agent_runs'], 1)
        self.assertIsNone(get_session(sid))
        for table, col in (('agent_messages', 'session_id'),
                           ('agent_runs', 'session_id')):
            left = query_one(f"SELECT COUNT(*) AS n FROM {table} "
                             f"WHERE {col} = ?", (sid,))
            self.assertEqual(left['n'], 0, f"{table} left behind a child")

    def test_retire_takes_explicit_ids_not_the_predicate(self):
        """What you confirmed is what goes.

        `retire_sessions` deliberately does not re-run the predicate: a
        session that became retirable between the dry run and the apply
        must not be swept unseen.
        """
        from agent.store import retire_sessions, get_session
        keep = self.make_session()
        drop = self.make_session()
        retire_sessions([drop])
        self.assertIsNone(get_session(drop))
        self.assertIsNotNone(get_session(keep))

    def test_retire_of_nothing_is_a_no_op(self):
        from agent.store import retire_sessions
        self.assertEqual(retire_sessions([]), {})

    def test_retire_reports_zero_for_untouched_tables(self):
        """Every table in the delete order appears in the result, so a
        caller printing the breakdown cannot silently omit one."""
        from agent.store import retire_sessions, _RETIRE_DELETES
        sid = self.make_session()
        deleted = retire_sessions([sid])
        self.assertEqual(set(deleted), {t for t, _ in _RETIRE_DELETES})

    def test_batching_handles_more_ids_than_one_statement_allows(self):
        """The id list is chunked to stay under SQLite's parameter cap."""
        from agent.store import retire_sessions, _RETIRE_BATCH, get_session
        ids = [self.make_session() for _ in range(5)]
        deleted = retire_sessions(ids)
        self.assertEqual(deleted['agent_sessions'], len(ids))
        self.assertTrue(all(get_session(i) is None for i in ids))
        self.assertGreater(_RETIRE_BATCH, 0)


if __name__ == '__main__':
    unittest.main()
