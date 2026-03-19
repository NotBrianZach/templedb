-- Add NixOps4 integration tables for declarative infrastructure deployment
-- Replaces simple deployment scheme with full-featured orchestration

-- ============================================================================
-- NixOps4 Networks
-- ============================================================================
-- A network is a logical grouping of machines managed together
CREATE TABLE IF NOT EXISTS nixops4_networks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Network identification
    network_name TEXT NOT NULL,           -- e.g., 'production', 'staging', 'dev-cluster'
    network_uuid TEXT NOT NULL UNIQUE,    -- UUID for nixops4 state tracking

    -- Configuration
    config_file_path TEXT NOT NULL,       -- Path to network.nix or flake.nix
    flake_uri TEXT,                       -- Flake URI if using flakes (e.g., 'github:org/repo#network')
    nix_options TEXT,                     -- JSON: extra nix options (--option key value)

    -- State
    state_file_path TEXT,                 -- Path to nixops4 state file
    is_active BOOLEAN DEFAULT 1,          -- Currently active network

    -- Metadata
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT,

    UNIQUE(project_id, network_name)
);

CREATE INDEX idx_nixops4_networks_project ON nixops4_networks(project_id);
CREATE INDEX idx_nixops4_networks_active ON nixops4_networks(project_id, is_active) WHERE is_active = 1;


-- ============================================================================
-- NixOps4 Machines
-- ============================================================================
-- Individual machines/systems in a network
CREATE TABLE IF NOT EXISTS nixops4_machines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network_id INTEGER NOT NULL REFERENCES nixops4_networks(id) ON DELETE CASCADE,

    -- Machine identification
    machine_name TEXT NOT NULL,           -- Machine name in nixops4 (e.g., 'web1', 'db1')
    machine_uuid TEXT NOT NULL UNIQUE,    -- UUID for machine state

    -- Target information
    target_host TEXT,                     -- Hostname or IP address
    target_user TEXT DEFAULT 'root',      -- SSH user for deployment
    target_port INTEGER DEFAULT 22,       -- SSH port

    -- Machine configuration
    system_type TEXT,                     -- 'nixos', 'linux', 'darwin'
    target_env TEXT,                      -- 'libvirtd', 'ec2', 'gce', 'azure', 'digitalocean', 'none' (existing machine)
    machine_config TEXT,                  -- JSON: machine-specific configuration

    -- Current state
    nixos_version TEXT,                   -- Current NixOS version
    system_profile TEXT,                  -- Current system profile path
    boot_id TEXT,                         -- Boot ID (changes on reboot)

    -- Status
    deployment_status TEXT DEFAULT 'new', -- 'new', 'deploying', 'deployed', 'failed', 'obsolete'
    last_deployed_at TIMESTAMP,
    last_health_check_at TIMESTAMP,
    health_status TEXT,                   -- 'healthy', 'degraded', 'unhealthy', 'unknown'

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(network_id, machine_name)
);

CREATE INDEX idx_nixops4_machines_network ON nixops4_machines(network_id);
CREATE INDEX idx_nixops4_machines_status ON nixops4_machines(deployment_status);


-- ============================================================================
-- NixOps4 Deployments
-- ============================================================================
-- History of deployment operations
CREATE TABLE IF NOT EXISTS nixops4_deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network_id INTEGER NOT NULL REFERENCES nixops4_networks(id) ON DELETE CASCADE,

    -- Deployment identification
    deployment_uuid TEXT NOT NULL UNIQUE,

    -- Operation type
    operation TEXT NOT NULL,              -- 'deploy', 'destroy', 'reboot', 'rebuild', 'modify'
    target_machines TEXT,                 -- JSON array: specific machines deployed (null = all)

    -- Configuration
    config_revision TEXT,                 -- Git commit hash or flake revision
    nixpkgs_revision TEXT,                -- Nixpkgs revision used

    -- Deployment options
    deploy_options TEXT,                  -- JSON: flags like --build-only, --dry-run, --force-reboot

    -- Execution
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    duration_seconds INTEGER,

    -- Status
    status TEXT DEFAULT 'running',        -- 'running', 'success', 'partial', 'failed', 'cancelled'
    exit_code INTEGER,

    -- Output
    stdout_log TEXT,                      -- Captured stdout
    stderr_log TEXT,                      -- Captured stderr

    -- Changes made
    changes_summary TEXT,                 -- JSON: summary of what changed per machine
    services_restarted TEXT,              -- JSON: services that were restarted

    -- Metadata
    triggered_by TEXT,                    -- User or automation source
    triggered_reason TEXT,                -- Why was this deployment triggered

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_nixops4_deployments_network ON nixops4_deployments(network_id, started_at DESC);
CREATE INDEX idx_nixops4_deployments_status ON nixops4_deployments(status);


