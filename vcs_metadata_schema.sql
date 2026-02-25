-- ============================================================================
-- VCS COMMIT METADATA EXTENSION
-- ============================================================================
-- Enhanced metadata for understanding intent and context of changes
-- ============================================================================

-- Commit Metadata - Rich contextual information about commits
-- ============================================================================
CREATE TABLE IF NOT EXISTS vcs_commit_metadata (
    id INTEGER PRIMARY KEY,
    commit_id INTEGER NOT NULL UNIQUE REFERENCES vcs_commits(id) ON DELETE CASCADE,

    -- Intent and Purpose
    intent TEXT,                    -- High-level "why" behind the commit
    change_type TEXT,               -- 'feature', 'bugfix', 'refactor', 'docs', 'test', 'chore', 'perf', 'style'
    scope TEXT,                     -- Area of codebase affected (e.g., 'auth', 'api', 'ui')

    -- Breaking Changes
    is_breaking BOOLEAN DEFAULT 0,
    breaking_change_description TEXT,
    migration_notes TEXT,           -- How to migrate from previous version

    -- Related Context
    related_issues TEXT,            -- JSON array of issue IDs/URLs
    related_commits TEXT,           -- JSON array of related commit hashes
    related_prs TEXT,               -- JSON array of PR/MR IDs

    -- Impact Assessment
    impact_level TEXT,              -- 'low', 'medium', 'high', 'critical'
    affected_systems TEXT,          -- JSON array of system components
    risk_level TEXT,                -- 'low', 'medium', 'high'

    -- Development Context
    ai_assisted BOOLEAN DEFAULT 0,  -- Was AI used for these changes?
    ai_tool TEXT,                   -- Which AI tool (e.g., 'Claude', 'GPT-4', 'Copilot')
    confidence_level TEXT,          -- 'low', 'medium', 'high' - developer's confidence

    -- Review and Quality
    review_status TEXT,             -- 'not_reviewed', 'reviewed', 'approved', 'changes_requested'
    reviewed_by TEXT,               -- Reviewer name/email
    reviewed_at TEXT,
    test_coverage_change REAL,      -- Change in test coverage percentage

    -- Technical Details
    refactor_reason TEXT,           -- Why code was refactored
    performance_impact TEXT,        -- Expected performance changes
    security_impact TEXT,           -- Security implications

    -- Tags and Categories (flexible JSON arrays)
    tags TEXT,                      -- JSON array of custom tags
    categories TEXT,                -- JSON array of categories

    -- Metadata timestamps
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- File Change Metadata - Per-file intent and context
-- ============================================================================
CREATE TABLE IF NOT EXISTS vcs_file_change_metadata (
    id INTEGER PRIMARY KEY,
    commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    -- File-specific intent
    change_intent TEXT,             -- Why this specific file was changed
    change_summary TEXT,            -- Brief summary of changes to this file

    -- Technical details
    change_complexity TEXT,         -- 'trivial', 'simple', 'moderate', 'complex'
    requires_testing BOOLEAN DEFAULT 1,
    test_file_path TEXT,            -- Associated test file

    -- Dependencies
    affects_files TEXT,             -- JSON array of file paths this change impacts
    breaking_for_dependents BOOLEAN DEFAULT 0,

    -- Review notes
    review_notes TEXT,
    requires_special_review BOOLEAN DEFAULT 0,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(commit_id, file_id)
);

-- Commit Tags - Many-to-many relationship for flexible tagging
-- ============================================================================
CREATE TABLE IF NOT EXISTS vcs_commit_tags (
    id INTEGER PRIMARY KEY,
    commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    tag_name TEXT NOT NULL,
    tag_category TEXT,              -- 'type', 'priority', 'team', 'custom'

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(commit_id, tag_name)
);

-- Commit Dependencies - Track which commits depend on others
-- ============================================================================
CREATE TABLE IF NOT EXISTS vcs_commit_dependencies (
    id INTEGER PRIMARY KEY,
    commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    depends_on_commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    dependency_type TEXT,           -- 'requires', 'related', 'fixes', 'reverts'
    description TEXT,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(commit_id, depends_on_commit_id),
    CHECK(commit_id != depends_on_commit_id)
);

-- ============================================================================
-- VIEWS FOR ENHANCED QUERIES
-- ============================================================================

-- Complete commit view with metadata
CREATE VIEW IF NOT EXISTS vcs_commits_with_metadata_view AS
SELECT
    c.id AS commit_id,
    c.project_id,
    p.slug AS project_slug,
    b.branch_name,
    c.commit_hash,
    c.author,
    c.commit_message,
    c.commit_timestamp,
    c.files_changed,
    c.lines_added,
    c.lines_removed,
    -- Metadata
    m.intent,
    m.change_type,
    m.scope,
    m.is_breaking,
    m.impact_level,
    m.ai_assisted,
    m.confidence_level,
    m.review_status
FROM vcs_commits c
JOIN projects p ON c.project_id = p.id
JOIN vcs_branches b ON c.branch_id = b.id
LEFT JOIN vcs_commit_metadata m ON c.id = m.commit_id
ORDER BY c.commit_timestamp DESC;

-- Breaking changes view
CREATE VIEW IF NOT EXISTS vcs_breaking_changes_view AS
SELECT
    c.id AS commit_id,
    p.slug AS project_slug,
    b.branch_name,
    c.commit_hash,
    c.author,
    c.commit_message,
    c.commit_timestamp,
    m.breaking_change_description,
    m.migration_notes,
    m.impact_level
FROM vcs_commits c
JOIN projects p ON c.project_id = p.id
JOIN vcs_branches b ON c.branch_id = b.id
JOIN vcs_commit_metadata m ON c.id = m.commit_id
WHERE m.is_breaking = 1
ORDER BY c.commit_timestamp DESC;

-- AI-assisted commits view
CREATE VIEW IF NOT EXISTS vcs_ai_commits_view AS
SELECT
    c.id AS commit_id,
    p.slug AS project_slug,
    b.branch_name,
    c.commit_hash,
    c.author,
    c.commit_message,
    c.commit_timestamp,
    m.ai_tool,
    m.confidence_level,
    m.intent
FROM vcs_commits c
JOIN projects p ON c.project_id = p.id
JOIN vcs_branches b ON c.branch_id = b.id
JOIN vcs_commit_metadata m ON c.id = m.commit_id
WHERE m.ai_assisted = 1
ORDER BY c.commit_timestamp DESC;

-- High-impact changes view
CREATE VIEW IF NOT EXISTS vcs_high_impact_changes_view AS
SELECT
    c.id AS commit_id,
    p.slug AS project_slug,
    b.branch_name,
    c.commit_hash,
    c.author,
    c.commit_message,
    c.commit_timestamp,
    m.impact_level,
    m.risk_level,
    m.intent,
    m.review_status
FROM vcs_commits c
JOIN projects p ON c.project_id = p.id
JOIN vcs_branches b ON c.branch_id = b.id
JOIN vcs_commit_metadata m ON c.id = m.commit_id
WHERE m.impact_level IN ('high', 'critical')
ORDER BY c.commit_timestamp DESC;

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_vcs_commit_metadata_commit ON vcs_commit_metadata(commit_id);
CREATE INDEX IF NOT EXISTS idx_vcs_commit_metadata_type ON vcs_commit_metadata(change_type);
CREATE INDEX IF NOT EXISTS idx_vcs_commit_metadata_breaking ON vcs_commit_metadata(is_breaking);
CREATE INDEX IF NOT EXISTS idx_vcs_commit_metadata_impact ON vcs_commit_metadata(impact_level);
CREATE INDEX IF NOT EXISTS idx_vcs_commit_metadata_ai ON vcs_commit_metadata(ai_assisted);

CREATE INDEX IF NOT EXISTS idx_vcs_file_change_metadata_commit ON vcs_file_change_metadata(commit_id);
CREATE INDEX IF NOT EXISTS idx_vcs_file_change_metadata_file ON vcs_file_change_metadata(file_id);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_tags_commit ON vcs_commit_tags(commit_id);
CREATE INDEX IF NOT EXISTS idx_vcs_commit_tags_name ON vcs_commit_tags(tag_name);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_deps_commit ON vcs_commit_dependencies(commit_id);
CREATE INDEX IF NOT EXISTS idx_vcs_commit_deps_depends ON vcs_commit_dependencies(depends_on_commit_id);

-- ============================================================================
-- TRIGGERS FOR AUTOMATION
-- ============================================================================

-- Auto-update updated_at timestamp on metadata updates
CREATE TRIGGER IF NOT EXISTS update_commit_metadata_timestamp
AFTER UPDATE ON vcs_commit_metadata
FOR EACH ROW
BEGIN
    UPDATE vcs_commit_metadata
    SET updated_at = datetime('now')
    WHERE id = NEW.id;
END;

-- ============================================================================
-- EXAMPLE USAGE
-- ============================================================================

-- Create a commit with rich metadata:
/*
-- 1. Create the commit
INSERT INTO vcs_commits (project_id, branch_id, commit_hash, author, commit_message)
VALUES (1, 1, 'abc123...', 'user@email.com', 'Add user authentication system');

-- 2. Add commit metadata
INSERT INTO vcs_commit_metadata (
    commit_id, intent, change_type, scope, impact_level,
    ai_assisted, ai_tool, confidence_level, is_breaking
)
VALUES (
    last_insert_rowid(),
    'Implement OAuth2-based authentication to replace legacy session system',
    'feature',
    'auth',
    'high',
    1,
    'Claude',
    'high',
    1
);

-- 3. Add file-specific metadata
INSERT INTO vcs_file_change_metadata (commit_id, file_id, change_intent, change_complexity)
VALUES (
    1,
    42,
    'Refactor auth middleware to support OAuth2 tokens',
    'moderate'
);

-- 4. Add tags
INSERT INTO vcs_commit_tags (commit_id, tag_name, tag_category)
VALUES
    (1, 'security', 'type'),
    (1, 'breaking-change', 'type'),
    (1, 'auth-team', 'team');

-- Query breaking changes:
SELECT * FROM vcs_breaking_changes_view WHERE project_slug = 'my-project';

-- Query AI-assisted commits:
SELECT * FROM vcs_ai_commits_view WHERE project_slug = 'my-project';

-- Query high-impact changes needing review:
SELECT * FROM vcs_high_impact_changes_view
WHERE project_slug = 'my-project' AND review_status = 'not_reviewed';
*/

-- ============================================================================
-- END OF VCS METADATA SCHEMA
-- ============================================================================
