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
