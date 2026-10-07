"""Migration 127: blob reference counting, intent linkage, dead views.

Three defects found by the 2026-10-06 schema atlas, each of which had
been live long enough to be invisible:

  1. content_blobs.reference_count had no UPDATE trigger, and
     file_contents is updated in place on every `file set`. Declared
     counts summed to 4,263 against 2,051 real rows.
  2. edit_intents.applied_commit_id was NULL on all 981 rows, so the
     intent span never closed and `provenance intent` stopped one hop
     short.
  3. related_readmes referenced a table migration 121 dropped. SQLite
     validates a view body only at query time, so it looked healthy in
     sqlite_master for six migrations.

Standalone sqlite fixtures rather than the shared conftest, matching
tests/vcs/test_session_stage_orphans.py: migrations/schema.sql is
stale, and building just the tables under test keeps the regressions
covered without waiting on that cleanup.
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'src'))

MIGRATION = REPO / 'migrations' / '127_blob_refcount_and_intent_linkage.sql'


def _apply_migration(conn):
    conn.executescript(MIGRATION.read_text())


class BlobRefcountTriggerTest(unittest.TestCase):
    """reference_count must survive an in-place content_hash UPDATE."""

    SCHEMA = """
        CREATE TABLE content_blobs (
            hash_sha256 TEXT PRIMARY KEY,
            content_text TEXT,
            content_type TEXT NOT NULL DEFAULT 'text',
            file_size_bytes INTEGER NOT NULL DEFAULT 0,
            reference_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE file_contents (
            id INTEGER PRIMARY KEY,
            file_id INTEGER NOT NULL,
            content_hash TEXT NOT NULL,
            file_size_bytes INTEGER NOT NULL DEFAULT 0,
            is_current BOOLEAN DEFAULT 1,
            UNIQUE(file_id, is_current)
        );
        CREATE TRIGGER increment_blob_reference
        AFTER INSERT ON file_contents FOR EACH ROW BEGIN
            UPDATE content_blobs SET reference_count = reference_count + 1
             WHERE hash_sha256 = NEW.content_hash;
        END;
        CREATE TRIGGER decrement_blob_reference
        AFTER DELETE ON file_contents FOR EACH ROW BEGIN
            UPDATE content_blobs SET reference_count = reference_count - 1
             WHERE hash_sha256 = OLD.content_hash;
        END;
        -- Tables the migration's other sections touch, so the script
        -- runs end to end against this fixture.
        CREATE TABLE vcs_commits (
            id INTEGER PRIMARY KEY, project_id INTEGER,
            commit_timestamp TEXT);
        CREATE TABLE vcs_file_states (
            id INTEGER PRIMARY KEY, commit_id INTEGER, file_id INTEGER,
            file_path TEXT, change_type TEXT, content_hash TEXT,
            old_content_hash TEXT);
        CREATE TABLE project_files (
            id INTEGER PRIMARY KEY, project_id INTEGER, file_path TEXT);
        CREATE TABLE edit_intents (
            id INTEGER PRIMARY KEY, project_id INTEGER, file_path TEXT,
            base_revision TEXT, new_content_hash TEXT, status TEXT,
            created_at TEXT, applied_commit_id INTEGER);
        CREATE TABLE unmaintained_columns_baseline (
            id INTEGER PRIMARY KEY, table_name TEXT, column_name TEXT,
            shape TEXT, row_count_at_baseline INTEGER, accepted_at TEXT,
            reason TEXT, UNIQUE(table_name, column_name));
    """

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.executescript(self.SCHEMA)
        for h in ('aaa', 'bbb'):
            self.conn.execute(
                "INSERT INTO content_blobs (hash_sha256, file_size_bytes) "
                "VALUES (?, 10)", (h,))

    def tearDown(self):
        self.conn.close()

    def _refcounts(self):
        return dict(self.conn.execute(
            "SELECT hash_sha256, reference_count FROM content_blobs"))

    def test_update_leaks_without_the_migration(self):
        """The bug, reproduced: an in-place UPDATE moves no counters."""
        self.conn.execute(
            "INSERT INTO file_contents (file_id, content_hash) VALUES (1,'aaa')")
        self.conn.execute(
            "UPDATE file_contents SET content_hash='bbb' WHERE file_id=1")
        # aaa still claims a reference it no longer has; bbb claims none
        # despite being the live content. This is the 2x over-count.
        self.assertEqual(self._refcounts(), {'aaa': 1, 'bbb': 0})

    def test_update_moves_the_reference(self):
        _apply_migration(self.conn)
        self.conn.execute(
            "INSERT INTO file_contents (file_id, content_hash) VALUES (1,'aaa')")
        self.conn.execute(
            "UPDATE file_contents SET content_hash='bbb' WHERE file_id=1")
        self.assertEqual(self._refcounts(), {'aaa': 0, 'bbb': 1})

    def test_insert_and_delete_still_work(self):
        """The new trigger must not displace the two that were right."""
        _apply_migration(self.conn)
        self.conn.execute(
            "INSERT INTO file_contents (file_id, content_hash) VALUES (1,'aaa')")
        self.assertEqual(self._refcounts()['aaa'], 1)
        self.conn.execute("DELETE FROM file_contents WHERE file_id=1")
        self.assertEqual(self._refcounts()['aaa'], 0)

    def test_no_op_update_does_not_double_count(self):
        """UPDATE that leaves content_hash alone must not fire."""
        _apply_migration(self.conn)
        self.conn.execute(
            "INSERT INTO file_contents (file_id, content_hash) VALUES (1,'aaa')")
        self.conn.execute(
            "UPDATE file_contents SET content_hash='aaa' WHERE file_id=1")
        self.assertEqual(self._refcounts()['aaa'], 1)

    def test_backfill_corrects_pre_existing_drift(self):
        """Rows written before the fix are repaired, not just frozen."""
        self.conn.execute(
            "INSERT INTO file_contents (file_id, content_hash) VALUES (1,'aaa')")
        self.conn.execute(
            "UPDATE file_contents SET content_hash='bbb' WHERE file_id=1")
        _apply_migration(self.conn)
        self.assertEqual(self._refcounts(), {'aaa': 0, 'bbb': 1})

    def test_migration_is_idempotent(self):
        _apply_migration(self.conn)
        self.conn.execute(
            "INSERT INTO file_contents (file_id, content_hash) VALUES (1,'aaa')")
        _apply_migration(self.conn)
        self.assertEqual(self._refcounts()['aaa'], 1)

    def test_refcount_never_goes_negative(self):
        """A blob whose count is already 0 must not be driven below it.

        Pre-127 drift left counts in both directions, so the decrement
        side of the UPDATE trigger can legitimately meet a zero.
        """
        _apply_migration(self.conn)
        self.conn.execute(
            "INSERT INTO file_contents (file_id, content_hash) VALUES (1,'aaa')")
        self.conn.execute(
            "UPDATE content_blobs SET reference_count=0 WHERE hash_sha256='aaa'")
        self.conn.execute(
            "UPDATE file_contents SET content_hash='bbb' WHERE file_id=1")
        self.assertEqual(self._refcounts()['aaa'], 0)


class IntentCommitLinkageTest(unittest.TestCase):
    """edit_intents.applied_commit_id must close when a commit lands."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.executescript(BlobRefcountTriggerTest.SCHEMA)
        self.conn.execute(
            "INSERT INTO project_files (id, project_id, file_path) "
            "VALUES (7, 1, 'src/foo.py')")

    def tearDown(self):
        self.conn.close()

    def _intent(self, hash_, created, project=1, path='src/foo.py',
                status='applied'):
        return self.conn.execute(
            "INSERT INTO edit_intents (project_id, file_path, "
            "new_content_hash, status, created_at) VALUES (?,?,?,?,?)",
            (project, path, hash_, status, created)).lastrowid

    def _commit(self, cid, ts, project=1):
        self.conn.execute(
            "INSERT INTO vcs_commits (id, project_id, commit_timestamp) "
            "VALUES (?,?,?)", (cid, project, ts))

    def _record(self, cid, hash_, path='src/foo.py', file_id=7):
        self.conn.execute(
            "INSERT INTO vcs_file_states (commit_id, file_id, file_path, "
            "change_type, content_hash) VALUES (?,?,?,'modified',?)",
            (cid, file_id, path, hash_))

    def _applied(self, iid):
        return self.conn.execute(
            "SELECT applied_commit_id FROM edit_intents WHERE id=?",
            (iid,)).fetchone()[0]

    def test_backfill_links_historical_intents(self):
        iid = self._intent('h1', '2026-10-01 10:00:00')
        self._commit(100, '2026-10-01 11:00:00')
        self._record(100, 'h1')
        self.assertIsNone(self._applied(iid))
        _apply_migration(self.conn)
        self.assertEqual(self._applied(iid), 100)

    def test_trigger_links_new_commits(self):
        _apply_migration(self.conn)
        iid = self._intent('h2', '2026-10-05 10:00:00')
        self._commit(200, '2026-10-05 11:00:00')
        self._record(200, 'h2')
        self.assertEqual(self._applied(iid), 200)

    def test_uncommitted_intent_stays_null(self):
        """NULL is the right answer for content no commit recorded.

        `file set` lands content without a commit, so an unlinked
        intent is a real state, not a gap to be filled with a guess.
        """
        _apply_migration(self.conn)
        iid = self._intent('never-committed', '2026-10-05 10:00:00')
        self._commit(300, '2026-10-05 11:00:00')
        self._record(300, 'something-else')
        self.assertIsNone(self._applied(iid))

    def test_commit_predating_the_intent_does_not_claim_it(self):
        """An A -> B -> A oscillation must not back-date the link."""
        _apply_migration(self.conn)
        self._commit(400, '2026-10-01 09:00:00')
        iid = self._intent('hA', '2026-10-05 10:00:00')
        self._record(400, 'hA')          # older commit, same bytes
        self.assertIsNone(self._applied(iid))

    def test_one_intent_per_file_state_row(self):
        """Two intents proposing identical bytes: only the latest links.

        Linking both would assert that one commit applied two distinct
        edits, which is the kind of plausible-but-wrong provenance the
        span exists to prevent.
        """
        _apply_migration(self.conn)
        old = self._intent('same', '2026-10-05 10:00:00')
        new = self._intent('same', '2026-10-05 10:30:00')
        self._commit(500, '2026-10-05 11:00:00')
        self._record(500, 'same')
        self.assertIsNone(self._applied(old))
        self.assertEqual(self._applied(new), 500)

    def test_other_project_does_not_match(self):
        """Hash equality across projects is not provenance."""
        _apply_migration(self.conn)
        iid = self._intent('shared', '2026-10-05 10:00:00', project=2)
        self._commit(600, '2026-10-05 11:00:00', project=1)
        self._record(600, 'shared')
        self.assertIsNone(self._applied(iid))

    def test_cancelled_intent_is_never_linked(self):
        _apply_migration(self.conn)
        iid = self._intent('hC', '2026-10-05 10:00:00', status='cancelled')
        self._commit(700, '2026-10-05 11:00:00')
        self._record(700, 'hC')
        self.assertIsNone(self._applied(iid))

    def test_already_linked_intent_is_not_relinked(self):
        _apply_migration(self.conn)
        iid = self._intent('hD', '2026-10-05 10:00:00')
        self._commit(800, '2026-10-05 11:00:00')
        self._record(800, 'hD')
        self._commit(801, '2026-10-05 12:00:00')
        self._record(801, 'hD')
        self.assertEqual(self._applied(iid), 800)

    def test_baseline_rows_are_retired(self):
        """The ratchet must stop suppressing columns that now get written."""
        for col in ('base_revision', 'applied_commit_id'):
            self.conn.execute(
                "INSERT INTO unmaintained_columns_baseline "
                "(table_name, column_name, shape, row_count_at_baseline) "
                "VALUES ('edit_intents', ?, 'all_null', 780)", (col,))
        _apply_migration(self.conn)
        left = self.conn.execute(
            "SELECT COUNT(*) FROM unmaintained_columns_baseline "
            "WHERE table_name='edit_intents'").fetchone()[0]
        self.assertEqual(left, 0)


class DanglingViewTest(unittest.TestCase):
    """A view whose table is gone must be reported, not silently kept."""

    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.executescript("""
            CREATE TABLE readme_topics (readme_id INTEGER, topic TEXT,
                                        relevance REAL);
            CREATE VIEW related_readmes AS
                SELECT readme_id, topic FROM readme_topics;
            CREATE TABLE live (a INTEGER);
            CREATE VIEW live_view AS SELECT a FROM live;
        """)

    def tearDown(self):
        self.conn.close()

    def _broken_views(self):
        """Mirror of _check_views_are_runnable's core."""
        bad = []
        for (name,) in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='view'"):
            try:
                self.conn.execute(f'EXPLAIN SELECT * FROM "{name}" LIMIT 0')
            except sqlite3.Error:
                bad.append(name)
        return bad

    def test_sqlite_does_not_notice_on_its_own(self):
        """The reason this went unseen: nothing routine complains."""
        self.conn.execute("DROP TABLE readme_topics")
        self.assertIn(
            'related_readmes',
            [r[0] for r in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='view'")])
        self.assertEqual(
            self.conn.execute("PRAGMA integrity_check").fetchone()[0], 'ok')

    def test_explain_catches_the_dangling_view(self):
        self.conn.execute("DROP TABLE readme_topics")
        self.assertEqual(self._broken_views(), ['related_readmes'])

    def test_healthy_views_pass(self):
        self.assertEqual(self._broken_views(), [])

    def test_explain_reads_no_rows(self):
        """EXPLAIN must compile, not scan — this is why the check is cheap."""
        self.conn.execute("INSERT INTO live (a) VALUES (1)")
        plan = self.conn.execute(
            'EXPLAIN SELECT * FROM "live_view" LIMIT 0').fetchall()
        self.assertTrue(plan)  # compiled
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM live").fetchone()[0], 1)


class ReferentCoverageTest(unittest.TestCase):
    """Every blob-hash column must be classified before gc can be safe.

    A referent missing from BLOB_REFERENTS means `storage blob gc`
    deletes content something still points at. Names alone are not
    enough to tell a blob hash from an aggregate fingerprint — four
    columns called content_hash are not blob hashes at all — so the
    rule is that every %content_hash% column in the live schema must
    appear in exactly one of the two lists. A migration that adds one
    and classifies neither fails here rather than in production.
    """

    def _live_hash_columns(self, conn):
        cols = set()
        for (tbl,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"):
            for row in conn.execute(f'PRAGMA table_info("{tbl}")'):
                if 'content_hash' in row[1]:
                    cols.add((tbl, row[1]))
        return cols

    def test_every_hash_column_is_classified(self):
        from cli.commands.blob import BlobCommands
        # Deliberately NOT TEMPLEDB_PATH: conftest points that at an
        # empty per-session temp DB, against which this test would
        # find zero hash columns and pass vacuously — the exact shape
        # of green-but-measuring-nothing the atlas was written about.
        # It needs a schema that actually has content_blobs in it.
        db = os.environ.get('TEMPLEDB_REAL_DB') or str(
            Path.home() / '.local/share/templedb/templedb.sqlite')
        if not Path(db).exists():
            self.skipTest(f'no populated database at {db}')
        conn = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
        try:
            if not conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' "
                    "AND name='content_blobs'").fetchone():
                self.skipTest(f'{db} has no content_blobs table')
            live = self._live_hash_columns(conn)
        finally:
            conn.close()
        self.assertTrue(live, 'found no hash columns — wrong database?')
        known = set(BlobCommands.BLOB_REFERENTS) | set(
            BlobCommands.NOT_BLOB_HASHES)
        unclassified = live - known
        self.assertFalse(
            unclassified,
            f"unclassified blob-hash column(s): {sorted(unclassified)}. "
            f"Add each to BlobCommands.BLOB_REFERENTS (gc must spare it) "
            f"or NOT_BLOB_HASHES (it is an aggregate fingerprint, with a "
            f"note saying why).")

    def test_lists_are_disjoint(self):
        from cli.commands.blob import BlobCommands
        both = set(BlobCommands.BLOB_REFERENTS) & set(
            BlobCommands.NOT_BLOB_HASHES)
        self.assertFalse(both, f"classified twice: {sorted(both)}")

    def test_doctor_check_agrees_with_gc(self):
        """The check and the collector must use the same referent set.

        If they drift, doctor reports a budget the gc cannot reclaim
        (or worse, stays green over content gc is about to delete).
        """
        import inspect
        from cli.commands.blob import BlobCommands
        from cli.commands.entity import EntityCommands
        src = inspect.getsource(
            EntityCommands._check_blob_orphans_within_budget)
        for tbl, col in BlobCommands.BLOB_REFERENTS:
            self.assertIn(
                f"('{tbl}', '{col}')", src,
                f"{tbl}.{col} is a gc referent but the doctor check does "
                f"not count it")


if __name__ == '__main__':
    unittest.main()
