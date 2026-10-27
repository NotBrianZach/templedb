"""`file set --if-match` rebases a stale base instead of refusing it.

`--if-match HASH` means "my content is HASH plus my changes", which is a
patch in everything but shape. The old behaviour on a moved base was an
unconditional exit 2, leaving the caller two bad options: redo the work,
or drop the guard — and dropping the guard is what silently reverts
people (CLAUDE.md hazard 1). So a stale base now gets three-way merged
onto what landed, and only a genuine line overlap refuses.

Tested at the `_rebase_onto_current` level rather than through
`subprocess.run(['templedb', ...])` like the neighbouring write-path
tests. Those exercise the *installed* binary, which lags the DB by a
rebuild, so a subprocess test of a brand-new flag asserts against code
that is not running yet and fails for a reason that has nothing to do
with the behaviour under test.

The invariant these all protect: this helper may return merged content
only when nothing was lost. Every other outcome must be None, because
None makes the caller refuse the write, and refusing is always safe.
"""
import hashlib
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
from db_utils import query_one
from repositories.base import BaseRepository


@pytest.fixture(scope="module")
def rebase_db(module_db):
    """Schema in a DB of this module's own. See the identical fixture in
    test_write_path_regressions.py for why this is not shared."""
    db_path = module_db
    schema_sql = (Path(__file__).parent.parent / "migrations" /
                  "schema.sql").read_text()
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    conn.commit()
    conn.close()
    yield db_path


def _put_blob(text, storage_location='inline', as_text=True):
    """Insert a content_blobs row and return its hash."""
    h = hashlib.sha256(text.encode('utf-8')).hexdigest()
    BaseRepository().execute(
        """INSERT OR IGNORE INTO content_blobs
               (hash_sha256, content_text, content_type, encoding,
                file_size_bytes, reference_count, storage_location)
             VALUES (?, ?, 'text', 'utf-8', ?, 0, ?)""",
        (h, text if as_text else None, len(text.encode()), storage_location),
    )
    return h


def _cmd(rebase_db):
    from cli.commands.file import FileCommands
    return FileCommands()


BASE = "alpha\nbravo\ncharlie\ndelta\necho\n"


class TestRebaseSucceedsWhenNothingIsLost:

    def test_disjoint_edits_both_survive(self, rebase_db):
        """The case the whole change exists for: two agents edit opposite
        ends of one file. Neither should have to redo its work."""
        base_h = _put_blob(BASE)
        theirs = BASE.replace("echo", "ECHO THEIRS")
        theirs_h = _put_blob(theirs)
        mine = BASE.replace("alpha", "ALPHA MINE")

        got = _cmd(rebase_db)._rebase_onto_current(
            file_path="t.txt", base_prefix=base_h[:12],
            current_hash=theirs_h, incoming=mine,
        )
        assert got is not None, "disjoint edits must rebase cleanly"
        merged, used_base = got
        assert used_base == base_h
        assert "ALPHA MINE" in merged, "my edit was dropped"
        assert "ECHO THEIRS" in merged, "their edit was reverted"
        assert "bravo" in merged and "delta" in merged

    def test_accepts_a_short_base_prefix(self, rebase_db):
        """Every surface that prints a hash truncates it, so the prefix
        form has to work here too or the flag is unusable in practice."""
        base_h = _put_blob(BASE)
        theirs_h = _put_blob(BASE.replace("echo", "ECHO2"))
        got = _cmd(rebase_db)._rebase_onto_current(
            file_path="t.txt", base_prefix=base_h[:8],
            current_hash=theirs_h, incoming=BASE.replace("alpha", "A2"),
        )
        assert got is not None
        assert got[1] == base_h


