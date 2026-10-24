-- 141_projects_fk_set_null.sql
--
-- Make `project rm` possible in the SCHEMA, not just in the one caller
-- that works around it.
--
-- 47 foreign keys point at `projects`. 42 carry ON DELETE CASCADE and
-- `nix_generations` carries SET NULL. Four carried NO ACTION:
--
--     agent_sessions.project_id      342 rows
--     agent_work_log.project_id      882 rows
--     handoff_notes.project_id        22 rows
--     prompt_usage_log.project_id      0 rows
--
-- `apply_standard_pragmas` sets foreign_keys=ON, so one row in any of
-- them aborted `DELETE FROM projects` with a bare FOREIGN KEY
-- constraint failed. Those are agent-activity tables, so in practice
-- every project an agent had ever touched was undeletable -- 9 of 25
-- when this was written, `templedb` and `bza` among them.
--
-- BE5BA021 fixed it in ProjectRepository.delete, which nulls these
-- references before deleting. That works and is tested, and it fixes
-- exactly one caller: the GUI's handoffs page, the MCP layer, a future
-- migration and anyone's psql-equivalent session all still hit the
-- constraint. The schema is where this belongs.
--
-- SET NULL AND NOT CASCADE, which is the substantive choice. An agent
-- session that worked on a since-removed project is still a true record
-- of work; the row should outlive the project, detached.
-- `nix_generations.project_id` already says exactly this by declaring
-- SET NULL, so this migration makes four columns agree with the one
-- that got it right rather than inventing a policy. NO ACTION was never
-- a decision to keep the history -- there is no reading of "keep this"
-- that also means "and make the project undeletable".
--
-- WHY A TABLE REBUILD. SQLite has no ALTER TABLE ... ALTER CONSTRAINT,
-- and ON DELETE lives inside the column definition, so the only way to
-- change it is to replace the table. This is the documented 12-step
-- procedure.
--
-- The cost was initially overstated, in a claim worth correcting
-- because it is the reason this migration was deferred: "on tables
-- cr-sqlite tracks". It does not track them. cr-sqlite's 24 triggers
-- and 8 shadow clocks are all on the `sync_*` tables; these four carry
-- ZERO triggers between them, so the step that recreates triggers is
-- vacuous and there is no CRDT state to re-register. Measured
-- 2026-10-23: 1,246 rows, 10 indexes (9 explicit, 1 implicit from
-- agent_sessions' UNIQUE), one view, no triggers.
--
-- ORDER. Easiest first, so the procedure is proven on a table with
-- nothing to lose before it reaches one with something:
--
--   1. prompt_usage_log   empty; DROP + CREATE, no copy (as 072 did)
--   2. handoff_notes      22 rows, 4 indexes, nothing references it
--   3. agent_work_log     882 rows, 3 indexes, nothing references it
--   4. agent_sessions     342 rows, NINE tables reference it
--
-- agent_sessions is the only one with inbound references:
-- agent_messages, agent_notifications, agent_pending_asks,
-- agent_pending_events, agent_runs, agent_session_notes,
-- agent_session_sections, agent_user_edits and agent_work_log all
-- declare REFERENCES agent_sessions(id). `id` is copied explicitly in
-- every INSERT below, so those references still resolve afterwards --
-- that is what makes the swap safe, and `PRAGMA foreign_key_check` at
-- the end is what proves it rather than assuming it.
--
-- THE PRAGMA. The 12-step procedure requires foreign_keys=OFF: with it
-- ON, `DROP TABLE agent_sessions` would itself fire the nine inbound
-- constraints. The migrator's connection has it ON
-- (apply_standard_pragmas), and a PRAGMA is a no-op inside a
-- transaction -- `executescript` commits before running, so the
-- statement below does take effect. It is turned back ON at the end,
-- because the connection is reused for every later migration and
-- leaving it off would silently disarm FK enforcement for the rest of
-- the run.
--
-- This is also the one operation the new `foreign_keys_hold` invariant
-- cannot protect during, only after -- which is why there is an
-- explicit foreign_key_check here, before the pragma goes back on.

PRAGMA foreign_keys=OFF;

-- ---------------------------------------------------------------------
-- 1. prompt_usage_log -- empty, so no copy. Its view goes first.
-- ---------------------------------------------------------------------

DROP VIEW IF EXISTS prompt_usage_summary_view;
DROP TABLE IF EXISTS prompt_usage_log;

CREATE TABLE prompt_usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_type TEXT NOT NULL,
    prompt_id INTEGER NOT NULL,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    used_by TEXT,
    usage_context TEXT,
    rendered_prompt TEXT,
    variables_used TEXT,
    used_at TEXT DEFAULT (datetime('now'))
);

CREATE VIEW prompt_usage_summary_view AS
SELECT
    prompt_type,
    prompt_id,
    COUNT(*) as usage_count,
    COUNT(DISTINCT used_by) as unique_users,
    COUNT(DISTINCT project_id) as projects_used_in,
    MIN(used_at) as first_used,
    MAX(used_at) as last_used
FROM prompt_usage_log
GROUP BY prompt_type, prompt_id;

-- ---------------------------------------------------------------------
-- 2. handoff_notes -- 22 rows, 4 indexes, no inbound references.
-- ---------------------------------------------------------------------

