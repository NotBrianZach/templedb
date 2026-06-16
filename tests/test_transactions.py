#!/usr/bin/env python3
"""
Test transaction rollback functionality in ProjectImporter

Tests:
1. Successful import commits all changes atomically
2. Failed import rolls back all changes (nothing persists)

Moved from root test_transactions.py and updated to use common fixtures.
"""

import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from db_utils import query_one, execute
from importer import ProjectImporter
from conftest import temp_project_dir, clean_db_session


@pytest.mark.integration
@pytest.mark.unit
def test_successful_import_commits_atomically(temp_project_dir: Path, clean_db_session):
    """Test that successful import commits all changes atomically"""

    project_slug = f"test_success_{id(temp_project_dir)}"

    try:
        # Get counts before import
        before_projects = query_one("SELECT COUNT(*) as count FROM projects")['count']
        before_files = query_one("SELECT COUNT(*) as count FROM project_files")['count']
        before_contents = query_one("SELECT COUNT(*) as count FROM file_contents")['count']

        # Create project record
        execute("""
            INSERT INTO projects (slug, name, repo_url, git_branch)
            VALUES (?, ?, ?, 'main')
        """, (project_slug, project_slug, str(temp_project_dir)))

        # Import project
        importer = ProjectImporter(project_slug, str(temp_project_dir))
        stats = importer.import_files()

        # Get counts after import
        after_projects = query_one("SELECT COUNT(*) as count FROM projects")['count']
        after_files = query_one("SELECT COUNT(*) as count FROM project_files")['count']
        after_contents = query_one("SELECT COUNT(*) as count FROM file_contents")['count']

        # Verify atomicity
        assert after_projects == before_projects + 1, "Project should be created"
        assert after_files > before_files, "Files should be imported"
        assert after_contents > before_contents, "Contents should be stored"
        assert stats.files_imported > 0, "Should have imported files"

    finally:
        # Cleanup
        project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if project:
            execute("DELETE FROM file_contents WHERE file_id IN (SELECT id FROM project_files WHERE project_id = ?)", (project['id'],))
            execute("DELETE FROM project_files WHERE project_id = ?", (project['id'],))
            execute("DELETE FROM projects WHERE id = ?", (project['id'],))


@pytest.mark.integration
@pytest.mark.unit
def test_failed_import_rolls_back(temp_project_dir: Path, clean_db_session):
    """Test that failed import rolls back all changes"""

    project_slug = f"test_rollback_{id(temp_project_dir)}"

    try:
        # Get counts before import (before creating project)
        before_projects = query_one("SELECT COUNT(*) as count FROM projects")['count']
        before_files = query_one("SELECT COUNT(*) as count FROM project_files")['count']
        before_contents = query_one("SELECT COUNT(*) as count FROM file_contents")['count']

        # Create project record (this will persist even if import fails)
        execute("""
            INSERT INTO projects (slug, name, repo_url, git_branch)
            VALUES (?, ?, ?, 'main')
        """, (project_slug, project_slug, str(temp_project_dir)))

        expected_projects = before_projects + 1

        # Create importer
        importer = ProjectImporter(project_slug, str(temp_project_dir))

        # Monkey-patch to force failure in the middle of import
        original_store_contents = importer._store_file_contents

        def failing_store_contents():
            # Call original to do some work
            original_store_contents()
            # Then raise an error to trigger rollback
            raise Exception("Simulated failure for testing rollback")

        importer._store_file_contents = failing_store_contents

        # Try to import (should fail)
        with pytest.raises(Exception, match="Simulated failure"):
            importer.import_files()

        # Get counts after failed import
        after_projects = query_one("SELECT COUNT(*) as count FROM projects")['count']
        after_files = query_one("SELECT COUNT(*) as count FROM project_files")['count']
        after_contents = query_one("SELECT COUNT(*) as count FROM file_contents")['count']

        # Verify rollback worked
        # Project record will persist (created before transaction), but that's OK
        assert after_projects == expected_projects, \
            f"Project count should be {expected_projects}, got {after_projects}"

        # The important checks: files and contents should NOT have changed
        # (transaction rolled back the import)
        assert after_files == before_files, \
            f"Rollback failed: Files changed from {before_files} to {after_files}"

        assert after_contents == before_contents, \
            f"Rollback failed: Contents changed from {before_contents} to {after_contents}"

    finally:
        # Cleanup
        project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if project:
            execute("DELETE FROM file_contents WHERE file_id IN (SELECT id FROM project_files WHERE project_id = ?)", (project['id'],))
            execute("DELETE FROM project_files WHERE project_id = ?", (project['id'],))
            execute("DELETE FROM projects WHERE id = ?", (project['id'],))


@pytest.mark.integration
def test_import_empty_directory(clean_db_session):
    """Test importing an empty directory"""

    import tempfile
    import shutil

    empty_dir = Path(tempfile.mkdtemp(prefix='templedb_empty_'))
    project_slug = f"test_empty_{id(empty_dir)}"

    try:
        # Create project
        execute("""
            INSERT INTO projects (slug, name, repo_url, git_branch)
            VALUES (?, ?, ?, 'main')
        """, (project_slug, project_slug, str(empty_dir)))

        # Import empty directory
        importer = ProjectImporter(project_slug, str(empty_dir))
        stats = importer.import_files()

        # Should complete without error but import 0 files
        assert stats.files_imported == 0, "Empty directory should import 0 files"

    finally:
        # Cleanup
        project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if project:
            execute("DELETE FROM projects WHERE id = ?", (project['id'],))
        shutil.rmtree(empty_dir, ignore_errors=True)
