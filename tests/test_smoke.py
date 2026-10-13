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
    prev_path = os.environ.get('TEMPLEDB_PATH')
    os.environ['TEMPLEDB_PATH'] = tmp

    from migrator import Migrator
    m = Migrator(tmp)
    m.migrate()

    yield tmp

    # Restore, never delete: an absent TEMPLEDB_PATH resolves to the
    # production database for every test that runs after this one.
    if prev_path is None:
        os.environ.pop('TEMPLEDB_PATH', None)
    else:
        os.environ['TEMPLEDB_PATH'] = prev_path
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
        # Was `assert skipped == len(MIGRATION_SEQUENCE)`, a module-level
        # list that no longer exists — migrator globs MIGRATIONS_DIR
        # instead of carrying a hardcoded sequence, so the import raised
        # ImportError and the test asserted nothing.
        #
        # Not restored as a count against _discover_migrations(). That
        # number is not a constant: MIGRATIONS_DIR is resolved by
        # probing candidate paths relative to the module, and the same
        # call answered 93 under pytest, 99 inside Migrator (which
        # passes its own migrations_dir and applied_filenames) and 0
        # from a bare script with src on PYTHONPATH. Pinning it would
        # mean re-deriving the migrator's own arguments and then
        # asserting the implementation against itself.
        #
        # The property worth holding is below and was already there: a
        # fresh install leaves nothing pending. All this adds is that
        # the numbered migrations were marked rather than silently
        # finding none.
        assert skipped > 0

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


# TestFuseFS lived here until 2026-10-13. FUSE was retired 2026-09-05
# (see reports/2026-08-29-post-fuse-editing-ux-alternatives-and-
# recommendation.html) and commit 954CDCDD purged it, including a fix to
# test.yml which was "still importing the deleted temple_fuse and
# cli.commands.mount modules" — so CI's import list got attention and
# this file did not.
#
# It survived because its own guard was shaped for the previous era:
# `except OSError: pytest.skip("libfuse not available")` was right when
# the module existed and the C library might not. A deleted module
# raises ModuleNotFoundError, which subclasses ImportError and not
# OSError, so the skip never fired and the test simply failed — one of
# the permanent reds that make a suite's failure count stop meaning
# anything.
#
# Deleted rather than widened to `except (OSError, ImportError)`: that
# would skip forever, and a test that always skips reads as coverage
# while asserting nothing. There is no TempleFS to parse paths with.


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


