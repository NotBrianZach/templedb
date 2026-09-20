#!/usr/bin/env python3
"""
Test TempleDB database constraints

Validates that all uniqueness constraints and foreign keys are enforced correctly.

Converted to pytest and using common fixtures from conftest.py
"""

import pytest
import sqlite3
from conftest import db_connection, db_path, query_one, query_all


# ============================================================================
# Constraint Violation Tests
# ============================================================================

@pytest.mark.constraints
@pytest.mark.unit
def test_duplicate_project_slugs_rejected(db_connection: sqlite3.Connection):
    """Test that duplicate project slugs are rejected"""

    with pytest.raises(sqlite3.IntegrityError):
        db_connection.execute("""
            INSERT INTO projects (slug, name)
            SELECT slug, 'Duplicate ' || name
            FROM projects
            LIMIT 1
        """)


@pytest.mark.constraints
@pytest.mark.unit
def test_duplicate_file_paths_within_project_rejected(db_connection: sqlite3.Connection):
    """Test that duplicate file paths within a project are rejected"""

    with pytest.raises(sqlite3.IntegrityError):
        db_connection.execute("""
            INSERT INTO project_files (project_id, file_path, file_type_id)
            SELECT project_id, file_path, file_type_id
            FROM project_files
            LIMIT 1
        """)


@pytest.mark.constraints
@pytest.mark.unit
def test_duplicate_branch_names_rejected(db_connection: sqlite3.Connection):
    """Test that duplicate branch names within a project are rejected"""

    with pytest.raises(sqlite3.IntegrityError):
        db_connection.execute("""
            INSERT INTO vcs_branches (project_id, branch_name)
            SELECT project_id, branch_name
            FROM vcs_branches
            WHERE branch_name IS NOT NULL
            LIMIT 1
        """)


@pytest.mark.constraints
@pytest.mark.unit
def test_duplicate_environment_names_rejected(db_connection: sqlite3.Connection):
    """Test that duplicate environment names within a project are rejected"""

    with pytest.raises(sqlite3.IntegrityError):
        db_connection.execute("""
            INSERT INTO nix_environments (project_id, env_name)
            SELECT project_id, env_name
            FROM nix_environments
            LIMIT 1
        """)


@pytest.mark.constraints
@pytest.mark.unit
def test_multiple_current_versions_rejected(db_connection: sqlite3.Connection):
    """Test that multiple current versions per file are rejected"""

    with pytest.raises(sqlite3.IntegrityError):
        db_connection.execute("""
            INSERT INTO file_contents (file_id, content_hash, file_size_bytes, is_current)
            SELECT file_id, content_hash, file_size_bytes, 1
            FROM file_contents
            WHERE is_current = 1
            LIMIT 1
        """)


@pytest.mark.constraints
@pytest.mark.unit
def test_file_self_dependency_rejected(db_connection: sqlite3.Connection):
    """Test that file self-dependencies are rejected"""

    with pytest.raises(sqlite3.IntegrityError):
        db_connection.execute("""
            INSERT INTO file_dependencies (parent_file_id, dependency_file_id, dependency_type)
            SELECT id, id, 'import'
            FROM project_files
            LIMIT 1
        """)


@pytest.mark.constraints
@pytest.mark.unit
def test_duplicate_deployment_targets_rejected(db_connection: sqlite3.Connection):
    """Test that duplicate deployment targets are rejected"""

    with pytest.raises(sqlite3.IntegrityError):
        db_connection.execute("""
            INSERT INTO deployment_targets (project_id, target_name, target_type)
            SELECT project_id, target_name, target_type
            FROM deployment_targets
            LIMIT 1
        """)


@pytest.mark.constraints
@pytest.mark.unit
def test_duplicate_content_hashes_rejected(db_connection: sqlite3.Connection):
    """Test that duplicate content blobs (by hash) are rejected"""

    with pytest.raises(sqlite3.IntegrityError):
        db_connection.execute("""
            INSERT INTO content_blobs (hash_sha256, content_type, file_size_bytes)
            SELECT hash_sha256, content_type, file_size_bytes
            FROM content_blobs
            LIMIT 1
        """)


# ============================================================================
# Data Validation Tests
# ============================================================================

@pytest.mark.constraints
@pytest.mark.integration
def test_no_duplicate_file_paths_in_projects():
    """Validate that no duplicate file paths exist within projects"""

    duplicates = query_all("""
        SELECT project_id, file_path, COUNT(*) as count
        FROM project_files
        GROUP BY project_id, file_path
        HAVING COUNT(*) > 1
    """)

    assert len(duplicates) == 0, \
        f"Found {len(duplicates)} duplicate file paths within projects"


@pytest.mark.constraints
@pytest.mark.integration
def test_no_multiple_current_versions():
    """Validate that no files have multiple current versions"""

    duplicates = query_all("""
        SELECT file_id, COUNT(*) as count
        FROM file_contents
        WHERE is_current = 1
        GROUP BY file_id
        HAVING COUNT(*) > 1
    """)

    assert len(duplicates) == 0, \
        f"Found {len(duplicates)} files with multiple current versions"


@pytest.mark.constraints
@pytest.mark.integration
def test_no_duplicate_project_slugs():
    """Validate that no duplicate project slugs exist"""

    duplicates = query_all("""
        SELECT slug, COUNT(*) as count
        FROM projects
        GROUP BY slug
        HAVING COUNT(*) > 1
    """)

    assert len(duplicates) == 0, \
        f"Found {len(duplicates)} duplicate project slugs"


@pytest.mark.constraints
@pytest.mark.integration
def test_no_duplicate_branch_names():
    """Validate that no duplicate branch names exist within projects"""

    duplicates = query_all("""
        SELECT project_id, branch_name, COUNT(*) as count
        FROM vcs_branches
        GROUP BY project_id, branch_name
        HAVING COUNT(*) > 1
    """)

    assert len(duplicates) == 0, \
        f"Found {len(duplicates)} duplicate branch names within projects"


@pytest.mark.constraints
@pytest.mark.integration
def test_all_foreign_keys_valid():
    """Validate that all foreign key relationships are valid"""

    # Check project_files -> projects
    orphans = query_all("""
        SELECT pf.id, pf.project_id
        FROM project_files pf
        LEFT JOIN projects p ON pf.project_id = p.id
        WHERE p.id IS NULL
        LIMIT 10
    """)

    assert len(orphans) == 0, \
        f"Found {len(orphans)} project_files with invalid project_id"

    # Check file_contents -> project_files
    orphans = query_all("""
        SELECT fc.id, fc.file_id
        FROM file_contents fc
        LEFT JOIN project_files pf ON fc.file_id = pf.id
        WHERE pf.id IS NULL
        LIMIT 10
    """)

    assert len(orphans) == 0, \
        f"Found {len(orphans)} file_contents with invalid file_id"


@pytest.mark.constraints
@pytest.mark.integration
def test_all_is_current_flags_consistent():
    """Validate that is_current flags are consistent"""

    # Each file should have at most one current version
    result = query_one("""
        SELECT COUNT(*) as count
        FROM (
            SELECT file_id, COUNT(*) as current_count
            FROM file_contents
            WHERE is_current = 1
            GROUP BY file_id
            HAVING COUNT(*) > 1
        )
    """)

    assert result['count'] == 0, \
        f"Found {result['count']} files with multiple is_current=1 versions"
