-- Migration 028: Add Vibe Coding Quiz System
-- Interactive quizzes to test developer understanding of AI-generated code changes

-- Quiz sessions track when a developer reviews changes
CREATE TABLE IF NOT EXISTS quiz_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Context
    session_name TEXT NOT NULL,              -- e.g., "Post-commit review: Fix auth bug"
    session_type TEXT DEFAULT 'commit',      -- commit, work-item, feature, general
    related_commit_id INTEGER REFERENCES vcs_commits(id),
    related_work_item_id TEXT REFERENCES work_items(id),

    -- Metadata
    generated_by TEXT,                       -- AI agent identifier
    reviewed_by TEXT,                        -- Developer identifier
    difficulty_level TEXT DEFAULT 'medium',  -- easy, medium, hard, expert

    -- Status
    status TEXT NOT NULL DEFAULT 'pending',  -- pending, in_progress, completed, abandoned
    score REAL,                              -- Overall score (0.0-1.0)

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),
    started_at TEXT,
    completed_at TEXT,

    -- Config
    show_answers_immediately BOOLEAN DEFAULT 0,  -- Show answers after each question
    shuffle_questions BOOLEAN DEFAULT 0,
    time_limit_seconds INTEGER,

    -- Metadata
    tags TEXT,                               -- JSON array
    metadata TEXT                            -- JSON for extensibility
);

-- Individual quiz questions
CREATE TABLE IF NOT EXISTS quiz_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,

    -- Question content
    question_text TEXT NOT NULL,
    question_type TEXT NOT NULL DEFAULT 'multiple_choice',  -- multiple_choice, true_false, short_answer, code_snippet
    sequence_order INTEGER NOT NULL,         -- Order in quiz

    -- Context (what code/change this relates to)
    related_file_path TEXT,
    related_commit_hash TEXT,
    code_snippet TEXT,                       -- The relevant code snippet
    line_range TEXT,                         -- JSON: {"start": 10, "end": 25}

    -- Answer data
    correct_answer TEXT NOT NULL,            -- JSON based on question_type
    options TEXT,                            -- JSON array for multiple choice
    explanation TEXT,                        -- Why this is the answer

    -- Difficulty & categorization
    difficulty TEXT DEFAULT 'medium',        -- easy, medium, hard
    category TEXT,                           -- architecture, logic, security, performance, style
    points INTEGER DEFAULT 1,

    -- Learning objectives
    learning_objective TEXT,                 -- What should dev understand from this?
    related_concepts TEXT,                   -- JSON array of concepts

    -- Metadata
    tags TEXT,                               -- JSON array
    hints TEXT,                              -- JSON array of progressive hints
    reference_links TEXT                     -- JSON array of doc links
);

-- Developer responses to questions
CREATE TABLE IF NOT EXISTS quiz_responses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL REFERENCES quiz_questions(id) ON DELETE CASCADE,

    -- Response
    answer_given TEXT NOT NULL,              -- Developer's answer (JSON)
    is_correct BOOLEAN,
    time_taken_seconds INTEGER,

    -- Context
    attempt_number INTEGER DEFAULT 1,        -- Allow retries
    hints_used INTEGER DEFAULT 0,

    -- Timestamps
    answered_at TEXT DEFAULT (datetime('now')),

    -- Feedback
    feedback_text TEXT,                      -- AI-generated feedback
    self_confidence INTEGER,                 -- Developer's self-reported confidence (1-5)

    UNIQUE(session_id, question_id, attempt_number)
);

-- Quiz templates for common patterns
CREATE TABLE IF NOT EXISTS quiz_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    category TEXT,                           -- commit-review, feature-understanding, architecture-check

    -- Template questions (JSON array of question templates)
    question_templates TEXT NOT NULL,

    -- Config
    default_difficulty TEXT DEFAULT 'medium',
    recommended_time_limit INTEGER,

    -- Metadata
    tags TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    created_by TEXT,
    usage_count INTEGER DEFAULT 0
);

