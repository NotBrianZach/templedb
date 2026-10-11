#!/usr/bin/env python3
"""Pruning entities whose source row is gone, and saying so correctly.

Ingest is add-and-refresh only — it has no delete pass. Deleting a file
removes its project_files row and leaves the File entity behind forever.
By 2026-09-28 that was 25 stale File entities against 1919 live rows.

The worse half was the advice. entity_counts_match_source_tables reported
the drift with "run `templedb ingest all`" in BOTH directions, and in this
one ingest cannot help: running it twice against a delta of 13 moved
nothing. The remedy sent you round a loop and the number never changed.

Deletion of graph rows is the kind of thing that should be hard to do by
accident, so prune-orphans is dry-run by default and --apply is the
opt-in — the inverse of the usual --dry-run flag.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

from db_utils import execute, query_one, query_all


@pytest.fixture(scope="module", autouse=True)
def _isolated_db(module_db):
    """This module hand-builds a partial schema; keep it out of the shared DB.

    Without this it created a 3-column `projects` into the one bootstrap
    DB via db_utils, which broke tests/conftest.py's bootstrap_schema for
    every other module. See module_db in tests/conftest.py.
    """


@pytest.fixture
def graph():
    """Seed a project with live and orphaned File entities."""
    _schema()
    _reset()
    execute("INSERT INTO projects (name, slug) VALUES ('p','p')")
    pid = query_one("SELECT id FROM projects WHERE slug='p'")['id']

    def _file(path, status='active'):
        execute("""INSERT INTO project_files (project_id, file_path, file_name, status)
                   VALUES (?, ?, ?, ?)""", (pid, path, Path(path).name, status))

    def _entity(kind, ref):
        execute("INSERT INTO entities (kind, external_ref, label) VALUES (?,?,?)",
                (kind, ref, Path(ref).name))
        return query_one("SELECT id FROM entities ORDER BY id DESC LIMIT 1")['id']

    from cli.commands.entity import EntityCommands
    return SimpleNamespace(pid=pid, file=_file, entity=_entity,
                           cmd=EntityCommands())


def _schema():
    for stmt in (
        """CREATE TABLE IF NOT EXISTS projects (
               id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, slug TEXT UNIQUE)""",
        """CREATE TABLE IF NOT EXISTS project_files (
               id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
               file_path TEXT, file_name TEXT, status TEXT DEFAULT 'active')""",
        # source_authority / observed_at are selected by the prune and
        # doctor queries, and UNIQUE(kind, external_ref) is what production
        # relies on, so all three belong here. NOT NULL is kept to match
        # production, with a default so the inserts below need not spell it
        # out; without the column at all every query died on
        # "no such column: e.source_authority".
        """CREATE TABLE IF NOT EXISTS entities (
               id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
               external_ref TEXT,
               source_authority TEXT NOT NULL DEFAULT 'templedb',
               label TEXT,
               observed_at TEXT NOT NULL DEFAULT (datetime('now')),
               created_at TEXT NOT NULL DEFAULT (datetime('now')),
               attributes_json TEXT,
               UNIQUE(kind, external_ref))""",
        """CREATE TABLE IF NOT EXISTS relations (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               from_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
               kind TEXT NOT NULL,
               to_entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
               source_authority TEXT NOT NULL DEFAULT 'templedb',
               observed_at TEXT NOT NULL DEFAULT (datetime('now')),
               attributes_json TEXT,
               UNIQUE(from_entity_id, kind, to_entity_id))""",
        """CREATE TABLE IF NOT EXISTS observations_archive (
               id INTEGER PRIMARY KEY AUTOINCREMENT, entity_id INTEGER)""",
        # The count invariant walks every dual-write pair, not just File,
        # so these have to exist for it to run at all. Empty is fine —
        # 0 entities vs 0 rows is within tolerance and reports nothing,
        # which keeps the assertions about File unambiguous.
        """CREATE TABLE IF NOT EXISTS vcs_commits (id INTEGER PRIMARY KEY)""",
        """CREATE TABLE IF NOT EXISTS edit_intents (id INTEGER PRIMARY KEY)""",
        """CREATE TABLE IF NOT EXISTS agent_sessions (id INTEGER PRIMARY KEY)""",
        """CREATE TABLE IF NOT EXISTS tool_calls (id INTEGER PRIMARY KEY)""",
        """CREATE TABLE IF NOT EXISTS deployment_history (id INTEGER PRIMARY KEY)""",
        """CREATE TABLE IF NOT EXISTS ast_builds (id INTEGER PRIMARY KEY)""",
        # checkouts and vcs_sessions are reached through the resolver on the
        # way to the entity tables, so they have to exist even though no
        # assertion here looks at them. Absent entirely until the suite got
        # per-module databases — before that another module had already
        # created them in the shared one, which is also why omitting them
        # went unnoticed. DDL kept identical to test_checkout_resolve.py.
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
               author TEXT, ended_at TEXT,
               started_at TEXT NOT NULL DEFAULT (datetime('now')))""",
        # prune_orphans writes an audit row here for every entity it
        # removes, so the table is part of the behaviour under test, not
        # incidental. Mirrors production, including relations_removed —
        # the count of rows lost to FK CASCADE, which leave no other trace.
        """CREATE TABLE IF NOT EXISTS entity_deletions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               entity_id INTEGER NOT NULL,
               entity_kind TEXT NOT NULL,
               entity_ref TEXT NOT NULL,
               label TEXT,
               source_authority TEXT NOT NULL DEFAULT 'templedb',
               deleted_via TEXT NOT NULL,
               reason TEXT NOT NULL,
               relations_removed INTEGER NOT NULL DEFAULT 0,
               deleted_at TEXT NOT NULL DEFAULT (datetime('now')))""",
    ):
        execute(stmt)


