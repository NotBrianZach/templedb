-- Migration: Add NixOS Managed Packages
-- Purpose: Track CLI tools and packages managed by TempleDB for NixOS system config
-- Date: 2026-03-21

-- Table to track packages that should be included in NixOS configuration
CREATE TABLE IF NOT EXISTS nixos_managed_packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    package_type TEXT NOT NULL CHECK(package_type IN ('system', 'home', 'user')),
    install_scope TEXT NOT NULL CHECK(install_scope IN ('system', 'user')),
    flake_uri TEXT,  -- URI to the flake (e.g., path:/home/user/project or github:org/repo)
    package_name TEXT,  -- Name of the package (e.g., 'bza')
    version TEXT,  -- Version tag/constraint
    enabled INTEGER DEFAULT 1,  -- Whether this package is currently enabled
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,  -- User notes about this package

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, install_scope)
);

CREATE INDEX idx_nixos_managed_packages_project ON nixos_managed_packages(project_id);
CREATE INDEX idx_nixos_managed_packages_enabled ON nixos_managed_packages(enabled);
CREATE INDEX idx_nixos_managed_packages_scope ON nixos_managed_packages(install_scope);

-- Trigger to update timestamp
CREATE TRIGGER update_nixos_managed_packages_timestamp
AFTER UPDATE ON nixos_managed_packages
BEGIN
    UPDATE nixos_managed_packages
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;

-- View to easily query managed packages with project info
CREATE VIEW nixos_managed_packages_view AS
SELECT
    nmp.id,
    nmp.project_id,
    p.slug as project_slug,
    p.name as project_name,
    p.repo_url as git_path,  -- Use repo_url, aliased as git_path for compatibility
    nmp.package_type,
    nmp.install_scope,
    nmp.flake_uri,
    nmp.package_name,
    nmp.version,
    nmp.enabled,
    nmp.added_at,
    nmp.updated_at,
    nmp.notes
FROM nixos_managed_packages nmp
JOIN projects p ON nmp.project_id = p.id;

-- Add system config keys for NixOS integration
INSERT OR IGNORE INTO system_config (key, value, description)
VALUES
    ('nixos.auto_rebuild', 'false', 'Automatically rebuild system when adding/removing packages'),
    ('nixos.default_scope', 'user', 'Default installation scope (system or user)'),
    ('nixos.config_path', '', 'Path to NixOS configuration directory (empty = auto-detect)');
