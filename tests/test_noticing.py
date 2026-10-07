"""The 2026-10-07 batch: things that go wrong without anyone noticing.

Every defect fixed in this round was invisible for the same reason --
TempleDB records faithfully and notices almost nothing. These cover
the noticing, not the recording:

  no_long_uncommitted_content        78 files ahead of HEAD, oldest July
  baseline_rows_still_describe_reality  a ratchet that went stale
  publish push-gating                content on a public mirror with no
                                     commit row behind it
  dev-mode tree preference           running another session's workspace
  _check_dirty_and_prompt(--yes)     a skip-prompts flag that deadlocked

Standalone sqlite fixtures, matching tests/test_blob_gc.py and
tests/vcs/test_session_stage_orphans.py: migrations/schema.sql is
stale, and building only the tables under test keeps these honest
without waiting on that cleanup.
"""
import os
import sqlite3
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'src'))


class UncommittedContentTest(unittest.TestCase):
    """'modified' means differs from HEAD, not from file_contents.

    Confusing the two is what made 78 genuinely-uncommitted files look
    like a scanner false positive for a day.
    """

    SCHEMA = """
        CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT);
        CREATE TABLE project_files (id INTEGER PRIMARY KEY, project_id INTEGER,
            file_path TEXT, status TEXT DEFAULT 'active');
        CREATE TABLE file_contents (id INTEGER PRIMARY KEY, file_id INTEGER,
            content_hash TEXT, is_current BOOLEAN DEFAULT 1, updated_at TEXT);
        CREATE TABLE vcs_commits (id INTEGER PRIMARY KEY, commit_timestamp TEXT);
        CREATE TABLE vcs_file_states (id INTEGER PRIMARY KEY, commit_id INTEGER,
            file_id INTEGER, content_hash TEXT);
    """

    QUERY = """
        WITH head AS (
          SELECT v.file_id, v.content_hash,
                 ROW_NUMBER() OVER (PARTITION BY v.file_id
                     ORDER BY c.commit_timestamp DESC, c.id DESC) rn
            FROM vcs_file_states v JOIN vcs_commits c ON c.id = v.commit_id)
        SELECT p.slug, COUNT(*) AS n
          FROM file_contents fc
          JOIN project_files pf ON pf.id = fc.file_id
          JOIN projects p ON p.id = pf.project_id
          LEFT JOIN head h ON h.file_id = pf.id AND h.rn = 1
         WHERE fc.is_current = 1 AND pf.status = 'active'
           AND h.content_hash IS NOT NULL
           AND h.content_hash <> fc.content_hash
           AND fc.updated_at < datetime('now', '-14 days')
         GROUP BY p.slug
    """

    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.executescript(self.SCHEMA)
        self.c.execute("INSERT INTO projects VALUES (1,'proj')")
        self.c.execute("INSERT INTO vcs_commits VALUES (10,'2026-01-01')")

    def tearDown(self):
        self.c.close()

    def _file(self, fid, current, committed, updated='2026-01-01',
              status='active'):
        self.c.execute(
            "INSERT INTO project_files VALUES (?,1,?,?)",
            (fid, f'f{fid}.py', status))
        self.c.execute(
            "INSERT INTO file_contents (file_id, content_hash, updated_at) "
            "VALUES (?,?,?)", (fid, current, updated))
        if committed:
            self.c.execute(
                "INSERT INTO vcs_file_states (commit_id, file_id, content_hash) "
                "VALUES (10,?,?)", (fid, committed))

    def _run(self):
        return self.c.execute(self.QUERY).fetchall()

    def test_content_ahead_of_head_is_reported(self):
        self._file(1, current='new', committed='old')
        self.assertEqual(self._run(), [('proj', 1)])

    def test_content_equal_to_head_is_not(self):
        self._file(1, current='same', committed='same')
        self.assertEqual(self._run(), [])

    def test_never_committed_file_is_not_reported(self):
        """No HEAD to differ from. An added-but-uncommitted file is a
        different condition and would drown this check in noise."""
        self._file(1, current='new', committed=None)
        self.assertEqual(self._run(), [])

    def test_recent_edit_is_within_grace(self):
        self._file(1, current='new', committed='old',
                   updated='2099-01-01')
        self.assertEqual(self._run(), [])

    def test_inactive_file_is_ignored(self):
        self._file(1, current='new', committed='old', status='deleted')
        self.assertEqual(self._run(), [])

    def test_only_the_latest_commit_counts(self):
        """A file committed twice compares against the newer one."""
        self._file(1, current='v2', committed='v1')
        self.c.execute("INSERT INTO vcs_commits VALUES (11,'2026-06-01')")
        self.c.execute(
            "INSERT INTO vcs_file_states (commit_id, file_id, content_hash) "
            "VALUES (11,1,'v2')")
        self.assertEqual(self._run(), [])


