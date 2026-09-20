-- Migration 104: deploy_stage_runs — every deploy-chain stage records
--                its input+output hashes as a fact
--
-- Motivation: the deploy chain (file_set → vcs_commit → materialize →
-- git_push → flake_resolve → nix_build → system_switch) has silent
-- no-op paths at every stage. Publish skips its VCS-commit if nothing
-- staged in this session. Materialize skips its git-commit if disk
-- matches HEAD. Nix locks to a stale rev if daemon HEAD hadn't
-- advanced. Each stage optimises its own idempotency and reports
-- success either way. Result: cross-stage, "everything says it worked"
-- is compatible with "nothing changed anywhere."
--
-- Fix: every stage writes a row here declaring its input_hash,
-- output_hash, and prev_stage_run_id. That's enough to:
--   1. Chain-verify offline (doctor invariant #12: adjacent stages
--      must chain by hash — my input == your output).
--   2. Answer "why is this file/binary/generation this way?"
--      (provenance query = graph traversal, not shell archaeology).
--   3. Detect no-op stages loudly — if stage.input_hash ==
--      stage.output_hash, that's declared, not silent.
--
-- Design: reports/2026-09-19-2012-declarative-reframe-*.html §3+§4.

CREATE TABLE IF NOT EXISTS deploy_stage_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_kind          TEXT NOT NULL,       -- see enum below
    slug                TEXT NOT NULL,       -- project this run affected
    session_id          INTEGER,             -- REFERENCES vcs_sessions(id), nullable for
                                             -- stages outside a VCS session (e.g. nix_build)
    input_hash          TEXT,                -- 12+ chars; NULL if stage has no input
    output_hash         TEXT,                -- 12+ chars; NULL on hard failure
    prev_stage_run_id   INTEGER REFERENCES deploy_stage_runs(id),  -- chain pointer
    started_at          TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at            TEXT,                -- NULL = in progress
    outcome             TEXT,                -- 'success' | 'noop' | 'failed'
    metadata_json       TEXT                 -- stage-specific detail (file count, etc.)
);

-- stage_kind enum, documented not enforced:
--   'file_set'       — templedb file set (single-file write to DB)
--   'vcs_commit'     — templedb vcs commit / file set --commit
--   'materialize'    — publish's DB→checkout step (may or may not
--                      produce a git commit)
--   'git_push'       — publish's push to mirrors
--   'flake_resolve'  — nix flake fetches an input; output_hash = rev
--   'nix_build'      — nix build produced a store path
--   'system_switch'  — /run/current-system flipped
--
-- New kinds MAY be added without a migration. Doctor invariants may
-- gain kind-specific rules, but the substrate is generic.

CREATE INDEX IF NOT EXISTS idx_deploy_stage_runs_slug_kind
    ON deploy_stage_runs(slug, stage_kind, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_deploy_stage_runs_prev
    ON deploy_stage_runs(prev_stage_run_id);
CREATE INDEX IF NOT EXISTS idx_deploy_stage_runs_in_progress
    ON deploy_stage_runs(started_at) WHERE ended_at IS NULL;

-- Convenience view: most recent run per (slug, stage_kind).
CREATE VIEW IF NOT EXISTS deploy_stage_current AS
    SELECT r.*
      FROM deploy_stage_runs r
      JOIN (
        SELECT slug, stage_kind, MAX(started_at) AS latest
          FROM deploy_stage_runs
         WHERE ended_at IS NOT NULL
         GROUP BY slug, stage_kind
      ) mx
        ON r.slug = mx.slug
       AND r.stage_kind = mx.stage_kind
       AND r.started_at = mx.latest;
