-- 134_register_local_host_in_fleet.sql
--
-- machines_with_generations_are_registered has been red for as long as
-- it has existed, with exactly one issue: zMothership2 has 159 nix
-- generations and no fleet_machines row. Its own docstring explains
-- why it was left that way --
--
--   "Fixing the FK means registering the host, which is a decision
--    about the user's fleet rather than a repair, so it is reported
--    rather than performed."
--
-- That was the right call for a check to make. The decision has now
-- been taken: register it.
--
-- The registry listed exactly the five machines that have done nothing
-- (every one of them "never deployed via templedb") and omitted the
-- one doing everything. zMothership2 goes into zach-lan, the
-- system_config network, because system_config is what deploys this
-- host -- zMothership3 is already there as its sibling.
--
-- Fields come from the latest recorded generation rather than being
-- invented, so the row describes what actually happened. target_host
-- is 'localhost' because it *is* this machine; reconcile learned in
-- the same change to read local state directly instead of trying to
-- SSH to itself, which it would otherwise now do daily and fail.
--
-- machine_uuid is NOT NULL UNIQUE, so it is generated here.
-- randomblob is the only source available inside a migration; the
-- column is an identifier, not data, so an arbitrary value is correct.

INSERT INTO fleet_machines (
    network_id, machine_name, machine_uuid,
    target_host, target_user, target_port,
    system_type, target_env,
    nixos_version, system_profile, boot_id,
    deployment_status, last_deployed_at, health_status
)
SELECT
    (SELECT n.id FROM fleet_networks n
       JOIN projects p ON p.id = n.project_id
      WHERE n.network_name = 'zach-lan' AND p.slug = 'system_config'),
    'zMothership2',
    lower(
        substr(hex(randomblob(4)), 1, 8) || '-' ||
        substr(hex(randomblob(2)), 1, 4) || '-' ||
        substr(hex(randomblob(2)), 1, 4) || '-' ||
        substr(hex(randomblob(2)), 1, 4) || '-' ||
        substr(hex(randomblob(6)), 1, 12)),
    'localhost', 'root', 22,
    'nixos', 'none',
    g.nixos_version, g.toplevel_path, g.boot_id,
    'deployed', g.switched_at, 'healthy'
  FROM nix_generations g
 WHERE g.machine_name = 'zMothership2'
   AND g.generation_number = (SELECT MAX(generation_number)
                                FROM nix_generations
                               WHERE machine_name = 'zMothership2')
   -- Idempotent, and a no-op if zach-lan is ever renamed away.
   AND NOT EXISTS (SELECT 1 FROM fleet_machines
                    WHERE machine_name = 'zMothership2')
   AND (SELECT n.id FROM fleet_networks n
          JOIN projects p ON p.id = n.project_id
         WHERE n.network_name = 'zach-lan'
           AND p.slug = 'system_config') IS NOT NULL
 LIMIT 1;

-- is_local is deliberately left FALSE. The flag drives
-- fleet_local_machines, which is about machines that run *services*
-- locally (local_port_base, local_fhs_env, local_working_dir) -- the
-- bza-local shape. zMothership2 is a NixOS host that happens to be
-- this one, not a local-service target, and putting it in that view
-- with three NULL columns would be the misleading answer.

-- Migration 130's machine_id backfill matched 0 of 156 rows because
-- there was no registry row to join to. Now there is. Same statement,
-- scoped to the rows that were waiting on it.
UPDATE nix_generations
   SET machine_id = (
       SELECT m.id FROM fleet_machines m
        WHERE m.machine_name = nix_generations.machine_name
        LIMIT 1)
 WHERE machine_id IS NULL
   AND machine_name IS NOT NULL;
