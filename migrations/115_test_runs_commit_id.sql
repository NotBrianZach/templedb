-- Migration 115: pin test_runs to the revision they were run against.
--
-- Before this, a test result was tied only to (project_id, created_at).
-- That is enough to say "the suite passed at some wall-clock time" and
-- not enough to say "the suite passed at revision R" — so a passing run
-- could never be reused as evidence for a specific commit, only as a
-- vague recency signal. Every other evidence-bearing table already
-- carries its provenance (ast_builds.output_hash, edit_intents.
-- applied_commit_id, agent_work_log.run_id); test_runs was the gap.
--
-- Nullable on purpose: existing rows genuinely have unknown provenance
-- and backfilling them from created_at would invent a pin that was
-- never observed. NULL here means "unpinned", not "pinned to nothing".

ALTER TABLE test_runs ADD COLUMN commit_id INTEGER REFERENCES vcs_commits(id);

CREATE INDEX IF NOT EXISTS idx_test_runs_commit
    ON test_runs(commit_id);
CREATE INDEX IF NOT EXISTS idx_test_runs_project_created
    ON test_runs(project_id, created_at DESC);
