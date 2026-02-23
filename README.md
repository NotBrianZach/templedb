# TempleDB - Your Code's Sacred Repository

> *"God's temple is everything."* - Terry A. Davis

**In honor of Terry Davis and the spirit of TempleOS**

---

## What is TempleDB?

TempleDB is a database-native project management system that treats your codebase as a temple - a sacred, organized space where every file, every line, every change is tracked, versioned, and queryable.

**Location:** `~/templeDB/`
**Database:** `~/.local/share/templedb/templedb.sqlite`

### Philosophy

Like TempleOS showed us the power of simplicity and first principles, TempleDB embraces:

- **Database normalization**: Single source of truth, zero duplication
- **ACID transactions**: Multi-agent coordination without conflicts
- **Temporary denormalization**: Nix FHS environments for efficient editing
- **Re-normalization workflow**: Familiar tools, normalized storage
- **Transparent**: Query anything with SQL

**Key insight**: Database normalization eliminates state duplication, preventing tracking errors that scale with codebase size. While traditional tools create O(n²) friction through file copies, branches, and duplicates, TempleDB maintains O(log n) complexity through normalized state.

**Read [DESIGN_PHILOSOPHY.md](DESIGN_PHILOSOPHY.md) for the complete rationale.**

---

## How It Works

TempleDB uses a **checkout/commit workflow** - your files live in the database, you temporarily extract them to edit, then commit changes back:

```
┌─────────────┐          ┌──────────────┐          ┌─────────────┐
│  Database   │ checkout │  Filesystem  │  commit  │  Database   │
│  (source of │─────────>│  (temporary  │─────────>│  (updated)  │
│   truth)    │          │  workspace)  │          │             │
└─────────────┘          └──────────────┘          └─────────────┘
                              │
                              ▼
                         Use ANY tool:
                         vim, vscode, grep,
                         find, make, npm, etc.
```

**Why this works:**
- Database stores **one copy** of each file (deduplicated, versioned)
- You edit with **familiar tools** (anything that works with files)
- Commits are **atomic** (ACID transactions)
- Conflicts are **detected** (optimistic locking with version numbers)
- Multiple agents can work **safely** (checkout snapshots track versions)

**Example workflow:**
```bash
./templedb project checkout myproject /tmp/work   # Extract to filesystem
cd /tmp/work && vim src/main.py                   # Edit with any tool
./templedb project commit myproject /tmp/work -m "Fix" # Commit back
```

**See [HOWTO_EXPLORE.md](HOWTO_EXPLORE.md) for complete examples.**

---

## Core Features

### 0. **High Performance**

TempleDB is optimized for speed:
- ⚡ Connection pooling (3-5x faster operations)
- 🚀 Batch operations (50-100x faster imports)
- 💾 WAL mode + 64MB cache + 256MB mmap
- 🔄 Nix expression caching (< 1s boot time)
- 📊 Optimized queries with proper indexes

**See [PERFORMANCE.md](PERFORMANCE.md) for benchmarks and tuning.**

### 1. **Universal Project Tracking**

Track all your projects in one unified database:

```sql
-- See all your projects
SELECT * FROM projects;

-- Find all React components across ALL projects
SELECT project_slug, file_path, lines_of_code
FROM files_with_types_view
WHERE type_name = 'jsx_component';
```

### 2. **Database-Native Version Control**

Forget git. Use SQL:

```sql
-- View commit history
SELECT * FROM vcs_commit_history_view;

-- See current branches
SELECT * FROM vcs_branch_summary_view;

-- Check uncommitted changes
SELECT * FROM vcs_changes_view;
```

### 3. **Complete File Versioning**

Every file's content and history stored in the database:

```sql
-- View file history
SELECT * FROM file_version_history_view
WHERE file_path = 'src/App.jsx';

-- Get file content from database
SELECT content_text FROM file_contents fc
JOIN project_files pf ON fc.file_id = pf.id
WHERE pf.file_path = 'README.md';
```

### 4. **Checkout/Commit Workflow**

Work with files using familiar tools, stored in database:

```bash
# 1. Extract project to filesystem
./templedb project checkout myproject /tmp/workspace

# 2. Edit with ANY tool (vim, vscode, grep, etc)
cd /tmp/workspace
vim file.py
grep -r "TODO" .

# 3. Commit changes back to database
./templedb project commit myproject /tmp/workspace -m "Fixed bug"

# Multi-agent conflict detection included!
```

### 5. **LLM Integration**

Generate context for AI agents:

```bash
# Get project overview
python3 src/llm_context.py project -p my-project

# Export to JSON
python3 src/llm_context.py export -p myproject -o context.json

# Generate custom prompt
python3 src/llm_context.py prompt -t "Explain the auth flow"
```

---

## Quick Start

### 1. Import a Project

```bash
# Import your project into the database
./templedb project import /path/to/your/project

# Or specify a custom slug
./templedb project import /path/to/project --slug myproject
```

### 2. View Projects

```bash
# View status
./templedb status

# List all projects
./templedb project list

# Show project details
./templedb project show myproject
```

