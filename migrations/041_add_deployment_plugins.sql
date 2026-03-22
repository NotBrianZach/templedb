-- Add deployment plugins system
-- Allows projects to register custom deployment scripts

CREATE TABLE IF NOT EXISTS deployment_plugins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug TEXT NOT NULL,
    script_path TEXT NOT NULL,
    description TEXT,
    enabled BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_slug)
);

CREATE INDEX IF NOT EXISTS idx_deployment_plugins_project ON deployment_plugins(project_slug);
CREATE INDEX IF NOT EXISTS idx_deployment_plugins_enabled ON deployment_plugins(enabled);

-- Trigger to update timestamp
CREATE TRIGGER IF NOT EXISTS update_deployment_plugins_timestamp
AFTER UPDATE ON deployment_plugins
BEGIN
    UPDATE deployment_plugins SET updated_at = datetime('now') WHERE id = NEW.id;
END;
