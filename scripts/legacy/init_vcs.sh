#!/usr/bin/env bash
# Initialize VCS for woofs_projects

DB_PATH="$HOME/.local/share/templedb/templedb.sqlite"

echo "Initializing VCS for woofs_projects..."

# Create default branch
sqlite3 "$DB_PATH" <<EOF
-- Get project_id
.mode list

-- Create main branch if not exists
INSERT OR IGNORE INTO vcs_branches (project_id, branch_name, is_default, created_by)
SELECT id, 'main', 1, '$USER'
FROM projects
WHERE slug = 'woofs_projects';

-- Create initial commit
INSERT OR IGNORE INTO vcs_commits (
    project_id,
    branch_id,
    commit_hash,
    author,
    author_email,
    commit_message,
    files_changed
)
SELECT
    p.id,
    b.id,
    hex(randomblob(32)),
    '$USER',
    '$USER@localhost',
    'Initial commit - imported from filesystem',
    (SELECT COUNT(*) FROM project_files WHERE project_id = p.id)
FROM projects p
JOIN vcs_branches b ON b.project_id = p.id AND b.branch_name = 'main'
WHERE p.slug = 'woofs_projects'
AND NOT EXISTS (
    SELECT 1 FROM vcs_commits WHERE project_id = p.id
);

-- Initialize working state for all files
INSERT OR IGNORE INTO vcs_working_state (
    project_id,
    branch_id,
    file_id,
    content_text,
    content_blob,
    content_hash,
    state,
    staged
)
SELECT
    pf.project_id,
    b.id,
    pf.id,
    fc.content_text,
    fc.content_blob,
    fc.hash_sha256,
    'unmodified',
    0
FROM project_files pf
JOIN file_contents fc ON fc.file_id = pf.id
JOIN projects p ON p.id = pf.project_id
JOIN vcs_branches b ON b.project_id = p.id AND b.is_default = 1
WHERE p.slug = 'woofs_projects';

-- Create file states for initial commit
INSERT OR IGNORE INTO vcs_file_states (
    commit_id,
    file_id,
    content_text,
    content_blob,
    content_hash,
    file_size,
    line_count,
    change_type
)
SELECT
    c.id,
    pf.id,
    fc.content_text,
    fc.content_blob,
    fc.hash_sha256,
    fc.file_size_bytes,
    fc.line_count,
    'added'
FROM vcs_commits c
JOIN projects p ON p.id = c.project_id
JOIN project_files pf ON pf.project_id = p.id
JOIN file_contents fc ON fc.file_id = pf.id
WHERE p.slug = 'woofs_projects'
AND c.commit_message = 'Initial commit - imported from filesystem';

EOF

echo "✓ VCS initialized"
echo ""
echo "Summary:"
sqlite3 "$DB_PATH" "
SELECT
    'Branch: ' || branch_name || ' (head: ' || SUBSTR(head_commit, 1, 8) || ')'
FROM vcs_branch_summary_view
WHERE project_slug = 'woofs_projects';

SELECT
    'Total commits: ' || COUNT(*)
FROM vcs_commits c
JOIN projects p ON p.id = c.project_id
WHERE p.slug = 'woofs_projects';

SELECT
    'Working files: ' || COUNT(*)
FROM vcs_working_state ws
JOIN projects p ON p.id = ws.project_id
WHERE p.slug = 'woofs_projects';
"
