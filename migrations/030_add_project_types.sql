-- Add project_type field to projects table
-- This enables different handling for nixos-config, services, etc.

-- Add project_type column (default to 'regular' for existing projects)
ALTER TABLE projects ADD COLUMN project_type TEXT DEFAULT 'regular' CHECK(project_type IN ('regular', 'nixos-config', 'service', 'library'));

-- Create index for faster lookups by type
CREATE INDEX IF NOT EXISTS idx_projects_type ON projects(project_type);

-- Add comment documenting project types
-- 'regular': Standard development projects (default)
-- 'nixos-config': NixOS system configuration projects (special deployment handling)
-- 'service': Long-running service projects
-- 'library': Shared library projects
