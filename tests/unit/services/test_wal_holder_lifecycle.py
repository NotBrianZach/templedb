"""Who may hold a WAL snapshot, and for how long.

test_wal_size_budget.py covers *reporting* a bloated -wal. This covers
not producing one.

Two mechanisms bound the WAL from inside this codebase: statements get
finalized (so no read transaction lingers) and connections have a
bounded life (so snapshots not yet traced to a leak still go away).
Both lived on MCPServer, and both were inert in `ai mcp daemon` --
the one process that outlives every CLI invocation and therefore the
only one able to accumulate an old snapshot:

  * The daemon assigned `_mcp_server._db_conn = db` directly. The
    retirement check returns early unless `_db_conn_opened_at` is set,
    and a bare assignment never set it, so the 60s lifetime bound was a
    no-op exactly where its own docstring says it was needed.
  * That connection was also shared by every request thread of a
    ThreadedHTTPServer, along with the single `_db_cursor` slot the
    cursor-finalizing fix tracks -- so the finalizer could close a
    cursor another thread was still reading.
  * HookEngine held the same connection for the life of the daemon and
    opened an un-closed cursor on it per refresh.
  * Nothing ever ran a TRUNCATE checkpoint, and an automatic (PASSIVE)
    one never shrinks the file. 9.1 GB in 2026-09, 4.0 GB in 2026-10.
"""
import os
import sqlite3
import sys
import threading
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest


JOURNAL_SIZE_LIMIT = 64 * 1024 * 1024


@pytest.fixture
def wal_db(tmp_path):
    """A real WAL-mode database with one table and room to grow."""
    path = tmp_path / "templedb.sqlite"
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, blob TEXT)")
    conn.execute(
        "CREATE TABLE projects (slug TEXT, repo_url TEXT)")
    conn.executemany(
        "INSERT INTO projects (slug, repo_url) VALUES (?, ?)",
        [("templedb", "git@github.com:z/templedb.git"),
         ("bza", "git@github.com:z/bza.git"),
         ("no-url", None)])
    conn.commit()
    conn.close()
    return path


def _grow_wal(path, rows=200):
    """Append frames and RETURN THE OPEN CONNECTION.

    The caller has to keep it open. Closing the last connection to a
    WAL database checkpoints and unlinks the -wal, so a helper that
    tidied up after itself would hand back a database with nothing to
    reclaim -- which is not the state under test.
    """
    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")  # don't drain it for us
    conn.executemany(
        "INSERT INTO t (blob) VALUES (?)", [("x" * 2000,) for _ in range(rows)])
    conn.commit()
    return conn


def _bare_server():
    """An MCPServer with only its connection machinery initialized.

    __init__ also builds a ProjectRepository and an LLM context against
    the configured database, which these tests have no use for; the
    connection state is the whole subject here.
    """
    from mcp_server import MCPServer
    srv = MCPServer.__new__(MCPServer)
    srv._db_state = threading.local()
    return srv


# ─────────────────────────────────────────────────────────────────────────
# The regression: a directly-assigned connection is never retired
# ─────────────────────────────────────────────────────────────────────────

def test_connections_handed_out_carry_an_age_stamp(wal_db):
    """Retirement keys off _db_conn_opened_at, so the accessor must set it."""
    srv = _bare_server()
    with patch("mcp_server.DB_PATH", str(wal_db)):
        srv._get_db_connection()
    assert srv._db_conn is not None
    assert srv._db_conn_opened_at is not None, \
        "an un-stamped connection is one retirement will never reclaim"


def test_an_unstamped_connection_is_never_retired(wal_db):
    """The shape of the daemon's bug, asserted directly.

    Keeping it as a test because the trap is silent: assigning _db_conn
    looks like it works, and the connection then lives forever.
    """
    srv = _bare_server()
    srv._db_conn = sqlite3.connect(str(wal_db))
    assert srv._db_conn_opened_at is None

    srv.DB_CONN_MAX_AGE_SECONDS = -1       # "infinitely old"
    srv._retire_connection_if_old()

    assert srv._db_conn is not None, \
        "retirement fired on an un-stamped connection -- update the daemon " \
        "comment explaining why injection was removed"


def test_the_daemon_hands_out_a_factory_not_a_connection():
    """HookEngine and WalMaintainer must own connections, not borrow one.

    A borrowed connection is a process-lifetime connection, since the
    daemon's own life is the process's.
    """
    import mcp_daemon

    assert not hasattr(mcp_daemon.MCPDaemon, "_get_db_connection"), \
        "the daemon is not supposed to hold a connection any more"
    assert callable(mcp_daemon.MCPDaemon.new_db_connection)


