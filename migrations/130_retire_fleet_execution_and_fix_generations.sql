-- 130_retire_fleet_execution_and_fix_generations.sql
--
-- Three unrelated cleanups that all came out of checking claims from
-- the 2026-10-06 schema atlas rather than acting on them.
--
-- ---------------------------------------------------------------
-- 1. Retire the fleet deployment-EXECUTION tables
-- ---------------------------------------------------------------
--
-- The atlas said the fleet_* family was "6 tables, 6 triggers, 4
-- views, 0 operational rows" and should go. Checking before deleting
-- showed that was wrong in the way that matters: only three of the six
-- are empty, and fleet_machines is load-bearing -- read by
-- reconcile.py, the fleet_machines_reconciled_within_7_days invariant,
-- summary, nix_deploy_backend, the Prolog engine and three GUI pages.
--
-- So the registry half stays (fleet_networks -> fleet_machines, 5 rows
-- each) and the execution half goes:
--
--   fleet_deployments          0 rows, ever
--   fleet_machine_deployments  0 rows, ever
--   fleet_resources            0 rows, ever
--
-- These are the nixops4-shaped model: deploy as a transaction across
-- machines, per-machine build/activate tracking, DNS and volumes as
-- first-class resources. It never ran once. What runs instead is the
-- observer-shaped path -- each machine switches itself and TempleDB
-- records what happened: 156 nix_generations and 11 reconcile_runs.
--
-- That is the real content of this change. Deleting these three tables
-- is the decision that TempleDB stays an observer rather than becoming
-- an orchestrator again, which is the same question Phase 5 asks about
-- the authority-over-source vocabulary. The data had already chosen.
--
-- nix_generations.deployment_id references fleet_deployments. It is
-- NULL on all 156 rows (nothing ever wrote it), so the column is
-- dropped with the table it pointed at. SQLite does not enforce FKs to
-- a dropped table, but leaving a column referencing nothing is how the
-- next reader gets misled -- see related_readmes in migration 127.

DROP VIEW  IF EXISTS fleet_deployment_history;
DROP TABLE IF EXISTS fleet_machine_deployments;
DROP TABLE IF EXISTS fleet_resources;
DROP TABLE IF EXISTS fleet_deployments;

-- fleet_network_summary counted fleet_resources and fleet_deployments.
-- Recreated without them rather than dropped: machine_count and
-- deployed_machines are the useful half and `summary` reads it.
DROP VIEW IF EXISTS fleet_network_summary;
CREATE VIEW fleet_network_summary AS
SELECT
    n.id, n.project_id, n.network_name, n.network_uuid, n.is_active,
    p.slug AS project_slug, p.name AS project_name,
    COUNT(DISTINCT m.id) AS machine_count,
    COUNT(DISTINCT CASE WHEN m.deployment_status = 'deployed'
                        THEN m.id END) AS deployed_machines,
    n.created_at, n.updated_at
FROM fleet_networks n
JOIN projects p ON n.project_id = p.id
LEFT JOIN fleet_machines m ON n.id = m.network_id
WHERE n.is_active = 1
GROUP BY n.id, n.project_id, n.network_name, n.network_uuid,
         n.is_active, p.slug, p.name, n.created_at, n.updated_at;

-- ---------------------------------------------------------------
-- 2. nix_generations.machine_id was never written
-- ---------------------------------------------------------------
--
-- NULL on all 156 rows, while fleet_machines holds 5. The
-- generation<->machine join has been running entirely through the
-- denormalised machine_name string, so the declared FK is decoration
-- and `provenance machine <host>` cannot use it.
--
-- Backfilled by name, which is exactly what the denormalised column
-- was standing in for. Rows whose machine_name matches no registry row
-- stay NULL -- that is the honest answer for a host TempleDB has a
-- generation from but no record of, and it is also what makes the
-- remaining NULL count meaningful rather than ambient.

UPDATE nix_generations
   SET machine_id = (
       SELECT m.id FROM fleet_machines m
        WHERE m.machine_name = nix_generations.machine_name
        LIMIT 1)
 WHERE machine_id IS NULL
   AND machine_name IS NOT NULL;

-- ---------------------------------------------------------------
-- 3. A fabricated content_blobs row keyed 'DELETED'
-- ---------------------------------------------------------------
--
-- content_blobs has a row whose hash_sha256 is the literal string
-- 'DELETED', created 2026-03-19, claiming content_type='binary' and
-- file_size_bytes=8059, with both content_text and content_blob NULL.
-- It is not a blob; it is the deletion sentinel that leaked out of
-- vcs_file_states.content_hash into the blob table.
--
-- The damage is that it lends the sentinel false credibility. 501
-- source_snapshots rows join to it and come back looking like a real
-- 8 KB revision whose content merely failed to load, rather than like
-- a record that was never kept. Nothing legitimate references it:
-- file_contents 0, vcs_working_state 0, checkout_snapshots 0,
-- edit_intents 0. Only vcs_file_states, which has no FK to
-- content_blobs, so this does not cascade.
--
-- The 501 vcs_file_states rows are left alone. They are history, the
-- bytes are gone, and rewriting them would substitute a different lie
-- for this one. file_states_have_recoverable_content reports the 124
-- non-deleted ones and holds the line against more.

DELETE FROM content_blobs WHERE hash_sha256 = 'DELETED';
