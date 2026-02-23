-- Phase 3: Checkout/Commit Workflow Schema
-- Adds tables for tracking checkouts and commit file changes

-- Track active checkouts (workspace locations)
CREATE TABLE IF NOT EXISTS checkouts (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    checkout_path TEXT NOT NULL,
    branch_name TEXT DEFAULT 'main',
    checkout_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_sync_at TEXT,
    is_active BOOLEAN DEFAULT 1,
    UNIQUE(project_id, checkout_path)
);

CREATE INDEX IF NOT EXISTS idx_checkouts_project ON checkouts(project_id);
CREATE INDEX IF NOT EXISTS idx_checkouts_active ON checkouts(is_active);

-- Track file changes in each commit
-- (vcs_commits table already exists from base schema)
CREATE TABLE IF NOT EXISTS commit_files (
    id INTEGER PRIMARY KEY,
    commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    change_type TEXT NOT NULL CHECK(change_type IN ('added', 'modified', 'deleted', 'renamed')),
    old_content_hash TEXT REFERENCES content_blobs(hash_sha256) ON DELETE SET NULL,
    new_content_hash TEXT REFERENCES content_blobs(hash_sha256) ON DELETE SET NULL,
    old_file_path TEXT,  -- For renames
    new_file_path TEXT,  -- For renames
    lines_added INTEGER DEFAULT 0,
    lines_removed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_commit_files_commit ON commit_files(commit_id);
CREATE INDEX IF NOT EXISTS idx_commit_files_file ON commit_files(file_id);
CREATE INDEX IF NOT EXISTS idx_commit_files_type ON commit_files(change_type);
