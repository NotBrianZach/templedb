-- 137_canonicalise_native_commit_ids.sql
--
-- Finish what migration 126 started, on the rows it could not have
-- known about: 81 commit_hash values that are 40-char lowercase and are
-- NOT git SHAs.
--
-- 126 gave commit_hash a single meaning -- native ids only, git SHAs in
-- git_commit_hash -- and repaired 261 rows on the premise that 40-char
-- lowercase identified a git SHA from git-history import. The premise
-- was incomplete: TWO writers produce that format.
--
--   src/importer/git_history.py:336 passes commit_hash=commit.hash, the
--     raw git SHA, and still does. 126 fixed the data, not this writer.
--   src/cli/commands/commit.py took sha256(f"{project_id}-{message}-
--     {time.time()}").hexdigest()[:40] -- a NATIVE id wearing git's
--     format, for an object that is not in git at all. Fixed to
--     [:16].upper() on 2026-10-13, matching `vcs commit`.
--
-- So after 126 every new 40-char lowercase row was ambiguous by
-- construction, and both halves leave git_commit_hash NULL. The count
-- climbed back to 81 across six projects and
-- commit_hash_is_canonical has been red throughout.
--
-- WHY ALL 81 ARE THE SECOND KIND
--
-- A git oracle was the obvious classifier and it does not work here.
-- `git cat-file -e` finds none of these -- but it also finds none of
-- the 261 rows that DO carry a git_commit_hash, so it is blind rather
-- than informative: publish's materialize regenerates these histories
-- and the SHAs the database recorded are no longer reachable objects. A
-- negative result from a blind oracle is indistinguishable from a true
-- negative, so it is not used here.
--
-- Six independent lines of evidence instead, all agreeing:
--
--   1. 81b33a4a90e590713672e11073566ef394093b29 is in this set and is
--      known native -- `templedb commit` produced it on 2026-10-13 and
--      the session that ran it watched it happen.
--   2. None carry git-import fingerprints. git_history sets author and
--      author_email from git; all 81 have author='zach', email NULL.
--   3. 49 of the 81 have a session_id. Sessions are a concept only the
--      commit commands touch; the rate elsewhere is 0.8%-2.7%.
--   4. Not one has a 'TempleDB materialize%' message, which is what
--      these repositories' histories actually contain. vcs_commits
--      holds no such message at all, so git history has never been
--      imported into this database.
--   5. All 81 postdate 126 (applied 2026-10-06 21:44:36), which
--      repaired every git SHA then present.
--   6. git_history dedupes via get_commit_by_hash, so a re-import would
--      have produced materialize-message rows. See 4.
--
-- WHAT THIS DOES
--
-- upper(substr(commit_hash, 1, 16)) -- the same transform 126 used, and
-- the same prefix-of-sha256 the fixed generator now emits, so a row
-- migrated here is indistinguishable from one written after the fix.
-- Verified before writing: 81 distinct results, zero collisions with
-- each other and zero with any existing commit_hash in any project.
-- There is no UNIQUE index on the column, so a collision would not have
-- raised -- it would have made two commits share an id and `vcs show`
-- ambiguous.
--
-- Unlike 126's 'git-sha' rows, NOTHING moves to git_commit_hash. These
-- values are not git SHAs; preserving them there would assert the exact
-- falsehood that made this set ambiguous.
--
-- NOT ADDRESSED HERE: git_history.py still writes a git SHA into
-- commit_hash. Nothing has run it since 126 -- which is what lets this
-- migration be unambiguous -- but it is why the invariant can regress.
-- Fixing it means deciding what native id a git-imported commit should
-- get, which is a design question rather than a data one.

CREATE TABLE IF NOT EXISTS commit_hash_migration_137 (
    commit_id  INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    old_hash   TEXT NOT NULL,
    new_hash   TEXT NOT NULL,
    -- 'native-40'  a native id that merely wore git's 40-char lowercase
    --              format. There is no other kind in this migration;
    --              the column exists so the audit trail says which
    --              claim was made, as 126's does.
    kind       TEXT NOT NULL
);

-- Built first so every UPDATE below keys off the map rather than off
-- the live value. Without it the statement order would matter and
-- vcs_commits would have to go last; with it each table is rewritten
-- independently and the migration is re-runnable.
INSERT OR IGNORE INTO commit_hash_migration_137
    (commit_id, project_id, old_hash, new_hash, kind)
SELECT id, project_id, commit_hash, upper(substr(commit_hash, 1, 16)),
       'native-40'
  FROM vcs_commits
 WHERE length(commit_hash) = 40
   AND git_commit_hash IS NULL;

-- Commit entities. external_ref is '<slug>/<hash>'; relations key on
-- integer entity ids, so rewriting the ref in place leaves every edge
-- intact and nothing needs re-pointing. 81 rows.
UPDATE entities
   SET external_ref = (
           SELECT p.slug || '/' || m.new_hash
             FROM commit_hash_migration_137 m
             JOIN projects p ON p.id = m.project_id
            WHERE entities.external_ref = p.slug || '/' || m.old_hash)
 WHERE kind = 'Commit'
   AND EXISTS (
           SELECT 1
             FROM commit_hash_migration_137 m
             JOIN projects p ON p.id = m.project_id
            WHERE entities.external_ref = p.slug || '/' || m.old_hash);

-- Tables holding the bare hash. Counted before writing:
-- report_implementations 6, nix_generations 4, sync_vcs_commits 35, and
-- zero in deployment_history, handoff_notes,
-- project_files.last_commit_hash and vcs_commit_metadata.related_commits
-- -- so those four are not touched.
UPDATE report_implementations
   SET commit_hash = (SELECT m.new_hash FROM commit_hash_migration_137 m
                       WHERE m.old_hash = report_implementations.commit_hash)
 WHERE commit_hash IN (SELECT old_hash FROM commit_hash_migration_137);

UPDATE nix_generations
   SET commit_hash = (SELECT m.new_hash FROM commit_hash_migration_137 m
                       WHERE m.old_hash = nix_generations.commit_hash)
 WHERE commit_hash IN (SELECT old_hash FROM commit_hash_migration_137);

-- The CRDT shadow. vcs_commits has only an AFTER INSERT trigger, so an
-- UPDATE does not propagate and this has to be rewritten by hand --
-- same reason 126 did it, quoted here because it is not obvious from
-- the schema.
UPDATE sync_vcs_commits
   SET commit_hash = (SELECT m.new_hash FROM commit_hash_migration_137 m
                       WHERE m.old_hash = sync_vcs_commits.commit_hash)
 WHERE commit_hash IN (SELECT old_hash FROM commit_hash_migration_137);

UPDATE vcs_commits
   SET commit_hash = (SELECT m.new_hash FROM commit_hash_migration_137 m
                       WHERE m.commit_id = vcs_commits.id)
 WHERE id IN (SELECT commit_id FROM commit_hash_migration_137);
