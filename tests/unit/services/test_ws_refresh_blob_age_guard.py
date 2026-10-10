#!/usr/bin/env python3
"""_refresh_ws_row_from_disk must not stage content older than it already has.

This function re-hashes a file from whatever directory resolves as the
project's "active checkout" before staging it. That resolution is
recency-based — nothing ever clears checkouts.is_active (61 rows set, 0
cleared on 2026-09-27) — so any command that materialises a tree
somewhere else can make a DIFFERENT tree authoritative as a side effect.

On 2026-09-26 that destroyed a verified write. `templedb file set
--verify` had confirmed hosts/zachgigamothers.nix as fd190b8c2437; a
`project checkout` to the canonical tree then made that tree newest, the
next `vcs add` re-hashed the pre-correction copy out of it, and
system_config commit FA20845EE25BD208 recorded 3dee653f6abd. The commit
message described content the commit did not contain.

The discriminator is blob AGE, not file mtime, and the mtime tests below
exist because mtime is the obvious wrong answer: a materialise writes
stale content with a fresh mtime, so an mtime comparison would call the
stale copy newer than the write it is about to destroy.

The function's original purpose — picking up an editor write the scanner
has not seen yet — has to keep working, so most of these tests assert the
guard stays OUT of the way.
"""
import sys
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

from db_utils import execute, query_one


OLD = '2026-09-06 16:15:07'   # when the DB first saw the stale content
NEW = '2026-09-24 15:43:56'   # when the DB first saw the verified content

# Distinct from None, because None is a meaningful value for
# row_hash_override — "the row's content_hash is NULL" is one of the
# cases under test, and `x if x is not None else default` cannot express
# it.
_UNSET = object()


@pytest.fixture(scope="module", autouse=True)
def _isolated_db(module_db):
    """This module hand-builds a partial schema; keep it out of the shared DB.

    Without this it created a 3-column `projects` into the one bootstrap
    DB via db_utils, which broke tests/conftest.py's bootstrap_schema for
    every other module. See module_db in tests/conftest.py.
    """


@pytest.fixture
def case(tmp_path):
    """Set up one project, one file, one working-state row, and a checkout.

    Each test chooses what the working-state row holds, what the checkout
    contains on disk, and when the DB first recorded each of those two
    contents. Returns (returned_hash, row_hash_after).
    """
    _schema()

    checkout = tmp_path / "active-checkout"
    checkout.mkdir()

    def _make(row_content, disk_content,
              row_blob_at=NEW, disk_blob_at=OLD,
              state='modified', row_hash_override=_UNSET,
              register_disk_blob=True, path='src/thing.py'):
        _reset()
        pid = _project()
        _branch(pid)
        file_id = _file(pid, path)

        row_hash = _hash(row_content)
        _blob(row_hash, row_content, row_blob_at)
        if register_disk_blob and disk_content != row_content:
            _blob(_hash(disk_content), disk_content, disk_blob_at)

        ws_id = _working_state(
            pid, file_id,
            row_hash if row_hash_override is _UNSET else row_hash_override,
            state)

        target = checkout / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(disk_content)

        returned = _run(ws_id, pid, path, checkout)
        after = query_one(
            "SELECT content_hash, state FROM vcs_working_state WHERE id = ?",
            (ws_id,))
        return returned, after

    return _make


def _run(ws_id, pid, path, checkout):
    """Call the real method with checkout resolution stubbed."""
    from services.vcs_service import VCSService

    svc = VCSService.__new__(VCSService)
    from logger import get_logger
    svc.logger = get_logger("test")

    class _Repo:
        def execute(self, sql, params=()):
            return execute(sql, params)

        def query_one(self, sql, params=()):
            return query_one(sql, params)

    svc.vcs_repo = _Repo()

    class _SM:
        def __init__(self, slug): pass
        def get_checkout_path(self): return checkout

    with patch('sync.manager.SyncManager', _SM):
        return svc._refresh_ws_row_from_disk(ws_id, {'slug': 'g'}, path)


