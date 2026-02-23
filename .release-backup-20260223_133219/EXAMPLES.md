# templedb Query Examples

Quick reference for querying your project database.

## Database Stats

**Current Status (woofs_projects):**
- **338 files** stored with full contents
- **3.2 MB** of source code
- **7.2 MB** total database size
- **338 versions** created

## Common Queries

### File Content Retrieval

```sql
-- Get current content of a file
SELECT content_text
FROM current_file_contents_view
WHERE file_path = 'shopUI/src/BookingForm.jsx';

-- Get all JSX component contents
SELECT file_path, content_text
FROM current_file_contents_view
WHERE type_name = 'jsx_component';

-- Get file with metadata
SELECT file_path, line_count, file_size_bytes, hash_sha256, updated_at
FROM current_file_contents_view
WHERE file_path = 'shopUI/src/BookingForm.jsx';
```

### Code Search

```sql
-- Find files containing specific text
SELECT file_path, type_name
FROM current_file_contents_view
WHERE content_text LIKE '%useState%';

-- Find React components using specific hooks
SELECT file_path
FROM current_file_contents_view
WHERE type_name = 'jsx_component'
  AND content_text LIKE '%useEffect%';

-- Find all files importing a specific module
SELECT file_path
FROM current_file_contents_view
WHERE content_text LIKE '%import%supabase%';

-- Case-insensitive search
SELECT file_path
FROM current_file_contents_view
WHERE LOWER(content_text) LIKE '%bookingform%';
```

### File Statistics

```sql
-- Largest files by line count
SELECT file_path, line_count, file_size_bytes
FROM current_file_contents_view
ORDER BY line_count DESC
LIMIT 10;

-- Code statistics by file type
SELECT
  type_name,
  COUNT(*) as files,
  SUM(line_count) as total_lines,
  SUM(file_size_bytes) as total_bytes,
  AVG(line_count) as avg_lines
FROM current_file_contents_view
GROUP BY type_name
ORDER BY total_bytes DESC;

-- Total project statistics
SELECT
  COUNT(*) as total_files,
  SUM(line_count) as total_lines,
  SUM(file_size_bytes) as total_bytes,
  ROUND(AVG(line_count), 2) as avg_lines_per_file
FROM current_file_contents_view;
```

### Version History

```sql
-- All versions of a specific file
SELECT version_number, author, commit_message, created_at
FROM file_version_history_view
WHERE file_path = 'shopUI/src/BookingForm.jsx'
ORDER BY version_number DESC;

-- Recent file changes
SELECT file_path, version_number, author, commit_message, created_at
FROM file_version_history_view
ORDER BY created_at DESC
LIMIT 20;

-- Files with most versions
SELECT file_path, COUNT(*) as version_count
FROM file_version_history_view
GROUP BY file_path
ORDER BY version_count DESC
LIMIT 10;
```

### Author Statistics

```sql
-- Files modified by author
SELECT author, COUNT(*) as files_modified
FROM file_version_history_view
GROUP BY author;

-- Lines of code by author
SELECT
  author,
  SUM(lines_added) as total_lines_added,
  SUM(lines_removed) as total_lines_removed
FROM file_version_history_view
GROUP BY author;

-- Most recent activity by author
SELECT author, MAX(created_at) as last_activity
FROM file_version_history_view
GROUP BY author;
```

### Change Timeline

```sql
-- Recent changes across all files
SELECT file_path, event_type, author, event_timestamp, commit_message
FROM file_change_timeline_view
ORDER BY event_timestamp DESC
LIMIT 20;

-- Changes to a specific file
SELECT event_type, author, event_timestamp, commit_message
FROM file_change_timeline_view
WHERE file_path = 'shopUI/src/BookingForm.jsx'
ORDER BY event_timestamp DESC;

-- Changes in last 24 hours
SELECT file_path, event_type, author
FROM file_change_timeline_view
WHERE event_timestamp > datetime('now', '-1 day')
ORDER BY event_timestamp DESC;
```

### File Metadata

```sql
-- Recently modified files
SELECT file_path, updated_at
FROM current_file_contents_view
ORDER BY updated_at DESC
LIMIT 20;

-- Files by hash (find duplicates)
SELECT hash_sha256, GROUP_CONCAT(file_path, ', ') as files
FROM current_file_contents_view
GROUP BY hash_sha256
HAVING COUNT(*) > 1;

-- Files by encoding
SELECT encoding, COUNT(*) as count
FROM current_file_contents_view
GROUP BY encoding;
```

### Combined Queries (File Tracking + Versioning)

