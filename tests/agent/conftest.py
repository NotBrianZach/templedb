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

    # Read agent migrations in order. Each subsequent migration builds on
    # the previous — 073 creates core agent tables, 080 adds pending asks
    # transport, 084 adds sections + pending events transport.
    mig_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'migrations')
    for fname in ('073_add_temple_agent.sql',
                  '080_agent_pending_asks.sql',
                  '084_agent_sections.sql'):
        p = os.path.join(mig_dir, fname)
        if os.path.exists(p):
            with open(p) as f:
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
