-- TempleDB Agent Session Management Schema
-- Tracks AI agent sessions, interactions, and their relationship to commits

-- Main agent sessions table
CREATE TABLE IF NOT EXISTS agent_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_uuid TEXT UNIQUE NOT NULL,
    project_id INTEGER,
    agent_type TEXT NOT NULL,  -- 'claude', 'cursor', 'copilot', 'custom', 'human'
    agent_version TEXT,        -- e.g., 'claude-sonnet-4-5-20250929'
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    initial_context TEXT,      -- Initial prompt/instructions given to agent
    session_goal TEXT,         -- High-level goal of the session
    status TEXT DEFAULT 'active', -- 'active', 'completed', 'aborted', 'error'
    metadata TEXT,             -- JSON for additional session info
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- Individual interactions within a session
CREATE TABLE IF NOT EXISTS agent_interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    interaction_type TEXT NOT NULL, -- 'user_message', 'agent_response', 'tool_call', 'file_read', 'file_write', 'command_execution'
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    content TEXT,              -- The actual message, command, or data
    metadata TEXT,             -- JSON for additional context (tool results, errors, etc.)
    FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
);

-- Links agent sessions to the commits they produced
CREATE TABLE IF NOT EXISTS agent_session_commits (
    session_id INTEGER NOT NULL,
    commit_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_primary BOOLEAN DEFAULT 1, -- Main commit vs. secondary/cleanup commit
    PRIMARY KEY (session_id, commit_id),
    FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (commit_id) REFERENCES vcs_commits(id) ON DELETE CASCADE
);

-- Tracks context snapshots provided to agents
CREATE TABLE IF NOT EXISTS agent_context_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    snapshot_type TEXT NOT NULL, -- 'initial', 'update', 'refresh'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    context_data TEXT NOT NULL,  -- JSON containing the context provided
    file_count INTEGER,
    token_estimate INTEGER,
    FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
);

-- Tracks performance metrics for agent sessions
CREATE TABLE IF NOT EXISTS agent_session_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    metric_type TEXT NOT NULL,   -- 'tokens_used', 'files_modified', 'commands_run', 'duration_seconds'
    metric_value REAL NOT NULL,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    metadata TEXT,               -- JSON for additional metric context
    FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_agent_sessions_project ON agent_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_status ON agent_sessions(status);
CREATE INDEX IF NOT EXISTS idx_agent_sessions_started ON agent_sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_agent_interactions_session ON agent_interactions(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_interactions_timestamp ON agent_interactions(timestamp);
CREATE INDEX IF NOT EXISTS idx_agent_session_commits_session ON agent_session_commits(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_session_commits_commit ON agent_session_commits(commit_id);
CREATE INDEX IF NOT EXISTS idx_agent_context_snapshots_session ON agent_context_snapshots(session_id);
CREATE INDEX IF NOT EXISTS idx_agent_session_metrics_session ON agent_session_metrics(session_id);
