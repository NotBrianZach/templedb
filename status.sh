#!/usr/bin/env bash
# Show complete status of templeDB

DB="$HOME/.local/share/templedb/templedb.sqlite"

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                     TempleDB Status                            ║"
echo "║            In Honor of Terry Davis (1969-2018)                 ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

sqlite3 "$DB" <<'EOF'
.mode column
.headers on

-- Overall statistics
SELECT '═════ Overall Statistics ═════' AS "";

SELECT
    'Projects' AS "Metric",
    CAST(COUNT(*) AS TEXT) AS "Value"
FROM projects
UNION ALL
SELECT 'Files', CAST(COUNT(*) AS TEXT)
FROM project_files
UNION ALL
SELECT 'Lines of Code', CAST(SUM(lines_of_code) AS TEXT)
FROM project_files
UNION ALL
SELECT 'File Contents Stored', CAST(COUNT(*) AS TEXT)
FROM file_contents
UNION ALL
SELECT 'VCS Commits', CAST(COUNT(*) AS TEXT)
FROM vcs_commits
UNION ALL
SELECT 'VCS Branches', CAST(COUNT(*) AS TEXT)
FROM vcs_branches
UNION ALL
SELECT 'Database Size', '~14MB'
FROM projects LIMIT 1;

SELECT '' AS "";
SELECT '═════ Projects ═════' AS "";

SELECT
    p.slug AS "Project",
    p.repo_url AS "Location",
    (SELECT COUNT(*) FROM project_files WHERE project_id = p.id) AS "Files",
    (SELECT SUM(lines_of_code) FROM project_files WHERE project_id = p.id) AS "Lines",
    (SELECT branch_name FROM vcs_branches WHERE project_id = p.id AND is_default = 1) AS "Branch"
FROM projects p
ORDER BY p.slug;

SELECT '' AS "";
SELECT '═════ File Types Distribution ═════' AS "";

SELECT
    type_name AS "Type",
    COUNT(*) AS "Count",
    SUM(lines_of_code) AS "Lines",
    PRINTF('%.1f%%', 100.0 * COUNT(*) / (SELECT COUNT(*) FROM project_files)) AS "% of Files"
FROM files_with_types_view
GROUP BY type_name
HAVING COUNT(*) > 0
ORDER BY COUNT(*) DESC
LIMIT 15;

SELECT '' AS "";
SELECT '═════ Top 10 Largest Files ═════' AS "";

SELECT
    SUBSTR(file_path, 1, 45) AS "File",
    project_slug AS "Project",
    lines_of_code AS "Lines"
FROM files_with_types_view
ORDER BY lines_of_code DESC
LIMIT 10;

SELECT '' AS "";
SELECT '═════ Recent Activity ═════' AS "";

SELECT
    SUBSTR(commit_message, 1, 40) AS "Commit",
    project_slug AS "Project",
    SUBSTR(commit_timestamp, 1, 16) AS "Time"
FROM vcs_commit_history_view
ORDER BY commit_timestamp DESC
LIMIT 10;

EOF

echo ""
echo "═════════════════════════════════════════════════════════════════"
echo "Location: ~/templeDB"
echo "Database: ~/.local/share/templedb/templedb.sqlite"
echo ""
echo "Quick commands:"
echo "  ./templedb-tui                          # Browse all projects"
echo "  python3 src/llm_context.py schema     # View schema"
echo "  ./import_all_projects.sh              # Re-import projects"
echo "  ./status.sh                            # Show this status"
echo "═════════════════════════════════════════════════════════════════"
