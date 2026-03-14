<div align="center">

![TempleDB Banner](assets/banner.svg)

</div>

> *"God's temple is everything."* - Terry A. Davis


---

## What is TempleDB?

<img src="assets/logo.svg" align="right" width="150" alt="TempleDB Logo"/>

TempleDB is a new way to write and deploy software. By moving from files to sqlite tables  your codebase becomes a temple - a sacred, organized space where every line, every change is normalized, versioned, and queryable.

We throw out of the temple those that would lend us technical debt in the form of state duplication, namely filesystem centric tools like git, sops, and potentially including ci/cd and deployment tools like docker. (though in the case of git it's loitering just outside the temple both for legacy compatibility reasons and also due to our affinity for nixos to tide us over until the day we can make some much more radical changes to operating systems)

### Philosophy

As TempleOS showed us the power of simplicity and first principles, so TempleDB embraces:

- **Database normalization**: Single source of truth, no redundant copies
- **ACID transactions&Transparency**: Multi-agent coordination without conflicts
- **Temporary denormalization&Re-normalization workflow**: Nix FHS environments for efficient editing

**Key insight**: With k git worktree checkouts of n files, traditional agent swarm workflows require O(k²) pairwise comparisons to verify consistency—quadratic coordination cost. TempleDB maintains a single source of truth, reducing verification to O(k) comparisons. This asymptotic improvement (O(k) factor) becomes significant as teams and branches scale. Storage savings (10-50×) are a bonus.

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
- Database stores **one copy** of each file (content-addressed, versioned)
- You edit with **familiar tools** (anything that works with files)
- Commits are **atomic** with conflict detection
- Multiple agents can work **safely** (optimistic locking with version tracking)

**Example workflow (AI Agent with Claude Code):**
```bash
# User initializes project (one-time setup)
$ cd ~/myproject
$ templedb project init
✓ Created .templedb/ marker
✓ Project 'myproject' initialized in database

# User starts Claude Code in project directory
$ cd ~/myproject
$ claude-code

# Interactive session:
User: "Fix the authentication bug"

Claude: Let me help you fix the authentication bug. I'll search the codebase
        using TempleDB MCP tools.

# Claude uses MCP tools behind the scenes:
mcp_templedb_vcs_status(project="myproject")
mcp_templedb_search_content(query="auth", project="myproject")

Claude: I found the issue in src/auth.py at line 42. Let me read the current code.

# Claude reads directly from database (no checkout needed!)
mcp_templedb_query(query="""
  SELECT cb.content_text FROM project_files pf
  JOIN file_contents fc ON fc.file_id = pf.id
  JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
  WHERE pf.file_path = 'src/auth.py' AND pf.project_id =
    (SELECT id FROM projects WHERE slug = 'myproject')
""")

Claude: The token validation is missing. I'll fix it using the Edit tool.

# Claude edits the file directly in the project directory
Edit(file_path="/home/user/myproject/src/auth.py",
     old_string="...", new_string="...")

Claude: Now I'll commit the changes to TempleDB.

# Claude stages and commits using MCP
mcp_templedb_vcs_add(project="myproject", files=["src/auth.py"])
mcp_templedb_vcs_commit(
  project="myproject",
  message="Fix authentication token validation",
  author="Claude <noreply@anthropic.com>"
)

Claude: ✓ Fixed! The authentication bug has been resolved and committed.

User: "Show me what changed in the last 3 commits"

# Claude queries commit history
mcp_templedb_vcs_log(project="myproject", limit=3)

Claude: Here are the last 3 commits:
        1. Fix authentication token validation (just now)
        2. Add user registration endpoint (2 hours ago)
        3. Update API documentation (yesterday)
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

### 5. **AI Agent Session Management**

Track AI agent sessions with automatic commit linking:

```bash
# Start an agent session
./templedb agent start --project myproject --goal "Implement authentication"
# → Session ID: 1

# Export session ID to link commits
export TEMPLEDB_SESSION_ID=1

# Checkout and work
./templedb project checkout myproject /tmp/work
cd /tmp/work && vim src/auth.py

# Commit - automatically linked to session
./templedb project commit myproject /tmp/work -m "Add auth" --ai-assisted

# View session status
./templedb agent status 1
# → Shows commits, interactions, duration

# End session
./templedb agent end 1
```

**Features:**
- Session lifecycle tracking (start/active/completed)
- Automatic commit-to-session linking via `TEMPLEDB_SESSION_ID`
- Interaction history logging
- Context snapshot generation
- Session analytics (duration, commits, metrics)

**See [AGENT_SESSIONS.md](AGENT_SESSIONS.md) for complete guide.**

---

## Installation

### Quick Install

```bash
git clone https://github.com/yourusername/templedb.git
cd templedb
./install.sh
```

The installer will:
- ✓ Check dependencies (Python, SQLite, git, age)
- ✓ Install `templedb` to your PATH
- ✓ Initialize the database at `~/.local/share/templedb/templedb.sqlite`
- ✓ Optionally import an example project

### Requirements

- Python 3.9+
- SQLite 3.35+
- git
- age (optional, for secret management)

See **[GETTING_STARTED.md](GETTING_STARTED.md)** for detailed installation instructions.

### AI Assistant Integration

**For Claude Code users**: TempleDB includes a comprehensive project context file for AI assistants:

```bash
# Launch Claude Code with full TempleDB context
./templedb claude

# Or if you have templedb in your PATH
templedb claude

# You can also pass additional arguments
./templedb claude --model opus

# Alternatively, use the claude command directly
claude --append-system-prompt-file .claude/project-context.md
```

The project context file (`.claude/project-context.md`) provides:
- Complete architecture overview
- CLI command reference
- Common SQL query patterns
- Development guidelines
- MCP integration details
- Multi-agent coordination guide

This ensures AI assistants have comprehensive understanding of TempleDB's philosophy, commands, and workflows from the start.

### MCP Server for AI Agents

TempleDB includes a Model Context Protocol (MCP) server that exposes the database directly to AI agents like Claude Code:

**Setup (one-time):**

```bash
# Option 1: Configure in Claude Desktop (~/.config/claude/claude_desktop_config.json)
{
  "mcpServers": {
    "templedb": {
      "command": "/path/to/templedb",
      "args": ["mcp", "serve"]
    }
  }
}

# Option 2: Or start manually for testing
./templedb mcp serve
```

**Usage:**

```bash
# Start Claude Code (MCP server auto-connects if configured)
$ claude-code

# Now interact naturally - Claude uses TempleDB MCP tools automatically:
You: "Show me all Python files in myproject"
Claude: [uses mcp_templedb_search_files to query database]

You: "Fix the bug in auth.py"
Claude: [reads from DB, edits, commits - all via MCP tools]

You: "What changed in the last 3 commits?"
Claude: [uses mcp_templedb_vcs_log to show history]
```

**Available MCP Tools:**
- `templedb_project_list/show/import/sync` - Project management
- `templedb_vcs_status/add/commit/log/diff/branch` - Version control operations
- `templedb_search_files/content` - Code search across all projects
- `templedb_query` - Direct SQL queries for complex analysis
- `templedb_context_generate` - Generate LLM context for projects
- `templedb_commit_list/create` - Commit tracking and creation
- `templedb_env_get/set/list` - Environment variable management
- `templedb_deploy` - Deployment orchestration

**Agent Workflow Benefits:**
- ✅ No filesystem checkouts needed - direct database access
- ✅ Atomic operations with ACID guarantees
- ✅ Multi-agent coordination via database transactions
- ✅ Query across all projects with SQL
- ✅ Automatic conflict detection and version tracking
- ✅ Natural language interface - just ask Claude to do things!

See the interactive example workflow above for a complete session.

---

## Quick Start

### 1. Initialize a Project

TempleDB uses git-like CWD-based project discovery with `.templedb/` markers:

```bash
# Initialize current directory as a TempleDB project
cd ~/myproject
./templedb project init

# Or import an existing project from elsewhere
./templedb project import /path/to/project --slug myproject
```

This creates a `.templedb/` marker in your project root - just like `.git/`!

### 2. View Projects

```bash
# View database status
./templedb status

# List all projects
./templedb project list

# Show current project details (from anywhere in project tree)
cd ~/myproject/src
./templedb project show

# Or show specific project
./templedb project show myproject
```

### 3. Work with Files

**Option A: AI Agent/Claude Code (via MCP - recommended for agents)**

```bash
# Start Claude Code in your project directory
cd ~/myproject
claude-code

# Claude uses TempleDB MCP tools to:
# - Check project status: mcp_templedb_vcs_status(project="myproject")
# - Search files: mcp_templedb_search_content(query="auth")
# - Read from database: mcp_templedb_query(...)
# - Edit files directly: Edit(file_path="src/main.py", ...)
# - Commit changes: mcp_templedb_vcs_commit(...)

# No checkouts needed - Claude edits files in-place and commits to database!
```

**Option B: Human Developer (Direct Editing)**

```bash
# Work in your project directory (like with git)
cd ~/myproject
vim src/main.py              # Edit files normally

# Sync changes to database
./templedb project sync

# Or use VCS workflow with staging
./templedb vcs add src/main.py
./templedb vcs commit -m "Fixed authentication"
```

**Option C: Explicit Checkout/Commit Workflow**

```bash
# For working in isolated temp locations
./templedb project checkout myproject /tmp/workspace
cd /tmp/workspace && vim src/main.py
./templedb project commit myproject /tmp/workspace -m "Fix"
rm -rf /tmp/workspace
```

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
- **Content-addressed storage** - Files stored by hash, referenced by version

### File Tracking

- **25+ file types** - JavaScript, Python, SQL, JSX, Edge Functions, etc.
- **Metadata** - LOC, complexity, git info, dependencies
- **Components** - Extract function/component names
- **Storage efficiency** - 50% reduction via content-addressable blobs

### Version Control System

- **Branches** - Database-native branching
- **Commits** - Atomic changesets with SHA-256 hashing
- **Version history** - All file versions tracked
- **Working state** - Track modified/staged files
- **Conflict detection** - Optimistic locking prevents data loss
- **Multi-agent safe** - Coordinated concurrent edits

### Checkout/Commit Workflow

- **Temporary denormalization** - Extract files to filesystem
- **Edit with any tool** - vim, vscode, grep, find, etc.
- **Re-normalize** - Commit changes back to database
- **Conflict detection** - Version-based optimistic locking
- **Atomic operations** - All changes in transactions

### AI Agent Integration

**Agent Session Management:**
- **Session tracking** - Create, manage, and monitor AI sessions
- **Automatic commit linking** - Link commits via `TEMPLEDB_SESSION_ID` env var
- **Interaction logging** - Record all agent interactions
- **Context snapshots** - Generate and store project context for agents
- **Session analytics** - Duration, commits, metrics per session
- **Multi-agent support** - Track multiple concurrent agent sessions

**Multi-Agent Coordination** ⭐ NEW - Inspired by [Gas Town](https://github.com/steveyegge/gastown):
- **Work Items (Beads)** - Structured task management with unique IDs (`tdb-xxxxx`)
- **Agent Coordinator** - Orchestrate multiple agents working in parallel
- **Auto-Dispatch** - Automatically assign work to least-busy agents
- **Mailbox System** - Asynchronous task assignment via database
- **Convoys** - Bundle related work items for coordinated execution
- **ACID Transactions** - Conflict-free multi-agent coordination

**LLM Context Provider:**
- **Schema overview** - Describe database structure
- **Project context** - Complete project information
- **File context** - File metadata and versions
- **Prompt generation** - Ready-to-use AI prompts

**See [MULTI_AGENT_COORDINATION.md](MULTI_AGENT_COORDINATION.md) for complete guide.**

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
- **[GETTING_STARTED.md](GETTING_STARTED.md)** - Installation and beginner's guide

### User Guides
- **[GUIDE.md](GUIDE.md)** - Complete usage guide (checkout/commit workflow, SQL queries, CLI commands)
- **[QUICKSTART.md](QUICKSTART.md)** - Advanced workflows for existing users
- **[DIRENV_INTEGRATION.md](DIRENV_INTEGRATION.md)** ⭐ NEW - Auto-load environments with direnv (v2.0)
- **[docs/VIBE.md](docs/VIBE.md)** ⭐ NEW - Vibe coding: Interactive learning from AI-generated code changes
- **[FILES.md](FILES.md)** - How file tracking and versioning works
- **[TUI.md](TUI.md)** - Terminal UI guide
- **[EXAMPLES.md](EXAMPLES.md)** - SQL query examples and common patterns
- **[WORK_COORDINATION.md](WORK_COORDINATION.md)** ⭐ - Work items and multi-agent coordination
- **[VCS_METADATA_GUIDE.md](VCS_METADATA_GUIDE.md)** - Commit metadata and AI attribution

### Critical Reference
- **[QUERY_BEST_PRACTICES.md](QUERY_BEST_PRACTICES.md)** - ⚠️ **Critical**: Query constraints and best practices (read this!)
- **[DATABASE_CONSTRAINTS.md](DATABASE_CONSTRAINTS.md)** - ⚠️ **Critical**: All uniqueness constraints and foreign keys

### Advanced Topics
- **[Multi-Key Secret Management](docs/MULTI_KEY_SECRET_MANAGEMENT.md)** ⭐ NEW - Multi-recipient encryption with Yubikeys + filesystem keys
- **[Deployment Guide](docs/DEPLOYMENT_EXAMPLE.md)** ⭐ - Complete deployment workflow for production
- **[Deployment Resilience](DEPLOYMENT_RESILIENCE.md)** ⭐ NEW - Retry logic, error handling, and production best practices
- **[Deployment Rollback](DEPLOYMENT_ROLLBACK.md)** - Rollback failed deployments
- **[Performance & Optimization](docs/advanced/ADVANCED.md)** - Tuning, Nix environments
- **[Yubikey Secrets](docs/advanced/YUBIKEY_SECRETS.md)** - Hardware-backed encryption
- **[Multi-User Setup](docs/advanced/CATHEDRAL.md)** - Teams and collaboration
- **[Building from Source](docs/advanced/BUILD.md)** - Development setup
- **[Security](docs/advanced/SECURITY.md)** - Security considerations

### Project Info
- **[ROADMAP.md](ROADMAP.md)** - Future features and development plans
- **[CHANGELOG.md](CHANGELOG.md)** - Version history
- **[RELEASE_NOTES.md](RELEASE_NOTES.md)** - Latest release notes
- **[MIGRATIONS.md](MIGRATIONS.md)** - Schema evolution history

### Implementation Details
- **[Implementation Docs](docs/implementation/)** - Historical analyses, refactors, and completed work

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

# Secrets (age encryption)
templedb secret init <proj> --age-recipient <key>  # Initialize secrets
templedb secret edit <proj> [--profile <prof>]     # Edit secrets
templedb secret export <proj> --format <fmt>       # Export (shell/json/yaml/dotenv)
templedb secret print-raw <proj>                   # Print encrypted blob

# Interactive TUI
templedb tui                   # Launch terminal UI with VCS features:
                               # - Interactive staging (stage/unstage files visually)
                               # - Commit creation dialog
                               # - Commit history with diff viewing
                               # - Staged changes diff viewer
                               # See TUI_VCS_ENHANCEMENTS.md for details

# Environments
templedb env enter <proj> [<env>]  # Enter Nix environment
templedb env list [<proj>]         # List environments
templedb env detect <proj>         # Auto-detect packages
templedb env new <proj> <env>      # Create new environment
templedb env generate <proj> <env> # Generate Nix expression

# Version Control (with staging area)
templedb vcs add -p <proj> [--all] [files...]       # Stage files for commit
templedb vcs reset -p <proj> [--all] [files...]     # Unstage files
templedb vcs diff <proj> [--staged]                 # Show diffs (staged or working)
templedb vcs show <proj> <commit>                   # Show commit details with diff
templedb vcs commit -m <msg> -p <proj> [-a <author>] # Commit staged changes
templedb vcs status <proj>                          # Show staged and unstaged changes
templedb vcs log <proj> [-n <num>]                  # Show commit history
templedb vcs branch <proj> [<name>]                 # List or create branches

# Agent Sessions (AI tracking)
templedb agent start --project <proj> [--goal <text>]    # Start AI agent session
templedb agent end <session-id> [--status <status>]      # End session
templedb agent list [--project <proj>] [--status <stat>] # List sessions
templedb agent status <session-id> [--verbose]           # Show session details
templedb agent history <session-id> [--limit <n>]        # View interaction history
templedb agent context <session-id> [--output <file>]    # Export session context

# Multi-Agent Coordination (Work Items)
templedb work create -p <proj> -t <title> [--type <type>] [--priority <pri>]  # Create work item
templedb work list [-p <proj>] [-s <status>] [--priority <pri>]               # List work items
templedb work show <item-id>                                                   # Show item details
templedb work assign <item-id> <session-id>                                    # Assign to agent
templedb work status <item-id> <status>                                        # Update status
templedb work stats [-p <proj>]                                                # Show statistics
templedb work mailbox <session-id> [-s <status>]                              # Show agent mailbox
templedb work dispatch [-p <proj>] [--priority <pri>]                          # Auto-dispatch work
templedb work agents [-p <proj>]                                               # List available agents
templedb work metrics [-p <proj>]                                              # Show coordination metrics

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

## Troubleshooting

### Claude Code in Emacs vterm

**Good news!** TempleDB now automatically detects Emacs vterm and uses a PTY wrapper (`script` command) to make Claude Code work properly.

When you run `templedb claude` in vterm, you'll see:

```
⚡ Detected Emacs vterm - using PTY wrapper for Claude Code

[Claude Code launches normally]
```

This works transparently - no configuration needed!

**Other non-TTY environments:**

If you're in a piped environment or CI/CD, Claude Code cannot run interactively. Use these alternatives:
- Use non-interactive TempleDB commands
- Run in a real terminal for interactive tools
- See [docs/TTY_DETECTION.md](docs/TTY_DETECTION.md) for details

---

## Contributing

Contributions or other maintainers are welcome.

---

*"An operating system is a temple."* - Terry A. Davis

**TempleDB - Where your code finds sanctuary**
