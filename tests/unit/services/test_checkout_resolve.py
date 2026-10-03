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


def test_no_edit_tree_does_not_claim_one_belongs_to_a_live_session(repo, caplog):
    """The fallback message has to match the situation.

    Both "all edit trees are owned by live sessions" and "there are no
    edit trees" land on the canonical tree, and before phase 4 both said
    the first. After the prune, no-edit-trees is the normal state for a
    project nobody is working on, so that message would be wrong most of
    the time it appeared.
    """
    import logging
    r, pid = repo([('canonical', 'canon', 1, None, True)])
    with caplog.at_level(logging.WARNING):
        got = r.resolve(pid, EDIT)
    assert got['checkout_path'].endswith('canon')
    assert not any('another live session' in m for m in caplog.messages)


# --- phase 4: the prune ------------------------------------------------
#
# Migration 122 named the rule as "session ended AND no uncommitted
# changes". The second half is wrong as stated and these tests pin the
# corrected version: a stale tree has changes by any diff you care to
# run, and sparing it is how templedb kept two adoptable trees whose
# content was older than what was published.


def _blob(hash_, created_at):
    execute("INSERT OR REPLACE INTO content_blobs (hash_sha256, created_at) "
            "VALUES (?, ?)", (hash_, created_at))


def _tracked_file(pid, rel, content, blob_created):
    """Give the project a file whose current content is `content`."""
    import hashlib
    h = hashlib.sha256(content.encode()).hexdigest()
    _blob(h, blob_created)
    execute("INSERT INTO project_files (project_id, file_path, status) "
            "VALUES (?, ?, 'active')", (pid, rel))
    fid = query_one("SELECT id FROM project_files WHERE project_id=? AND "
                    "file_path=?", (pid, rel))['id']
    execute("INSERT INTO file_contents (file_id, content_hash, is_current) "
            "VALUES (?, ?, 1)", (fid, h))
    return h


_CONTENT_TABLES = ('file_contents', 'content_blobs', 'project_files')


@pytest.fixture
def content_tables():
    """The three tables classify_edit_tree reads, and nothing else.

    Dropped on the way in AND on the way out, which is not fussiness:
    conftest gives the whole run one test DB, and six other modules here
    build these same tables with `CREATE TABLE IF NOT EXISTS` and their
    own fuller column sets. A minimal `project_files` left behind by this
    module made IF NOT EXISTS a no-op for them and 32 tests in four files
    failed with "no column named file_type_id" — passing in isolation and
    failing in the suite, which is the worst way for a fixture to be
    wrong. Leaving no schema behind is this module's half of that
    contract.
    """
    def _drop():
        for t in _CONTENT_TABLES:
            execute(f"DROP TABLE IF EXISTS {t}")
    _drop()
    for stmt in (
        """CREATE TABLE project_files (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               project_id INTEGER NOT NULL, file_path TEXT NOT NULL,
               status TEXT DEFAULT 'active')""",
        """CREATE TABLE file_contents (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               file_id INTEGER NOT NULL, content_hash TEXT NOT NULL,
               is_current INTEGER DEFAULT 1)""",
        """CREATE TABLE content_blobs (
               hash_sha256 TEXT PRIMARY KEY, created_at TEXT NOT NULL)""",
    ):
        execute(stmt)
    yield
    _drop()


def test_stale_tree_is_prunable_even_though_every_file_differs(repo, tmp_path, content_tables):
    """The case migration 122's wording would have spared.

    Measured shape, from templedb's claude-code-agent-6352 on 2026-10-03:
    21 files differing from the DB, all 21 holding a blob the DB recorded
    and moved past. "Has uncommitted changes" reads that as 21 reasons to
    keep it; blob age reads it as what it is.
    """
    r, pid = repo([('edit', 'ws', 1, None, True)])
    _tracked_file(pid, 'a.py', 'new content\n', '2026-10-02 00:00:00')
    _blob(__import__('hashlib').sha256(b'old content\n').hexdigest(),
          '2026-09-01 00:00:00')
    (tmp_path / 'ws' / 'a.py').write_text('old content\n')

    v = r.classify_edit_tree(pid, tmp_path / 'ws')
    assert v['verdict'] == r.TREE_STALE
    assert [f['file_path'] for f in v['stale']] == ['a.py']
    assert v['has_work'] == []


