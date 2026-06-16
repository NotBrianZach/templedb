-- ============================================================================
-- FILE VERSIONING SCHEMA EXTENSION
-- ============================================================================
-- Stores actual file contents in the database with full version history
-- ============================================================================

-- File Contents Storage (Current Version)
-- ============================================================================
CREATE TABLE IF NOT EXISTS file_contents (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    -- Content storage
    content_text TEXT,                -- For text files (UTF-8)
    content_blob BLOB,                -- For binary files
    content_type TEXT NOT NULL,       -- 'text' or 'binary'
    encoding TEXT DEFAULT 'utf-8',    -- For text files

    -- Metadata
    file_size_bytes INTEGER NOT NULL,
    line_count INTEGER,               -- For text files
    hash_sha256 TEXT NOT NULL,        -- SHA-256 hash of content

    -- Current version reference
    is_current BOOLEAN DEFAULT 1,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(file_id, is_current)       -- Only one current version per file
);

-- Version History
-- ============================================================================
CREATE TABLE IF NOT EXISTS file_versions (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    -- Version identification
    version_number INTEGER NOT NULL,  -- Auto-incrementing version number
    version_tag TEXT,                 -- Optional tag (e.g., 'v1.0.0', 'release')

    -- Content storage
    content_text TEXT,
    content_blob BLOB,
    content_type TEXT NOT NULL,
    encoding TEXT DEFAULT 'utf-8',

    -- Metadata
    file_size_bytes INTEGER NOT NULL,
    line_count INTEGER,
    hash_sha256 TEXT NOT NULL,

    -- Version control metadata
    author TEXT,                      -- Who made this version
    commit_message TEXT,              -- Description of changes
    parent_version_id INTEGER REFERENCES file_versions(id),  -- Previous version

    -- Git integration (optional)
    git_commit_hash TEXT,             -- Associated git commit
    git_branch TEXT,                  -- Git branch

    -- Change statistics
    lines_added INTEGER,
    lines_removed INTEGER,
    lines_modified INTEGER,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(file_id, version_number),
    CHECK(version_number > 0)
);

-- Diff Storage (Space-efficient version control)
-- ============================================================================
CREATE TABLE IF NOT EXISTS file_diffs (
    id INTEGER PRIMARY KEY,
    from_version_id INTEGER NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,
    to_version_id INTEGER NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,

    -- Diff format
    diff_format TEXT NOT NULL DEFAULT 'unified',  -- 'unified', 'context', 'ed'
    diff_content TEXT NOT NULL,       -- Actual diff content

    -- Statistics
    chunks_count INTEGER,             -- Number of diff chunks
    lines_added INTEGER,
    lines_removed INTEGER,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(from_version_id, to_version_id)
);

-- File Change Events (Audit Trail)
-- ============================================================================
CREATE TABLE IF NOT EXISTS file_change_events (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    version_id INTEGER REFERENCES file_versions(id) ON DELETE SET NULL,

    event_type TEXT NOT NULL,         -- 'created', 'modified', 'deleted', 'restored', 'renamed'

    -- Change details
    old_content_hash TEXT,
    new_content_hash TEXT,
    old_file_path TEXT,
    new_file_path TEXT,

    -- Who and when
    author TEXT,
    author_email TEXT,
    event_timestamp TEXT NOT NULL DEFAULT (datetime('now')),

    -- Context
    commit_message TEXT,
    git_commit_hash TEXT,
    git_branch TEXT,

    -- Additional metadata
    metadata TEXT                     -- JSON for additional context
);

-- File Tags (for marking specific versions)
-- ============================================================================
CREATE TABLE IF NOT EXISTS version_tags (
    id INTEGER PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,

    tag_name TEXT NOT NULL,           -- e.g., 'production', 'stable', 'v1.0'
    tag_type TEXT NOT NULL,           -- 'release', 'snapshot', 'milestone', 'backup'
    description TEXT,

    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(version_id, tag_name)
);

