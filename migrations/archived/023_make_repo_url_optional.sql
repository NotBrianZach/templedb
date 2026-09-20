-- Migration: Make repo_url optional (support CWD-based project discovery)
-- Date: 2026-03-03
-- Description: With .templedb markers, projects no longer need to store absolute paths

-- The repo_url field is kept for backward compatibility but is now optional
-- Projects with .templedb markers use CWD-based discovery instead

-- Note: SQLite doesn't support ALTER COLUMN directly, so we document the change
-- New projects created after this migration will treat repo_url as optional
-- Existing projects continue to work with their stored repo_url values

-- Add comment to projects table documentation
-- (This is a no-op migration - just documents the behavioral change)

-- Future: Consider adding a 'discovery_mode' field: 'cwd' | 'absolute' | 'registry'
-- For now, we support both modes transparently