class TestRebaseRefusesWhenAnythingCouldBeLost:

    def test_overlapping_edits_refuse(self, rebase_db):
        """Both sides rewrote the same line. There is no answer that
        keeps both, so this must fall through to the caller's exit 2."""
        base_h = _put_blob(BASE)
        theirs_h = _put_blob(BASE.replace("charlie", "CHARLIE THEIRS"))
        got = _cmd(rebase_db)._rebase_onto_current(
            file_path="t.txt", base_prefix=base_h[:12],
            current_hash=theirs_h,
            incoming=BASE.replace("charlie", "CHARLIE MINE"),
        )
        assert got is None, "an overlapping edit must not be auto-merged"

    def test_never_returns_conflict_markers(self, rebase_db):
        """`file set` writes whatever it is handed straight into
        file_contents, so returning marker text would commit '<<<<<<<'
        as the file's content — worse than refusing."""
        base_h = _put_blob(BASE)
        theirs_h = _put_blob(BASE.replace("charlie", "CHARLIE THEIRS"))
        got = _cmd(rebase_db)._rebase_onto_current(
            file_path="t.txt", base_prefix=base_h[:12],
            current_hash=theirs_h,
            incoming=BASE.replace("charlie", "CHARLIE MINE"),
        )
        assert got is None or "<<<<<<<" not in got[0]

    def test_missing_base_blob_refuses(self, rebase_db):
        """A base that has been gc'd cannot be reconstructed. Guessing
        the ancestor is how a two-way merge gets mistaken for a
        three-way one."""
        theirs_h = _put_blob(BASE.replace("echo", "ECHO3"))
        absent = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
        got = _cmd(rebase_db)._rebase_onto_current(
            file_path="t.txt", base_prefix=absent[:12],
            current_hash=theirs_h, incoming=BASE.replace("alpha", "A3"),
        )
        assert got is None

    def test_non_inline_base_refuses(self, rebase_db):
        """An externally-stored blob has no content_text to merge. The
        row exists, so this is the case that would read as an empty base
        rather than a missing one."""
        external = "ext-" + uuid.uuid4().hex + "\n"
        base_h = _put_blob(external, storage_location='external',
                           as_text=False)
        theirs_h = _put_blob(BASE.replace("echo", "ECHO4"))
        got = _cmd(rebase_db)._rebase_onto_current(
            file_path="t.txt", base_prefix=base_h[:12],
            current_hash=theirs_h, incoming=BASE.replace("alpha", "A4"),
        )
        assert got is None

    def test_incoming_already_contained_refuses(self, rebase_db):
        """If the merge reproduces current content exactly, nothing of
        the incoming edit survived. Reporting success would claim the
        edit landed when it did not."""
        base_h = _put_blob(BASE)
        theirs = BASE.replace("alpha", "ALPHA MINE")
        theirs_h = _put_blob(theirs)
        # Someone already applied precisely my change.
        got = _cmd(rebase_db)._rebase_onto_current(
            file_path="t.txt", base_prefix=base_h[:12],
            current_hash=theirs_h, incoming=theirs,
        )
        assert got is None, "a no-op rebase must not report success"

    def test_short_or_junk_prefix_refuses(self, rebase_db):
        """Guards against a LIKE pattern built from unvalidated input
        matching an unrelated blob."""
        theirs_h = _put_blob(BASE.replace("echo", "ECHO5"))
        cmd = _cmd(rebase_db)
        for bad in ("", "abc", "zzzzzzzzzz", "' OR 1=1 --"):
            got = cmd._rebase_onto_current(
                file_path="t.txt", base_prefix=bad,
                current_hash=theirs_h, incoming=BASE,
            )
            assert got is None, f"prefix {bad!r} must not resolve a base"


class TestBlobTextHelper:

    def test_reads_inline_text_by_prefix(self, rebase_db):
        h = _put_blob("hello blob\n")
        assert _cmd(rebase_db)._blob_text(h[:10]) == "hello blob\n"

    def test_rejects_short_and_non_hex(self, rebase_db):
        cmd = _cmd(rebase_db)
        assert cmd._blob_text("abc") is None
        assert cmd._blob_text("nothexnothex") is None
        assert cmd._blob_text(None) is None


