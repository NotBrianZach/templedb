-- 128_blob_deletions_audit.sql
--
-- An audit trail for blob collection, and a repair for the
-- over-counting bug that `blob_refcount_is_accurate` caught within
-- hours of migration 127 adding it.
--
-- ---------------------------------------------------------------
-- 1. blob_deletions — attribution for a destructive, bulk operation
-- ---------------------------------------------------------------
--
-- On 2026-10-07 the first `storage blob gc --apply` removed 8,715
-- blobs and 378 MB. Nothing recorded it. The only way to establish
-- what had happened was arithmetic: the count before, the count
-- after, and a reported reclaimable figure that happened to match.
--
-- That is precisely the gap migration 124 closed for entities, and
-- the reasoning carries over unchanged. Its header puts it best: a
-- gap in the audit table next to a drop in the counts means "not
-- deleted through the CLI", which is the most useful thing to know
-- when numbers move unexpectedly. Blob deletion is strictly more
-- destructive than entity deletion -- an entity can be re-derived by
-- re-running ingest, a blob is the only copy of its bytes -- so it
-- had the weaker story and the higher stakes.
--
-- Per-row rather than per-run. A summary row would answer "how much"
-- but not "was MY file in there", which is the question someone asks
-- at the point they are worried. 8,715 rows is the same order as
-- entity_deletions already carries, and gc should be rare once the
-- backlog is cleared.
--
-- Deliberately does NOT store content. This is attribution, not
-- recovery; a table that could un-delete would have to hold the very
-- bytes the operation exists to reclaim. Recovery comes from the
-- nightly backups, and the hash recorded here is what identifies the
-- blob in them.
--
-- No FK on hash_sha256: by construction the row it names is gone.
-- Not unique either -- content is addressed by hash, so the same
-- hash can be re-added by a later write and collected again, and
-- both events are real.

CREATE TABLE IF NOT EXISTS blob_deletions (
    id               INTEGER PRIMARY KEY,
    hash_sha256      TEXT    NOT NULL,
    file_size_bytes  INTEGER NOT NULL,
    content_type     TEXT,
    -- How old the blob was when collected. The age guard is the main
    -- safety property of gc, so an incident review needs to see
    -- whether a deleted blob was actually old.
    blob_created_at  TEXT,
    -- Which code path removed it. 'blob_gc' today; a future tier
    -- migration or a manual sweep would use its own value, and a
    -- deletion with no row here was raw SQL.
    deleted_via      TEXT    NOT NULL,
    reason           TEXT    NOT NULL,
    -- Groups one invocation, so "what did that run take?" is one
    -- query. Assigned by the caller: SQLite has no uuid(), and a
    -- timestamp alone collides when two runs share a second.
    gc_run_id        TEXT,
    deleted_at       TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_blob_deletions_hash
    ON blob_deletions(hash_sha256);
CREATE INDEX IF NOT EXISTS idx_blob_deletions_run
    ON blob_deletions(gc_run_id);
CREATE INDEX IF NOT EXISTS idx_blob_deletions_time
    ON blob_deletions(deleted_at);

-- ---------------------------------------------------------------
-- 2. Blobs were over-counted from birth
-- ---------------------------------------------------------------
--
-- Four INSERT sites created content_blobs rows with
-- reference_count = 1 hardcoded:
--
--   cli/commands/file.py   _record_and_apply_intent  (text)
--   cli/commands/file.py   _write_content_to_db      (binary)
--   cli/commands/file.py   _write_content_to_db      (text)
--   cli/commands/intent.py intent_create             (text)
--
-- A blob row is not a reference to itself. The count means "how many
-- file_contents rows point here", and increment_blob_reference
-- already answers that on the INSERT that follows -- so every blob
-- born through those paths went straight to 2 for a single
-- file_contents row, and a cancelled intent's blob sat at 1 with no
-- referent at all.
--
-- This is why migration 127's backfill looked clean and then drifted
-- within the hour: the backfill was correct, and the next five writes
-- re-broke it. 127 fixed the trigger coverage; the counter still had
-- a second, independent source of error at the insert.
--
-- All four literals are now 0. Same recompute-from-scratch backfill
-- as 127, which converges rather than drifting if run twice.

UPDATE content_blobs
   SET reference_count = (
       SELECT COUNT(*) FROM file_contents fc
        WHERE fc.content_hash = content_blobs.hash_sha256
   );
