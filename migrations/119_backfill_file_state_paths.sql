-- Migration 119: backfill the file_path rows written NULL after 118.
--
-- Migration 118 added vcs_file_states.file_path and backfilled every
-- existing row, but the writers were never taught to populate it. Every
-- commit from 3F8FA78C (2026-10-01 15:36, the first after 118 applied)
-- onward therefore has file_path NULL on all its rows -- 10 rows across
-- 5 commits at the time this was written.
--
-- That column is not cosmetic. project_files is hard-deleted on commit
-- (cli/commands/file.py), so for a deleted file this row is the only
-- surviving record of what the path was; 118 exists partly because 140
-- such rows could recover their path only from commit_files. A NULL here
-- is unrecoverable once the project_files row goes.
--
-- All 10 rows are still recoverable: their files are present in
-- project_files, because nothing committed in that window was a delete.
-- Had any been, this migration could not have rescued them -- which is
-- the argument for fixing the writers (same change as this migration)
-- rather than re-running a backfill periodically.
--
-- Scoped to rows that can actually be resolved. A row whose file_id is
-- gone from project_files keeps its NULL: there is nothing truthful to
-- put there, and inventing a path would be worse than an honest gap.

UPDATE vcs_file_states
   SET file_path = (
           SELECT pf.file_path
             FROM project_files pf
            WHERE pf.id = vcs_file_states.file_id
       )
 WHERE file_path IS NULL
   AND EXISTS (
           SELECT 1
             FROM project_files pf
            WHERE pf.id = vcs_file_states.file_id
       );
