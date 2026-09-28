-- 114_checkout_session_backfill.sql
--
-- Phase 4 groundwork for reports/2026-09-27-2103-checkout-role-and-
-- session-scoped-resolution-design.html: give the existing edit
-- workspaces an owner.
--
-- Migration 113 deliberately left session_id NULL everywhere, on the
-- reasoning that historical attribution had no consumer and a wrong
-- owner is worse than an honest NULL. Both halves of that have since
-- changed:
--
--   * There IS a consumer now. resolve(PURPOSE_EDIT) prefers the calling
--     session's own workspace, and refuses to silently take one owned by
--     another LIVE session. With every session_id NULL, every tree looks
--     unowned, so the preference could never fire and concurrent agents
--     kept sharing one answer.
--   * It is not a guess. Every one of the 6 live edit workspaces has a
--     leaf directory name that matches a vcs_sessions.name EXACTLY --
--     they are named by the session that created them:
--
--       claude-code-agent-15508              -> session 942 (live)
--       claude-code-agent-521251             -> session 940 (ended)
--       zMothership2-201212-20260921-141308  -> session 896 (ended)
--       zMothership2-951760-20260924-130517  -> session 922 (ended)
--       claude-code-agent-fixups             -> session 944 (live)
--       zMothership2-1107692-20260924-153510 -> session 935 (ended)
--
--     So this is a join on an exact key, not inference from a shape.
--
-- Scoped to kind='edit'. A canonical tree is shared by definition and
-- must not acquire an owner -- if it did, resolve() would start treating
-- the published tree as some session's private workspace.
--
-- Rows whose leaf matches no session keep NULL and stay adoptable, which
-- is the correct reading of "nobody owns this".

UPDATE checkouts
   SET session_id = (
       SELECT s.id
         FROM vcs_sessions s
        WHERE s.name = replace(checkouts.checkout_path,
                               rtrim(checkouts.checkout_path,
                                     replace(checkouts.checkout_path, '/', '')),
                               '')
        ORDER BY s.started_at DESC
        LIMIT 1)
 WHERE kind = 'edit'
   AND session_id IS NULL
   AND EXISTS (
       SELECT 1
         FROM vcs_sessions s
        WHERE s.name = replace(checkouts.checkout_path,
                               rtrim(checkouts.checkout_path,
                                     replace(checkouts.checkout_path, '/', '')),
                               ''));

-- The leaf extraction above is the standard SQLite idiom and reads
-- badly, so: replace(path, '/', '') strips every slash; rtrim(path,
-- <that>) removes all trailing characters that appear in it, leaving the
-- directory prefix up to and including the final '/'; replacing that
-- prefix with '' leaves the last path segment. ORDER BY started_at DESC
-- picks the most recent session when a name was reused.
--
-- Expected: 6 of 6 live edit rows owned, plus any inactive ones whose
-- names still match. Ownership by itself changes nothing for a caller
-- with no session -- it only lets resolve() distinguish "mine" from
-- "someone else's, and they are still running".
