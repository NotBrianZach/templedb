-- Create unified views for deployment history and configuration reporting
--
-- This migration creates views that combine data from:
-- - NixOps4 deployments and system_deployments
-- - System configuration across all scopes
-- - Cross-system status and reporting

-- ============================================================================
-- Unified Deployment History View
-- ============================================================================
--
-- Combines:
-- - nixops4_deployments (multi-machine network deployments)
-- - system_deployments (single-machine NixOS rebuilds)
--
-- Provides a single timeline view of all deployment activity

CREATE VIEW IF NOT EXISTS unified_deployment_history AS
-- NixOps4 network deployments
SELECT
    'nixops4' AS deployment_system,
    d.id AS deployment_id,
    d.deployment_uuid AS deployment_identifier,
    p.slug AS project_slug,
    p.name AS project_name,
    n.network_name AS target_name,
    d.operation AS command,
    d.status AS status,
    d.started_at AS deployed_at,
    d.completed_at,
    d.duration_seconds,
    d.triggered_by AS deployed_by,
    d.config_revision,
    COUNT(DISTINCT m.id) AS machines_affected,
    COUNT(DISTINCT CASE WHEN md.status = 'success' THEN md.id END) AS machines_successful,
    d.stdout_log AS output,
    d.stderr_log AS error_output
FROM nixops4_deployments d
JOIN nixops4_networks n ON d.network_id = n.id
JOIN projects p ON n.project_id = p.id
LEFT JOIN nixops4_machine_deployments md ON d.id = md.deployment_id
LEFT JOIN nixops4_machines m ON md.machine_id = m.id
GROUP BY d.id, d.deployment_uuid, p.slug, p.name, n.network_name,
         d.operation, d.status, d.started_at, d.completed_at,
         d.duration_seconds, d.triggered_by, d.config_revision,
         d.stdout_log, d.stderr_log

UNION ALL

-- System (single-machine) deployments
SELECT
    'system' AS deployment_system,
    sd.id AS deployment_id,
    CAST(sd.id AS TEXT) AS deployment_identifier,
    p.slug AS project_slug,
    p.name AS project_name,
    'system' AS target_name,
    sd.command AS command,
    CASE
        WHEN sd.exit_code = 0 THEN 'success'
        ELSE 'failed'
    END AS status,
    sd.deployed_at AS deployed_at,
    sd.deployed_at AS completed_at,  -- Assume immediate completion
    NULL AS duration_seconds,
    sd.created_by AS deployed_by,
    NULL AS config_revision,
    1 AS machines_affected,
    CASE WHEN sd.exit_code = 0 THEN 1 ELSE 0 END AS machines_successful,
    sd.output AS output,
    NULL AS error_output
FROM system_deployments sd
JOIN projects p ON sd.project_id = p.id

ORDER BY deployed_at DESC;


-- ============================================================================
-- Unified Configuration Dashboard View
-- ============================================================================
--
-- Shows all system_config entries with their scope hierarchy and metadata
-- Useful for understanding what configs are defined at each level

CREATE VIEW IF NOT EXISTS unified_config_dashboard AS
-- Machine-level configs
SELECT
    'machine' AS scope_type,
    4 AS scope_priority,  -- Highest
    sc.key,
    sc.value,
    sc.description,
    p.slug AS project_slug,
    n.network_name,
    m.machine_name AS scope_name,
    m.id AS scope_id,
    m.target_host AS scope_detail,
    sc.updated_at
FROM system_config sc
JOIN nixops4_machines m ON sc.scope_id = m.id AND sc.scope_type = 'machine'
JOIN nixops4_networks n ON m.network_id = n.id
JOIN projects p ON n.project_id = p.id

UNION ALL

-- Network-level configs
SELECT
    'network' AS scope_type,
    3 AS scope_priority,
    sc.key,
    sc.value,
    sc.description,
    p.slug AS project_slug,
    n.network_name AS network_name,
    n.network_name AS scope_name,
    n.id AS scope_id,
    CAST(n.id AS TEXT) || ' machines' AS scope_detail,
    sc.updated_at
FROM system_config sc
JOIN nixops4_networks n ON sc.scope_id = n.id AND sc.scope_type = 'network'
JOIN projects p ON n.project_id = p.id

UNION ALL

