-- Migration 099: sync_scope column on entities + relations
--
-- Per Q5 answer in parallel-session report
-- reports/2026-09-03-1947-answers-to-open-questions-*.html.
--
-- Three values:
--   'fleet'          — sync across all machines (Commit, Deployment,
--                      Machine, Generation, Report, File, EditIntent)
--   'machine-local'  — never leaves this host (Symbol, ToolCall,
--                      re-derivable from source, per-machine only)
--   'none'           — transient, don't sync
--
-- Every ingestion adapter sets sync_scope when it emits. Doctor
-- invariant verifies no NULL values (would silently break sync).
--
-- The actual sync_entities / sync_relations tables + CRSql wiring
-- are deferred — the __crsql_clock / __crsql_pks machinery has live
-- data and adding to it needs careful study. Landing sync_scope
-- now means the classification is settled when CRSql wiring
-- catches up.

ALTER TABLE entities ADD COLUMN sync_scope TEXT
    CHECK (sync_scope IN ('fleet', 'machine-local', 'none'));
ALTER TABLE relations ADD COLUMN sync_scope TEXT
    CHECK (sync_scope IN ('fleet', 'machine-local', 'none'));

CREATE INDEX IF NOT EXISTS idx_entities_sync_scope
    ON entities(sync_scope, kind);
CREATE INDEX IF NOT EXISTS idx_relations_sync_scope
    ON relations(sync_scope, kind);
