-- Migration 065: Deployment pipeline automation
--
-- Adds deploy triggers (branch->target mapping for auto-deploy on commit),
-- deploy notifications (webhook/command hooks), and enhances rollback support.

-- Deploy triggers: branch->target auto-deploy rules
CREATE TABLE IF NOT EXISTS deployment_triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    branch_pattern TEXT NOT NULL,
    target_name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    auto_rollback INTEGER NOT NULL DEFAULT 0,
    require_health_check INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_id, branch_pattern, target_name)
);

CREATE INDEX IF NOT EXISTS idx_deployment_triggers_project ON deployment_triggers(project_id);

-- Deploy notifications: webhook/command hooks for deploy events
CREATE TABLE IF NOT EXISTS deployment_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    event TEXT NOT NULL,
    notification_type TEXT NOT NULL,
    config TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_deployment_notifications_project ON deployment_notifications(project_id);
CREATE INDEX IF NOT EXISTS idx_deployment_notifications_event ON deployment_notifications(event);