-- Track learning progress over time
CREATE TABLE IF NOT EXISTS learning_progress (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    developer_id TEXT NOT NULL,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,

    -- Aggregated stats
    total_quizzes INTEGER DEFAULT 0,
    total_questions INTEGER DEFAULT 0,
    total_correct INTEGER DEFAULT 0,
    average_score REAL,

    -- By category
    category_stats TEXT,                     -- JSON: {"architecture": {"correct": 5, "total": 8}, ...}

    -- Strengths and weaknesses
    strong_concepts TEXT,                    -- JSON array
    weak_concepts TEXT,                      -- JSON array

    -- Timestamps
    first_quiz_at TEXT,
    last_quiz_at TEXT,
    updated_at TEXT DEFAULT (datetime('now')),

    UNIQUE(developer_id, project_id)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_quiz_sessions_project ON quiz_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_quiz_sessions_status ON quiz_sessions(status);
CREATE INDEX IF NOT EXISTS idx_quiz_sessions_commit ON quiz_sessions(related_commit_id);
CREATE INDEX IF NOT EXISTS idx_quiz_sessions_work_item ON quiz_sessions(related_work_item_id);

CREATE INDEX IF NOT EXISTS idx_quiz_questions_session ON quiz_questions(session_id);
CREATE INDEX IF NOT EXISTS idx_quiz_questions_category ON quiz_questions(category);
CREATE INDEX IF NOT EXISTS idx_quiz_questions_order ON quiz_questions(session_id, sequence_order);

CREATE INDEX IF NOT EXISTS idx_quiz_responses_session ON quiz_responses(session_id);
CREATE INDEX IF NOT EXISTS idx_quiz_responses_question ON quiz_responses(question_id);
CREATE INDEX IF NOT EXISTS idx_quiz_responses_correct ON quiz_responses(is_correct);

CREATE INDEX IF NOT EXISTS idx_learning_progress_developer ON learning_progress(developer_id);
CREATE INDEX IF NOT EXISTS idx_learning_progress_project ON learning_progress(project_id);

-- Views

-- Active quiz sessions
CREATE VIEW IF NOT EXISTS active_quiz_sessions_view AS
SELECT
    qs.id,
    qs.session_name,
    qs.session_type,
    qs.status,
    p.slug as project_slug,
    p.name as project_name,
    qs.generated_by,
    qs.reviewed_by,
    qs.difficulty_level,
    qs.score,
    COUNT(qq.id) as total_questions,
    COUNT(qr.id) as answered_questions,
    qs.created_at,
    qs.started_at
FROM quiz_sessions qs
JOIN projects p ON qs.project_id = p.id
LEFT JOIN quiz_questions qq ON qq.session_id = qs.id
LEFT JOIN quiz_responses qr ON qr.session_id = qs.id
WHERE qs.status IN ('pending', 'in_progress')
GROUP BY qs.id;

-- Quiz results summary
CREATE VIEW IF NOT EXISTS quiz_results_view AS
SELECT
    qs.id as session_id,
    qs.session_name,
    p.slug as project_slug,
    qs.reviewed_by,
    qs.difficulty_level,
    COUNT(qq.id) as total_questions,
    COUNT(qr.id) as answered_questions,
    SUM(CASE WHEN qr.is_correct = 1 THEN 1 ELSE 0 END) as correct_answers,
    AVG(CASE WHEN qr.is_correct = 1 THEN 1.0 ELSE 0.0 END) as accuracy,
    AVG(qr.time_taken_seconds) as avg_time_per_question,
    qs.completed_at
FROM quiz_sessions qs
JOIN projects p ON qs.project_id = p.id
LEFT JOIN quiz_questions qq ON qq.session_id = qs.id
LEFT JOIN quiz_responses qr ON qr.session_id = qs.id AND qr.attempt_number = 1
WHERE qs.status = 'completed'
GROUP BY qs.id;

-- Questions with their responses
CREATE VIEW IF NOT EXISTS quiz_questions_with_responses_view AS
SELECT
    qq.id as question_id,
    qq.session_id,
    qs.session_name,
    qq.question_text,
    qq.question_type,
    qq.category,
    qq.difficulty,
    qq.code_snippet,
    qq.related_file_path,
    qr.answer_given,
    qr.is_correct,
    qr.time_taken_seconds,
    qr.hints_used,
    qr.answered_at,
    qq.explanation
FROM quiz_questions qq
JOIN quiz_sessions qs ON qq.session_id = qs.id
LEFT JOIN quiz_responses qr ON qr.question_id = qq.id
ORDER BY qq.session_id, qq.sequence_order;

-- Developer learning analytics
CREATE VIEW IF NOT EXISTS developer_learning_analytics_view AS
SELECT
    lp.developer_id,
    p.slug as project_slug,
    lp.total_quizzes,
    lp.total_questions,
    lp.total_correct,
    lp.average_score,
    lp.strong_concepts,
    lp.weak_concepts,
    lp.last_quiz_at,
    CAST((julianday('now') - julianday(lp.last_quiz_at)) AS INTEGER) as days_since_last_quiz
FROM learning_progress lp
LEFT JOIN projects p ON lp.project_id = p.id
ORDER BY lp.last_quiz_at DESC;

-- Migration complete
-- Run: ./templedb migration apply 028
