#!/usr/bin/env python3
"""Every commit but a first one gets a parent, in both places it is stored.

create_commit took an optional parent_hash and silently produced a root
commit when it was omitted. Two callers omitted it:

  cli/commands/commit.py   `templedb commit` — no parent at all
  cli/commands/vcs.py      `vcs merge` — wrote the vcs_commit_parents row
                           but never set vcs_commits.parent_commit_id

The first is the path CLAUDE.md recommends over `vcs commit`, so it wrote
most of the history: measured 2026-10-03, 888 of 1048 commits were
unreachable from any branch or session head, 541 of them in templedb
alone. Branch heads were all current — the chain was the broken part, in
246 fragments whose roots were commits that should have had parents.

The second is why linkage moved into create_commit rather than being
fixed at each call site: parent_commit_id and the order-0
vcs_commit_parents row are two spellings of one fact, and leaving callers
to write both let them drift.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

import db_utils
from repositories.vcs_repository import VCSRepository


# Real DDL, so the head-advance trigger and the join-table PK are exercised.
NEEDED = ('projects', 'vcs_sessions', 'vcs_branches', 'vcs_commits',
          'vcs_commit_parents')


@pytest.fixture
def repo(tmp_path, monkeypatch):
    live = sqlite3.connect(
        'file:/home/zach/.local/share/templedb/templedb.sqlite?mode=ro', uri=True)
    ddl = []
    for name in NEEDED:
        row = live.execute(
            "SELECT sql FROM sqlite_master WHERE name=? AND type='table'", (name,)).fetchone()
        if row is None:
            pytest.skip(f"live DB lacks {name}")
        ddl.append(row[0])
    trig = live.execute(
        "SELECT sql FROM sqlite_master WHERE type='trigger' "
        "AND name='update_branch_head_on_commit'").fetchone()
    live.close()

    monkeypatch.setattr(db_utils, 'DB_PATH', str(tmp_path / 'p.sqlite'))
    db_utils.close_connection()
    monkeypatch.setattr(db_utils._thread_local, 'tx_depth', 0, raising=False)
    for stmt in ddl:
        db_utils.execute(stmt)
    if trig:
        db_utils.execute(trig[0])
    db_utils.execute("INSERT INTO projects (id, slug, name) VALUES (1, 'p', 'p')")
    db_utils.execute(
        "INSERT INTO vcs_branches (id, project_id, branch_name, is_default) "
        "VALUES (9, 1, 'main', 1)")

    yield VCSRepository()
    db_utils.close_connection()


def _mk(repo, h, **kw):
    return repo.create_commit(project_id=1, branch_id=9, commit_hash=h,
                              author='t', message=f'commit {h}', **kw)


def _parents(cid):
    col = db_utils.query_one("SELECT parent_commit_id FROM vcs_commits WHERE id=?", (cid,))
    join = db_utils.query_all(
        "SELECT parent_commit_id, parent_order FROM vcs_commit_parents "
        "WHERE commit_id=? ORDER BY parent_order", (cid,))
    return col['parent_commit_id'], [(r['parent_commit_id'], r['parent_order']) for r in join]


def test_parent_commit_id_sets_both_representations(repo):
    """The regression: one argument, both spellings written."""
    root = _mk(repo, 'aaa')
    child = _mk(repo, 'bbb', parent_commit_id=root)

    assert _parents(child) == (root, [(root, 0)])


def test_parent_hash_still_resolves(repo):
    """The older spelling keeps working, and now writes the join row too."""
    root = _mk(repo, 'aaa')
    child = _mk(repo, 'bbb', parent_hash='aaa')

    assert _parents(child) == (root, [(root, 0)])


def test_no_parent_means_a_genuine_root(repo):
    """Omitting both is still allowed — a first commit has no parent."""
    root = _mk(repo, 'aaa')
    assert _parents(root) == (None, [])


def test_unknown_parent_hash_does_not_invent_a_link(repo):
    """An unresolvable hash leaves a root rather than a dangling id."""
    c = _mk(repo, 'aaa', parent_hash='nope')
    assert _parents(c) == (None, [])


def test_parent_commit_id_wins_over_parent_hash(repo):
    root_a = _mk(repo, 'aaa')
    root_b = _mk(repo, 'bbb')
    child = _mk(repo, 'ccc', parent_hash='aaa', parent_commit_id=root_b)

    assert _parents(child) == (root_b, [(root_b, 0)])


def test_chain_of_commits_is_reachable_from_the_branch_head(repo):
    """What the bug actually cost: walking back from HEAD sees everything.

    The trigger advances head on each insert, so this also pins the
    ordering requirement — read the head before creating the commit, or
    every commit becomes its own parent's parent.
    """
    ids = []
    for h in ('c1', 'c2', 'c3', 'c4'):
        head = db_utils.query_one("SELECT head_commit_id FROM vcs_branches WHERE id=9")
        ids.append(_mk(repo, h, parent_commit_id=head['head_commit_id']))

    head = db_utils.query_one("SELECT head_commit_id FROM vcs_branches WHERE id=9")
    assert head['head_commit_id'] == ids[-1]

    walked, cur = [], head['head_commit_id']
    while cur is not None:
        walked.append(cur)
        cur = db_utils.query_one(
            "SELECT parent_commit_id FROM vcs_commits WHERE id=?", (cur,))['parent_commit_id']

    assert walked == list(reversed(ids)), "chain from HEAD does not cover every commit"


def test_relinking_is_idempotent(repo):
    """A caller that also inserts order-0 itself must not collide.

    vcs merge did exactly that before this change, and the join table has
    a (commit_id, parent_commit_id) primary key.
    """
    root = _mk(repo, 'aaa')
    child = _mk(repo, 'bbb', parent_commit_id=root)
    db_utils.execute(
        "INSERT OR IGNORE INTO vcs_commit_parents (commit_id, parent_commit_id, parent_order) "
        "VALUES (?, ?, 0)", (child, root))

    assert _parents(child) == (root, [(root, 0)])
