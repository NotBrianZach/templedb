# TempleDB Project Context

> **Purpose**: This file provides comprehensive context about TempleDB for AI assistants working with the codebase.
> **Usage**: Launch Claude Code with `claude --append-system-prompt-file .claude/project-context.md`

---

## What is TempleDB?

TempleDB is a **database-native AI swarm project management system** that treats your codebase as a temple - a sacred, organized space where every file, every line, every change is tracked, versioned, and queryable in SQLite.

### Core Philosophy

**Database as single source of truth**:
- All files, versions, and metadata stored in SQLite
- Files stored once via content addressing, referenced via versions
- Multi-agent coordination through ACID transactions, not merge conflicts
- Temporary denormalization for editing (checkout → edit → commit)

---

## Architecture Overview

### Checkout/Commit Workflow

TempleDB uses **temporary denormalization** for editing:

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

**Why this works**:
1. Database stores **one copy** of each file (content-addressed, versioned)
2. You edit with **familiar tools** (anything that works with files)
3. Commits are **atomic** with conflict detection
4. Multiple agents work **safely** (optimistic locking with version tracking)

### Database Schema

**30+ tables** organized into domains:

- **Projects**: `projects`, `project_files`, `file_types`
- **Version Control**: `vcs_branches`, `vcs_commits`, `vcs_commit_files`, `vcs_working_state`
- **File Versioning**: `file_contents`, `file_versions`, `content_blobs` (content-addressed storage)
- **Agent Sessions**: `agent_sessions`, `session_interactions`, `session_context_snapshots`
- **Multi-Agent Coordination**: `work_items`, `work_convoys`, `agent_mailbox`
- **Environments**: `nix_environments`, `environment_packages`
- **Secrets**: `project_secrets`, `secret_profiles`
- **Checkouts**: `project_checkouts` (tracks temporary filesystem extractions)

**21 views** for common queries:
- `files_with_types_view` - Files with type classification
- `file_version_history_view` - Complete version history
- `vcs_commit_history_view` - Commit log
- `current_file_contents_view` - Latest file contents
- And many more...

---

## Core Features

### 1. Database-Native Version Control

**Forget git. Use SQL:**

```sql
-- View commit history
SELECT * FROM vcs_commit_history_view;

-- See current branches
SELECT * FROM vcs_branch_summary_view;

-- Check uncommitted changes
SELECT * FROM vcs_changes_view;
```

**Commands:**
```bash
templedb vcs add -p <project> [files...]    # Stage files
templedb vcs commit -m <msg> -p <project>   # Commit staged changes
templedb vcs status <project>               # Show working state
templedb vcs log <project>                  # View history
templedb vcs branch <project> [<name>]      # Manage branches
```

### 2. Checkout/Commit Workflow

**Primary way to edit files:**

```bash
# 1. Extract project to filesystem
templedb project checkout myproject /tmp/workspace

# 2. Edit with ANY tool
cd /tmp/workspace
vim src/main.py
grep -r "TODO" .

# 3. Commit changes back to database
templedb project commit myproject /tmp/workspace -m "Fixed bug"
```

**Features:**
- Conflict detection via version tracking
- Atomic transactions
- Multi-agent safe
- Familiar tool support (vim, vscode, grep, etc.)

### 3. AI Agent Session Management

**Track AI agent work with automatic commit linking:**

```bash
# Start session
templedb agent start --project myproject --goal "Implement auth"
# → Returns session ID (e.g., 1)

# Export session ID to link commits
export TEMPLEDB_SESSION_ID=1

# Work and commit
templedb project checkout myproject /tmp/work
cd /tmp/work && vim src/auth.py
templedb project commit myproject /tmp/work -m "Add auth" --ai-assisted

# View session status
templedb agent status 1

# End session
templedb agent end 1
```

**Capabilities:**
- Session lifecycle tracking
- Automatic commit-to-session linking
- Interaction history logging
- Context snapshot generation
- Session analytics

### 4. Multi-Agent Coordination (Gas Town Inspired)

**Work Items (Beads)** - Structured task management:

```bash
# Create work item
templedb work create -p myproject -t "Fix auth bug" --type bug --priority high
# → Returns work item ID (e.g., tdb-a4f2e)

# Auto-dispatch to available agents
templedb work dispatch -p myproject

# Agent checks mailbox
templedb work mailbox <session-id>

# Update work status
templedb work status tdb-a4f2e in_progress
templedb work status tdb-a4f2e completed

# View coordination metrics
templedb work metrics -p myproject
```

**Key features:**
- ACID transactions (no merge conflicts)
- Atomic work item updates
- Centralized mailbox system
- Version-based conflict detection
- Database-native task tracking

### 5. MCP (Model Context Protocol) Integration

**TempleDB exposes operations as MCP tools** for Claude Code:

