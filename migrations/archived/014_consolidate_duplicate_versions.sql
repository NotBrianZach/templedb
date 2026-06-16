-- Migration 014: Consolidate Duplicate Version Systems
--
-- Problem: Two overlapping version control systems
--   1. file_versions (old): Inline content storage, simple versioning
--   2. vcs_file_states (new): Part of full VCS with commits/branches
--
-- Solution: Unify into single system
--   - Keep vcs_* tables for full version control workflow
--   - Modify vcs_file_states to reference content_blobs (deduplication)
--   - Remove file_versions (migrate data to vcs_file_states)
--   - Keep file_contents as "current version" pointer
--
-- Reduction: 1 table removed, content deduplication added to VCS
--

BEGIN TRANSACTION;

-- ============================================================================
-- STEP 1: Backup existing data
-- ============================================================================

-- Backup file_versions before migration
CREATE TABLE IF NOT EXISTS file_versions_backup AS
SELECT * FROM file_versions WHERE EXISTS (SELECT 1 FROM file_versions LIMIT 1);

-- ============================================================================
-- STEP 2: Modify vcs_file_states to use content_blobs
-- ============================================================================

-- Create new vcs_file_states with content-addressed storage
CREATE TABLE vcs_file_states_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commit_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,

    -- Content reference (not inline storage)
    content_hash TEXT NOT NULL,

    -- File metadata at this commit
    file_mode TEXT,
    file_size INTEGER NOT NULL,
    line_count INTEGER,

    -- Change type in this commit
    change_type TEXT NOT NULL,  -- 'added', 'modified', 'deleted', 'renamed'
    previous_path TEXT,

    FOREIGN KEY (commit_id) REFERENCES vcs_commits(id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES project_files(id) ON DELETE CASCADE,
    FOREIGN KEY (content_hash) REFERENCES content_blobs(hash_sha256),
    UNIQUE(commit_id, file_id)
);

-- Migrate existing vcs_file_states data
-- Move inline content to content_blobs, then reference by hash
INSERT INTO vcs_file_states_new (
    id, commit_id, file_id, content_hash,
    file_mode, file_size, line_count, change_type, previous_path
)
SELECT
    vfs.id,
    vfs.commit_id,
    vfs.file_id,
    vfs.content_hash,
    vfs.file_mode,
    vfs.file_size,
    vfs.line_count,
    vfs.change_type,
    vfs.previous_path
FROM vcs_file_states vfs
WHERE EXISTS (SELECT 1 FROM vcs_file_states);

-- For any vcs_file_states with inline content, store in content_blobs
-- (This handles edge case where vcs_file_states has content but hash not in content_blobs)
INSERT OR IGNORE INTO content_blobs (hash_sha256, content_text, content_blob, content_type, file_size_bytes)
SELECT DISTINCT
    vfs.content_hash,
    vfs.content_text,
    vfs.content_blob,
    CASE
        WHEN vfs.content_text IS NOT NULL THEN 'text'
        ELSE 'binary'
    END as content_type,
    vfs.file_size
FROM vcs_file_states vfs
WHERE EXISTS (SELECT 1 FROM vcs_file_states)
  AND vfs.content_hash IS NOT NULL
  AND NOT EXISTS (
    SELECT 1 FROM content_blobs cb WHERE cb.hash_sha256 = vfs.content_hash
  );

-- Drop old table and rename new one
DROP TABLE IF EXISTS vcs_file_states;
ALTER TABLE vcs_file_states_new RENAME TO vcs_file_states;

-- Recreate indexes
CREATE INDEX idx_vcs_file_states_commit ON vcs_file_states(commit_id);
CREATE INDEX idx_vcs_file_states_file ON vcs_file_states(file_id);
CREATE INDEX idx_vcs_file_states_hash ON vcs_file_states(content_hash);
CREATE INDEX idx_vcs_file_states_change_type ON vcs_file_states(change_type);

-- ============================================================================
-- STEP 3: Migrate file_versions data to VCS system
-- ============================================================================

-- For each project with file_versions, create a VCS branch if not exists
INSERT OR IGNORE INTO vcs_branches (project_id, branch_name, is_default)
SELECT DISTINCT
    pf.project_id,
    'main' as branch_name,
    1 as is_default
FROM file_versions fv
JOIN project_files pf ON fv.file_id = pf.id
WHERE EXISTS (SELECT 1 FROM file_versions)
  AND NOT EXISTS (
    SELECT 1 FROM vcs_branches vb
    WHERE vb.project_id = pf.project_id AND vb.branch_name = 'main'
  );

