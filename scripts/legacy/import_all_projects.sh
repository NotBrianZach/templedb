#!/usr/bin/env bash
# Import all projects from /home/zach/projects/ into templeDB

set -e

DB="$HOME/.local/share/templedb/templedb.sqlite"
PROJECTS_DIR="/home/zach/projects"
PROJECTDB_DIR="/home/zach/templeDB"

echo "🔄 Importing all projects into templeDB"
echo ""

# Function to import a project
import_project() {
    local project_path="$1"
    local project_name=$(basename "$project_path")
    local slug=$(echo "$project_name" | tr '[:upper:]' '[:lower:]' | tr ' ' '_')

    echo "📦 Processing: $project_name"

    # Check if project already exists
    existing=$(sqlite3 "$DB" "SELECT id FROM projects WHERE slug = '$slug'")

    if [ -n "$existing" ]; then
        echo "   ℹ️  Already exists (ID: $existing), updating..."
        project_id=$existing
        sqlite3 "$DB" "UPDATE projects SET repo_url = '$project_path', updated_at = datetime('now') WHERE id = $project_id"
    else
        echo "   ✨ Creating new project..."
        sqlite3 "$DB" <<EOF
INSERT INTO projects (slug, name, repo_url, git_branch, created_at, updated_at)
VALUES ('$slug', '$project_name', '$project_path', 'master', datetime('now'), datetime('now'));
EOF
        project_id=$(sqlite3 "$DB" "SELECT id FROM projects WHERE slug = '$slug'")
        echo "   ✓ Created (ID: $project_id)"
    fi

    # Populate files
    echo "   📁 Scanning files..."
    cd "$PROJECTDB_DIR"
    node src/populate_project.cjs "$project_path" "$slug" 2>&1 | grep -E "(Found|Analyzed|inserted)" | sed 's/^/      /'

    # Store file contents
    echo "   💾 Storing file contents..."
    PROJECT_ROOT="$project_path" PROJECT_SLUG="$slug" node src/populate_file_contents.cjs 2>&1 | grep -E "(Found|Processed|created)" | sed 's/^/      /'

    # Initialize VCS
    echo "   🌿 Initializing VCS..."
    sqlite3 "$DB" <<EOF
-- Create main branch if not exists
INSERT OR IGNORE INTO vcs_branches (project_id, branch_name, is_default, created_by)
VALUES ($project_id, 'master', 1, '$USER');

-- Create initial commit
INSERT OR IGNORE INTO vcs_commits (
    project_id, branch_id, commit_hash, author, author_email, commit_message, files_changed
)
SELECT
    $project_id, b.id, hex(randomblob(32)), '$USER', '$USER@localhost',
    'Initial import of $project_name',
    (SELECT COUNT(*) FROM project_files WHERE project_id = $project_id)
FROM vcs_branches b
WHERE b.project_id = $project_id AND b.branch_name = 'master'
AND NOT EXISTS (SELECT 1 FROM vcs_commits WHERE project_id = $project_id);

-- Initialize working state
INSERT OR IGNORE INTO vcs_working_state (
    project_id, branch_id, file_id, content_text, content_hash, state
)
SELECT pf.project_id, b.id, pf.id, fc.content_text, fc.hash_sha256, 'unmodified'
FROM project_files pf
JOIN file_contents fc ON fc.file_id = pf.id
JOIN vcs_branches b ON b.project_id = pf.project_id AND b.is_default = 1
WHERE pf.project_id = $project_id;

-- Create file states for initial commit
INSERT OR IGNORE INTO vcs_file_states (
    commit_id, file_id, content_text, content_hash, file_size, line_count, change_type
)
SELECT c.id, pf.id, fc.content_text, fc.hash_sha256, fc.file_size_bytes, fc.line_count, 'added'
FROM vcs_commits c
JOIN project_files pf ON pf.project_id = c.project_id
JOIN file_contents fc ON fc.file_id = pf.id
WHERE c.project_id = $project_id
AND c.commit_message = 'Initial import of $project_name';
EOF
    echo "   ✓ VCS initialized"
    echo ""
}

# Find all project directories
echo "Scanning $PROJECTS_DIR for projects..."
echo ""

for dir in "$PROJECTS_DIR"/*; do
    if [ -d "$dir" ]; then
        # Skip hidden directories and special dirs
        basename_dir=$(basename "$dir")
        if [[ "$basename_dir" == .* ]] || [[ "$basename_dir" == "stuff" ]]; then
            echo "⏭️  Skipping: $basename_dir"
            continue
        fi

        import_project "$dir"
    fi
done

# Show summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📊 Import Summary"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

sqlite3 "$DB" <<'EOF'
.mode column
.headers on

SELECT
    slug AS "Project",
    (SELECT COUNT(*) FROM project_files WHERE project_id = p.id) AS "Files",
    (SELECT SUM(lines_of_code) FROM project_files WHERE project_id = p.id) AS "Lines",
    (SELECT COUNT(*) FROM vcs_commits WHERE project_id = p.id) AS "Commits"
FROM projects p
ORDER BY slug;

SELECT '' AS "";
SELECT 'Total Projects: ' || COUNT(*) AS "Summary" FROM projects
UNION ALL
SELECT 'Total Files: ' || COUNT(*) FROM project_files
UNION ALL
SELECT 'Total Lines: ' || SUM(lines_of_code) FROM project_files;
EOF

echo ""
echo "✅ Import complete!"
echo ""
echo "Try:"
echo "  cd ~/templeDB"
echo "  ./templedb-tui  # Browse all projects"
echo "  python3 src/llm_context.py schema  # View database schema"
echo ""
