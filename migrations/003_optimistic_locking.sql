-- Phase 4: Optimistic Locking Schema
-- Adds version tracking and checkout snapshots for conflict detection

-- Add version column to file_contents
-- This tracks the version of each file's content
ALTER TABLE file_contents ADD COLUMN version INTEGER DEFAULT 1;

-- Ensure all existing rows have version initialized
-- (SQLite ALTER TABLE ADD COLUMN should set DEFAULT, but be explicit)
UPDATE file_contents SET version = 1 WHERE version IS NULL;

-- Create index on version for fast lookups
CREATE INDEX IF NOT EXISTS idx_file_contents_version ON file_contents(file_id, version);

-- Create checkout snapshots table
-- Records what version each file was at when checked out
CREATE TABLE IF NOT EXISTS checkout_snapshots (
    id INTEGER PRIMARY KEY,
    checkout_id INTEGER NOT NULL REFERENCES checkouts(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    version INTEGER NOT NULL,
    checked_out_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(checkout_id, file_id)
);

CREATE INDEX IF NOT EXISTS idx_checkout_snapshots_checkout ON checkout_snapshots(checkout_id);
CREATE INDEX IF NOT EXISTS idx_checkout_snapshots_file ON checkout_snapshots(file_id);
CREATE INDEX IF NOT EXISTS idx_checkout_snapshots_version ON checkout_snapshots(version);

-- Create conflicts table (for tracking detected conflicts)
CREATE TABLE IF NOT EXISTS file_conflicts (
    id INTEGER PRIMARY KEY,
    checkout_id INTEGER NOT NULL REFERENCES checkouts(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    base_version INTEGER NOT NULL,           -- Version at checkout
    current_version INTEGER NOT NULL,        -- Current version in DB
    conflict_type TEXT NOT NULL,             -- 'version_mismatch', 'content_diverged'
    detected_at TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_at TEXT,
    resolution_strategy TEXT,                -- 'abort', 'force', 'merge', 'manual'
    resolved_by TEXT
);

CREATE INDEX IF NOT EXISTS idx_file_conflicts_checkout ON file_conflicts(checkout_id);
CREATE INDEX IF NOT EXISTS idx_file_conflicts_file ON file_conflicts(file_id);
CREATE INDEX IF NOT EXISTS idx_file_conflicts_unresolved ON file_conflicts(resolved_at) WHERE resolved_at IS NULL;