-- Project-level configs
SELECT
    'project' AS scope_type,
    2 AS scope_priority,
    sc.key,
    sc.value,
    sc.description,
    p.slug AS project_slug,
    NULL AS network_name,
    p.name AS scope_name,
    p.id AS scope_id,
    p.slug AS scope_detail,
    sc.updated_at
FROM system_config sc
JOIN projects p ON sc.scope_id = p.id AND sc.scope_type = 'project'

UNION ALL

-- System-level configs (global)
SELECT
    'system' AS scope_type,
    1 AS scope_priority,  -- Lowest (fallback)
    sc.key,
    sc.value,
    sc.description,
    NULL AS project_slug,
    NULL AS network_name,
    'System-wide' AS scope_name,
    NULL AS scope_id,
    'Global default' AS scope_detail,
    sc.updated_at
FROM system_config sc
WHERE sc.scope_type = 'system'

ORDER BY key, scope_priority DESC;


-- ============================================================================
-- Configuration Coverage Report View
-- ============================================================================
--
-- Shows which configs are defined at each scope level
-- Useful for identifying gaps or redundancy

CREATE VIEW IF NOT EXISTS config_coverage_report AS
SELECT
    sc.key,
    COUNT(DISTINCT CASE WHEN sc.scope_type = 'system' THEN 1 END) AS has_system_default,
    COUNT(DISTINCT CASE WHEN sc.scope_type = 'project' THEN sc.scope_id END) AS project_overrides,
    COUNT(DISTINCT CASE WHEN sc.scope_type = 'network' THEN sc.scope_id END) AS network_overrides,
    COUNT(DISTINCT CASE WHEN sc.scope_type = 'machine' THEN sc.scope_id END) AS machine_overrides,
    COUNT(DISTINCT sc.scope_id) AS total_scopes,
    MIN(sc.updated_at) AS first_set,
    MAX(sc.updated_at) AS last_updated
FROM system_config sc
GROUP BY sc.key
ORDER BY total_scopes DESC, sc.key;


-- ============================================================================
-- Deployment Success Rate View
-- ============================================================================
--
-- Calculates success rates for both deployment systems

CREATE VIEW IF NOT EXISTS deployment_success_rates AS
-- NixOps4 success rates by network
SELECT
    'nixops4' AS deployment_system,
    p.slug AS project_slug,
    n.network_name AS target_name,
    COUNT(*) AS total_deployments,
    COUNT(CASE WHEN d.status = 'success' THEN 1 END) AS successful_deployments,
    COUNT(CASE WHEN d.status = 'failed' THEN 1 END) AS failed_deployments,
    ROUND(100.0 * COUNT(CASE WHEN d.status = 'success' THEN 1 END) / COUNT(*), 2) AS success_rate_percent,
    MIN(d.started_at) AS first_deployment,
    MAX(d.started_at) AS last_deployment
FROM nixops4_deployments d
JOIN nixops4_networks n ON d.network_id = n.id
JOIN projects p ON n.project_id = p.id
GROUP BY p.slug, n.network_name

UNION ALL

-- System deployment success rates by project
SELECT
    'system' AS deployment_system,
    p.slug AS project_slug,
    'system' AS target_name,
    COUNT(*) AS total_deployments,
    COUNT(CASE WHEN sd.exit_code = 0 THEN 1 END) AS successful_deployments,
    COUNT(CASE WHEN sd.exit_code != 0 THEN 1 END) AS failed_deployments,
    ROUND(100.0 * COUNT(CASE WHEN sd.exit_code = 0 THEN 1 END) / COUNT(*), 2) AS success_rate_percent,
    MIN(sd.deployed_at) AS first_deployment,
    MAX(sd.deployed_at) AS last_deployment
FROM system_deployments sd
JOIN projects p ON sd.project_id = p.id
GROUP BY p.slug

ORDER BY success_rate_percent DESC, total_deployments DESC;


-- ============================================================================
-- Active Deployment Status View
-- ============================================================================
--
-- Shows current active/running deployments across both systems

CREATE VIEW IF NOT EXISTS active_deployment_status AS
-- NixOps4 running deployments
SELECT
    'nixops4' AS deployment_system,
    d.deployment_uuid AS identifier,
    p.slug AS project_slug,
    n.network_name AS target_name,
    d.operation,
    d.started_at,
    CAST((julianday('now') - julianday(d.started_at)) * 1440 AS INTEGER) AS elapsed_minutes,
    d.triggered_by,
    COUNT(md.id) AS total_machines,
    COUNT(CASE WHEN md.status = 'success' THEN 1 END) AS completed_machines,
    COUNT(CASE WHEN md.status IN ('pending', 'building', 'deploying') THEN 1 END) AS active_machines
