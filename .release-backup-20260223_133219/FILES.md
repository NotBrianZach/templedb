# TempleDB File System

**How TempleDB tracks, versions, and stores your code**

---

## Overview

TempleDB stores your entire codebase in a SQLite database with:
- **Content deduplication** (SHA-256 based, 60% storage reduction)
- **Version tracking** (optimistic locking with conflict detection)
- **File metadata** (type, dependencies, complexity)
- **ACID transactions** (atomic commits, rollback on error)

---

## Core Concepts

### 1. Content-Addressable Storage

Files are stored using their SHA-256 hash as a key:

```
File A (v1) ──┐
              ├──> content_blobs[hash_abc123]
File B (v3) ──┘

File A (v2) ────> content_blobs[hash_def456]
```

**Benefits:**
- Duplicate content stored only once
- Instant deduplication across projects
- Content verification via hashing

### 2. Version Control

Every file has a version number that increments on change:

```sql
file_contents:
  file_id | content_hash | version | is_current
  --------+--------------+---------+-----------
  42      | abc123       | 1       | 0
  42      | def456       | 2       | 0
  42      | xyz789       | 3       | 1  ← current
```

### 3. Checkout Snapshots

When you checkout, TempleDB records the exact versions:

```
Checkout → Record versions → Edit files → Commit → Detect conflicts
```

If someone else modified the same file:
```
Your version:    3
Current version: 4  ← Conflict!
```

---

## Database Schema

### Core Tables

**projects** - Project metadata
```sql
id, slug, name, repo_url, git_branch, created_at, updated_at
```

**project_files** - File registry
```sql
id, project_id, file_type_id, file_path, file_name,
component_name, lines_of_code, status, last_modified
```

**content_blobs** - Deduplicated content
```sql
hash_sha256 (PK), content_text, content_blob,
content_type, encoding, file_size_bytes
```

**file_contents** - Current file versions
```sql
id, file_id, content_hash → content_blobs,
version, is_current, updated_at
```

### Checkout/Commit Tables

**checkouts** - Active workspaces
```sql
id, project_id, checkout_path, branch_name,
checkout_at, last_sync_at, is_active
```

**checkout_snapshots** - Version tracking
```sql
id, checkout_id, file_id, content_hash,
version, checked_out_at
```

**file_conflicts** - Detected conflicts
```sql
id, checkout_id, file_id, base_version,
current_version, detected_at, resolved_at
```

### VCS Tables

**vcs_commits** - Commit history
```sql
id, project_id, branch_id, commit_hash,
author, commit_message, commit_timestamp
```

**commit_files** - Files changed per commit
```sql
id, commit_id, file_id, change_type (added/modified/deleted),
old_content_hash, new_content_hash, lines_added, lines_removed
```

---

## File Types

TempleDB recognizes 25+ file types:

### Programming Languages
- `python`, `javascript`, `typescript`
- `rust`, `go`, `c`, `cpp`

### Web Components  
- `jsx_component`, `tsx_component`
- `react_hook`, `vue_component`

### Database
- `sql_table`, `sql_view`, `sql_function`
- `plpgsql_function`, `sql_trigger`

### Configuration
- `package_json`, `tsconfig`, `webpack_config`
- `docker_file`, `nix_flake`, `shell_script`

### Documentation
- `markdown`, `rst`, `asciidoc`

Add custom types in `file_types` table.

---

## How It Works

### Import Process

```bash
./templedb project import /path/to/project
```

1. **Scan directory** - FileScanner finds all tracked file types
2. **Calculate hashes** - SHA-256 of file content
3. **Deduplicate** - INSERT OR IGNORE into content_blobs
4. **Create records** - project_files entries
5. **Link content** - file_contents references blobs
6. **Extract metadata** - Git info, LOC, complexity

### Checkout Process

```bash
./templedb project checkout myproject /tmp/workspace
```

1. **Query current files** - Get all is_current=1 files
2. **Fetch content** - Join to content_blobs
3. **Write to filesystem** - Create directory structure
4. **Record checkout** - Create checkout record
5. **Snapshot versions** - Save current version numbers

### Commit Process

```bash
./templedb project commit myproject /tmp/workspace -m "Changes"
```

1. **Scan workspace** - Find added/modified/deleted files
2. **Detect conflicts** - Compare versions with snapshots
3. **Hash content** - Calculate SHA-256
4. **Store blobs** - INSERT OR IGNORE (dedup)
5. **Update file_contents** - Increment version numbers
6. **Create VCS commit** - Record in vcs_commits
7. **Update snapshots** - Sync checkout_snapshots

---

## Content Deduplication

### How It Works

```python
# Simplified logic
def store_file(content):
    hash = sha256(content)
    execute("INSERT OR IGNORE INTO content_blobs VALUES (?, ?)", (hash, content))
    # If hash exists, INSERT is ignored - no duplication!
```

### Real-World Results

From Phase 1 testing:
- **2,847 files** imported
- **606 unique content blobs** (78.5% duplicates!)
- **35.78 MB** saved (60.68% reduction)

Common duplicates:
- `package-lock.json` (same across branches)
- Boilerplate files (LICENSE, .gitignore)
- Generated files (build outputs)
- Vendored libraries

