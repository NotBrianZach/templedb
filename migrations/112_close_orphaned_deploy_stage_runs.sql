-- 112_close_orphaned_deploy_stage_runs.sql
--
-- Backfill for the leak fixed in VCSService.end_session.
--
-- deploy_stage_runs rows are finalized by the stage context manager on
-- exit. Nothing finalized them when the owning *session* ended, so a
-- wrapper process that died mid-stage — or any session closed by
-- `vcs session gc` — left its row at ended_at IS NULL permanently, and
-- deploy_stages_have_no_stale_runs counted it forever after.
--
-- State on 2026-09-25: 13 open rows out of 189, oldest stuck since
-- 2026-09-21 18:47. Every one of the 13 belonged to a session that had
-- already ended, which is what identifies them as orphans rather than
-- work in flight.
--
-- Scoped deliberately to runs whose session is *provably* finished. An
-- open run with a NULL session_id, or one whose session is still
-- active, may legitimately be in flight right now and is left alone —
-- the invariant's 900s threshold is the right detector for those.
--
-- 'orphaned' is a new outcome value alongside the existing 'success'
-- and 'noop'. It is deliberately distinguishable from both: these
-- stages did not succeed and did not decline to act, they were
-- abandoned, and a later audit should be able to tell the difference.

UPDATE deploy_stage_runs
   SET ended_at = datetime('now'),
       outcome  = 'orphaned'
 WHERE ended_at IS NULL
   AND session_id IN (
         SELECT id FROM vcs_sessions WHERE ended_at IS NOT NULL
       );