-- File Snapshots (Full backups at important points)
-- ============================================================================
CREATE TABLE IF NOT EXISTS file_snapshots (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    snapshot_name TEXT NOT NULL,
    snapshot_reason TEXT,             -- 'daily', 'before-deploy', 'milestone', 'manual'

    -- Snapshot content
    content_text TEXT,
    content_blob BLOB,
    content_type TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    hash_sha256 TEXT NOT NULL,

    -- Reference to version
    version_id INTEGER REFERENCES file_versions(id),

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(file_id, snapshot_name)
);

-- ============================================================================
-- VIEWS FOR VERSION CONTROL
-- ============================================================================

-- Current file contents with metadata
CREATE VIEW IF NOT EXISTS current_file_contents_view AS
SELECT
    pf.id AS file_id,
    pf.file_path,
    pf.file_name,
    pf.component_name,
    ft.type_name,
    fc.content_text,
    fc.content_type,
    fc.file_size_bytes,
    fc.line_count,
    fc.hash_sha256,
    fc.updated_at,
    p.slug AS project_slug
FROM file_contents fc
JOIN project_files pf ON fc.file_id = pf.id
JOIN file_types ft ON pf.file_type_id = ft.id
JOIN projects p ON pf.project_id = p.id
WHERE fc.is_current = 1;

-- Version history with change information
CREATE VIEW IF NOT EXISTS file_version_history_view AS
SELECT
    fv.id AS version_id,
    pf.id AS file_id,
    pf.file_path,
    pf.component_name,
    fv.version_number,
    fv.version_tag,
    fv.author,
    fv.commit_message,
    fv.hash_sha256,
    fv.file_size_bytes,
    fv.lines_added,
    fv.lines_removed,
    fv.git_commit_hash,
    fv.git_branch,
    fv.created_at,
    p.slug AS project_slug
FROM file_versions fv
JOIN project_files pf ON fv.file_id = pf.id
JOIN projects p ON pf.project_id = p.id
ORDER BY fv.file_id, fv.version_number DESC;

-- File change timeline
CREATE VIEW IF NOT EXISTS file_change_timeline_view AS
SELECT
    fce.id,
    pf.file_path,
    pf.component_name,
    fce.event_type,
    fce.author,
    fce.commit_message,
    fce.event_timestamp,
    fce.git_commit_hash,
    fce.old_content_hash,
    fce.new_content_hash,
    p.slug AS project_slug
FROM file_change_events fce
JOIN project_files pf ON fce.file_id = pf.id
JOIN projects p ON pf.project_id = p.id
ORDER BY fce.event_timestamp DESC;

-- Latest versions by file
CREATE VIEW IF NOT EXISTS latest_file_versions_view AS
SELECT
    pf.id AS file_id,
    pf.file_path,
    pf.component_name,
    MAX(fv.version_number) AS latest_version,
    fv.author AS last_author,
    fv.commit_message AS last_commit_message,
    fv.created_at AS last_updated,
    fv.hash_sha256,
    p.slug AS project_slug
FROM project_files pf
LEFT JOIN file_versions fv ON pf.id = fv.file_id
JOIN projects p ON pf.project_id = p.id
GROUP BY pf.id;

-- Files with change statistics
CREATE VIEW IF NOT EXISTS file_change_stats_view AS
SELECT
    pf.id AS file_id,
    pf.file_path,
    pf.component_name,
    COUNT(DISTINCT fce.id) AS total_changes,
    COUNT(DISTINCT fv.id) AS total_versions,
    COUNT(DISTINCT fce.author) AS unique_authors,
    MIN(fce.event_timestamp) AS first_change,
    MAX(fce.event_timestamp) AS last_change,
    SUM(fv.lines_added) AS total_lines_added,
    SUM(fv.lines_removed) AS total_lines_removed,
    p.slug AS project_slug
FROM project_files pf
LEFT JOIN file_change_events fce ON pf.id = fce.file_id
LEFT JOIN file_versions fv ON pf.id = fv.file_id
JOIN projects p ON pf.project_id = p.id
GROUP BY pf.id;

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_file_contents_file_id ON file_contents(file_id);
CREATE INDEX IF NOT EXISTS idx_file_contents_hash ON file_contents(hash_sha256);
CREATE INDEX IF NOT EXISTS idx_file_contents_current ON file_contents(is_current);

