-- 136_one_default_branch_per_project.sql
--
-- Three projects have TWO branches flagged is_default=1:
--
--   templedb        master#2  (head=11,   5 commits)   main#19 (head=1239, 644)
--   system_config   master#6  (head=6)                 main#18 (head=1230)
--   woofs_projects  master#7  (head=NULL)              main#1  (head=1240)
--
-- Nothing picks between them. Both of these resolve the default branch
-- with an unordered single-row read:
--
--   src/cli/commands/publish.py
--     SELECT id FROM vcs_branches WHERE project_id = ? AND is_default = 1
--     ... .fetchone()
--   VCSService.get_default_branch()
--
-- so which branch a publish commits to is whatever SQLite hands back
-- first. There is no ORDER BY and no LIMIT making that stable: it falls
-- out of the query plan, so it can change when an index is added, when
-- the table is rebuilt by a later migration, or when row count crosses
-- a planner threshold. It happens to return main today. That is luck,
-- not a guarantee -- the same shape of latent bug as the merge-parent
-- read that picked a parent with no ORDER BY.
--
-- Committing to master instead of main would not error. It would
-- fast-forward a 5-commit stub branch, leave main's 644-commit history
-- untouched, and publish would then materialize current file_contents
-- and push -- shipping content to the mirror recorded against a branch
-- nobody reads.
--
-- main is canonical in all three projects, which is both the user's
-- call and what the commit counts show: every master here is a stub
-- from an early import that stopped being written to. Clear the flag
-- on the others rather than deleting the branches, since they still
-- own commit rows (5 for templedb) and dropping them would cascade.
UPDATE vcs_branches
   SET is_default = 0
 WHERE is_default = 1
   AND branch_name != 'main'
   AND project_id IN (
       SELECT project_id FROM vcs_branches
        WHERE is_default = 1
        GROUP BY project_id
       HAVING COUNT(*) > 1
   )
   -- Only safe to demote a non-main branch if THIS project actually has
   -- a main to fall back on. A project whose two defaults are, say,
   -- `trunk` and `release` would otherwise be left with zero and no
   -- resolvable default at all, which is worse than an ambiguous one.
   AND project_id IN (
       SELECT project_id FROM vcs_branches WHERE branch_name = 'main'
   );

-- Make the ambiguity unrepresentable rather than relying on the above
-- holding forever. Partial unique index, so it constrains only the
-- flagged rows: any number of non-default branches per project, at most
-- one default. Zero stays legal -- no project is in that state now, and
-- forbidding it would mean a branch has to exist before the first one
-- can be created.
CREATE UNIQUE INDEX IF NOT EXISTS idx_vcs_branches_one_default
    ON vcs_branches(project_id)
 WHERE is_default = 1;