CREATE TABLE handoff_notes_new (
    id              INTEGER PRIMARY KEY,

    -- Sender identity. from_session is TEMPLEDB_SESSION_ID or a
    -- fallback derived from (host, ppid) if the env var isn't set.
    from_session    TEXT NOT NULL,
    from_actor      TEXT,   -- 'claude-code', 'vibe', 'human', 'temple-agent'

    -- Destination. Exactly one of to_session / to_topic / (both NULL
    -- = broadcast) is typical. Convention, not enforced, so a note
    -- can address both a session AND a topic if useful.
    to_session      TEXT,
    to_topic        TEXT,   -- 'templedb', 'refactor:foo', ...

    -- Content
    subject         TEXT NOT NULL,
    body            TEXT NOT NULL,
    tags            TEXT,   -- comma-separated

    -- Cross-references into other authoritative objects
    ref_report      TEXT,   -- reports/YYYY-MM-DD-HHMM-slug.html
    ref_commit      TEXT,   -- commit hash prefix or full
    ref_file        TEXT,   -- project_slug:path
    project_id      INTEGER REFERENCES projects(id) ON DELETE SET NULL,

    -- Lifecycle
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    read_at         TEXT,
    acked_at        TEXT,
    expires_at      TEXT
);

INSERT INTO handoff_notes_new
    (id, from_session, from_actor, to_session, to_topic, subject, body,
     tags, ref_report, ref_commit, ref_file, project_id, created_at,
     read_at, acked_at, expires_at)
SELECT
     id, from_session, from_actor, to_session, to_topic, subject, body,
     tags, ref_report, ref_commit, ref_file, project_id, created_at,
     read_at, acked_at, expires_at
  FROM handoff_notes;

DROP TABLE handoff_notes;
ALTER TABLE handoff_notes_new RENAME TO handoff_notes;

CREATE INDEX idx_handoff_notes_to_session
    ON handoff_notes(to_session, acked_at);
CREATE INDEX idx_handoff_notes_to_topic
    ON handoff_notes(to_topic, acked_at);
CREATE INDEX idx_handoff_notes_project
    ON handoff_notes(project_id);
CREATE INDEX idx_handoff_notes_broadcast
    ON handoff_notes(created_at DESC)
    WHERE to_session IS NULL AND to_topic IS NULL;

-- ---------------------------------------------------------------------
-- 3. agent_work_log -- 882 rows, 3 indexes, no inbound references.
-- ---------------------------------------------------------------------

CREATE TABLE agent_work_log_new (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES agent_sessions(id),
    run_id INTEGER REFERENCES agent_runs(id),
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    -- What was asked
    user_message TEXT,
    -- What was done
    summary TEXT,
    tools_used TEXT,           -- JSON array of tool names
    files_read TEXT,           -- JSON array of file paths
    files_modified TEXT,       -- JSON array of file paths
    commands_run TEXT,         -- JSON array of bash commands
    -- Outcome
    assistant_response_preview TEXT,  -- first 500 chars of response
    status TEXT NOT NULL DEFAULT 'completed',  -- completed, failed, cancelled
    -- Stats
    cost_usd REAL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    duration_ms INTEGER,
    num_turns INTEGER,
    -- Timestamps
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO agent_work_log_new
    (id, session_id, run_id, project_id, user_message, summary,
     tools_used, files_read, files_modified, commands_run,
     assistant_response_preview, status, cost_usd, input_tokens,
     output_tokens, duration_ms, num_turns, created_at)
SELECT
     id, session_id, run_id, project_id, user_message, summary,
     tools_used, files_read, files_modified, commands_run,
     assistant_response_preview, status, cost_usd, input_tokens,
     output_tokens, duration_ms, num_turns, created_at
  FROM agent_work_log;

DROP TABLE agent_work_log;
ALTER TABLE agent_work_log_new RENAME TO agent_work_log;

CREATE INDEX idx_agent_work_log_session ON agent_work_log(session_id);
CREATE INDEX idx_agent_work_log_project ON agent_work_log(project_id);
CREATE INDEX idx_agent_work_log_created ON agent_work_log(created_at);

-- ---------------------------------------------------------------------
-- 4. agent_sessions -- 342 rows, and the one with inbound references.
--
-- `id` is copied explicitly, so the nine tables that reference it keep
-- resolving. The UNIQUE on session_uuid is in the CREATE, so its
-- implicit index comes back without being named.
-- ---------------------------------------------------------------------

CREATE TABLE agent_sessions_new (
    id INTEGER PRIMARY KEY,
    session_uuid TEXT NOT NULL UNIQUE,
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    provider_id INTEGER NOT NULL REFERENCES agent_providers(id),
    external_session_id TEXT,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'created',
    model TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

INSERT INTO agent_sessions_new
    (id, session_uuid, project_id, provider_id, external_session_id,
     title, status, model, created_at, updated_at)
SELECT
     id, session_uuid, project_id, provider_id, external_session_id,
     title, status, model, created_at, updated_at
  FROM agent_sessions;

DROP TABLE agent_sessions;
ALTER TABLE agent_sessions_new RENAME TO agent_sessions;

CREATE INDEX idx_agent_sessions_project ON agent_sessions(project_id);
CREATE INDEX idx_agent_sessions_status ON agent_sessions(status);

-- ---------------------------------------------------------------------
-- Step 10 of the procedure, and the reason the pragma can go back on.
-- Reports any row left pointing at nothing; the migrator runs this
-- script in one executescript and rolls back on error, so a violation
-- here does not get committed.
-- ---------------------------------------------------------------------

PRAGMA foreign_key_check;

PRAGMA foreign_keys=ON;