class BaselineStalenessTest(unittest.TestCase):
    """A ratchet row that stopped being true must be reported.

    vcs_commits.git_commit_hash was recorded as all_null and then
    populated by migration 126 — the ratchet suppressed the very
    column that migration existed to fill, for three migrations.
    """

    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.executescript("""
            CREATE TABLE unmaintained_columns_baseline (
                id INTEGER PRIMARY KEY, table_name TEXT, column_name TEXT,
                shape TEXT, row_count_at_baseline INTEGER, reason TEXT,
                UNIQUE(table_name, column_name));
            CREATE TABLE demo (id INTEGER PRIMARY KEY, col TEXT);
        """)

    def tearDown(self):
        self.c.close()

    def _baseline(self, shape):
        self.c.execute(
            "INSERT INTO unmaintained_columns_baseline "
            "(table_name, column_name, shape, row_count_at_baseline) "
            "VALUES ('demo','col',?,0)", (shape,))

    def _stale(self):
        """Mirror of the check's core for one row."""
        row = self.c.execute(
            "SELECT shape FROM unmaintained_columns_baseline").fetchone()
        if not row:
            return False
        if row[0] == 'all_null':
            return self.c.execute(
                "SELECT COUNT(*) FROM demo WHERE col IS NOT NULL"
            ).fetchone()[0] > 0
        return self.c.execute(
            "SELECT COUNT(DISTINCT col) FROM demo").fetchone()[0] > 1

    def test_all_null_row_with_values_is_stale(self):
        self._baseline('all_null')
        self.c.execute("INSERT INTO demo (col) VALUES ('x')")
        self.assertTrue(self._stale())

    def test_all_null_row_still_null_is_fine(self):
        self._baseline('all_null')
        self.c.execute("INSERT INTO demo (col) VALUES (NULL)")
        self.assertFalse(self._stale())

    def test_constant_row_with_two_values_is_stale(self):
        self._baseline('constant')
        self.c.execute("INSERT INTO demo (col) VALUES ('a'),('b')")
        self.assertTrue(self._stale())

    def test_constant_row_still_constant_is_fine(self):
        self._baseline('constant')
        self.c.execute("INSERT INTO demo (col) VALUES ('a'),('a')")
        self.assertFalse(self._stale())

    def test_migration_129_clears_the_three_known_rows(self):
        mig = REPO / 'migrations' / '129_retire_stale_baseline_rows.sql'
        for t, col in (('relations', 'attributes_json'),
                       ('sync_relations', 'attributes_json'),
                       ('vcs_commits', 'git_commit_hash'),
                       ('keep_me', 'untouched')):
            self.c.execute(
                "INSERT INTO unmaintained_columns_baseline "
                "(table_name, column_name, shape, row_count_at_baseline) "
                "VALUES (?,?,'all_null',0)", (t, col))
        self.c.executescript(mig.read_text())
        left = [r[0] for r in self.c.execute(
            "SELECT table_name FROM unmaintained_columns_baseline")]
        self.assertEqual(left, ['keep_me'])


class PublishPushGateTest(unittest.TestCase):
    """A failed commit must not reach a mirror."""

    def _source(self):
        return (REPO / 'src' / 'cli' / 'commands' / 'publish.py').read_text()

    def test_push_is_gated_on_failures(self):
        src = self._source()
        head, _, tail = src.partition('pushed = 0')
        self.assertTrue(tail, "the push loop moved; re-check this guard")
        # The gate must sit between materialize and the push loop.
        self.assertIn('failures and not', head[-2000:],
                      "nothing stops the push when an earlier step failed")

    def test_override_flag_is_registered(self):
        self.assertIn("'--push-anyway'", self._source())

    def test_materialize_still_runs_on_failure(self):
        """Deliberate: materialize is local and the DB holds the right
        content either way. Only the outward-facing step is gated."""
        src = self._source()
        self.assertIn('continuing with materialize', src)


