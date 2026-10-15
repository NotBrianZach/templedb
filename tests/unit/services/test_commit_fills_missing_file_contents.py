#!/usr/bin/env python3
"""A commit that records a content_hash must leave file_contents agreeing.

`_commit_modified_file` updated file_contents with a bare UPDATE ...
WHERE file_id = ? AND is_current = 1. On a row with no such file_contents
row that matched nothing and did nothing, while the vcs_file_states
insert a few lines below recorded the content_hash anyway. The commit
reported success, the blob landed in content_blobs, and the index never
pointed at it — a path-only row with history asserting the opposite.
The materializer INNER JOINs file_contents, so it omits the path; the
whole-tree scanner LEFT JOINs, so it finds the file absent from disk and
reads it as a deletion.

Reachable from an ordinary sequence, not a corrupt DB, which is why this
is a regression test and not a defensive one. The importer indexes an
untracked file it scans into project_files (plus content_blobs and
working state) WITHOUT a file_contents row — content is meant to land at
commit. So `vcs status --refresh` then commit takes the MODIFIED branch,
because the row exists and its hash is NULL while the disk hash is not,
rather than the ADDED branch that would have inserted the row.

Reproduced 2026-10-13 by committing the change that introduced
src/cli/commit_message.py: it landed as an active row with no current
content, recorded in vcs_file_states as 'modified', and
`doctor entities --check active_files_have_current_content` went red on
it. tests/test_write_path_regressions.py already asserted this invariant
but only over the `file set` route, which writes content directly.
"""
import sys
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

from db_utils import execute, query_one, query_all


@pytest.fixture(scope="module", autouse=True)
def _isolated_db(module_db):
    """This module hand-builds a partial schema; keep it out of the shared DB."""


@pytest.fixture
def committer():
    """A CommitCommand with the two tables _commit_modified_file writes.

    vcs_repo is mocked: record_file_change and the vcs_file_states
    insert are a different concern, and standing their schema up would
    make this test about more than the one statement it is pinning.
    """
    def _drop():
        for t in ('file_contents', 'content_blobs', 'project_files',
                  'vcs_working_state'):
            execute(f"DROP TABLE IF EXISTS {t}")
    _drop()
    for stmt in (
        """CREATE TABLE project_files (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               project_id INTEGER NOT NULL, file_path TEXT NOT NULL,
               status TEXT DEFAULT 'active')""",
        """CREATE TABLE content_blobs (
               hash_sha256 TEXT PRIMARY KEY, content_text TEXT,
               content_blob BLOB, content_type TEXT, encoding TEXT,
               file_size_bytes INTEGER)""",
        """CREATE TABLE file_contents (
               id INTEGER PRIMARY KEY AUTOINCREMENT, file_id INTEGER,
               content_hash TEXT, file_size_bytes INTEGER, line_count INTEGER,
               version INTEGER DEFAULT 1, is_current INTEGER DEFAULT 1,
               updated_at TEXT)""",
        # _commit_modified_file finishes by retiring the working-state
        # row for the content it just committed (_settle_working_state).
        """CREATE TABLE vcs_working_state (
               id INTEGER PRIMARY KEY AUTOINCREMENT, file_id INTEGER,
               content_hash TEXT, state TEXT, staged_by_session_id INTEGER)""",
    ):
        execute(stmt)

    from cli.commands.commit import CommitCommand, FileChange
    cmd = CommitCommand()
    cmd.vcs_repo = Mock()

    class Harness:
        command = cmd

        def tracked_row(self, rel='new.py'):
            execute("INSERT INTO project_files (project_id, file_path, "
                    "status) VALUES (1, ?, 'active')", (rel,))
            return query_one("SELECT id FROM project_files WHERE "
                             "file_path = ?", (rel,))['id']

        def change(self, file_id, rel, text):
            content = Mock()
            content.hash_sha256 = __import__('hashlib').sha256(
                text.encode()).hexdigest()
            content.content_text = text
            content.content_type = 'text'
            content.encoding = 'utf-8'
            content.file_size = len(text)
            content.line_count = text.count('\n')
            return FileChange(change_type='modified', file_path=rel,
                              file_id=file_id, old_hash=None, content=content)

        def current(self, file_id):
            return query_all("SELECT content_hash, version FROM file_contents "
                             "WHERE file_id = ? AND is_current = 1", (file_id,))

    yield Harness()
    _drop()


def test_a_row_with_no_file_contents_gets_one(committer):
    """The bug. An UPDATE matching nothing used to be the whole write."""
    fid = committer.tracked_row('new.py')
    change = committer.change(fid, 'new.py', 'fresh content\n')

    committer.command._commit_modified_file(1, 1, change)

    rows = committer.current(fid)
    assert len(rows) == 1, "the commit must leave current content behind"
    assert rows[0]['content_hash'] == change.content.hash_sha256


def test_the_blob_is_stored_too(committer):
    """Without this the restored row would point at nothing — the
    content_blobs FK is what makes the index resolvable."""
    fid = committer.tracked_row('new.py')
    change = committer.change(fid, 'new.py', 'fresh content\n')

    committer.command._commit_modified_file(1, 1, change)

    blob = query_one("SELECT content_text FROM content_blobs WHERE "
                     "hash_sha256 = ?", (change.content.hash_sha256,))
    assert blob and blob['content_text'] == 'fresh content\n'


