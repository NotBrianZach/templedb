# How to View/Review/Fiddle with TempleDB Projects

**TL;DR**: Use checkout/commit workflow + standard Unix tools. The TUI was removed because it was unnecessary complexity.

---

## Philosophy

TempleDB follows **"normalize in database, denormalize to filesystem"**:

1. **Database = Source of truth** (normalized, deduplicated, versioned)
2. **Filesystem = Temporary workspace** (for editing with familiar tools)
3. **Commit = Sync changes back** (with conflict detection)

---

## Quick Reference

```bash
# See what's in the database
./templedb status                    # Overall stats
./templedb project list              # All projects
./templedb project show myproject    # Project details

# Work with files (the main workflow)
./templedb project checkout myproject /tmp/workspace
cd /tmp/workspace
vim file.py                          # Use ANY editor
./templedb project commit myproject /tmp/workspace -m "Changes"

# Browse database directly
sqlite3 ~/.local/share/templedb/templedb.sqlite
```

---

## Method 1: Checkout/Commit Workflow (Recommended)

This is the **primary way** to work with projects.

### 1. Checkout Project

Extract files from database to filesystem:

```bash
# Basic checkout
./templedb project checkout system_config /tmp/my-workspace

# Force overwrite existing directory
./templedb project checkout system_config /tmp/my-workspace --force
```

### 2. Edit Files Normally

Use **any tools you want**:

```bash
cd /tmp/my-workspace

# Use your favorite editor
vim bootstrap.sh
emacs backup.sh
code .              # VS Code
nano README.md

# Use standard tools
grep -r "TODO" .
find . -name "*.py"
tree
ls -la
```

### 3. Commit Changes Back

Scan for changes and commit to database:

```bash
./templedb project commit system_config /tmp/my-workspace -m "Fixed bootstrap script"
```

**What it does**:
- Scans workspace for added/modified/deleted files
- Detects conflicts with other agents
- Deduplicates content (saves storage)
- Increments version numbers
- Records in VCS (commit history)

### 4. Manage Checkouts

```bash
# List all active checkouts
./templedb project checkout-list system_config

# Clean up stale checkouts (deleted directories)
./templedb project checkout-cleanup system_config --force
```

---

## Method 2: Direct SQL Queries (For Browsing)

Browse database state directly with SQL.

### Enter SQLite Shell

```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite
```

### Useful Queries

```sql
-- List all projects
SELECT slug, name FROM projects;

-- Files in a project
SELECT file_path, lines_of_code
FROM project_files
WHERE project_id = (SELECT id FROM projects WHERE slug = 'system_config')
ORDER BY file_path;

-- File content (view a specific file)
SELECT pf.file_path, cb.content_text
FROM project_files pf
JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
WHERE pf.file_path = 'bootstrap.sh'
  AND pf.project_id = (SELECT id FROM projects WHERE slug = 'system_config');

-- Recent commits
SELECT
    commit_hash,
    author,
    commit_message,
    commit_timestamp
FROM vcs_commits
ORDER BY commit_timestamp DESC
LIMIT 10;

-- Files by type
SELECT ft.type_name, COUNT(*) as count
FROM project_files pf
JOIN file_types ft ON pf.file_type_id = ft.id
GROUP BY ft.type_name
ORDER BY count DESC;

-- Checkouts (active workspaces)
SELECT
    p.slug,
    c.checkout_path,
    c.checkout_at,
    c.last_sync_at
FROM checkouts c
JOIN projects p ON c.project_id = p.id
ORDER BY c.checkout_at DESC;

-- File conflicts
SELECT
    pf.file_path,
    fc.base_version,
    fc.current_version,
    fc.detected_at
FROM file_conflicts fc
JOIN project_files pf ON fc.file_id = pf.id
WHERE fc.resolved_at IS NULL;
```

### Pro Tips

