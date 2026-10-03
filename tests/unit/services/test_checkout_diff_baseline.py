#!/usr/bin/env python3
"""checkout-diff compares against the database, not checkout_snapshots.

`project checkout-diff` printed a `File: <path>` header for files whose
diff body was then empty. It decided "modified" by comparing the file on
disk to `checkout_snapshots.content_hash` — what the file looked like
when it was last materialised into that tree — but printed a diff of
`file_contents` (current DB) against disk. Those are different
questions, so the two disagreed whenever the DB moved on: edit a file in
a workspace, commit it, and the snapshot still held the pre-edit hash
while DB and disk already agreed. Header printed, zero hunks.

Measured 2026-10-03 on a 789-file checkout: 24 files had
snapshot != db_current, nearly all untouched in that tree. That made the
"changed files" count unusable as a has-uncommitted-work signal, which is
exactly what it gets reached for before deleting a workspace.

The fix gates on the same comparison the diff displays.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

from cli.commands.checkout import CheckoutCommand


COMMITTED = "def f():\n    return 1\n"
STALE_SNAPSHOT_HASH = "0" * 64
LOCAL_EDIT = "def f():\n    return 2\n"


def _cmd(tmp_path, local_text, db_text, monkeypatch,
         snapshot_text=None, since_checkout=False):
    """A CheckoutCommand whose repos are stubbed to one file.

    `snapshot_text` is what was materialised into the tree. Left unset it
    defaults to a hash that matches nothing, so any implementation still
    gating the default path on checkout_snapshots reports the file as
    changed and then prints an empty diff.
    """
    import hashlib

    checkout_dir = tmp_path / "ws"
    checkout_dir.mkdir()
    (checkout_dir / "a.py").write_text(local_text)

    if snapshot_text is None:
        snap_hash, snap_body = STALE_SNAPSHOT_HASH, None
    else:
        snap_hash = hashlib.sha256(snapshot_text.encode()).hexdigest()
        snap_body = snapshot_text

    cmd = CheckoutCommand()
    cmd.project_repo = SimpleNamespace(get_by_slug=lambda slug: {'id': 1})
    cmd.checkout_repo = SimpleNamespace(
        get_by_path=lambda pid, path: {'id': 7},
        query_all=lambda sql, params: [{
            'file_path': 'a.py',
            'content_hash': snap_hash,
            'content_text': snap_body,
            'content_blob': None,
            'content_type': 'text',
        }],
    )

    cmd.file_repo = SimpleNamespace(get_files_for_project=lambda pid, include_content: [{
        'file_path': 'a.py',
        'file_id': 1,
        'content_type': 'text',
        'content_text': db_text,
        'content_blob': None,
        'content_hash': hashlib.sha256(db_text.encode()).hexdigest(),
    }])

    args = SimpleNamespace(project_slug='p', checkout_path=str(checkout_dir),
                           file=None, since_checkout=since_checkout)
    return cmd, args


def test_file_matching_db_is_not_reported(tmp_path, monkeypatch, capsys):
    """Disk == DB is not a difference, even with a stale snapshot row.

    This is the regression: the snapshot hash below never matches, so the
    pre-fix gate fired and printed a header for an empty diff.
    """
    cmd, args = _cmd(tmp_path, COMMITTED, COMMITTED, monkeypatch)

    assert cmd.diff(args) == 0

    out = capsys.readouterr().out
    assert 'File: a.py' not in out
    assert 'No differences' in out


def test_file_differing_from_db_is_reported_with_hunks(tmp_path, monkeypatch, capsys):
    """A real edit still reports, and the body is non-empty."""
    cmd, args = _cmd(tmp_path, LOCAL_EDIT, COMMITTED, monkeypatch)

    assert cmd.diff(args) == 0

    out = capsys.readouterr().out
    assert 'File: a.py' in out
    assert 'return 2' in out      # the local side of the hunk
    assert 'return 1' in out      # the database side
    assert '1 file differ' in out


def test_header_never_appears_without_a_hunk(tmp_path, monkeypatch, capsys):
    """The invariant the bug violated, stated directly.

    Every `File:` header must be followed by at least one diff line. Any
    future baseline drift reintroducing a no-op header fails here.
    """
    for i, (local, db) in enumerate(((COMMITTED, COMMITTED), (LOCAL_EDIT, COMMITTED))):
        base = tmp_path / f"case{i}"
        base.mkdir()
        cmd, args = _cmd(base, local, db, monkeypatch)
        cmd.diff(args)
        out = capsys.readouterr().out
        if 'File: a.py' in out:
            body = out.split('File: a.py', 1)[1]
            assert any(l.lstrip('\033[0123456789;m').startswith(('+', '-', '@'))
                       for l in body.splitlines()), f"header with no hunk for {local!r}"


def test_since_checkout_reports_a_local_edit_the_db_already_has(tmp_path, monkeypatch, capsys):
    """The question the default baseline cannot answer.

    A file edited here and then committed is identical to the DB, so the
    default says nothing — correctly, committing this tree would change
    nothing. But the edit did happen here, and that is what you need to
    know before deleting the workspace.
    """
    cmd, args = _cmd(tmp_path, LOCAL_EDIT, LOCAL_EDIT, monkeypatch,
                     snapshot_text=COMMITTED, since_checkout=True)

    assert cmd.diff(args) == 0

    out = capsys.readouterr().out
    assert 'File: a.py' in out
    assert 'at checkout' in out       # baseline is labelled, not implied
    assert 'return 1' in out          # what was materialized
    assert 'return 2' in out          # what is on disk now
    assert '1 file differ' in out


def test_since_checkout_is_silent_on_an_untouched_file(tmp_path, monkeypatch, capsys):
    """Disk == what was materialized here: nothing was edited in this tree.

    True even though the DB has moved on, which is the case that made the
    default baseline's count unusable as a has-local-work signal.
    """
    cmd, args = _cmd(tmp_path, COMMITTED, "def f():\n    return 99\n", monkeypatch,
                     snapshot_text=COMMITTED, since_checkout=True)

    assert cmd.diff(args) == 0

    out = capsys.readouterr().out
    assert 'File: a.py' not in out
    assert 'No differences' in out


def test_db_file_without_current_content_is_skipped(tmp_path, monkeypatch, capsys):
    """A DB row with no current content has nothing to diff against.

    Deleted migrations leave exactly this shape. Comparing a real hash to
    None would report every such file as changed forever.
    """
    checkout_dir = tmp_path / "ws2"
    checkout_dir.mkdir()
    (checkout_dir / "a.py").write_text(COMMITTED)

    cmd = CheckoutCommand()
    cmd.project_repo = SimpleNamespace(get_by_slug=lambda slug: {'id': 1})
    cmd.checkout_repo = SimpleNamespace(
        get_by_path=lambda pid, path: {'id': 7},
        query_all=lambda sql, params: [],
    )
    cmd.file_repo = SimpleNamespace(get_files_for_project=lambda pid, include_content: [{
        'file_path': 'a.py',
        'file_id': 1,
        'content_type': 'text',
        'content_text': None,
        'content_blob': None,
        'content_hash': None,
    }])

    args = SimpleNamespace(project_slug='p', checkout_path=str(checkout_dir), file=None)
    assert cmd.diff(args) == 0

    out = capsys.readouterr().out
    assert 'File: a.py' not in out
    assert 'No differences' in out
