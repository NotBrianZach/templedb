-- Migration: Add migration tracking system
-- Date: 2026-02-23
-- Purpose: Track which migrations have been applied to each deployment target

CREATE TABLE IF NOT EXISTS migration_history (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    target_name TEXT NOT NULL,        -- 'production', 'staging', 'local', etc.
    migration_file TEXT NOT NULL,     -- Relative path from project root
    migration_checksum TEXT NOT NULL, -- SHA256 of migration content
    applied_at TEXT NOT NULL DEFAULT (datetime('now')),
    applied_by TEXT,                  -- User or system that ran the migration
    execution_time_ms INTEGER,        -- How long the migration took
    status TEXT NOT NULL DEFAULT 'success',  -- 'success', 'failed', 'rolled_back'
    error_message TEXT,               -- Error details if status='failed'

    -- Prevent duplicate migrations per target
    UNIQUE(project_id, target_name, migration_file)
);

-- Index for common queries
CREATE INDEX IF NOT EXISTS idx_migration_history_project_target
    ON migration_history(project_id, target_name);

CREATE INDEX IF NOT EXISTS idx_migration_history_status
    ON migration_history(status);

CREATE INDEX IF NOT EXISTS idx_migration_history_applied_at
    ON migration_history(applied_at DESC);

-- No triggers needed - applied_at is set on INSERT only
