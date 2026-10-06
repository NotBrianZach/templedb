-- 124_entity_deletions_audit.sql
--
-- An audit trail for entity removal, because there wasn't one.
--
-- On 2026-10-02 every entity with source_authority='scip-typescript'
-- disappeared: 12,428 Symbols and 22,906 relations, created 2026-09-05
-- and intact in the 2026-10-02 05:04 backup, gone by the 10-03 05:20
-- backup. Nothing recorded it. Reconstructing even the 24-hour window
-- took a bisect over six nightly SQLite backups, and the only reason
-- the rows were identifiable at all is that 2,141 observations_archive
-- rows happened to survive -- which is itself the bug below.
--
-- Both code paths that delete entities (graph_forget, prune-orphans)
-- also DELETE the matching observations_archive rows. That is exactly
-- backwards: the archive is the only durable trace of an entity having
-- existed, so deleting it alongside the entity destroys the evidence
-- at precisely the moment it becomes the sole record. Those two paths
-- now write here first and leave the archive alone, which makes the
-- archive append-only in practice.
--
-- This table cannot catch raw SQL, and the Oct 2 deletion was raw SQL
-- (it bypassed both paths -- the archive survived). What it does is
-- make every deletion that goes THROUGH templedb accountable, so that
-- the next unexplained gap can be attributed by elimination rather
-- than by bisecting backups.
--
-- No FK on entity_id: by construction the row it names is gone.
-- Deliberately no `actor` column -- single-user install, so it would be
-- a constant, which is the shape 123_unmaintained_columns_baseline
-- exists to report. deleted_via carries the information that matters.

CREATE TABLE IF NOT EXISTS entity_deletions (
    id                INTEGER PRIMARY KEY,
    -- The id the entity had. Not a FK, and not unique: ids are reused
    -- by SQLite after deletion, so (entity_id, deleted_at) is what
    -- identifies an event.
    entity_id         INTEGER NOT NULL,
    entity_kind       TEXT    NOT NULL,
    entity_ref        TEXT    NOT NULL,
    label             TEXT,
    source_authority  TEXT    NOT NULL,
    -- Which code path removed it: 'graph_forget' | 'prune_orphans'.
    -- A gap in this table next to a drop in entity counts therefore
    -- means "not deleted through the CLI", which is the single most
    -- useful thing to know when counts move unexpectedly.
    deleted_via       TEXT    NOT NULL,
    reason            TEXT    NOT NULL,
    -- Relations lost to FK CASCADE. Recorded because the relation rows
    -- leave no trace of their own.
    relations_removed INTEGER NOT NULL DEFAULT 0,
    deleted_at        TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_entity_deletions_at
    ON entity_deletions(deleted_at);
CREATE INDEX IF NOT EXISTS idx_entity_deletions_authority
    ON entity_deletions(source_authority, deleted_at);
CREATE INDEX IF NOT EXISTS idx_entity_deletions_ref
    ON entity_deletions(entity_kind, entity_ref);
