-- Migration: Add deployment history tracking for rollbacks
-- Date: 2026-03-03
-- Purpose: Track all deployments to enable rollback functionality

-- Deployment history table
CREATE TABLE IF NOT EXISTS deployment_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    target_name TEXT NOT NULL,
    deployment_type TEXT NOT NULL,  -- 'deploy' or 'rollback'

    -- Version tracking
    commit_hash TEXT,  -- VCS commit that was deployed
    cathedral_checksum TEXT,  -- Cathedral package checksum if used

    -- Status
    status TEXT NOT NULL,  -- 'in_progress', 'success', 'failed', 'rolled_back'
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    duration_ms INTEGER,

    -- Execution details
    deployed_by TEXT,  -- User or system that triggered deployment
    deployment_method TEXT,  -- 'orchestrator', 'manual', 'ci'

    -- Results
    groups_deployed TEXT,  -- JSON array of group names
    files_deployed TEXT,  -- JSON array of file paths
    error_message TEXT,

    -- Snapshot of deployed state
    deployment_snapshot TEXT,  -- JSON snapshot of what was deployed

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- Index for querying deployment history
CREATE INDEX IF NOT EXISTS idx_deployment_history_project_target
    ON deployment_history(project_id, target_name, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_deployment_history_status
    ON deployment_history(status, started_at DESC);

-- Deployment snapshots table (stores actual deployed files for rollback)
CREATE TABLE IF NOT EXISTS deployment_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    file_size_bytes INTEGER,

    -- For rollback: store actual content or reference
    content_stored BOOLEAN DEFAULT 0,

    FOREIGN KEY (deployment_id) REFERENCES deployment_history(id) ON DELETE CASCADE,
    UNIQUE(deployment_id, file_path)
);

CREATE INDEX IF NOT EXISTS idx_deployment_snapshots_deployment
    ON deployment_snapshots(deployment_id);

-- Rollback metadata table (tracks relationship between deployments)
CREATE TABLE IF NOT EXISTS deployment_rollbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_deployment_id INTEGER NOT NULL,  -- Deployment being rolled back
    to_deployment_id INTEGER,  -- Target deployment to roll back to (NULL for initial state)
    rollback_deployment_id INTEGER NOT NULL,  -- The rollback deployment record
    rollback_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (from_deployment_id) REFERENCES deployment_history(id),
    FOREIGN KEY (to_deployment_id) REFERENCES deployment_history(id),
    FOREIGN KEY (rollback_deployment_id) REFERENCES deployment_history(id)
);

-- Migration tracking enhancements (link to deployments)
-- Note: This is optional - only works if migration_history table exists
-- ALTER TABLE migration_history ADD COLUMN deployment_id INTEGER
--     REFERENCES deployment_history(id);
--
-- CREATE INDEX IF NOT EXISTS idx_migration_history_deployment
--     ON migration_history(deployment_id);
