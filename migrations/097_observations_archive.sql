-- Migration 097: observations_archive (audit trail for entities)
--
-- Per the parallel-session recommendation in
-- reports/2026-09-03-1947-answers-to-open-questions-on-the-observer-integrator-schema.html
-- (Question 2: entities/relations gets huge).
--
-- Split of responsibilities:
--   entities table  = current view (one row per (kind, external_ref))
--   observations_archive = append-only history of every observation
--
-- Populated by AFTER UPDATE trigger on entities — every time an
-- entity's label or source_authority changes, the previous state
-- goes to the archive with the timestamp of that observation.
-- Insert-only updates to entities (no label/authority change) don't
-- fire the trigger.
--
-- Query surface: entities for "what does the graph say NOW"; the
-- archive for "when did this last change" and "who observed what
-- when." Cheap because the archive isn't on the hot query path.
--
-- Retention: no automatic cleanup yet — per-kind retention policy is
-- flagged as a follow-up. Manual `DELETE FROM observations_archive
-- WHERE observed_at < datetime('now', '-90 days')` works if the
-- archive grows uncomfortable.

CREATE TABLE IF NOT EXISTS observations_archive (
    id                INTEGER PRIMARY KEY,

    -- What was observed
    entity_kind       TEXT NOT NULL,
    entity_ref        TEXT NOT NULL,   -- the entity's external_ref
    label             TEXT,
    source_authority  TEXT,

    -- When
    observed_at       TEXT NOT NULL DEFAULT (datetime('now')),

    -- Who / how
    entity_id         INTEGER,          -- FK-ish (entity may have been deleted)

    -- Prior values (what the row looked like before the update).
    -- Nullable in case the trigger fires from a state we can't fully
    -- capture; the essential fields above are always populated.
    prior_label            TEXT,
    prior_source_authority TEXT
);

CREATE INDEX IF NOT EXISTS idx_observations_archive_entity
    ON observations_archive(entity_kind, entity_ref, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_observations_archive_time
    ON observations_archive(observed_at DESC);

-- AFTER UPDATE trigger: fires only when label or source_authority
-- change (avoids logging pure observed_at refreshes which happen
-- on every ingest of an unchanged entity).
CREATE TRIGGER IF NOT EXISTS trg_entities_archive_on_update
AFTER UPDATE OF label, source_authority ON entities
WHEN OLD.label IS NOT NEW.label
  OR OLD.source_authority IS NOT NEW.source_authority
BEGIN
    INSERT INTO observations_archive
        (entity_kind, entity_ref, label, source_authority,
         entity_id, prior_label, prior_source_authority)
    VALUES
        (NEW.kind, NEW.external_ref, NEW.label, NEW.source_authority,
         NEW.id, OLD.label, OLD.source_authority);
END;
