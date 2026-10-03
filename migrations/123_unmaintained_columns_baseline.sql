-- 123_unmaintained_columns_baseline.sql
--
-- A registry of columns that currently hold no information, so that the
-- next one to appear is reported instead of discovered years later.
--
-- The pattern this exists to catch, from the "Wider point" of
-- reports/2026-09-27-2103-checkout-role-and-session-scoped-resolution-
-- design.html: `checkouts.is_active` was a boolean that no code ever
-- cleared, so it decayed into a constant while still looking like state.
-- `WHERE is_active = 1` selected all 61 rows while appearing to filter.
-- Every reader then layered its own heuristic on top and the heuristics
-- diverged. That report counted three instances (project_files.
-- lines_of_code, project_files.status, checkouts.is_active); measuring
-- properly on 2026-10-02 found 47.
--
-- A column nothing maintains is worse than a missing column, because a
-- missing column cannot be trusted by mistake. The two shapes recorded
-- here differ in how they mislead:
--
--   all_null  every row NULL. A reader gets None and usually falls back
--             to a hardcoded default -- vcs_sessions.reap_policy and
--             expected_lifetime_seconds are both ALL NULL across 953
--             rows, yet session gc prints "lifetime 86400s,
--             policy=orphan_stages" for every session. The numbers come
--             from code, not from the column being read.
--   constant  every row the same value. Worse, because the value is
--             plausible: vcs_commits.lines_removed is 0 on all 1039
--             rows, so anything rendering a diffstat from it is
--             confidently wrong and nothing about the read looks broken.
--
-- Deliberately NOT recorded: the "sparse" shape -- one distinct value
-- plus many NULLs. edit_intents.cancelled_at (1 of 780 set) and
-- vcs_sessions.host (952 of 953) look identical to a constant under
-- COUNT(DISTINCT), which ignores NULLs, but both are correct: an
-- optional timestamp and a near-single-machine fleet. Treating them as
-- violations is how this invariant would have become noise.
--
-- Being in this table is NOT approval. Most rows carry 'not triaged' and
-- mean only "true on 2026-10-02". The point is that the SET is frozen:
-- a new unmaintained column is a regression the invariant reports, while
-- these stay quiet until someone populates or drops them.

CREATE TABLE IF NOT EXISTS unmaintained_columns_baseline (
    id                    INTEGER PRIMARY KEY,
    table_name            TEXT NOT NULL,
    column_name           TEXT NOT NULL,
    -- 'all_null' | 'constant' -- recorded so that a column CHANGING
    -- shape (someone starts writing one value where it was NULL) is
    -- still visible rather than matching the baseline on name alone.
    shape                 TEXT NOT NULL,
    row_count_at_baseline INTEGER NOT NULL,
    accepted_at           TEXT NOT NULL DEFAULT (datetime('now')),
    reason                TEXT,
    UNIQUE(table_name, column_name)
);

INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('agent_events', 'raw_payload_json', 'all_null', 10014, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('agent_messages', 'content_format', 'constant', 897, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('audit_log', 'actor', 'constant', 1563, 'single-user install');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('config_nodes', 'enabled', 'constant', 1254, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('config_nodes', 'description', 'all_null', 1254, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('config_nodes', 'category', 'all_null', 1254, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('content_blobs', 'storage_location', 'constant', 12246, 'all blobs are inline; no other backend in use');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('content_blobs', 'external_path', 'all_null', 12246, 'external/compressed blob storage is not in use');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('content_blobs', 'chunk_count', 'constant', 12246, 'blob chunking is not in use');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('content_blobs', 'compression', 'all_null', 12246, 'external/compressed blob storage is not in use');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('content_blobs', 'remote_url', 'all_null', 12246, 'external/compressed blob storage is not in use');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('content_blobs', 'fetch_count', 'constant', 12246, 'remote blob fetch is not in use');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('content_blobs', 'last_fetched_at', 'all_null', 12246, 'external/compressed blob storage is not in use');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('deploy_stage_runs', 'prev_stage_run_id', 'all_null', 693, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('edit_intents', 'base_revision', 'constant', 780, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('edit_intents', 'author', 'constant', 780, 'single-user install');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('edit_intents', 'applied_commit_id', 'all_null', 780, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('file_contents', 'is_current', 'constant', 2021, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('ingestion_runs', 'entities_refreshed', 'constant', 1858, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('invariant_checks', 'ingestion_run_id', 'all_null', 514, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('nix_store_paths', 'is_valid', 'constant', 10389, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('project_files', 'description', 'all_null', 2338, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('project_files', 'purpose', 'all_null', 2338, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('project_files', 'owner', 'all_null', 2338, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('project_files', 'documentation_url', 'all_null', 2338, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('project_files', 'inline_documentation', 'all_null', 2338, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('project_files', 'complexity_score', 'all_null', 2338, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('project_files', 'edit_mode', 'all_null', 2338, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('relations', 'attributes_json', 'all_null', 27318, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('relations', 'sync_scope', 'all_null', 27318, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('sync_cache', 'file_size', 'constant', 1407, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('sync_entities', 'sync_scope', 'constant', 4283, 'single sync scope on this install');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('sync_relations', 'attributes_json', 'constant', 3790, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('sync_relations', 'sync_scope', 'constant', 3790, 'single sync scope on this install');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('tool_calls', 'finished_at', 'all_null', 8453, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('tool_calls', 'args_hash', 'all_null', 8453, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('tool_calls', 'result_hash', 'all_null', 8453, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('vcs_commit_parents', 'parent_order', 'constant', 718, 'no merge commits yet, so every parent is first');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('vcs_commits', 'merge_parent_commit_id', 'all_null', 1039, 'no merge commits yet; merges also tracked in vcs_commit_parents');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('vcs_commits', 'committer', 'all_null', 1039, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('vcs_commits', 'committer_email', 'all_null', 1039, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('vcs_commits', 'lines_removed', 'constant', 1039, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('vcs_commits', 'git_commit_hash', 'all_null', 1039, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('vcs_commits', 'git_branch', 'all_null', 1039, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('vcs_file_states', 'previous_path', 'all_null', 4001, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('vcs_sessions', 'expected_lifetime_seconds', 'all_null', 953, 'pre-existing at baseline; not triaged');
INSERT OR IGNORE INTO unmaintained_columns_baseline
  (table_name, column_name, shape, row_count_at_baseline, reason) VALUES
  ('vcs_sessions', 'reap_policy', 'all_null', 953, 'pre-existing at baseline; not triaged');
