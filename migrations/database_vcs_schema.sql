-- ============================================================================
-- DATABASE VERSION CONTROL SYSTEM
-- ============================================================================
-- Replace git-centric approach with database-native version control
-- Includes branching, merging, and history tracking
-- ============================================================================

-- Branches - like git branches but in database
-- ============================================================================
CREATE TABLE IF NOT EXISTS vcs_branches (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    branch_name TEXT NOT NULL,
    parent_branch_id INTEGER REFERENCES vcs_branches(id),

    -- Branch metadata
    is_default BOOLEAN DEFAULT 0,
    is_protected BOOLEAN DEFAULT 0,  -- prevent force updates

    -- Branch state
    head_commit_id INTEGER,  -- references vcs_commits, set after creation

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_by TEXT,

    UNIQUE(project_id, branch_name)
);

-- Commits - atomic sets of changes
-- ============================================================================
CREATE TABLE IF NOT EXISTS vcs_commits (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    branch_id INTEGER NOT NULL REFERENCES vcs_branches(id) ON DELETE CASCADE,

    -- Commit identity
    commit_hash TEXT NOT NULL UNIQUE,  -- SHA-256 of commit content
    parent_commit_id INTEGER REFERENCES vcs_commits(id),
    merge_parent_commit_id INTEGER REFERENCES vcs_commits(id),  -- for merges

    -- Commit metadata
    author TEXT NOT NULL,
    author_email TEXT,
    committer TEXT,
    committer_email TEXT,

    commit_message TEXT NOT NULL,
    commit_timestamp TEXT NOT NULL DEFAULT (datetime('now')),

    -- Statistics
    files_changed INTEGER DEFAULT 0,
    lines_added INTEGER DEFAULT 0,
    lines_removed INTEGER DEFAULT 0,

    -- Git import mapping
    git_commit_hash TEXT,  -- if imported from git
    git_branch TEXT,

    UNIQUE(project_id, commit_hash)
);

-- Now set the foreign key constraint for head_commit_id
-- This creates a circular dependency that's resolved by allowing NULL initially
CREATE INDEX IF NOT EXISTS idx_vcs_branches_head ON vcs_branches(head_commit_id);

-- File States - content of files at specific commits
-- ============================================================================
CREATE TABLE IF NOT EXISTS vcs_file_states (
    id INTEGER PRIMARY KEY,
    commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    -- File content at this commit
    content_text TEXT,
    content_blob BLOB,
    content_hash TEXT NOT NULL,  -- SHA-256

    -- File metadata at this commit
    file_mode TEXT,  -- permissions
    file_size INTEGER NOT NULL,
    line_count INTEGER,

    -- Change type in this commit
    change_type TEXT NOT NULL,  -- 'added', 'modified', 'deleted', 'renamed'
    previous_path TEXT,  -- if renamed

    UNIQUE(commit_id, file_id)
);

