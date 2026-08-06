-- Temple Agent: pending asks table for MCP bridge
-- The MCP tool (templedb_ask_user / templedb_message_user) inserts here from
-- one process; the agent service polls this table in another process and
-- forwards to Emacs as an event; Emacs replies via protocol; the response
-- lands back in this table and the MCP tool sees it.

CREATE TABLE IF NOT EXISTS agent_pending_asks (
    ask_id TEXT PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES agent_sessions(id),
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    response TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    responded_at TEXT,
    dispatched_at TEXT
);

CREATE INDEX IF NOT EXISTS agent_pending_asks_session_status
    ON agent_pending_asks(session_id, status);
