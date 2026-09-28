#!/usr/bin/env python3
"""CheckoutRepository.resolve — pick the tree by what it is for.

Before migration 113 there was one answer to "the active checkout", and
it was "whichever directory was written to most recently", because
is_active was 1 on all 61 rows and 0 on none. That is how a
`project checkout` refreshing the canonical tree became the source for
staging and cost system_config commit FA20845EE25BD208 its content.

Two consumers genuinely want different trees and no single flag can serve
both: a build must read the materialised tree `publish` owns, a commit
must read the tree someone is editing. resolve() takes the purpose.

Phase 2 of reports/2026-09-27-2103-checkout-role-and-session-scoped-
resolution-design.html.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

from db_utils import execute, query_one


@pytest.fixture
def repo(tmp_path):
    """Build a project's checkout rows and return (resolver, mkdir helper)."""
    _schema()

    def _make(rows, session_id=None):
        """rows: list of (kind, leaf, is_active, session_id, exists)."""
        _reset()
        execute("INSERT INTO projects (name, slug) VALUES ('p','p')")
        pid = query_one("SELECT id FROM projects WHERE slug='p'")['id']
        for i, (kind, leaf, active, sid, exists) in enumerate(rows):
            p = tmp_path / leaf
            if exists:
                p.mkdir(parents=True, exist_ok=True)
            execute("""INSERT INTO checkouts
                         (project_id, checkout_path, branch_name, checkout_at,
                          is_active, kind, session_id)
                       VALUES (?, ?, 'main', ?, ?, ?, ?)""",
                    (pid, str(p), f"2026-09-{10+i:02d} 00:00:00",
                     active, kind, sid))
        from repositories.checkout_repository import CheckoutRepository
        return CheckoutRepository(), pid

    return _make


def _schema():
    for stmt in (
        """CREATE TABLE IF NOT EXISTS projects (
               id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, slug TEXT UNIQUE)""",
        """CREATE TABLE IF NOT EXISTS checkouts (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               project_id INTEGER NOT NULL, checkout_path TEXT NOT NULL,
               branch_name TEXT DEFAULT 'main',
               checkout_at TEXT NOT NULL DEFAULT (datetime('now')),
               last_sync_at TEXT, is_active BOOLEAN DEFAULT 1,
               kind TEXT NOT NULL DEFAULT 'scratch',
               session_id INTEGER,
               UNIQUE(project_id, checkout_path))""",
        """CREATE TABLE IF NOT EXISTS vcs_sessions (
               id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT,
               author TEXT, ended_at TEXT)""",
    ):
        execute(stmt)


def _reset():
    for t in ('checkouts', 'vcs_sessions', 'projects'):
        execute(f"DELETE FROM {t}")


def _session(ended=False):
    execute("INSERT INTO vcs_sessions (name, author, ended_at) VALUES ('s','a',?)",
            ('2026-09-20 00:00:00' if ended else None,))
    return query_one("SELECT id FROM vcs_sessions ORDER BY id DESC LIMIT 1")['id']


BUILD = 'build'
EDIT = 'edit'


# --- build takes canonical --------------------------------------------

def test_build_takes_canonical_even_when_an_edit_tree_is_newer(repo):
    """The incident in one assertion. Recency used to decide this, so a
    newer edit workspace won and a build read an in-progress tree."""
    r, pid = repo([
        ('canonical', 'canon', 1, None, True),
        ('edit', 'ws', 1, None, True),          # newer
    ])
    assert r.resolve(pid, BUILD)['checkout_path'].endswith('canon')


def test_build_ignores_scratch_entirely(repo):
    r, pid = repo([
        ('canonical', 'canon', 1, None, True),
        ('scratch', 'tmp', 1, None, True),      # newer, still active
    ])
    assert r.resolve(pid, BUILD)['checkout_path'].endswith('canon')


def test_build_skips_a_canonical_row_whose_directory_is_gone(repo):
    r, pid = repo([
        ('canonical', 'vanished', 1, None, False),
        ('edit', 'ws', 1, None, True),
    ])
    # No extant canonical; must not return a path that isn't there.
    assert r.resolve(pid, BUILD)['checkout_path'].endswith('ws')


# --- edit prefers this session ----------------------------------------

# NOTE: sessions must be created AFTER repo(), which resets the tables.
# Creating one first leaves a dangling session_id, and a dangling id reads
# as "not live" — so these tests would pass without exercising liveness at
# all. Two of them did, before this was noticed.

def test_edit_prefers_this_sessions_workspace_over_a_newer_one(repo):
    """The concurrent-agent case. bza has had two agent workspaces at
    once; recency handed both agents the same tree."""
    r, pid = repo([
        ('edit', 'mine', 1, None, True),
        ('edit', 'theirs', 1, None, True),      # newer
    ])
    mine = _session()
    execute("UPDATE checkouts SET session_id=? WHERE checkout_path LIKE '%mine'",
            (mine,))
    assert r.resolve(pid, EDIT, session_id=mine)['checkout_path'].endswith('mine')


