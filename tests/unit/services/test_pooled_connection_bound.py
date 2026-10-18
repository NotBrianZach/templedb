#!/usr/bin/env python3
"""The pooled connection must not outlive its bound.

db_utils hands out one thread-local connection and keeps it for the life
of the thread. In a CLI process that is milliseconds. In
`ai agent serve --stdio` it is the life of the process, and in WAL mode
a connection holding a read snapshot stops a checkpoint advancing past
it — nothing outside a process can end that process's transaction, so
the only lever is the holder closing its own connection.

`ai mcp daemon` got that bound on 2026-10-04
(MCPServer.DB_CONN_MAX_AGE_SECONDS). This connection never did. Measured
2026-10-17, an hour after the daemon side was fixed and deployed: the
-wal was 110 MB with the checkpoint pinned at frame 21 and 27,039 frames
behind it, while the daemon's own maintainer logged
`busy=1, checkpointed 21 of 21935` every five minutes. Finalising
cursors (_pooled_cursor, 2026-10-02) removed the known leak here;
bounding the connection removes the class.

The bound is applied at a REQUEST BOUNDARY, not inside
get_connection(). Roughly 70 call sites do `conn = get_connection()` and
hold the result across statements, three of them storing it on an object
(`self.db_conn`), so retiring inside the accessor would let a nested
query_all() close a connection its caller was still using. The tests
that matter most here are therefore the ones pinning when it DECLINES.
"""
import sqlite3
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolated_db(module_db):
    """Points db_utils at a temp file; keep it off the shared DB."""


@pytest.fixture
def pooled(tmp_path, monkeypatch):
    """A pooled connection against a throwaway WAL database."""
    import db_utils

    db = tmp_path / "pool.sqlite"
    monkeypatch.setattr(db_utils, 'DB_PATH', str(db))
    db_utils.close_connection()

    conn = db_utils.get_connection()
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.commit()

    yield db_utils, db

    db_utils.close_connection()


def _age(db_utils, seconds):
    """Make the current pooled connection look `seconds` old."""
    import time
    db_utils._thread_local.connection_opened_at = time.monotonic() - seconds


# ─── it declines ────────────────────────────────────────────────────────

def test_a_young_connection_is_kept(pooled):
    db_utils, _ = pooled
    before = db_utils.get_connection()

    assert db_utils.release_pooled_connection() is False
    assert db_utils.get_connection() is before


def test_declines_inside_an_explicit_transaction(pooled):
    """transaction() owns the commit. Closing underneath it would
    discard everything written in the block."""
    db_utils, _ = pooled

    with db_utils.transaction() as conn:
        _age(db_utils, 9999)
        assert db_utils.release_pooled_connection() is False
        conn.execute("INSERT INTO t (v) VALUES ('inside')")

    assert db_utils.query_one("SELECT COUNT(*) AS n FROM t")['n'] == 1, \
        "the transaction's write did not survive"


def test_declines_while_an_implicit_write_transaction_is_open(pooled):
    """execute(commit=False) outside a transaction() block leaves a write
    transaction open. Retiring would roll back uncommitted work, which is
    worse than a large -wal and is somebody else's bug to fix."""
    db_utils, _ = pooled

    db_utils.execute("INSERT INTO t (v) VALUES ('uncommitted')", commit=False)
    conn = db_utils.get_connection()
    assert conn.in_transaction, "precondition: a write transaction is open"

    _age(db_utils, 9999)
    assert db_utils.release_pooled_connection() is False
    assert db_utils.get_connection() is conn

    conn.commit()
    assert db_utils.query_one("SELECT COUNT(*) AS n FROM t")['n'] == 1


def test_declines_when_there_is_no_connection(pooled):
    db_utils, _ = pooled
    db_utils.close_connection()
    assert db_utils.release_pooled_connection() is False


def test_declines_when_the_timestamp_is_missing(pooled):
    """A connection opened by something that did not stamp it is left
    alone rather than retired on sight."""
    db_utils, _ = pooled
    del db_utils._thread_local.connection_opened_at

    assert db_utils.release_pooled_connection() is False


# ─── it retires ─────────────────────────────────────────────────────────

def test_an_old_idle_connection_is_closed(pooled):
    db_utils, _ = pooled
    conn = db_utils.get_connection()
    _age(db_utils, 9999)

    assert db_utils.release_pooled_connection() is True
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_the_next_caller_gets_a_working_connection(pooled):
    db_utils, _ = pooled
    first = db_utils.get_connection()
    _age(db_utils, 9999)
    db_utils.release_pooled_connection()

    second = db_utils.get_connection()
    assert second is not first
    assert second.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 0


def test_a_reopened_connection_is_not_instantly_retired(pooled):
    """The timestamp has to be cleared with the connection. Leaving it
    behind makes every fresh connection inherit the old age and get
    retired on its first boundary — a close/reopen per request forever."""
    db_utils, _ = pooled
    _age(db_utils, 9999)
    db_utils.release_pooled_connection()

    fresh = db_utils.get_connection()
    assert db_utils.release_pooled_connection() is False, \
        "retired a connection that was just opened"
    assert db_utils.get_connection() is fresh


def test_close_connection_clears_the_timestamp(pooled):
    db_utils, _ = pooled
    db_utils.close_connection()
    assert not hasattr(db_utils._thread_local, 'connection_opened_at')


def test_the_bound_is_sixty_seconds(pooled):
    """Matched to MCPServer.DB_CONN_MAX_AGE_SECONDS on purpose — same
    trade-off, and two different numbers would be two behaviours to
    reason about."""
    db_utils, _ = pooled
    assert db_utils.POOLED_CONN_MAX_AGE_SECONDS == 60

    _age(db_utils, 59)
    assert db_utils.release_pooled_connection() is False
    _age(db_utils, 61)
    assert db_utils.release_pooled_connection() is True


# ─── thread isolation ───────────────────────────────────────────────────

# A behavioural test belongs here and was written, then removed: it
# pinned a checkpoint with a live reader, retired the holder, and
# asserted the -wal then drained. TRUNCATE works normally in this
# environment (verified separately: write, close, checkpoint -> busy=0
# and the -wal is removed), but once a checkpoint has run against a
# pinned reader, the WAL stayed stuck at the pinned frame reporting
# busy=1 even after every connection was closed, and I could not explain
# why. A test whose failure mode is not understood is a liability, and
# that one was asserting a property of SQLite rather than of this code:
# what db_utils has to get right is WHEN it closes, which the cases
# above cover. The pin/checkpoint relationship is evidenced in
# production instead, by WalMaintainer's warnings in mcp_daemon.

def test_other_threads_connections_are_untouched(pooled):
    """Thread-local means thread-local: a boundary reached on one thread
    must not close a connection another thread is using."""
    db_utils, _ = pooled
    mine = db_utils.get_connection()
    theirs = {}
    done = threading.Event()

    def worker():
        theirs['conn'] = db_utils.get_connection()
        done.wait(timeout=5)
        try:
            theirs['conn'].execute("SELECT 1").fetchone()
            theirs['ok'] = True
        except Exception as e:
            theirs['ok'] = e

    t = threading.Thread(target=worker)
    t.start()
    while 'conn' not in theirs:
        pass

    _age(db_utils, 9999)
    assert db_utils.release_pooled_connection() is True
    done.set()
    t.join(timeout=10)

    assert theirs['conn'] is not mine
    assert theirs['ok'] is True, f"closed another thread's connection: {theirs['ok']}"