def test_an_existing_row_is_updated_not_duplicated(committer):
    """The ordinary path must be unchanged: one current row, version
    bumped. An unconditional INSERT would leave two is_current rows and
    make `file cat` depend on which one a query happened to pick."""
    fid = committer.tracked_row('tracked.py')
    first = committer.change(fid, 'tracked.py', 'v1\n')
    committer.command._commit_modified_file(1, 1, first)
    second = committer.change(fid, 'tracked.py', 'v2\n')
    committer.command._commit_modified_file(1, 2, second)

    rows = committer.current(fid)
    assert len(rows) == 1, "exactly one current row"
    assert rows[0]['content_hash'] == second.content.hash_sha256
    assert rows[0]['version'] == 2, "version still increments"


# --- a file added after the workspace was cut is not a deletion -------
#
# Walked into on 2026-10-13. A parallel session added
# tests/test_mojibake_guard.py while this workspace was open, and
# committing the workspace tombstoned it: the whole-tree scan found a
# tracked path absent from disk and called it a deletion. One file, so
# the mass-deletion guard could not help — its floor is 10, right for
# catching a wrong directory and useless against a tree that is merely a
# few hours old. classify_edit_tree already separates this case out as
# `absent` ("the ordinary shape of a tree cut before a commit added
# files"); the commit scanner did not consult the same reasoning.


@pytest.fixture
def scanner_db():
    """project_files + content_blobs + file_contents + checkouts.

    Enough for _added_after_workspace_was_cut, which dates a path's
    current blob against the checkouts row for the directory being
    diffed.
    """
    def _drop():
        for t in ('file_contents', 'content_blobs', 'project_files',
                  'checkouts'):
            execute(f"DROP TABLE IF EXISTS {t}")
    _drop()
    for stmt in (
        """CREATE TABLE project_files (
               id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
               file_path TEXT, status TEXT DEFAULT 'active')""",
        """CREATE TABLE content_blobs (
               hash_sha256 TEXT PRIMARY KEY, created_at TEXT)""",
        """CREATE TABLE file_contents (
               id INTEGER PRIMARY KEY AUTOINCREMENT, file_id INTEGER,
               content_hash TEXT, is_current INTEGER DEFAULT 1)""",
        # Every column get_by_path SELECTs. A short table here made the
        # lookup raise "no such column: branch_name", which
        # _added_after_workspace_was_cut catches and treats as "cannot
        # date it" — so the guard silently did nothing and the first run
        # of these tests failed for a reason that had nothing to do with
        # the logic under test.
        """CREATE TABLE checkouts (
               id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
               checkout_path TEXT, branch_name TEXT DEFAULT 'main',
               checkout_at TEXT, last_sync_at TEXT,
               is_active INTEGER DEFAULT 1, kind TEXT DEFAULT 'edit')""",
    ):
        execute(stmt)

    from cli.commands.commit import CommitCommand

    class Harness:
        command = CommitCommand()
        project_id = 1

        def workspace(self, path, cut_at):
            execute("INSERT INTO checkouts (project_id, checkout_path, "
                    "checkout_at) VALUES (1, ?, ?)", (str(path), cut_at))

        def tracked(self, rel, blob_created):
            execute("INSERT INTO content_blobs (hash_sha256, created_at) "
                    "VALUES (?, ?)", (f'hash-{rel}', blob_created))
            execute("INSERT INTO project_files (project_id, file_path) "
                    "VALUES (1, ?)", (rel,))
            fid = query_one("SELECT id FROM project_files WHERE file_path=?",
                            (rel,))['id']
            execute("INSERT INTO file_contents (file_id, content_hash, "
                    "is_current) VALUES (?, ?, 1)", (fid, f'hash-{rel}'))

        def postdates(self, ws, rel):
            return self.command._added_after_workspace_was_cut(1, ws, rel)

    yield Harness()
    _drop()


def test_a_file_added_after_the_cut_is_not_a_deletion(scanner_db, tmp_path):
    """test_mojibake_guard.py, in one assertion."""
    scanner_db.workspace(tmp_path, '2026-10-13 14:18:00')
    scanner_db.tracked('tests/test_mojibake_guard.py', '2026-10-13 18:46:00')
    assert scanner_db.postdates(tmp_path, 'tests/test_mojibake_guard.py')


def test_a_file_that_predates_the_cut_still_deletes(scanner_db, tmp_path):
    """The property this must not weaken. A file that WAS in the tree and
    is now gone is a real deletion — that is the data-loss signal the
    whole scan exists to produce."""
    scanner_db.workspace(tmp_path, '2026-10-13 14:18:00')
    scanner_db.tracked('src/old.py', '2026-10-01 09:00:00')
    assert not scanner_db.postdates(tmp_path, 'src/old.py')


def test_an_unregistered_directory_does_not_suppress(scanner_db, tmp_path):
    """A plain scratch copy has no checkouts row and therefore no
    checkout_at to compare against. Declining to guess is the
    conservative half: a tree nobody registered is one nothing can
    vouch for, so the deletion stands."""
    scanner_db.tracked('src/old.py', '2026-10-13 18:46:00')
    assert not scanner_db.postdates(tmp_path, 'src/old.py')


def test_another_projects_path_is_not_consulted(scanner_db, tmp_path):
    """The blob-age lookup is project-scoped. Two projects routinely hold
    the same relative path, and an unrelated project's newer copy must
    not suppress a real deletion here."""
    scanner_db.workspace(tmp_path, '2026-10-13 14:18:00')
    execute("INSERT INTO content_blobs (hash_sha256, created_at) "
            "VALUES ('other', '2026-10-13 20:00:00')")
    execute("INSERT INTO project_files (project_id, file_path) "
            "VALUES (2, 'src/shared.py')")
    fid = query_one("SELECT id FROM project_files WHERE project_id=2")['id']
    execute("INSERT INTO file_contents (file_id, content_hash, is_current) "
            "VALUES (?, 'other', 1)", (fid,))
    assert not scanner_db.postdates(tmp_path, 'src/shared.py')
