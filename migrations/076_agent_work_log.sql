-- Agent work log: automatic audit trail for agent sessions
-- Each completed run generates a structured log entry

CREATE TABLE IF NOT EXISTS agent_work_log (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES agent_sessions(id),
    run_id INTEGER REFERENCES agent_runs(id),
    project_id INTEGER REFERENCES projects(id),
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

CREATE INDEX IF NOT EXISTS idx_agent_work_log_session ON agent_work_log(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_work_log_project ON agent_work_log(project_id);
CREATE INDEX IF NOT EXISTS idx_agent_work_log_created ON agent_work_log(created_at);
