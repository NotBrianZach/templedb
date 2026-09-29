-- Migration 116: claims + claim_evidence (phase 1 of docs/CLAIMS_AND_WARRANTS.md)
--
-- A claim is a proposition with a revision scope. The point of the
-- table is the scope, not the prose: `commit_id` is NOT NULL so that a
-- claim about "now" is unwritable. A claim that cannot name the
-- revision it is about is exactly the thing that rots in a report.
--
-- Phase 1 deliberately omits warrant_checks and the checker registry.
-- `warrant_kind` is recorded but nothing evaluates it yet. Scope is
-- what prevents rot; checkers are what let you re-verify later, and
-- they are the more expensive half. This migration buys the first
-- without paying for the second.
--
-- There is no `is_valid` / `is_stale` column, on purpose. "Config
-- builds at revision R" does not become false when R+1 lands — it
-- stops *covering HEAD*. Coverage is a relation between a claim's
-- scope and the question being asked right now, so it is computed at
-- read time (see claims_service.coverage) and never stored. A stored
-- flag would reintroduce the exact failure this design exists to
-- prevent.

CREATE TABLE IF NOT EXISTS claims (
    id              INTEGER PRIMARY KEY,

    -- The proposition, asserted not hedged.
    statement       TEXT NOT NULL,

    -- ---- Scope: what the claim is about --------------------------
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    commit_id       INTEGER NOT NULL REFERENCES vcs_commits(id),
    host_name       TEXT,               -- NULL = host-independent
    inputs_json     TEXT,               -- template values, flags, env

    -- ---- Warrant: names the inference rule, not the conclusion ----
    -- Checkers land in phase 2, keyed by this column. 'asserted' means
    -- there is no predicate and never will be — an agent's say-so,
    -- recorded as such so it is distinguishable from a checked claim.
    warrant_kind    TEXT NOT NULL,
    warrant_gloss   TEXT,

    -- ---- Attribution (optional) ----------------------------------
    -- report_ref is an attribution, NOT a parent. Claims are produced
    -- by work, which happens constantly; reports are authored, which
    -- happens rarely. Requiring a report would throttle claim creation
    -- to human writing speed.
    asserted_by     TEXT NOT NULL,      -- 'test_runner', 'ast_build_service', agent ref
    report_ref      TEXT,               -- entities.external_ref of a Report

    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),

    -- Re-running the same work at the same revision is a re-observation,
    -- not a second claim.
    UNIQUE(project_id, commit_id, statement)
);

CREATE INDEX IF NOT EXISTS idx_claims_scope
    ON claims(project_id, commit_id);
CREATE INDEX IF NOT EXISTS idx_claims_warrant
    ON claims(warrant_kind);

-- Evidence is never copied. It stays in the table that owns it
-- (ast_builds, test_runs, agent_work_log) and this is a join with a
-- role. (evidence_kind, evidence_ref) mirrors the entities convention
-- so heterogeneous ID types coexist.
CREATE TABLE IF NOT EXISTS claim_evidence (
    id              INTEGER PRIMARY KEY,
    claim_id        INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,

    -- 'TestRun'  -> test_runs.id
    -- 'AstBuild' -> '<host_name>/<output_hash>'  (matches the AstBuild entity ref)
    -- 'WorkLog'  -> agent_work_log.id
    evidence_kind   TEXT NOT NULL,
    evidence_ref    TEXT NOT NULL,

    -- 'undercuts' lets a claim carry its own contrary evidence rather
    -- than the author silently omitting it.
    role            TEXT NOT NULL DEFAULT 'supports'
                      CHECK (role IN ('supports', 'undercuts')),

    -- Fingerprint captured at assertion time. When phase 2 lands, a
    -- mismatch here means the evidence moved under the claim and the
    -- warrant must fail loudly rather than pass against different
    -- bytes than the asserter saw.
    evidence_hash   TEXT,

    observed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(claim_id, evidence_kind, evidence_ref)
);

CREATE INDEX IF NOT EXISTS idx_claim_evidence_claim
    ON claim_evidence(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_evidence_source
    ON claim_evidence(evidence_kind, evidence_ref);