-- ============================================================================
-- NixOps4 Machine Deployments
-- ============================================================================
-- Per-machine deployment status (many-to-many between deployments and machines)
CREATE TABLE IF NOT EXISTS nixops4_machine_deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id INTEGER NOT NULL REFERENCES nixops4_deployments(id) ON DELETE CASCADE,
    machine_id INTEGER NOT NULL REFERENCES nixops4_machines(id) ON DELETE CASCADE,

    -- Build information
    build_started_at TIMESTAMP,
    build_completed_at TIMESTAMP,
    build_duration_seconds INTEGER,

    -- Deployment to machine
    deploy_started_at TIMESTAMP,
    deploy_completed_at TIMESTAMP,
    deploy_duration_seconds INTEGER,

    -- Status
    status TEXT DEFAULT 'pending',        -- 'pending', 'building', 'deploying', 'success', 'failed', 'skipped'
    error_message TEXT,

    -- Results
    old_system_profile TEXT,              -- Previous system profile
    new_system_profile TEXT,              -- New system profile
    units_restarted TEXT,                 -- JSON array: systemd units restarted

    -- Activation
    activation_script_ran BOOLEAN DEFAULT 0,
    activation_warnings TEXT,             -- JSON array: warnings during activation

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(deployment_id, machine_id)
);

CREATE INDEX idx_nixops4_machine_deployments ON nixops4_machine_deployments(deployment_id);
CREATE INDEX idx_nixops4_machine_deployments_machine ON nixops4_machine_deployments(machine_id, deploy_completed_at DESC);


-- ============================================================================
-- NixOps4 Resources
-- ============================================================================
-- Managed resources (DNS records, storage volumes, keys, etc.)
CREATE TABLE IF NOT EXISTS nixops4_resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network_id INTEGER NOT NULL REFERENCES nixops4_networks(id) ON DELETE CASCADE,
    machine_id INTEGER REFERENCES nixops4_machines(id) ON DELETE CASCADE,  -- null for network-level resources

    -- Resource identification
    resource_name TEXT NOT NULL,
    resource_type TEXT NOT NULL,          -- 'dns-record', 'storage-volume', 'ssh-key', 'vpc', 'security-group', etc.
    resource_uuid TEXT NOT NULL UNIQUE,

    -- Resource details
    provider TEXT,                        -- 'route53', 'cloudflare', 'gcs', 'aws', 'azure', etc.
    provider_resource_id TEXT,            -- Provider-specific resource ID
    resource_config TEXT,                 -- JSON: resource configuration

    -- State
    status TEXT DEFAULT 'planned',        -- 'planned', 'creating', 'created', 'updating', 'deleting', 'deleted', 'failed'

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(network_id, resource_name, resource_type)
);

CREATE INDEX idx_nixops4_resources_network ON nixops4_resources(network_id);
CREATE INDEX idx_nixops4_resources_machine ON nixops4_resources(machine_id);
CREATE INDEX idx_nixops4_resources_type ON nixops4_resources(resource_type);