class DevModeOwnTreeTest(unittest.TestCase):
    """Dev mode must prefer the caller's own workspace.

    Ranking edit trees by recency alone let any agent on the host win
    by having touched a workspace last.
    """

    SCHEMA = """
        CREATE TABLE projects (id INTEGER PRIMARY KEY, slug TEXT);
        CREATE TABLE vcs_sessions (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE checkouts (id INTEGER PRIMARY KEY, project_id INTEGER,
            checkout_path TEXT, kind TEXT, is_active INTEGER DEFAULT 1,
            checkout_at TEXT, session_id INTEGER);
    """

    ORDERED = """SELECT c.checkout_path FROM checkouts c
                    JOIN projects p ON p.id = c.project_id
               LEFT JOIN vcs_sessions s ON s.id = c.session_id
                   WHERE p.slug = 'templedb' AND c.is_active = 1
                   ORDER BY CASE WHEN (? IS NOT NULL AND s.name = ?) THEN 0
                                 WHEN (? IS NOT NULL AND c.session_id = ?) THEN 0
                                 ELSE 1 END,
                            CASE c.kind WHEN 'edit' THEN 0
                                        WHEN 'canonical' THEN 1 ELSE 2 END,
                            c.checkout_at DESC"""

    def setUp(self):
        self.c = sqlite3.connect(':memory:')
        self.c.executescript(self.SCHEMA)
        self.c.execute("INSERT INTO projects VALUES (1,'templedb')")
        self.c.execute("INSERT INTO vcs_sessions VALUES (1,'mine')")
        self.c.execute("INSERT INTO vcs_sessions VALUES (2,'theirs')")
        # Theirs is NEWER — under the old ordering it won.
        self.c.execute("INSERT INTO checkouts VALUES "
                       "(1,1,'/mine','edit',1,'2026-01-01',1)")
        self.c.execute("INSERT INTO checkouts VALUES "
                       "(2,1,'/theirs','edit',1,'2026-09-09',2)")
        self.c.execute("INSERT INTO checkouts VALUES "
                       "(3,1,'/canon','canonical',1,'2026-09-10',NULL)")

    def tearDown(self):
        self.c.close()

    def _first(self, name, sid):
        return self.c.execute(
            self.ORDERED, (name, name, sid, sid)).fetchone()[0]

    def test_own_tree_by_name_wins_over_newer(self):
        self.assertEqual(self._first('mine', None), '/mine')

    def test_own_tree_by_session_id_wins(self):
        self.assertEqual(self._first(None, 1), '/mine')

    def test_unpinned_caller_falls_back_to_recency(self):
        """No session declared: previous behaviour, newest edit tree."""
        self.assertEqual(self._first(None, None), '/theirs')

    def test_unknown_session_does_not_match_everything(self):
        """A stale env var must rank nothing first, not everything."""
        self.assertEqual(self._first('ghost', None), '/theirs')


class GeneratePromptTest(unittest.TestCase):
    """--yes must neither deadlock nor silently regenerate."""

    def _source(self):
        return (REPO / 'src' / 'cli' / 'commands' / 'nixos.py').read_text()

    def test_prompt_takes_assume_yes(self):
        self.assertIn('def _check_dirty_and_prompt(assume_yes',
                      self._source())

    def test_all_call_sites_thread_the_flag(self):
        src = self._source()
        self.assertNotIn('_check_dirty_and_prompt()', src,
                         "a call site still ignores --yes and will "
                         "deadlock on EOF")

    def test_yes_skips_rather_than_runs_generate(self):
        """Generate rewrites flake.nix, where --pin-input writes the
        templedb rev. --yes means 'do not ask', not 'regenerate'."""
        src = self._source()
        block = src.split('if assume_yes:')[1][:400]
        self.assertIn('skipping generate', block)


if __name__ == '__main__':
    unittest.main()
