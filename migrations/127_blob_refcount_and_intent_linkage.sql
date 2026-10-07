-- 127_blob_refcount_and_intent_linkage.sql
--
-- Three repairs found by the 2026-10-06 schema atlas
-- (reports/2026-10-06-1811-templedb-schema-atlas-*.html): a reference
-- counter that cannot count, an edit-intent span that never closes,
-- and a view that references a table dropped six migrations ago.
--
-- ---------------------------------------------------------------
-- 1. content_blobs.reference_count has never been right
-- ---------------------------------------------------------------
--
-- Two triggers maintain it: increment_blob_reference AFTER INSERT ON
-- file_contents, decrement_blob_reference AFTER DELETE. There is no
-- UPDATE trigger -- and file_contents holds exactly one row per file
-- (UNIQUE(file_id, is_current), all 2,051 rows is_current=1), so the
-- overwhelmingly common operation is an in-place UPDATE of
-- content_hash, which neither trigger sees. Every `file set` on an
-- existing file therefore leaves the old blob's count too high and the
-- new blob's too low, forever.
--
-- Measured 2026-10-06: declared counts summed to 4,263 against 2,051
-- actual file_contents rows, wrong on 2,073 of 12,512 blobs. A counter
-- that over-reports by 2x cannot gate a collector, which is half the
-- reason 8,741 blobs (378 MB, 54% of the database file) are currently
-- unreachable from any table and nothing has ever reclaimed them.
--
-- Note what reference_count does and does not mean after this. It
-- counts file_contents rows ONLY -- not vcs_file_states,
-- vcs_working_state, checkout_snapshots, edit_intents, sync_cache or
-- deployment_snapshots, all of which also pin a hash. Making it count
-- all seven would need triggers on seven tables and would still be a
-- cache. It is kept as the cheap "is this the current content of some
-- file" signal, and `storage blob gc` does the full seven-way
-- anti-join itself rather than trusting this column. The
-- blob_refcount_is_accurate doctor check keeps the narrow claim
-- honest.

DROP TRIGGER IF EXISTS update_blob_reference;

CREATE TRIGGER update_blob_reference
AFTER UPDATE OF content_hash ON file_contents
FOR EACH ROW
WHEN OLD.content_hash IS NOT NEW.content_hash
BEGIN
    UPDATE content_blobs
       SET reference_count = MAX(0, reference_count - 1)
     WHERE hash_sha256 = OLD.content_hash;
    UPDATE content_blobs
       SET reference_count = reference_count + 1
     WHERE hash_sha256 = NEW.content_hash;
END;

-- Backfill to truth. Idempotent: recomputes from scratch, so running
-- the migration twice converges rather than drifting.
UPDATE content_blobs
   SET reference_count = (
       SELECT COUNT(*) FROM file_contents fc
        WHERE fc.content_hash = content_blobs.hash_sha256
   );

-- ---------------------------------------------------------------
-- 2. edit_intents.applied_commit_id has never been written
-- ---------------------------------------------------------------
--
-- All 981 rows have it NULL, including the 980 marked status='applied'.
-- The column is the commit end of the intent span -- the thing that
-- makes `templedb provenance intent <id>` able to answer "and where
-- did it land". Without it the intent table is a log, not a span, and
-- the Phase 3 cross-authority walk stops one hop short.
--
-- It was never written because nothing could write it at the right
-- time: `file set` creates the intent and marks it applied immediately
-- (content lands in file_contents without a commit), and the commit
-- that eventually records those bytes happens later, in a different
-- process, through one of four separate INSERT sites
-- (cli/commands/commit.py x3, cli/commands/vcs.py x2,
-- repositories/vcs_repository.py, cathedral_import.py).
--
-- A trigger rather than a call at each site, for the same reason
-- update_branch_head_on_commit is a trigger: the linkage then holds
-- for raw SQL and for any future write path, instead of depending on
-- seven callers remembering. Matching is by content hash, which is the
-- honest join -- the intent proposed exactly these bytes for exactly
-- this path, and this commit recorded them.
--
-- Exactly one intent is linked per file-state row: the most recent
-- still-unlinked applied intent created no later than the commit. That
-- bound matters for a file that oscillates A -> B -> A, where an old
-- intent proposing A would otherwise be claimed by a much later commit
-- that happens to restore A.

