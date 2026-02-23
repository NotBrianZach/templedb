#!/usr/bin/env python3
"""
TempleDB Database Utilities
Provides connection pooling and query optimization
"""

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

DB_PATH = os.environ.get(
    'TEMPLEDB_PATH',
    os.path.expanduser("~/.local/share/templedb/templedb.sqlite")
)

# Thread-local storage for connections
_thread_local = threading.local()


def get_connection() -> sqlite3.Connection:
    """Get thread-local database connection (connection pooling)"""
    if not hasattr(_thread_local, 'connection'):
        _thread_local.connection = sqlite3.connect(DB_PATH)
        _thread_local.connection.row_factory = sqlite3.Row
        # Enable performance optimizations
        _thread_local.connection.execute("PRAGMA journal_mode=WAL")
        _thread_local.connection.execute("PRAGMA synchronous=NORMAL")
        _thread_local.connection.execute("PRAGMA cache_size=-64000")  # 64MB cache
        _thread_local.connection.execute("PRAGMA temp_store=MEMORY")
        _thread_local.connection.execute("PRAGMA mmap_size=268435456")  # 256MB mmap
    return _thread_local.connection


def close_connection():
    """Close thread-local connection"""
    if hasattr(_thread_local, 'connection'):
        _thread_local.connection.close()
        delattr(_thread_local, 'connection')


@contextmanager
def transaction():
    """Context manager for database transactions"""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def query_one(sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    """Execute query and return single row as dict"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    row = cursor.fetchone()
    return dict(row) if row else None


def query_all(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Execute query and return all rows as list of dicts"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    return [dict(row) for row in cursor.fetchall()]


def execute(sql: str, params: tuple = (), commit: bool = True) -> int:
    """Execute statement and return lastrowid

    Args:
        sql: SQL statement to execute
        params: Parameters for the statement
        commit: Whether to auto-commit (default True for backward compatibility)
                Set to False when using transaction() context manager

    Returns:
        Last inserted row ID
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    if commit:
        conn.commit()
    return cursor.lastrowid


def executemany(sql: str, params_list: List[tuple], commit: bool = True) -> None:
    """Execute statement with multiple parameter sets

    Args:
        sql: SQL statement to execute
        params_list: List of parameter tuples
        commit: Whether to auto-commit (default True for backward compatibility)
                Set to False when using transaction() context manager
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.executemany(sql, params_list)
    if commit:
        conn.commit()


# Prepared statement cache
_prepared_statements = {}


def query_prepared(name: str, sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    """Execute prepared query (cached)"""
    # Note: SQLite doesn't have true prepared statements like PostgreSQL,
    # but we cache the SQL string for consistency
    if name not in _prepared_statements:
        _prepared_statements[name] = sql
    return query_all(_prepared_statements[name], params)


# Common queries (optimized and cached)

def get_project_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """Get project by slug (cached query)"""
    return query_one(
        "SELECT * FROM projects WHERE slug = ? LIMIT 1",
        (slug,)
    )


def get_environment(project_slug: str, env_name: str) -> Optional[Dict[str, Any]]:
    """Get environment configuration (optimized)"""
    env = query_one("""
        SELECT
            ne.id,
            ne.project_id,
            p.slug AS project_slug,
            p.name AS project_name,
            p.repo_url,
            ne.env_name,
            ne.description,
            ne.base_packages,
            ne.target_packages,
            ne.multi_packages,
            ne.profile,
            ne.runScript
        FROM nix_environments ne
        JOIN projects p ON ne.project_id = p.id
        WHERE p.slug = ? AND ne.env_name = ? AND ne.is_active = 1
        LIMIT 1
    """, (project_slug, env_name))

    if not env:
        return None

    # Get environment variables in single query
    env['variables'] = query_all("""
        SELECT var_name, var_value, description
        FROM nix_env_variables
        WHERE environment_id = ?
        ORDER BY var_name
    """, (env['id'],))

    return env


def list_projects() -> List[Dict[str, Any]]:
    """List all projects with file counts (optimized)"""
    return query_all("""
        SELECT
            p.slug,
            p.name,
            p.repo_url,
            COUNT(pf.id) as file_count,
            SUM(pf.lines_of_code) as total_lines
        FROM projects p
        LEFT JOIN project_files pf ON pf.project_id = p.id
        GROUP BY p.id, p.slug, p.name, p.repo_url
        ORDER BY p.slug
    """)


def list_environments(project_slug: Optional[str] = None) -> List[Dict[str, Any]]:
    """List environments (optimized)"""
    if project_slug:
        return query_all("""
            SELECT
                env_name,
                description,
                json_array_length(base_packages) as package_count,
                (SELECT COUNT(*) FROM nix_env_sessions WHERE environment_id = ne.id) as session_count
            FROM nix_environments ne
            JOIN projects p ON ne.project_id = p.id
            WHERE p.slug = ? AND ne.is_active = 1
            ORDER BY env_name
        """, (project_slug,))
    else:
        return query_all("""
            SELECT
                p.slug as project_slug,
                ne.env_name,
                ne.description,
                json_array_length(ne.base_packages) as package_count,
                (SELECT COUNT(*) FROM nix_env_sessions WHERE environment_id = ne.id) as session_count
            FROM nix_environments ne
            JOIN projects p ON ne.project_id = p.id
            WHERE ne.is_active = 1
            ORDER BY p.slug, ne.env_name
        """)


# Batch operations for performance

def batch_insert_files(files: List[Dict[str, Any]]):
    """Batch insert files (much faster than individual inserts)"""
    if not files:
        return

    conn = get_connection()
    cursor = conn.cursor()

    # Prepare data
    values = [
        (
            f.get('project_id'),
            f.get('file_path'),
            f.get('component_name'),
            f.get('file_type_id'),
            f.get('description'),
            f.get('lines_of_code', 0),
            f.get('status', 'active')
        )
        for f in files
    ]

    cursor.executemany("""
        INSERT INTO project_files
        (project_id, file_path, component_name, file_type_id, description, lines_of_code, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, values)

    conn.commit()


# Performance monitoring

def get_db_stats() -> Dict[str, Any]:
    """Get database performance statistics"""
    conn = get_connection()
    stats = {}

    # Database size
    result = query_one("SELECT page_count * page_size as size FROM pragma_page_count(), pragma_page_size()")
    stats['size_bytes'] = result['size'] if result else 0
    stats['size_mb'] = stats['size_bytes'] / (1024 * 1024)

    # Table counts
    stats['tables'] = {}
    tables = ['projects', 'project_files', 'nix_environments', 'vcs_commits', 'vcs_branches']
    for table in tables:
        result = query_one(f"SELECT COUNT(*) as count FROM {table}")
        stats['tables'][table] = result['count'] if result else 0

    return stats


def vacuum_db():
    """Vacuum database to reclaim space and optimize"""
    conn = get_connection()
    conn.execute("VACUUM")
    conn.execute("ANALYZE")


def check_integrity() -> bool:
    """Check database integrity"""
    result = query_one("PRAGMA integrity_check")
    return result and result.get('integrity_check') == 'ok'
