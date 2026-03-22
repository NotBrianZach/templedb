-- Migration 029: Vibe Coding Real-Time Sessions
-- Enhances vibe coding with real-time browser-based quiz interface

-- Add session tracking for active vibe coding sessions
ALTER TABLE quiz_sessions ADD COLUMN session_token TEXT;
ALTER TABLE quiz_sessions ADD COLUMN browser_url TEXT;
ALTER TABLE quiz_sessions ADD COLUMN claude_pid INTEGER;
ALTER TABLE quiz_sessions ADD COLUMN auto_generate BOOLEAN DEFAULT 1;

-- Create index for session_token uniqueness
CREATE UNIQUE INDEX IF NOT EXISTS idx_quiz_sessions_token ON quiz_sessions(session_token) WHERE session_token IS NOT NULL;

-- Track live changes during vibe session
CREATE TABLE IF NOT EXISTS vibe_session_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,

    -- Change tracking
    file_path TEXT NOT NULL,
    change_type TEXT NOT NULL,              -- 'edit', 'create', 'delete'
    diff_content TEXT,

    -- Question generation
    questions_generated INTEGER DEFAULT 0,
    questions_answered INTEGER DEFAULT 0,

    -- Timestamps
    changed_at TEXT DEFAULT (datetime('now')),

    -- Metadata
    commit_hash TEXT,                        -- If committed
    claude_interaction_id TEXT               -- Link to Claude interaction if available
);

-- Real-time question queue (questions waiting to be shown)
CREATE TABLE IF NOT EXISTS vibe_question_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,

    -- Queue management
    queue_position INTEGER NOT NULL,
    priority TEXT DEFAULT 'normal',          -- high, normal, low
    status TEXT DEFAULT 'pending',           -- pending, shown, answered, skipped

    -- Presentation
    shown_at TEXT,
    answered_at TEXT,
    time_in_queue_seconds INTEGER,

    -- Context for when to show
    trigger_type TEXT,                       -- 'on_change', 'on_commit', 'periodic', 'manual'
    related_change_id INTEGER REFERENCES vibe_session_changes(id),

    UNIQUE(session_id, question_id)
);

-- Session events for debugging and replay
CREATE TABLE IF NOT EXISTS vibe_session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,

    -- Event details
    event_type TEXT NOT NULL,                -- 'started', 'change', 'question_generated',
                                             -- 'question_shown', 'question_answered',
                                             -- 'claude_response', 'committed', 'ended'
    event_data TEXT,                         -- JSON

    -- Timestamp
    occurred_at TEXT DEFAULT (datetime('now'))
);

-- Browser session tracking (for reconnection)
CREATE TABLE IF NOT EXISTS vibe_browser_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,

    -- Browser info
    session_token TEXT NOT NULL UNIQUE,
    user_agent TEXT,
    ip_address TEXT,

    -- Connection tracking
    connected_at TEXT DEFAULT (datetime('now')),
    last_heartbeat_at TEXT DEFAULT (datetime('now')),
    disconnected_at TEXT,

    -- State
    current_question_id INTEGER REFERENCES quiz_questions(id),
    questions_shown INTEGER DEFAULT 0,
    questions_answered INTEGER DEFAULT 0
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_vibe_changes_session ON vibe_session_changes(session_id);
CREATE INDEX IF NOT EXISTS idx_vibe_changes_file ON vibe_session_changes(file_path);
CREATE INDEX IF NOT EXISTS idx_vibe_changes_time ON vibe_session_changes(changed_at);

CREATE INDEX IF NOT EXISTS idx_vibe_queue_session ON vibe_question_queue(session_id);
CREATE INDEX IF NOT EXISTS idx_vibe_queue_status ON vibe_question_queue(status);
CREATE INDEX IF NOT EXISTS idx_vibe_queue_position ON vibe_question_queue(session_id, queue_position);

CREATE INDEX IF NOT EXISTS idx_vibe_events_session ON vibe_session_events(session_id);
CREATE INDEX IF NOT EXISTS idx_vibe_events_type ON vibe_session_events(event_type);
CREATE INDEX IF NOT EXISTS idx_vibe_events_time ON vibe_session_events(occurred_at);

CREATE INDEX IF NOT EXISTS idx_vibe_browser_token ON vibe_browser_sessions(session_token);
CREATE INDEX IF NOT EXISTS idx_vibe_browser_session ON vibe_browser_sessions(session_id);

-- Views

-- Active vibe sessions with browser status
CREATE VIEW IF NOT EXISTS active_vibe_sessions_view AS
SELECT
    qs.id,
    qs.session_name,
    qs.session_token,
    qs.browser_url,
    qs.claude_pid,
    p.slug as project_slug,
    COUNT(DISTINCT vsc.id) as total_changes,
    COUNT(DISTINCT vqq.id) as queued_questions,
    COUNT(DISTINCT vqq.id) FILTER (WHERE vqq.status = 'answered') as answered_questions,
    MAX(vbs.last_heartbeat_at) as last_browser_heartbeat,
    qs.started_at,
    qs.status
FROM quiz_sessions qs
JOIN projects p ON qs.project_id = p.id
LEFT JOIN vibe_session_changes vsc ON vsc.session_id = qs.id
LEFT JOIN vibe_question_queue vqq ON vqq.session_id = qs.id
LEFT JOIN vibe_browser_sessions vbs ON vbs.session_id = qs.id
WHERE qs.status IN ('pending', 'in_progress')
  AND qs.session_type = 'vibe-realtime'
GROUP BY qs.id;

-- Question queue for browser to poll
CREATE VIEW IF NOT EXISTS vibe_question_queue_view AS
SELECT
    vqq.id as queue_id,
    vqq.session_id,
    qq.id as question_id,
    qq.question_text,
    qq.question_type,
    qq.code_snippet,
    qq.related_file_path,
    qq.options,
    qq.difficulty,
    qq.category,
    qq.learning_objective,
    qq.points,
    vqq.queue_position,
    vqq.priority,
    vqq.status,
    vqq.trigger_type,
    vsc.file_path as related_change_file,
    vsc.diff_content as related_change_diff
FROM vibe_question_queue vqq
JOIN quiz_questions qq ON vqq.question_id = qq.id
LEFT JOIN vibe_session_changes vsc ON vqq.related_change_id = vsc.id
WHERE vqq.status IN ('pending', 'shown')
ORDER BY vqq.priority DESC, vqq.queue_position ASC;

-- Session timeline for replay
CREATE VIEW IF NOT EXISTS vibe_session_timeline_view AS
SELECT
    vse.id,
    vse.session_id,
    qs.session_name,
    vse.event_type,
    vse.event_data,
    vse.occurred_at,
    CAST((julianday(vse.occurred_at) - julianday(qs.started_at)) * 24 * 60 AS INTEGER) as minutes_since_start
FROM vibe_session_events vse
JOIN quiz_sessions qs ON vse.session_id = qs.id
ORDER BY vse.occurred_at DESC;

-- Migration complete
-- Run: ./templedb migration apply 029
