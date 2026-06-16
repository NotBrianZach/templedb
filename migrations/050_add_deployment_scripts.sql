-- Migration 050: Deployment Scripts System (CONSOLIDATED)
--
-- This migration consolidates:
--   - 041_add_deployment_plugins.sql (base table as 'deployment_plugins')
--   - 043_rename_plugins_to_deploy_scripts.sql (rename to final name)
--   - 062_add_deployment_docs.sql (add documentation column)
--
-- Date: 2026-04-07 (Consolidated)
-- Original dates: 2026-03-22, 2026-03-23, 2026-04-05
--
-- Purpose: Allow projects to register custom deployment scripts that run instead of
-- or alongside standard TempleDB deployment workflows. Scripts can manage services,
-- run migrations, coordinate complex deployments, or integrate with external platforms.

CREATE TABLE IF NOT EXISTS deployment_scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug TEXT NOT NULL,
    script_path TEXT NOT NULL,
    description TEXT,
    documentation TEXT,  -- Markdown documentation for deployment process (added in 062)
    enabled BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_slug)
);

-- Indexes for efficient lookups
CREATE INDEX IF NOT EXISTS idx_deployment_scripts_project ON deployment_scripts(project_slug);
CREATE INDEX IF NOT EXISTS idx_deployment_scripts_enabled ON deployment_scripts(enabled);

-- Index for searching projects with documentation
CREATE INDEX IF NOT EXISTS idx_deployment_scripts_has_docs
    ON deployment_scripts(project_slug) WHERE documentation IS NOT NULL;

-- Trigger to update timestamp on changes
CREATE TRIGGER IF NOT EXISTS update_deployment_scripts_timestamp
AFTER UPDATE ON deployment_scripts
BEGIN
    UPDATE deployment_scripts SET updated_at = datetime('now') WHERE id = NEW.id;
END;

-- ============================================================================
-- CONSOLIDATION NOTES
-- ============================================================================
-- This migration replaces three separate migrations:
--
-- 1. Migration 041 (2026-03-22): Created deployment_plugins table
--    - Base schema with project_slug, script_path, description, enabled
--
-- 2. Migration 043 (2026-03-23): Renamed deployment_plugins → deployment_scripts
--    - Simple ALTER TABLE RENAME (incorporated by using final name from start)
--
-- 3. Migration 062 (2026-04-05): Added documentation column
--    - ALTER TABLE ADD COLUMN documentation TEXT
--    - Added idx_deployment_scripts_has_docs index
--
-- By consolidating, new databases get the complete schema in one migration.
-- The final table name (deployment_scripts) is used from the start.
--
-- Example documentation format (markdown):
--
-- # Project Deployment Guide
--
-- ## Quick Start
-- ```bash
-- ./templedb deploy run myproject --target production
-- ```
--
-- ## Management Commands
-- - Status: `./templedb deploy exec myproject './deploy.sh status'`
-- - Stop: `./templedb deploy exec myproject './deploy.sh stop'`
-- - Restart: `./templedb deploy exec myproject './deploy.sh restart'`
--
-- ## Environment Variables
-- Required variables and how to set them using TempleDB.
--
-- ## Troubleshooting
-- Common issues and solutions specific to this project.
