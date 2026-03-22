-- Migration 010: Consolidate Environment Variable Tables
-- Consolidates env_vars, project_env_vars, nix_env_variables, and compound_values
-- into single environment_variables table
--
-- Before: 4 tables (env_vars, project_env_vars, nix_env_variables, compound_values)
-- After: 1 table (environment_variables)
-- Reduction: 3 tables

BEGIN TRANSACTION;

-- Create consolidated environment_variables table
CREATE TABLE IF NOT EXISTS environment_variables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_type TEXT NOT NULL CHECK(scope_type IN ('global', 'project', 'nix_env')),
    scope_id INTEGER,  -- NULL for global, project_id for project, nix_environment_id for nix_env
    var_name TEXT NOT NULL,
    var_value TEXT,
    value_type TEXT DEFAULT 'static' CHECK(value_type IN ('static', 'compound', 'secret_ref')),
    template TEXT,  -- For compound values (template with ${VAR} substitutions)
    is_secret BOOLEAN DEFAULT 0,
    is_exported BOOLEAN DEFAULT 1,  -- Whether to export to shell environment
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scope_type, scope_id, var_name)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_environment_variables_scope
    ON environment_variables(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_environment_variables_name
    ON environment_variables(var_name);
CREATE INDEX IF NOT EXISTS idx_environment_variables_type
    ON environment_variables(value_type);

-- Migrate data from env_vars (global scope)
INSERT INTO environment_variables (
    scope_type, scope_id, var_name, var_value, value_type,
    is_exported, description, created_at, updated_at
)
SELECT
    'global' as scope_type,
    NULL as scope_id,
    var_name,
    var_value,
    'static' as value_type,
    is_exported,
    description,
    created_at,
    updated_at
FROM env_vars
WHERE EXISTS (SELECT 1 FROM env_vars);

-- Migrate data from project_env_vars (project scope)
INSERT INTO environment_variables (
    scope_type, scope_id, var_name, var_value, value_type,
    is_exported, created_at, updated_at
)
SELECT
    'project' as scope_type,
    project_id as scope_id,
    var_name,
    var_value,
    'static' as value_type,
    1 as is_exported,
    created_at,
    updated_at
FROM project_env_vars pev
WHERE EXISTS (SELECT 1 FROM project_env_vars)
AND project_id IS NOT NULL;

-- Migrate data from nix_env_variables (nix_env scope)
INSERT INTO environment_variables (
    scope_type, scope_id, var_name, var_value, value_type,
    is_exported, created_at
)
SELECT
    'nix_env' as scope_type,
    environment_id as scope_id,
    var_name,
    var_value,
    'static' as value_type,
    1 as is_exported,
    created_at
FROM nix_env_variables
WHERE EXISTS (SELECT 1 FROM nix_env_variables)
AND environment_id IS NOT NULL;

-- Migrate data from compound_values (compound type)
INSERT INTO environment_variables (
    scope_type, scope_id, var_name, var_value, value_type, template, description
)
SELECT
    CASE
        WHEN project_id IS NOT NULL THEN 'project'
        ELSE 'global'
    END as scope_type,
    project_id as scope_id,
    value_name as var_name,
    value as var_value,
    'compound' as value_type,
    template,
    description
FROM compound_values
WHERE EXISTS (SELECT 1 FROM compound_values);

-- Create backward-compatible views
CREATE VIEW IF NOT EXISTS env_vars_view AS
SELECT
    id,
    var_name,
    var_value,
    is_exported,
    description,
    created_at,
    updated_at
FROM environment_variables
WHERE scope_type = 'global';

CREATE VIEW IF NOT EXISTS project_env_vars_view AS
SELECT
    id,
    scope_id as project_id,
    var_name,
    var_value,
    created_at,
    updated_at
FROM environment_variables
WHERE scope_type = 'project';

CREATE VIEW IF NOT EXISTS nix_env_variables_view AS
SELECT
    id,
    scope_id as environment_id,
    var_name,
    var_value,
    created_at
FROM environment_variables
WHERE scope_type = 'nix_env';

CREATE VIEW IF NOT EXISTS compound_values_view AS
SELECT
    id,
    scope_id as project_id,
    var_name as value_name,
    var_value as value,
    template,
    description
FROM environment_variables
WHERE value_type = 'compound';

-- Create comprehensive view for all environment variables with context
CREATE VIEW IF NOT EXISTS environment_variables_full_view AS
SELECT
    ev.id,
    ev.scope_type,
    ev.scope_id,
    ev.var_name,
    ev.var_value,
    ev.value_type,
    ev.template,
    ev.is_secret,
    ev.is_exported,
    ev.description,
    CASE
        WHEN ev.scope_type = 'global' THEN 'Global'
        WHEN ev.scope_type = 'project' THEN p.slug
        WHEN ev.scope_type = 'nix_env' THEN ne.env_name || ' (' || p2.slug || ')'
        ELSE 'Unknown'
    END as scope_display,
    ev.created_at,
    ev.updated_at
FROM environment_variables ev
LEFT JOIN projects p ON ev.scope_type = 'project' AND ev.scope_id = p.id
LEFT JOIN nix_environments ne ON ev.scope_type = 'nix_env' AND ev.scope_id = ne.id
LEFT JOIN projects p2 ON ne.project_id = p2.id;

-- Drop old tables
DROP TABLE IF EXISTS env_vars;
DROP TABLE IF EXISTS project_env_vars;
DROP TABLE IF EXISTS nix_env_variables;
DROP TABLE IF EXISTS compound_values;

-- Create trigger to auto-update updated_at
CREATE TRIGGER IF NOT EXISTS update_environment_variables_timestamp
AFTER UPDATE ON environment_variables
FOR EACH ROW
BEGIN
    UPDATE environment_variables SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- Create trigger to resolve compound values on insert/update
CREATE TRIGGER IF NOT EXISTS resolve_compound_values
AFTER INSERT ON environment_variables
FOR EACH ROW
WHEN NEW.value_type = 'compound' AND NEW.template IS NOT NULL
BEGIN
    UPDATE environment_variables
    SET var_value = (
        -- Simple template resolution: replace ${VAR} with values from same scope
        -- This is a basic implementation; more complex resolution can be done in application code
        SELECT COALESCE(
            (SELECT var_value FROM environment_variables ev2
             WHERE ev2.scope_type = NEW.scope_type
             AND ev2.scope_id = NEW.scope_id
             AND NEW.template LIKE '%${' || ev2.var_name || '}%'
             LIMIT 1),
            NEW.template
        )
    )
    WHERE id = NEW.id;
END;

COMMIT;

-- Verify migration
SELECT
    'environment_variables' as table_name,
    COUNT(*) as total_vars,
    COUNT(CASE WHEN scope_type = 'global' THEN 1 END) as global_vars,
    COUNT(CASE WHEN scope_type = 'project' THEN 1 END) as project_vars,
    COUNT(CASE WHEN scope_type = 'nix_env' THEN 1 END) as nix_env_vars,
    COUNT(CASE WHEN value_type = 'compound' THEN 1 END) as compound_vars,
    COUNT(CASE WHEN is_secret = 1 THEN 1 END) as secret_vars
FROM environment_variables;