**Available MCP Tools:**
- `templedb_project_list` - List all projects
- `templedb_project_show` - Show project details
- `templedb_project_import` - Import git repository
- `templedb_project_sync` - Sync with filesystem
- `templedb_query` - Execute SQL queries
- `templedb_context_generate` - Generate LLM context
- `templedb_search_files` - Search by file path
- `templedb_search_content` - Search file contents
- `templedb_commit_list` - List commits
- `templedb_commit_create` - Record commit

**Configuration** (`.mcp.json`):
```json
{
  "mcpServers": {
    "templedb": {
      "command": "./templedb",
      "args": ["mcp", "serve"],
      "env": {
        "TEMPLEDB_DB_PATH": "~/.templedb/projdb.db"
      }
    }
  }
}
```

Claude Code automatically discovers and uses these tools.

### 6. File Tracking & Type Detection

**25+ file types automatically identified:**
- JavaScript, TypeScript, JSX, TSX
- Python, Rust, Go, Java
- SQL files and migrations
- Markdown, JSON, YAML
- Edge functions, serverless functions
- Configuration files

**Metadata extracted:**
- Lines of code
- Component/function names
- Complexity metrics
- Dependencies
- Git metadata

### 7. Content-Addressed Storage

**50% storage reduction** via deduplication:
- Files stored by SHA-256 hash in `content_blobs`
- Versions reference blobs, not duplicate content
- Same file content stored once, referenced many times

### 8. Nix Environment Management

**Reproducible development environments:**

```bash
templedb env detect <project>              # Auto-detect packages
templedb env new <project> <env-name>      # Create environment
templedb env enter <project> [<env>]       # Enter Nix shell
```

**Features:**
- Expression caching (< 1s boot time)
- Package dependency tracking
- Multiple environments per project
- FHS (Filesystem Hierarchy Standard) compatibility

### 9. Secrets Management

**age-encrypted secrets** with profile support:

```bash
templedb secret init <project> --age-recipient <key>
templedb secret edit <project> [--profile <prof>]
templedb secret export <project> --format <fmt>  # shell/json/yaml/dotenv
```

**Features:**
- Hardware-backed encryption (Yubikey support)
- Multiple secret profiles (dev/staging/prod)
- Database-native storage
- Secure export formats

### 10. Terminal UI (TUI)

**Interactive interface** with real-time updates:

```bash
templedb tui
```

**Capabilities:**
- Project dashboard
- File browser
- Commit history viewer
- Staging area (visual file staging)
- Diff viewer
- Multi-session monitoring
- Agent coordination panel

---

## CLI Command Reference

### Projects
```bash
templedb project import <path>              # Import git project
templedb project list                       # List all projects
templedb project show <slug>                # Show project details
templedb project sync <proj>                # Re-sync with filesystem
```

### Checkout/Commit Workflow
```bash
templedb project checkout <proj> <dir>      # Checkout to filesystem
templedb project commit <proj> <dir> -m <msg> # Commit changes back
templedb project checkout-list [<proj>]     # List active checkouts
templedb project checkout-cleanup [<proj>]  # Remove stale checkouts
```

### Version Control
```bash
templedb vcs add -p <proj> [--all] [files...]    # Stage files
templedb vcs reset -p <proj> [--all] [files...]  # Unstage files
templedb vcs commit -m <msg> -p <proj>           # Commit staged changes
templedb vcs status <proj>                       # Show working state
templedb vcs log <proj> [-n <num>]               # View commit history
templedb vcs diff <proj> [--staged]              # Show diffs
templedb vcs show <proj> <commit>                # Show commit details
templedb vcs branch <proj> [<name>]              # Manage branches
```

### Agent Sessions
```bash
templedb agent start --project <proj> [--goal <text>]  # Start session
templedb agent end <session-id>                        # End session
templedb agent list [--project <proj>]                 # List sessions
templedb agent status <session-id>                     # Show details
templedb agent history <session-id>                    # View interactions
templedb agent context <session-id>                    # Export context
```

### Multi-Agent Coordination
```bash
templedb work create -p <proj> -t <title> [--type <type>] [--priority <pri>]
templedb work list [-p <proj>] [-s <status>]
templedb work show <item-id>
templedb work assign <item-id> <session-id>
templedb work status <item-id> <status>
templedb work mailbox <session-id>
templedb work dispatch [-p <proj>] [--priority <pri>]
templedb work agents [-p <proj>]
templedb work metrics [-p <proj>]
```

### Search
```bash
templedb search content <pattern> [-p <proj>] [-i]  # Search file contents
templedb search files <pattern> [-p <proj>]         # Search file names
```

### LLM Context
```bash
templedb llm context <proj>        # Generate context
templedb llm export <proj> [<out>] # Export to JSON
templedb llm schema                # Show schema
```