-- Migrate file_versions to vcs_commits + vcs_file_states
-- Each file version becomes a commit with one file change
INSERT INTO vcs_commits (
    project_id,
    branch_id,
    commit_hash,
    parent_commit_id,
    author,
    commit_message,
    commit_timestamp,
    files_changed,
    lines_added,
    lines_removed
)
SELECT
    pf.project_id,
    (SELECT id FROM vcs_branches
     WHERE project_id = pf.project_id AND is_default = 1
     LIMIT 1) as branch_id,
    'fv-' || fv.id || '-' || substr(fv.hash_sha256, 1, 12) as commit_hash,
    (SELECT id FROM vcs_commits vc
     WHERE vc.project_id = pf.project_id
       AND vc.commit_hash = 'fv-' || fv.parent_version_id || '-' || substr(fvp.hash_sha256, 1, 12)
     LIMIT 1) as parent_commit_id,
    COALESCE(fv.author, 'unknown') as author,
    COALESCE(fv.commit_message, 'Version ' || fv.version_number) as commit_message,
    fv.created_at as commit_timestamp,
    1 as files_changed,
    COALESCE(fv.lines_added, 0) as lines_added,
    COALESCE(fv.lines_removed, 0) as lines_removed
FROM file_versions fv
JOIN project_files pf ON fv.file_id = pf.id
LEFT JOIN file_versions fvp ON fv.parent_version_id = fvp.id
WHERE EXISTS (SELECT 1 FROM file_versions)
  AND NOT EXISTS (
    SELECT 1 FROM vcs_commits vc2
    WHERE vc2.commit_hash = 'fv-' || fv.id || '-' || substr(fv.hash_sha256, 1, 12)
  )
ORDER BY fv.file_id, fv.version_number;

-- Store file_versions content in content_blobs (if not already there)
INSERT OR IGNORE INTO content_blobs (
    hash_sha256,
    content_text,
    content_blob,
    content_type,
    encoding,
    file_size_bytes
)
SELECT DISTINCT
    fv.hash_sha256,
    fv.content_text,
    fv.content_blob,
    fv.content_type,
    fv.encoding,
    fv.file_size_bytes
FROM file_versions fv
WHERE EXISTS (SELECT 1 FROM file_versions)
  AND fv.hash_sha256 IS NOT NULL;

-- Create vcs_file_states entries for each file version
INSERT INTO vcs_file_states (
    commit_id,
    file_id,
    content_hash,
    file_size,
    line_count,
    change_type
)
SELECT
    vc.id as commit_id,
    fv.file_id,
    fv.hash_sha256 as content_hash,
    fv.file_size_bytes as file_size,
    fv.line_count,
    CASE
        WHEN fv.parent_version_id IS NULL THEN 'added'
        ELSE 'modified'
    END as change_type
FROM file_versions fv
JOIN project_files pf ON fv.file_id = pf.id
JOIN vcs_commits vc ON vc.commit_hash = 'fv-' || fv.id || '-' || substr(fv.hash_sha256, 1, 12)
WHERE EXISTS (SELECT 1 FROM file_versions)
  AND NOT EXISTS (
    SELECT 1 FROM vcs_file_states vfs2
    WHERE vfs2.commit_id = vc.id AND vfs2.file_id = fv.file_id
  );

-- ============================================================================
-- STEP 4: Update file_contents to ensure consistency
-- ============================================================================

-- Ensure file_contents references content_blobs correctly
-- (This should already be the case, but verify)
UPDATE file_contents
SET content_hash = (
    SELECT hash_sha256
    FROM content_blobs
    WHERE content_blobs.content_text = file_contents.content_text
       OR content_blobs.content_blob = file_contents.content_blob
    LIMIT 1
)
WHERE content_hash IS NULL AND EXISTS (SELECT 1 FROM file_contents WHERE content_hash IS NULL);

-- ============================================================================
-- STEP 5: Update views for backward compatibility
-- ============================================================================

-- Drop old file_versions views
DROP VIEW IF EXISTS file_version_history_view;
DROP VIEW IF EXISTS latest_file_versions_view;
DROP VIEW IF EXISTS file_change_stats_view;
DROP VIEW IF EXISTS current_file_versions_view;

-- Create new file_version_history_view (backed by vcs_file_states)
CREATE VIEW file_version_history_view AS
SELECT
    vfs.id as version_id,
    vfs.file_id,
    pf.file_path,
    pf.component_name,
    ROW_NUMBER() OVER (PARTITION BY vfs.file_id ORDER BY vc.commit_timestamp) as version_number,
    NULL as version_tag,  -- Tags now in vcs_tags
    vc.author,
    vc.commit_message,
    vfs.content_hash as hash_sha256,
    vfs.file_size as file_size_bytes,
    NULL as lines_added,
    NULL as lines_removed,
    NULL as git_commit_hash,
    NULL as git_branch,
    vc.commit_timestamp as created_at,
    p.slug as project_slug
