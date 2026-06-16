-- Migration 030: Vibe Claude Code Interaction Tracking
-- Captures all prompts, responses, and tool uses during vibe sessions
-- Enables RAG, analytics, and session continuity

-- Main interaction log - stores every message in the Claude conversation
CREATE TABLE IF NOT EXISTS vibe_claude_interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,

    -- Interaction metadata
    interaction_sequence INTEGER NOT NULL,  -- Order within session (0, 1, 2, ...)
    interaction_type TEXT NOT NULL,        -- 'user_prompt', 'assistant_response', 'tool_use', 'tool_result'
    role TEXT NOT NULL,                    -- 'user', 'assistant', 'system'

    -- Content
    content TEXT NOT NULL,                 -- The actual text content
    content_type TEXT DEFAULT 'text',      -- 'text', 'markdown', 'code', 'json', 'error'
    content_language TEXT,                 -- Programming language if code

    -- Context about what files/code this relates to
    related_files TEXT,                    -- JSON array of file paths mentioned/modified
    related_change_id INTEGER REFERENCES vibe_session_changes(id),
    related_commit_hash TEXT,

    -- Tool usage (if this is a tool use/result)
    tool_name TEXT,                        -- e.g., 'Read', 'Edit', 'Bash', 'Grep'
    tool_params TEXT,                      -- JSON of tool parameters
    tool_result TEXT,                      -- Result if tool_result type
    tool_success BOOLEAN,                  -- Whether tool succeeded

    -- API metadata
    model_used TEXT,                       -- e.g., 'claude-sonnet-4.5-20250929'
    tokens_input INTEGER,                  -- Tokens in (if available)
    tokens_output INTEGER,                 -- Tokens out (if available)
    latency_ms INTEGER,                    -- Response time in milliseconds
    api_request_id TEXT,                   -- Claude API request ID

    -- Vector embedding for semantic search (future RAG)
    embedding BLOB,                        -- Store sentence transformer embeddings
    embedding_model TEXT,                  -- Model used for embedding

    -- Quality signals
    contains_code BOOLEAN DEFAULT 0,
    contains_error BOOLEAN DEFAULT 0,
    code_blocks_count INTEGER DEFAULT 0,

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),

    -- Extensibility
    metadata TEXT                          -- JSON for additional data
);

-- Link prompts to their responses for easy pairing
CREATE TABLE IF NOT EXISTS vibe_interaction_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,
    prompt_interaction_id INTEGER NOT NULL REFERENCES vibe_claude_interactions(id),
    response_interaction_id INTEGER NOT NULL REFERENCES vibe_claude_interactions(id),

    -- Conversation turn metadata
    turn_number INTEGER NOT NULL,

    -- Quality metrics
    user_rating INTEGER,                   -- 1-5 stars (user can rate responses)
    was_helpful BOOLEAN,
    led_to_code_change BOOLEAN DEFAULT 0,
    led_to_commit BOOLEAN DEFAULT 0,
    related_commit_hash TEXT,

    -- Complexity metrics
    tool_calls_count INTEGER DEFAULT 0,
    files_modified_count INTEGER DEFAULT 0,
    lines_changed INTEGER DEFAULT 0,

    -- Timing
    total_duration_ms INTEGER,             -- Time from prompt to response
    thinking_time_ms INTEGER,              -- Time spent "thinking"

    created_at TEXT DEFAULT (datetime('now'))
);

-- Track code snippets extracted from interactions for easy retrieval
CREATE TABLE IF NOT EXISTS vibe_interaction_code_snippets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interaction_id INTEGER NOT NULL REFERENCES vibe_claude_interactions(id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,

    -- Code details
    language TEXT NOT NULL,
    code_content TEXT NOT NULL,
    snippet_type TEXT,                     -- 'example', 'fix', 'feature', 'refactor'

    -- Context
    file_path TEXT,                        -- If associated with a file
    was_applied BOOLEAN DEFAULT 0,         -- Did this code get used?

    -- Metadata
    line_count INTEGER,
    char_count INTEGER,

    created_at TEXT DEFAULT (datetime('now'))
);

