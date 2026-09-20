-- Session-scoped VCS staging (Phase 1 of 5)
--
-- Motivation: TempleDB's VCS has one shared staging area per project/branch,
-- so parallel agents sweep each other's in-progress work into their commits.
-- This migration adds a lightweight sessions table and a foreign-key column
-- on vcs_working_state, so staging becomes session-isolated. Old `staged`
-- BOOLEAN stays for one release as a compat mirror maintained by service
-- code (dropped in a follow-up migration once nothing reads it).
--
-- Design: reports/2026-08-20-session-scoped-vcs-staging-design.html

CREATE TABLE IF NOT EXISTS vcs_sessions (
    id INTEGER PRIMARY KEY,
    name TEXT,                              -- optional human label
    author TEXT NOT NULL,                   -- resolved from TEMPLEDB_AUTHOR / git config / 'unknown'
    host TEXT,                              -- socket.gethostname() at start
    pid INTEGER,                            -- start pid (debugging)
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,                          -- NULL = active
    ended_reason TEXT                       -- 'explicit-end' | 'commit-cleanup' | 'stale-timeout' | 'backfill'
);

CREATE INDEX IF NOT EXISTS idx_vcs_sessions_active
    ON vcs_sessions(ended_at) WHERE ended_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_vcs_sessions_name
    ON vcs_sessions(name);

-- SQLite ALTER TABLE ADD COLUMN can't add a REFERENCES constraint on an
-- existing table without a table rebuild, and this project doesn't rely
-- on SQLite FK enforcement anywhere else in the schema. Integrity is
-- maintained in service code (VCSService.get_or_create_session and the
-- commit path); a future migration can promote to a real FK via rebuild
-- if we ever turn PRAGMA foreign_keys = ON.
ALTER TABLE vcs_working_state ADD COLUMN staged_by_session_id INTEGER;

CREATE INDEX IF NOT EXISTS idx_vcs_working_state_staged_session
    ON vcs_working_state(staged_by_session_id)
    WHERE staged_by_session_id IS NOT NULL;

-- Backfill: any existing staged=1 row gets attributed to a synthetic
-- 'legacy-backfill' session, so history isn't silently reattributed.
INSERT INTO vcs_sessions (name, author, started_at, ended_at, ended_reason)
    VALUES ('legacy-backfill', 'unknown',
            datetime('now'), datetime('now'), 'backfill');

UPDATE vcs_working_state
    SET staged_by_session_id = (
        SELECT id FROM vcs_sessions
        WHERE name = 'legacy-backfill'
        ORDER BY id DESC LIMIT 1
    )
    WHERE staged = 1;

-- vcs_staging was already dropped from live DBs by archived migration 011,
-- but migrations/database_vcs_schema.sql still defines it, so fresh installs
-- recreate a dead table. Drop it here to normalize both cases.
DROP TABLE IF EXISTS vcs_staging;
