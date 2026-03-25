# TempleDB Query Best Practices

## Critical Constraint: File Paths Are NOT Unique

### The Issue

**File paths are only unique within a project, NOT globally.**

Multiple projects can have files with the same path:
- `README.md`
- `src/index.ts`
- `package.json`
- `migrations/001_init.sql`

### The Rule

**ALWAYS filter by project when querying files by path.**

### ❌ WRONG - Will return wrong file if multiple projects have the same path

```sql
-- BAD: No project filter
SELECT * FROM project_files WHERE file_path = 'README.md';

-- BAD: Will get content from wrong project
SELECT content_text
FROM file_contents fc
JOIN project_files pf ON fc.file_id = pf.id
WHERE pf.file_path = 'src/index.ts';
```

### ✅ CORRECT - Always include project filter

```sql
-- GOOD: Filter by project_id
SELECT * FROM project_files
WHERE project_id = ? AND file_path = 'README.md';

-- GOOD: Filter by project_id in subquery
SELECT content_text
FROM file_contents fc
JOIN project_files pf ON fc.file_id = pf.id
WHERE pf.project_id = (SELECT id FROM projects WHERE slug = 'my-project')
  AND pf.file_path = 'src/index.ts';

-- GOOD: Use views that include project_slug
SELECT content_text
FROM current_file_contents_view
WHERE project_slug = 'my-project'
  AND file_path = 'src/index.ts';
```

## Performance Considerations

### Composite Index

A composite index on `(project_id, file_path)` ensures efficient lookups:

```sql
CREATE INDEX idx_project_files_project_path
ON project_files(project_id, file_path);
```

This index is created automatically in TempleDB.

### Query Patterns

**Fast (uses index):**
```sql
WHERE project_id = ? AND file_path = ?
```

**Slow (requires full scan):**
```sql
WHERE file_path = ?  -- Missing project filter!
```

## Common Queries

### Get File Content

```sql
-- Using current_file_contents_view (recommended)
SELECT content_text, content_type, file_size_bytes
FROM current_file_contents_view
WHERE project_slug = 'my-project'
  AND file_path = 'src/app.ts';

-- Using joins (when you need more control)
SELECT cb.content_text, cb.content_type, fc.file_size_bytes
FROM project_files pf
JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
WHERE pf.project_id = (SELECT id FROM projects WHERE slug = 'my-project')
  AND pf.file_path = 'src/app.ts';
```

### Get File Metadata

```sql
-- Using files_with_types_view (recommended)
SELECT file_path, type_name, lines_of_code, file_size_bytes
FROM files_with_types_view
WHERE project_slug = 'my-project'
  AND file_path = 'src/app.ts';

-- Using base table
SELECT pf.*, ft.type_name
FROM project_files pf
LEFT JOIN file_types ft ON pf.file_type_id = ft.id
WHERE pf.project_id = (SELECT id FROM projects WHERE slug = 'my-project')
  AND pf.file_path = 'src/app.ts';
```

### Get File Version History

```sql
SELECT version_number, author, commit_message, created_at
FROM file_version_history_view
WHERE project_slug = 'my-project'
  AND file_path = 'src/app.ts'
ORDER BY version_number DESC;
```

### Find Files by Pattern

```sql
-- Find all TypeScript files in a project
SELECT file_path, lines_of_code
FROM files_with_types_view
WHERE project_slug = 'my-project'
  AND type_name = 'typescript'
ORDER BY lines_of_code DESC;

-- Find files matching glob pattern
SELECT file_path
FROM project_files
WHERE project_id = (SELECT id FROM projects WHERE slug = 'my-project')
  AND file_path GLOB 'src/**/*.ts'
ORDER BY file_path;
```

## API Usage

When using the Python API, always pass `project_slug` or `project_id`:

```python
from llm_context import LLMContext

context = LLMContext()

# GOOD: Includes project_slug
file_content = context.get_file_content('my-project', 'src/app.ts')

# GOOD: Query with project filter
files = context.query("""
    SELECT file_path, lines_of_code
    FROM project_files
    WHERE project_id = (SELECT id FROM projects WHERE slug = 'my-project')
      AND file_path LIKE 'src/%'
""")
```

## Migration and Import Code

When writing migration or import code:

```python
# GOOD: Always include project_id
cursor.execute("""
    SELECT id FROM project_files
    WHERE project_id = ? AND file_path = ?
""", (project_id, file_path))

# GOOD: Update with project scope
cursor.execute("""
    UPDATE project_files
    SET lines_of_code = ?
    WHERE project_id = ? AND file_path = ?
""", (lines, project_id, file_path))
```

## Views That Handle This Automatically

These views include `project_slug`, so they're safer:

- `files_with_types_view` - Always filter by `project_slug`
- `current_file_contents_view` - Always filter by `project_slug`
- `file_version_history_view` - Always filter by `project_slug`
- `vcs_branch_summary_view` - Always filter by `project_slug`

```sql
-- These views require project_slug, so they're safe
SELECT * FROM files_with_types_view WHERE project_slug = 'my-project';
SELECT * FROM current_file_contents_view WHERE project_slug = 'my-project';
```

## Checklist for New Queries

Before running a query that involves `file_path`:

- [ ] Does it filter by `project_id` or `project_slug`?
- [ ] If using `project_files` directly, is `project_id` in the WHERE clause?
- [ ] If using views, is `project_slug` in the WHERE clause?
- [ ] Can multiple projects have this file path?

## Summary

**The Golden Rule:**

> File paths are NOT globally unique. ALWAYS filter by project when querying by path.

**Safe Pattern:**
```sql
WHERE project_id = ? AND file_path = ?
```

**Unsafe Pattern:**
```sql
WHERE file_path = ?  -- ❌ WRONG!
```

Following this rule prevents cross-project data corruption and ensures correct query results.
