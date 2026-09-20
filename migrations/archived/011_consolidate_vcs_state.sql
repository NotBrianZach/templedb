-- Migration 011: Consolidate VCS Working State and Staging
-- Merges vcs_working_state and vcs_staging into single table with staged flag
--
-- Before: 2 tables (vcs_working_state, vcs_staging)
-- After: 1 table (vcs_working_state with staged column)
-- Reduction: 1 table

BEGIN TRANSACTION;

-- Create new consolidated vcs_working_state table
CREATE TABLE IF NOT EXISTS vcs_working_state_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    branch_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,
    state TEXT NOT NULL CHECK(state IN ('unmodified', 'modified', 'added', 'deleted', 'renamed', 'conflicted')),
    staged BOOLEAN DEFAULT 0,  -- Whether file is staged for commit
    content_text TEXT,
    content_blob BLOB,
    content_hash TEXT,
    file_size_bytes INTEGER,
    line_count INTEGER,
    change_type TEXT,  -- 'content', 'permissions', 'metadata'
    old_file_path TEXT,  -- For renamed files
    last_modified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    staged_at TIMESTAMP,  -- When file was staged
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (branch_id) REFERENCES vcs_branches(id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES project_files(id) ON DELETE CASCADE,
    UNIQUE(project_id, branch_id, file_id)
);

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_vcs_working_state_new_project_branch
    ON vcs_working_state_new(project_id, branch_id);
CREATE INDEX IF NOT EXISTS idx_vcs_working_state_new_file
    ON vcs_working_state_new(file_id);
CREATE INDEX IF NOT EXISTS idx_vcs_working_state_new_state
    ON vcs_working_state_new(state);
CREATE INDEX IF NOT EXISTS idx_vcs_working_state_new_staged
    ON vcs_working_state_new(project_id, branch_id, staged);
CREATE INDEX IF NOT EXISTS idx_vcs_working_state_new_modified
    ON vcs_working_state_new(last_modified);

-- Migrate data from existing vcs_working_state
INSERT INTO vcs_working_state_new (
    id, project_id, branch_id, file_id, state, staged,
    content_text, content_blob, content_hash, file_size_bytes,
    last_modified
)
SELECT
    id, project_id, branch_id, file_id, state,
    COALESCE(staged, 0) as staged,
    content_text, content_blob, content_hash, file_size_bytes,
    last_modified
FROM vcs_working_state
WHERE EXISTS (SELECT 1 FROM vcs_working_state);

-- Migrate data from vcs_staging (mark as staged)
INSERT OR REPLACE INTO vcs_working_state_new (
    project_id, branch_id, file_id, state, staged,
    content_text, content_blob, content_hash, file_size_bytes,
    change_type, staged_at, last_modified
)
SELECT
    project_id, branch_id, file_id,
    COALESCE(change_type, 'modified') as state,
    1 as staged,
    content_text, content_blob, content_hash, file_size_bytes,
    change_type,
    staged_at,
    COALESCE(staged_at, CURRENT_TIMESTAMP) as last_modified
FROM vcs_staging
WHERE EXISTS (SELECT 1 FROM vcs_staging)
ON CONFLICT(project_id, branch_id, file_id) DO UPDATE SET
    staged = 1,
    content_text = excluded.content_text,
    content_blob = excluded.content_blob,
    content_hash = excluded.content_hash,
    staged_at = excluded.staged_at;

-- Create views for backward compatibility and convenience
CREATE VIEW IF NOT EXISTS vcs_unstaged_changes_view AS
SELECT
    ws.id,
    ws.project_id,
    p.slug as project_slug,
    ws.branch_id,
    vb.branch_name,
    ws.file_id,
    pf.file_path,
    ws.state,
    ws.content_hash,
    ws.file_size_bytes,
    ws.line_count,
    ws.last_modified
FROM vcs_working_state_new ws
JOIN projects p ON ws.project_id = p.id
JOIN vcs_branches vb ON ws.branch_id = vb.id
JOIN project_files pf ON ws.file_id = pf.id
WHERE ws.staged = 0 AND ws.state != 'unmodified';

CREATE VIEW IF NOT EXISTS vcs_staged_changes_view AS
SELECT
    ws.id,
    ws.project_id,
    p.slug as project_slug,
    ws.branch_id,
    vb.branch_name,
    ws.file_id,
    pf.file_path,
    ws.state,
    ws.content_hash,
    ws.file_size_bytes,
    ws.line_count,
    ws.change_type,
    ws.staged_at,
    ws.last_modified
FROM vcs_working_state_new ws
JOIN projects p ON ws.project_id = p.id
JOIN vcs_branches vb ON ws.branch_id = vb.id
JOIN project_files pf ON ws.file_id = pf.id
WHERE ws.staged = 1;

