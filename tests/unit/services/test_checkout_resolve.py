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
def repo(tmp_path, monkeypatch):
    """Build a project's checkout rows and return (resolver, mkdir helper)."""
    _schema()

    # resolve() now defaults session_id to this process's session, read
    # from the environment. Left alone, these tests would inherit whatever
    # TEMPLEDB_SESSION the developer (or agent) happens to have exported
    # and give different answers on different machines. Cleared by default;
    # tests that care set it explicitly.
    monkeypatch.delenv('TEMPLEDB_SESSION', raising=False)
    monkeypatch.delenv('TEMPLEDB_SESSION_ID', raising=False)

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
        # started_at matters: current_session_id() orders by it to pick
        # the most recent session when a name has been reused.
        """CREATE TABLE IF NOT EXISTS vcs_sessions (
               id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT,
               author TEXT, ended_at TEXT,
               started_at TEXT NOT NULL DEFAULT (datetime('now')))""",
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


# --- creation must classify, or the row is invisible -------------------

def test_create_or_update_classifies_by_path(repo, tmp_path, monkeypatch):
    """`kind` must be written at creation, not left to the column default.

    The default is 'scratch' and resolve() ignores scratch, so a checkout
    created without a kind would be invisible to every command that looks
    for a tree — `templedb edit <slug>` would hand back a workspace that
    staging then refused to read. This shipped briefly in phase 2.
    """
    r, pid = repo([])
    monkeypatch.delenv('TEMPLEDB_SESSION', raising=False)
    monkeypatch.delenv('TEMPLEDB_SESSION_ID', raising=False)
    cases = [
        ('/home/u/.config/templedb/checkouts/proj', 'canonical'),
        ('/home/u/.config/templedb/edit-workspaces/proj/sess', 'edit'),
        ('/tmp/whatever', 'scratch'),
        ('/some/unfamiliar/place', 'scratch'),
    ]
    for path, expected in cases:
        assert r.classify_path(path) == expected, path
        r.create_or_update(pid, path)
        row = r.get_by_path(pid, path)
        got = query_one("SELECT kind FROM checkouts WHERE id = ?", (row['id'],))
        assert got['kind'] == expected, f"{path} -> {got['kind']}"


def test_unfamiliar_paths_default_to_scratch(repo):
    """Conservative on purpose: guessing 'edit' for an unrecognised path
    would hand it authority over commits."""
    r, _ = repo([])
    assert r.classify_path('/opt/somewhere/else') == 'scratch'


def test_created_edit_workspace_is_owned_by_this_session(repo, tmp_path, monkeypatch):
    """Ownership is what lets concurrent agents stop competing."""
    r, pid = repo([])
    execute("INSERT INTO vcs_sessions (name, author, ended_at) VALUES ('mine','a',NULL)")
    sid = query_one("SELECT id FROM vcs_sessions WHERE name='mine'")['id']
    monkeypatch.setenv('TEMPLEDB_SESSION', 'mine')
    monkeypatch.delenv('TEMPLEDB_SESSION_ID', raising=False)
    p = '/home/u/.config/templedb/edit-workspaces/proj/mine'
    r.create_or_update(pid, p)
    row = query_one("SELECT kind, session_id FROM checkouts WHERE checkout_path=?", (p,))
    assert row['kind'] == 'edit'
    assert row['session_id'] == sid


def test_canonical_never_acquires_an_owner(repo, monkeypatch):
    """A published tree is shared by definition. If it gained a session,
    resolve() would start treating it as someone's private workspace."""
    r, pid = repo([])
    execute("INSERT INTO vcs_sessions (name, author, ended_at) VALUES ('mine','a',NULL)")
    monkeypatch.setenv('TEMPLEDB_SESSION', 'mine')
    p = '/home/u/.config/templedb/checkouts/proj'
    r.create_or_update(pid, p)
    row = query_one("SELECT kind, session_id FROM checkouts WHERE checkout_path=?", (p,))
    assert row['kind'] == 'canonical'
    assert row['session_id'] is None


def test_rematerialising_does_not_orphan_another_sessions_workspace(repo, monkeypatch):
    """COALESCE on the upsert: a session-less materialise must not erase
    an existing owner, or an incidental `project checkout` would strand
    another agent's tree."""
    r, pid = repo([])
    execute("INSERT INTO vcs_sessions (name, author, ended_at) VALUES ('owner','a',NULL)")
    sid = query_one("SELECT id FROM vcs_sessions WHERE name='owner'")['id']
    p = '/home/u/.config/templedb/edit-workspaces/proj/owner'
    monkeypatch.setenv('TEMPLEDB_SESSION', 'owner')
    r.create_or_update(pid, p)
    monkeypatch.delenv('TEMPLEDB_SESSION', raising=False)
    r.create_or_update(pid, p)          # e.g. a plain `project checkout`
    row = query_one("SELECT session_id FROM checkouts WHERE checkout_path=?", (p,))
    assert row['session_id'] == sid, "owner must survive a session-less re-checkout"


def test_current_session_id_never_creates_a_session(repo, monkeypatch):
    """Resolving a path must not have the side effect of opening a
    session — `vcs status` would start one just by asking where the tree
    is. This is why it is not VCSService.get_current_session."""
    r, _ = repo([])
    monkeypatch.setenv('TEMPLEDB_SESSION', 'does-not-exist')
    before = query_one("SELECT COUNT(*) c FROM vcs_sessions")['c']
    assert r.current_session_id() is None
    assert query_one("SELECT COUNT(*) c FROM vcs_sessions")['c'] == before


def test_ended_session_is_not_current(repo, monkeypatch):
    r, _ = repo([])
    execute("INSERT INTO vcs_sessions (name, author, ended_at) VALUES ('old','a','2026-09-01')")
    monkeypatch.setenv('TEMPLEDB_SESSION', 'old')
    assert r.current_session_id() is None
