#!/usr/bin/env bash
# Dogfood templeDB - have it manage itself!

set -e

DB="$HOME/.local/share/templedb/templedb.sqlite"
PROJECT_ROOT="/home/zach/projects/system_config/templeDB"

echo "🐕 Dogfooding templeDB - managing itself!"
echo ""

# 1. Add templeDB as a project
echo "1️⃣  Adding templeDB project to database..."
sqlite3 "$DB" <<EOF
INSERT OR IGNORE INTO projects (slug, name, repo_url, git_branch, git_ref)
VALUES (
    'templeDB',
    'ProjectDB - Database-native Project Management',
    'https://github.com/NotBrianZach/system_config',
    'master',
    ''
);
EOF

PROJECT_ID=$(sqlite3 "$DB" "SELECT id FROM projects WHERE slug = 'templeDB'")
echo "   ✓ Project ID: $PROJECT_ID"
echo ""

# 2. Populate files
echo "2️⃣  Scanning and populating templeDB files..."
cd "$PROJECT_ROOT"
node src/populate_templedb_files.cjs "$PROJECT_ROOT" "$PROJECT_ID" 2>&1 | tail -5
echo ""

# 3. Store file contents
echo "3️⃣  Storing file contents in database..."
node src/populate_file_contents.cjs "$PROJECT_ID" 2>&1 | tail -5
echo ""

# 4. Initialize VCS
echo "4️⃣  Initializing VCS for templeDB..."
sqlite3 "$DB" <<EOF
-- Create main branch
INSERT OR IGNORE INTO vcs_branches (project_id, branch_name, is_default, created_by)
VALUES ($PROJECT_ID, 'master', 1, '$USER');

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
    $PROJECT_ID,
    b.id,
    hex(randomblob(32)),
    '$USER',
    '$USER@localhost',
    'Initial commit - templeDB managing itself',
    (SELECT COUNT(*) FROM project_files WHERE project_id = $PROJECT_ID)
FROM vcs_branches b
WHERE b.project_id = $PROJECT_ID AND b.branch_name = 'master'
AND NOT EXISTS (
    SELECT 1 FROM vcs_commits WHERE project_id = $PROJECT_ID
);

-- Initialize working state
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
JOIN vcs_branches b ON b.project_id = pf.project_id AND b.is_default = 1
WHERE pf.project_id = $PROJECT_ID;

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
JOIN project_files pf ON pf.project_id = c.project_id
JOIN file_contents fc ON fc.file_id = pf.id
WHERE c.project_id = $PROJECT_ID
AND c.commit_message = 'Initial commit - templeDB managing itself';
EOF
echo "   ✓ VCS initialized"
echo ""

# 5. Show statistics
echo "📊 ProjectDB Stats:"
sqlite3 "$DB" <<EOF
.mode column
.headers on

SELECT 'Files tracked' AS "Metric", COUNT(*) AS "Value"
FROM project_files WHERE project_id = $PROJECT_ID
UNION ALL
SELECT 'Total lines of code', SUM(lines_of_code)
FROM project_files WHERE project_id = $PROJECT_ID
UNION ALL
SELECT 'File contents stored', COUNT(*)
FROM file_contents fc
JOIN project_files pf ON fc.file_id = pf.id
WHERE pf.project_id = $PROJECT_ID
UNION ALL
SELECT 'VCS commits', COUNT(*)
FROM vcs_commits WHERE project_id = $PROJECT_ID;
EOF
echo ""

echo "📁 File Types:"
sqlite3 "$DB" <<EOF
.mode column
.headers on
SELECT
    type_name AS "Type",
    COUNT(*) AS "Count",
    SUM(lines_of_code) AS "Lines"
FROM files_with_types_view
WHERE project_id = $PROJECT_ID
GROUP BY type_name
ORDER BY COUNT(*) DESC;
EOF
echo ""

echo "✨ Success! ProjectDB is now managing itself!"
echo ""
echo "Try these commands:"
echo ""
echo "  # Use TUI to edit templeDB's own code:"
echo "  ./templedb-tui"
echo "  # Press SPC -> f -> search for 'templedb_tui' -> c to edit"
echo ""
echo "  # Query templeDB's files:"
echo "  sqlite3 $DB \\"
echo "    \"SELECT file_path, type_name, lines_of_code \\"
echo "     FROM files_with_types_view \\"
echo "     WHERE project_slug = 'templeDB' \\"
echo "     ORDER BY lines_of_code DESC LIMIT 10\""
echo ""
echo "  # View templeDB's VCS status:"
echo "  sqlite3 $DB \\"
echo "    \"SELECT * FROM vcs_branch_summary_view \\"
echo "     WHERE project_slug = 'templeDB'\""
echo ""
echo "  # Generate LLM context for templeDB itself:"
echo "  python3 src/llm_context.py project -p templeDB"
echo ""