class TestIntentApplyRebasesAStaleProposal:
    """`intent apply` had no base check at all.

    It pointed file_contents straight at new_content_hash and retired
    whatever was current, so applying a proposal written against older
    content silently reverted everything landed in between. That gap is
    worse here than in `file set`: an intent is *designed* to outlive the
    state it was written against, so a stale base is the normal case over
    any real interval rather than an edge case.
    """

    @staticmethod
    def _project():
        import uuid
        slug = f"intent-rebase-{uuid.uuid4().hex[:8]}"
        base = BaseRepository()
        pid = base.execute(
            "INSERT INTO projects (slug, name) VALUES (?, ?)",
            (slug, "intent rebase"),
        )
        base.execute(
            "INSERT INTO vcs_branches (project_id, branch_name, is_default) "
            "VALUES (?, 'main', 1)", (pid,),
        )
        return pid, slug

    @staticmethod
    def _file_with(pid, path, text):
        """Register `path` in the project with `text` as current content."""
        base = BaseRepository()
        ft = query_one("SELECT id FROM file_types LIMIT 1")
        if not ft:
            base.execute(
                "INSERT INTO file_types (type_name, category) "
                "VALUES ('t', 'test')", ())
            ft = query_one("SELECT id FROM file_types LIMIT 1")
        fid = base.execute(
            "INSERT INTO project_files "
            "(project_id, file_type_id, file_path, file_name, status) "
            "VALUES (?, ?, ?, ?, 'active')", (pid, ft['id'], path, path),
        )
        h = _put_blob(text)
        base.execute(
            "INSERT INTO file_contents "
            "(file_id, content_hash, file_size_bytes, is_current) "
            "VALUES (?, ?, ?, 1)", (fid, h, len(text.encode())),
        )
        return fid, h

    @staticmethod
    def _propose(pid, path, base_hash, text):
        h = _put_blob(text)
        iid = BaseRepository().execute(
            """INSERT INTO edit_intents
                   (project_id, file_path, base_revision, new_content_hash,
                    patch_summary, author, description, status)
                 VALUES (?, ?, ?, ?, 'proposed', 'test', 'test',
                         'proposed')""",
            (pid, path, base_hash, h),
        )
        return iid, h

    @staticmethod
    def _apply(iid, no_rebase=False):
        import argparse
        from cli.commands.intent import IntentCommands
        args = argparse.Namespace(id=str(iid), no_rebase=no_rebase)
        return IntentCommands().apply(args)

    @staticmethod
    def _current_text(fid):
        row = query_one(
            """SELECT cb.content_text FROM file_contents fc
                   JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
                  WHERE fc.file_id = ? AND fc.is_current = 1""", (fid,))
        return row['content_text'] if row else None

    def test_disjoint_proposal_rebases_and_keeps_both(self, rebase_db):
        pid, _ = self._project()
        fid, base_h = self._file_with(pid, "a.txt", BASE)
        iid, proposed_h = self._propose(
            pid, "a.txt", base_h, BASE.replace("alpha", "ALPHA INTENT"))
        # The file moves after the proposal was written.
        moved = BASE.replace("echo", "ECHO LANDED")
        moved_h = _put_blob(moved)
        BaseRepository().execute(
            "UPDATE file_contents SET content_hash = ? "
            "WHERE file_id = ? AND is_current = 1", (moved_h, fid))

        assert self._apply(iid) == 0
        got = self._current_text(fid)
        assert "ALPHA INTENT" in got, "the proposal was dropped"
        assert "ECHO LANDED" in got, "the concurrent write was reverted"

        row = query_one("SELECT * FROM edit_intents WHERE id = ?", (iid,))
        assert row['status'] == 'applied'
        # The proposal itself must survive verbatim -- it is the only
        # record of what the author actually wrote.
        assert row['new_content_hash'] == proposed_h
        assert row['base_revision'] == base_h
        assert 'rebased onto' in row['patch_summary']
        assert 'applied as' in row['patch_summary']

    def test_overlapping_proposal_refuses_and_changes_nothing(self, rebase_db):
        pid, _ = self._project()
        fid, base_h = self._file_with(pid, "b.txt", BASE)
        iid, _ = self._propose(
            pid, "b.txt", base_h, BASE.replace("charlie", "CHARLIE INTENT"))
        moved = BASE.replace("charlie", "CHARLIE LANDED")
        moved_h = _put_blob(moved)
        BaseRepository().execute(
            "UPDATE file_contents SET content_hash = ? "
            "WHERE file_id = ? AND is_current = 1", (moved_h, fid))

        assert self._apply(iid) == 4
        assert self._current_text(fid) == moved, "file must be untouched"
        row = query_one("SELECT status FROM edit_intents WHERE id = ?", (iid,))
        assert row['status'] == 'proposed', (
            "a refused apply must leave the intent applicable"
        )

    def test_no_rebase_refuses_even_when_mergeable(self, rebase_db):
        pid, _ = self._project()
        fid, base_h = self._file_with(pid, "c.txt", BASE)
        iid, _ = self._propose(
            pid, "c.txt", base_h, BASE.replace("alpha", "ALPHA INTENT"))
        moved = BASE.replace("echo", "ECHO LANDED")
        moved_h = _put_blob(moved)
        BaseRepository().execute(
            "UPDATE file_contents SET content_hash = ? "
            "WHERE file_id = ? AND is_current = 1", (moved_h, fid))

        assert self._apply(iid, no_rebase=True) == 4
        assert self._current_text(fid) == moved

    def test_unmoved_base_applies_as_proposed(self, rebase_db):
        """The common case must stay byte-identical to the old path: no
        merge, no rebase note, content exactly as proposed."""
        pid, _ = self._project()
        fid, base_h = self._file_with(pid, "d.txt", BASE)
        want = BASE.replace("alpha", "ALPHA INTENT")
        iid, proposed_h = self._propose(pid, "d.txt", base_h, want)

        assert self._apply(iid) == 0
        assert self._current_text(fid) == want
        row = query_one("SELECT * FROM edit_intents WHERE id = ?", (iid,))
        assert row['new_content_hash'] == proposed_h
        assert 'rebased onto' not in (row['patch_summary'] or '')

    def test_sentinel_base_revisions_do_not_trigger_a_rebase(self, rebase_db):
        """'current' and 'new-file' are sentinels, not hashes -- 886 early
        rows carry the literal 'current'. Treating them as a stale base
        would send every one of those through a merge against nothing."""
        for sentinel in ('current', 'new-file'):
            pid, _ = self._project()
            fid, _ = self._file_with(pid, "e.txt", BASE)
            want = BASE.replace("alpha", f"ALPHA {sentinel}")
            iid, proposed_h = self._propose(pid, "e.txt", sentinel, want)
            assert self._apply(iid) == 0
            assert self._current_text(fid) == want
            row = query_one(
                "SELECT patch_summary FROM edit_intents WHERE id = ?", (iid,))
            assert 'rebased onto' not in (row['patch_summary'] or '')
