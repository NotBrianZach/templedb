-- Migration 007: Add Nix FHS Environment Support
-- Enables creating reproducible development environments with buildFHSEnvironment

-- Environment definitions
CREATE TABLE IF NOT EXISTS nix_environments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    env_name TEXT NOT NULL,
    description TEXT,

    -- Build configuration
    base_packages TEXT DEFAULT '[]', -- JSON array of base packages
    target_packages TEXT DEFAULT '[]', -- JSON array for targetPkgs
    multi_packages TEXT DEFAULT '[]', -- JSON array for multiPkgs

    -- Environment setup
    profile TEXT, -- Shell profile script
    runScript TEXT DEFAULT 'bash', -- Command to run when entering env

    -- Metadata
    auto_detected BOOLEAN DEFAULT 0, -- If environment was auto-detected from files
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, env_name)
);

-- Environment variables
CREATE TABLE IF NOT EXISTS nix_env_variables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    environment_id INTEGER NOT NULL,
    var_name TEXT NOT NULL,
    var_value TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (environment_id) REFERENCES nix_environments(id) ON DELETE CASCADE,
    UNIQUE(environment_id, var_name)
);

-- Track environment usage/sessions
CREATE TABLE IF NOT EXISTS nix_env_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    environment_id INTEGER NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    command_run TEXT,
    exit_code INTEGER,

    FOREIGN KEY (environment_id) REFERENCES nix_environments(id) ON DELETE CASCADE
);

-- View: Complete environment configurations
CREATE VIEW IF NOT EXISTS nix_environments_view AS
SELECT
    ne.id,
    ne.project_id,
    p.slug AS project_slug,
    p.name AS project_name,
    ne.env_name,
    ne.description,
    ne.base_packages,
    ne.target_packages,
    ne.multi_packages,
    ne.profile,
    ne.runScript,
    ne.auto_detected,
    ne.is_active,
    ne.created_at,
    ne.updated_at,
    (SELECT COUNT(*) FROM nix_env_variables WHERE environment_id = ne.id) AS var_count,
    (SELECT COUNT(*) FROM nix_env_sessions WHERE environment_id = ne.id) AS session_count
FROM nix_environments ne
JOIN projects p ON ne.project_id = p.id
WHERE ne.is_active = 1
ORDER BY p.slug, ne.env_name;

-- View: Environment variables with project context
CREATE VIEW IF NOT EXISTS nix_env_vars_view AS
SELECT
    nev.id,
    nev.environment_id,
    ne.env_name,
    p.slug AS project_slug,
    nev.var_name,
    nev.var_value,
    nev.description
FROM nix_env_variables nev
JOIN nix_environments ne ON nev.environment_id = ne.id
JOIN projects p ON ne.project_id = p.id
ORDER BY p.slug, ne.env_name, nev.var_name;

-- View: Environment session history
CREATE VIEW IF NOT EXISTS nix_env_sessions_view AS
SELECT
    nes.id,
    ne.env_name,
    p.slug AS project_slug,
    nes.started_at,
    nes.ended_at,
    CASE
        WHEN nes.ended_at IS NULL THEN 'running'
        ELSE 'completed'
    END AS status,
    nes.command_run,
    nes.exit_code,
    CAST((julianday(COALESCE(nes.ended_at, 'now')) - julianday(nes.started_at)) * 86400 AS INTEGER) AS duration_seconds
FROM nix_env_sessions nes
JOIN nix_environments ne ON nes.environment_id = ne.id
JOIN projects p ON ne.project_id = p.id
ORDER BY nes.started_at DESC;

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_nix_environments_project ON nix_environments(project_id);
CREATE INDEX IF NOT EXISTS idx_nix_environments_active ON nix_environments(is_active);
CREATE INDEX IF NOT EXISTS idx_nix_env_variables_env ON nix_env_variables(environment_id);
CREATE INDEX IF NOT EXISTS idx_nix_env_sessions_env ON nix_env_sessions(environment_id);
CREATE INDEX IF NOT EXISTS idx_nix_env_sessions_time ON nix_env_sessions(started_at);

-- Sample environment for templedb project itself
INSERT OR IGNORE INTO nix_environments (project_id, env_name, description, base_packages, profile)
SELECT
    id,
    'dev',
    'TempleDB development environment',
    '["python311", "python311Packages.textual", "python311Packages.rich", "sqlite", "nodejs_20", "git"]',
    'export TEMPLEDB_PATH="$HOME/.local/share/templedb/templedb.sqlite"
export EDITOR="vim"
echo "TempleDB development environment loaded"
echo "Database: $TEMPLEDB_PATH"'
FROM projects
WHERE slug = 'templedb'
LIMIT 1;