def _reset():
    for t in ('observations_archive', 'relations', 'entities',
              'project_files', 'projects'):
        execute(f"DELETE FROM {t}")


def _args(dry_run=True, kind=None):
    return SimpleNamespace(dry_run=dry_run, kind=kind)


def _n_entities():
    return query_one("SELECT COUNT(*) c FROM entities")['c']


# --- finding them -----------------------------------------------------

def test_orphan_is_found_and_live_entity_is_not(graph):
    graph.file('src/live.py')
    graph.entity('File', 'p/src/live.py')
    graph.entity('File', 'p/src/deleted.py')      # no project_files row
    graph.cmd.graph_prune_orphans(_args(dry_run=False))
    left = [r['external_ref'] for r in query_all("SELECT external_ref FROM entities")]
    assert left == ['p/src/live.py']


def test_soft_deleted_file_counts_as_orphan(graph):
    """status='deleted' is how a file leaves the active set, and the
    entity should go with it — that is the exact case that produced 25
    strays here."""
    graph.file('src/gone.py', status='deleted')
    graph.entity('File', 'p/src/gone.py')
    graph.cmd.graph_prune_orphans(_args(dry_run=False))
    assert _n_entities() == 0


def test_entity_of_another_project_is_not_touched(graph):
    """external_ref is '<slug>/<path>', so a same-named file under a
    different project must not be mistaken for this one's orphan."""
    graph.file('src/x.py')
    graph.entity('File', 'other/src/x.py')
    graph.cmd.graph_prune_orphans(_args(dry_run=False))
    # 'other' has no projects row at all, so this IS an orphan — assert
    # the reason, not just the count.
    assert _n_entities() == 0

    _reset()
    execute("INSERT INTO projects (name, slug) VALUES ('other','other')")
    opid = query_one("SELECT id FROM projects WHERE slug='other'")['id']
    execute("""INSERT INTO project_files (project_id, file_path, file_name, status)
               VALUES (?, 'src/x.py', 'x.py', 'active')""", (opid,))
    graph.entity('File', 'other/src/x.py')
    graph.cmd.graph_prune_orphans(_args(dry_run=False))
    assert _n_entities() == 1, "a live file in another project must survive"


