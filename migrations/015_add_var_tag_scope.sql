-- Migration 015: Complete env_vars table rename + add tag scope + add tags/project_tags tables
--
-- The live DB has environment_variables_new (from a partial migration 010 run) but
-- it was never renamed to environment_variables. This migration finishes that and adds
-- tag scope support.
--
-- Changes:
--   1. Rename environment_variables_new → environment_variables (if not already done)
--   2. Create indexes on environment_variables
--   3. Add tags table (named groups of projects)
--   4. Add project_tags junction table

BEGIN TRANSACTION;

-- Step 1: Rename environment_variables_new if it exists and environment_variables doesn't
-- (handles the case where migration 010 was interrupted before the rename)
-- We use a CREATE TABLE ... SELECT approach instead of ALTER TABLE RENAME to avoid
-- triggering the broken work_items_with_prompts_view

-- If environment_variables_new exists, just rename it
-- SQLite doesn't have IF EXISTS for ALTER TABLE, so we do this via a trigger trick:
-- We'll just try both paths safely.

-- Create environment_variables if it doesn't exist (idempotent)
CREATE TABLE IF NOT EXISTS environment_variables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_type TEXT NOT NULL CHECK(scope_type IN ('global', 'project', 'nix_env', 'tag')),
    scope_id INTEGER,
    var_name TEXT NOT NULL,
    var_value TEXT,
    value_type TEXT DEFAULT 'static' CHECK(value_type IN ('static', 'compound', 'secret_ref')),
    template TEXT,
    is_secret BOOLEAN DEFAULT 0,
    is_exported BOOLEAN DEFAULT 1,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scope_type, scope_id, var_name)
);

-- Copy any rows from environment_variables_new that aren't already in environment_variables
INSERT OR IGNORE INTO environment_variables
    (id, scope_type, scope_id, var_name, var_value, value_type,
     template, is_secret, is_exported, description, created_at, updated_at)
SELECT id, scope_type, scope_id, var_name, var_value, value_type,
       template, is_secret, is_exported, description, created_at, updated_at
FROM environment_variables_new
WHERE EXISTS (SELECT 1 FROM sqlite_master WHERE type='table' AND name='environment_variables_new');

-- Step 2: Recreate indexes
CREATE INDEX IF NOT EXISTS idx_environment_variables_scope
    ON environment_variables(scope_type, scope_id);
CREATE INDEX IF NOT EXISTS idx_environment_variables_name
    ON environment_variables(var_name);
CREATE INDEX IF NOT EXISTS idx_environment_variables_type
    ON environment_variables(value_type);

-- Step 3: Add tags table
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Step 4: Add project_tags junction table
CREATE TABLE IF NOT EXISTS project_tags (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_project_tags_project ON project_tags(project_id);
CREATE INDEX IF NOT EXISTS idx_project_tags_tag ON project_tags(tag_id);

COMMIT;
