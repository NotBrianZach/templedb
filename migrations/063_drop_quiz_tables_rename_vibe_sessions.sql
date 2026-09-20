-- Migration 063: Drop quiz tables, rename quiz_sessions → vibe_sessions
--
-- Removes the quiz system (quiz_configs, quiz_questions, quiz_responses,
-- vibe_question_queue, vibe_browser_sessions, learning_progress) and
-- replaces quiz_sessions with a streamlined vibe_sessions table focused
-- on interaction tracking rather than quizzes.

-- Step 1: Create new vibe_sessions table
CREATE TABLE IF NOT EXISTS vibe_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    session_name TEXT NOT NULL,
    session_type TEXT DEFAULT 'coding',
    related_commit_id INTEGER REFERENCES vcs_commits(id),
    related_work_item_id TEXT REFERENCES work_items(id),
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT DEFAULT (datetime('now')),
    started_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,
    tags TEXT,
    metadata TEXT,
    session_token TEXT
);

-- Step 2: Migrate data from quiz_sessions → vibe_sessions (preserve IDs for FK integrity)
INSERT OR IGNORE INTO vibe_sessions (id, project_id, session_name, session_type, related_commit_id, related_work_item_id, status, created_at, started_at, completed_at, tags, metadata, session_token)
SELECT id, project_id, session_name,
       CASE session_type WHEN 'vibe-realtime' THEN 'coding' WHEN 'commit' THEN 'review' ELSE 'coding' END,
       related_commit_id, related_work_item_id,
       CASE status WHEN 'pending' THEN 'active' WHEN 'in_progress' THEN 'active' ELSE status END,
       created_at, started_at, completed_at, tags, metadata, session_token
FROM quiz_sessions;

-- Step 3: Update FK references in kept tables
-- vibe_claude_interactions
CREATE TABLE IF NOT EXISTS _vibe_claude_interactions_new AS SELECT * FROM vibe_claude_interactions WHERE 0;
INSERT INTO _vibe_claude_interactions_new SELECT * FROM vibe_claude_interactions;

-- For SQLite, FK constraints are checked at statement level, not schema level,
-- so we just need the data migrated. The schema.sql has the correct FK references.

-- Step 4: Drop quiz tables and related objects
DROP VIEW IF EXISTS active_quiz_sessions_view;
DROP VIEW IF EXISTS quiz_questions_with_responses_view;
DROP VIEW IF EXISTS quiz_results_view;
DROP VIEW IF EXISTS vibe_question_queue_view;
DROP VIEW IF EXISTS developer_learning_analytics_view;

DROP TABLE IF EXISTS vibe_question_queue;
DROP TABLE IF EXISTS vibe_browser_sessions;
DROP TABLE IF EXISTS quiz_responses;
DROP TABLE IF EXISTS quiz_questions;
DROP TABLE IF EXISTS quiz_configs;
DROP TABLE IF EXISTS learning_progress;

-- Step 5: Recreate views with vibe_sessions references
DROP VIEW IF EXISTS active_vibe_sessions_view;
CREATE VIEW IF NOT EXISTS active_vibe_sessions_view AS
SELECT
    vs.id,
    vs.session_name,
    vs.session_type,
    vs.session_token,
    p.slug as project_slug,
    p.name as project_name,
    COUNT(DISTINCT vsc.id) as total_changes,
    COUNT(DISTINCT ci.id) as total_interactions,
    vss.user_prompts,
    vss.assistant_responses,
    vss.total_tokens,
    vs.started_at,
    vs.status
FROM vibe_sessions vs
JOIN projects p ON vs.project_id = p.id
LEFT JOIN vibe_session_changes vsc ON vsc.session_id = vs.id
LEFT JOIN vibe_claude_interactions ci ON ci.session_id = vs.id
LEFT JOIN vibe_session_stats vss ON vss.session_id = vs.id
WHERE vs.status = 'active'
GROUP BY vs.id;