```sql
-- Enable pretty output
.mode column
.headers on
.width 50 20 10

-- Save output to file
.output /tmp/files.txt
SELECT * FROM project_files;
.output stdout

-- Export to CSV
.mode csv
.output /tmp/projects.csv
SELECT * FROM projects;
```

---

## Method 3: CLI Commands (Project Management)

Use CLI for high-level operations.

### Project Commands

```bash
# List all projects
./templedb project list

# Show project details
./templedb project show system_config

# Import new project
./templedb project import /path/to/project --slug myproject

# Re-sync project from filesystem
./templedb project sync system_config

# Remove project
./templedb project rm myproject --force
```

### VCS Commands

```bash
# List branches
./templedb vcs list-branches system_config

# Show commits
./templedb vcs log system_config

# Show commit details
./templedb vcs show-commit <commit-hash>
```

### System Commands

```bash
# Database status
./templedb status

# Backup database
./templedb backup /tmp/backup.sqlite

# Restore database
./templedb restore /tmp/backup.sqlite
```

---

## Method 4: Standard Unix Tools (Searching/Browsing)

Use familiar tools on **checked-out workspaces**.

### Searching

```bash
cd /tmp/workspace

# Find files
find . -name "*.py"
find . -type f -size +100k

# Search content
grep -r "function" .
rg "TODO" --type py

# Count lines
wc -l **/*.py
cloc .
```

### Exploring Structure

```bash
# Tree view
tree
tree -L 2

# File listing
ls -lh
ls -lhS    # Sort by size
ls -lht    # Sort by time

# Disk usage
du -sh *
du -h --max-depth=1 | sort -h
```

### Viewing Files

```bash
# Quick preview
cat file.py
head -20 file.py
tail -50 file.py
less file.py

# Syntax highlighting
bat file.py
pygmentize file.py

# Side-by-side comparison
diff -y file1.py file2.py
```

---

## Method 5: Direct File Access (Read-Only)

Query and extract files programmatically.

### Python Script Example

```python
#!/usr/bin/env python3
import sqlite3

DB_PATH = "~/.local/share/templedb/templedb.sqlite"
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

# Get all Python files
cursor.execute("""
    SELECT pf.file_path, cb.content_text
    FROM project_files pf
    JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
    JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
    JOIN file_types ft ON pf.file_type_id = ft.id
    WHERE ft.type_name = 'python'
""")

for row in cursor:
    print(f"File: {row['file_path']}")
    print(f"Lines: {len(row['content_text'].split())}")
    print()

conn.close()
```

### Shell Script Example

```bash
#!/bin/bash
# Extract all markdown files

sqlite3 ~/.local/share/templedb/templedb.sqlite <<SQL
SELECT
    pf.file_path,
    cb.content_text
FROM project_files pf
JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
WHERE pf.file_path LIKE '%.md';
SQL
```

---

## Common Workflows

### Workflow 1: Quick Edit

```bash
# 1. Checkout
./templedb project checkout myproject /tmp/edit

# 2. Edit one file
vim /tmp/edit/file.py

# 3. Commit
./templedb project commit myproject /tmp/edit -m "Fixed bug"

# 4. Cleanup
rm -rf /tmp/edit
```

### Workflow 2: Major Refactoring

```bash
# 1. Checkout to persistent location
./templedb project checkout myproject ~/work/myproject

# 2. Work over multiple sessions
cd ~/work/myproject
# ... edit many files over days ...

# 3. Commit when ready
./templedb project commit myproject ~/work/myproject -m "Refactored auth"

# 4. Keep workspace for future work (or delete)
```

### Workflow 3: Explore and Search

```bash
# 1. Checkout (read-only exploration)
./templedb project checkout bigproject /tmp/explore

# 2. Use search tools
cd /tmp/explore
rg "API_KEY"
find . -name "*config*"

# 3. No commit needed (just delete)
rm -rf /tmp/explore
```

### Workflow 4: Multi-Agent Collaboration

