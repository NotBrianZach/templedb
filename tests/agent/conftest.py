"""Shared test setup for agent tests."""
import os
import sys
import sqlite3
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

_test_db_path = None


def setup_test_db():
    """Create a temporary DB with agent tables and required parent tables."""
    global _test_db_path
    if _test_db_path and os.path.exists(_test_db_path):
        return _test_db_path

    fd, path = tempfile.mkstemp(suffix='.sqlite')
    os.close(fd)
    os.environ['TEMPLEDB_PATH'] = path

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")

    # Create minimal projects table (FK target for agent_sessions)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT,
            repo_url TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Read agent migration
    migration_path = os.path.join(os.path.dirname(__file__), '..', '..', 'migrations', '073_add_temple_agent.sql')
    with open(migration_path) as f:
        conn.executescript(f.read())
    conn.close()

    # Force reimport of db_utils with new path
    for mod in list(sys.modules.keys()):
        if mod.startswith('db_utils') or mod.startswith('agent'):
            del sys.modules[mod]

    _test_db_path = path
    return path


def teardown_test_db():
    """Clean up the test database."""
    global _test_db_path
    if _test_db_path and os.path.exists(_test_db_path):
        os.unlink(_test_db_path)
        _test_db_path = None
    os.environ.pop('TEMPLEDB_PATH', None)
