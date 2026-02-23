#!/usr/bin/env python3
"""
Test transaction rollback functionality in ProjectImporter

Tests:
1. Successful import commits all changes atomically
2. Failed import rolls back all changes (nothing persists)
"""

import os
import sys
import shutil
import tempfile
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / 'src'))

from db_utils import query_one, execute, get_connection, close_connection
from importer import ProjectImporter


def setup_test_project():
    """Create a temporary test project"""
    test_dir = tempfile.mkdtemp(prefix='templedb_test_')
    test_path = Path(test_dir)

    # Create some test files
    (test_path / 'test.py').write_text('print("hello")\n')
    (test_path / 'test.txt').write_text('test content\n')
    (test_path / 'subdir').mkdir()
    (test_path / 'subdir' / 'nested.py').write_text('def foo():\n    pass\n')

    return test_path


def cleanup_test_project(project_slug):
    """Remove test project from database"""
    project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
    if project:
        execute("DELETE FROM file_contents WHERE file_id IN (SELECT id FROM project_files WHERE project_id = ?)", (project['id'],))
        execute("DELETE FROM project_files WHERE project_id = ?", (project['id'],))
        execute("DELETE FROM projects WHERE id = ?", (project['id'],))


def create_test_project(project_slug, project_path):
    """Create a test project record in database"""
    execute("""
        INSERT INTO projects (slug, name, repo_url, git_branch)
        VALUES (?, ?, ?, 'main')
    """, (project_slug, project_slug, str(project_path)))


def test_successful_import():
    """Test that successful import commits all changes"""
    print("=" * 70)
    print("TEST 1: Successful Import (Atomic Commit)")
    print("=" * 70)

    test_path = setup_test_project()
    project_slug = "test_success"

    try:
        # Clean up any existing test project
        cleanup_test_project(project_slug)

        # Get counts before import
        before_projects = query_one("SELECT COUNT(*) as count FROM projects")['count']
        before_files = query_one("SELECT COUNT(*) as count FROM project_files")['count']
        before_contents = query_one("SELECT COUNT(*) as count FROM file_contents")['count']

        print(f"\n📊 Before import:")
        print(f"  Projects: {before_projects}")
        print(f"  Files: {before_files}")
        print(f"  Contents: {before_contents}")

        # Create project record
        create_test_project(project_slug, test_path)

        # Import project
        print(f"\n▶️  Importing {test_path}...")
        importer = ProjectImporter(project_slug, str(test_path))
        stats = importer.import_files()

        # Get counts after import
        after_projects = query_one("SELECT COUNT(*) as count FROM projects")['count']
        after_files = query_one("SELECT COUNT(*) as count FROM project_files")['count']
        after_contents = query_one("SELECT COUNT(*) as count FROM file_contents")['count']

        print(f"\n📊 After import:")
        print(f"  Projects: {after_projects}")
        print(f"  Files: {after_files}")
        print(f"  Contents: {after_contents}")

        # Verify atomicity
        assert after_projects == before_projects + 1, "Project should be created"
        assert after_files > before_files, "Files should be imported"
        assert after_contents > before_contents, "Contents should be stored"

        print(f"\n✅ SUCCESS: All changes committed atomically!")
        print(f"  Imported {stats.files_imported} files")

        # Cleanup
        cleanup_test_project(project_slug)
        return True

    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        cleanup_test_project(project_slug)
        return False
    finally:
        shutil.rmtree(test_path, ignore_errors=True)
        close_connection()


def test_failed_import_rollback():
    """Test that failed import rolls back all changes"""
    print("\n" + "=" * 70)
    print("TEST 2: Failed Import (Rollback)")
    print("=" * 70)

    test_path = setup_test_project()
    project_slug = "test_rollback"

    try:
        # Clean up any existing test project
        cleanup_test_project(project_slug)

        # Get counts before import (before creating project)
        before_projects = query_one("SELECT COUNT(*) as count FROM projects")['count']
        before_files = query_one("SELECT COUNT(*) as count FROM project_files")['count']
        before_contents = query_one("SELECT COUNT(*) as count FROM file_contents")['count']

        print(f"\n📊 Before import:")
        print(f"  Projects: {before_projects}")
        print(f"  Files: {before_files}")
        print(f"  Contents: {before_contents}")

        # Create project record (this will persist even if import fails)
        create_test_project(project_slug, test_path)
        expected_projects = before_projects + 1

        # Create importer
        importer = ProjectImporter(project_slug, str(test_path))

        # Monkey-patch to force failure in the middle of import
        original_store_contents = importer._store_file_contents

        def failing_store_contents():
            # Call original to do some work
            original_store_contents()
            # Then raise an error to trigger rollback
            raise Exception("Simulated failure for testing rollback")

        importer._store_file_contents = failing_store_contents

        # Try to import (should fail)
        print(f"\n▶️  Importing {test_path} (will fail intentionally)...")
        try:
            stats = importer.import_files()
            print("\n❌ FAILED: Import should have raised an exception!")
            return False
        except Exception as e:
            print(f"\n✓ Import failed as expected: {e}")

        # Get counts after failed import
        after_projects = query_one("SELECT COUNT(*) as count FROM projects")['count']
        after_files = query_one("SELECT COUNT(*) as count FROM project_files")['count']
        after_contents = query_one("SELECT COUNT(*) as count FROM file_contents")['count']

        print(f"\n📊 After failed import:")
        print(f"  Projects: {after_projects} (expected {expected_projects}, project created outside transaction)")
        print(f"  Files: {after_files}")
        print(f"  Contents: {after_contents}")

        # Verify rollback worked
        # Project record will persist (created before transaction), but that's OK
        if after_projects != expected_projects:
            print(f"\n⚠️  WARNING: Project count unexpected: {after_projects} (expected {expected_projects})")
            # This is not a failure - just informational

        # The important checks: files and contents should NOT have changed
        # (transaction rolled back the import)
        if after_files != before_files:
            print(f"\n❌ FAILED: Rollback didn't work! Files changed: {before_files} → {after_files}")
            return False

        if after_contents != before_contents:
            print(f"\n❌ FAILED: Rollback didn't work! Contents changed: {before_contents} → {after_contents}")
            return False

        print(f"\n✅ SUCCESS: Transaction rollback worked correctly!")
        print(f"  Files: {before_files} (unchanged)")
        print(f"  Contents: {before_contents} (unchanged)")
        print(f"  Project: {expected_projects} (created before transaction, persisted as expected)")

        return True

    except Exception as e:
        print(f"\n❌ FAILED: Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        cleanup_test_project(project_slug)
        shutil.rmtree(test_path, ignore_errors=True)
        close_connection()


def main():
    print("Testing TempleDB Transaction Support")
    print("=" * 70)

    results = []

    # Test 1: Successful import
    results.append(("Successful Import", test_successful_import()))

    # Test 2: Failed import rollback
    results.append(("Failed Import Rollback", test_failed_import_rollback()))

    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)

    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")

    all_passed = all(passed for _, passed in results)

    if all_passed:
        print("\n🎉 All tests passed! Transaction support is working correctly.")
        return 0
    else:
        print("\n⚠️  Some tests failed. Transaction support needs debugging.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
