#!/usr/bin/env python3
"""
Test multi-agent locking and conflict detection

Converted from test_phase4_concurrent.sh

Tests:
1. Non-conflicting concurrent edits (different files)
2. Conflicting concurrent edits (same file)
3. Conflict detection and abort
4. Force overwrite strategy
5. Version number increments
6. Checkout snapshot tracking
"""

import pytest
import shutil
from pathlib import Path

from conftest import (
    checkout_project,
    commit_project,
    create_file,
    modify_file,
    query_one,
    query_all
)


@pytest.mark.concurrent
@pytest.mark.integration
def test_non_conflicting_concurrent_edits(temp_workspace: Path):
    """Test that agents editing different files can both commit successfully"""

    project_slug = "templedb"
    workspace_a = temp_workspace / "agent_a"
    workspace_b = temp_workspace / "agent_b"

    workspace_a.mkdir()
    workspace_b.mkdir()

    # Both agents checkout
    checkout_project(project_slug, workspace_a, force=True)
    checkout_project(project_slug, workspace_b, force=True)

    # Agent A edits file1
    create_file(workspace_a / "NOTES_A.md", "# Notes from Agent A\n")

    # Agent B edits file2 (different file)
    create_file(workspace_b / "NOTES_B.md", "# Notes from Agent B\n")

    # Both commit - should succeed
    result_a = commit_project(project_slug, workspace_a, "Agent A changes")
    assert result_a.returncode == 0, f"Agent A commit should succeed: {result_a.stderr}"

    result_b = commit_project(project_slug, workspace_b, "Agent B changes")
    assert result_b.returncode == 0, f"Agent B commit should succeed: {result_b.stderr}"


@pytest.mark.concurrent
@pytest.mark.integration
def test_conflicting_concurrent_edits_detected(temp_workspace: Path):
    """Test that conflict is detected when agents edit the same file"""

    project_slug = "templedb"
    workspace_a = temp_workspace / "agent_a"
    workspace_b = temp_workspace / "agent_b"

    workspace_a.mkdir()
    workspace_b.mkdir()

    # Both agents checkout fresh
    checkout_project(project_slug, workspace_a, force=True)
    checkout_project(project_slug, workspace_b, force=True)

    # Both edit SAME file
    modify_file(workspace_a / "README.md", append="\n# Feature A by Agent A\n")
    modify_file(workspace_b / "README.md", append="\n# Feature B by Agent B\n")

    # Agent A commits first - should succeed
    result_a = commit_project(project_slug, workspace_a, "Agent A feature")
    assert result_a.returncode == 0, f"Agent A commit should succeed: {result_a.stderr}"

    # Agent B commits second - should detect conflict
    result_b = commit_project(
        project_slug,
        workspace_b,
        "Agent B feature",
        strategy="abort"
    )

    # Should fail due to conflict
    assert result_b.returncode != 0, "Agent B commit should fail due to conflict"
    assert "conflict" in result_b.stderr.lower() or "conflict" in result_b.stdout.lower(), \
        "Error message should mention conflict"


@pytest.mark.concurrent
@pytest.mark.integration
def test_force_overwrite_strategy(temp_workspace: Path):
    """Test that --force allows overwriting conflicting changes"""

    project_slug = "templedb"
    workspace_a = temp_workspace / "agent_a"
    workspace_b = temp_workspace / "agent_b"

    workspace_a.mkdir()
    workspace_b.mkdir()

    # Both agents checkout
    checkout_project(project_slug, workspace_a, force=True)
    checkout_project(project_slug, workspace_b, force=True)

    # Both edit same file
    modify_file(workspace_a / "README.md", append="\n# Change A\n")
    modify_file(workspace_b / "README.md", append="\n# Change B\n")

    # Agent A commits
    result_a = commit_project(project_slug, workspace_a, "Agent A change")
    assert result_a.returncode == 0

    # Agent B force commits - should succeed
    result_b = commit_project(
        project_slug,
        workspace_b,
        "Agent B force change",
        force=True
    )
    assert result_b.returncode == 0, f"Force commit should succeed: {result_b.stderr}"


@pytest.mark.concurrent
def test_version_numbers_increment(temp_workspace: Path):
    """Test that file version numbers increment correctly after commits"""

    project_slug = "templedb"

    # Get a specific file's version
    file_row = query_one("""
        SELECT pf.id, pf.file_path, fc.version
        FROM project_files pf
        JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
        WHERE pf.project_id = (SELECT id FROM projects WHERE slug = ?)
            AND pf.file_path = 'README.md'
    """, (project_slug,))

    if not file_row:
        pytest.skip("README.md not found in project")

    initial_version = file_row['version']

    # Make a change and commit
    checkout_project(project_slug, temp_workspace, force=True)
    modify_file(temp_workspace / "README.md", append="\n# Version test\n")
    result = commit_project(project_slug, temp_workspace, "Version increment test")

    assert result.returncode == 0

    # Check version incremented
    updated_file = query_one("""
        SELECT version
        FROM file_contents
        WHERE file_id = ? AND is_current = 1
    """, (file_row['id'],))

    assert updated_file is not None
    assert updated_file['version'] > initial_version, \
        f"Version should increment from {initial_version} to {updated_file['version']}"


@pytest.mark.concurrent
@pytest.mark.slow
def test_checkout_snapshots_recorded(temp_workspace: Path):
    """Test that checkout snapshots are recorded for conflict detection"""

    project_slug = "templedb"

    # Get initial snapshot count
    initial_count = query_one("""
        SELECT COUNT(*) as count
        FROM checkout_snapshots cs
        JOIN checkouts c ON cs.checkout_id = c.id
        WHERE c.project_id = (SELECT id FROM projects WHERE slug = ?)
    """, (project_slug,))['count']

    # Perform checkout
    checkout_project(project_slug, temp_workspace, force=True)

    # Check snapshot count increased
    final_count = query_one("""
        SELECT COUNT(*) as count
        FROM checkout_snapshots cs
        JOIN checkouts c ON cs.checkout_id = c.id
        WHERE c.project_id = (SELECT id FROM projects WHERE slug = ?)
    """, (project_slug,))['count']

    assert final_count > initial_count, \
        f"Checkout should create snapshots: {initial_count} -> {final_count}"


@pytest.mark.concurrent
def test_sequential_commits_no_conflict(temp_workspace: Path):
    """Test that sequential commits from same workspace don't create false conflicts"""

    project_slug = "templedb"

    # Checkout once
    checkout_project(project_slug, temp_workspace, force=True)

    # First commit
    modify_file(temp_workspace / "README.md", append="\n# First sequential commit\n")
    result1 = commit_project(project_slug, temp_workspace, "First commit")
    assert result1.returncode == 0

    # Second commit (same workspace, no re-checkout)
    modify_file(temp_workspace / "README.md", append="\n# Second sequential commit\n")
    result2 = commit_project(project_slug, temp_workspace, "Second commit")
    assert result2.returncode == 0, \
        "Sequential commits from same workspace should not conflict"

    # Third commit
    modify_file(temp_workspace / "README.md", append="\n# Third sequential commit\n")
    result3 = commit_project(project_slug, temp_workspace, "Third commit")
    assert result3.returncode == 0, \
        "Multiple sequential commits should all succeed"
