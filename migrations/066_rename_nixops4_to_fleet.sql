-- Rename nixops4_* tables/views/triggers/indexes to fleet_*
-- Part of the transition from nixops4 dependency to TempleDB-native fleet deployment

-- ============================================================================
-- Step 1: Drop views (must drop before renaming tables they reference)
-- ============================================================================
DROP VIEW IF EXISTS nixops4_deployment_history;
DROP VIEW IF EXISTS nixops4_machine_health;
DROP VIEW IF EXISTS nixops4_network_summary;
DROP VIEW IF EXISTS nixops4_local_machines;
DROP VIEW IF EXISTS nixops4_port_usage;
DROP VIEW IF EXISTS nixops4_profile_summary;
DROP VIEW IF EXISTS nixops4_service_status;

-- ============================================================================
-- Step 2: Drop triggers (must drop before renaming tables)
-- ============================================================================
DROP TRIGGER IF EXISTS nixops4_calculate_deployment_duration;
DROP TRIGGER IF EXISTS nixops4_calculate_machine_build_duration;
DROP TRIGGER IF EXISTS nixops4_calculate_machine_deploy_duration;
DROP TRIGGER IF EXISTS nixops4_local_services_allocate_port;
DROP TRIGGER IF EXISTS nixops4_local_services_updated;
DROP TRIGGER IF EXISTS nixops4_machines_set_local_flag;
DROP TRIGGER IF EXISTS nixops4_network_profiles_updated;
DROP TRIGGER IF EXISTS nixops4_update_machine_timestamp;
DROP TRIGGER IF EXISTS nixops4_update_network_timestamp;

-- ============================================================================
-- Step 3: Drop old indexes (new ones created with renamed tables)
-- ============================================================================
DROP INDEX IF EXISTS idx_nixops4_deployment_environments_machine;
DROP INDEX IF EXISTS idx_nixops4_deployments_network;
DROP INDEX IF EXISTS idx_nixops4_deployments_status;
DROP INDEX IF EXISTS idx_nixops4_local_services_network_profile;
DROP INDEX IF EXISTS idx_nixops4_local_services_status;
DROP INDEX IF EXISTS idx_nixops4_machine_deployments;
DROP INDEX IF EXISTS idx_nixops4_machine_deployments_machine;
DROP INDEX IF EXISTS idx_nixops4_machines_is_local;
DROP INDEX IF EXISTS idx_nixops4_machines_network;
DROP INDEX IF EXISTS idx_nixops4_machines_status;
DROP INDEX IF EXISTS idx_nixops4_network_info;
DROP INDEX IF EXISTS idx_nixops4_network_profiles_default;
DROP INDEX IF EXISTS idx_nixops4_network_profiles_network;
DROP INDEX IF EXISTS idx_nixops4_networks_active;
DROP INDEX IF EXISTS idx_nixops4_networks_project;
DROP INDEX IF EXISTS idx_nixops4_port_allocations_active;
DROP INDEX IF EXISTS idx_nixops4_resources_machine;
DROP INDEX IF EXISTS idx_nixops4_resources_network;
DROP INDEX IF EXISTS idx_nixops4_resources_type;

-- ============================================================================
-- Step 4: Rename tables
-- ============================================================================
ALTER TABLE nixops4_networks RENAME TO fleet_networks;
ALTER TABLE nixops4_machines RENAME TO fleet_machines;
ALTER TABLE nixops4_deployments RENAME TO fleet_deployments;
ALTER TABLE nixops4_machine_deployments RENAME TO fleet_machine_deployments;
ALTER TABLE nixops4_resources RENAME TO fleet_resources;
ALTER TABLE nixops4_network_info RENAME TO fleet_network_info;
ALTER TABLE nixops4_deployment_environments RENAME TO fleet_deployment_environments;
ALTER TABLE nixops4_local_services RENAME TO fleet_local_services;
ALTER TABLE nixops4_network_profiles RENAME TO fleet_network_profiles;
ALTER TABLE nixops4_port_allocations RENAME TO fleet_port_allocations;

-- Note: nixops4_secrets table may not exist in all installations
-- (was in migration 036 but not always applied)