CREATE VIEW IF NOT EXISTS vcs_changes_view AS
SELECT
    ws.id,
    ws.project_id,
    p.slug as project_slug,
    ws.branch_id,
    vb.branch_name,
    ws.file_id,
    pf.file_path,
    ws.state,
    ws.staged,
    ws.content_hash,
    ws.file_size_bytes,
    CASE WHEN ws.staged = 1 THEN 'Staged' ELSE 'Not Staged' END as stage_status,
    ws.last_modified,
    ws.staged_at
FROM vcs_working_state_new ws
JOIN projects p ON ws.project_id = p.id
JOIN vcs_branches vb ON ws.branch_id = vb.id
JOIN project_files pf ON ws.file_id = pf.id
WHERE ws.state != 'unmodified'
ORDER BY ws.staged DESC, ws.state, pf.file_path;

-- Create view for git status-like output
CREATE VIEW IF NOT EXISTS vcs_status_view AS
SELECT
    p.slug as project,
    vb.branch_name as branch,
    (SELECT commit_hash FROM vcs_commits
     WHERE branch_id = ws.branch_id
     ORDER BY commit_timestamp DESC LIMIT 1) as head_commit,
    COUNT(CASE WHEN ws.staged = 1 THEN 1 END) as staged_files,
    COUNT(CASE WHEN ws.staged = 0 AND ws.state != 'unmodified' THEN 1 END) as unstaged_files,
    COUNT(CASE WHEN ws.state = 'added' THEN 1 END) as new_files,
    COUNT(CASE WHEN ws.state = 'modified' THEN 1 END) as modified_files,
    COUNT(CASE WHEN ws.state = 'deleted' THEN 1 END) as deleted_files,
    COUNT(CASE WHEN ws.state = 'conflicted' THEN 1 END) as conflicted_files
FROM vcs_working_state_new ws
JOIN projects p ON ws.project_id = p.id
JOIN vcs_branches vb ON ws.branch_id = vb.id
GROUP BY ws.project_id, ws.branch_id;

-- Drop old tables
DROP TABLE IF EXISTS vcs_working_state;
DROP TABLE IF EXISTS vcs_staging;

-- Rename new table
ALTER TABLE vcs_working_state_new RENAME TO vcs_working_state;

-- Recreate indexes with correct names
DROP INDEX IF EXISTS idx_vcs_working_state_new_project_branch;
DROP INDEX IF EXISTS idx_vcs_working_state_new_file;
DROP INDEX IF EXISTS idx_vcs_working_state_new_state;
DROP INDEX IF EXISTS idx_vcs_working_state_new_staged;
DROP INDEX IF EXISTS idx_vcs_working_state_new_modified;

CREATE INDEX idx_vcs_working_state_project_branch ON vcs_working_state(project_id, branch_id);
CREATE INDEX idx_vcs_working_state_file ON vcs_working_state(file_id);
CREATE INDEX idx_vcs_working_state_state ON vcs_working_state(state);
CREATE INDEX idx_vcs_working_state_staged ON vcs_working_state(project_id, branch_id, staged);
CREATE INDEX idx_vcs_working_state_modified ON vcs_working_state(last_modified);

-- Create trigger to auto-update staged_at timestamp
CREATE TRIGGER IF NOT EXISTS update_staged_at_timestamp
AFTER UPDATE ON vcs_working_state
FOR EACH ROW
WHEN NEW.staged = 1 AND OLD.staged = 0
BEGIN
    UPDATE vcs_working_state SET staged_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- Create trigger to auto-update last_modified timestamp
CREATE TRIGGER IF NOT EXISTS update_vcs_working_state_modified
AFTER UPDATE ON vcs_working_state
FOR EACH ROW
WHEN NEW.content_hash != OLD.content_hash OR NEW.state != OLD.state
BEGIN
    UPDATE vcs_working_state SET last_modified = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

COMMIT;

-- Verify migration
SELECT
    'vcs_working_state' as table_name,
    COUNT(*) as total_entries,
    COUNT(DISTINCT project_id) as projects,
    COUNT(DISTINCT branch_id) as branches,
    COUNT(CASE WHEN staged = 1 THEN 1 END) as staged_files,
    COUNT(CASE WHEN staged = 0 AND state != 'unmodified' THEN 1 END) as unstaged_changes,
    COUNT(CASE WHEN state = 'modified' THEN 1 END) as modified,
    COUNT(CASE WHEN state = 'added' THEN 1 END) as added,
    COUNT(CASE WHEN state = 'deleted' THEN 1 END) as deleted
FROM vcs_working_state;