DROP TRIGGER IF EXISTS link_intent_to_commit;

CREATE TRIGGER link_intent_to_commit
AFTER INSERT ON vcs_file_states
FOR EACH ROW
WHEN NEW.content_hash IS NOT NULL
BEGIN
    UPDATE edit_intents
       SET applied_commit_id = NEW.commit_id
     WHERE id = (
        SELECT ei.id
          FROM edit_intents ei
          JOIN vcs_commits c ON c.id = NEW.commit_id
         WHERE ei.applied_commit_id IS NULL
           AND ei.status = 'applied'
           AND ei.project_id = c.project_id
           AND ei.new_content_hash = NEW.content_hash
           AND ei.file_path = COALESCE(
                 NEW.file_path,
                 (SELECT file_path FROM project_files
                   WHERE id = NEW.file_id))
           AND ei.created_at <= c.commit_timestamp
         ORDER BY ei.created_at DESC, ei.id DESC
         LIMIT 1
     );
END;

-- Backfill the existing 980 applied intents against history. Same
-- matching rule as the trigger, applied once per (commit, file) pair
-- oldest-first so that an intent is claimed by the earliest commit
-- that recorded its bytes rather than the latest. Hash-matched, so an
-- intent whose content was never committed stays NULL -- which is the
-- correct answer for it, not a gap.
--
-- Correlated UPDATE rather than a loop: SQLite has no procedural
-- backfill, and the ORDER BY ... LIMIT 1 inside the subquery gives the
-- same "most recent eligible intent" choice the trigger makes.
UPDATE edit_intents
   SET applied_commit_id = (
       SELECT vfs.commit_id
         FROM vcs_file_states vfs
         JOIN vcs_commits c ON c.id = vfs.commit_id
        WHERE vfs.content_hash = edit_intents.new_content_hash
          AND c.project_id     = edit_intents.project_id
          AND COALESCE(vfs.file_path,
                       (SELECT file_path FROM project_files
                         WHERE id = vfs.file_id)) = edit_intents.file_path
          AND c.commit_timestamp >= edit_intents.created_at
        ORDER BY c.commit_timestamp ASC, vfs.commit_id ASC
        LIMIT 1
   )
 WHERE applied_commit_id IS NULL
   AND status = 'applied';

-- ---------------------------------------------------------------
-- 3. related_readmes references a table dropped by migration 121
-- ---------------------------------------------------------------
--
-- 121_drop_readme_index.sql removed the readme tables and left the
-- view that reads readme_topics behind. SQLite validates a view body
-- at query time, never at CREATE VIEW or at schema load, so a view can
-- outlive its tables indefinitely and look perfectly healthy in
-- sqlite_master. Any SELECT against it errors with
-- "no such table: main.readme_topics".
--
-- The views_are_runnable doctor check added alongside this migration
-- EXPLAINs every view once per run so the next one is caught in a day
-- rather than in six migrations.

DROP VIEW IF EXISTS related_readmes;

-- ---------------------------------------------------------------
-- 4. Retire two now-maintained baseline rows
-- ---------------------------------------------------------------
--
-- unmaintained_columns_baseline is a ratchet: a row in it tells
-- no_new_unmaintained_columns to stop reporting that column. Both of
-- these are now written, so leaving the rows in place would suppress a
-- real regression if either stopped being populated again.
--
-- edit_intents.base_revision was recorded as `constant` at 780 rows on
-- 2026-10-03 and fixed the next day: of 981 rows, 888 still hold the
-- legacy 'current', but every intent created since 2026-10-04 15:33
-- carries a real base hash or the explicit 'new-file' sentinel (93
-- rows). applied_commit_id is populated by section 2 above.

DELETE FROM unmaintained_columns_baseline
 WHERE table_name = 'edit_intents'
   AND column_name IN ('base_revision', 'applied_commit_id');
