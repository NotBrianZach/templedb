-- Migration 046: Add Nix-First Project Support
-- Adds support for Nix flake validation, metadata tracking, and daemon/service projects

-- ============================================================================
-- Extend projects table with Nix-specific columns
-- ============================================================================

-- Add Nix project tracking
ALTER TABLE projects ADD COLUMN is_nix_project BOOLEAN DEFAULT 0 NOT NULL;
ALTER TABLE projects ADD COLUMN project_category TEXT DEFAULT 'package'
    CHECK(project_category IN ('package', 'service', 'desktop-app', 'nixos-module', 'home-module'));

-- Flake validation status
ALTER TABLE projects ADD COLUMN flake_validated_at TEXT;
ALTER TABLE projects ADD COLUMN flake_check_status TEXT
    CHECK(flake_check_status IN ('valid', 'invalid', 'unknown', NULL));
ALTER TABLE projects ADD COLUMN nix_build_status TEXT
    CHECK(nix_build_status IN ('builds', 'fails', 'untested', NULL));

-- Service-specific type
ALTER TABLE projects ADD COLUMN service_type TEXT
    CHECK(service_type IN ('oneshot', 'simple', 'forking', 'dbus', 'notify', NULL));

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_projects_nix ON projects(is_nix_project);
CREATE INDEX IF NOT EXISTS idx_projects_category ON projects(project_category);
CREATE INDEX IF NOT EXISTS idx_projects_build_status ON projects(nix_build_status);

-- ============================================================================
-- Nix Flake Metadata Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS nix_flake_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,

    -- Flake inputs (dependencies)
    flake_inputs TEXT,                    -- JSON: {"nixpkgs": {"url": "...", "follows": "..."}}
    nixpkgs_commit TEXT,                  -- Which nixpkgs commit/channel

    -- Flake outputs
    packages TEXT,                        -- JSON: ["default", "templedb", "templedb-tui"]
    apps TEXT,                            -- JSON: ["default", "templedb"]
    devShells TEXT,                       -- JSON: ["default"]
    nixosModules TEXT,                    -- JSON: ["default"]
    homeManagerModules TEXT,              -- JSON: ["default"]
    overlays TEXT,                        -- JSON: available overlays
    nix_outputs_raw TEXT,                 -- Full JSON from 'nix flake show --json'

    -- Build status
    last_build_check TEXT,
    last_build_succeeded BOOLEAN,
    build_error_log TEXT,

    -- Lock file tracking
    flake_lock_hash TEXT,                 -- Hash of flake.lock for change detection
    inputs_updated_at TEXT,

    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_flake_metadata_project ON nix_flake_metadata(project_id);
CREATE INDEX IF NOT EXISTS idx_flake_metadata_build_status ON nix_flake_metadata(last_build_succeeded);
CREATE INDEX IF NOT EXISTS idx_flake_metadata_updated ON nix_flake_metadata(updated_at);

-- ============================================================================
-- Nix Service Metadata Table (for daemons/services)
-- ============================================================================

CREATE TABLE IF NOT EXISTS nix_service_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,

    -- Service identification
    service_name TEXT NOT NULL,           -- e.g., 'templedb-git-server'
    service_description TEXT,

    -- NixOS module details
    module_path TEXT,                     -- 'services.templedb' or 'programs.templedb'
    config_options TEXT,                  -- JSON: list of available options

    -- Systemd configuration
    systemd_service_name TEXT,            -- e.g., 'templedb-git-server.service'
    systemd_wants TEXT,                   -- JSON: ["multi-user.target"]
    systemd_after TEXT,                   -- JSON: ["network.target", "postgresql.service"]
    systemd_requires TEXT,                -- JSON: hard dependencies

    -- Resource management
    needs_user BOOLEAN DEFAULT 0,
    user_name TEXT,
    needs_group BOOLEAN DEFAULT 0,
    group_name TEXT,

    -- State management
    needs_state_directory BOOLEAN DEFAULT 0,
    state_directory_path TEXT,            -- e.g., '/var/lib/templedb'
    needs_runtime_directory BOOLEAN DEFAULT 0,
    runtime_directory_path TEXT,          -- e.g., '/run/templedb'

    -- Network
    opens_ports TEXT,                     -- JSON: [9418, 8080]
    binds_to_address TEXT,                -- '0.0.0.0', '127.0.0.1', etc.

    -- Dependencies
    requires_services TEXT,               -- JSON: ["postgresql", "redis"]
    requires_databases TEXT,              -- JSON: ["postgresql"]

    -- Security
    dynamic_user BOOLEAN DEFAULT 0,
    private_tmp BOOLEAN DEFAULT 1,
    protect_system TEXT,                  -- 'strict', 'full', 'true'

    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_service_metadata_project ON nix_service_metadata(project_id);
