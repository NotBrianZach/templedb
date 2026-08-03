"""Tests for _resolve_cwd in agent.service."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))
from tests.agent.conftest import setup_test_db, teardown_test_db


class TestResolveCwd(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.db_path = setup_test_db()
        cls.tmpdir = tempfile.mkdtemp(prefix="templedb_test_cwd_")

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()
        import shutil
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    def _make_project(self, slug, repo_url):
        from db_utils import execute, query_one
        execute("INSERT INTO projects (slug, name, repo_url) VALUES (?, ?, ?)",
                (slug, slug, repo_url))
        return query_one("SELECT id FROM projects WHERE slug = ?", (slug,))["id"]

    def test_context_cwd_wins(self):
        from agent.service import _resolve_cwd
        got = _resolve_cwd({"project_id": None}, {"cwd": "/explicit/path"})
        self.assertEqual(got, "/explicit/path")

    def test_context_projects_slug_resolves(self):
        from agent.service import _resolve_cwd
        self._make_project("proj_ctx", self.tmpdir)
        got = _resolve_cwd(None, {"projects": [{"slug": "proj_ctx"}]})
        self.assertEqual(got, self.tmpdir)

    def test_falls_back_to_session_project_id(self):
        from agent.service import _resolve_cwd
        pid = self._make_project("proj_sess", self.tmpdir)
        got = _resolve_cwd({"project_id": pid}, None)
        self.assertEqual(got, self.tmpdir)

    def test_context_slug_overrides_session_project(self):
        from agent.service import _resolve_cwd
        other = tempfile.mkdtemp(prefix="templedb_test_other_")
        try:
            self._make_project("proj_a", self.tmpdir)
            pid_b = self._make_project("proj_b", other)
            got = _resolve_cwd({"project_id": pid_b},
                               {"projects": [{"slug": "proj_a"}]})
            self.assertEqual(got, self.tmpdir)
        finally:
            import shutil
            shutil.rmtree(other, ignore_errors=True)

    def test_missing_directory_returns_none(self):
        from agent.service import _resolve_cwd
        self._make_project("proj_missing", "/does/not/exist/anywhere/xyz")
        got = _resolve_cwd(None, {"projects": [{"slug": "proj_missing"}]})
        self.assertIsNone(got)

    def test_unknown_slug_returns_none(self):
        from agent.service import _resolve_cwd
        got = _resolve_cwd(None, {"projects": [{"slug": "no_such_slug"}]})
        self.assertIsNone(got)

    def test_no_context_no_session_project_returns_none(self):
        from agent.service import _resolve_cwd
        got = _resolve_cwd({"project_id": None}, None)
        self.assertIsNone(got)


if __name__ == "__main__":
    unittest.main()
