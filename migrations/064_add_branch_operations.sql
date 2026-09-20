-- Migration 064: Add branch operations support
--
-- Adds active_branch_id to projects, vcs_commit_parents join table,

-- Step 1: Add active_branch_id to projects
ALTER TABLE projects ADD COLUMN active_branch_id INTEGER REFERENCES vcs_branches(id);

-- Backfill: set active_branch_id to the default branch for each project
UPDATE projects SET active_branch_id = (
    SELECT id FROM vcs_branches WHERE project_id = projects.id AND is_default = 1 LIMIT 1
) WHERE active_branch_id IS NULL;

-- Step 2: Create vcs_commit_parents join table for merge commits
CREATE TABLE IF NOT EXISTS vcs_commit_parents (
    commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    parent_commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    parent_order INTEGER NOT NULL DEFAULT 0,

    PRIMARY KEY (commit_id, parent_commit_id)
);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_parents_parent ON vcs_commit_parents(parent_commit_id);

-- Step 3: Backfill vcs_commit_parents from existing parent_commit_id
INSERT OR IGNORE INTO vcs_commit_parents (commit_id, parent_commit_id, parent_order)
SELECT id, parent_commit_id, 0
FROM vcs_commits
WHERE parent_commit_id IS NOT NULL;

-- Also backfill merge parents
INSERT OR IGNORE INTO vcs_commit_parents (commit_id, parent_commit_id, parent_order)
SELECT id, merge_parent_commit_id, 1
FROM vcs_commits
WHERE merge_parent_commit_id IS NOT NULL;