# --- not deleting them ------------------------------------------------

def test_dry_run_is_the_default_and_deletes_nothing(graph):
    graph.entity('File', 'p/src/gone.py')
    graph.cmd.graph_prune_orphans(_args())        # no --apply
    assert _n_entities() == 1


def test_other_kinds_are_untouched(graph):
    """Only kinds with an explicit orphan rule are prunable. A kind
    without one cannot be checked safely, so it is left alone rather
    than guessed at."""
    graph.entity('Symbol', 'p/src/foo.py:bar')
    graph.entity('Commit', 'p/ABC123')
    graph.cmd.graph_prune_orphans(_args(dry_run=False))
    assert _n_entities() == 2


def test_unknown_kind_is_refused(graph, capsys):
    rc = graph.cmd.graph_prune_orphans(_args(dry_run=False, kind='Nonsense'))
    assert rc == 1


# --- cleaning up after them -------------------------------------------

def test_relations_go_but_archive_rows_are_kept(graph):
    """Relations would be orphans; the archive row is the point.

    This asserted `observations_archive == 0` until 2026-10-10, which is
    the behaviour migration 124 deliberately REVERSED. Its header is
    explicit: both delete paths used to remove the matching archive rows
    and "that is exactly backwards -- the archive is the only durable
    trace of an entity having existed, so deleting it alongside the
    entity destroys the evidence at precisely the moment it becomes the
    sole record." That was written after 12,428 scip Symbols vanished on
    2026-10-02 and the 2,141 surviving archive rows were the only reason
    the loss could be identified at all.

    It passed anyway because the suite shared one database and some other
    module's observations_archive DDL carried an ON DELETE CASCADE that
    production does not have (production comments entity_id "FK-ish
    (entity may have been deleted)"). Per-module databases removed the
    borrowed FK and the assertion inverted — a test encoding the exact
    bug 124 fixed.
    """
    live = graph.entity('File', 'p/src/live.py')
    graph.file('src/live.py')
    dead = graph.entity('File', 'p/src/gone.py')
    execute("INSERT INTO relations (from_entity_id, to_entity_id, kind) VALUES (?,?,'imports')",
            (dead, live))
    execute("INSERT INTO observations_archive (entity_id) VALUES (?)", (dead,))
    execute("PRAGMA foreign_keys = ON")
    graph.cmd.graph_prune_orphans(_args(dry_run=False))
    # Kept on purpose: append-only trace of the entity having existed.
    assert query_one("SELECT COUNT(*) c FROM observations_archive")['c'] == 1
    # Relations genuinely cascade — leaving them would orphan them.
    assert query_one("SELECT COUNT(*) c FROM relations")['c'] == 0
    assert _n_entities() == 1
    # And the removal is accountable, which is what 124 added.
    assert query_one(
        "SELECT COUNT(*) c FROM entity_deletions WHERE entity_id=?", (dead,)
    )['c'] == 1


# --- the advice that was wrong ----------------------------------------

def test_remedy_names_pruning_when_entities_exceed_sources(graph):
    """`ingest all` has no delete pass, so recommending it in this
    direction sent people round a loop that changed nothing."""
    for i in range(10):
        graph.entity('File', f'p/src/gone{i}.py')
    issues = graph.cmd._check_entity_counts_match_sources()
    fileish = [i for i in issues if i.startswith('File:')]
    assert fileish, "the drift should still be reported"
    assert 'prune-orphans' in fileish[0]
    assert 'will NOT fix' in fileish[0]


def test_remedy_still_says_ingest_when_sources_exceed_entities(graph):
    """The other direction is genuine ingest lag, and ingest is the fix."""
    for i in range(10):
        graph.file(f'src/new{i}.py')
    issues = graph.cmd._check_entity_counts_match_sources()
    fileish = [i for i in issues if i.startswith('File:')]
    assert fileish
    assert 'ingest all' in fileish[0]
    assert 'prune-orphans' not in fileish[0]
