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
        """CREATE TABLE IF NOT EXISTS entities (
               id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT,
               external_ref TEXT, label TEXT)""",
        """CREATE TABLE IF NOT EXISTS relations (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               from_entity_id INTEGER REFERENCES entities(id) ON DELETE CASCADE,
               to_entity_id INTEGER REFERENCES entities(id) ON DELETE CASCADE,
               kind TEXT)""",
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

def test_relations_and_archive_rows_go_too(graph):
    """Leaving either behind would trade one kind of orphan for another."""
    live = graph.entity('File', 'p/src/live.py')
    graph.file('src/live.py')
    dead = graph.entity('File', 'p/src/gone.py')
    execute("INSERT INTO relations (from_entity_id, to_entity_id, kind) VALUES (?,?,'imports')",
            (dead, live))
    execute("INSERT INTO observations_archive (entity_id) VALUES (?)", (dead,))
    execute("PRAGMA foreign_keys = ON")
    graph.cmd.graph_prune_orphans(_args(dry_run=False))
    assert query_one("SELECT COUNT(*) c FROM observations_archive")['c'] == 0
    assert query_one("SELECT COUNT(*) c FROM relations")['c'] == 0
    assert _n_entities() == 1


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
