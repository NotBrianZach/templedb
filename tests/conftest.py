#!/usr/bin/env python3
"""
Pytest configuration and shared fixtures for TempleDB tests

Provides common test utilities, fixtures, and helper functions.
"""

import os
import sys
import shutil
import tempfile
import sqlite3
import subprocess
from pathlib import Path
from typing import Generator, Dict, Any

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from db_utils import query_one, query_all, execute, get_connection, close_connection


# ============================================================================
# Test Configuration
# ============================================================================

@pytest.fixture(scope="session")
def db_path() -> str:
    """Get database path"""
    return str(Path.home() / ".local" / "share" / "templedb" / "templedb.sqlite")


@pytest.fixture(scope="session")
def templedb_cli() -> str:
    """Get path to templedb CLI"""
    return str(Path(__file__).parent.parent / "templedb")


# ============================================================================
# Database Fixtures
# ============================================================================

@pytest.fixture
def db_connection(db_path: str) -> Generator[sqlite3.Connection, None, None]:
    """Provide a database connection that auto-rolls back"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    yield conn
    conn.rollback()  # Always rollback to not affect database
    conn.close()


@pytest.fixture
def clean_db_session():
    """Ensure database session is clean"""
    close_connection()
    yield
    close_connection()


# ============================================================================
# Test Project Fixtures
# ============================================================================

@pytest.fixture
def temp_project_dir() -> Generator[Path, None, None]:
    """Create a temporary project directory with sample files"""
    test_dir = tempfile.mkdtemp(prefix='templedb_test_')
    test_path = Path(test_dir)

    # Create sample files
    (test_path / 'README.md').write_text('# Test Project\n\nThis is a test.\n')
    (test_path / 'test.py').write_text('print("hello")\n')
    (test_path / 'test.txt').write_text('test content\n')
    (test_path / 'subdir').mkdir()
    (test_path / 'subdir' / 'nested.py').write_text('def foo():\n    pass\n')

    yield test_path

    # Cleanup
    shutil.rmtree(test_path, ignore_errors=True)


@pytest.fixture
def temp_workspace() -> Generator[Path, None, None]:
    """Create a temporary workspace directory"""
    workspace = tempfile.mkdtemp(prefix='templedb_workspace_')
    yield Path(workspace)
    shutil.rmtree(workspace, ignore_errors=True)


@pytest.fixture
def test_project(temp_project_dir: Path) -> Generator[Dict[str, Any], None, None]:
    """Create and cleanup a test project in database"""
    project_slug = f"test_{os.getpid()}"

    # Create project record
    execute("""
        INSERT INTO projects (slug, name, repo_url, git_branch)
        VALUES (?, ?, ?, 'main')
    """, (project_slug, f"Test Project {project_slug}", str(temp_project_dir)))

    project = query_one("SELECT * FROM projects WHERE slug = ?", (project_slug,))

    yield {
        'slug': project_slug,
        'id': project['id'],
        'path': temp_project_dir,
        'name': project['name']
    }

    # Cleanup
    if project:
        execute("DELETE FROM file_contents WHERE file_id IN (SELECT id FROM project_files WHERE project_id = ?)", (project['id'],))
        execute("DELETE FROM project_files WHERE project_id = ?", (project['id'],))
        execute("DELETE FROM vcs_commits WHERE project_id = ?", (project['id'],))
        execute("DELETE FROM vcs_branches WHERE project_id = ?", (project['id'],))
        execute("DELETE FROM projects WHERE id = ?", (project['id'],))


# ============================================================================
# CLI Helper Functions
# ============================================================================

def run_templedb_cmd(args: list, check: bool = True) -> subprocess.CompletedProcess:
    """
    Run templedb CLI command

    Args:
        args: Command arguments (e.g., ['project', 'list'])
        check: Raise exception on non-zero exit code

    Returns:
        CompletedProcess with stdout, stderr, returncode
    """
    templedb_path = Path(__file__).parent.parent / "templedb"
    cmd = [str(templedb_path)] + args

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False
    )

    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, cmd, result.stdout, result.stderr
        )

    return result


def checkout_project(project_slug: str, workspace: Path, force: bool = True) -> None:
    """Checkout a project to workspace"""
    args = ['project', 'checkout', project_slug, str(workspace)]
    if force:
        args.append('--force')
    run_templedb_cmd(args)


def commit_project(
    project_slug: str,
    workspace: Path,
    message: str,
    force: bool = False,
    strategy: str = None
) -> subprocess.CompletedProcess:
    """
    Commit changes from workspace

    Returns:
        CompletedProcess (check returncode for success/failure)
    """
    args = ['project', 'commit', project_slug, str(workspace), '-m', message]
    if force:
        args.append('--force')
    if strategy:
        args.extend(['--strategy', strategy])

    return run_templedb_cmd(args, check=False)


# ============================================================================
# Database Query Helpers
# ============================================================================

def get_project_stats(project_slug: str) -> Dict[str, int]:
    """Get file and commit counts for a project"""
    project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
    if not project:
        return {'files': 0, 'commits': 0, 'contents': 0}

    files = query_one(
        "SELECT COUNT(*) as count FROM project_files WHERE project_id = ?",
        (project['id'],)
    )['count']

    commits = query_one(
        "SELECT COUNT(*) as count FROM vcs_commits WHERE project_id = ?",
        (project['id'],)
    )['count']

    contents = query_one(
        """
        SELECT COUNT(*) as count FROM file_contents
        WHERE file_id IN (SELECT id FROM project_files WHERE project_id = ?)
        """,
        (project['id'],)
    )['count']

    return {'files': files, 'commits': commits, 'contents': contents}


def get_latest_commit(project_slug: str) -> Dict[str, Any]:
    """Get latest commit for a project"""
    return query_one("""
        SELECT c.*
        FROM vcs_commits c
        JOIN projects p ON c.project_id = p.id
        WHERE p.slug = ?
        ORDER BY c.commit_timestamp DESC
        LIMIT 1
    """, (project_slug,))


def count_table_rows(table_name: str) -> int:
    """Count rows in a table"""
    result = query_one(f"SELECT COUNT(*) as count FROM {table_name}")
    return result['count'] if result else 0


# ============================================================================
# File System Helpers
# ============================================================================

def create_file(path: Path, content: str) -> None:
    """Create a file with content"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def modify_file(path: Path, append: str = None, content: str = None) -> None:
    """Modify a file by appending or replacing content"""
    if append:
        with open(path, 'a') as f:
            f.write(append)
    elif content:
        path.write_text(content)


def delete_file(path: Path) -> None:
    """Delete a file if it exists"""
    if path.exists():
        path.unlink()


# ============================================================================
# Assertion Helpers
# ============================================================================

def assert_file_exists(path: Path, message: str = None) -> None:
    """Assert that a file exists"""
    if not path.exists():
        msg = message or f"File should exist: {path}"
        pytest.fail(msg)


def assert_file_not_exists(path: Path, message: str = None) -> None:
    """Assert that a file does not exist"""
    if path.exists():
        msg = message or f"File should not exist: {path}"
        pytest.fail(msg)


def assert_file_contains(path: Path, text: str, message: str = None) -> None:
    """Assert that a file contains specific text"""
    if not path.exists():
        pytest.fail(f"File does not exist: {path}")

    content = path.read_text()
    if text not in content:
        msg = message or f"File should contain '{text}': {path}"
        pytest.fail(msg)
