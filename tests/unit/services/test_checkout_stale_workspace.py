#!/usr/bin/env python3
"""checkout_matches_db must catch a STALE workspace, not just an unrecorded one.

The check already reported a checkout that diverged from the DB with no
vcs_working_state row. It said nothing when a row existed, on the
reasoning that a row means someone is mid-edit. That reasoning has a
hole, and on 2026-09-26 the hole cost real content:

  this project's edit workspace held src/agent/providers/claude_code.py
  from 09-19 and src/importer/scanner.py from 09-06, while the DB's
  current blobs for both dated from 09-24. Committing that workspace
  would have silently reverted the agent idle-timeout watchdog and the
  lock-file scanner patterns. Both rows read state='modified', so the one
  invariant built for exactly this failure class stayed green.

An edit in progress and a workspace left behind are indistinguishable by
`state`. They are distinguishable by WHEN the checkout's content was
first recorded: a real edit produces content the database has never
stored, while a stale workspace holds a blob the DB recorded and moved
past. These tests pin that discriminator down in both directions —
catching staleness matters, but so does staying quiet for ordinary
uncommitted work, since a check that fires on every edit is a check
nobody reads.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

from db_utils import execute, query_one


OLD = '2026-09-06 16:15:07'   # when the stale workspace's blob was stored
NEW = '2026-09-24 15:43:56'   # when the DB's current blob was stored


@pytest.fixture(scope="module", autouse=True)
def _isolated_db(module_db):
    """This module hand-builds a partial schema; keep it out of the shared DB.

    Without this it created a 3-column `projects` into the one bootstrap
    DB via db_utils, which broke tests/conftest.py's bootstrap_schema for
    every other module. See module_db in tests/conftest.py.
    """


@pytest.fixture
def case(tmp_path):
    """Seed one project + one file, and let each test choose:

      db_content    — what the DB says is current
      disk_content  — what is actually in the checkout
      ws_state      — the vcs_working_state row ('modified', 'added',
                      or None for no row at all)
      disk_blob_at  — created_at of the blob matching disk_content

    Returns the issues list from the real checker.
    """
    from cli.commands.entity import EntityCommands

    _schema()

    checkout = tmp_path / "workspace"
    checkout.mkdir()

    def _make(db_content, disk_content, ws_state='modified',
              disk_blob_at=OLD, db_blob_at=NEW, path='src/thing.py',
              write_disk=True):
        _reset()
        project_id = _project('stale-case')
        _checkout(project_id, checkout)

        db_hash = 'db' + str(abs(hash(db_content)))[:20]
        disk_hash = 'ws' + str(abs(hash(disk_content)))[:20]

        _blob(db_hash, db_content, db_blob_at)
        file_id = _file(project_id, path, db_hash)

        if write_disk:
            target = checkout / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(disk_content)

        if ws_state is not None:
            # A stale workspace's content is, by definition, content the
            # DB has seen before — that is what makes the timestamp
            # comparison possible at all.
            if disk_hash != db_hash:
                _blob(disk_hash, disk_content, disk_blob_at)
            _working_state(project_id, file_id, ws_state, disk_hash)

        return EntityCommands()._check_checkout_matches_db()

    return _make


def _schema():
    """Create just the tables the check reads.

    Built here rather than loaded from migrations/schema.sql: that file
    is known to lag the migrations (it does not define deploy_stage_runs
    at all), so depending on it would make this test fail for reasons
    unrelated to what it is testing. Only the columns the checker
    actually touches are declared.
    """
    ddl = [
        """CREATE TABLE IF NOT EXISTS projects (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               name TEXT, slug TEXT UNIQUE)""",
        """CREATE TABLE IF NOT EXISTS file_types (
               id INTEGER PRIMARY KEY AUTOINCREMENT, type_name TEXT)""",
        # UNIQUE(project_id, file_path) matches production and must match
        # the other test modules' DDL exactly. conftest gives the whole
        # pytest session ONE database, so these CREATE TABLE IF NOT
        # EXISTS statements race: whichever module runs first defines the
        # table and every later one silently no-ops. A module that
        # omitted the constraint here made
        # test_detect_changes_deletions' UNIQUE-violation test pass for
        # the wrong reason when run together and fail when run alone.
        """CREATE TABLE IF NOT EXISTS project_files (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               project_id INTEGER NOT NULL, file_type_id INTEGER,
               file_path TEXT NOT NULL, file_name TEXT,
               lines_of_code INTEGER, status TEXT DEFAULT 'active',
               created_at TEXT DEFAULT (datetime('now')),
               updated_at TEXT DEFAULT (datetime('now')),
               UNIQUE(project_id, file_path))""",
        """CREATE TABLE IF NOT EXISTS content_blobs (
               hash_sha256 TEXT PRIMARY KEY,
               content_text TEXT, content_blob BLOB,
               content_type TEXT, encoding TEXT,
               file_size_bytes INTEGER,
               created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS file_contents (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               file_id INTEGER, content_hash TEXT,
               file_size_bytes INTEGER, line_count INTEGER,
               version INTEGER DEFAULT 1, is_current INTEGER DEFAULT 1)""",
        """CREATE TABLE IF NOT EXISTS vcs_branches (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               project_id INTEGER, branch_name TEXT,
               is_default INTEGER DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS vcs_working_state (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               project_id INTEGER, branch_id INTEGER, file_id INTEGER,
               content_hash TEXT, state TEXT,
               staged_by_session_id INTEGER)""",
        """CREATE TABLE IF NOT EXISTS checkouts (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               project_id INTEGER, checkout_path TEXT,
               is_active INTEGER DEFAULT 1,
               checkout_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
    ]
    for stmt in ddl:
        execute(stmt)
    if not query_one("SELECT id FROM file_types LIMIT 1"):
        execute("INSERT INTO file_types (type_name) VALUES ('python')")


def _reset():
    for table in ('vcs_working_state', 'checkouts', 'file_contents',
                  'project_files', 'content_blobs', 'vcs_branches',
                  'projects'):
        execute(f"DELETE FROM {table}")


def _project(slug):
    execute("INSERT INTO projects (name, slug) VALUES (?, ?)", (slug, slug))
    return query_one("SELECT id FROM projects WHERE slug = ?", (slug,))['id']


def _checkout(project_id, path):
    execute(
        """INSERT INTO checkouts (project_id, checkout_path, is_active)
           VALUES (?, ?, 1)""", (project_id, str(path)))


def _blob(hash_, text, created_at):
    execute(
        """INSERT OR IGNORE INTO content_blobs
               (hash_sha256, content_text, content_type, encoding,
                file_size_bytes, created_at)
             VALUES (?, ?, 'text', 'utf-8', ?, ?)""",
        (hash_, text, len(text.encode()), created_at))


def _file(project_id, path, content_hash):
    ftype = query_one("SELECT id FROM file_types LIMIT 1")
    execute(
        """INSERT INTO project_files
               (project_id, file_type_id, file_path, file_name, status)
             VALUES (?, ?, ?, ?, 'active')""",
        (project_id, ftype['id'] if ftype else None, path,
         Path(path).name))
    file_id = query_one(
        "SELECT id FROM project_files WHERE project_id = ? AND file_path = ?",
        (project_id, path))['id']
    execute(
        """INSERT INTO file_contents
               (file_id, content_hash, file_size_bytes, is_current)
             VALUES (?, ?, 0, 1)""", (file_id, content_hash))
    return file_id


def _working_state(project_id, file_id, state, content_hash):
    branch = query_one(
        "SELECT id FROM vcs_branches WHERE project_id = ?", (project_id,))
    if not branch:
        execute(
            """INSERT INTO vcs_branches
                   (project_id, branch_name, is_default)
                 VALUES (?, 'main', 1)""", (project_id,))
        branch = query_one(
            "SELECT id FROM vcs_branches WHERE project_id = ?", (project_id,))
    execute(
        """INSERT INTO vcs_working_state
               (project_id, branch_id, file_id, content_hash, state)
             VALUES (?, ?, ?, ?, ?)""",
        (project_id, branch['id'], file_id, content_hash, state))


# --- the incident -----------------------------------------------------

def test_stale_workspace_is_reported(case):
    """The 2026-09-26 case: disk holds an older known revision and the
    working_state row says 'modified'. Before this fix: silent."""
    issues = case(db_content="new content\n", disk_content="old content\n")
    assert len(issues) == 1
    assert 'OLDER than' in issues[0]
    assert 'src/thing.py' in issues[0]


def test_report_names_both_timestamps_and_the_remedy(case):
    """A bare 'these differ' would leave the reader to work out which
    side is behind — the question that actually decides what to do."""
    issues = case(db_content="new\n", disk_content="old\n")
    assert OLD in issues[0] and NEW in issues[0]
    assert '--refresh' in issues[0]


# --- staying quiet ----------------------------------------------------

def test_ordinary_uncommitted_edit_stays_silent(case):
    """Novel content the DB has never stored. This is the common case —
    firing here would make the check noise and it would stop being read.
    """
    issues = case(db_content="committed\n", disk_content="my new edit\n",
                  disk_blob_at='2026-09-30 10:00:00')
    assert issues == []


def test_edit_whose_blob_is_untracked_stays_silent(case):
    """No content_blobs row for the disk content at all, so there is no
    timestamp to compare. Absence of evidence is not staleness."""
    issues = case(db_content="committed\n", disk_content="brand new\n",
                  ws_state=None, write_disk=True)
    # No working_state row -> falls through to the pre-existing DIFFERS
    # branch, which is the correct report for that shape.
    assert len(issues) == 1
    assert 'no working_state row' in issues[0]


def test_matching_content_is_silent(case):
    """Disk equals DB. Nothing to say regardless of blob timestamps."""
    issues = case(db_content="same\n", disk_content="same\n")
    assert issues == []


def test_added_file_is_not_stale(case):
    """state='added' means the path has no committed history to be
    behind. Its blob is older only because the file was created earlier
    in the session."""
    issues = case(db_content="new file\n", disk_content="new file\n",
                  ws_state='added')
    assert issues == []


def test_equal_timestamps_are_not_stale(case):
    """Strictly-older is the rule. Same-second blobs are a tie, and a
    tie is not evidence of lag."""
    issues = case(db_content="a\n", disk_content="b\n",
                  disk_blob_at=NEW, db_blob_at=NEW)
    assert issues == []


def test_newer_disk_blob_is_not_stale(case):
    """Disk content recorded AFTER the DB's current — that is an edit
    ahead of the DB, the opposite problem, and not this check's to
    report."""
    issues = case(db_content="older\n", disk_content="newer\n",
                  disk_blob_at='2026-09-30 00:00:00', db_blob_at=NEW)
    assert issues == []


# --- the same discriminator, on the path that runs FIRST ---------------
#
# The invariant above reports staleness after the fact.
# WorkingStateDetector._stale_disk_content stops it being recorded in the
# first place, because `vcs status --refresh` reaches vcs_working_state
# through a full rescan that had no age test at all — so asking a
# read-only-looking question wrote the stale tree's older content into
# every row, and a later commit would have replayed it as a revert.
#
# Measured 2026-10-03 on templedb: one --refresh against a workspace cut
# 10-01 produced 21 'modified' rows, and all 21 hashes were blobs the DB
# had recorded and moved past, the oldest from 09-21.


def _detector():
    """The method touches no instance state, so skip __init__ (which
    requires a real project row and a resolvable project_root)."""
    from importer import WorkingStateDetector
    return WorkingStateDetector.__new__(WorkingStateDetector)


@pytest.fixture
def stale_check(tmp_path):
    """Returns _stale_disk_content's verdict for one file.

    db_content is what the DB currently holds; disk_content is what the
    checkout holds. The two *_blob_at values are when this database
    first saw each.
    """
    def _run(db_content, disk_content,
             db_blob_at=NEW, disk_blob_at=OLD, register_disk_blob=True):
        import hashlib
        _schema()
        _reset()
        pid = _project('g')
        db_hash = hashlib.sha256(db_content.encode()).hexdigest()
        _blob(db_hash, db_content, db_blob_at)
        file_id = _file(pid, 'src/thing.py', db_hash)
        disk_hash = hashlib.sha256(disk_content.encode()).hexdigest()
        if register_disk_blob and disk_hash != db_hash:
            _blob(disk_hash, disk_content, disk_blob_at)
        return _detector()._stale_disk_content(file_id, disk_hash)
    return _run


def test_rescan_declines_content_the_db_has_moved_past(stale_check):
    """This session's incident, in one assertion."""
    import hashlib
    verdict = stale_check(db_content="published\n", disk_content="stale\n",
                          db_blob_at=NEW, disk_blob_at=OLD)
    assert verdict is not None
    assert verdict['db_hash'] == hashlib.sha256(b'published\n').hexdigest()
    assert verdict['disk_at'] == OLD and verdict['db_at'] == NEW


def test_rescan_keeps_an_ordinary_editor_write(stale_check):
    """The behaviour the rescan exists for. Content the DB has never
    stored has no blob row, so there is no evidence of staleness and it
    must pass — otherwise every uncommitted edit would be reverted by
    the guard meant to protect it."""
    assert stale_check(db_content="committed\n", disk_content="my edit\n",
                       register_disk_blob=False) is None


def test_rescan_is_silent_when_the_tree_agrees(stale_check):
    assert stale_check(db_content="same\n", disk_content="same\n") is None


def test_rescan_allows_content_newer_than_the_db(stale_check):
    """A blob recorded after the DB's current one is an edit ahead of the
    DB, not a stale tree."""
    assert stale_check(db_content="older\n", disk_content="newer\n",
                       db_blob_at=OLD, disk_blob_at=NEW) is None


def test_rescan_treats_a_tie_as_no_evidence(stale_check):
    """Equal timestamps are not evidence of staleness, and the guard
    only ever acts on evidence — same rule as the `vcs add` guard."""
    assert stale_check(db_content="a\n", disk_content="b\n",
                       db_blob_at=NEW, disk_blob_at=NEW) is None
