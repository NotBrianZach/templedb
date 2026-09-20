-- Migration 103: sessions get a `context` attribute
--
-- Motivation: agents (Claude Code and similar wrappers) run each
-- templedb call in a fresh shell with a fresh session-leader PID and
-- no inherited env. The existing SID-based resolution creates a new
-- session per shell, so `file set` in one call and `vcs commit` in the
-- next end up in different sessions — commit sees nothing staged in
-- "this" session and prints the well-known
-- "N file(s) staged in other sessions" footer.
--
-- The current workaround is a filesystem pin
-- (~/.local/state/templedb/session.pin), which works but requires
-- explicit setup, isn't queryable from the DB, and expires opaquely.
--
-- Fix: sessions get a `context` column. When `TEMPLEDB_CONTEXT=<name>`
-- is set in env, session resolution matches on (author, host, context)
-- instead of (author, host, sid). The env var IS the session identity
-- — declarative, no detection heuristics, no pin file needed. Multiple
-- shells with the same context share a session; different contexts
-- get isolated sessions on the same host.
--
-- Backward compatible: existing rows have `context = NULL` and
-- continue resolving via SID / pin / SESSION_ID env. Only the
-- explicit env-var path exercises the new column.
--
-- Design: reports/2026-09-19-2012-declarative-reframe-*.html §1.

ALTER TABLE vcs_sessions ADD COLUMN context TEXT;

-- Fast lookup for the resolution path: (author, host, context) with
-- ended_at IS NULL. Partial index keeps it tiny — most rows have
-- context = NULL and are excluded.
CREATE INDEX IF NOT EXISTS idx_vcs_sessions_context_active
    ON vcs_sessions(author, host, context)
    WHERE ended_at IS NULL AND context IS NOT NULL;