-- Track topics/themes discussed in sessions for clustering
CREATE TABLE IF NOT EXISTS vibe_interaction_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES quiz_sessions(id) ON DELETE CASCADE,

    -- Topic identification
    topic_name TEXT NOT NULL,              -- e.g., 'authentication', 'error-handling', 'database-migration'
    topic_category TEXT,                   -- 'feature', 'bug', 'refactor', 'question', 'debug'
    confidence REAL,                       -- 0.0-1.0 confidence in topic extraction

    -- Related interactions
    first_interaction_id INTEGER REFERENCES vibe_claude_interactions(id),
    last_interaction_id INTEGER REFERENCES vibe_claude_interactions(id),
    interaction_count INTEGER DEFAULT 1,

    -- Keywords for matching
    keywords TEXT,                         -- JSON array of keywords

    created_at TEXT DEFAULT (datetime('now')),

    UNIQUE(session_id, topic_name)
);

-- Store embeddings separately for efficient vector search
CREATE TABLE IF NOT EXISTS vibe_interaction_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interaction_id INTEGER NOT NULL UNIQUE REFERENCES vibe_claude_interactions(id) ON DELETE CASCADE,

    -- Embedding vector (stored as blob)
    embedding BLOB NOT NULL,
    embedding_dim INTEGER NOT NULL,        -- Dimension of embedding (e.g., 384, 768, 1536)
    embedding_model TEXT NOT NULL,         -- e.g., 'all-MiniLM-L6-v2', 'text-embedding-3-small'

    -- For normalized cosine similarity
    embedding_norm REAL,                   -- L2 norm for faster similarity

    created_at TEXT DEFAULT (datetime('now'))
);

