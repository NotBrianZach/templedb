# TempleDB Database Constraints

## Overview

This document lists all uniqueness constraints in TempleDB and explains why they exist. These constraints prevent data corruption and enforce business rules at the database level.

## Critical Uniqueness Constraints

### Projects

```sql
projects:
  slug TEXT NOT NULL UNIQUE
```

**Why:** Project slugs must be globally unique. They're used in CLI commands, URLs, and file paths.

**Example violations prevented:**
- ❌ Two projects with slug "my-app"
- ✓ Only one project can have slug "my-app"

---

### Files Within Projects

```sql
project_files:
  UNIQUE(project_id, file_path)
```

**Why:** File paths must be unique within a project. Multiple projects can have the same path (e.g., "README.md"), but within a single project, each path must be unique.

**Example violations prevented:**
- ❌ Two files with path "src/app.ts" in project "my-app"
- ✓ Different projects can each have "src/app.ts"
- ✓ Same project with "src/app.ts" and "src/App.ts" (case-sensitive)

**Performance:** Composite index `idx_project_files_project_path` on `(project_id, file_path)`

---

### VCS Branches

```sql
vcs_branches:
  UNIQUE(project_id, branch_name)
```

**Why:** Branch names must be unique within a project. You can't have two "main" branches in the same project.

**Example violations prevented:**
- ❌ Two branches named "main" in project "my-app"
- ✓ Different projects can each have "main" branch

---

### VCS Commits

```sql
vcs_commits:
  commit_hash TEXT NOT NULL UNIQUE
  UNIQUE(project_id, commit_hash)
```

**Why:** Commit hashes are SHA-256 digests of commit content. They must be globally unique (content-addressed). The composite constraint ensures no duplicate commits within a project.

---

### File Contents (Current Version)

```sql
file_contents:
  UNIQUE(file_id, is_current)
```

**Why:** Each file can have only ONE current version marked with `is_current = 1`. Historical versions have `is_current = 0` and can be multiple.

**How it works:**
- When `is_current = 1`: Only one row can exist per file_id
- When `is_current = 0`: Multiple rows allowed (version history)

**Example violations prevented:**
- ❌ Two rows with `file_id = 42` and `is_current = 1`
- ✓ One current + multiple historical versions

---

### Content Blobs (Content-Addressed Storage)

```sql
content_blobs:
  hash_sha256 TEXT PRIMARY KEY
```

**Why:** Content is stored once per unique hash. This is content-addressed storage - identical content (same SHA-256) is deduplicated automatically.

**Example:**
- File A: "Hello World" → SHA-256: abc123...
- File B: "Hello World" → SHA-256: abc123... (same hash)
- Result: Only one blob stored, both files reference it

---

### Deployment Targets

```sql
deployment_targets:
  UNIQUE(project_id, target_name, target_type)
```

**Why:** Each project can have one target of each type with a given name. For example, one "production" database target, one "production" edge_function target, etc.

**Example violations prevented:**
- ❌ Two "production" database targets for same project
- ✓ One "production" database + one "production" edge_function

---

### Nix Environments

```sql
nix_environments:
  UNIQUE(project_id, env_name)
```

**Why:** Environment names must be unique within a project. You can't have two environments named "default" in the same project.

**Example violations prevented:**
- ❌ Two "default" environments in project "my-app"
- ✓ Different projects can each have "default" environment

---

### Migration History

```sql
migration_history:
  UNIQUE(project_id, target_name, migration_file)
```

**Why:** Each migration can only be applied once per project per target. This prevents accidentally running the same migration twice.

**Example violations prevented:**
- ❌ Running `001_init.sql` twice on production
- ✓ Running `001_init.sql` on production, then on staging (different targets)

---

### Database Migrations

```sql
database_migrations:
  UNIQUE(project_id, migration_number)
```

**Why:** Migration numbers must be sequential and unique within a project. This ensures migrations run in correct order.

---

### Environment Variables

```sql
environment_variables:
  UNIQUE(scope_type, scope_id, var_name)
```

**Why:** Each variable name can appear only once per scope. For example, only one `DATABASE_URL` per project.

**Example violations prevented:**
- ❌ Two `DATABASE_URL` variables for project_id = 1
- ✓ One `DATABASE_URL` per project, per target (using different scopes)

---

### Checkouts

```sql
checkouts:
  UNIQUE(project_id, checkout_path)
```

**Why:** Each project can be checked out to a specific path only once. Prevents multiple active checkouts to the same directory.

**Example violations prevented:**
- ❌ Checking out "my-app" to `/tmp/work` twice
- ✓ Checking out "my-app" to `/tmp/work` and "other-app" to `/tmp/work2`

---

### API Endpoints

```sql
api_endpoints:
  UNIQUE(project_id, endpoint_path, http_method)
```

**Why:** Each path+method combination must be unique within a project. You can't have two `GET /api/users` endpoints.

