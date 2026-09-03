-- Migration 095: reconcile_runs (Phase 3 active-reconcile persistence)
--
-- Per-run log for `templedb reconcile machine <name>`. Complements
-- ingestion_runs (migration 091, passive DB ingest logs) and
-- invariant_checks (migration 092, passive doctor result history).
--
-- The three tables together are the reconcile-story storage layer:
--   ingestion_runs      — when did we last read authority X into DB?
--   invariant_checks    — when did passive doctor last flag anything?
--   reconcile_runs      — when did we last actively probe reality?
--
-- Enables `templedb reconcile history [--machine NAME]` and a doctor
-- invariant that warns if any fleet machine hasn't been reconciled
-- in > 7 days (drift is undetectable without probing).

CREATE TABLE IF NOT EXISTS reconcile_runs (
    id                INTEGER PRIMARY KEY,

    -- Which machine was probed
    machine_name      TEXT NOT NULL,

    -- Lifecycle timestamps
    ran_at            TEXT NOT NULL DEFAULT (datetime('now')),
    duration_ms       INTEGER,

    -- Outcome
    status            TEXT NOT NULL DEFAULT 'ok'
                        CHECK (status IN
                            ('ok', 'drift', 'unreachable', 'error')),

    -- SSH exit code if we got one (NULL = SSH didn't run or failed
    -- before returning). Handy for triaging "keys wrong" vs
    -- "host down" vs "unexpected exit".
    ssh_exit_code     INTEGER,

    -- If status='drift', the details as JSON: which of {toplevel,
    -- nixos_version, boot_id} disagreed and what the DB vs machine
    -- values were.
    drift_details_json TEXT,

    -- Who invoked the reconcile — TEMPLEDB_AUTHOR/USER env, or NULL
    -- for scheduled runs.
    ran_by            TEXT
);

CREATE INDEX IF NOT EXISTS idx_reconcile_runs_machine_time
    ON reconcile_runs(machine_name, ran_at DESC);
CREATE INDEX IF NOT EXISTS idx_reconcile_runs_status
    ON reconcile_runs(status, ran_at DESC)
    WHERE status IN ('drift', 'unreachable', 'error');
