-- Migration 009: Consolidate File Versioning Tables
-- Consolidates file_versions, file_snapshots, and version_tags into single file_versions table
-- Removes file_change_events (redundant with vcs_commits)
--
-- Before: 6 tables (file_contents, file_versions, file_diffs, file_change_events, version_tags, file_snapshots)
-- After: 3 tables (file_contents, file_versions_consolidated, file_diffs)
-- Reduction: 3 tables

BEGIN TRANSACTION;

-- Create consolidated file_versions table
CREATE TABLE IF NOT EXISTS file_versions_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    version_number INTEGER NOT NULL,
    version_type TEXT DEFAULT 'normal' CHECK(version_type IN ('normal', 'snapshot', 'release', 'backup')),
    version_tag TEXT,  -- For tagged versions (e.g., 'v1.0.0', 'stable', 'pre-refactor')
    content_text TEXT,
    content_blob BLOB,
    hash_sha256 TEXT NOT NULL,
    file_size_bytes INTEGER,
    line_count INTEGER,
    author TEXT,
    commit_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    commit_id INTEGER,  -- Link to VCS commit
    is_current BOOLEAN DEFAULT 0,  -- Mark current version
    FOREIGN KEY (file_id) REFERENCES project_files(id) ON DELETE CASCADE,
    FOREIGN KEY (commit_id) REFERENCES vcs_commits(id) ON DELETE SET NULL,
    UNIQUE(file_id, version_number)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_file_versions_new_file_id
    ON file_versions_new(file_id);
CREATE INDEX IF NOT EXISTS idx_file_versions_new_hash
    ON file_versions_new(hash_sha256);
CREATE INDEX IF NOT EXISTS idx_file_versions_new_current
    ON file_versions_new(file_id, is_current);
CREATE INDEX IF NOT EXISTS idx_file_versions_new_commit
    ON file_versions_new(commit_id);
CREATE INDEX IF NOT EXISTS idx_file_versions_new_tag
    ON file_versions_new(version_tag);

-- Migrate data from existing file_versions
INSERT INTO file_versions_new (
    id, file_id, version_number, version_type, version_tag,
    content_text, content_blob, hash_sha256, file_size_bytes,
    line_count, author, commit_message, created_at, commit_id, is_current
)
SELECT
    id, file_id, version_number,
    'normal' as version_type,
    version_tag,
    content_text, content_blob, hash_sha256, file_size_bytes,
    line_count, author, commit_message, created_at,
    NULL as commit_id,  -- Will be linked later if needed
    is_current
FROM file_versions
WHERE EXISTS (SELECT 1 FROM file_versions);

-- Migrate data from file_snapshots (if table exists)
INSERT INTO file_versions_new (
    file_id, version_number, version_type, version_tag,
    content_text, content_blob, hash_sha256, file_size_bytes,
    author, commit_message, created_at, is_current
)
SELECT
    file_id,
    (SELECT COALESCE(MAX(version_number), 0) + row_number() OVER (PARTITION BY file_id ORDER BY created_at)
     FROM file_versions_new WHERE file_versions_new.file_id = fs.file_id) as version_number,
    'snapshot' as version_type,
    snapshot_name as version_tag,
    content_text, content_blob, hash_sha256, file_size_bytes,
    created_by as author,
    purpose as commit_message,
    created_at,
    0 as is_current
FROM file_snapshots fs
WHERE EXISTS (SELECT 1 FROM file_snapshots);

-- Migrate version tags as tagged versions
UPDATE file_versions_new
SET version_tag = (
    SELECT tag_name
    FROM version_tags
    WHERE version_tags.version_id = file_versions_new.id
    LIMIT 1
),
version_type = 'release'
WHERE id IN (SELECT version_id FROM version_tags WHERE EXISTS (SELECT 1 FROM version_tags));

-- Create backward-compatible view for file_version_history
CREATE VIEW IF NOT EXISTS file_version_history_view AS
SELECT
    fv.id,
    fv.file_id,
    pf.file_path,
    pf.project_id,
    p.slug as project_slug,
    fv.version_number,
    fv.version_type,
    fv.version_tag,
    fv.hash_sha256,
    fv.file_size_bytes,
    fv.line_count,
    fv.author,
    fv.commit_message,
    fv.created_at,
    fv.is_current,
    fv.commit_id