**Example violations prevented:**
- ❌ Two `GET /api/users` handlers
- ✓ One `GET /api/users` + one `POST /api/users`

---

### File Dependencies

```sql
file_dependencies:
  UNIQUE(parent_file_id, dependency_file_id, dependency_type)
  CHECK(parent_file_id != dependency_file_id)
```

**Why:** Prevents duplicate dependency relationships and self-dependencies.

**Example violations prevented:**
- ❌ Recording "app.ts imports utils.ts" twice
- ❌ Recording "app.ts imports app.ts" (self-dependency)

---

### File Tags (Global)

```sql
file_tags:
  tag_name TEXT NOT NULL UNIQUE
```

**Why:** Tag names are globally unique. The same tag "frontend" can be used across all projects and files.

---

### File Type Names (Global)

```sql
file_types:
  type_name TEXT NOT NULL UNIQUE
```

**Why:** File type names are globally unique. Only one definition of "typescript", "python", etc.

---

## CHECK Constraints

### File Dependencies

```sql
CHECK(parent_file_id != dependency_file_id)
```

**Why:** Files cannot depend on themselves.

### Booking Configurations (Woofs example)

```sql
CONSTRAINT single_config CHECK (id = 1)
```

**Why:** Ensures only one configuration row exists. Singleton pattern at database level.

---

## Foreign Key Constraints

All foreign keys are defined with appropriate `ON DELETE` actions:

- **CASCADE**: When parent is deleted, child records are deleted
  - Example: Deleting a project deletes all its files

- **RESTRICT**: Prevents deletion if child records exist
  - Example: Can't delete a content_blob if files reference it

- **SET NULL**: Sets foreign key to NULL when parent is deleted
  - Used for optional relationships

---

## Automated Testing

Run the comprehensive constraint test suite:

```bash
python3 tests/test_constraints.py
```

This validates:
- All uniqueness constraints are enforced
- CHECK constraints work correctly
- Existing data doesn't violate any constraints

**Expected output:**
```
✅ All constraint tests passed!
✅ All existing data is valid!
```

## Manual Validation

To manually verify constraints are enforced:

```sql
-- Check for duplicate file paths within projects
SELECT project_id, file_path, COUNT(*) as count
FROM project_files
GROUP BY project_id, file_path
HAVING COUNT(*) > 1;
-- Should return 0 rows

-- Check for multiple current versions per file
SELECT file_id, COUNT(*) as current_count
FROM file_contents
WHERE is_current = 1
GROUP BY file_id
HAVING COUNT(*) > 1;
-- Should return 0 rows

-- Check for duplicate project slugs
SELECT slug, COUNT(*) as count
FROM projects
GROUP BY slug
HAVING COUNT(*) > 1;
-- Should return 0 rows
```

---

## Adding New Constraints

When adding new tables, consider:

1. **What makes a record unique?**
   - Within a project? Add `UNIQUE(project_id, identifier)`
   - Globally? Add `UNIQUE(identifier)` or `PRIMARY KEY`

2. **Can records reference themselves?**
   - If no: Add `CHECK(id != parent_id)` constraint

3. **What happens on delete?**
   - Children should be deleted? Use `ON DELETE CASCADE`
   - Prevent deletion? Use `ON DELETE RESTRICT`
   - Optional reference? Use `ON DELETE SET NULL`

4. **Performance implications?**
   - Unique constraints automatically create indexes
   - Composite unique constraints create composite indexes
   - Foreign keys may need explicit indexes on the child table

---

## Common Patterns

### Project-Scoped Uniqueness

Most resources are unique within a project:

```sql
UNIQUE(project_id, resource_name)
```

Examples:
- Files: `UNIQUE(project_id, file_path)`
- Branches: `UNIQUE(project_id, branch_name)`
- Environments: `UNIQUE(project_id, env_name)`
- Migrations: `UNIQUE(project_id, migration_number)`

### Content-Addressed Storage

Content stored by hash with deduplication:

```sql
hash_sha256 TEXT PRIMARY KEY
```

Examples:
- `content_blobs`: One copy per unique content
- `vcs_commits`: One commit per unique hash

### Singleton Pattern

Only one configuration record allowed:

```sql
CONSTRAINT single_config CHECK (id = 1)
```

### Versioned Resources

One current version, multiple historical:

```sql
UNIQUE(resource_id, is_current)
```

Only enforced when `is_current = 1`, allows multiple rows with `is_current = 0`.

---

## Summary

✓ **All critical uniqueness constraints are in place**

Key takeaways:
1. File paths are unique per project (not globally)
2. Content is deduplicated by hash (content-addressed)
3. Most resources are scoped to projects
4. Constraints prevent corruption at database level
5. Foreign keys maintain referential integrity

**See also:**
- [QUERY_BEST_PRACTICES.md](QUERY_BEST_PRACTICES.md) - How to query with constraints in mind
- [DESIGN_PHILOSOPHY.md](DESIGN_PHILOSOPHY.md) - Why normalized storage matters