-- ============================================================================
-- NixOps4 Secrets
-- ============================================================================
-- Secrets deployed to machines (managed separately from templedb secrets)
CREATE TABLE IF NOT EXISTS nixops4_secrets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network_id INTEGER NOT NULL REFERENCES nixops4_networks(id) ON DELETE CASCADE,
    machine_id INTEGER REFERENCES nixops4_machines(id) ON DELETE SET NULL,  -- null = shared across network

    -- Secret identification
    secret_name TEXT NOT NULL,
    secret_path TEXT NOT NULL,            -- Destination path on machine

    -- Secret management
    secret_source TEXT,                   -- 'file', 'pass', 'age', 'sops', 'vault'
    secret_source_path TEXT,              -- Path to secret source

    -- Permissions
    owner TEXT DEFAULT 'root',
    owner_group TEXT DEFAULT 'root',
    permissions TEXT DEFAULT '0600',

    -- Deployment tracking
    last_deployed_at TIMESTAMP,
    last_deployed_hash TEXT,              -- Hash of deployed content (for change detection)

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(network_id, machine_id, secret_name)
);

CREATE INDEX idx_nixops4_secrets_network ON nixops4_secrets(network_id);
CREATE INDEX idx_nixops4_secrets_machine ON nixops4_secrets(machine_id);


-- ============================================================================
-- NixOps4 Network Info
-- ============================================================================
-- Network topology and connectivity information
CREATE TABLE IF NOT EXISTS nixops4_network_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network_id INTEGER NOT NULL REFERENCES nixops4_networks(id) ON DELETE CASCADE,

    -- Topology
    network_topology TEXT,                -- JSON: graph of machine connectivity

    -- Collected at
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Network details
    private_network_cidr TEXT,            -- CIDR for private network
    vpn_type TEXT,                        -- 'wireguard', 'tinc', 'none'
    vpn_config TEXT,                      -- JSON: VPN configuration

    -- DNS
    internal_dns_zone TEXT,               -- Internal DNS zone name
    external_dns_zone TEXT                -- External DNS zone name
);

CREATE INDEX idx_nixops4_network_info ON nixops4_network_info(network_id, collected_at DESC);


-- ============================================================================
-- Views for easier querying
-- ============================================================================

-- Active networks with machine counts
CREATE VIEW IF NOT EXISTS nixops4_network_summary AS
SELECT
    n.id,
    n.project_id,
    n.network_name,
    n.network_uuid,
    n.is_active,
    p.slug AS project_slug,
    p.name AS project_name,
    COUNT(DISTINCT m.id) AS machine_count,
    COUNT(DISTINCT CASE WHEN m.deployment_status = 'deployed' THEN m.id END) AS deployed_machines,
    COUNT(DISTINCT r.id) AS resource_count,
    MAX(d.started_at) AS last_deployment_at,
    n.created_at,
    n.updated_at
FROM nixops4_networks n
JOIN projects p ON n.project_id = p.id
LEFT JOIN nixops4_machines m ON n.id = m.network_id
LEFT JOIN nixops4_resources r ON n.id = r.network_id
LEFT JOIN nixops4_deployments d ON n.id = d.network_id
WHERE n.is_active = 1
GROUP BY n.id, n.project_id, n.network_name, n.network_uuid, n.is_active,
         p.slug, p.name, n.created_at, n.updated_at;


-- Recent deployments with status
CREATE VIEW IF NOT EXISTS nixops4_deployment_history AS
SELECT
    d.id,
    d.deployment_uuid,
    d.network_id,
    n.network_name,
    n.project_id,
    p.slug AS project_slug,
    d.operation,
    d.target_machines,
    d.config_revision,
    d.status,
    d.started_at,
    d.completed_at,
    d.duration_seconds,
    d.triggered_by,
    COUNT(md.id) AS total_machines,
    COUNT(CASE WHEN md.status = 'success' THEN 1 END) AS successful_machines,
    COUNT(CASE WHEN md.status = 'failed' THEN 1 END) AS failed_machines
FROM nixops4_deployments d
JOIN nixops4_networks n ON d.network_id = n.id
JOIN projects p ON n.project_id = p.id
LEFT JOIN nixops4_machine_deployments md ON d.id = md.deployment_id
GROUP BY d.id, d.deployment_uuid, d.network_id, n.network_name, n.project_id,
         p.slug, d.operation, d.target_machines, d.config_revision, d.status,
         d.started_at, d.completed_at, d.duration_seconds, d.triggered_by
ORDER BY d.started_at DESC;