def test_content_the_db_has_never_stored_is_work(repo, tmp_path, content_tables):
    """The load-bearing half. A file whose bytes have no content_blobs
    row has never been through this database, so nothing has reviewed it
    and the tree is not retired."""
    r, pid = repo([('edit', 'ws', 1, None, True)])
    _tracked_file(pid, 'a.py', 'committed\n', '2026-10-02 00:00:00')
    (tmp_path / 'ws' / 'a.py').write_text('a genuine edit nobody has seen\n')

    v = r.classify_edit_tree(pid, tmp_path / 'ws')
    assert v['verdict'] == r.TREE_HAS_WORK
    assert [f['file_path'] for f in v['has_work']] == ['a.py']


def test_a_blob_at_least_as_new_as_the_db_counts_as_work(repo, tmp_path, content_tables):
    """Stored but not current means a revert or a lost race. Either way
    it is not staleness, and guessing which is not this function's job."""
    r, pid = repo([('edit', 'ws', 1, None, True)])
    _tracked_file(pid, 'a.py', 'current\n', '2026-10-01 00:00:00')
    _blob(__import__('hashlib').sha256(b'newer\n').hexdigest(),
          '2026-10-02 00:00:00')
    (tmp_path / 'ws' / 'a.py').write_text('newer\n')

    v = r.classify_edit_tree(pid, tmp_path / 'ws')
    assert v['verdict'] == r.TREE_HAS_WORK


def test_a_file_missing_from_the_tree_is_not_work(repo, tmp_path, content_tables):
    """A tree cut before a commit added files is the ordinary case — it
    was 5 files on templedb — and absence cannot hold content."""
    r, pid = repo([('edit', 'ws', 1, None, True)])
    _tracked_file(pid, 'added-later.py', 'x\n', '2026-10-02 00:00:00')

    v = r.classify_edit_tree(pid, tmp_path / 'ws')
    assert v['verdict'] == r.TREE_CLEAN
    assert v['absent'] == ['added-later.py']


def test_an_untracked_file_the_scanner_would_pick_up_is_work(repo, tmp_path, content_tables):
    """This codebase's most expensive recurring loss: a new file written
    into a workspace and never committed (commit 7A3BF285 reported
    "Files: 2" and wrote one). Any of them keeps the tree."""
    r, pid = repo([('edit', 'ws', 1, None, True)])
    (tmp_path / 'ws' / 'brand_new.py').write_text('print(1)\n')

    v = r.classify_edit_tree(pid, tmp_path / 'ws')
    assert v['verdict'] == r.TREE_HAS_WORK
    assert v['untracked'] == ['brand_new.py']


def test_build_debris_does_not_read_as_work(repo, tmp_path, content_tables):
    """Reuses the scanner's SKIP_DIRS rather than a second list. Without
    this, every tree has a __pycache__ and nothing is ever prunable."""
    r, pid = repo([('edit', 'ws', 1, None, True)])
    cache = tmp_path / 'ws' / '__pycache__'
    cache.mkdir(parents=True, exist_ok=True)
    (cache / 'mod.cpython-313.pyc').write_bytes(b'\x00')
    (tmp_path / 'ws' / 'node_modules').mkdir(exist_ok=True)
    (tmp_path / 'ws' / 'node_modules' / 'x.js').write_text('1')

    v = r.classify_edit_tree(pid, tmp_path / 'ws')
    assert v['verdict'] == r.TREE_CLEAN, v['untracked']


def test_prune_candidates_require_an_ended_owner(repo, tmp_path):
    """Three rows, one candidate. An unowned row is NOT one, even though
    resolve() finds it equally adoptable: migration 113's backfill left
    session_id NULL rather than matching leaf names, so NULL means
    nobody recorded an owner — not that the owner finished."""
    r, pid = repo([
        ('edit', 'unowned', 1, None, True),
        ('edit', 'live', 1, None, True),
        ('edit', 'dead', 1, None, True),
    ])
    live, dead = _session(), _session(ended=True)
    execute("UPDATE checkouts SET session_id=? WHERE checkout_path LIKE '%live'",
            (live,))
    execute("UPDATE checkouts SET session_id=? WHERE checkout_path LIKE '%dead'",
            (dead,))

    paths = [c['checkout_path'] for c in r.find_retired_edit_checkouts(pid)]
    assert len(paths) == 1 and paths[0].endswith('dead')