def test_retired_connection_is_reopened_on_next_use(wal_db):
    srv = _bare_server()
    with patch("mcp_server.DB_PATH", str(wal_db)):
        first = srv._get_db_connection()
        srv.DB_CONN_MAX_AGE_SECONDS = -1
        srv._retire_connection_if_old()
        assert srv._db_conn is None
        second = srv._get_db_connection()

    assert second is not first
    second.execute("SELECT 1").fetchone()   # usable


# ─────────────────────────────────────────────────────────────────────────
# Per-thread state: the daemon serves each request on its own thread
# ─────────────────────────────────────────────────────────────────────────

def test_threads_get_their_own_connection(wal_db):
    srv = _bare_server()
    seen = {}

    def work(name):
        with patch("mcp_server.DB_PATH", str(wal_db)):
            seen[name] = srv._get_db_connection()

    with patch("mcp_server.DB_PATH", str(wal_db)):
        main_conn = srv._get_db_connection()

    threads = [threading.Thread(target=work, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert seen["a"] is not seen["b"]
    assert seen["a"] is not main_conn
    assert srv._db_conn is main_conn, \
        "a request thread replaced the main thread's connection"


def test_a_request_thread_leaves_no_connection_behind(wal_db):
    """The daemon's thread is per-request, so its connection must not
    outlive the request waiting on garbage collection."""
    srv = _bare_server()
    captured = {}

    def request():
        with patch("mcp_server.DB_PATH", str(wal_db)):
            conn = srv._get_db_connection()
            cur = srv._fresh_cursor(conn)
            cur.execute("SELECT id FROM t")      # deliberately not drained
            captured["conn"] = conn
            srv._release_db_connection()

    t = threading.Thread(target=request)
    t.start()
    t.join()

    with pytest.raises(sqlite3.ProgrammingError):
        captured["conn"].execute("SELECT 1")


def test_release_on_one_thread_leaves_another_threads_cursor_alone(wal_db):
    """_fresh_cursor closes the previously tracked cursor. With one
    shared slot, that cursor could belong to another in-flight request."""
    srv = _bare_server()
    opened = threading.Event()
    released = threading.Event()
    failure = {}

    def holder():
        try:
            with patch("mcp_server.DB_PATH", str(wal_db)):
                conn = srv._get_db_connection()
                cur = srv._fresh_cursor(conn)
                cur.execute("SELECT id FROM t")
                opened.set()
                released.wait(timeout=5)
                cur.fetchall()
        except Exception as e:          # pragma: no cover - the bug path
            failure["holder"] = e
        finally:
            # Set unconditionally so a holder that died early cannot let
            # this test pass by never reaching its assertion.
            opened.set()

    def other():
        opened.wait(timeout=5)
        with patch("mcp_server.DB_PATH", str(wal_db)):
            conn = srv._get_db_connection()
            srv._fresh_cursor(conn).execute("SELECT 1")
            srv._release_db_connection()
        released.set()

    threads = [threading.Thread(target=holder), threading.Thread(target=other)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert released.is_set(), "the second request never ran"
    assert "holder" not in failure, \
        f"another thread finalized our cursor: {failure.get('holder')}"


def test_main_thread_keeps_the_age_bound(wal_db):
    """stdio mode reuses one connection across requests, so there the
    bound is a lifetime rather than close-after-every-request."""
    srv = _bare_server()
    with patch("mcp_server.DB_PATH", str(wal_db)):
        conn = srv._get_db_connection()
        srv._release_db_connection()
        assert srv._db_conn is conn, "closed a reusable connection"
        conn.execute("SELECT 1").fetchone()


# ─────────────────────────────────────────────────────────────────────────
# HookEngine owns no connection
# ─────────────────────────────────────────────────────────────────────────

def test_hook_engine_closes_every_connection_it_opens(wal_db):
    import mcp_daemon

    handed_out = []

    def factory():
        conn = sqlite3.connect(str(wal_db))
        conn.row_factory = sqlite3.Row
        handed_out.append(conn)
        return conn

    engine = mcp_daemon.HookEngine(factory)
    assert engine._project_cache, "cache did not load"
    assert len(handed_out) == 1

    engine._refresh_cache()
    assert len(handed_out) == 2, "refresh reused a held connection"

    for conn in handed_out:
        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


def test_hook_engine_cache_contents(wal_db):
    """Behaviour preserved across the factory change: NULL repo_url rows
    are filtered, slugs are all collected."""
    import mcp_daemon

    engine = mcp_daemon.HookEngine(lambda: sqlite3.connect(str(wal_db)))

    assert engine._slug_set == {"templedb", "bza"}
    assert engine._project_cache == {
        "git@github.com:z/templedb.git": "templedb",
        "git@github.com:z/bza.git": "bza",
    }


def test_hook_engine_survives_a_dead_factory(wal_db):
    """A refresh failure must not take the daemon down -- hooks keep
    answering from the cache they already have."""
    import mcp_daemon

    engine = mcp_daemon.HookEngine(lambda: sqlite3.connect(str(wal_db)))
    before = dict(engine._project_cache)

    def boom():
        raise sqlite3.OperationalError("database is locked")

    engine._conn_factory = boom
    engine._refresh_cache()          # must not raise

    assert engine._project_cache == before


# ─────────────────────────────────────────────────────────────────────────
# Pragmas and the periodic checkpoint
# ─────────────────────────────────────────────────────────────────────────

def test_daemon_connections_bound_the_wal_file(wal_db):
    """journal_size_limit is what makes a TRUNCATE actually give the
    space back. The daemon's inline pragma copy had drifted without it."""
    import mcp_daemon

    daemon = mcp_daemon.MCPDaemon()
    with patch("mcp_daemon.DB_PATH", str(wal_db)):
        conn = daemon.new_db_connection()
    try:
        limit = conn.execute("PRAGMA journal_size_limit").fetchone()[0]
        assert limit == JOURNAL_SIZE_LIMIT
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_maintainer_truncates_a_grown_wal(wal_db):
    """An idle connection is not a blocker -- only an open transaction
    is. The writer here stays connected throughout, as the daemon's
    peers do, and the checkpoint still reclaims everything."""
    import mcp_daemon

    writer = _grow_wal(wal_db)
    try:
        wal = Path(f"{wal_db}-wal")
        assert wal.exists() and wal.stat().st_size > 0

        def factory():
            conn = sqlite3.connect(str(wal_db))
            conn.execute("PRAGMA journal_size_limit=%d" % JOURNAL_SIZE_LIMIT)
            return conn

        maintainer = mcp_daemon.WalMaintainer(factory)
        busy, log, checkpointed = maintainer.checkpoint_once()

        assert busy == 0
        assert checkpointed == log
        assert wal.stat().st_size == 0, "TRUNCATE did not give the space back"
    finally:
        writer.close()


def test_maintainer_reports_a_pinned_checkpoint(wal_db):
    """The incident condition, reproduced: a reader holding an open
    snapshot means the -wal cannot shrink past it. The gap between
    `checkpointed` and `log` is the only diagnostic that names this, so
    it has to reach the log rather than be swallowed."""
    import mcp_daemon

    writer = _grow_wal(wal_db)

    reader = sqlite3.connect(str(wal_db))
    reader.execute("BEGIN")
    reader.execute("SELECT count(*) FROM t").fetchone()   # pin a snapshot
    try:
        writer.executemany(
            "INSERT INTO t (blob) VALUES (?)", [("y" * 2000,) for _ in range(200)])
        writer.commit()

        maintainer = mcp_daemon.WalMaintainer(lambda: sqlite3.connect(str(wal_db)))
        with patch("mcp_daemon.logger") as log:
            result = maintainer.checkpoint_once()

        busy, log_frames, checkpointed = result
        assert busy or checkpointed < log_frames, \
            "expected the pinned reader to block a full drain"
        assert log.warning.called, "a pinned checkpoint was not reported"
        message = log.warning.call_args[0][0]
        assert "snapshot" in message
    finally:
        reader.close()
        writer.close()


def test_maintainer_closes_its_connection(wal_db):
    """It runs forever; a connection it kept would be the very holder it
    exists to prevent."""
    import mcp_daemon

    handed_out = []

    def factory():
        conn = sqlite3.connect(str(wal_db))
        handed_out.append(conn)
        return conn

    mcp_daemon.WalMaintainer(factory).checkpoint_once()

    assert len(handed_out) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        handed_out[0].execute("SELECT 1")


def test_maintainer_closes_its_connection_on_failure(wal_db):
    import mcp_daemon

    handed_out = []

    class Exploding(sqlite3.Connection):
        def cursor(self, *a, **kw):
            raise sqlite3.OperationalError("disk I/O error")

    def factory():
        conn = sqlite3.connect(str(wal_db), factory=Exploding)
        handed_out.append(conn)
        return conn

    maintainer = mcp_daemon.WalMaintainer(factory)
    with pytest.raises(sqlite3.OperationalError):
        maintainer.checkpoint_once()

    with pytest.raises(sqlite3.ProgrammingError):
        handed_out[0].execute("SELECT 1")


def test_maintainer_loop_survives_a_failing_checkpoint(wal_db):
    """run() is the daemon's third thread. An exception escaping it
    would kill WAL maintenance silently for the life of the process."""
    import mcp_daemon

    calls = []

    maintainer = mcp_daemon.WalMaintainer(lambda: None, interval=0.01)

    def boom():
        calls.append(1)
        if len(calls) >= 3:
            maintainer.stop()
        raise sqlite3.OperationalError("nope")

    maintainer.checkpoint_once = boom
    with patch("mcp_daemon.logger"):
        maintainer.run()        # returns when stop() is set

    assert len(calls) >= 3
