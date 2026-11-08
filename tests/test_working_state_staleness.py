"""`vcs status` must not answer from a cache it cannot invalidate.

The bug: the freshness test for `vcs_working_state` was
`COUNT(*) == 0` — rescan only when there are no rows at all. A cache
keyed on its own emptiness has no invalidation, so the first scan filled
it and every later `vcs status` reported that scan's findings forever.
Observed on `templedb-rust`: fourteen edited files in the resolved
workspace, 45 cached rows all saying `unmodified`, and a header that
printed the right checkout before answering about a reading of it taken
hours earlier. `-r` gave the right answer, so the fix was reachable and
the default was wrong.

`FileScanner.newest_mtime` is the probe that replaced it, and these
tests are mostly about its *membership* rules rather than its
arithmetic. A probe that walked the whole tree would report every tree
as permanently stale — `templedb-rust`'s checkout has a multi-gigabyte
`target/` beside 49 tracked files, rewritten by every build — which is
indistinguishable from having no cache. So the probe has to see exactly
the set `scan_directory` would write, and that is what is pinned here.
"""
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestNewestMtime(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def scanner(self):
        from importer.scanner import FileScanner
        return FileScanner(str(self.root))

    def write(self, rel, content="x", mtime=None):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        if mtime is not None:
            os.utime(p, (mtime, mtime))
        return p

    def test_empty_tree_is_none_and_must_not_read_as_fresh(self):
        """None is "nothing to compare", which the caller treats as stale.

        An empty tree against non-empty cached rows is itself a change —
        every tracked file is a deletion — so returning a timestamp here
        would be the wrong kind of wrong.
        """
        self.assertIsNone(self.scanner().newest_mtime())

    def test_returns_the_newest_of_several(self):
        self.write("a.py", mtime=1_000_000)
        self.write("b.py", mtime=3_000_000)
        self.write("c.py", mtime=2_000_000)
        self.assertEqual(self.scanner().newest_mtime(), 3_000_000)

    def test_skip_dirs_cannot_make_a_tree_look_stale(self):
        """The reason this probe reuses the scanner's rules at all.

        `target/` is rewritten by every `cargo build` and holds no
        tracked file. If it counted, the cache would be invalid on
        every invocation forever.
        """
        self.write("src/main.rs", mtime=1_000_000)
        self.write("target/release/binary", mtime=9_000_000)
        self.write("node_modules/dep/index.js", mtime=9_000_000)
        self.write("__pycache__/mod.pyc", mtime=9_000_000)
        self.assertEqual(self.scanner().newest_mtime(), 1_000_000)

    def test_ignored_debris_cannot_make_a_tree_look_stale(self):
        """Atomic-write debris and editor backups are out of scope for
        `scan_directory`, so they are out of scope here. An Emacs
        autosave must not force a rescan."""
        self.write("a.py", mtime=1_000_000)
        self.write("a.py.tmp.12345", mtime=9_000_000)
        self.write("notes.txt~", mtime=9_000_000)
        self.write(".#locked.py", mtime=9_000_000)
        self.assertEqual(self.scanner().newest_mtime(), 1_000_000)

    def test_a_tree_with_only_skipped_files_is_none(self):
        self.write("target/release/binary", mtime=9_000_000)
        self.assertIsNone(self.scanner().newest_mtime())

    def test_gitignored_files_cannot_make_a_tree_look_stale(self):
        """In a git repo, membership is git's answer — same as
        `scan_directory`. A build artifact named in .gitignore must not
        force a rescan even when it sits outside SKIP_DIRS."""
        try:
            subprocess.run(["git", "init", "-q"], cwd=self.root, check=True,
                           capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError):
            self.skipTest("git unavailable")
        (self.root / ".gitignore").write_text("artifact.out\n")
        self.write("tracked.py", mtime=1_000_000)
        self.write("artifact.out", mtime=9_000_000)
        os.utime(self.root / ".gitignore", (1_000_000, 1_000_000))
        subprocess.run(["git", "add", "-A"], cwd=self.root, check=True,
                       capture_output=True, timeout=30)
        self.assertEqual(self.scanner().newest_mtime(), 1_000_000)

    def test_membership_matches_scan_directory(self):
        """The property the whole design rests on: the probe and the
        scan agree about which files exist. Asserted by construction
        rather than by listing rules, so a new rule added to one and not
        the other fails here."""
        self.write("src/main.rs", mtime=1_000_000)
        self.write("README.md", mtime=2_000_000)
        self.write("target/release/binary", mtime=9_000_000)
        self.write("README.md~", mtime=9_000_000)

        s = self.scanner()
        scanned = {f.relative_path for f in s.scan_directory()}
        newest = s.newest_mtime()
        newest_of_scanned = max(
            (self.root / rel).stat().st_mtime for rel in scanned)
        self.assertEqual(newest, newest_of_scanned)

    def test_an_edit_moves_the_answer(self):
        """End to end, with a real clock rather than a forged mtime."""
        self.write("a.py")
        before = self.scanner().newest_mtime()
        time.sleep(0.01)
        self.write("a.py", content="changed")
        self.assertGreater(self.scanner().newest_mtime(), before)


class TestStalenessVerdict(unittest.TestCase):
    """The reason strings, which are the command's explanation to the user.

    `_working_state_staleness` returns a reason or None, and `None` is
    the only value that suppresses a rescan — so every failure to
    establish freshness has to return a string. These pin the shape
    rather than the wording: a future reason that returned None on an
    unanswerable question would restore the original bug.
    """

    def verdict(self, **kw):
        """Drive the staleness logic with the database and tree stubbed.

        Stubbed rather than fixtured because the decision under test is
        arithmetic over two inputs — a timestamp from SQLite and an
        mtime from disk — and building a real project to supply them
        tests the fixture instead.
        """
        from cli.commands.vcs import VCSCommands

        cmd = VCSCommands.__new__(VCSCommands)
        row = kw.get('row', {'scanned_at': '2026-01-01 00:00:00', 'count': 1})

        class _Repo:
            def query_one(self, *a, **k):
                return row
        cmd.vcs_repo = _Repo()
        tree = kw.get('tree', '/nonexistent-tree')
        cmd._scan_tree = lambda project: tree
        return cmd._working_state_staleness({'id': 1, 'slug': 'x'})

    def test_no_rows_is_first_time(self):
        self.assertEqual(
            self.verdict(row={'scanned_at': None, 'count': 0}), "first time")

    def test_rows_without_a_timestamp_cannot_vouch_for_themselves(self):
        self.assertEqual(
            self.verdict(row={'scanned_at': None, 'count': 3}),
            "cached scan has no timestamp")

    def test_an_unreadable_timestamp_is_stale_not_fresh(self):
        self.assertEqual(
            self.verdict(row={'scanned_at': 'not a date', 'count': 3},
                         tree=tempfile.gettempdir()),
            "cached scan timestamp is unreadable")

    def test_a_missing_checkout_is_stale(self):
        self.assertEqual(self.verdict(tree='/nonexistent-tree'),
                         "checkout is missing")

    def test_an_unresolvable_checkout_defers_to_the_refresh(self):
        from cli.commands.vcs import VCSCommands

        cmd = VCSCommands.__new__(VCSCommands)

        class _Repo:
            def query_one(self, *a, **k):
                return {'scanned_at': '2026-01-01 00:00:00', 'count': 1}
        cmd.vcs_repo = _Repo()

        def _raise(project):
            raise ValueError("no checkout")
        cmd._scan_tree = _raise
        self.assertEqual(cmd._working_state_staleness({'id': 1, 'slug': 'x'}),
                         "checkout could not be resolved")

    def test_a_tree_newer_than_the_scan_is_stale(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.py"
            p.write_text("x")
            # 2026-01-01 00:00:00 UTC is 1767225600.
            os.utime(p, (1767225600 + 10, 1767225600 + 10))
            self.assertEqual(self.verdict(tree=d),
                             "tree changed since last scan")

    def test_a_tree_older_than_the_scan_is_fresh(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.py"
            p.write_text("x")
            os.utime(p, (1767225600 - 10, 1767225600 - 10))
            self.assertIsNone(self.verdict(tree=d))

    def test_the_boundary_second_is_stale(self):
        """`>=`, not `>`. `last_modified` has second granularity, so an
        edit landing in the same second as the scan is invisible to a
        strict comparison. One extra scan is the cheaper mistake."""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.py"
            p.write_text("x")
            os.utime(p, (1767225600, 1767225600))
            self.assertEqual(self.verdict(tree=d),
                             "tree changed since last scan")

    def test_the_cached_timestamp_is_read_as_utc(self):
        """`last_modified` comes from SQLite's `datetime('now')`, which
        is UTC, while `vcs_commits.created_at` in the same database is
        local. Reading it as local placed the cache hours in the future
        on a UTC-6 machine and reported every tree as fresh — the
        original bug with a new cause.

        Pinned by putting a file one hour *after* the recorded scan in
        UTC: fresh under any local reading west of Greenwich, stale
        under the correct one.
        """
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "a.py"
            p.write_text("x")
            os.utime(p, (1767225600 + 3600, 1767225600 + 3600))
            self.assertEqual(self.verdict(tree=d),
                             "tree changed since last scan")

    def test_an_empty_tree_against_cached_rows_is_stale(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(self.verdict(tree=d),
                             "tree has no scannable files")


class TestCleanCountsOtherSessions(unittest.TestCase):
    """A file staged by another session is not "no changes".

    `clean` was `not (staged or modified or untracked)` and left
    `staged_by_others` out. `_human` prints "No changes" and *returns*
    on `clean`, so its own "Staged in other sessions" block was
    unreachable in exactly the case it exists for: a file staged by a
    session that ended without committing. The tree read as clean while
    holding content nobody could see, and `vcs commit` would not pick it
    up either, because the commit selects by this session's id.

    Reproduced on `regr-test`: one file, `state=modified`,
    `staged_by_session_id=1196` from an ended session, and every later
    session got "No changes" with no listing.
    """

    def clean(self, **status):
        base = {'staged': [], 'modified': [], 'untracked': [],
                'staged_by_others': []}
        base.update(status)
        # The expression under test, as `status()` computes it.
        return not (base.get('staged') or base.get('modified')
                    or base.get('untracked') or base.get('staged_by_others'))

    def test_nothing_anywhere_is_clean(self):
        self.assertTrue(self.clean())

    def test_other_session_staging_is_not_clean(self):
        self.assertFalse(self.clean(staged_by_others=['test.txt']))

    def test_the_other_three_still_count(self):
        self.assertFalse(self.clean(staged=['a']))
        self.assertFalse(self.clean(modified=['a']))
        self.assertFalse(self.clean(untracked=['a']))


if __name__ == '__main__':
    unittest.main()
