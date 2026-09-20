#!/usr/bin/env python3
"""
Test snapshot updates after commit

Converted from test_snapshot_update.sh

Tests that snapshots are properly updated after commits to prevent
false conflicts on subsequent commits from the same workspace.

This tests the fix for Issue #1: sequential commits from the same
workspace should not trigger false conflicts.
"""

import pytest
from pathlib import Path

from conftest import (
    checkout_project,
    commit_project,
    modify_file
)


@pytest.mark.workflow
@pytest.mark.integration
def test_snapshot_updates_after_commit(temp_workspace: Path):
    """
    Test that snapshots update after commit to prevent false conflicts

    This is a regression test for Issue #1: after committing, the checkout
    snapshots should be updated so the next commit doesn't see a false conflict.
    """

    project_slug = "templedb"

    # Initial checkout
    checkout_project(project_slug, temp_workspace, force=True)

    # First commit - modify README
    modify_file(temp_workspace / "README.md", append="\n# First change\n")
    result1 = commit_project(project_slug, temp_workspace, "First commit to README")

    assert result1.returncode == 0, f"First commit should succeed: {result1.stderr}"

    # Second commit - modify README AGAIN (same workspace, no re-checkout)
    modify_file(temp_workspace / "README.md", append="\n# Second change\n")
    result2 = commit_project(project_slug, temp_workspace, "Second commit to README")

    # This should NOT show conflict - snapshots should have been updated
    assert result2.returncode == 0, \
        f"Second commit should not show false conflict: {result2.stderr}"

    # Third commit - verify still working
    modify_file(temp_workspace / "README.md", append="\n# Third change\n")
    result3 = commit_project(project_slug, temp_workspace, "Third commit to README")

    assert result3.returncode == 0, \
        f"Third commit should also succeed: {result3.stderr}"


@pytest.mark.workflow
def test_multiple_files_sequential_commits(temp_workspace: Path):
    """Test that multiple files can be edited across sequential commits"""

    project_slug = "templedb"

    checkout_project(project_slug, temp_workspace, force=True)

    # Commit 1: Edit file A
    modify_file(temp_workspace / "README.md", append="\n# Edit to README\n")
    result1 = commit_project(project_slug, temp_workspace, "Edit README")
    assert result1.returncode == 0

    # Commit 2: Edit file B
    modify_file(temp_workspace / "GETTING_STARTED.md", append="\n# Edit to guide\n")
    result2 = commit_project(project_slug, temp_workspace, "Edit guide")
    assert result2.returncode == 0

    # Commit 3: Edit both files
    modify_file(temp_workspace / "README.md", append="\n# Another README edit\n")
    modify_file(temp_workspace / "GETTING_STARTED.md", append="\n# Another guide edit\n")
    result3 = commit_project(project_slug, temp_workspace, "Edit both files")
    assert result3.returncode == 0


@pytest.mark.workflow
def test_commit_after_failed_commit(temp_workspace: Path):
    """Test that commit works after a previous commit failed"""

    project_slug = "templedb"

    checkout_project(project_slug, temp_workspace, force=True)

    # Make a change
    modify_file(temp_workspace / "README.md", append="\n# Test change\n")

    # Attempt commit with invalid strategy (should fail)
    result1 = commit_project(
        project_slug,
        temp_workspace,
        "Test commit",
        strategy="invalid_strategy"
    )

    # First commit might fail due to invalid strategy
    # (depending on CLI validation)

    # Second commit with valid params should work
    result2 = commit_project(project_slug, temp_workspace, "Valid commit")
    assert result2.returncode == 0, \
        "Commit should succeed after failed attempt"


@pytest.mark.workflow
def test_re_checkout_after_commit(temp_workspace: Path):
    """Test that re-checkout after commit works correctly"""

    project_slug = "templedb"

    # Checkout, edit, commit
    checkout_project(project_slug, temp_workspace, force=True)
    modify_file(temp_workspace / "README.md", append="\n# Initial change\n")
    result1 = commit_project(project_slug, temp_workspace, "Initial commit")
    assert result1.returncode == 0

    # Re-checkout (force)
    checkout_project(project_slug, temp_workspace, force=True)

    # Make another change
    modify_file(temp_workspace / "README.md", append="\n# After re-checkout\n")
    result2 = commit_project(project_slug, temp_workspace, "After re-checkout")
    assert result2.returncode == 0, \
        "Commit should work after re-checkout"