### Environments
```bash
templedb env enter <proj> [<env>]  # Enter Nix environment
templedb env list [<proj>]         # List environments
templedb env detect <proj>         # Auto-detect packages
templedb env new <proj> <env>      # Create environment
```

### Secrets
```bash
templedb secret init <proj> --age-recipient <key>
templedb secret edit <proj> [--profile <prof>]
templedb secret export <proj> --format <fmt>
templedb secret print-raw <proj>
```

### MCP Server
```bash
templedb mcp serve  # Start Model Context Protocol server
```

### System
```bash
templedb status      # Show database status
templedb tui         # Launch terminal UI
templedb backup      # Backup database
templedb restore     # Restore from backup
```

---

## Common SQL Query Patterns

### Cross-Project Analysis

**Find all React components across projects:**
```sql
SELECT project_slug, file_path, lines_of_code
FROM files_with_types_view
WHERE type_name = 'jsx_component'
ORDER BY project_slug;
```

**Get total LOC per project:**
```sql
SELECT
  p.slug,
  COUNT(pf.id) as file_count,
  SUM(pf.lines_of_code) as total_lines
FROM projects p
LEFT JOIN project_files pf ON pf.project_id = p.id
GROUP BY p.id
ORDER BY total_lines DESC;
```

**Find largest files:**
```sql
SELECT project_slug, file_path, lines_of_code
FROM files_with_types_view
ORDER BY lines_of_code DESC
LIMIT 20;
```

### File Search

**Find files by name pattern:**
```sql
SELECT project_slug, file_path
FROM files_with_types_view
WHERE file_path LIKE '%auth%'
ORDER BY project_slug;
```

**Read file from database:**
```sql
SELECT content_text
FROM current_file_contents_view
WHERE project_slug = 'myproject'
  AND file_path = 'src/main.py';
```

### Version Control

**View commit history:**
```sql
SELECT commit_hash, author, commit_message, committed_at
FROM vcs_commit_history_view
WHERE project_slug = 'myproject'
ORDER BY committed_at DESC
LIMIT 10;
```

**See files changed in commits:**
```sql
SELECT
  c.commit_hash,
  c.commit_message,
  pf.file_path,
  cf.change_type
FROM vcs_commits c
JOIN vcs_commit_files cf ON cf.commit_id = c.id
JOIN project_files pf ON cf.file_id = pf.id
WHERE c.project_id = (SELECT id FROM projects WHERE slug = 'myproject')
ORDER BY c.committed_at DESC;
```

---

## Development Guidelines

### When Working with TempleDB

1. **Use the checkout/commit workflow** for file editing
   - Don't edit database records directly for file content
   - Always checkout → edit → commit

2. **Prefer TempleDB VCS over git**
   - Use `templedb vcs` commands, not `git`
   - Database is the source of truth, not .git

3. **Leverage MCP tools when available**
   - Use `templedb_*` MCP tools in Claude Code
   - Fall back to CLI commands if MCP unavailable

4. **Track agent sessions properly**
   - Start session with `agent start`
   - Set `TEMPLEDB_SESSION_ID` environment variable
   - Use `--ai-assisted` flag on commits

5. **Use work items for coordination**
   - Create work items for tasks
   - Use auto-dispatch for parallel agent work
   - Check mailbox regularly

6. **Query with SQL for analysis**
   - Use views for common patterns
   - Add LIMIT clauses for large datasets
   - Leverage content-addressed storage for deduplication

### Anti-Git Guidelines

**Never use git commands** when TempleDB equivalents exist:

❌ **Don't:**
- `git add` → Use `templedb vcs add`
- `git commit` → Use `templedb vcs commit`
- `git status` → Use `templedb vcs status`
- `git log` → Use `templedb vcs log`
- `git branch` → Use `templedb vcs branch`
- `git diff` → Use `templedb vcs diff`

✅ **Do:**
- Use TempleDB VCS commands
- Query database for history
- Trust database as source of truth
- Use checkout/commit workflow

See `.claude/skills/ANTI_GIT_GUIDELINES.md` for complete patterns.

---

## Performance Characteristics

### Optimizations

- ⚡ **Connection pooling** - 3-5x faster operations
- 🚀 **Batch operations** - 50-100x faster imports
- 💾 **WAL mode** - Concurrent readers/writers
- 🔄 **Nix expression caching** - < 1s boot time
- 📊 **Optimized queries** - Proper indexes on all tables
- 💿 **64MB cache** + **256MB mmap** - Fast in-memory operations

### Benchmarks

See `PERFORMANCE.md` for detailed benchmarks and tuning guide.

---

## File Locations

### Database
- **Primary database**: `~/.local/share/templedb/templedb.sqlite`
- **Backup location**: `~/.local/share/templedb/backups/`

