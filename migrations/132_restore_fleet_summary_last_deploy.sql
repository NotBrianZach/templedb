-- 132_restore_fleet_summary_last_deploy.sql
--
-- Migration 130 recreated fleet_network_summary without
-- last_deployment_at, because that column came from
-- MAX(fleet_deployments.started_at) and fleet_deployments was being
-- dropped. `templedb deploy fleet network list` reads the column by
-- name and broke with KeyError: 'last_deployment_at'.
--
-- My mistake upstream of that: I tested reachability with
-- `templedb fleet --help`, got "Unknown command", and concluded
-- fleet.py was dead code. It is not. It registers as a SUBCOMMAND --
-- `templedb deploy fleet`, via register_under_deploy() at
-- deploy.py:875 -- which is the convention seven other deploy modules
-- use. Checking the top-level namespace for a module that was never
-- meant to be there proved nothing.
--
-- The column comes back, sourced from fleet_machines.last_deployed_at.
-- That is the fact that actually exists and it is what the fleet
-- deployment rows would have been summarising anyway.

DROP VIEW IF EXISTS fleet_network_summary;
CREATE VIEW fleet_network_summary AS
SELECT
    n.id, n.project_id, n.network_name, n.network_uuid, n.is_active,
    p.slug AS project_slug, p.name AS project_name,
    COUNT(DISTINCT m.id) AS machine_count,
    COUNT(DISTINCT CASE WHEN m.deployment_status = 'deployed'
                        THEN m.id END) AS deployed_machines,
    MAX(m.last_deployed_at) AS last_deployment_at,
    n.created_at, n.updated_at
FROM fleet_networks n
JOIN projects p ON n.project_id = p.id
LEFT JOIN fleet_machines m ON n.id = m.network_id
WHERE n.is_active = 1
GROUP BY n.id, n.project_id, n.network_name, n.network_uuid,
         n.is_active, p.slug, p.name, n.created_at, n.updated_at;
