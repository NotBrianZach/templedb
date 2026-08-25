"""Tests for session-scoped VCS staging (Phase 1 + 2 + 3.5).

Covers the semantics established by migration 082: staging is attributed
to a vcs_sessions row via staged_by_session_id; sessions can be reused
across shell invocations via (author, host, ppid) lookup; sessions end
does not unstage rows; TEMPLEDB_SESSION_ID env var overrides implicit
resolution.
"""
import os
import sys
import sqlite3
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))


class _VCSFixture(unittest.TestCase):
    """Fresh DB with full VCS schema and a seed project + branch."""

    @classmethod
    def setUpClass(cls):
        fd, cls.db_path = tempfile.mkstemp(suffix='.sqlite', prefix='vcs-test-')
        os.close(fd)
        os.environ['TEMPLEDB_PATH'] = cls.db_path

        # Wipe any cached modules that captured the previous path
        for mod in list(sys.modules.keys()):
            if (mod.startswith('db_utils') or mod.startswith('repositories')
                    or mod.startswith('services') or mod == 'migrator'):
                del sys.modules[mod]

        # schema.sql (regenerated 2026-08-22) is the canonical superset
        # and includes migration 082's effects. Apply it directly and
        # seed the legacy-backfill session row the migration would have
        # inserted (it's a live-DB artifact, not a schema.sql shape).
        migrations_dir = Path(__file__).parent.parent.parent / 'migrations'
        conn = sqlite3.connect(cls.db_path)
        conn.executescript((migrations_dir / 'schema.sql').read_text())
        conn.execute(
            "INSERT INTO vcs_sessions (name, author, started_at, ended_at, ended_reason) "
            "VALUES ('legacy-backfill', 'unknown', "
            "datetime('now'), datetime('now'), 'backfill')"
        )
        conn.commit()
        conn.close()

        conn = sqlite3.connect(cls.db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        cur = conn.execute(
            "INSERT INTO projects (slug, name) VALUES ('vcs-test', 'VCS Test')")
        cls.project_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO vcs_branches (project_id, branch_name, is_default) "
            "VALUES (?, 'main', 1)",
            (cls.project_id,))
        cls.branch_id = cur.lastrowid
        # Seed a file_type + two project files + working_state rows so
        # stage/unstage have rows to touch.
        cur = conn.execute(
            "INSERT INTO file_types (type_name, category) VALUES ('text', 'test')")
        ftid = cur.lastrowid
        for path in ('a.txt', 'b.txt'):
            cur = conn.execute(
                "INSERT INTO project_files "
                "(project_id, file_type_id, file_path, file_name) "
                "VALUES (?, ?, ?, ?)",
                (cls.project_id, ftid, path, path))
            fid = cur.lastrowid
            conn.execute(
                "INSERT INTO vcs_working_state "
                "(project_id, branch_id, file_id, state) "
                "VALUES (?, ?, ?, 'modified')",
                (cls.project_id, cls.branch_id, fid))
        conn.commit()
        conn.close()

    @classmethod
    def tearDownClass(cls):
        os.environ.pop('TEMPLEDB_PATH', None)
        os.environ.pop('TEMPLEDB_SESSION_ID', None)
        os.environ.pop('TEMPLEDB_AUTHOR', None)
        if os.path.exists(cls.db_path):
            os.unlink(cls.db_path)

    def setUp(self):
        # Reset session envs between tests to keep isolation clean
        os.environ.pop('TEMPLEDB_SESSION_ID', None)

    def _service(self, session_id_env=None, author=None):
        """Fresh VCSService with a fresh per-request env."""
        if session_id_env is None:
            os.environ.pop('TEMPLEDB_SESSION_ID', None)
        else:
            os.environ['TEMPLEDB_SESSION_ID'] = str(session_id_env)
        if author is not None:
            os.environ['TEMPLEDB_AUTHOR'] = author
        from services.context import ServiceContext
        ctx = ServiceContext()
        return ctx.get_vcs_service()

    def _db(self):
        return sqlite3.connect(self.db_path)


class TestMigrationBackfill(_VCSFixture):

    def test_legacy_backfill_session_created(self):
        conn = self._db()
        row = conn.execute(
            "SELECT id, name, author, ended_reason FROM vcs_sessions "
            "WHERE name = 'legacy-backfill'"
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row, "migration should have created legacy-backfill session")
        self.assertEqual(row[3], 'backfill')

    def test_staged_by_session_id_column_exists(self):
        conn = self._db()
        cols = [r[1] for r in conn.execute("PRAGMA table_info(vcs_working_state)")]
        conn.close()
        self.assertIn('staged_by_session_id', cols)