FROM nixops4_deployments d
JOIN nixops4_networks n ON d.network_id = n.id
JOIN projects p ON n.project_id = p.id
LEFT JOIN nixops4_machine_deployments md ON d.id = md.deployment_id
WHERE d.status = 'running' AND d.completed_at IS NULL
GROUP BY d.deployment_uuid, p.slug, n.network_name, d.operation,
         d.started_at, d.triggered_by

ORDER BY d.started_at DESC;


-- ============================================================================
-- Machine Health Summary View
-- ============================================================================
--
-- Combines nixops4_machine_health with system deployment status
-- Provides health status across all managed systems

CREATE VIEW IF NOT EXISTS machine_health_summary AS
-- NixOps4 machines
SELECT
    'nixops4' AS management_system,
    p.slug AS project_slug,
    n.network_name,
    m.machine_name,
    m.target_host,
    m.deployment_status,
    m.health_status,
    m.last_deployed_at,
    m.nixos_version,
    (SELECT COUNT(*)
     FROM nixops4_machine_deployments md
     WHERE md.machine_id = m.id AND md.status = 'failed'
    ) AS failed_deployment_count,
    (SELECT COUNT(*)
     FROM nixops4_machine_deployments md
     WHERE md.machine_id = m.id AND md.status = 'success'
    ) AS successful_deployment_count
FROM nixops4_machines m
JOIN nixops4_networks n ON m.network_id = n.id
JOIN projects p ON n.project_id = p.id

UNION ALL

-- System deployments (single-machine)
SELECT
    'system' AS management_system,
    p.slug AS project_slug,
    NULL AS network_name,
    'system' AS machine_name,
    NULL AS target_host,
    CASE WHEN sd.is_active = 1 THEN 'deployed' ELSE 'inactive' END AS deployment_status,
    CASE WHEN sd.exit_code = 0 THEN 'healthy' ELSE 'unhealthy' END AS health_status,
    sd.deployed_at AS last_deployed_at,
    NULL AS nixos_version,
    (SELECT COUNT(*) FROM system_deployments WHERE project_id = p.id AND exit_code != 0) AS failed_deployment_count,
    (SELECT COUNT(*) FROM system_deployments WHERE project_id = p.id AND exit_code = 0) AS successful_deployment_count
FROM system_deployments sd
JOIN projects p ON sd.project_id = p.id
WHERE sd.is_active = 1

ORDER BY project_slug, network_name, machine_name;


-- ============================================================================
-- Migration Notes
-- ============================================================================
--
-- This migration creates unified reporting views for:
--
-- 1. unified_deployment_history
--    - Single timeline of all deployments (nixops4 + system)
--    - Includes status, timing, and affected machines
--
-- 2. unified_config_dashboard
--    - All system_config entries with scope hierarchy
--    - Shows machine > network > project > system precedence
--
-- 3. config_coverage_report
--    - Which configs are defined at which scopes
--    - Identifies gaps and redundancy
--
-- 4. deployment_success_rates
--    - Success rates by project/network
--    - Across both deployment systems
--
-- 5. active_deployment_status
--    - Currently running deployments
--    - Progress tracking
--
-- 6. machine_health_summary
--    - Health status for all managed machines
--    - Combines nixops4 and system deployments
--
-- Usage Examples:
--
--   -- View all deployments
--   SELECT * FROM unified_deployment_history
--   WHERE project_slug = 'myproject'
--   ORDER BY deployed_at DESC LIMIT 20;
--
--   -- Check config hierarchy
--   SELECT * FROM unified_config_dashboard
--   WHERE key LIKE 'nginx%'
--   ORDER BY scope_priority DESC;
--
--   -- See deployment success rates
--   SELECT * FROM deployment_success_rates
--   WHERE success_rate_percent < 100;
--
--   -- Monitor active deployments
--   SELECT * FROM active_deployment_status;
--
--   -- Check machine health
--   SELECT * FROM machine_health_summary
--   WHERE health_status != 'healthy';
