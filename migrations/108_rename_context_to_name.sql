-- Migration 108: unify vcs_sessions.context into vcs_sessions.name
--
-- Migration 103 added `context` for TEMPLEDB_CONTEXT-based session
-- resolution but `name` (present since 082 as an "optional human
-- label") already served the same purpose. All INSERTs since 103
-- populated both columns identically (see VCSService.get_current_session
-- and the "context:..." prefix pattern in `name`). The two columns
-- are redundant.
--
-- Drop `context` and standardize on `name`. Env var renamed alongside
-- in code: TEMPLEDB_CONTEXT -> TEMPLEDB_SESSION.
--
-- Why the naming matters: `context` collides with `templedb context
-- generate` (LLM context bundles) and reads ambiguously against
-- session-identity semantics; `name` says exactly what the value is
-- and reads declaratively ("this shell belongs to the <name> session").
--
-- Data migration: prefer the raw context value in `name` for rows
-- that used the "context:<value>" prefix pattern — that way an env
-- var TEMPLEDB_SESSION=<value> will match those legacy rows on their
-- new `name` field. Other rows keep their existing `name`.

UPDATE vcs_sessions
   SET name = context
 WHERE context IS NOT NULL
   AND name = 'context:' || context;

-- Drop the migration-103 index that references context before the
-- column drop (SQLite won't auto-drop referring indexes and the
-- ALTER errors otherwise).
DROP INDEX IF EXISTS idx_vcs_sessions_context_active;

-- SQLite 3.35+ supports ALTER TABLE DROP COLUMN. TempleDB targets
-- SQLite 3.35+ (migration 083 already relied on this).
ALTER TABLE vcs_sessions DROP COLUMN context;

-- Replacement index keyed on `name` for the same fast (author, host,
-- name) resolution path Phase B's declarative-session lookup uses.
CREATE INDEX IF NOT EXISTS idx_vcs_sessions_name_active
    ON vcs_sessions(author, host, name)
    WHERE ended_at IS NULL AND name IS NOT NULL;