DROP VIEW IF EXISTS vibe_conversation_view;
CREATE VIEW IF NOT EXISTS vibe_conversation_view AS
SELECT
    ci.id, ci.session_id, vs.session_name, p.slug as project_slug, p.name as project_name,
    ci.interaction_sequence, ci.interaction_type, ci.role, ci.content, ci.tool_name,
    ci.related_files, ci.tokens_input, ci.tokens_output, ci.latency_ms, ci.created_at,
    ip.turn_number, ip.was_helpful, ip.led_to_commit, ip.tool_calls_count
FROM vibe_claude_interactions ci
JOIN vibe_sessions vs ON ci.session_id = vs.id
JOIN projects p ON vs.project_id = p.id
LEFT JOIN vibe_interaction_pairs ip ON (ip.prompt_interaction_id = ci.id OR ip.response_interaction_id = ci.id)
ORDER BY ci.session_id, ci.interaction_sequence;

DROP VIEW IF EXISTS vibe_code_generation_view;
CREATE VIEW IF NOT EXISTS vibe_code_generation_view AS
SELECT
    cs.session_id, vs.session_name, p.slug as project_slug, cs.language,
    COUNT(*) as snippet_count, SUM(cs.line_count) as total_lines,
    SUM(CASE WHEN cs.was_applied = 1 THEN 1 ELSE 0 END) as applied_count,
    SUM(CASE WHEN cs.was_applied = 1 THEN cs.line_count ELSE 0 END) as applied_lines,
    ROUND(100.0 * SUM(CASE WHEN cs.was_applied = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as application_rate_pct
FROM vibe_interaction_code_snippets cs
JOIN vibe_sessions vs ON cs.session_id = vs.id
JOIN projects p ON vs.project_id = p.id
GROUP BY cs.session_id, cs.language
ORDER BY snippet_count DESC;

DROP VIEW IF EXISTS vibe_tool_usage_view;
CREATE VIEW IF NOT EXISTS vibe_tool_usage_view AS
SELECT
    ci.session_id, vs.session_name, p.slug as project_slug, ci.tool_name,
    COUNT(*) as usage_count, AVG(ci.latency_ms) as avg_latency_ms,
    SUM(CASE WHEN ci.tool_success = 1 THEN 1 ELSE 0 END) as success_count,
    SUM(CASE WHEN ci.tool_success = 0 THEN 1 ELSE 0 END) as failure_count,
    MIN(ci.created_at) as first_used, MAX(ci.created_at) as last_used
FROM vibe_claude_interactions ci
JOIN vibe_sessions vs ON ci.session_id = vs.id
JOIN projects p ON vs.project_id = p.id
WHERE ci.tool_name IS NOT NULL
GROUP BY ci.session_id, ci.tool_name
ORDER BY usage_count DESC;

DROP VIEW IF EXISTS vibe_session_quality_view;
CREATE VIEW IF NOT EXISTS vibe_session_quality_view AS
SELECT
    vs.id as session_id, vs.session_name, p.slug as project_slug,
    vss.total_interactions, vss.user_prompts, vss.assistant_responses, vss.tool_uses,
    vss.total_tokens, vss.avg_response_latency_ms, vss.total_errors,
    COUNT(DISTINCT ip.id) as total_turns,
    SUM(CASE WHEN ip.was_helpful = 1 THEN 1 ELSE 0 END) as helpful_responses,
    SUM(CASE WHEN ip.led_to_commit = 1 THEN 1 ELSE 0 END) as productive_turns,
    ROUND(100.0 * SUM(CASE WHEN ip.was_helpful = 1 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) as helpfulness_pct,
    vss.first_interaction_at, vss.last_interaction_at,
    CAST((julianday(vss.last_interaction_at) - julianday(vss.first_interaction_at)) * 24 * 60 AS INTEGER) as session_duration_minutes
FROM vibe_sessions vs
JOIN projects p ON vs.project_id = p.id
LEFT JOIN vibe_session_stats vss ON vss.session_id = vs.id
LEFT JOIN vibe_interaction_pairs ip ON ip.session_id = vs.id
GROUP BY vs.id;

DROP VIEW IF EXISTS vibe_session_timeline_view;
CREATE VIEW IF NOT EXISTS vibe_session_timeline_view AS
SELECT
    vse.id, vse.session_id, vs.session_name, vse.event_type, vse.event_data, vse.occurred_at,
    CAST((julianday(vse.occurred_at) - julianday(vs.started_at)) * 24 * 60 AS INTEGER) as minutes_since_start
FROM vibe_session_events vse
JOIN vibe_sessions vs ON vse.session_id = vs.id
ORDER BY vse.occurred_at DESC;

DROP VIEW IF EXISTS vibe_topics_view;
CREATE VIEW IF NOT EXISTS vibe_topics_view AS
SELECT
    t.id, t.session_id, vs.session_name, p.slug as project_slug,
    t.topic_name, t.topic_category, t.confidence, t.interaction_count, t.keywords, t.created_at,
    ci_first.content as first_mention, ci_last.content as last_mention
FROM vibe_interaction_topics t
JOIN vibe_sessions vs ON t.session_id = vs.id
JOIN projects p ON vs.project_id = p.id
LEFT JOIN vibe_claude_interactions ci_first ON t.first_interaction_id = ci_first.id
LEFT JOIN vibe_claude_interactions ci_last ON t.last_interaction_id = ci_last.id
ORDER BY t.session_id, t.created_at;

DROP VIEW IF EXISTS vibe_reusable_patterns_view;
CREATE VIEW IF NOT EXISTS vibe_reusable_patterns_view AS
SELECT
    p.slug as project_slug, cs.language, cs.snippet_type,
    COUNT(DISTINCT cs.session_id) as sessions_used, COUNT(*) as total_occurrences,
    SUM(CASE WHEN cs.was_applied = 1 THEN 1 ELSE 0 END) as times_applied,
    GROUP_CONCAT(DISTINCT t.topic_name) as related_topics, cs.code_content as example_code
FROM vibe_interaction_code_snippets cs
JOIN vibe_sessions vs ON cs.session_id = vs.id
JOIN projects p ON vs.project_id = p.id
LEFT JOIN vibe_interaction_topics t ON t.session_id = cs.session_id
WHERE cs.was_applied = 1
GROUP BY p.id, cs.language, cs.snippet_type, cs.code_content
HAVING sessions_used > 1
ORDER BY sessions_used DESC, times_applied DESC;

-- Step 6: New indexes for vibe_sessions
CREATE INDEX IF NOT EXISTS idx_vibe_sessions_project ON vibe_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_vibe_sessions_status ON vibe_sessions(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vibe_sessions_token ON vibe_sessions(session_token) WHERE session_token IS NOT NULL;

-- Step 7: Drop old quiz_sessions (after all FKs are migrated)
-- Note: child tables already reference by id, and data was preserved.
-- SQLite doesn't enforce FK constraints on DROP TABLE, so this is safe.
DROP TABLE IF EXISTS quiz_sessions;

-- Step 8: Clean up temp table
DROP TABLE IF EXISTS _vibe_claude_interactions_new;

-- Step 9: Drop old quiz indexes (they reference dropped tables, SQLite may have already removed them)
DROP INDEX IF EXISTS idx_quiz_questions_category;
DROP INDEX IF EXISTS idx_quiz_questions_order;
DROP INDEX IF EXISTS idx_quiz_questions_session;
DROP INDEX IF EXISTS idx_quiz_responses_correct;
DROP INDEX IF EXISTS idx_quiz_responses_question;
DROP INDEX IF EXISTS idx_quiz_responses_session;
DROP INDEX IF EXISTS idx_quiz_sessions_commit;
DROP INDEX IF EXISTS idx_quiz_sessions_project;
DROP INDEX IF EXISTS idx_quiz_sessions_status;
DROP INDEX IF EXISTS idx_quiz_sessions_token;
DROP INDEX IF EXISTS idx_quiz_sessions_work_item;
DROP INDEX IF EXISTS idx_vibe_queue_position;
DROP INDEX IF EXISTS idx_vibe_queue_session;
DROP INDEX IF EXISTS idx_vibe_queue_status;
DROP INDEX IF EXISTS idx_learning_progress_developer;
DROP INDEX IF EXISTS idx_learning_progress_project;