-- Session-level aggregates for quick stats
CREATE TABLE IF NOT EXISTS vibe_session_stats (
    session_id INTEGER PRIMARY KEY REFERENCES quiz_sessions(id) ON DELETE CASCADE,

    -- Interaction counts
    total_interactions INTEGER DEFAULT 0,
    user_prompts INTEGER DEFAULT 0,
    assistant_responses INTEGER DEFAULT 0,
    tool_uses INTEGER DEFAULT 0,

    -- Content stats
    total_tokens INTEGER DEFAULT 0,
    total_code_blocks INTEGER DEFAULT 0,
    total_files_mentioned INTEGER DEFAULT 0,
    total_files_modified INTEGER DEFAULT 0,

    -- Quality metrics
    avg_response_latency_ms INTEGER,
    total_errors INTEGER DEFAULT 0,

    -- Topics
    topics_discussed TEXT,                 -- JSON array of topics
    primary_programming_languages TEXT,    -- JSON array of languages

    -- Timestamps
    first_interaction_at TEXT,
    last_interaction_at TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_claude_interactions_session
    ON vibe_claude_interactions(session_id);
CREATE INDEX IF NOT EXISTS idx_claude_interactions_sequence
    ON vibe_claude_interactions(session_id, interaction_sequence);
CREATE INDEX IF NOT EXISTS idx_claude_interactions_type
    ON vibe_claude_interactions(interaction_type);
CREATE INDEX IF NOT EXISTS idx_claude_interactions_created
    ON vibe_claude_interactions(created_at);
CREATE INDEX IF NOT EXISTS idx_claude_interactions_tool
    ON vibe_claude_interactions(tool_name) WHERE tool_name IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_claude_interactions_files
    ON vibe_claude_interactions(related_files) WHERE related_files IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_interaction_pairs_session
    ON vibe_interaction_pairs(session_id);
CREATE INDEX IF NOT EXISTS idx_interaction_pairs_prompt
    ON vibe_interaction_pairs(prompt_interaction_id);
CREATE INDEX IF NOT EXISTS idx_interaction_pairs_response
    ON vibe_interaction_pairs(response_interaction_id);
CREATE INDEX IF NOT EXISTS idx_interaction_pairs_turn
    ON vibe_interaction_pairs(session_id, turn_number);
CREATE INDEX IF NOT EXISTS idx_interaction_pairs_helpful
    ON vibe_interaction_pairs(was_helpful) WHERE was_helpful = 1;

CREATE INDEX IF NOT EXISTS idx_code_snippets_interaction
    ON vibe_interaction_code_snippets(interaction_id);
CREATE INDEX IF NOT EXISTS idx_code_snippets_session
    ON vibe_interaction_code_snippets(session_id);
CREATE INDEX IF NOT EXISTS idx_code_snippets_language
    ON vibe_interaction_code_snippets(language);
CREATE INDEX IF NOT EXISTS idx_code_snippets_applied
    ON vibe_interaction_code_snippets(was_applied);

CREATE INDEX IF NOT EXISTS idx_topics_session
    ON vibe_interaction_topics(session_id);
CREATE INDEX IF NOT EXISTS idx_topics_category
    ON vibe_interaction_topics(topic_category);
CREATE INDEX IF NOT EXISTS idx_topics_name
    ON vibe_interaction_topics(topic_name);

CREATE INDEX IF NOT EXISTS idx_embeddings_interaction
    ON vibe_interaction_embeddings(interaction_id);

-- Views for common queries

-- Complete conversation view with paired interactions
CREATE VIEW IF NOT EXISTS vibe_conversation_view AS
SELECT
    ci.id,
    ci.session_id,
    qs.session_name,
    p.slug as project_slug,
    p.name as project_name,
    ci.interaction_sequence,
    ci.interaction_type,
    ci.role,
    ci.content,
    ci.tool_name,
    ci.related_files,
    ci.tokens_input,
    ci.tokens_output,
    ci.latency_ms,
    ci.created_at,
    ip.turn_number,
    ip.was_helpful,
    ip.led_to_commit,
    ip.tool_calls_count
FROM vibe_claude_interactions ci
JOIN quiz_sessions qs ON ci.session_id = qs.id
JOIN projects p ON qs.project_id = p.id
LEFT JOIN vibe_interaction_pairs ip ON (
    ip.prompt_interaction_id = ci.id OR
    ip.response_interaction_id = ci.id
)
ORDER BY ci.session_id, ci.interaction_sequence;

-- Tool usage analytics
CREATE VIEW IF NOT EXISTS vibe_tool_usage_view AS
SELECT
    ci.session_id,
    qs.session_name,
    p.slug as project_slug,
    ci.tool_name,
    COUNT(*) as usage_count,
    AVG(ci.latency_ms) as avg_latency_ms,
    SUM(CASE WHEN ci.tool_success = 1 THEN 1 ELSE 0 END) as success_count,
    SUM(CASE WHEN ci.tool_success = 0 THEN 1 ELSE 0 END) as failure_count,
    MIN(ci.created_at) as first_used,
    MAX(ci.created_at) as last_used
FROM vibe_claude_interactions ci
JOIN quiz_sessions qs ON ci.session_id = qs.id
JOIN projects p ON qs.project_id = p.id
WHERE ci.tool_name IS NOT NULL
GROUP BY ci.session_id, ci.tool_name
ORDER BY usage_count DESC;

-- Code generation metrics
CREATE VIEW IF NOT EXISTS vibe_code_generation_view AS
SELECT
    cs.session_id,
    qs.session_name,
    p.slug as project_slug,
    cs.language,
    COUNT(*) as snippet_count,
    SUM(cs.line_count) as total_lines,
    SUM(CASE WHEN cs.was_applied = 1 THEN 1 ELSE 0 END) as applied_count,
    SUM(CASE WHEN cs.was_applied = 1 THEN cs.line_count ELSE 0 END) as applied_lines,
    ROUND(100.0 * SUM(CASE WHEN cs.was_applied = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as application_rate_pct
FROM vibe_interaction_code_snippets cs
JOIN quiz_sessions qs ON cs.session_id = qs.id
JOIN projects p ON qs.project_id = p.id
GROUP BY cs.session_id, cs.language
ORDER BY snippet_count DESC;

-- Session quality metrics
CREATE VIEW IF NOT EXISTS vibe_session_quality_view AS
SELECT
    qs.id as session_id,
    qs.session_name,
    p.slug as project_slug,
    vss.total_interactions,
    vss.user_prompts,
    vss.assistant_responses,
    vss.tool_uses,
    vss.total_tokens,
    vss.avg_response_latency_ms,
    vss.total_errors,
    COUNT(DISTINCT ip.id) as total_turns,
    SUM(CASE WHEN ip.was_helpful = 1 THEN 1 ELSE 0 END) as helpful_responses,
    SUM(CASE WHEN ip.led_to_commit = 1 THEN 1 ELSE 0 END) as productive_turns,
    ROUND(100.0 * SUM(CASE WHEN ip.was_helpful = 1 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) as helpfulness_pct,
    vss.first_interaction_at,
    vss.last_interaction_at,
    CAST((julianday(vss.last_interaction_at) - julianday(vss.first_interaction_at)) * 24 * 60 AS INTEGER) as session_duration_minutes
FROM quiz_sessions qs
JOIN projects p ON qs.project_id = p.id
LEFT JOIN vibe_session_stats vss ON vss.session_id = qs.id
LEFT JOIN vibe_interaction_pairs ip ON ip.session_id = qs.id
WHERE qs.session_type = 'vibe-realtime'
GROUP BY qs.id;

-- Topic exploration view
CREATE VIEW IF NOT EXISTS vibe_topics_view AS
SELECT
    t.id,
    t.session_id,
    qs.session_name,
    p.slug as project_slug,
    t.topic_name,
    t.topic_category,
    t.confidence,
    t.interaction_count,
    t.keywords,
    t.created_at,
    ci_first.content as first_mention,
    ci_last.content as last_mention
FROM vibe_interaction_topics t
JOIN quiz_sessions qs ON t.session_id = qs.id
JOIN projects p ON qs.project_id = p.id
LEFT JOIN vibe_claude_interactions ci_first ON t.first_interaction_id = ci_first.id
LEFT JOIN vibe_claude_interactions ci_last ON t.last_interaction_id = ci_last.id
ORDER BY t.session_id, t.created_at;

-- Cross-session learning: find similar past interactions
CREATE VIEW IF NOT EXISTS vibe_reusable_patterns_view AS
SELECT
    p.slug as project_slug,
    cs.language,
    cs.snippet_type,
    COUNT(DISTINCT cs.session_id) as sessions_used,
    COUNT(*) as total_occurrences,
    SUM(CASE WHEN cs.was_applied = 1 THEN 1 ELSE 0 END) as times_applied,
    GROUP_CONCAT(DISTINCT t.topic_name) as related_topics,
    cs.code_content as example_code
FROM vibe_interaction_code_snippets cs
JOIN quiz_sessions qs ON cs.session_id = qs.id
JOIN projects p ON qs.project_id = p.id
LEFT JOIN vibe_interaction_topics t ON t.session_id = cs.session_id
WHERE cs.was_applied = 1
GROUP BY p.id, cs.language, cs.snippet_type, cs.code_content
HAVING sessions_used > 1
ORDER BY sessions_used DESC, times_applied DESC;

-- Triggers for maintaining stats

-- Update session stats when interaction is inserted
CREATE TRIGGER IF NOT EXISTS update_session_stats_on_interaction
AFTER INSERT ON vibe_claude_interactions
BEGIN
    INSERT INTO vibe_session_stats (session_id, updated_at)
    VALUES (NEW.session_id, datetime('now'))
    ON CONFLICT(session_id) DO UPDATE SET
        total_interactions = total_interactions + 1,
        user_prompts = user_prompts + CASE WHEN NEW.role = 'user' THEN 1 ELSE 0 END,
        assistant_responses = assistant_responses + CASE WHEN NEW.role = 'assistant' THEN 1 ELSE 0 END,
        tool_uses = tool_uses + CASE WHEN NEW.tool_name IS NOT NULL THEN 1 ELSE 0 END,
        total_tokens = total_tokens + COALESCE(NEW.tokens_input, 0) + COALESCE(NEW.tokens_output, 0),
        total_code_blocks = total_code_blocks + COALESCE(NEW.code_blocks_count, 0),
        total_errors = total_errors + CASE WHEN NEW.contains_error = 1 THEN 1 ELSE 0 END,
        last_interaction_at = NEW.created_at,
        first_interaction_at = COALESCE(first_interaction_at, NEW.created_at),
        updated_at = datetime('now');
END;

-- Migration metadata
-- Note: TempleDB doesn't use schema_migrations table, so this is commented out
-- INSERT OR IGNORE INTO schema_migrations (version, description, applied_at)
-- VALUES (30, 'Add vibe Claude Code interaction tracking', datetime('now'));
