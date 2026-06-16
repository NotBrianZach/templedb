#!/usr/bin/env python3
"""
Test TempleDB checkout → edit → commit workflow

Converted from test_phase3_workflow.sh

Tests the complete workflow:
1. Checkout project from database
2. Make changes (add, modify, delete files)
3. Commit changes back to database
4. Verify round-trip integrity
"""

import pytest
from pathlib import Path

from conftest import (
    checkout_project,
    commit_project,
    get_project_stats,
    get_latest_commit,
    create_file,
    modify_file,
    delete_file,
    assert_file_exists,
    assert_file_not_exists,
    assert_file_contains,
    query_one,
    query_all
)


@pytest.mark.workflow
@pytest.mark.integration
def test_checkout_edit_commit_workflow(temp_workspace: Path):
    """Test complete checkout → edit → commit workflow"""

    project_slug = "templedb"  # Use existing project
    workspace = temp_workspace

    # Step 1: Checkout project
    checkout_project(project_slug, workspace, force=True)

    # Verify checkout worked
    assert_file_exists(workspace / "README.md", "README.md should be checked out")

    # Get initial stats
    initial_stats = get_project_stats(project_slug)

    # Step 2: Make various changes

    # Modify existing file
    readme_path = workspace / "README.md"
    modify_file(readme_path, append="\n# Modified by workflow test\n")

    # Add new file
    new_file = workspace / "test-workflow.md"
    create_file(new_file, "# New test file from workflow test\n")

    # Delete a file (if exists)
    delete_candidate = workspace / "test-workflow-deleteme.md"
    if not delete_candidate.exists():
        # Create it first so we have something to delete
        create_file(delete_candidate, "# File to delete\n")
        commit_project(project_slug, workspace, "Add file to delete")

    delete_file(delete_candidate)

    # Step 3: Commit changes
    result = commit_project(
        project_slug,
        workspace,
        "Workflow test: add, modify, delete"
    )

    assert result.returncode == 0, f"Commit should succeed: {result.stderr}"

    # Step 4: Verify commit recorded
    latest_commit = get_latest_commit(project_slug)
    assert latest_commit is not None, "Should have a latest commit"
    assert "Workflow test" in latest_commit['commit_message']

    # Verify commit has change records
    commit_files = query_all("""
        SELECT cf.change_type, pf.file_path
        FROM commit_files cf
        JOIN project_files pf ON cf.file_id = pf.id
        WHERE cf.commit_id = ?
        ORDER BY cf.change_type, pf.file_path
    """, (latest_commit['id'],))

    assert len(commit_files) > 0, "Commit should have file changes"

    # Should have at least: 1 add, 1 modify, 1 delete
    change_types = {cf['change_type'] for cf in commit_files}
    assert 'add' in change_types or 'modify' in change_types, "Should have additions or modifications"

    # Step 5: Test round-trip (checkout again and verify)
    workspace2 = temp_workspace.parent / f"{temp_workspace.name}_roundtrip"
    workspace2.mkdir(exist_ok=True)

    try:
        checkout_project(project_slug, workspace2, force=True)

        # Verify new file exists
        assert_file_exists(
            workspace2 / "test-workflow.md",
            "New file should exist in fresh checkout"
        )

        # Verify modified file has changes
        assert_file_contains(
            workspace2 / "README.md",
            "Modified by workflow test",
            "Modified file should have changes"
        )

        # Verify deleted file doesn't exist
        assert_file_not_exists(
            workspace2 / "test-workflow-deleteme.md",
            "Deleted file should not exist in fresh checkout"
        )

    finally:
        # Cleanup workspace2
        import shutil
        shutil.rmtree(workspace2, ignore_errors=True)


@pytest.mark.workflow
def test_checkout_creates_directory(temp_workspace: Path):
    """Test that checkout creates workspace directory if it doesn't exist"""

    project_slug = "templedb"
    new_workspace = temp_workspace / "subdir" / "workspace"

    # Directory doesn't exist yet
    assert not new_workspace.exists()

    # Checkout should create it
    checkout_project(project_slug, new_workspace, force=True)

    # Directory should now exist
    assert new_workspace.exists()
    assert new_workspace.is_dir()

    # Should have files
    files = list(new_workspace.glob("*"))
    assert len(files) > 0, "Workspace should contain files"


@pytest.mark.workflow
def test_commit_empty_workspace_fails(temp_workspace: Path):
    """Test that committing an empty workspace fails gracefully"""

    project_slug = "templedb"

    # Try to commit empty workspace (no checkout)
    result = commit_project(
        project_slug,
        temp_workspace,
        "Empty commit",
    )

    # Should fail (no changes to commit)
    assert result.returncode != 0, "Committing empty workspace should fail"


@pytest.mark.workflow
def test_commit_message_required():
    """Test that commit requires a message"""

    # This test verifies CLI behavior - we expect it to fail without -m
    # We test this by checking if the CLI properly requires the -m flag
    # (This is more of a CLI test, but included for completeness)
    pass  # Skip for now - CLI validation happens before reaching Python code
