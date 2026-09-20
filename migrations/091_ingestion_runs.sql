-- Migration 091: ingestion_runs (Phase 3 reconcile groundwork)
--
-- Per-adapter run log. Each `templedb ingest <adapter>` invocation
-- records a row. Enables:
--
--   - Freshness telemetry per authority ("git ingest last ran 2h ago")
--   - History of ingest counts (spikes = interesting)
--   - Debugging: which run was responsible for a suspect entity
--
-- Design note: this is one of the tables the schema-report
-- (reports/2026-09-03-0843-proposed-schema-*.html) called out as
-- Phase 3 additions. Small, cheap, high-leverage.

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id                INTEGER PRIMARY KEY,

    -- Which adapter ran. Matches the choices in `templedb ingest`
    -- ('git', 'agent', 'intent', 'reports', ...).
    adapter           TEXT NOT NULL,

    -- Lifecycle
    started_at        TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at       TEXT,
    status            TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN
                            ('running', 'ok', 'partial', 'error')),

    -- Change counters
    entities_added    INTEGER DEFAULT 0,
    entities_refreshed INTEGER DEFAULT 0,
    relations_added   INTEGER DEFAULT 0,
    extra_added       INTEGER DEFAULT 0,   -- span/junction rows

    -- Freeform per-run notes (error message, adapter-specific stats)
    notes             TEXT
);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_adapter_started
    ON ingestion_runs(adapter, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingestion_runs_status
    ON ingestion_runs(status)
    WHERE status IN ('running', 'error');
