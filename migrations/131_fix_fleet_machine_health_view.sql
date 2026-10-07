-- 131_fix_fleet_machine_health_view.sql
--
-- Migration 130 dropped fleet_machine_deployments and recreated
-- fleet_network_summary, but missed fleet_machine_health, which also
-- reads it. The view kept compiling in sqlite_master and failed only
-- on SELECT -- the exact condition migration 127 added
-- views_are_runnable for.
--
-- That check caught this one deploy cycle after the drop, which is
-- the shortest feedback loop any defect in this series has had. The
-- previous instance of the same shape, related_readmes, survived six
-- migrations. Worth recording as evidence the invariant layer pays
-- for itself: the author of the regression was the author of the
-- check, and it still caught him.
--
-- Recreated without the two subqueries that read the dropped table.
-- last_successful_deployment and failed_deployment_count came from
-- fleet_machine_deployments, which held zero rows for its entire
-- existence, so both columns were always NULL/0 anyway. Dropping them
-- loses nothing real; m.last_deployed_at carries the fact that exists.

DROP VIEW IF EXISTS fleet_machine_health;
CREATE VIEW fleet_machine_health AS
SELECT
    m.id, m.machine_name, m.network_id,
    n.network_name, n.project_id, p.slug AS project_slug,
    m.target_host, m.deployment_status, m.health_status,
    m.last_deployed_at, m.last_health_check_at, m.nixos_version
FROM fleet_machines m
JOIN fleet_networks n ON m.network_id = n.id
JOIN projects p ON n.project_id = p.id
ORDER BY n.network_name, m.machine_name;