def test_edit_never_silently_takes_another_live_sessions_tree(repo):
    """Staging another agent's in-progress work is the outcome worth
    preventing. Falls back to canonical instead."""
    r, pid = repo([
        ('canonical', 'canon', 1, None, True),
        ('edit', 'theirs', 1, None, True),
    ])
    theirs = _session()
    execute("UPDATE checkouts SET session_id=? WHERE checkout_path LIKE '%theirs'",
            (theirs,))
    assert r.resolve(pid, EDIT)['checkout_path'].endswith('canon')


def test_a_dead_sessions_workspace_is_adoptable(repo):
    """Sessions get reaped. Their tree must not become unreachable, or
    the work in it is stranded."""
    r, pid = repo([('edit', 'orphan', 1, None, True)])
    dead = _session(ended=True)
    execute("UPDATE checkouts SET session_id=? WHERE checkout_path LIKE '%orphan'",
            (dead,))
    assert r.resolve(pid, EDIT)['checkout_path'].endswith('orphan')


def test_workspace_of_a_vanished_session_is_adoptable(repo):
    """A session_id pointing at no row cannot be live. Treating it as
    owned would strand the tree permanently."""
    r, pid = repo([('edit', 'orphan', 1, None, True)])
    execute("UPDATE checkouts SET session_id=9999 WHERE checkout_path LIKE '%orphan'")
    assert r.resolve(pid, EDIT)['checkout_path'].endswith('orphan')


def test_single_unowned_edit_tree_resolves(repo):
    """The common case, and the backward-compatibility guarantee: one
    workspace, no session, behaves exactly as before."""
    r, pid = repo([('edit', 'ws', 1, None, True)])
    assert r.resolve(pid, EDIT)['checkout_path'].endswith('ws')


def test_ambiguous_edit_trees_warn_but_still_resolve(repo, caplog):
    """Not fatal yet, deliberately. session_id is NULL on every row
    migration 113 touched, so raising here would break the three projects
    that currently have more than one edit tree. Warn and keep the
    deterministic answer; phase 4 makes it fatal."""
    r, pid = repo([
        ('edit', 'a', 1, None, True),
        ('edit', 'b', 1, None, True),
    ])
    import logging
    with caplog.at_level(logging.WARNING):
        got = r.resolve(pid, EDIT)
    assert got['checkout_path'].endswith('b'), "newest wins, as before"
    assert any('candidate edit checkouts' in m for m in caplog.messages)


def test_edit_ignores_scratch(repo):
    """A /tmp tree must never be staged from, however recent."""
    r, pid = repo([
        ('edit', 'ws', 1, None, True),
        ('scratch', 'tmp', 1, None, True),
    ])
    assert r.resolve(pid, EDIT)['checkout_path'].endswith('ws')


def test_inactive_rows_are_never_resolved(repo):
    """What migration 113 retired must stay retired."""
    r, pid = repo([
        ('canonical', 'canon', 1, None, True),
        ('edit', 'retired', 0, None, True),
    ])
    assert r.resolve(pid, EDIT)['checkout_path'].endswith('canon')


def test_no_rows_returns_none(repo):
    r, pid = repo([])
    assert r.resolve(pid, EDIT) is None


def test_legacy_shim_still_works(repo):
    """get_active_for_project is kept so call sites migrate one at a
    time; it must mean EDIT."""
    r, pid = repo([
        ('canonical', 'canon', 1, None, True),
        ('edit', 'ws', 1, None, True),
    ])
    assert r.get_active_for_project(pid)['checkout_path'].endswith('ws')


# --- the raw-sqlite duplicate must agree ------------------------------

def test_dev_mode_sql_orders_edit_before_canonical(repo):
    """src/cli/__init__.py re-implements this ordering in stdlib sqlite3,
    because it runs before templedb is importable. If the two disagree,
    TEMPLEDB_DEV_MODE=1 runs different code than the tree you edited —
    which its own comment says already happened once.
    """
    import sqlite3
    import os
    r, pid = repo([
        ('canonical', 'canon', 1, None, True),
        ('edit', 'ws', 1, None, True),
        ('scratch', 'tmp', 1, None, True),
    ])
    db_path = os.environ['TEMPLEDB_PATH']
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = con.execute(
        """SELECT c.checkout_path FROM checkouts c
             JOIN projects p ON p.id = c.project_id
            WHERE p.slug = 'p' AND c.is_active = 1
            ORDER BY CASE c.kind WHEN 'edit' THEN 0
                                 WHEN 'canonical' THEN 1
                                 ELSE 2 END,
                     c.checkout_at DESC""").fetchall()
    con.close()
    assert rows[0][0].endswith('ws'), "dev mode must prefer the edit tree"
    assert rows[1][0].endswith('canon'), "then canonical"
    assert rows[2][0].endswith('tmp'), "scratch last"
    # And the repository agrees on the top pick.
    assert r.resolve(pid, EDIT)['checkout_path'] == rows[0][0]