FROM vcs_file_states vfs
JOIN vcs_commits vc ON vfs.commit_id = vc.id
JOIN project_files pf ON vfs.file_id = pf.id
JOIN projects p ON pf.project_id = p.id
ORDER BY vfs.file_id, vc.commit_timestamp DESC;

-- Latest file versions view (backed by vcs_file_states)
CREATE VIEW latest_file_versions_view AS
SELECT
    pf.id as file_id,
    pf.file_path,
    pf.component_name,
    MAX(ranked.version_number) as latest_version,
    ranked.author as last_author,
    ranked.commit_message as last_commit_message,
    ranked.created_at as last_updated,
    ranked.hash_sha256,
    p.slug as project_slug
FROM project_files pf
JOIN projects p ON pf.project_id = p.id
LEFT JOIN (
    SELECT
        vfs.file_id,
        ROW_NUMBER() OVER (PARTITION BY vfs.file_id ORDER BY vc.commit_timestamp) as version_number,
        vc.author,
        vc.commit_message,
        vc.commit_timestamp as created_at,
        vfs.content_hash as hash_sha256
    FROM vcs_file_states vfs
    JOIN vcs_commits vc ON vfs.commit_id = vc.id
) ranked ON pf.id = ranked.file_id
GROUP BY pf.id;

-- File change stats view (backed by vcs_file_states)
CREATE VIEW file_change_stats_view AS
SELECT
    pf.id as file_id,
    pf.file_path,
    pf.component_name,
    COUNT(DISTINCT vfs.id) as total_changes,
    COUNT(DISTINCT vfs.commit_id) as total_versions,
    COUNT(DISTINCT vc.author) as unique_authors,
    MIN(vc.commit_timestamp) as first_change,
    MAX(vc.commit_timestamp) as last_change,
    SUM(vc.lines_added) as total_lines_added,
    SUM(vc.lines_removed) as total_lines_removed,
    p.slug as project_slug
FROM project_files pf
JOIN projects p ON pf.project_id = p.id
LEFT JOIN vcs_file_states vfs ON pf.id = vfs.file_id
LEFT JOIN vcs_commits vc ON vfs.commit_id = vc.id
GROUP BY pf.id;

-- Current file versions view
CREATE VIEW current_file_versions_view AS
SELECT
    fc.id,
    fc.file_id,
    pf.file_path,
    pf.project_id,
    p.slug as project_slug,
    (SELECT COUNT(*) FROM vcs_file_states vfs
     JOIN vcs_commits vc2 ON vfs.commit_id = vc2.id
     WHERE vfs.file_id = pf.id) as version_number,
    fc.content_hash as hash_sha256,
    cb.content_text,
    fc.file_size_bytes,
    fc.line_count,
    (SELECT vc.author FROM vcs_file_states vfs
     JOIN vcs_commits vc ON vfs.commit_id = vc.id
     WHERE vfs.file_id = pf.id
     ORDER BY vc.commit_timestamp DESC
     LIMIT 1) as author,
    (SELECT vc.commit_timestamp FROM vcs_file_states vfs
     JOIN vcs_commits vc ON vfs.commit_id = vc.id
     WHERE vfs.file_id = pf.id
     ORDER BY vc.commit_timestamp DESC
     LIMIT 1) as created_at
FROM file_contents fc
JOIN project_files pf ON fc.file_id = pf.id
JOIN projects p ON pf.project_id = p.id
LEFT JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
WHERE fc.is_current = 1;

-- ============================================================================
-- STEP 6: Drop old file_versions table
-- ============================================================================

DROP TABLE IF EXISTS file_versions;

-- ============================================================================
-- STEP 7: Drop file_diffs (if exists) - no longer needed
-- ============================================================================

-- Diffs can be computed on-demand from content_blobs
DROP TABLE IF EXISTS file_diffs;

COMMIT;

-- ============================================================================
-- Verification queries
-- ============================================================================

SELECT
    'Migration Summary' as report;

SELECT
    'vcs_file_states' as table_name,
    COUNT(*) as total_rows,
    COUNT(DISTINCT file_id) as unique_files,
    COUNT(DISTINCT commit_id) as unique_commits
FROM vcs_file_states;

SELECT
    'content_blobs' as table_name,
    COUNT(*) as total_blobs,
    SUM(file_size_bytes) as total_size_bytes,
    SUM(file_size_bytes) / 1024.0 / 1024.0 as total_size_mb
FROM content_blobs;

SELECT
    'vcs_commits' as table_name,
    COUNT(*) as total_commits,
    COUNT(DISTINCT project_id) as unique_projects,
    COUNT(DISTINCT branch_id) as unique_branches
FROM vcs_commits;