```sql
-- React components with their git info
SELECT
  pf.file_path,
  pf.component_name,
  fc.line_count,
  fv.author,
  fv.git_commit_hash,
  fv.git_branch
FROM project_files pf
JOIN file_contents fc ON pf.id = fc.file_id
JOIN file_versions fv ON pf.id = fv.file_id
JOIN file_types ft ON pf.file_type_id = ft.id
WHERE ft.type_name = 'jsx_component'
  AND fv.version_number = (
    SELECT MAX(version_number)
    FROM file_versions
    WHERE file_id = pf.id
  );

-- Edge functions with content
SELECT
  pf.file_path,
  ef.function_name,
  ef.endpoint_path,
  fc.line_count,
  fc.content_text
FROM project_files pf
JOIN edge_functions ef ON pf.id = ef.file_id
JOIN file_contents fc ON pf.id = fc.file_id;
```

### Database Maintenance

```sql
-- Database size
SELECT page_count * page_size / 1024.0 / 1024.0 as size_mb
FROM pragma_page_count(), pragma_page_size();

-- Table sizes
SELECT
  name,
  SUM(pgsize) / 1024.0 / 1024.0 as size_mb
FROM dbstat
WHERE name IN ('file_contents', 'file_versions', 'project_files')
GROUP BY name;

-- Vacuum database
VACUUM;

-- Analyze for query optimization
ANALYZE;
```

## Shell Commands

### Quick Queries

```bash
# Get file content
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT content_text FROM current_file_contents_view WHERE file_path = 'shopUI/src/BookingForm.jsx'"

# Find files with useState
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT file_path FROM current_file_contents_view WHERE content_text LIKE '%useState%'"

# Count total lines of code
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT SUM(line_count) FROM current_file_contents_view"

# Export file content to disk
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT content_text FROM current_file_contents_view WHERE file_path = 'shopUI/src/BookingForm.jsx'" \
  > /tmp/BookingForm.jsx
```

### Export Data

```bash
# Export all file paths and line counts
sqlite3 -csv ~/.local/share/templedb/templedb.sqlite \
  "SELECT file_path, line_count FROM current_file_contents_view" \
  > file_stats.csv

# Export version history
sqlite3 -csv ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM file_version_history_view" \
  > version_history.csv

# Export all JSX components
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT file_path, content_text FROM current_file_contents_view WHERE type_name = 'jsx_component'" \
  > all_jsx_components.txt
```

## Advanced Use Cases

### Code Analysis

```sql
-- Find components with complex logic (high line count)
SELECT file_path, line_count
FROM current_file_contents_view
WHERE type_name = 'jsx_component'
  AND line_count > 500
ORDER BY line_count DESC;

-- Find files with TODO comments
SELECT file_path, type_name
FROM current_file_contents_view
WHERE content_text LIKE '%TODO%'
   OR content_text LIKE '%FIXME%';

-- Find console.log statements
SELECT file_path
FROM current_file_contents_view
WHERE content_text LIKE '%console.log%';
```

### Dependency Analysis

```sql
-- Find what imports React
SELECT file_path
FROM current_file_contents_view
WHERE content_text LIKE '%import%React%';

-- Find Supabase client usage
SELECT file_path, type_name
FROM current_file_contents_view
WHERE content_text LIKE '%supabaseClient%'
   OR content_text LIKE '%createClient%';
```

### Deployment Preparation

```sql
-- Tag current versions as production
INSERT INTO version_tags (version_id, tag_name, tag_type, description)
SELECT
  fv.id,
  'production-2026-02-21',
  'release',
  'Production deployment Feb 21, 2026'
FROM file_versions fv
WHERE fv.version_number = (
  SELECT MAX(version_number)
  FROM file_versions
  WHERE file_id = fv.file_id
);

-- Create snapshot before deployment
INSERT INTO file_snapshots (
  file_id, snapshot_name, snapshot_reason,
  content_text, content_blob, content_type,
  file_size_bytes, hash_sha256
)
SELECT
  file_id,
  'pre-deploy-' || date('now'),
  'before-deploy',
  content_text,
  content_blob,
  content_type,
  file_size_bytes,
  hash_sha256
FROM file_contents
WHERE is_current = 1;
```

## Tips

1. **Use LIKE for fuzzy matching**: `WHERE content_text LIKE '%pattern%'`
2. **Case-insensitive search**: `WHERE LOWER(content_text) LIKE '%pattern%'`
3. **Limit results for performance**: Always add `LIMIT` for large result sets
4. **Use views**: Pre-defined views join tables for convenience
5. **Export results**: Use `-csv` or `-json` modes in sqlite3
6. **Backup before queries**: The database is precious!

## Performance

For large databases:

```sql
-- Create custom indexes
CREATE INDEX idx_content_text_search ON file_contents(content_text);

-- Use FTS5 for full-text search (advanced)
CREATE VIRTUAL TABLE file_content_fts USING fts5(file_path, content_text);
```

---

**See also:**
- `FILE_VERSIONING.md` - Complete versioning documentation
- `FILE_TRACKING.md` - File tracking documentation
- `README.md` - System overview
