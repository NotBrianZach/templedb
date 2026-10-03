-- 122_checkout_role_unique_indexes.sql
--
-- Phase 3 of reports/2026-09-27-2103-checkout-role-and-session-scoped-
-- resolution-design.html: promote the two rules resolve() already
-- assumes into constraints the database enforces, and retire the scratch
-- rows that have accumulated since migration 113.
--
-- Why now rather than with 113: that migration deliberately stayed pure
-- bookkeeping so it could be reverted by clearing the two columns, and
-- the per-session index was unenforceable while every session_id was
-- NULL. Migration 114 then populated ownership from an exact join on
-- vcs_sessions.name, and CheckoutRepository.create_or_update now stamps
-- session_id on every new edit tree, so owned rows are the normal case
-- rather than the exception.

-- One canonical tree per project.
--
-- Measured on the live database before writing: 7 active canonical rows
-- across 7 distinct projects, 0 violations. This has always been true
-- structurally -- the canonical path is checkouts/<slug>, one per project
-- by construction -- but nothing stopped a second row from being
-- inserted and winning resolution for PURPOSE_BUILD, which decides what
-- `publish` and `materialize` read.
CREATE UNIQUE INDEX IF NOT EXISTS checkouts_one_canonical
    ON checkouts(project_id)
 WHERE kind = 'canonical' AND is_active = 1;

-- One edit tree per (project, session).
--
-- Measured: 9 active edit rows, no duplicate (project_id, session_id)
-- pair. What this does and does not buy is worth being exact about,
-- because the index looks stronger than it is:
--
--   It DOES stop one session from owning two edit trees in the same
--   project, which is the state that would make resolve()'s "prefer
--   mine" step pick arbitrarily between two trees the caller has equal
--   claim to -- silently, with no warning, since that branch returns
--   mine[0] without checking for a second match.
--
--   It does NOT constrain unowned rows. SQLite treats NULLs as distinct
--   in a unique index, so every session_id IS NULL row slips through --
--   and those are precisely the rows resolve() calls "adoptable" and
--   warns about when there is more than one. Making that case impossible
--   is not an index's job; it needs the stale-tree prune named below.
CREATE UNIQUE INDEX IF NOT EXISTS checkouts_one_edit_per_session
    ON checkouts(project_id, session_id)
 WHERE kind = 'edit' AND is_active = 1;

-- Retire scratch rows created since 113.
--
-- 113 deactivated all 47 scratch rows that existed then, but
-- create_or_update inserts every new checkout with is_active = 1
-- regardless of kind, so each `templedb commit <slug> <dir>` against a
-- /tmp tree leaves a fresh active scratch row behind. One had already
-- accumulated: /tmp/tdb-land, created 2026-10-02 14:55 by a
-- `templedb commit templedb /tmp/tdb-land`.
--
-- resolve() ignores kind='scratch' for both purposes, so an active
-- scratch row cannot win resolution and this is not a correctness fix.
-- It is a noise fix with a real cost attached: the checkout_matches_db
-- invariant walks active rows, so /tmp/tdb-land was reported as
-- "templedb: src/db_utils.py DIFFERS between DB and checkout ... builds
-- and commits reading /tmp/tdb-land will silently use the checkout's
-- version" -- a warning about a tree nothing resolves to. A health check
-- that cries wolf about unreachable trees is how the real entries in it
-- get skimmed past.
--
-- Deactivating rather than deleting: `templedb commit <slug> <dir>`
-- reaches its tree through get_by_path, which does not filter on
-- is_active, so a named scratch tree keeps working. The row is also the
-- only record that the tree was ever checked out.
UPDATE checkouts
   SET is_active = 0
 WHERE kind = 'scratch'
   AND is_active = 1;

-- Not done here, and the reason, so the next reader does not assume
-- phase 4 is finished:
--
-- The design's last step makes an ambiguous edit resolution fatal
-- instead of a warning. That is still gated, and reaping the eight
-- expired sessions on 2026-10-02 made it more gated rather than less:
-- ending a session does not deactivate its edit checkout row, and
-- resolve() counts a row whose owner is no longer live as adoptable. So
-- bza and templedb each went from 1 adoptable tree to 3. Raising today
-- would break exactly the projects most used.
--
-- The missing piece is the prune the design names: deactivate an edit
-- row whose owning session has ended AND whose tree holds no
-- uncommitted changes. The second half cannot be expressed in SQL -- it
-- is a content comparison against the filesystem -- so it belongs in
-- admin checkout-gc, not in a migration.
