#!/usr/bin/env python3
"""transaction() is atomic even when what it calls autocommits.

`execute()` defaults to commit=True, which is right for the many callers
that write one row and want it durable. Reached from inside a
transaction() block, though, that default committed the *caller's* open
transaction, making everything written so far permanent and leaving the
later rollback nothing to undo.

`project commit` hit exactly this. It opened a transaction, inserted the
vcs_commits row, then resolved the VCS session — and session creation
inserts into vcs_sessions on the commit=True default. So when a per-file
write failed afterwards, the rollback dropped the file states but not
the commit row: a commit with zero vcs_file_states, listed in the log
and with parent_commit_id NULL, breaking the chain. Commit 3ae8d2dc in
this repo's own history is one; reproduced on demand 2026-10-03 by
injecting a failure into _commit_modified_file.

Fixing only the session call would have left every other transitive
callee one forgotten keyword away from the same corruption, so the
suppression lives in transaction() itself.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

import db_utils


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Point db_utils at a scratch file and hand back a verifier.

    Reads go through a second, independent connection so a test cannot
    pass on uncommitted state visible only to the writing connection.
    """
    import sqlite3

    path = tmp_path / "tx.sqlite"
    monkeypatch.setattr(db_utils, 'DB_PATH', str(path))
    db_utils.close_connection()
    monkeypatch.setattr(db_utils._thread_local, 'tx_depth', 0, raising=False)

    db_utils.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT UNIQUE)")

    def committed():
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            return [r[0] for r in conn.execute("SELECT v FROM t ORDER BY v")]
        finally:
            conn.close()

    yield committed
    db_utils.close_connection()


def test_inner_autocommit_does_not_escape_a_rollback(db):
    """The regression. An inner commit=True must not survive the rollback.

    `inner-autocommit` mimics session creation: a plain execute() with
    the default, called while the caller's transaction is mid-flight.
    """
    with pytest.raises(RuntimeError):
        with db_utils.transaction():
            db_utils.execute("INSERT INTO t (v) VALUES ('before')", commit=False)
            db_utils.execute("INSERT INTO t (v) VALUES ('inner-autocommit')")
            raise RuntimeError("fails after the inner commit")

    assert db() == [], "inner commit=True made the transaction non-atomic"


def test_successful_transaction_still_commits(db):
    """Suppression must not swallow the commit on the happy path."""
    with db_utils.transaction():
        db_utils.execute("INSERT INTO t (v) VALUES ('a')", commit=False)
        db_utils.execute("INSERT INTO t (v) VALUES ('b')")

    assert db() == ['a', 'b']


def test_autocommit_outside_a_transaction_is_unchanged(db):
    """The commit=True default still means durable when nothing wraps it."""
    db_utils.execute("INSERT INTO t (v) VALUES ('standalone')")
    assert db() == ['standalone']


def test_nested_transactions_commit_once_at_the_outermost_exit(db):
    """An inner block must not commit the outer block's work early."""
    with pytest.raises(RuntimeError):
        with db_utils.transaction():
            db_utils.execute("INSERT INTO t (v) VALUES ('outer')", commit=False)
            with db_utils.transaction():
                db_utils.execute("INSERT INTO t (v) VALUES ('inner')", commit=False)
            # inner block exited cleanly; nothing may be durable yet
            assert db() == [], "inner transaction() committed the outer work"
            raise RuntimeError("outer fails")

    assert db() == []


def test_nested_transactions_persist_when_the_outer_one_succeeds(db):
    with db_utils.transaction():
        db_utils.execute("INSERT INTO t (v) VALUES ('outer')", commit=False)
        with db_utils.transaction():
            db_utils.execute("INSERT INTO t (v) VALUES ('inner')", commit=False)

    assert db() == ['inner', 'outer']


def test_depth_is_restored_after_a_failed_transaction(db):
    """A raised block must not leave the thread stuck in suppression.

    If depth leaked, every later execute(commit=True) in the process
    would stop committing — a far worse failure than the one being fixed.
    """
    with pytest.raises(RuntimeError):
        with db_utils.transaction():
            raise RuntimeError("boom")

    assert not db_utils._in_explicit_transaction()
    db_utils.execute("INSERT INTO t (v) VALUES ('after')")
    assert db() == ['after']


def test_executemany_also_respects_the_open_transaction(db):
    with pytest.raises(RuntimeError):
        with db_utils.transaction():
            db_utils.executemany("INSERT INTO t (v) VALUES (?)", [('x',), ('y',)])
            raise RuntimeError("boom")

    assert db() == []