def test_a_workspace_whose_session_row_vanished_is_a_candidate(repo):
    """resolve() already treats a dangling session_id as adoptable, so
    the prune has to see it too or it stays ambiguous forever."""
    r, pid = repo([('edit', 'orphan', 1, None, True)])
    execute("UPDATE checkouts SET session_id = 9999")
    assert len(r.find_retired_edit_checkouts(pid)) == 1


def test_retiring_a_row_leaves_the_tree_reachable_by_name(repo, tmp_path):
    """Deactivate, never delete — the reason migration 122 gives for
    scratch rows. get_by_path does not filter on is_active, so
    `templedb commit <slug> <dir>` still works on a retired tree."""
    r, pid = repo([('edit', 'ws', 1, None, True)])
    path = str(tmp_path / 'ws')
    row = r.get_by_path(pid, path)
    r.deactivate(row['id'])

    assert query_one("SELECT is_active FROM checkouts WHERE id=?",
                     (row['id'],))['is_active'] == 0
    assert r.get_by_path(pid, path) is not None, "still reachable by name"
    assert r.resolve(pid, EDIT) is None, "but never resolved to"


def test_prune_removes_the_ambiguity_resolve_warns_about(repo, tmp_path, caplog, content_tables):
    """End to end, in the shape templedb was actually in: two adoptable
    trees, both stale, both owned by sessions reaped in the same pass."""
    import logging
    r, pid = repo([
        ('edit', 'older', 1, None, True),
        ('edit', 'newer', 1, None, True),
    ])
    _tracked_file(pid, 'a.py', 'published\n', '2026-10-02 00:00:00')
    _blob(__import__('hashlib').sha256(b'stale\n').hexdigest(),
          '2026-09-01 00:00:00')
    for leaf in ('older', 'newer'):
        (tmp_path / leaf / 'a.py').write_text('stale\n')
        sid = _session(ended=True)
        execute("UPDATE checkouts SET session_id=? WHERE checkout_path LIKE ?",
                (sid, f'%{leaf}'))

    with caplog.at_level(logging.WARNING):
        r.resolve(pid, EDIT)
    assert any('candidate edit checkouts' in m for m in caplog.messages)

    for cand in r.find_retired_edit_checkouts(pid):
        v = r.classify_edit_tree(cand['project_id'], cand['checkout_path'])
        assert v['verdict'] == r.TREE_STALE
        r.deactivate(cand['id'])

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert r.resolve(pid, EDIT) is None
    assert caplog.messages == []


def test_a_lone_adoptable_tree_that_predates_the_db_still_warns(
        repo, tmp_path, caplog, content_tables):
    """The hole the prune does not close.

    One candidate is not ambiguous, so step 2 returned it with nothing
    to say — and said nothing about whether it was current either.
    Retiring templedb's 6352 left the next unpinned `vcs status` reading
    a tree from 09-26 in silence, which is less noise and no more truth.
    """
    import logging
    r, pid = repo([('edit', 'old-ws', 1, None, True)])
    _tracked_file(pid, 'a.py', 'published later\n', '2026-10-02 00:00:00')
    # repo() stamps checkout_at as 2026-09-10, before that blob.
    with caplog.at_level(logging.WARNING):
        got = r.resolve(pid, EDIT)
    assert got['checkout_path'].endswith('old-ws'), "still resolves"
    assert any('newer content for 1 file' in m for m in caplog.messages)


def test_a_current_lone_tree_is_adopted_without_complaint(
        repo, tmp_path, caplog, content_tables):
    """The warning has to stay rare or it is the next thing skimmed
    past. A tree newer than every blob says nothing."""
    import logging
    r, pid = repo([('edit', 'ws', 1, None, True)])
    _tracked_file(pid, 'a.py', 'x\n', '2026-09-01 00:00:00')
    with caplog.at_level(logging.WARNING):
        assert r.resolve(pid, EDIT)['checkout_path'].endswith('ws')
    assert caplog.messages == []
