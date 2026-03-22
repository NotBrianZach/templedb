-- Migration: Add deployment configuration to projects
-- Date: 2026-02-23
-- Purpose: Store deployment orchestration config in project metadata

-- Add deployment_config column to projects table
ALTER TABLE projects ADD COLUMN deployment_config TEXT;

-- deployment_config stores JSON with this structure:
-- {
--   "groups": [
--     {
--       "name": "migrations",
--       "order": 1,
--       "file_patterns": ["migrations/*.sql"],
--       "pre_deploy": ["psql --version"],
--       "deploy_command": "psql $DATABASE_URL -f {file}",
--       "post_deploy": ["echo 'Done'"],
--       "required_env_vars": ["DATABASE_URL"]
--     }
--   ],
--   "health_check": {
--     "url": "https://api.example.com/health",
--     "expected_status": 200,
--     "timeout_seconds": 30
--   }
-- }