CREATE INDEX IF NOT EXISTS idx_service_metadata_service_name ON nix_service_metadata(service_name);

-- ============================================================================
-- Nix Flake Validation History Table
-- ============================================================================

CREATE TABLE IF NOT EXISTS nix_flake_validation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    validation_timestamp TEXT DEFAULT (datetime('now')),
    validation_type TEXT NOT NULL        -- 'flake-check', 'build', 'build-dry-run'
        CHECK(validation_type IN ('flake-check', 'build', 'build-dry-run', 'module-parse')),

    succeeded BOOLEAN NOT NULL,
    error_message TEXT,
    error_log TEXT,

    -- What was tested
    nixpkgs_version TEXT,
    nix_version TEXT,

    -- Performance
    duration_seconds REAL,

    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_validation_history_project ON nix_flake_validation_history(project_id);
CREATE INDEX IF NOT EXISTS idx_validation_history_timestamp ON nix_flake_validation_history(validation_timestamp);
CREATE INDEX IF NOT EXISTS idx_validation_history_type ON nix_flake_validation_history(validation_type, succeeded);

-- ============================================================================
-- Views for convenient querying
-- ============================================================================

-- View: Nix-ready projects with metadata
CREATE VIEW IF NOT EXISTS nix_ready_projects AS
SELECT
    p.slug,
    p.name,
    p.project_category,
    p.is_nix_project,
    p.flake_check_status,
    p.nix_build_status,
    nfm.packages,
    nfm.nixosModules,
    nfm.homeManagerModules,
    nfm.last_build_succeeded,
    nfm.last_build_check
FROM projects p
LEFT JOIN nix_flake_metadata nfm ON p.id = nfm.project_id
WHERE p.is_nix_project = 1;

-- View: Service projects with metadata
CREATE VIEW IF NOT EXISTS nix_service_projects AS
SELECT
    p.slug,
    p.name,
    p.service_type,
    nsm.service_name,
    nsm.systemd_service_name,
    nsm.opens_ports,
    nsm.requires_services,
    nsm.requires_databases,
    nsm.module_path
FROM projects p
JOIN nix_service_metadata nsm ON p.id = nsm.project_id
WHERE p.project_category = 'service';

-- View: Project validation summary
CREATE VIEW IF NOT EXISTS project_validation_summary AS
SELECT
    p.slug,
    p.project_category,
    COUNT(nvh.id) as total_validations,
    SUM(CASE WHEN nvh.succeeded = 1 THEN 1 ELSE 0 END) as successful_validations,
    SUM(CASE WHEN nvh.succeeded = 0 THEN 1 ELSE 0 END) as failed_validations,
    MAX(nvh.validation_timestamp) as last_validation,
    AVG(nvh.duration_seconds) as avg_duration_seconds
FROM projects p
LEFT JOIN nix_flake_validation_history nvh ON p.id = nvh.project_id
WHERE p.is_nix_project = 1
GROUP BY p.id;

-- ============================================================================
-- Migration complete
-- ============================================================================

-- Migration complete
-- Note: Audit log entry omitted as this is a system-wide migration