def _hash(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


def _schema():
    for stmt in (
        """CREATE TABLE IF NOT EXISTS projects (
               id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, slug TEXT UNIQUE)""",
        """CREATE TABLE IF NOT EXISTS file_types (
               id INTEGER PRIMARY KEY AUTOINCREMENT, type_name TEXT)""",
        """CREATE TABLE IF NOT EXISTS project_files (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               project_id INTEGER NOT NULL, file_type_id INTEGER,
               file_path TEXT NOT NULL, file_name TEXT,
               lines_of_code INTEGER, status TEXT DEFAULT 'active',
               created_at TEXT DEFAULT (datetime('now')),
               updated_at TEXT DEFAULT (datetime('now')),
               UNIQUE(project_id, file_path))""",
        """CREATE TABLE IF NOT EXISTS content_blobs (
               hash_sha256 TEXT PRIMARY KEY, content_text TEXT,
               content_blob BLOB, content_type TEXT, encoding TEXT,
               file_size_bytes INTEGER,
               created_at TEXT DEFAULT CURRENT_TIMESTAMP)""",
        """CREATE TABLE IF NOT EXISTS vcs_branches (
               id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
               branch_name TEXT, is_default INTEGER DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS vcs_working_state (
               id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
               branch_id INTEGER, file_id INTEGER, content_hash TEXT,
               state TEXT, staged_by_session_id INTEGER,
               last_modified TEXT)""",
    ):
        execute(stmt)


def _reset():
    for t in ('vcs_working_state', 'project_files', 'content_blobs',
              'vcs_branches', 'file_types', 'projects'):
        execute(f"DELETE FROM {t}")


def _project():
    execute("INSERT INTO projects (name, slug) VALUES ('g','g')")
    return query_one("SELECT id FROM projects WHERE slug='g'")['id']


def _branch(pid):
    execute("""INSERT INTO vcs_branches (project_id, branch_name, is_default)
               VALUES (?, 'main', 1)""", (pid,))


def _file(pid, path):
    execute("INSERT INTO file_types (type_name) VALUES ('python')")
    ft = query_one("SELECT id FROM file_types LIMIT 1")['id']
    execute("""INSERT INTO project_files
                 (project_id, file_type_id, file_path, file_name, status)
               VALUES (?, ?, ?, ?, 'active')""",
            (pid, ft, path, Path(path).name))
    return query_one("""SELECT id FROM project_files
                         WHERE project_id=? AND file_path=?""", (pid, path))['id']


def _blob(h, text, created_at):
    execute("""INSERT OR IGNORE INTO content_blobs
                 (hash_sha256, content_text, content_type, encoding,
                  file_size_bytes, created_at)
               VALUES (?, ?, 'text', 'utf-8', ?, ?)""",
            (h, text, len(text.encode()), created_at))


def _working_state(pid, file_id, content_hash, state):
    bid = query_one("SELECT id FROM vcs_branches WHERE project_id=?", (pid,))['id']
    execute("""INSERT INTO vcs_working_state
                 (project_id, branch_id, file_id, content_hash, state,
                  last_modified)
               VALUES (?, ?, ?, ?, ?, '2026-09-24 15:43:56')""",
            (pid, bid, file_id, content_hash, state))
    return query_one("SELECT id FROM vcs_working_state ORDER BY id DESC LIMIT 1")['id']


# --- the incident -----------------------------------------------------

def test_stale_checkout_does_not_overwrite_verified_write(case):
    """The 2026-09-26 case. The row holds content the DB recorded on the
    24th; the checkout holds content it recorded on the 6th."""
    returned, after = case(row_content="verified\n", disk_content="stale\n",
                           row_blob_at=NEW, disk_blob_at=OLD)
    assert after['content_hash'] == _hash("verified\n"), \
        "the verified write must survive staging"
    assert returned == _hash("verified\n"), \
        "callers stage the return value, so it must be the kept hash"


def test_declining_leaves_state_untouched(case):
    """Refusing must not half-apply — state is part of the row a commit
    reads, so flipping it while keeping the old hash would be worse than
    either outcome alone."""
    _, after = case(row_content="verified\n", disk_content="stale\n",
                    state='added')
    assert after['state'] == 'added'


# --- the feature this function exists for must keep working ------------

def test_editor_write_is_still_picked_up(case):
    """The original purpose: content the DB has never seen. The
    INSERT OR IGNORE in the method registers it with a current
    timestamp, so it is newer and must win."""
    returned, after = case(row_content="old\n", disk_content="fresh edit\n",
                           register_disk_blob=False)
    assert after['content_hash'] == _hash("fresh edit\n")
    assert returned == _hash("fresh edit\n")


def test_newer_known_content_wins(case):
    """Disk content the DB has seen, but more recently than the row's."""
    returned, after = case(row_content="older\n", disk_content="newer\n",
                           row_blob_at=OLD, disk_blob_at=NEW)
    assert after['content_hash'] == _hash("newer\n")


def test_identical_content_is_a_noop(case):
    """Nothing to decide; must not be reported as a refusal."""
    returned, after = case(row_content="same\n", disk_content="same\n")
    assert after['content_hash'] == _hash("same\n")
    assert returned == _hash("same\n")


def test_equal_timestamps_proceed(case):
    """Strictly-older is the rule. A tie is not evidence of staleness, and
    treating it as such would block same-second legitimate writes."""
    _, after = case(row_content="a\n", disk_content="b\n",
                    row_blob_at=NEW, disk_blob_at=NEW)
    assert after['content_hash'] == _hash("b\n")


def test_row_with_no_hash_proceeds(case):
    """Nothing to protect. A NULL hash is the scanner's 'unknown', not a
    value worth defending."""
    _, after = case(row_content="ignored\n", disk_content="disk\n",
                    row_hash_override=None)
    assert after['content_hash'] == _hash("disk\n")


def test_unknown_disk_blob_age_proceeds(case):
    """If the disk content somehow has no content_blobs row, there is no
    evidence of staleness. Fail open, preserving prior behaviour, rather
    than blocking a write on missing metadata."""
    _, after = case(row_content="row\n", disk_content="mystery\n",
                    register_disk_blob=False)
    assert after['content_hash'] == _hash("mystery\n")


# --- mtime is the wrong signal ----------------------------------------

def test_stale_content_with_fresh_mtime_is_still_declined(case, tmp_path):
    """The reason this is not an mtime check.

    A materialise writes stale CONTENT with a brand-new mtime. Any
    implementation comparing file timestamps would see the stale copy as
    newer and overwrite the good write — exactly the original bug. The
    blob timestamp is a property of the content, so it is unmoved by
    rewriting the file.
    """
    returned, after = case(row_content="verified\n", disk_content="stale\n",
                           row_blob_at=NEW, disk_blob_at=OLD)
    assert after['content_hash'] == _hash("verified\n")


def test_deleted_file_still_marks_deleted(case, tmp_path):
    """The guard sits after the missing-file branch and must not shadow
    it: a file gone from disk is still a deletion, not a stale read."""
    _schema()
    _reset()
    pid = _project()
    _branch(pid)
    file_id = _file(pid, 'src/gone.py')
    h = _hash("had content\n")
    _blob(h, "had content\n", NEW)
    ws_id = _working_state(pid, file_id, h, 'modified')

    empty = tmp_path / "empty-checkout"
    empty.mkdir()
    returned = _run(ws_id, pid, 'src/gone.py', empty)

    after = query_one(
        "SELECT content_hash, state FROM vcs_working_state WHERE id = ?",
        (ws_id,))
    assert returned is None
    assert after['state'] == 'deleted'
    assert after['content_hash'] is None
