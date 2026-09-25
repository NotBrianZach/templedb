"""end_session must finalize the session's in-flight deploy_stage_runs.

deploy_stage_runs rows are closed by the stage context manager on exit.
Nothing closed them when the owning session ended, so a wrapper process
that died mid-stage -- or any session reaped by `vcs session gc` -- left
its row at ended_at IS NULL forever and
`deploy_stages_have_no_stale_runs` counted it from then on. 13 such rows
had accumulated by 2026-09-25, the oldest stuck open since 09-21, and
every one belonged to a session that had already ended.

Deliberately standalone rather than added to tests/vcs/test_sessions.py:
that module's fixture builds from migrations/schema.sql, which is stale
(no session_id, no reap_policy, no deploy_stage_runs) and leaves 10 of
its 17 tests failing before any of this. Building the table explicitly
here keeps the regression covered without waiting on that cleanup.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))


class _StageRunFixture(unittest.TestCase):
    """Minimal DB: just the two tables end_session touches."""

    CREATE_SESSIONS = """
        CREATE TABLE vcs_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, author TEXT, host TEXT, pid INTEGER,
            started_at TEXT DEFAULT (datetime('now')),
            ended_at TEXT, ended_reason TEXT,
            expected_lifetime_seconds INTEGER, reap_policy TEXT
        )"""
    CREATE_STAGE_RUNS = """
        CREATE TABLE deploy_stage_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stage_kind TEXT, slug TEXT, session_id INTEGER,
            input_hash TEXT, output_hash TEXT, prev_stage_run_id INTEGER,
            started_at TEXT DEFAULT (datetime('now')),
            ended_at TEXT, outcome TEXT, metadata_json TEXT
        )"""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.sqlite',
                                            prefix='stage-orphan-')
        os.close(fd)
        os.environ['TEMPLEDB_PATH'] = self.db_path
        for mod in list(sys.modules):
            if (mod.startswith('db_utils') or mod.startswith('repositories')
                    or mod.startswith('services') or mod == 'migrator'):
                del sys.modules[mod]
        conn = sqlite3.connect(self.db_path)
        conn.execute(self.CREATE_SESSIONS)
        if self.WITH_STAGE_RUNS:
            conn.execute(self.CREATE_STAGE_RUNS)
        conn.commit()
        conn.close()

    def tearDown(self):
        os.environ.pop('TEMPLEDB_PATH', None)
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def _service(self):
        from services.context import ServiceContext
        return ServiceContext().get_vcs_service()

    def _new_session(self, **cols):
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            "INSERT INTO vcs_sessions (name, author) VALUES (?, ?)",
            (cols.get('name', 'test-session'), cols.get('author', 'tester')))
        sid = cur.lastrowid
        conn.commit()
        conn.close()
        return sid

    def _add_stage_run(self, session_id, ended=False):
        conn = sqlite3.connect(self.db_path)
        cur = conn.execute(
            "INSERT INTO deploy_stage_runs "
            "(stage_kind, slug, session_id, ended_at, outcome) "
            "VALUES ('vcs_commit', 'demo', ?, ?, ?)",
            (session_id,
             "2026-09-25 00:00:00" if ended else None,
             'success' if ended else None))
        rid = cur.lastrowid
        conn.commit()
        conn.close()
        return rid

    def _row(self, run_id):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM deploy_stage_runs WHERE id = ?", (run_id,)
        ).fetchone()
        conn.close()
        return row


class TestOrphanClosing(_StageRunFixture):
    WITH_STAGE_RUNS = True

    def test_open_run_is_closed_and_marked_orphaned(self):
        sid = self._new_session()
        run = self._add_stage_run(sid)

        result = self._service().end_session(sid, reason='stale-timeout')

        row = self._row(run)
        self.assertIsNotNone(row['ended_at'],
                             "in-flight run left open by end_session")
        self.assertEqual(row['outcome'], 'orphaned')
        self.assertEqual(result['orphaned_stage_runs'], 1)

    def test_already_closed_run_keeps_its_outcome(self):
        """A stage that genuinely succeeded must not be relabelled."""
        sid = self._new_session()
        run = self._add_stage_run(sid, ended=True)

        self._service().end_session(sid)

        row = self._row(run)
        self.assertEqual(row['outcome'], 'success')
        self.assertEqual(row['ended_at'], "2026-09-25 00:00:00")

    def test_other_sessions_runs_are_untouched(self):
        mine = self._new_session(name='mine')
        theirs = self._new_session(name='theirs')
        my_run = self._add_stage_run(mine)
        their_run = self._add_stage_run(theirs)

        self._service().end_session(mine)

        self.assertEqual(self._row(my_run)['outcome'], 'orphaned')
        self.assertIsNone(self._row(their_run)['ended_at'],
                          "closed a run belonging to a live session")

    def test_reports_zero_when_nothing_was_in_flight(self):
        sid = self._new_session()
        result = self._service().end_session(sid)
        self.assertEqual(result['orphaned_stage_runs'], 0)


class TestMissingTableIsTolerated(_StageRunFixture):
    """schema.sql does not define deploy_stage_runs, so end_session has
    to survive its absence rather than fail an ordinary session end."""

    WITH_STAGE_RUNS = False

    def test_end_session_succeeds_without_the_table(self):
        sid = self._new_session()

        result = self._service().end_session(sid, reason='explicit-end')

        self.assertEqual(result['orphaned_stage_runs'], 0)
        self.assertIsNotNone(result.get('ended_at'),
                             "session was not ended")


if __name__ == '__main__':
    unittest.main()