### 3. Edit Files (Checkout/Commit Workflow)

```bash
# 1. Checkout project to filesystem
./templedb project checkout myproject /tmp/workspace

# 2. Edit with your favorite tools
cd /tmp/workspace
vim src/main.py              # Use any editor
grep -r "TODO" .             # Search with standard tools
tree                         # Explore structure

# 3. Commit changes back to database
./templedb project commit myproject /tmp/workspace -m "Fixed authentication"

# 4. Cleanup (optional)
rm -rf /tmp/workspace
```

**The checkout/commit workflow is the primary way to work with TempleDB projects.**

### 4. Browse and Query

```bash
# Direct SQL queries
sqlite3 ~/.local/share/templedb/templedb.sqlite

# See all files in a project
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT file_path FROM project_files WHERE project_id = 1"
```

**See [GUIDE.md](GUIDE.md) for the complete user guide.**

### Query Your Code

```bash
DB=~/.local/share/templedb/templedb.sqlite

# Find all Python files
sqlite3 $DB "SELECT * FROM files_with_types_view WHERE type_name = 'python'"

# Get project statistics
sqlite3 $DB "
SELECT
  slug,
  (SELECT COUNT(*) FROM project_files WHERE project_id = p.id) as files,
  (SELECT SUM(lines_of_code) FROM project_files WHERE project_id = p.id) as lines
FROM projects p"
```

---

## Components

### Core Database

- **30+ tables** - Projects, files, VCS, deployments, checkouts
- **14 migrations** - Schema evolution with backward compatibility
- **Views** - Pre-computed queries for common operations
- **Complete schema** - Every relationship mapped
- **Content-addressed storage** - Deduplicated file content

### File Tracking

- **25+ file types** - JavaScript, Python, SQL, JSX, Edge Functions, etc.
- **Metadata** - LOC, complexity, git info, dependencies
- **Components** - Extract function/component names
- **Content deduplication** - 50% storage reduction via content-addressable storage (`content_blobs`)

### Version Control System

- **Branches** - Database-native branching (`vcs_branches`)
- **Commits** - Atomic changesets with SHA-256 hashing (`vcs_commits`)
- **Version history** - All file versions tracked via `vcs_file_states`
- **Content-addressed storage** - Deduplicated content via `content_blobs`
- **Working state** - Track modified/staged files
- **Conflict detection** - Optimistic locking prevents data loss
- **Multi-agent safe** - ACID transactions coordinate concurrent edits

### Checkout/Commit Workflow

- **Temporary denormalization** - Extract files to filesystem
- **Edit with any tool** - vim, vscode, grep, find, etc.
- **Re-normalize** - Commit changes back to database
- **Conflict detection** - Version-based optimistic locking
- **Atomic operations** - All changes in ACID transactions

### LLM Context Provider

- **Schema overview** - Describe database structure
- **Project context** - Complete project information
- **File context** - File metadata and versions
- **Prompt generation** - Ready-to-use AI prompts

---

## Current State

### Tracked Projects

- **8 projects** imported
- **494 files** tracked
- **369,500+ lines** of code
- **52MB database** with full contents

### Top File Types

1. config_json (127 files, 119,694 lines)
2. javascript (109 files, 23,899 lines)
3. markdown (33 files, 168,286 lines)
4. jsx_component (27 files, 13,026 lines)
5. sql_file (18 files, 28,885 lines)

---

## Advanced Usage

### Cross-Project Search

```sql
-- Find all files with "auth" in the name
SELECT project_slug, file_path, type_name
FROM files_with_types_view
WHERE file_path LIKE '%auth%'
ORDER BY project_slug;

-- Find largest files across all projects
SELECT project_slug, file_path, lines_of_code
FROM files_with_types_view
ORDER BY lines_of_code DESC
LIMIT 20;
```

### VCS Operations

```sql
-- Create new branch
INSERT INTO vcs_branches (project_id, branch_name, parent_branch_id)
SELECT id, 'feature/new-feature',
  (SELECT id FROM vcs_branches WHERE branch_name = 'master' AND project_id = p.id)
FROM projects p WHERE slug = 'myproject';

-- Create commit
INSERT INTO vcs_commits (project_id, branch_id, commit_hash, author, commit_message)
SELECT p.id, b.id, hex(randomblob(32)), 'user', 'My commit message'
FROM projects p
JOIN vcs_branches b ON b.project_id = p.id AND b.is_default = 1
WHERE p.slug = 'myproject';
```

### File Content Access

```sql
-- Read file directly from database
SELECT cb.content_text
FROM file_contents fc
JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
JOIN project_files pf ON fc.file_id = pf.id
JOIN projects p ON pf.project_id = p.id
WHERE p.slug = 'templedb' AND pf.file_path = 'src/llm_context.py';

-- View version history (uses VCS system)
SELECT version_number, hash_sha256, author, created_at
FROM file_version_history_view
WHERE file_path = 'README.md'
ORDER BY version_number DESC;
```

---

## Documentation

