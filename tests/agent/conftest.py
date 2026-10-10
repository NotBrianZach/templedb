"""Shared test setup for agent tests.

Design: the agent suite owns its OWN database file, and `db_utils` is
re-pointed at it only for the duration of `tests/agent/` by the autouse
`_agent_db` fixture below.

It used to migrate into whatever DB the root tests/conftest.py had set
up, which made it the suite's primary source of cross-contamination: at
IMPORT time (i.e. during collection, before any test runs) it created a
5-column `projects` table — no nix_build_status, no git_branch — into
the shared bootstrap DB. tests/conftest.py's `bootstrap_schema` then ran
schema.sql, whose `CREATE TABLE IF NOT EXISTS projects` silently no-ops
against that partial table, so the column stayed missing and a later
view referencing projects.nix_build_status aborted the whole script.
That single interaction produced 32 "no such column: nix_build_status"
setup errors and 3 "projects has no column named git_branch" failures in
files that pass 100% on their own. Verified: test_safe_queries.py is
18/18 alone and 18 passed + 14 errors when run alongside tests/agent.

Re-pointing rather than env-at-import-time is what keeps that from
recurring: an import-time `os.environ['TEMPLEDB_PATH'] = ...` is global
and leaks to every module collected afterwards, whereas the fixture's
swap is scoped and restored.

The old flow deleted `agent.*` and `db_utils.*` from sys.modules to
force re-imports with the new env var — which worked from a plain
`python -c ...` but broke under pytest, because pytest caches loader
state per module and doesn't invalidate on sys.modules deletion. That
surgery is unnecessary: db_utils reads its module-level DB_PATH when it
opens a connection, not at import, so assigning DB_PATH and dropping the
cached handle is enough (the root conftest's restore_test_db_path() has
always relied on exactly that).

Callers still call `setup_test_db()` / `teardown_test_db()` — they
now just ensure the DB is initialised (first call migrates) and
unlink on shutdown (last call)."""
import atexit
import os
import sys
import sqlite3
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))


def _init_test_db():
    """Create and migrate a DB owned solely by the agent suite.

    Deliberately does NOT read or write TEMPLEDB_PATH: this runs at
    import/collection time, so touching the env or the root session DB
    here is what leaked into unrelated modules. `_agent_db` does the
    pointing, per-test-run and reversibly.
    """
    fd, path = tempfile.mkstemp(suffix='.sqlite', prefix='templedb-agent-tests-')
    os.close(fd)

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


atexit.register(_cleanup)


@pytest.fixture(scope='package', autouse=True)
def _agent_db():
    """Point TEMPLEDB_PATH and db_utils at the agent DB for these tests only.

    Both are set because the two are read by different consumers: env for
    anything that re-resolves the path (including subprocesses), and
    db_utils.DB_PATH for the in-process connection pool, which captured
    its value at import. close_connection() drops the cached thread-local
    handle so the next get_connection() actually opens the new file.

    The previous values are restored on the way out. Note the old
    _cleanup() instead did `os.environ.pop('TEMPLEDB_PATH')`, which the
    root conftest warns about explicitly: with the variable absent,
    config._get_db_path() falls through to the user's real database, so
    unsetting it points everything that follows at production.
    """
    prev_env = os.environ.get('TEMPLEDB_PATH')
    os.environ['TEMPLEDB_PATH'] = _test_db_path

    try:
        import db_utils
    except ImportError:
        db_utils = None
        prev_db_path = None
    else:
        prev_db_path = getattr(db_utils, 'DB_PATH', None)
        db_utils.close_connection()
        db_utils.DB_PATH = _test_db_path

    try:
        yield _test_db_path
    finally:
        if db_utils is not None:
            db_utils.close_connection()
            if prev_db_path is not None:
                db_utils.DB_PATH = prev_db_path
        if prev_env is not None:
            os.environ['TEMPLEDB_PATH'] = prev_env
        else:
            os.environ.pop('TEMPLEDB_PATH', None)


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
