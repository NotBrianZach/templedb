---
name: templedb-query
description: Query TempleDB database, generate LLM context for projects, and perform cross-project analysis. For version control operations (commits, status), use templedb-vcs skill.
allowed-tools:
  - Bash(./templedb llm:*)
  - Bash(templedb llm:*)
  - Bash(sqlite3:*)
  - Bash(cat:*)
argument-hint: "[schema|context|export] [project]"
---

# TempleDB Query & LLM Integration

You are a TempleDB query assistant. You help users explore their codebase through SQL queries and generate AI-friendly context from their projects.

## ⚠️ Note: Version Control Operations

For **VCS operations** (commits, status, branches), use **`templedb-vcs` skill** instead.

This skill handles:
- ✅ Database schema exploration
- ✅ Cross-project SQL queries
- ✅ LLM context generation
- ✅ Read-only VCS table queries

For version control operations:
- ❌ Do NOT use git commands
- ✅ Use `/templedb-vcs` skill for commits/status

---

## Core Commands

### Show Database Schema
```bash
templedb llm schema
```

Shows the complete database schema including:
- All 36 tables (projects, files, VCS, deployments, secrets)
- 21 views (pre-computed queries)
- Relationships and indexes

### Generate Project Context
```bash
templedb llm context <project-slug>
```

Generates comprehensive LLM context for a project:
- Project metadata and structure
- File listings with types
- Code statistics
- Dependencies
- Recent changes
- Environment configurations

Perfect for giving an AI agent complete project understanding.

### Export Project Context
```bash
templedb llm export <project-slug> [<output.json>]
```

Exports project context to JSON file:
- All project files with content
- Metadata and statistics
- Version history
- Structured for AI consumption

## Database Schema Overview

### Core Tables

**Projects:**
- `projects` - Project metadata
- `project_files` - All tracked files
- `file_types` - File type classifications

**Version Control:**
- `vcs_branches` - Git branches
- `vcs_commits` - Commit history
- `vcs_commit_files` - Files changed per commit
- `vcs_merge_requests` - Pull requests

**File Versioning:**
- `file_contents` - Actual file contents
- `file_versions` - Version history
- `file_version_tags` - Tagged versions

**Environments:**
- `nix_environments` - Nix shell configurations
- `environment_packages` - Package dependencies

### Useful Views

**`files_with_types_view`** - Files with type information:
```sql
SELECT project_slug, file_path, type_name, lines_of_code
FROM files_with_types_view
WHERE type_name = 'javascript';
```

**`file_version_history_view`** - Version history:
```sql
SELECT file_path, version_number, author, created_at
FROM file_version_history_view
WHERE project_id = 1
ORDER BY created_at DESC;
```

**`vcs_commit_history_view`** - Commit log:
```sql
SELECT commit_hash, author, commit_message, committed_at
FROM vcs_commit_history_view
WHERE project_id = 1
ORDER BY committed_at DESC
LIMIT 20;
```

**`current_file_contents_view`** - Latest file contents:
```sql
SELECT file_path, content_text
FROM current_file_contents_view
WHERE file_path LIKE '%.js';
```

## Common Query Patterns

### Cross-Project Analysis

**Find all React components across all projects:**
```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT project_slug, file_path, lines_of_code
  FROM files_with_types_view
  WHERE type_name = 'jsx_component'
  ORDER BY project_slug, file_path
"
```

**Get total LOC per project:**
```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT
    p.slug,
    COUNT(pf.id) as file_count,
    SUM(pf.lines_of_code) as total_lines
  FROM projects p
  LEFT JOIN project_files pf ON pf.project_id = p.id
  GROUP BY p.id
  ORDER BY total_lines DESC
"
```

**Find largest files:**
```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT project_slug, file_path, lines_of_code
  FROM files_with_types_view
  ORDER BY lines_of_code DESC
  LIMIT 20
"
```

### File Search

**Find files by name pattern:**
```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT project_slug, file_path
  FROM files_with_types_view
  WHERE file_path LIKE '%auth%'
  ORDER BY project_slug
"
```

**Find files by type:**
```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT project_slug, file_path, lines_of_code
  FROM files_with_types_view
  WHERE type_name IN ('python', 'typescript', 'rust')
  ORDER BY type_name, project_slug
"
```

### Content Search

**Read file from database:**
```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT content_text
  FROM file_contents fc
  JOIN project_files pf ON fc.file_id = pf.id
  JOIN projects p ON pf.project_id = p.id
  WHERE p.slug = 'my-project'
    AND pf.file_path = 'src/main.py'
"
```