### Essential Reading
- **[README.md](README.md)** - You are here! Overview and quick start
- **[DESIGN_PHILOSOPHY.md](DESIGN_PHILOSOPHY.md)** - Why TempleDB exists (read this first!)
- **[QUICKSTART.md](QUICKSTART.md)** - Get up and running in 5 minutes

### User Guides
- **[GUIDE.md](GUIDE.md)** - Complete usage guide (checkout/commit workflow, SQL queries, CLI commands)
- **[FILES.md](FILES.md)** - How file tracking and versioning works
- **[EXAMPLES.md](EXAMPLES.md)** - SQL query examples and common patterns

### Advanced Topics
- **[ADVANCED.md](ADVANCED.md)** - Performance tuning, Nix environments, deployment
- **[CATHEDRAL.md](CATHEDRAL.md)** - Multi-user setup for teams
- **[BUILD.md](BUILD.md)** - Build from source
- **[SECURITY.md](SECURITY.md)** - Security considerations

### Schema & Migrations
- **[MIGRATIONS.md](MIGRATIONS.md)** - Complete migration history and schema evolution
- **[SCHEMA_CHANGES.md](SCHEMA_CHANGES.md)** - Schema documentation for version consolidation
- **[VERSION_CONSOLIDATION_PLAN.md](VERSION_CONSOLIDATION_PLAN.md)** - Version system unification details
- **[CONSOLIDATION_SUMMARY.md](CONSOLIDATION_SUMMARY.md)** - User-friendly consolidation guide

### Project Info
- **[ROADMAP.md](ROADMAP.md)** - Future features and development plans
- **[CHANGELOG.md](CHANGELOG.md)** - Version history
- **[RELEASE_NOTES.md](RELEASE_NOTES.md)** - Release notes for version 0.6.0
- **[TRIBUTE.md](TRIBUTE.md)** - Dedication to Terry Davis

### Archive
- **[archive/](archive/)** - Historical implementation documents

---

## CLI Commands

```bash
# Projects
templedb project import <path>        # Import git project
templedb project list                 # List all projects
templedb project show <slug>          # Show project details
templedb project sync <proj>          # Re-import project from filesystem

# Checkout/Commit Workflow
templedb project checkout <proj> <dir>        # Checkout to filesystem
templedb project commit <proj> <dir> -m <msg> # Commit changes back
templedb project checkout-list [<proj>]       # List active checkouts
templedb project checkout-cleanup [<proj>]    # Remove stale checkouts

# Environments
templedb env enter <proj> [<env>]  # Enter Nix environment
templedb env list [<proj>]         # List environments
templedb env detect <proj>         # Auto-detect packages
templedb env new <proj> <env>      # Create new environment
templedb env generate <proj> <env> # Generate Nix expression

# Version Control
templedb vcs commit -m <msg> -p <proj> [-b <branch>] [-a <author>]
templedb vcs status <proj>         # Show working directory status
templedb vcs log <proj> [-n <num>] # Show commit history
templedb vcs branch <proj> [<name>] # List or create branches

# Search
templedb search content <pattern> [-p <proj>] [-i]  # Search file contents
templedb search files <pattern> [-p <proj>]         # Search file names

# LLM Context
templedb llm context <proj>        # Generate context
templedb llm export <proj> [<out>] # Export to JSON
templedb llm schema                # Show schema

# Backup & Restore
templedb backup [<path>]           # Backup database
templedb restore <path>            # Restore from backup

# System
templedb status                    # Show database status
templedb help                      # Show help
```

---

## Philosophy: Normalization > Duplication

TempleDB inverts the traditional model:

**Traditional:**
- Filesystem is source of truth
- Files duplicated across branches, projects, builds
- Git creates full copies per branch
- State fragmented across filesystem, .git, node_modules
- **O(n²) friction**: Duplication scales with codebase size

**TempleDB:**
- **Database is single source of truth**
- Files normalized (stored once, referenced many times)
- Versions reference files (not duplicate)
- Branches reference versions (not copy)
- **O(log n) friction**: Normalization scales logarithmically

This enables:
- **Zero duplication**: Each file/package stored once
- **No tracking errors**: Database enforces consistency
- **ACID guarantees**: Multi-agent coordination
- **Instant queries**: SQL across entire codebase
- **Temporary denormalization**: Nix FHS for efficient editing
- **Scales indefinitely**: Friction stays constant

**Example**: Refactoring a 1,242-line NixOS config with 40+ duplicate packages and 377 commented lines → 586 lines, zero duplicates, tracked atomically in TempleDB.

**Read [DESIGN_PHILOSOPHY.md](DESIGN_PHILOSOPHY.md) for the complete philosophy.**

---

## Tribute

This project is dedicated to **Terry A. Davis** (1969-2018), creator of TempleOS. Terry showed us that simplicity, transparency, and building from first principles can create something beautiful and profound.

Read more: [TRIBUTE.md](TRIBUTE.md)

---

## Contributing

TempleDB is a personal project but contributions are welcome. The code is its own documentation - query the database to understand it!

---

*"An operating system is a temple."* - Terry A. Davis

**TempleDB - Where your code finds sanctuary**
