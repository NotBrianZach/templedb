-- Temple Agent: native AI agent infrastructure
-- Tables for agent sessions, runs, messages, events, and providers

CREATE TABLE IF NOT EXISTS agent_providers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    provider_kind TEXT NOT NULL,
    executable TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    config_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    id INTEGER PRIMARY KEY,
    session_uuid TEXT NOT NULL UNIQUE,
    project_id INTEGER REFERENCES projects(id),
    provider_id INTEGER NOT NULL REFERENCES agent_providers(id),
    external_session_id TEXT,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'created',
    model TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES agent_sessions(id),
    status TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    last_event_sequence INTEGER NOT NULL DEFAULT 0,
    error_text TEXT
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES agent_sessions(id),
    run_id INTEGER REFERENCES agent_runs(id),
    sequence_number INTEGER NOT NULL,
    role TEXT NOT NULL,
    content_text TEXT NOT NULL DEFAULT '',
    content_format TEXT NOT NULL DEFAULT 'org',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, sequence_number)
);

CREATE TABLE IF NOT EXISTS agent_events (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES agent_runs(id),
    sequence_number INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    summary TEXT,
    payload_json TEXT,
    raw_payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(run_id, sequence_number)
);

CREATE TABLE IF NOT EXISTS agent_session_notes (
    session_id INTEGER PRIMARY KEY REFERENCES agent_sessions(id),
    goal_org TEXT,
    notes_org TEXT,
    scratch_org TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_agent_sessions_project ON agent_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_status ON agent_sessions(status);
CREATE INDEX IF NOT EXISTS idx_agent_runs_session ON agent_runs(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_messages_session ON agent_messages(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_events_run ON agent_events(run_id);
CREATE INDEX IF NOT EXISTS idx_agent_events_type ON agent_events(event_type);

-- Seed default providers
INSERT OR IGNORE INTO agent_providers (name, provider_kind, executable, enabled)
VALUES ('fake', 'fake', NULL, 1);

INSERT OR IGNORE INTO agent_providers (name, provider_kind, executable, enabled)
VALUES ('claude-code', 'claude_code', 'claude', 1);
