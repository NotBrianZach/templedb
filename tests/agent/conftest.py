"""Shared test setup for agent tests.

Design: `TEMPLEDB_PATH` is set at conftest IMPORT TIME (before any
test module runs, and before pytest's import machinery touches
`db_utils` or `agent.*`). That way when tests do `from agent.store
import X`, db_utils sees our test-only DB from its very first
connection and no import-cache surgery is needed.

The old flow deleted `agent.*` and `db_utils.*` from sys.modules to
force re-imports with the new env var — which worked from a plain
`python -c ...` but broke under pytest, because pytest caches loader
state per module and doesn't invalidate on sys.modules deletion. The
resulting `ModuleNotFoundError: No module named 'agent.store'` was
hitting every test in `tests/agent/`.

Callers still call `setup_test_db()` / `teardown_test_db()` — they
now just ensure the DB is initialised (first call migrates) and
unlink on shutdown (last call)."""
import atexit
import os
import sys
import sqlite3
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def _init_test_db():
    """Apply agent migrations to whatever DB the root tests/conftest.py
    already set up. Called ONCE at agent conftest import time.

    If TEMPLEDB_PATH isn't set (agent conftest imported directly, no
    root conftest bootstrapping), create a temp DB here as a fallback."""
    path = os.environ.get('TEMPLEDB_PATH')
    if not path:
        fd, path = tempfile.mkstemp(suffix='.sqlite')
        os.close(fd)
        os.environ['TEMPLEDB_PATH'] = path

    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys=ON")

    # FK target for agent_sessions.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            name TEXT,
            repo_url TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    # Agent migrations, in order.
    mig_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'migrations')
    for fname in ('073_add_temple_agent.sql',
                  '080_agent_pending_asks.sql',
                  '084_agent_sections.sql',
                  '085_agent_user_edits.sql',
                  '094_tool_calls.sql'):
        p = os.path.join(mig_dir, fname)
        if os.path.exists(p):
            with open(p) as f:
                conn.executescript(f.read())
    conn.close()
    return path


_test_db_path = _init_test_db()


def _cleanup():
    global _test_db_path
    if _test_db_path and os.path.exists(_test_db_path):
        try:
            os.unlink(_test_db_path)
        except OSError:
            pass
        _test_db_path = None
    os.environ.pop('TEMPLEDB_PATH', None)


atexit.register(_cleanup)


def setup_test_db():
    """Reset shared test DB rowsets so each test class starts fresh.
    The FILE is shared across the session (pytest needs stable imports),
    but rowsets are wiped between test classes — mirrors what the old
    conftest achieved via `sys.modules` deletion, without the fragility.
    Order matters (children before parents due to FK constraints).

    We also close db_utils's thread-local connection if it exists, so
    the next `get_connection()` call opens a fresh handle that sees
    the newly-empty rowsets under WAL (avoids transaction-snapshot
    staleness where the cached connection was mid-txn when we wiped)."""
    conn = sqlite3.connect(_test_db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    for table in ("agent_user_edits",
                  "agent_session_sections",
                  "agent_pending_events",
                  "agent_pending_asks",
                  "agent_session_notes",
                  "agent_work_log",
                  "tool_calls",
                  "agent_events",
                  "agent_messages",
                  "agent_runs",
                  "agent_sessions",
                  "projects"):
        try:
            conn.execute(f"DELETE FROM {table}")
        except sqlite3.OperationalError:
            pass  # table doesn't exist in this build; harmless
    conn.commit()
    conn.close()
    # Invalidate the cached thread-local connection so tests see a
    # fresh snapshot of the just-cleared tables.
    try:
        import db_utils as _du  # already-imported by prior test class
        if hasattr(_du, "_thread_local") and hasattr(_du._thread_local, "connection"):
            try:
                _du._thread_local.connection.close()
            except Exception:
                pass
            del _du._thread_local.connection
    except ImportError:
        pass
    return _test_db_path


def teardown_test_db():
    """Kept for API compatibility. Actual cleanup happens at exit."""
    pass
