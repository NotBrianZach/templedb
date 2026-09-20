-- Migration 048: Add deployment tracking and health checks
-- This enables audit trails, rollback support, and deployment monitoring

-- Deployment history table
CREATE TABLE IF NOT EXISTS deployment_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    target TEXT NOT NULL,  -- staging, production, etc.
    deployed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deployed_by TEXT,  -- username or 'system'
    status TEXT NOT NULL CHECK(status IN ('in_progress', 'success', 'failed', 'rolled_back')),
    exit_code INTEGER,
    deployment_hash TEXT,  -- Content hash from cathedral package
    duration_seconds REAL,
    work_dir TEXT,  -- Path to deployment directory
    notes TEXT,  -- Error messages or deployment notes

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_deployment_history_project ON deployment_history(project_id);
CREATE INDEX IF NOT EXISTS idx_deployment_history_target ON deployment_history(target);
CREATE INDEX IF NOT EXISTS idx_deployment_history_status ON deployment_history(status);
CREATE INDEX IF NOT EXISTS idx_deployment_history_deployed_at ON deployment_history(deployed_at);

-- Deployment health checks
CREATE TABLE IF NOT EXISTS deployment_health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id INTEGER NOT NULL,
    check_type TEXT NOT NULL,  -- 'http', 'database', 'edge_function', 'custom'
    check_name TEXT NOT NULL,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL CHECK(status IN ('pass', 'fail', 'skip', 'timeout')),
    response_time_ms INTEGER,
    endpoint TEXT,  -- URL or connection string checked
    status_code INTEGER,  -- HTTP status code if applicable
    error_message TEXT,
    details TEXT,  -- JSON with additional check details

    FOREIGN KEY (deployment_id) REFERENCES deployment_history(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_health_checks_deployment ON deployment_health_checks(deployment_id);
CREATE INDEX IF NOT EXISTS idx_health_checks_type ON deployment_health_checks(check_type);
CREATE INDEX IF NOT EXISTS idx_health_checks_status ON deployment_health_checks(status);

-- Deployment environment snapshot (for rollback)
CREATE TABLE IF NOT EXISTS deployment_environment_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id INTEGER NOT NULL,
    var_name TEXT NOT NULL,
    var_value TEXT,

    FOREIGN KEY (deployment_id) REFERENCES deployment_history(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_deployment_env_snapshot ON deployment_environment_snapshot(deployment_id);

-- View for latest deployments per project/target
CREATE VIEW IF NOT EXISTS latest_deployments AS
SELECT
    dh.*,
    p.slug as project_slug,
    p.name as project_name
FROM deployment_history dh
JOIN projects p ON dh.project_id = p.id
WHERE dh.id IN (
    SELECT MAX(id)
    FROM deployment_history
    GROUP BY project_id, target
);

-- View for deployment success rate
CREATE VIEW IF NOT EXISTS deployment_stats AS
SELECT
    p.slug as project_slug,
    dh.target,
    COUNT(*) as total_deployments,
    SUM(CASE WHEN dh.status = 'success' THEN 1 ELSE 0 END) as successful_deployments,
    SUM(CASE WHEN dh.status = 'failed' THEN 1 ELSE 0 END) as failed_deployments,
    AVG(dh.duration_seconds) as avg_duration_seconds,
    MAX(dh.deployed_at) as last_deployed_at
FROM deployment_history dh
JOIN projects p ON dh.project_id = p.id
GROUP BY p.id, dh.target;