-- ============================================================================
-- Step 5: Recreate indexes with new names
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_fleet_networks_project ON fleet_networks(project_id);
CREATE INDEX IF NOT EXISTS idx_fleet_networks_active ON fleet_networks(project_id, is_active) WHERE is_active = 1;
CREATE INDEX IF NOT EXISTS idx_fleet_machines_network ON fleet_machines(network_id);
CREATE INDEX IF NOT EXISTS idx_fleet_machines_status ON fleet_machines(deployment_status);
CREATE INDEX IF NOT EXISTS idx_fleet_machines_is_local ON fleet_machines(is_local) WHERE is_local = TRUE;
CREATE INDEX IF NOT EXISTS idx_fleet_deployments_network ON fleet_deployments(network_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_fleet_deployments_status ON fleet_deployments(status);
CREATE INDEX IF NOT EXISTS idx_fleet_machine_deployments ON fleet_machine_deployments(deployment_id);
CREATE INDEX IF NOT EXISTS idx_fleet_machine_deployments_machine ON fleet_machine_deployments(machine_id, deploy_completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_fleet_resources_network ON fleet_resources(network_id);
CREATE INDEX IF NOT EXISTS idx_fleet_resources_machine ON fleet_resources(machine_id);
CREATE INDEX IF NOT EXISTS idx_fleet_resources_type ON fleet_resources(resource_type);
CREATE INDEX IF NOT EXISTS idx_fleet_network_info ON fleet_network_info(network_id, collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_fleet_deployment_environments_machine ON fleet_deployment_environments(machine_id);
CREATE INDEX IF NOT EXISTS idx_fleet_local_services_network_profile ON fleet_local_services(network_id, profile_name);
CREATE INDEX IF NOT EXISTS idx_fleet_local_services_status ON fleet_local_services(status);
CREATE INDEX IF NOT EXISTS idx_fleet_network_profiles_network ON fleet_network_profiles(network_id);
CREATE INDEX IF NOT EXISTS idx_fleet_network_profiles_default ON fleet_network_profiles(network_id, is_default) WHERE is_default = TRUE;
CREATE INDEX IF NOT EXISTS idx_fleet_port_allocations_active ON fleet_port_allocations(port_number) WHERE is_active = TRUE;

-- ============================================================================
-- Step 6: Recreate triggers with new names
-- ============================================================================

CREATE TRIGGER IF NOT EXISTS fleet_update_network_timestamp
AFTER UPDATE ON fleet_machines
BEGIN
    UPDATE fleet_networks
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.network_id;
END;

CREATE TRIGGER IF NOT EXISTS fleet_update_machine_timestamp
AFTER UPDATE ON fleet_machines
FOR EACH ROW
BEGIN
    UPDATE fleet_machines
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS fleet_calculate_deployment_duration
AFTER UPDATE OF completed_at ON fleet_deployments
WHEN NEW.completed_at IS NOT NULL AND OLD.completed_at IS NULL
BEGIN
    UPDATE fleet_deployments
    SET duration_seconds = CAST((julianday(NEW.completed_at) - julianday(NEW.started_at)) * 86400 AS INTEGER)
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS fleet_calculate_machine_deploy_duration
AFTER UPDATE OF deploy_completed_at ON fleet_machine_deployments
WHEN NEW.deploy_completed_at IS NOT NULL AND OLD.deploy_completed_at IS NULL
BEGIN
    UPDATE fleet_machine_deployments
    SET deploy_duration_seconds = CAST((julianday(NEW.deploy_completed_at) - julianday(NEW.deploy_started_at)) * 86400 AS INTEGER)
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS fleet_calculate_machine_build_duration
AFTER UPDATE OF build_completed_at ON fleet_machine_deployments
WHEN NEW.build_completed_at IS NOT NULL AND OLD.build_completed_at IS NULL
BEGIN
    UPDATE fleet_machine_deployments
    SET build_duration_seconds = CAST((julianday(NEW.build_completed_at) - julianday(NEW.build_started_at)) * 86400 AS INTEGER)
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS fleet_machines_set_local_flag
AFTER INSERT ON fleet_machines
FOR EACH ROW
WHEN NEW.system_type = 'localhost'
BEGIN
    UPDATE fleet_machines
    SET is_local = TRUE
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS fleet_local_services_allocate_port
AFTER INSERT ON fleet_local_services
FOR EACH ROW
WHEN NEW.port_mapping IS NOT NULL
BEGIN
    SELECT 1;
END;

CREATE TRIGGER IF NOT EXISTS fleet_local_services_updated
AFTER UPDATE ON fleet_local_services
FOR EACH ROW
BEGIN
    UPDATE fleet_local_services
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS fleet_network_profiles_updated
AFTER UPDATE ON fleet_network_profiles
FOR EACH ROW
BEGIN
    UPDATE fleet_network_profiles
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;

-- ============================================================================
-- Step 7: Recreate views with new names
-- ============================================================================

CREATE VIEW IF NOT EXISTS fleet_network_summary AS
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
FROM fleet_networks n
JOIN projects p ON n.project_id = p.id
LEFT JOIN fleet_machines m ON n.id = m.network_id
LEFT JOIN fleet_resources r ON n.id = r.network_id
LEFT JOIN fleet_deployments d ON n.id = d.network_id
WHERE n.is_active = 1
GROUP BY n.id, n.project_id, n.network_name, n.network_uuid, n.is_active,
         p.slug, p.name, n.created_at, n.updated_at;

CREATE VIEW IF NOT EXISTS fleet_deployment_history AS
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
FROM fleet_deployments d
JOIN fleet_networks n ON d.network_id = n.id
JOIN projects p ON n.project_id = p.id
LEFT JOIN fleet_machine_deployments md ON d.id = md.deployment_id
GROUP BY d.id, d.deployment_uuid, d.network_id, n.network_name, n.project_id,
         p.slug, d.operation, d.target_machines, d.config_revision, d.status,
         d.started_at, d.completed_at, d.duration_seconds, d.triggered_by
ORDER BY d.started_at DESC;

CREATE VIEW IF NOT EXISTS fleet_machine_health AS
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
    (SELECT started_at
     FROM fleet_machine_deployments md
     JOIN fleet_deployments d ON md.deployment_id = d.id
     WHERE md.machine_id = m.id AND md.status = 'success'
     ORDER BY md.deploy_completed_at DESC LIMIT 1) AS last_successful_deployment,
    (SELECT COUNT(*)
     FROM fleet_machine_deployments md
     WHERE md.machine_id = m.id AND md.status = 'failed') AS failed_deployment_count
FROM fleet_machines m
JOIN fleet_networks n ON m.network_id = n.id
JOIN projects p ON n.project_id = p.id
ORDER BY n.network_name, m.machine_name;

CREATE VIEW IF NOT EXISTS fleet_local_machines AS
SELECT
    m.id,
    m.machine_name,
    m.target_host,
    m.local_port_base,
    m.local_fhs_env,
    m.local_working_dir,
    m.deployment_status,
    m.health_status,
    n.network_name,
    n.project_id,
    p.slug as project_slug
FROM fleet_machines m
JOIN fleet_networks n ON m.network_id = n.id
JOIN projects p ON n.project_id = p.id
WHERE m.is_local = TRUE;

CREATE VIEW IF NOT EXISTS fleet_port_usage AS
SELECT
    pa.port_number,
    pa.allocated_to,
    pa.purpose,
    pa.profile_name,
    n.network_name,
    p.slug as project_slug,
    pa.allocated_at
FROM fleet_port_allocations pa
JOIN fleet_networks n ON pa.network_id = n.id
JOIN projects p ON n.project_id = p.id
WHERE pa.is_active = TRUE
ORDER BY pa.port_number;

CREATE VIEW IF NOT EXISTS fleet_profile_summary AS
SELECT
    np.id,
    np.profile_name,
    np.use_local_services,
    np.enable_mocking,
    n.network_name,
    p.slug as project_slug,
    COUNT(DISTINCT ls.id) as service_count,
    COUNT(DISTINCT CASE WHEN ls.status = 'running' THEN ls.id END) as running_services,
    np.is_default
FROM fleet_network_profiles np
JOIN fleet_networks n ON np.network_id = n.id
JOIN projects p ON n.project_id = p.id
LEFT JOIN fleet_local_services ls ON ls.network_id = np.network_id
    AND ls.profile_name = np.profile_name
GROUP BY np.id, np.profile_name, np.use_local_services, np.enable_mocking,
         n.network_name, p.slug, np.is_default;

CREATE VIEW IF NOT EXISTS fleet_service_status AS
SELECT
    ls.id,
    ls.service_name,
    ls.service_type,
    ls.status,
    ls.port_mapping,
    ls.container_id,
    ls.last_started_at,
    ls.failure_reason,
    np.profile_name,
    n.network_name,
    p.slug as project_slug
FROM fleet_local_services ls
JOIN fleet_networks n ON ls.network_id = n.id
JOIN fleet_network_profiles np ON np.network_id = n.id
    AND np.profile_name = ls.profile_name
JOIN projects p ON n.project_id = p.id;