---

## Version Tracking

### Optimistic Locking

TempleDB uses version numbers for conflict detection:

```sql
-- On commit, check if version changed
SELECT version FROM file_contents 
WHERE file_id = ? AND is_current = 1;

-- If version matches snapshot, update:
UPDATE file_contents 
SET content_hash = ?, version = version + 1
WHERE file_id = ? AND version = ?;  -- Only if version unchanged

-- If version doesn't match → CONFLICT
```

### Conflict Resolution Strategies

```bash
# Abort (default) - show conflicts, don't commit
./templedb project commit proj /tmp/work -m "Changes"

# Force - overwrite conflicts (dangerous!)
./templedb project commit proj /tmp/work -m "Changes" --force

# Strategy flag
./templedb project commit proj /tmp/work -m "Changes" --strategy abort
```

---

## SQL Examples

### Find Duplicate Content

```sql
SELECT 
    hash_sha256,
    COUNT(*) as file_count,
    file_size_bytes
FROM content_blobs cb
WHERE hash_sha256 IN (
    SELECT content_hash FROM file_contents GROUP BY content_hash HAVING COUNT(*) > 1
)
GROUP BY hash_sha256
ORDER BY file_count DESC;
```

### File Version History

```sql
SELECT 
    fc.version,
    fc.updated_at,
    c.commit_message,
    c.author
FROM file_contents fc
LEFT JOIN commit_files cf ON cf.file_id = fc.file_id
LEFT JOIN vcs_commits c ON c.id = cf.commit_id
WHERE fc.file_id = ?
ORDER BY fc.version DESC;
```

### Storage Statistics

```sql
SELECT 
    COUNT(DISTINCT hash_sha256) as unique_blobs,
    COUNT(*) as total_references,
    SUM(file_size_bytes) as total_bytes,
    SUM(file_size_bytes) / COUNT(*) as avg_size
FROM content_blobs;
```

### Active Checkouts

```sql
SELECT 
    p.slug,
    c.checkout_path,
    COUNT(cs.id) as files_checked_out,
    c.checkout_at,
    c.last_sync_at
FROM checkouts c
JOIN projects p ON c.project_id = p.id
LEFT JOIN checkout_snapshots cs ON cs.checkout_id = c.id
WHERE c.is_active = 1
GROUP BY c.id;
```

---

## Performance Characteristics

### Storage Efficiency
- **O(1) deduplication** - hash lookup
- **~60% reduction** in practice
- **No duplicate I/O** - write once, reference many

### Query Performance
- **Indexed lookups** - all foreign keys indexed
- **O(log n) searches** - B-tree indexes
- **Batch operations** - 50-100x faster than individual

### Scalability
- **10k+ files** - tested and working
- **1M+ lines** - no performance degradation
- **Multi-agent safe** - ACID transactions

---

## Best Practices

### 1. Commit Frequently
```bash
# Good: Small, focused commits
./templedb project commit myproj /tmp/work -m "Fix auth bug"

# Avoid: Massive commits with many changes
```

### 2. Use Meaningful Messages
```bash
# Good
-m "Add user authentication endpoint"

# Bad
-m "changes" -m "fix" -m "wip"
```

### 3. Clean Up Checkouts
```bash
# List stale checkouts
./templedb project checkout-list

# Remove invalid ones
./templedb project checkout-cleanup --force
```

### 4. Monitor Storage
```sql
-- Check database size
SELECT page_count * page_size / 1024 / 1024.0 AS size_mb 
FROM pragma_page_count(), pragma_page_size();

-- Check deduplication effectiveness
SELECT 
    COUNT(*) as total_file_refs,
    COUNT(DISTINCT content_hash) as unique_blobs,
    100.0 * (1 - COUNT(DISTINCT content_hash) * 1.0 / COUNT(*)) as dedup_pct
FROM file_contents;
```

---

## Troubleshooting

### "No changes to commit"
**Cause**: Files not tracked type or no actual changes
**Fix**: Check file types with `./templedb project show`

### "Conflict detected"
**Cause**: Someone else modified the file
**Fix**: 
1. Checkout fresh copy
2. Manually merge changes
3. Commit again

Or use `--force` to overwrite (careful!)

### "Database locked"
**Cause**: Another process accessing database
**Fix**: 
```bash
# Find process
ps aux | grep templedb

# Kill if needed
killall python3
```

### Slow queries
**Cause**: Missing indexes or large dataset
**Fix**: 
```sql
-- Add indexes
CREATE INDEX idx_file_contents_version ON file_contents(file_id, version);
CREATE INDEX idx_checkout_snapshots_file ON checkout_snapshots(file_id);

-- Analyze query
EXPLAIN QUERY PLAN SELECT ...;
```

---

## Summary

TempleDB's file system provides:
- ✅ **60% storage reduction** via deduplication
- ✅ **Complete version history** with conflict detection
- ✅ **Multi-agent safety** through ACID transactions
- ✅ **Simple workflow** - checkout, edit, commit
- ✅ **SQL queryable** - analyze your entire codebase

All while letting you use familiar tools (vim, vscode, grep) for editing!