FROM file_versions_new fv
JOIN project_files pf ON fv.file_id = pf.id
JOIN projects p ON pf.project_id = p.id
ORDER BY fv.file_id, fv.version_number DESC;

-- Create view for current file versions
CREATE VIEW IF NOT EXISTS current_file_versions_view AS
SELECT
    fv.id,
    fv.file_id,
    pf.file_path,
    pf.project_id,
    p.slug as project_slug,
    fv.version_number,
    fv.hash_sha256,
    fv.content_text,
    fv.file_size_bytes,
    fv.line_count,
    fv.author,
    fv.created_at
FROM file_versions_new fv
JOIN project_files pf ON fv.file_id = pf.id
JOIN projects p ON pf.project_id = p.id
WHERE fv.is_current = 1;

-- Create view for file change timeline (replaces file_change_events)
CREATE VIEW IF NOT EXISTS file_change_timeline_view AS
SELECT
    fv.id as event_id,
    fv.file_id,
    pf.file_path,
    pf.project_id,
    'version_created' as event_type,
    fv.author,
    fv.commit_message as description,
    fv.created_at as event_timestamp,
    json_object(
        'version_number', fv.version_number,
        'version_type', fv.version_type,
        'hash', fv.hash_sha256,
        'size', fv.file_size_bytes
    ) as metadata
FROM file_versions_new fv
JOIN project_files pf ON fv.file_id = pf.id
UNION ALL
SELECT
    vc.id as event_id,
    vfs.file_id,
    pf.file_path,
    vc.project_id,
    'committed' as event_type,
    vc.author,
    vc.commit_message as description,
    vc.commit_timestamp as event_timestamp,
    json_object(
        'commit_hash', vc.commit_hash,
        'branch', vb.branch_name,
        'change_type', vfs.change_type
    ) as metadata
FROM vcs_commits vc
JOIN vcs_file_states vfs ON vc.id = vfs.commit_id
JOIN vcs_branches vb ON vc.branch_id = vb.id
JOIN project_files pf ON vfs.file_id = pf.id
WHERE EXISTS (SELECT 1 FROM vcs_commits)
ORDER BY event_timestamp DESC;

-- Drop old tables
DROP TABLE IF EXISTS file_versions;
DROP TABLE IF EXISTS file_snapshots;
DROP TABLE IF EXISTS version_tags;
DROP TABLE IF EXISTS file_change_events;

-- Rename new table
ALTER TABLE file_versions_new RENAME TO file_versions;

-- Recreate indexes with correct names after rename
DROP INDEX IF EXISTS idx_file_versions_new_file_id;
DROP INDEX IF EXISTS idx_file_versions_new_hash;
DROP INDEX IF EXISTS idx_file_versions_new_current;
DROP INDEX IF EXISTS idx_file_versions_new_commit;
DROP INDEX IF EXISTS idx_file_versions_new_tag;

CREATE INDEX idx_file_versions_file_id ON file_versions(file_id);
CREATE INDEX idx_file_versions_hash ON file_versions(hash_sha256);
CREATE INDEX idx_file_versions_current ON file_versions(file_id, is_current);
CREATE INDEX idx_file_versions_commit ON file_versions(commit_id);
CREATE INDEX idx_file_versions_tag ON file_versions(version_tag);

-- Create trigger to ensure only one current version per file
CREATE TRIGGER IF NOT EXISTS enforce_single_current_version
BEFORE UPDATE ON file_versions
FOR EACH ROW
WHEN NEW.is_current = 1 AND OLD.is_current = 0
BEGIN
    UPDATE file_versions SET is_current = 0 WHERE file_id = NEW.file_id AND id != NEW.id;
END;

COMMIT;

-- Verify migration
SELECT
    'file_versions' as table_name,
    COUNT(*) as total_versions,
    COUNT(DISTINCT file_id) as unique_files,
    COUNT(CASE WHEN version_type = 'snapshot' THEN 1 END) as snapshots,
    COUNT(CASE WHEN version_type = 'release' THEN 1 END) as releases,
    COUNT(CASE WHEN is_current = 1 THEN 1 END) as current_versions
FROM file_versions;
