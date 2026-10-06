-- 126_separate_git_shas_from_commit_ids.sql
--
-- Give vcs_commits.commit_hash a single meaning.
--
-- It carried two identifier namespaces at once. `vcs commit` writes
-- sha256(slug:branch:message:time)[:16].upper() -- 842 rows of 16-char
-- uppercase native ids. git-history import wrote the raw git SHA
-- straight through (importer/git_history.py: commit_hash=commit.hash)
-- -- 261 rows of 40-char lowercase. Both in the same column, in the
-- same projects: templedb alone held 395 of the first and 192 of the
-- second.
--
-- vcs_commits.git_commit_hash has existed for the git SHA the whole
-- time and was NULL on all 1,109 rows, written by nothing in src/.
-- Migration 123 recorded it as all_null without anyone noticing the
-- data was landing in the neighbouring column.
--
-- The visible symptom was casing. SQLite's `=` is case-sensitive while
-- LIKE is not, so a hash typed in the other case returns no rows rather
-- than an error -- indistinguishable from "no such commit". On
-- 2026-10-06 that made five commits cited by handoffs #4-#7 look absent
-- from history; they were present, stored lowercase. 125 patched the
-- read paths with COLLATE NOCASE, which worked but only made the
-- collision survivable instead of impossible. This removes the cause.
--
-- AFTER THIS MIGRATION
--   commit_hash      uppercase hex, native ids only, one namespace
--   git_commit_hash  the 40-char git SHA, lowercase as git emits it
--
-- The git SHA stays resolvable: get_commit_by_hash matches either
-- column, so every existing reference to a lowercase SHA in a report,
-- handoff or commit message still works.
--
-- The minted id is upper(substr(sha,1,16)) -- deterministic, derived
-- from the SHA so the link is legible, and in the same 16-char
-- uppercase shape as every other native id. Verified before writing:
-- 261 rows, 0 collisions among themselves, 0 against existing hashes,
-- 0 malformed.
--
-- One further row is normalised: prediction_dashboards' 2026-06-09
-- "Initial import" carries a 64-char lowercase native id from an older
-- import path (the other five 64-char rows are already uppercase).
-- It is not a git SHA, so it gets no git_commit_hash -- only its case.

CREATE TABLE IF NOT EXISTS commit_hash_migration_126 (
    commit_id  INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    old_hash   TEXT NOT NULL,
    new_hash   TEXT NOT NULL,
    -- 'git-sha'   the old value was a git SHA and moves to
    --             git_commit_hash
    -- 'case-only' a native id that was merely lowercase; no SHA to keep
    kind       TEXT NOT NULL
);

-- Built first so every UPDATE below keys off the map rather than off
-- the live value. Without it the order of the statements would matter
-- and vcs_commits would have to go last; with it, each table can be
-- rewritten independently and the migration is re-runnable.
INSERT OR IGNORE INTO commit_hash_migration_126
    (commit_id, project_id, old_hash, new_hash, kind)
SELECT id, project_id, commit_hash, upper(substr(commit_hash, 1, 16)),
       'git-sha'
  FROM vcs_commits
 WHERE length(commit_hash) = 40
   AND commit_hash <> upper(commit_hash);

INSERT OR IGNORE INTO commit_hash_migration_126
    (commit_id, project_id, old_hash, new_hash, kind)
SELECT id, project_id, commit_hash, upper(commit_hash), 'case-only'
  FROM vcs_commits
 WHERE length(commit_hash) <> 40
   AND commit_hash <> upper(commit_hash);

-- Commit entities carry the hash inside external_ref as '<slug>/<hash>'
UPDATE entities
   SET external_ref = (
       SELECT p.slug || '/' || m.new_hash
         FROM commit_hash_migration_126 m
         JOIN projects p ON p.id = m.project_id
        WHERE entities.external_ref = p.slug || '/' || m.old_hash)
 WHERE kind = 'Commit'
   AND EXISTS (
       SELECT 1 FROM commit_hash_migration_126 m
         JOIN projects p ON p.id = m.project_id
        WHERE entities.external_ref = p.slug || '/' || m.old_hash);

UPDATE nix_generations
   SET commit_hash = (SELECT m.new_hash FROM commit_hash_migration_126 m
                       WHERE m.old_hash = nix_generations.commit_hash)
 WHERE commit_hash IN (SELECT old_hash FROM commit_hash_migration_126);

UPDATE project_files
   SET last_commit_hash = (SELECT m.new_hash FROM commit_hash_migration_126 m
                            WHERE m.old_hash = project_files.last_commit_hash)
 WHERE last_commit_hash IN (SELECT old_hash FROM commit_hash_migration_126);

UPDATE report_implementations
   SET commit_hash = (SELECT m.new_hash FROM commit_hash_migration_126 m
                       WHERE m.old_hash = report_implementations.commit_hash)
 WHERE commit_hash IN (SELECT old_hash FROM commit_hash_migration_126);

-- The CRDT shadow. vcs_commits has only an AFTER INSERT trigger, so an
-- UPDATE does not propagate and this has to be rewritten by hand.
UPDATE sync_vcs_commits
   SET commit_hash = (SELECT m.new_hash FROM commit_hash_migration_126 m
                       WHERE m.old_hash = sync_vcs_commits.commit_hash)
 WHERE commit_hash IN (SELECT old_hash FROM commit_hash_migration_126);

-- Last, the table itself. git_commit_hash is set only for 'git-sha'
-- rows; a 'case-only' row has no SHA and correctly stays NULL.
UPDATE vcs_commits
   SET git_commit_hash = (SELECT m.old_hash FROM commit_hash_migration_126 m
                           WHERE m.commit_id = vcs_commits.id
                             AND m.kind = 'git-sha'),
       commit_hash     = (SELECT m.new_hash FROM commit_hash_migration_126 m
                           WHERE m.commit_id = vcs_commits.id)
 WHERE id IN (SELECT commit_id FROM commit_hash_migration_126);

CREATE INDEX IF NOT EXISTS idx_vcs_commits_git_hash
    ON vcs_commits(git_commit_hash);