-- Working Directory State - tracks current editing state
-- ============================================================================
CREATE TABLE IF NOT EXISTS vcs_working_state (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    branch_id INTEGER NOT NULL REFERENCES vcs_branches(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    -- Current working content (may differ from committed)
    content_text TEXT,
    content_blob BLOB,
    content_hash TEXT,

    -- State tracking
    state TEXT NOT NULL DEFAULT 'unmodified',  -- 'unmodified', 'modified', 'added', 'deleted', 'conflict'
    staged BOOLEAN DEFAULT 0,  -- ready to commit

    last_modified TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(project_id, branch_id, file_id)
);

-- Staging Area - files ready to be committed
-- ============================================================================
CREATE TABLE IF NOT EXISTS vcs_staging (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    branch_id INTEGER NOT NULL REFERENCES vcs_branches(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    -- Staged content
    content_text TEXT,
    content_blob BLOB,
    content_hash TEXT NOT NULL,

    change_type TEXT NOT NULL,  -- 'added', 'modified', 'deleted', 'renamed'
    previous_path TEXT,

    staged_at TEXT NOT NULL DEFAULT (datetime('now')),
    staged_by TEXT,

    UNIQUE(project_id, branch_id, file_id)
);

-- Merge Requests - like pull requests
-- ============================================================================
CREATE TABLE IF NOT EXISTS vcs_merge_requests (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Source and target
    source_branch_id INTEGER NOT NULL REFERENCES vcs_branches(id),
    target_branch_id INTEGER NOT NULL REFERENCES vcs_branches(id),

    title TEXT NOT NULL,
    description TEXT,

    -- State
    status TEXT NOT NULL DEFAULT 'open',  -- 'open', 'merged', 'closed', 'conflict'

    -- Resolution
    merge_commit_id INTEGER REFERENCES vcs_commits(id),
    merged_at TEXT,
    merged_by TEXT,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_by TEXT NOT NULL,

    CHECK(source_branch_id != target_branch_id)
);

-- Tags - mark important commits
-- ============================================================================
CREATE TABLE IF NOT EXISTS vcs_tags (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,

    tag_name TEXT NOT NULL,
    tag_type TEXT NOT NULL DEFAULT 'lightweight',  -- 'lightweight', 'annotated'

    -- Annotated tag info
    tagger TEXT,
    tagger_email TEXT,
    tag_message TEXT,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(project_id, tag_name)
);

-- Git Import Mapping - for projects imported from git
-- ============================================================================
CREATE TABLE IF NOT EXISTS vcs_git_imports (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Git repository info
    git_remote_url TEXT NOT NULL,
    git_default_branch TEXT,

    -- Import metadata
    last_import_at TEXT,
    last_import_commit TEXT,
    import_status TEXT,  -- 'complete', 'partial', 'in_progress', 'failed'

    -- Mapping stats
    commits_imported INTEGER DEFAULT 0,
    branches_imported INTEGER DEFAULT 0,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(project_id)
);

-- Git to VCS mapping
CREATE TABLE IF NOT EXISTS vcs_git_commit_map (
    git_commit_hash TEXT NOT NULL,
    vcs_commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    PRIMARY KEY (project_id, git_commit_hash)
);

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

-- Current file states per branch
CREATE VIEW IF NOT EXISTS vcs_current_files_view AS
SELECT
    ws.project_id,
    p.slug AS project_slug,
    b.branch_name,
    pf.file_path,
    ws.state,
    ws.staged,
    ws.content_hash,
    ws.last_modified
FROM vcs_working_state ws
JOIN vcs_branches b ON ws.branch_id = b.id
JOIN project_files pf ON ws.file_id = pf.id
JOIN projects p ON ws.project_id = p.id;

-- Branch summary
CREATE VIEW IF NOT EXISTS vcs_branch_summary_view AS
SELECT
    b.id AS branch_id,
    b.project_id,
    p.slug AS project_slug,
    b.branch_name,
    b.is_default,
    b.is_protected,
    c.commit_hash AS head_commit,
    c.author AS last_author,
    c.commit_message AS last_message,
    c.commit_timestamp AS last_commit_time,
    (SELECT COUNT(*) FROM vcs_commits WHERE branch_id = b.id) AS total_commits
FROM vcs_branches b
JOIN projects p ON b.project_id = p.id
LEFT JOIN vcs_commits c ON b.head_commit_id = c.id;

-- Commit history view
CREATE VIEW IF NOT EXISTS vcs_commit_history_view AS
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
    c.git_commit_hash
FROM vcs_commits c
JOIN projects p ON c.project_id = p.id
JOIN vcs_branches b ON c.branch_id = b.id
ORDER BY c.commit_timestamp DESC;

-- File change history
CREATE VIEW IF NOT EXISTS vcs_file_history_view AS
SELECT
    pf.file_path,
    c.commit_hash,
    c.author,
    c.commit_message,
    c.commit_timestamp,
    fs.change_type,
    fs.file_size,
    fs.line_count,
    b.branch_name,
    p.slug AS project_slug
FROM vcs_file_states fs
JOIN vcs_commits c ON fs.commit_id = c.id
JOIN project_files pf ON fs.file_id = pf.id
JOIN vcs_branches b ON c.branch_id = b.id
JOIN projects p ON c.project_id = p.id
ORDER BY c.commit_timestamp DESC;

-- Uncommitted changes
CREATE VIEW IF NOT EXISTS vcs_changes_view AS
SELECT
    p.slug AS project_slug,
    b.branch_name,
    pf.file_path,
    ws.state,
    ws.staged,
    CASE
        WHEN ws.staged = 1 THEN 'ready_to_commit'
        WHEN ws.state = 'modified' THEN 'modified'
        WHEN ws.state = 'added' THEN 'new_file'
        WHEN ws.state = 'deleted' THEN 'deleted'
        ELSE ws.state
    END AS change_status
FROM vcs_working_state ws
JOIN vcs_branches b ON ws.branch_id = b.id
JOIN project_files pf ON ws.file_id = pf.id
JOIN projects p ON ws.project_id = p.id
WHERE ws.state != 'unmodified' OR ws.staged = 1;

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_vcs_commits_project ON vcs_commits(project_id);
CREATE INDEX IF NOT EXISTS idx_vcs_commits_branch ON vcs_commits(branch_id);
CREATE INDEX IF NOT EXISTS idx_vcs_commits_parent ON vcs_commits(parent_commit_id);
CREATE INDEX IF NOT EXISTS idx_vcs_commits_hash ON vcs_commits(commit_hash);
CREATE INDEX IF NOT EXISTS idx_vcs_commits_timestamp ON vcs_commits(commit_timestamp);

CREATE INDEX IF NOT EXISTS idx_vcs_file_states_commit ON vcs_file_states(commit_id);
CREATE INDEX IF NOT EXISTS idx_vcs_file_states_file ON vcs_file_states(file_id);

CREATE INDEX IF NOT EXISTS idx_vcs_working_state_project ON vcs_working_state(project_id);
CREATE INDEX IF NOT EXISTS idx_vcs_working_state_branch ON vcs_working_state(branch_id);
CREATE INDEX IF NOT EXISTS idx_vcs_working_state_file ON vcs_working_state(file_id);
CREATE INDEX IF NOT EXISTS idx_vcs_working_state_state ON vcs_working_state(state);

CREATE INDEX IF NOT EXISTS idx_vcs_staging_branch ON vcs_staging(branch_id);
CREATE INDEX IF NOT EXISTS idx_vcs_staging_file ON vcs_staging(file_id);

-- ============================================================================
-- TRIGGERS FOR AUTOMATION
-- ============================================================================

-- Auto-update branch head when new commit
CREATE TRIGGER IF NOT EXISTS update_branch_head_on_commit
AFTER INSERT ON vcs_commits
FOR EACH ROW
BEGIN
    UPDATE vcs_branches
    SET head_commit_id = NEW.id
    WHERE id = NEW.branch_id;
END;

-- ============================================================================
-- EXAMPLE USAGE
-- ============================================================================

-- Create default branch for a project:
-- INSERT INTO vcs_branches (project_id, branch_name, is_default)
-- VALUES (3, 'main', 1);

-- Create a commit:
-- INSERT INTO vcs_commits (project_id, branch_id, commit_hash, author, commit_message)
-- VALUES (3, 1, 'abc123...', 'user', 'Initial commit');

-- Add file state to commit:
-- INSERT INTO vcs_file_states (commit_id, file_id, content_text, content_hash,
--                               file_size, line_count, change_type)
-- VALUES (1, 1, 'content...', 'hash...', 1234, 50, 'added');

-- Check uncommitted changes:
-- SELECT * FROM vcs_changes_view WHERE project_slug = 'woofs_projects';

-- ============================================================================
-- END OF VCS SCHEMA
-- ============================================================================
