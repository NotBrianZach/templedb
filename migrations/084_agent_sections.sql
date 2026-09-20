-- Temple Agent: persistent state for agent-writable sections
-- (Findings / Todo / Open Questions / dynamic sections) + a generic
-- pending-events transport for one-way MCP-tool → Emacs notifications.
--
-- Persistence contract mirrors agent_session_notes: one row per
-- (session, section, entry_id), JSON blob for the entry fields.
-- Load path returned by session.open alongside notes.

CREATE TABLE IF NOT EXISTS agent_session_sections (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES agent_sessions(id),
    -- Section id as seen by Emacs. One of:
    --   'findings' | 'todo' | 'open-questions'
    --   'dynamic:NAME' for agent-created dynamic sections
    section TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    -- Full entry as JSON dict. Shape depends on section:
    --   findings:       {text, refs?}
    --   todo:           {text, priority?, done?}
    --   open-questions: {text, answered?, answer?}
    --   dynamic:*:      {text}
    entry_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, section, entry_id)
);

CREATE INDEX IF NOT EXISTS agent_session_sections_by_session
    ON agent_session_sections(session_id);

-- Generic outbound-event transport. MCP tools (out-of-process) can't
-- write directly to Emacs's stdio; they insert into this table, and
-- the agent service's poll loop forwards each row to the active
-- agent stdio connection as a JSON event.

CREATE TABLE IF NOT EXISTS agent_pending_events (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES agent_sessions(id),
    event_type TEXT NOT NULL,     -- e.g. 'agent.section.finding.add'
    payload_json TEXT NOT NULL,   -- JSON dict, becomes event.data
    summary TEXT,                 -- optional short summary line
    dispatched_at TEXT,           -- NULL until forwarded to Emacs
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS agent_pending_events_undispatched
    ON agent_pending_events(session_id, dispatched_at)
    WHERE dispatched_at IS NULL;