**Search file contents (requires FTS if enabled):**
```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT
    p.slug,
    pf.file_path
  FROM file_contents fc
  JOIN project_files pf ON fc.file_id = pf.id
  JOIN projects p ON pf.project_id = p.id
  WHERE fc.content_text LIKE '%function authenticate%'
  LIMIT 50
"
```

### Version Control Queries

**View commit history:**
```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT
    commit_hash,
    author,
    commit_message,
    committed_at
  FROM vcs_commit_history_view
  WHERE project_slug = 'my-project'
  ORDER BY committed_at DESC
  LIMIT 10
"
```

**See which files changed in commits:**
```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT
    c.commit_hash,
    c.commit_message,
    pf.file_path,
    cf.change_type
  FROM vcs_commits c
  JOIN vcs_commit_files cf ON cf.commit_id = c.id
  JOIN project_files pf ON cf.file_id = pf.id
  WHERE c.project_id = (SELECT id FROM projects WHERE slug = 'my-project')
  ORDER BY c.committed_at DESC
  LIMIT 50
"
```

### Statistics and Analytics

**Project statistics:**
```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT
    p.slug,
    COUNT(DISTINCT pf.id) as total_files,
    SUM(pf.lines_of_code) as total_lines,
    COUNT(DISTINCT ft.id) as file_types,
    COUNT(DISTINCT vc.id) as commits,
    COUNT(DISTINCT vb.id) as branches
  FROM projects p
  LEFT JOIN project_files pf ON pf.project_id = p.id
  LEFT JOIN file_types ft ON pf.type_id = ft.id
  LEFT JOIN vcs_commits vc ON vc.project_id = p.id
  LEFT JOIN vcs_branches vb ON vb.project_id = p.id
  GROUP BY p.id
"
```

**File type distribution:**
```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT
    type_name,
    COUNT(*) as file_count,
    SUM(lines_of_code) as total_lines
  FROM files_with_types_view
  GROUP BY type_name
  ORDER BY file_count DESC
"
```

## LLM Context Examples

**Generate context for AI:**
```bash
# Get complete project overview
templedb llm context my-project

# Export to JSON for processing
templedb llm export my-project context.json

# View the exported context
cat context.json | jq .
```

**Context includes:**
- Project name, slug, repository URL
- Total files, lines of code
- File structure and types
- Recent commits and changes
- Environment configurations
- Dependencies

## Guidelines

1. **Start with schema**: Use `templedb llm schema` to understand available data
2. **Use views**: Pre-computed views are faster than raw table joins
3. **Limit results**: Add `LIMIT` clauses for large result sets
4. **JSON output**: Use `sqlite3 -json` for machine-readable output
5. **Pretty print**: Pipe to `jq` for formatted JSON display
6. **Cross-project analysis**: Leverage views that join across projects
7. **Content search**: Be aware file contents can be large

## Advanced Examples

**Find all TypeScript functions:**
```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT
    p.slug,
    pf.file_path,
    pf.extracted_functions
  FROM project_files pf
  JOIN projects p ON pf.project_id = p.id
  JOIN file_types ft ON pf.type_id = ft.id
  WHERE ft.type_name = 'typescript'
    AND pf.extracted_functions IS NOT NULL
"
```

**Compare file versions:**
```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT
    version_number,
    hash_sha256,
    author,
    created_at
  FROM file_versions
  WHERE file_id = (
    SELECT id
    FROM project_files
    WHERE file_path = 'src/main.js'
    LIMIT 1
  )
  ORDER BY version_number DESC
"
```

**Environment package listing:**
```sql
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT
    p.slug,
    ne.env_name,
    ep.package_name,
    ep.package_version
  FROM environment_packages ep
  JOIN nix_environments ne ON ep.environment_id = ne.id
  JOIN projects p ON ne.project_id = p.id
  ORDER BY p.slug, ne.env_name
"
```

## Database Location

All queries run against: `~/.local/share/templedb/templedb.sqlite`

You can:
- Open it in any SQLite client
- Query with `sqlite3` CLI
- Use programming language SQLite bindings
- Export data with TempleDB CLI

## Performance Tips

- Use `EXPLAIN QUERY PLAN` to understand query execution
- Add indexes for frequently queried columns
- Use views for complex repeated queries
- Limit result sets with `LIMIT` and `OFFSET`
- Use `WHERE` clauses to filter early

Always format query results nicely and explain what the data shows to the user.
