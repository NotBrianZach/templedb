-- Migration 092: invariant_checks (Phase 3 reconcile groundwork)
--
-- Persists results of `templedb doctor entities` runs. Each check
-- inserts one row per doctor invocation, so we get history of when
-- drift appeared and when it was resolved.
--
-- Design note: this is the "commuting-diagram invariants as
-- machine-checked" idea from the critique — named laws like
--     hash(source_snapshot(c)) = provenance(build(c))
-- with last-checked-at and status. See docs/ENTITY_GRAPH_DESIGN.md.
--
-- The schema-report (reports/2026-09-03-0843-proposed-schema-*.html)
-- calls this out as a Phase 3 addition. Currently doctor prints
-- results but doesn't persist them; this table changes that.

CREATE TABLE IF NOT EXISTS invariant_checks (
    id            INTEGER PRIMARY KEY,

    -- Name of the invariant. Matches the strings used in
    -- EntityCommands.doctor_entities checks list:
    --   'edit_intent_applied_to_valid_commit'
    --   'every_edit_intent_has_entity'
    --   'every_commit_has_entity'
    --   'relations_reference_valid_entities'
    --   'report_impls_reference_valid_reports'
    --   'report_impls_reference_valid_commits'
    check_name    TEXT NOT NULL,

    -- When the check ran and how long it took
    ran_at        TEXT NOT NULL DEFAULT (datetime('now')),
    duration_ms   INTEGER,

    -- Result. 'ok' means invariant held. 'violated' means one or more
    -- issues found. 'error' means the check itself failed to run.
    status        TEXT NOT NULL DEFAULT 'ok'
                    CHECK (status IN ('ok', 'violated', 'error')),
    issue_count   INTEGER NOT NULL DEFAULT 0,

    -- Up to first-N issues as JSON for context, without storing
    -- unbounded lists. Freshness > completeness for a history log.
    sample_issues_json TEXT,

    -- Optional link to the ingest run that likely produced the drift.
    ingestion_run_id INTEGER REFERENCES ingestion_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_invariant_checks_name_time
    ON invariant_checks(check_name, ran_at DESC);
CREATE INDEX IF NOT EXISTS idx_invariant_checks_violated
    ON invariant_checks(status, ran_at DESC)
    WHERE status IN ('violated', 'error');
