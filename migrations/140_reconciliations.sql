-- 140_reconciliations.sql
--
-- Record that a discrepancy is being worked on.
--
-- TempleDB already records two of the three things a disagreement between
-- authorities needs:
--
--   detection   invariant_checks (check_name, status, issue_count,
--               sample_issues_json) and reconcile_runs (machine_name,
--               drift_details_json). Both are point-in-time logs: "these
--               two authorities disagreed at T".
--
--   acceptance  unmaintained_columns_baseline — but only for one narrow
--               kind. Its shape is the right one and worth copying: it
--               stores `shape` and `row_count_at_baseline` alongside the
--               reason, so a column that CHANGES is still visible instead
--               of matching the baseline on name alone.
--
-- Missing: the episode. Nothing says a discrepancy is owned, what the plan
-- is, what was decided per item, or that it was deliberately accepted and
-- why. The consequence is visible right now — 9 invariants are violated
-- with the stalest result 9 days old, and there is nowhere to write either
-- "I am fixing this" or "this is fine, here is the argument".
--
-- The second consequence is duplication. Session 313's todo asked for a
-- `dormant_tables` registry "mirroring unmaintained_columns_baseline" —
-- a third hand-built copy of this shape. This table is the general one.
--
-- Deliberate boundaries:
--
--   * Detection stays in its own tables. One declarer per fact: detection
--     declares "they differ", a reconciliation declares "here is what we
--     did about it", and points back via (source_kind, source_id). Merging
--     them would make the hourly doctor run rewrite resolution state.
--
--   * Identity is (kind, subject_ref), unique among non-historical rows,
--     so re-detection RE-OBSERVES an existing episode rather than
--     spawning a duplicate on every scheduled run.
--
--   * `accepted` carries a fingerprint of the state at acceptance. If the
--     state changes, the acceptance no longer applies and the episode
--     re-opens. An acceptance that silently covers a growing problem is
--     worse than no record: `file_states_have_recoverable_content` says
--     "not repairable; this must not grow" and nothing enforces the
--     second clause.
--
--   * vcs_merges keeps its own table and gains nothing here yet. A merge
--     has structure (three commits, a squash flag) that a generic episode
--     should not model; it becomes a `kind` with a link once this shape
--     has survived contact with a real producer.

CREATE TABLE IF NOT EXISTS reconciliations (
    id              INTEGER PRIMARY KEY,

    -- What sort of disagreement. Open vocabulary on purpose — a new
    -- producer should not need a migration to register itself. Known:
    --   'invariant'      doctor entities / doctor history
    --   'machine_drift'  reconcile machine
    --   'db_vs_head'     content ahead of HEAD
    --   'db_vs_checkout' materialised tree disagrees with the DB
    --   'vcs_merge'      a branch merge
    --   'unmaintained_column', 'dormant_table'
    kind            TEXT NOT NULL,

    -- Stable identity WITHIN kind. For 'invariant' this is the
    -- check_name; for 'machine_drift' the machine name. Re-detection
    -- matches on (kind, subject_ref), which is what makes an hourly
    -- producer idempotent.
    subject_ref     TEXT NOT NULL,
    title           TEXT,

    -- NULL for database-wide discrepancies, which most invariants are.
    project_id      INTEGER REFERENCES projects(id) ON DELETE CASCADE,

    -- The two sides, named rather than implied. 'db' vs 'git',
    -- 'db' vs 'zMothership2', 'entities' vs 'vcs_commits'.
    authority_a     TEXT,
    authority_b     TEXT,

    -- What each side said, most recent observation. JSON so a producer
    -- can be specific without this table knowing its shape.
    observed_json   TEXT,
    item_count      INTEGER NOT NULL DEFAULT 0,

    --   open         detected, nobody has picked it up
    --   in_progress  someone is working on it (see owner, plan_md)
    --   settled      the authorities agree again
    --   accepted     deliberately tolerated; see accepted_reason and
    --                accepted_fingerprint
    --   superseded   no longer the right frame for the problem
    status          TEXT NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open', 'in_progress', 'settled',
                                        'accepted', 'superseded')),

    -- Testimony. Appended to, not replaced, so an episode that changes
    -- hands accumulates the account of what each party did.
    plan_md         TEXT,

    owner           TEXT,
    session_id      INTEGER REFERENCES vcs_sessions(id),

    -- Which detection log row surfaced this, for provenance.
    source_kind     TEXT,
    source_id       INTEGER,

    -- Acceptance, with the state it was accepted at. A changed
    -- fingerprint re-opens the episode.
    accepted_reason      TEXT,
    accepted_fingerprint TEXT,
    accepted_at          TEXT,
    -- Honest about "for now": an acceptance with no review date quietly
    -- becomes permanent, which is how unmaintained_columns_baseline
    -- behaves today.
    review_after         TEXT,

    first_detected_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_observed_at  TEXT NOT NULL DEFAULT (datetime('now')),
    observation_count INTEGER NOT NULL DEFAULT 1,
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at         TEXT,
    outcome_note      TEXT
);

-- One live episode per subject. `settled` and `superseded` are excluded so
-- history accumulates: a discrepancy that comes back gets a new row and
-- the old one still records how it was dealt with last time.
CREATE UNIQUE INDEX IF NOT EXISTS idx_reconciliations_live_subject
    ON reconciliations(kind, subject_ref)
 WHERE status IN ('open', 'in_progress', 'accepted');

CREATE INDEX IF NOT EXISTS idx_reconciliations_status
    ON reconciliations(status, last_observed_at);

CREATE TABLE IF NOT EXISTS reconciliation_items (
    id                INTEGER PRIMARY KEY,
    reconciliation_id INTEGER NOT NULL
                        REFERENCES reconciliations(id) ON DELETE CASCADE,

    -- The individual thing in disagreement: a file path, a row id, a
    -- column name, a machine attribute.
    item_ref          TEXT NOT NULL,
    detail            TEXT,

    --   open              not yet addressed
    --   fixed             the disagreement is gone
    --   accepted          tolerated, with reasoning
    --   not_reproducible  looked, could not find it
    --   wont_fix          deliberately left
    disposition       TEXT NOT NULL DEFAULT 'open'
                        CHECK (disposition IN ('open', 'fixed', 'accepted',
                                               'not_reproducible',
                                               'wont_fix')),

    -- Per-item testimony, same three columns as vcs_merge_files so the
    -- two read the same way.
    reasoning         TEXT,
    confidence        TEXT,
    decided_by        TEXT,

    resolved_at       TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(reconciliation_id, item_ref)
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_items_parent
    ON reconciliation_items(reconciliation_id, disposition);
