-- Migration 019: Add Interactive Agent Mode Support
-- Adds schema for real-time agent session monitoring, interactive chat,
-- and inflection point prompting (Claude Code-style interaction)

-- Add columns to agent_interactions for user input prompts
ALTER TABLE agent_interactions ADD COLUMN requires_input BOOLEAN DEFAULT 0;
ALTER TABLE agent_interactions ADD COLUMN input_prompt TEXT;
ALTER TABLE agent_interactions ADD COLUMN input_options TEXT; -- JSON array of options
ALTER TABLE agent_interactions ADD COLUMN user_response TEXT; -- User's response to prompt

-- Create agent_session_state table for real-time session tracking
CREATE TABLE IF NOT EXISTS agent_session_state (
    session_id INTEGER PRIMARY KEY,
    current_activity TEXT,              -- What the agent is currently doing
    activity_type TEXT,                 -- 'thinking', 'tool_use', 'waiting_input', 'idle'
    waiting_for_input BOOLEAN DEFAULT 0,
    last_heartbeat TEXT DEFAULT (datetime('now')),
    last_interaction_id INTEGER,        -- Reference to most recent interaction
    progress_indicator TEXT,            -- Optional progress message

    FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (last_interaction_id) REFERENCES agent_interactions(id) ON DELETE SET NULL
);

-- Create index for quick session state lookups
CREATE INDEX IF NOT EXISTS idx_session_state_waiting
    ON agent_session_state(waiting_for_input, last_heartbeat);

-- Create agent_session_watchers table to track who's watching sessions
CREATE TABLE IF NOT EXISTS agent_session_watchers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    watcher_pid INTEGER,                -- Process ID of watching terminal
    watcher_terminal TEXT,              -- TTY of watcher
    started_watching TEXT DEFAULT (datetime('now')),
    last_poll TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE
);

-- Create index for watcher cleanup
CREATE INDEX IF NOT EXISTS idx_watchers_session
    ON agent_session_watchers(session_id, last_poll);

-- Add interaction types for interactive mode
-- (These use the existing agent_interactions.interaction_type column)
-- New types: 'user_message', 'user_decision', 'inflection_point',
--            'activity_update', 'prompt_user'

-- Create view for active sessions with watchers
CREATE VIEW IF NOT EXISTS active_sessions_with_watchers AS
SELECT
    s.id,
    s.session_uuid,
    s.project_id,
    s.agent_type,
    s.agent_version,
    s.status,
    s.started_at,
    s.session_goal,
    ss.current_activity,
    ss.activity_type,
    ss.waiting_for_input,
    ss.last_heartbeat,
    COUNT(w.id) as watcher_count
FROM agent_sessions s
LEFT JOIN agent_session_state ss ON s.id = ss.session_id
LEFT JOIN agent_session_watchers w ON s.id = w.session_id
WHERE s.status = 'active'
GROUP BY s.id;

-- Create trigger to initialize session state when session is created
CREATE TRIGGER IF NOT EXISTS init_session_state_on_create
AFTER INSERT ON agent_sessions
BEGIN
    INSERT INTO agent_session_state (
        session_id,
        current_activity,
        activity_type,
        waiting_for_input
    ) VALUES (
        NEW.id,
        'Initializing session',
        'idle',
        0
    );
END;

-- Create trigger to update last_heartbeat on new interactions
CREATE TRIGGER IF NOT EXISTS update_heartbeat_on_interaction
AFTER INSERT ON agent_interactions
WHEN NEW.session_id IS NOT NULL
BEGIN
    UPDATE agent_session_state
    SET
        last_heartbeat = datetime('now'),
        last_interaction_id = NEW.id,
        current_activity = CASE
            WHEN NEW.interaction_type = 'tool_use' THEN 'Using tool: ' || substr(NEW.content, 1, 50)
            WHEN NEW.interaction_type = 'prompt_user' THEN 'Waiting for user input'
            WHEN NEW.interaction_type = 'user_message' THEN 'Processing user message'
            ELSE NEW.interaction_type
        END,
        activity_type = CASE
            WHEN NEW.interaction_type = 'prompt_user' THEN 'waiting_input'
            WHEN NEW.interaction_type = 'tool_use' THEN 'tool_use'
            ELSE 'thinking'
        END,
        waiting_for_input = CASE
            WHEN NEW.requires_input = 1 THEN 1
            ELSE 0
        END
    WHERE session_id = NEW.session_id;
END;

-- Create trigger to clean up session state when session ends
CREATE TRIGGER IF NOT EXISTS cleanup_session_state_on_end
AFTER UPDATE OF status ON agent_sessions
WHEN NEW.status != 'active' AND OLD.status = 'active'
BEGIN
    UPDATE agent_session_state
    SET
        current_activity = 'Session ended',
        activity_type = 'idle',
        waiting_for_input = 0,
        last_heartbeat = datetime('now')
    WHERE session_id = NEW.id;

    -- Remove watchers
    DELETE FROM agent_session_watchers
    WHERE session_id = NEW.id;
END;

-- Add metadata column to agent_sessions for interactive mode settings
-- (Check if column exists first - SQLite doesn't have IF NOT EXISTS for ALTER COLUMN)
-- This will be handled in Python code to check before altering

-- Migration complete
-- Run: python3 -m migration.runner apply 019