CREATE INDEX IF NOT EXISTS idx_file_versions_file_id ON file_versions(file_id);
CREATE INDEX IF NOT EXISTS idx_file_versions_number ON file_versions(file_id, version_number);
CREATE INDEX IF NOT EXISTS idx_file_versions_hash ON file_versions(hash_sha256);
CREATE INDEX IF NOT EXISTS idx_file_versions_author ON file_versions(author);
CREATE INDEX IF NOT EXISTS idx_file_versions_git_commit ON file_versions(git_commit_hash);

CREATE INDEX IF NOT EXISTS idx_file_diffs_versions ON file_diffs(from_version_id, to_version_id);

CREATE INDEX IF NOT EXISTS idx_file_change_events_file_id ON file_change_events(file_id);
CREATE INDEX IF NOT EXISTS idx_file_change_events_timestamp ON file_change_events(event_timestamp);
CREATE INDEX IF NOT EXISTS idx_file_change_events_author ON file_change_events(author);
CREATE INDEX IF NOT EXISTS idx_file_change_events_git_commit ON file_change_events(git_commit_hash);

CREATE INDEX IF NOT EXISTS idx_version_tags_version_id ON version_tags(version_id);
CREATE INDEX IF NOT EXISTS idx_version_tags_name ON version_tags(tag_name);

CREATE INDEX IF NOT EXISTS idx_file_snapshots_file_id ON file_snapshots(file_id);
CREATE INDEX IF NOT EXISTS idx_file_snapshots_name ON file_snapshots(snapshot_name);

-- ============================================================================
-- TRIGGERS
-- ============================================================================

-- Auto-increment version numbers
-- Note: Version numbers are handled in application code
-- SQLite doesn't support SELECT INTO in triggers like PostgreSQL
-- The populate_file_contents.cjs script will automatically assign version numbers

-- Update file_contents updated_at
CREATE TRIGGER IF NOT EXISTS update_file_contents_updated_at
AFTER UPDATE ON file_contents
FOR EACH ROW
BEGIN
    UPDATE file_contents SET updated_at = datetime('now') WHERE id = NEW.id;
END;

-- Only allow one current version per file
CREATE TRIGGER IF NOT EXISTS enforce_single_current_version
BEFORE INSERT ON file_contents
FOR EACH ROW
WHEN NEW.is_current = 1
BEGIN
    UPDATE file_contents SET is_current = 0 WHERE file_id = NEW.file_id AND is_current = 1;
END;

-- Log file changes when new version is created
CREATE TRIGGER IF NOT EXISTS log_file_version_change
AFTER INSERT ON file_versions
FOR EACH ROW
BEGIN
    INSERT INTO file_change_events (
        file_id, version_id, event_type,
        new_content_hash, author, commit_message,
        git_commit_hash, git_branch
    )
    VALUES (
        NEW.file_id, NEW.id, 'modified',
        NEW.hash_sha256, NEW.author, NEW.commit_message,
        NEW.git_commit_hash, NEW.git_branch
    );
END;

-- ============================================================================
-- HELPER FUNCTIONS (via triggers/views)
-- ============================================================================

-- Note: SQLite doesn't have user-defined functions like PostgreSQL,
-- but you can achieve similar functionality through application code
-- or by using the JSON1 extension for complex queries.

-- Example queries you can use:

-- Get all versions of a specific file:
-- SELECT * FROM file_version_history_view WHERE file_path = 'path/to/file.js';

-- Compare two versions (you'd calculate diff in application code):
-- SELECT fv1.content_text as v1, fv2.content_text as v2
-- FROM file_versions fv1, file_versions fv2
-- WHERE fv1.file_id = fv2.file_id
--   AND fv1.version_number = 1
--   AND fv2.version_number = 2;

-- Get latest version of all files:
-- SELECT * FROM latest_file_versions_view;

-- Find files modified by specific author:
-- SELECT DISTINCT file_path FROM file_version_history_view WHERE author = 'username';

-- ============================================================================
-- END OF VERSIONING SCHEMA
-- ============================================================================