### Configuration
- **Project config**: `.mcp.json` (MCP server configuration)
- **Skills**: `.claude/skills/*/SKILL.md`
- **System config**: `~/.config/templedb/config.yaml` (optional)

### Temporary Workspaces
- **Checkouts**: User-specified (e.g., `/tmp/workspace`)
- **Tracked in**: `project_checkouts` table

---

## Available Skills

TempleDB includes several Claude Code skills in `.claude/skills/`:

- **templedb-projects** - Project management (import, list, status)
- **templedb-query** - Database queries and LLM context generation
- **templedb-vcs** - Version control operations
- **templedb-environments** - Nix environment management
- **templedb-secrets** - Secrets management
- **templedb-cathedral** - Package export/import for sharing

Each skill has MCP tool integration and CLI fallbacks.

---

## Key Documentation Files

### Essential Reading
- `README.md` - Overview and quick start
- `DESIGN_PHILOSOPHY.md` - Why TempleDB exists (O(k) vs O(k²))
- `GETTING_STARTED.md` - Installation and beginner's guide
- `MCP_INTEGRATION.md` - Model Context Protocol integration details

### User Guides
- `GUIDE.md` - Complete usage guide
- `QUICKSTART.md` - Advanced workflows
- `FILES.md` - File tracking and versioning
- `TUI.md` - Terminal UI guide
- `EXAMPLES.md` - SQL query examples
- `AGENT_SESSIONS.md` - AI agent session management
- `MULTI_AGENT_COORDINATION.md` - Multi-agent coordination and work items

### Critical Reference
- `QUERY_BEST_PRACTICES.md` - ⚠️ Critical query constraints
- `DATABASE_CONSTRAINTS.md` - ⚠️ Critical uniqueness constraints

### Advanced Topics
- `docs/DEPLOYMENT_EXAMPLE.md` - Production deployment
- `docs/advanced/ADVANCED.md` - Performance tuning
- `docs/advanced/YUBIKEY_SECRETS.md` - Hardware-backed encryption
- `docs/advanced/CATHEDRAL.md` - Multi-user setup

### Project Info
- `ROADMAP.md` - Future features
- `CHANGELOG.md` - Version history
- `RELEASE_NOTES.md` - Latest release notes
- `TRIBUTE.md` - Dedication to Terry Davis

---

## Philosophy in Practice

### Single Source of Truth

```
Traditional Git Workflow:
├── main branch checkout (copy 1)
├── feature-a branch checkout (copy 2)
├── feature-b branch checkout (copy 3)
└── Multiple copies, merge conflicts

TempleDB Workflow:
├── Database (single source of truth)
├── Checkout 1 → edit → commit (version tracking)
├── Checkout 2 → edit → commit (version tracking)
└── No duplicate state, version-based conflict detection
```

### Temporary Denormalization

**Philosophy**: Use familiar tools (vim, vscode, grep) by temporarily extracting files, then re-normalize back to database.

**Benefits**:
- Edit with ANY tool that works with files
- No learning curve for developers
- Database ensures consistency
- Atomic commits with conflict detection

### Multi-Agent Coordination

**Database-native approach**:
- Single source of truth in database
- ACID transactions eliminate conflicts
- Work items and mailbox system for task assignment
- Version-based conflict detection instead of content merging

---

## Tribute

This project is dedicated to **Terry A. Davis** (1969-2018), creator of TempleOS. Terry showed us that simplicity, transparency, and building from first principles can create something beautiful and profound.

> *"God's temple is everything."* - Terry A. Davis

TempleDB carries forward this philosophy: treating your codebase as a sacred space, maintaining truth through normalization, and building on solid foundations (SQLite, Nix, age encryption).

---

## Quick Reference Card

**Most Common Operations:**

```bash
# Import a project
./templedb project import /path/to/project

# Edit files (checkout → edit → commit)
./templedb project checkout myproject /tmp/work
cd /tmp/work && vim src/file.py
./templedb project commit myproject /tmp/work -m "Fix bug"

# Version control
./templedb vcs status myproject
./templedb vcs add -p myproject --all
./templedb vcs commit -m "Update" -p myproject

# Start agent session
./templedb agent start --project myproject --goal "Task description"
export TEMPLEDB_SESSION_ID=1

# Query database
sqlite3 ~/.local/share/templedb/templedb.sqlite "SELECT * FROM projects"

# Launch TUI
./templedb tui
```

---

**Database Location**: `~/.local/share/templedb/templedb.sqlite`
**Project Root**: `/home/zach/templeDB`
**Documentation**: See README.md and docs/ directory
**MCP Config**: `.mcp.json`
**Skills**: `.claude/skills/*/SKILL.md`

---

*TempleDB - Where your code finds sanctuary*
