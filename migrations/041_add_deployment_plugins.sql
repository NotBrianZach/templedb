-- Add deployment scripts system
-- Allows projects to register custom deployment scripts
--
-- NOTE: Originally named 'deployment_plugins' but renamed to 'deployment_scripts'
-- in migration 043. This base migration now uses the final name.

CREATE TABLE IF NOT EXISTS deployment_scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug TEXT NOT NULL,
    script_path TEXT NOT NULL,
    description TEXT,
    enabled BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_slug)
);

CREATE INDEX IF NOT EXISTS idx_deployment_scripts_project ON deployment_scripts(project_slug);
CREATE INDEX IF NOT EXISTS idx_deployment_scripts_enabled ON deployment_scripts(enabled);

-- Trigger to update timestamp
CREATE TRIGGER IF NOT EXISTS update_deployment_scripts_timestamp
AFTER UPDATE ON deployment_scripts
BEGIN
    UPDATE deployment_scripts SET updated_at = datetime('now') WHERE id = NEW.id;
END;
