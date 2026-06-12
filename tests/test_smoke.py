#!/usr/bin/env python3
"""
Smoke tests for TempleDB core features.

These test the features we've built without requiring the live DB.
Runs on a temp DB created from schema.sql.
"""
import os
import sys
import tempfile
import sqlite3
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))


@pytest.fixture
def temp_db():
    """Create a temp DB from schema.sql for testing."""
    tmp = tempfile.mktemp(suffix='.sqlite')
    os.environ['TEMPLEDB_PATH'] = tmp

    from migrator import Migrator
    m = Migrator(tmp)
    m.migrate()

    yield tmp

    del os.environ['TEMPLEDB_PATH']
    try:
        os.unlink(tmp)
    except Exception:
        pass


class TestMigrator:
    def test_fresh_install(self):
        tmp = tempfile.mktemp(suffix='.sqlite')
        from migrator import Migrator
        m = Migrator(tmp)
        applied, skipped = m.migrate()
        assert applied == 1  # schema.sql
        assert skipped == 22  # numbered migrations marked as applied

        status = m.status()
        pending = sum(1 for s in status if not s["applied"])
        assert pending == 0

        os.unlink(tmp)

    def test_stamp_existing(self):
        tmp = tempfile.mktemp(suffix='.sqlite')
        # Create a DB with just a projects table (simulating old DB)
        conn = sqlite3.connect(tmp)
        conn.execute("CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT)")
        conn.close()

        from migrator import Migrator
        m = Migrator(tmp)
        stamped = m.stamp_existing()
        assert stamped > 0

        status = m.status()
        pending = sum(1 for s in status if not s["applied"])
        assert pending == 0

        os.unlink(tmp)

    def test_idempotent(self):
        tmp = tempfile.mktemp(suffix='.sqlite')
        from migrator import Migrator
        m = Migrator(tmp)
        m.migrate()
        # Run again — should be no-op
        applied, skipped = m.migrate()
        assert applied == 0
        assert skipped > 0
        os.unlink(tmp)


class TestFuseFS:
    def test_path_parsing(self):
        try:
            from temple_fuse import TempleFS
        except OSError:
            pytest.skip("libfuse not available")

        fs = TempleFS.__new__(TempleFS)

        assert fs._parse_path("/") == (None, None)
        assert fs._parse_path("/myproject") == ("myproject", None)
        assert fs._parse_path("/myproject/src/main.py") == ("myproject", "src/main.py")
        assert fs._parse_path("/a/b/c/d.txt") == ("a", "b/c/d.txt")


class TestKnowledgeGraph:
    def test_search_empty_db(self, temp_db):
        from knowledge_graph import search_everywhere
        results = search_everywhere("anything")
        assert isinstance(results, dict)

    def test_cross_project_empty(self, temp_db):
        from knowledge_graph import cross_project_analysis
        results = cross_project_analysis()
        assert "projects" in results
        assert isinstance(results["projects"], list)

    def test_project_dependencies_missing(self, temp_db):
        from knowledge_graph import project_dependencies
        result = project_dependencies("nonexistent")
        assert "error" in result


class TestDirenvGenerator:
    def test_shell_escape(self):
        from direnv_generator import shell_escape
        assert shell_escape("") == "''"
        assert shell_escape("hello") == "'hello'"
        assert "\\'" in shell_escape("it's")

    def test_get_git_info_non_repo(self):
        from direnv_generator import get_git_info
        branch, ref = get_git_info(Path("/tmp"))
        assert branch is None
        assert ref is None


class TestGitExport:
    def test_missing_project(self, temp_db):
        from git_export import export_to_git
        with pytest.raises(ValueError, match="not found"):
            export_to_git("nonexistent", "/tmp/test-export", db_path=temp_db)


class TestSyncEngine:
    def test_shadow_table_creation(self, temp_db):
        """Test that sync init creates shadow tables."""
        # This will fail if crsqlite.so isn't available, which is fine in CI
        try:
            from sync_engine import SyncEngine
            engine = SyncEngine(db_path=temp_db)
            result = engine.initialize()
            assert "site_id" in result
            assert "db_version" in result
            engine.close()
        except Exception as e:
            if "crsqlite" in str(e).lower():
                pytest.skip("cr-sqlite not available")
            raise
