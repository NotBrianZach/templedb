-- Migration 087: edit_intents (Phase 2 groundwork)
--
-- Formalises the "proposed source edit" as a first-class DB entity,
-- so multi-agent editing has an intent queue instead of racing on
-- vcs_working_state, and every applied change is trace-able to a
-- named intent (which session proposed it, when, based on what
-- base revision).
--
-- This is intentionally MVP shape — it adds the storage layer and
-- the CRUD CLI (templedb intent {create, list, show, apply, cancel}).
-- Later work in Phase 2:
--   * templedb file set becomes a thin wrapper (create+apply)
--   * Agent MCP tools produce intents rather than direct writes
--   * vcs_working_state grows an intent_id reference
--   * Revert + dry-run
--
-- Status lifecycle:
--   proposed  → apply → applied
--             → cancel → cancelled
--
-- base_revision is a snapshot revision (a commit_hash from
-- source_snapshots.revision, or 'current' if the intent was
-- authored against latest). Recording it lets us detect stale
-- intents (base has moved) at apply time.

CREATE TABLE IF NOT EXISTS edit_intents (
    id                INTEGER PRIMARY KEY,
    session_id        INTEGER REFERENCES vcs_sessions(id),
    project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_path         TEXT NOT NULL,

    -- What the intent proposes
    base_revision     TEXT NOT NULL DEFAULT 'current',
    new_content_hash  TEXT NOT NULL,
    patch_summary     TEXT,

    -- Metadata
    author            TEXT,
    description       TEXT,

    -- Lifecycle
    status            TEXT NOT NULL DEFAULT 'proposed'
                        CHECK (status IN ('proposed', 'applied', 'cancelled')),
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    applied_at        TEXT,
    cancelled_at      TEXT,

    -- If applied via templedb VCS, points at the commit that recorded it
    applied_commit_id INTEGER REFERENCES vcs_commits(id)
);

CREATE INDEX IF NOT EXISTS idx_edit_intents_project
    ON edit_intents(project_id);

CREATE INDEX IF NOT EXISTS idx_edit_intents_session
    ON edit_intents(session_id);

CREATE INDEX IF NOT EXISTS idx_edit_intents_status
    ON edit_intents(status)
    WHERE status = 'proposed';

CREATE INDEX IF NOT EXISTS idx_edit_intents_file
    ON edit_intents(project_id, file_path, status);