-- Machine health summary
CREATE VIEW IF NOT EXISTS nixops4_machine_health AS
SELECT
    m.id,
    m.machine_name,
    m.network_id,
    n.network_name,
    n.project_id,
    p.slug AS project_slug,
    m.target_host,
    m.deployment_status,
    m.health_status,
    m.last_deployed_at,
    m.last_health_check_at,
    m.nixos_version,
    -- Latest deployment info
    (SELECT started_at
     FROM nixops4_machine_deployments md
     JOIN nixops4_deployments d ON md.deployment_id = d.id
     WHERE md.machine_id = m.id AND md.status = 'success'
     ORDER BY md.deploy_completed_at DESC LIMIT 1) AS last_successful_deployment,
    (SELECT COUNT(*)
     FROM nixops4_machine_deployments md
     WHERE md.machine_id = m.id AND md.status = 'failed') AS failed_deployment_count
FROM nixops4_machines m
JOIN nixops4_networks n ON m.network_id = n.id
JOIN projects p ON n.project_id = p.id
ORDER BY n.network_name, m.machine_name;


-- ============================================================================
-- Triggers
-- ============================================================================

-- Update network updated_at on machine changes
CREATE TRIGGER IF NOT EXISTS nixops4_update_network_timestamp
AFTER UPDATE ON nixops4_machines
BEGIN
    UPDATE nixops4_networks
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.network_id;
END;

-- Update machine updated_at
CREATE TRIGGER IF NOT EXISTS nixops4_update_machine_timestamp
AFTER UPDATE ON nixops4_machines
FOR EACH ROW
BEGIN
    UPDATE nixops4_machines
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;

-- Calculate deployment duration on completion
CREATE TRIGGER IF NOT EXISTS nixops4_calculate_deployment_duration
AFTER UPDATE OF completed_at ON nixops4_deployments
WHEN NEW.completed_at IS NOT NULL AND OLD.completed_at IS NULL
BEGIN
    UPDATE nixops4_deployments
    SET duration_seconds = CAST((julianday(NEW.completed_at) - julianday(NEW.started_at)) * 86400 AS INTEGER)
    WHERE id = NEW.id;
END;

-- Calculate machine deployment durations
CREATE TRIGGER IF NOT EXISTS nixops4_calculate_machine_deploy_duration
AFTER UPDATE OF deploy_completed_at ON nixops4_machine_deployments
WHEN NEW.deploy_completed_at IS NOT NULL AND OLD.deploy_completed_at IS NULL
BEGIN
    UPDATE nixops4_machine_deployments
    SET deploy_duration_seconds = CAST((julianday(NEW.deploy_completed_at) - julianday(NEW.deploy_started_at)) * 86400 AS INTEGER)
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS nixops4_calculate_machine_build_duration
AFTER UPDATE OF build_completed_at ON nixops4_machine_deployments
WHEN NEW.build_completed_at IS NOT NULL AND OLD.build_completed_at IS NULL
BEGIN
    UPDATE nixops4_machine_deployments
    SET build_duration_seconds = CAST((julianday(NEW.build_completed_at) - julianday(NEW.build_started_at)) * 86400 AS INTEGER)
    WHERE id = NEW.id;
END;


-- ============================================================================
-- Migration notes
-- ============================================================================
-- This migration adds comprehensive nixops4 support to TempleDB.
--
-- Key features:
-- - Network-based deployment organization
-- - Per-machine deployment tracking
-- - Resource management (DNS, storage, keys)
-- - Deployment history with per-machine detail
-- - Health monitoring and status tracking
-- - Secret management integration
--
-- To use nixops4 deployments:
-- 1. Create a network: ./templedb nixops4 network create <project> <name>
-- 2. Define machines: ./templedb nixops4 machine add <network> <machine-name>
-- 3. Deploy: ./templedb nixops4 deploy <network>
-- 4. Monitor: ./templedb nixops4 status <network>
--
-- The old deployment_targets and file_deployments tables are not removed
-- to maintain backward compatibility, but nixops4 provides a more robust
-- deployment solution for NixOS infrastructure.
