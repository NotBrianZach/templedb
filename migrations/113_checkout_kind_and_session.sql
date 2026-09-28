-- 113_checkout_kind_and_session.sql
--
-- Phase 1 of reports/2026-09-27-2103-checkout-role-and-session-scoped-
-- resolution-design.html. Bookkeeping only: adds the columns and
-- classifies the existing rows. No resolution code reads `kind` yet, so
-- this migration cannot change which checkout any command picks.
--
-- The problem it prepares to fix: `checkouts.is_active` was 1 on all 61
-- rows and 0 on none. Nothing ever cleared it -- the single UPDATE that
-- touches it (vcs_service.py, session reaping) only fires when a
-- workspace is rmtree'd -- so `WHERE is_active = 1` was a no-op filter
-- and "the active checkout" effectively meant "whichever directory was
-- written to most recently". Any command that materialised a tree
-- elsewhere could therefore make a different tree authoritative as a
-- side effect. On 2026-09-26 that is exactly what happened: a
-- `project checkout` refreshed the canonical tree, the next `vcs add`
-- re-hashed a pre-correction copy out of it, and system_config commit
-- FA20845EE25BD208 recorded content that `file set --verify` had already
-- superseded.
--
-- Three roles, because the readers genuinely want different trees and no
-- single "active" flag can express that:
--
--   canonical  the materialised, publish-owned tree. What builds,
--              `publish` and `materialize` must read.
--   edit       a writable working tree. What staging and commit must
--              read. Ideally one per session.
--   scratch    throwaway (/tmp, one-off `project checkout <dir>`).
--              Never authoritative for anything; usable only when named
--              explicitly, e.g. `templedb commit <slug> <dir>`.

ALTER TABLE checkouts ADD COLUMN kind TEXT NOT NULL DEFAULT 'scratch';
ALTER TABLE checkouts ADD COLUMN session_id INTEGER REFERENCES vcs_sessions(id);

-- DEFAULT 'scratch' is fail-safe on purpose. An unclassified row must
-- never win authority; defaulting to 'edit' would make every future
-- unlabelled row a candidate, which is the bug above with extra steps.

-- Classification is by path shape alone -- no inference, no guessing at
-- intent. Measured before writing: 47 scratch, 9 edit, 5 canonical.
UPDATE checkouts
   SET kind = 'canonical'
 WHERE checkout_path LIKE '%/.config/templedb/checkouts/%';

UPDATE checkouts
   SET kind = 'edit'
 WHERE checkout_path LIKE '%/.config/templedb/edit-workspaces/%';

-- session_id is deliberately left NULL for every existing row. The leaf
-- name of a session-stamped workspace usually IS the session name, so a
-- join against vcs_sessions would populate some of them -- but nothing
-- consumes historical attribution, and a wrong owner is worse than an
-- honest NULL because resolution will treat "owned by another live
-- session" as a reason to refuse. Only new checkouts get an owner.

-- Retire the scratch rows. This is the single change that removes the
-- most exposure: all 47 are /tmp trees that still exist on disk, and
-- each was one `project checkout` away from becoming the tree that the
-- next commit was built from.
UPDATE checkouts
   SET is_active = 0
 WHERE kind = 'scratch';

-- Retire the "bare legacy" edit rows -- edit-workspaces/<slug> with no
-- session segment beneath it.
--
-- These are not merely stale, they are structurally wrong: each one is
-- the PARENT directory of the session-stamped workspaces for the same
-- project. edit-workspaces/templedb contains both a copy of the project
-- AND edit-workspaces/templedb/claude-code-agent-fixups. If such a row
-- ever won resolution, a scan of it would descend into the session
-- subdirectories and see every file twice.
--
-- Matched structurally rather than by listing the three absolute paths,
-- so this stays correct on a machine with a different $HOME: an edit
-- path with no '/' after the 'edit-workspaces/' prefix is a bare one.
-- Verified against the live database to select exactly the 3 intended
-- rows and none of the 6 session-stamped ones.
UPDATE checkouts
   SET is_active = 0
 WHERE kind = 'edit'
   AND instr(checkout_path, '/edit-workspaces/') > 0
   AND instr(
         substr(checkout_path,
                instr(checkout_path, '/edit-workspaces/')
                + length('/edit-workspaces/')),
         '/') = 0;

-- Expected after this migration: 50 rows deactivated (47 scratch + 3
-- bare legacy), 11 left active (5 canonical + 6 session-stamped edit).
--
-- This does NOT make resolution unambiguous, and the design report is
-- explicit that it cannot: bza still has 3 live edit workspaces and
-- templedb 2. Disambiguating those needs session ownership (phase 4),
-- which is why the per-session unique index is not created here. SQLite
-- treats NULLs as distinct in a unique index, so an index on
-- (project_id, session_id) would admit every row this migration leaves
-- with a NULL session_id -- precisely the ambiguous set. It would look
-- like a constraint while enforcing nothing.
--
-- The canonical index IS satisfiable today (5 rows, 5 projects, 0
-- violations) but is held back to phase 3 so that this migration stays
-- pure bookkeeping and can be reverted by clearing the two columns.
