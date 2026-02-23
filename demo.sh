#!/usr/bin/env bash
# ProjectDB Feature Demo

DB="$HOME/.local/share/templedb/templedb.sqlite"

echo "=== ProjectDB Feature Demo ==="
echo ""

# 1. Show VCS status
echo "📊 VCS Status:"
sqlite3 "$DB" <<EOF
.mode column
.headers on
SELECT
    branch_name AS "Branch",
    SUBSTR(head_commit, 1, 8) AS "Head",
    total_commits AS "Commits",
    last_author AS "Author",
    SUBSTR(last_message, 1, 40) AS "Message"
FROM vcs_branch_summary_view
WHERE project_slug = 'woofs_projects';
EOF
echo ""

# 2. Show file statistics
echo "📁 File Statistics:"
sqlite3 "$DB" <<EOF
.mode column
.headers on
SELECT
    type_name AS "Type",
    COUNT(*) AS "Count",
    SUM(lines_of_code) AS "Lines"
FROM files_with_types_view
WHERE project_slug = 'woofs_projects'
GROUP BY type_name
ORDER BY COUNT(*) DESC
LIMIT 10;
EOF
echo ""

# 3. Show recent file changes
echo "📝 Recent File Changes:"
sqlite3 "$DB" <<EOF
.mode column
.headers on
SELECT
    SUBSTR(COALESCE(fce.new_file_path, pf.file_path), 1, 40) AS "File",
    fce.event_type AS "Event",
    SUBSTR(fce.author, 1, 15) AS "Author",
    SUBSTR(fce.event_timestamp, 1, 16) AS "Time"
FROM file_change_events fce
LEFT JOIN project_files pf ON fce.file_id = pf.id
ORDER BY fce.event_timestamp DESC
LIMIT 10;
EOF
echo ""

# 4. Show uncommitted changes (if any)
echo "🔄 Uncommitted Changes:"
CHANGES=$(sqlite3 "$DB" "SELECT COUNT(*) FROM vcs_changes_view WHERE project_slug = 'woofs_projects'")
if [ "$CHANGES" -eq 0 ]; then
    echo "  Working directory clean ✓"
else
    sqlite3 "$DB" <<EOF
.mode column
.headers on
SELECT
    SUBSTR(file_path, 1, 50) AS "File",
    change_status AS "Status"
FROM vcs_changes_view
WHERE project_slug = 'woofs_projects'
LIMIT 20;
EOF
fi
echo ""

# 5. Show deployments
echo "🚀 Deployment Targets:"
DEPLOYS=$(sqlite3 "$DB" "SELECT COUNT(*) FROM deployment_targets WHERE project_id = 3")
if [ "$DEPLOYS" -eq 0 ]; then
    echo "  No deployment targets configured"
else
    sqlite3 "$DB" <<EOF
.mode column
.headers on
SELECT
    target_name AS "Name",
    target_type AS "Type",
    provider AS "Provider",
    region AS "Region"
FROM deployment_targets
WHERE project_id = 3;
EOF
fi
echo ""

# 6. Show SQL objects
echo "🗄️  SQL Objects (sample):"
sqlite3 "$DB" <<EOF
.mode column
.headers on
SELECT
    so.object_type AS "Type",
    COUNT(*) AS "Count"
FROM sql_objects so
JOIN project_files pf ON so.file_id = pf.id
WHERE pf.project_id = 3
GROUP BY so.object_type
ORDER BY COUNT(*) DESC;
EOF
echo ""

# 7. Database size
echo "💾 Database Info:"
SIZE=$(du -h "$DB" | cut -f1)
echo "  Location: $DB"
echo "  Size: $SIZE"
echo "  Tables: $(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='table'")"
echo "  Views: $(sqlite3 "$DB" "SELECT COUNT(*) FROM sqlite_master WHERE type='view'")"
echo ""

echo "=== Quick Commands ==="
echo ""
echo "Launch TUI:"
echo "  ./templedb-tui"
echo ""
echo "Generate LLM context:"
echo "  python3 src/llm_context.py schema"
echo "  python3 src/llm_context.py project -p woofs_projects"
echo ""
echo "Query VCS:"
echo "  sqlite3 $DB 'SELECT * FROM vcs_branch_summary_view'"
echo "  sqlite3 $DB 'SELECT * FROM vcs_changes_view'"
echo ""
echo "See UPDATES.md for full documentation"
echo ""
