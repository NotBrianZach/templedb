#!/usr/bin/env python3
"""detect_changes must report a deletion once, not on every scan.

`vcs status --refresh` printed "Deleted: 28" for templedb and 268 for
bza, every single time it ran. The numbers never went down and the files
were never listed — the status listing renders the staged and modified
sets, so a deletion count had nowhere to appear. There was nothing to
act on and no way to make it drop.

The cause was one missing predicate: detect_changes loaded
`project_files WHERE project_id = ?` with no status filter, so rows
already recorded as `status='deleted'` were rediscovered as fresh
deletions forever. Of templedb's 26 contentless rows, 25 were already
marked deleted and 25 had real commit history — properly deleted files,
reported as news indefinitely.

The fix has a trap in it, which the resurrection tests below exist to
hold: project_files has UNIQUE(project_id, file_path), so the path->id
lookup must keep deleted rows even though deletion *detection* skips
them. Filter the map instead of the loop and re-creating a deleted file
dies on the constraint.
"""
import sys
from pathlib import Path

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
def project(tmp_path):
    """A project rooted at tmp_path with a working detect_changes."""
    _schema()
    _reset()

    execute("INSERT INTO projects (name, slug) VALUES ('dc', 'dc')")
    pid = query_one("SELECT id FROM projects WHERE slug = 'dc'")['id']
    execute("""INSERT INTO vcs_branches (project_id, branch_name, is_default)
               VALUES (?, 'main', 1)""", (pid,))
    execute("INSERT INTO file_types (type_name) VALUES ('python')")

    class Harness:
        project_id = pid
        project_root = tmp_path
        project_slug = 'dc'

        def track(self, rel, status='active'):
            """Put a row in project_files without touching disk."""
            ft = query_one("SELECT id FROM file_types LIMIT 1")['id']
            execute("""INSERT INTO project_files
                         (project_id, file_type_id, file_path, file_name, status)
                       VALUES (?, ?, ?, ?, ?)""",
                    (pid, ft, rel, Path(rel).name, status))
            return query_one("""SELECT id FROM project_files
                                 WHERE project_id = ? AND file_path = ?""",
                             (pid, rel))['id']

        def write(self, rel, text='content\n'):
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)

        def run(self):
            from importer import WorkingStateDetector
            return WorkingStateDetector('dc', str(tmp_path)).detect_changes()

        def status_of(self, rel):
            return query_one("""SELECT status FROM project_files
                                 WHERE project_id = ? AND file_path = ?""",
                             (pid, rel))['status']

        def ws_state(self, rel):
            row = query_one("""SELECT ws.state FROM vcs_working_state ws
                                 JOIN project_files pf ON pf.id = ws.file_id
                                WHERE pf.project_id = ? AND pf.file_path = ?""",
                            (pid, rel))
            return row['state'] if row else None

    return Harness()


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
        """CREATE TABLE IF NOT EXISTS file_contents (
               id INTEGER PRIMARY KEY AUTOINCREMENT, file_id INTEGER,
               content_hash TEXT, file_size_bytes INTEGER, line_count INTEGER,
               version INTEGER DEFAULT 1, is_current INTEGER DEFAULT 1)""",
        """CREATE TABLE IF NOT EXISTS vcs_branches (
               id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
               branch_name TEXT, is_default INTEGER DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS vcs_working_state (
               id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
               branch_id INTEGER, file_id INTEGER, content_hash TEXT,
               state TEXT, staged_by_session_id INTEGER,
               last_modified TEXT)""",
        """CREATE TABLE IF NOT EXISTS vcs_commits (
               id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
               branch_id INTEGER, commit_hash TEXT, commit_timestamp TEXT)""",
        """CREATE TABLE IF NOT EXISTS vcs_file_states (
               id INTEGER PRIMARY KEY AUTOINCREMENT, commit_id INTEGER,
               file_id INTEGER, content_hash TEXT, content_text TEXT,
               change_type TEXT)""",
    ):
        execute(stmt)


def _reset():
    for t in ('vcs_working_state', 'vcs_file_states', 'vcs_commits',
              'file_contents', 'project_files', 'content_blobs',
              'vcs_branches', 'file_types', 'projects'):
        execute(f"DELETE FROM {t}")


# --- the incident -----------------------------------------------------

def test_already_deleted_row_is_not_recounted(project):
    """The bug: a row already marked deleted, with no file on disk,
    counted as a fresh deletion on every single scan."""
    project.track('gone.py', status='deleted')
    assert project.run()['deleted'] == 0


def test_many_already_deleted_rows_stay_silent(project):
    """bza's 268. Same mechanism, and the reason the count looked
    alarming rather than merely wrong."""
    for i in range(25):
        project.track(f'old/gone{i}.py', status='deleted')
    assert project.run()['deleted'] == 0


def test_a_genuine_deletion_is_still_reported(project):
    """The whole point of the check. An active row whose file is gone
    must still be caught — that is the data-loss signal."""
    project.track('real.py', status='active')
    assert project.run()['deleted'] == 1
    assert project.ws_state('real.py') == 'deleted'


def test_deletion_is_reported_once_then_settles(project):
    """After the deletion is recorded and the status updated, a second
    scan should be quiet. This is the behaviour the count never had."""
    project.track('real.py', status='active')
    assert project.run()['deleted'] == 1
    execute("""UPDATE project_files SET status = 'deleted'
                WHERE project_id = ? AND file_path = 'real.py'""",
            (project.project_id,))
    assert project.run()['deleted'] == 0


# --- the trap the fix sets ---------------------------------------------

def test_recreating_a_deleted_file_does_not_violate_unique(project):
    """project_files has UNIQUE(project_id, file_path). If deleted rows
    were dropped from the path lookup instead of skipped in the deletion
    loop, this would take the 'new file' branch and fail the INSERT."""
    project.track('back.py', status='deleted')
    project.write('back.py')
    project.run()  # must not raise
    rows = query_all("""SELECT id FROM project_files
                         WHERE project_id = ? AND file_path = 'back.py'""",
                     (project.project_id,))
    assert len(rows) == 1, "should reuse the existing row, not insert a second"


def test_recreated_file_is_reactivated(project):
    """A file back on disk must return to status='active', or it stays
    invisible to `file ls`, checkout, and checkout_matches_db — all of
    which filter on active."""
    project.track('back.py', status='deleted')
    project.write('back.py')
    project.run()
    assert project.status_of('back.py') == 'active'


def test_active_file_on_disk_is_untouched(project):
    """The ordinary case must not acquire a status write."""
    project.track('here.py', status='active')
    project.write('here.py')
    project.run()
    assert project.status_of('here.py') == 'active'
