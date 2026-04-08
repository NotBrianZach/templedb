-- Add deployment documentation field to deployment_scripts
-- Allows projects to store detailed deployment instructions visible via CLI

ALTER TABLE deployment_scripts ADD COLUMN documentation TEXT;

-- Create index for searching docs
CREATE INDEX IF NOT EXISTS idx_deployment_scripts_has_docs
ON deployment_scripts(project_slug) WHERE documentation IS NOT NULL;

-- Example documentation format (markdown):
--
-- # BZA Deployment
--
-- ## Quick Start
-- ```bash
-- ./templedb deploy run bza --target dev
-- ```
--
-- ## Management Commands
-- - Status: `./templedb deploy exec bza './deploy.sh status'`
-- - Stop: `./templedb deploy exec bza './deploy.sh stop'`
-- - Restart: `./templedb deploy exec bza './deploy.sh restart'`
--
-- ## Environment Variables
-- - OPENROUTER_API_KEY - Set via `./templedb secret set bza OPENROUTER_API_KEY`