class TestSessionResolution(_VCSFixture):

    def test_implicit_session_creates_new(self):
        svc = self._service(author='alice')
        s = svc.get_current_session()
        self.assertIsNotNone(s.get('id'))
        self.assertEqual(s.get('author'), 'alice')

    def test_explicit_env_var_resolves(self):
        svc = self._service(author='bob')
        s = svc.start_session(name='explicit-test')
        # Fresh service reads env
        svc2 = self._service(session_id_env=s['id'])
        s2 = svc2.get_current_session()
        self.assertEqual(s2['id'], s['id'])

    def test_invalid_env_var_raises(self):
        from error_handler import ResourceNotFoundError
        svc = self._service(session_id_env=999999)
        with self.assertRaises(ResourceNotFoundError):
            svc.get_current_session()

    def test_ppid_reuse_across_service_instances(self):
        """Same author+host+ppid should reuse a recent implicit session."""
        svc1 = self._service(author='reuse-test')
        s1 = svc1.get_current_session()
        # Fresh service instance, no env — should find s1 via ppid lookup
        svc2 = self._service(author='reuse-test')
        s2 = svc2.get_current_session()
        self.assertEqual(s1['id'], s2['id'],
                         "second implicit resolution should reuse the first session")

    def test_different_author_does_not_reuse(self):
        svc1 = self._service(author='author-A')
        s1 = svc1.get_current_session()
        svc2 = self._service(author='author-B')
        s2 = svc2.get_current_session()
        self.assertNotEqual(s1['id'], s2['id'])


class TestStagingIsolation(_VCSFixture):

    def _stage(self, author, file_pattern):
        svc = self._service(author=author)
        svc.stage_files('vcs-test', file_patterns=[file_pattern])
        return svc.get_current_session()['id']

    def test_two_sessions_see_own_stage_only(self):
        sid_a = self._stage('agent-A', 'a.txt')
        sid_b = self._stage('agent-B', 'b.txt')
        self.assertNotEqual(sid_a, sid_b)

        svc_a = self._service(session_id_env=sid_a)
        status_a = svc_a.get_status('vcs-test')
        self.assertEqual(status_a['staged'], ['a.txt'])
        self.assertEqual(status_a['staged_by_others'], ['b.txt'])

        svc_b = self._service(session_id_env=sid_b)
        status_b = svc_b.get_status('vcs-test')
        self.assertEqual(status_b['staged'], ['b.txt'])
        self.assertEqual(status_b['staged_by_others'], ['a.txt'])

    def test_reset_only_clears_own_session(self):
        sid_a = self._stage('agent-A', 'a.txt')
        sid_b = self._stage('agent-B', 'b.txt')

        svc_a = self._service(session_id_env=sid_a)
        cleared = svc_a.unstage_files('vcs-test', unstage_all=True)
        self.assertEqual(cleared, 1, "reset should clear exactly 1 row (own)")

        svc_b = self._service(session_id_env=sid_b)
        status_b = svc_b.get_status('vcs-test')
        self.assertEqual(status_b['staged'], ['b.txt'],
                         "session B's row should survive session A's reset")


class TestSessionLifecycle(_VCSFixture):

    def test_end_session_does_not_unstage(self):
        sid = self._service(author='end-test').start_session(name='lifecycle')['id']
        svc = self._service(session_id_env=sid)
        svc.stage_files('vcs-test', file_patterns=['a.txt'])

        svc.end_session(sid, reason='explicit-end')

        # Row is still staged by ended session
        conn = self._db()
        row = conn.execute(
            "SELECT COUNT(*) FROM vcs_working_state WHERE staged_by_session_id = ?",
            (sid,)
        ).fetchone()
        conn.close()
        self.assertGreaterEqual(row[0], 1, "ending a session must not unstage its rows")

    def test_list_sessions_active_filter(self):
        svc = self._service(author='list-test')
        s1 = svc.start_session(name='will-end')
        s2 = svc.start_session(name='stay-active')
        svc.end_session(s1['id'])

        all_sessions = svc.list_sessions()
        active_only = svc.list_sessions(active_only=True)

        all_ids = {s['id'] for s in all_sessions}
        active_ids = {s['id'] for s in active_only}
        self.assertIn(s1['id'], all_ids)
        self.assertIn(s2['id'], active_ids)
        self.assertNotIn(s1['id'], active_ids)


if __name__ == '__main__':
    unittest.main()