**Agent A:**
```bash
./templedb project checkout shared /tmp/agent-a
vim /tmp/agent-a/file1.py
./templedb project commit shared /tmp/agent-a -m "A's changes"
```

**Agent B:**
```bash
./templedb project checkout shared /tmp/agent-b
vim /tmp/agent-b/file2.py  # Different file = no conflict
./templedb project commit shared /tmp/agent-b -m "B's changes"
```

**Agent C (conflicts with A):**
```bash
./templedb project checkout shared /tmp/agent-c
vim /tmp/agent-c/file1.py  # Same file as A!
./templedb project commit shared /tmp/agent-c -m "C's changes"
# ⚠️ CONFLICT DETECTED - must resolve
```

---

## Why No TUI?

The TUI was **1,800 lines of complexity** that:
- Duplicated what CLI + checkout/commit does better
- Forced you into a modal interface
- Made automation harder
- Required extra dependencies (Textual)
- Edited files via temp YAML files (awkward)

**Better approach:**
- CLI for management commands
- Checkout/commit for file editing
- Standard Unix tools for searching
- Direct SQL for advanced queries
- Scriptable and automatable

---

## Pro Tips

### 1. Use Shell Aliases

```bash
# In ~/.bashrc or ~/.zshrc
alias tdb='./templedb'
alias tdb-co='./templedb project checkout'
alias tdb-ci='./templedb project commit'
alias tdb-ls='./templedb project list'
alias tdb-st='./templedb status'

# Now:
tdb-co myproject /tmp/work
tdb-ci myproject /tmp/work -m "Changes"
```

### 2. Create Helper Scripts

```bash
#!/bin/bash
# quick-edit.sh - Quick edit workflow

PROJECT=$1
FILE=$2
MESSAGE=$3

WORKSPACE="/tmp/tdb-$$"

./templedb project checkout "$PROJECT" "$WORKSPACE"
"$EDITOR" "$WORKSPACE/$FILE"
./templedb project commit "$PROJECT" "$WORKSPACE" -m "$MESSAGE"
rm -rf "$WORKSPACE"
```

### 3. Use `watch` for Live Updates

```bash
# Monitor database stats
watch -n 5 './templedb status'

# Monitor commits
watch -n 10 "sqlite3 templedb.sqlite 'SELECT * FROM vcs_commits ORDER BY commit_timestamp DESC LIMIT 5'"
```

### 4. Integrate with Git

```bash
# In checked-out workspace
cd /tmp/workspace
git init
git add .
git commit -m "Work in progress"

# Make changes...

# Diff before committing to TempleDB
git diff

# Commit to TempleDB
./templedb project commit myproject /tmp/workspace -m "Changes"
```

---

## Troubleshooting

### "No changes to commit"

```bash
# Make sure files are tracked types
./templedb project show myproject  # Check file types

# Re-scan
./templedb project sync myproject
```

### Conflicts

```bash
# Option 1: Abort and merge manually
./templedb project commit myproject /tmp/work -m "Changes" --strategy abort
# Then: checkout fresh copy, manually merge, commit again

# Option 2: Force overwrite (dangerous!)
./templedb project commit myproject /tmp/work -m "Changes" --force
```

### Stale Checkouts

```bash
# List all checkouts
./templedb project checkout-list

# Remove invalid ones
./templedb project checkout-cleanup --force
```

### Database Locked

```bash
# Check for stuck processes
ps aux | grep templedb

# Kill if needed
killall python3

# Or backup and restore
./templedb backup /tmp/backup.sqlite
# Kill processes
./templedb restore /tmp/backup.sqlite
```

---

## Summary

**For editing:** Use checkout/commit workflow
**For browsing:** Use SQL queries or CLI commands
**For searching:** Use standard tools on checked-out code
**For automation:** Write scripts using CLI or SQL

The TUI was unnecessary - you have better, more flexible tools!
