<div align="center">

![TempleDB Banner](assets/banner.svg)

</div>

> *"God's temple is everything."* - Terry A. Davis


---

## What is TempleDB?

<img src="assets/logo.svg" align="right" width="150" alt="TempleDB Logo"/>
  Templedb is a project management and version control system focused on simplifying and unifying underlying abstractions to create a clean and introspectable environment for ai assisted development and deployment.

By moving from files and environment variables to sqlite tables your codebase becomes a temple - a sacred, organized space where every line, every change is normalized, versioned, and queryable.

Or, it's like a normalized version  of fossil-scm (sqlite, relational version of git) + claude mcp&stored procedures (api tuned for ai agent interactions) + superpowers (hierchical agent dispatch&contextualization) + gitnexus (dependency graph/clustering for ai contextualization) + nixops4 (deployment tool) + sops (secret management).

We throw out of the temple those that would lend us technical debt in the form of state duplication, namely filesystem centric tools like git, sops, ci/cd like jenkins and deployment tools like docker. (though in the case of git it's loitering just outside the temple both for legacy compatibility reasons and also due to our affinity for nixos to tide us over until the day we can make some much more radical changes to operating systems).

**Read [DESIGN_PHILOSOPHY.md](docs/DESIGN_PHILOSOPHY.md) for the complete rationale.**

---

## How It Works

TempleDB supports **two workflows** for working with your code:

### Workflow A: VCS Staging (Git-like) - Recommended for Development

Work directly in your project directory, just like with git:

```
┌─────────────┐          ┌──────────────┐          ┌─────────────┐
│  Database   │          │   Project    │   vcs    │  Database   │
│  (source of │          │  Directory   │  add +   │  (updated)  │
│   truth)    │          │  (.templedb) │  commit  │             │
└─────────────┘          └──────────────┘─────────>└─────────────┘
                              │
                              ▼
                         Edit in place:
                         vim, vscode, grep, etc.

                         Explicit staging workflow:
                         1. Edit files
                         2. tdb vcs add myproject file.py
                         3. tdb vcs commit -m "message"

                         (Conflict detection on commit)
```

**Use for:** Normal development, AI agents, continuous coding

**Key Point:** Like git, changes are NOT automatically saved to the database. You must explicitly stage (`vcs add`) and commit (`vcs commit`). The database provides conflict detection using three-way merge logic.

### Workflow B: Checkout/Commit - For Isolated Workspaces

Extract files to a temporary directory for one-off edits:

```
┌─────────────┐          ┌──────────────┐          ┌─────────────┐
│  Database   │ checkout │  Filesystem  │  commit  │  Database   │
│  (source of │─────────>│  (temporary  │─────────>│  (updated)  │
│   truth)    │          │  workspace)  │          │             │
└─────────────┘          └──────────────┘          └─────────────┘
       │                      │
       │                      ▼
       │                 Use ANY tool:
       │                 vim, vscode, grep, etc.
       │
       └─> Read-only by default
           tdb vcs edit → makes writable
           tdb vcs discard → return to read-only

           Explicit commit workflow:
           1. tdb project checkout myproject /tmp/work
           2. tdb vcs edit myproject
           3. Edit files in /tmp/work
           4. tdb project commit myproject /tmp/work -m "message"

           (Conflict detection on commit)
```

**Use for:** Experimentation, one-off changes, isolated testing

**Key Point:** Checkouts are read-only by default to prevent accidental edits. Use `vcs edit` to enable editing. Like Workflow A, changes require an explicit commit - nothing is automatic.

**Why both work:**
- Database stores **one copy** of each file (content-addressed, versioned)
- You edit with **familiar tools** (anything that works with files)
- Commits are **explicit and atomic** - nothing is automatic
- Changes require **manual staging** (`vcs add`) and **commit** (`vcs commit`)
- **Conflict detection** on commit (three-way merge logic)
- Multiple agents can work **safely** (optimistic locking with version tracking)
- Read-only checkouts prevent accidental modifications

**Three-way merge conflict detection:**

TempleDB uses three content hashes to intelligently detect conflicts:

1. **Base** (cached hash) - What the file was when you started editing
2. **Yours** (disk hash) - What you have now on disk
3. **Theirs** (db hash) - What the database has now

```
Scenario                              Decision
────────────────────────────────────  ────────────────────
Only you changed (disk ≠ base, db = base)     ✓ Commit allowed
Only they changed (db ≠ base, disk = base)    ✓ Pull update first
Both changed to same (disk = db ≠ base)       ✓ Commit allowed (idempotent)
Both changed differently (all different)      ✗ CONFLICT - manual merge required
```

This is the same approach used by git, Subversion, and other modern VCS systems. It prevents false conflicts and enables safe concurrent editing.

**Example conflict scenario:**

```bash
# You checkout and start editing
tdb project checkout myproject /tmp/work
# → TempleDB caches: src/auth.py hash = "abc123"

# You edit the file
vim /tmp/work/src/auth.py
# → Disk hash becomes: "xyz999"

# Meanwhile, someone else commits a change to the same file
# → Database hash becomes: "new456"

# You try to commit
tdb project commit myproject /tmp/work -m "My changes"

# TempleDB detects conflict:
# - Cached (base): abc123
# - Yours (disk): xyz999  ← You changed it
# - Theirs (db): new456   ← They changed it
# Result: ✗ Conflict! All three are different

# Error message:
# "Conflict detected in src/auth.py
#  Database version changed since checkout
#  Pull latest changes and resolve conflicts manually"
```

**Example workflow (AI Agent with Claude Code):**

*Note: This example uses **Workflow A (VCS Staging)** - the project directory already exists with files in place. No explicit checkout needed!*

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

# Claude reads directly from database
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

### 4a. **VCS Staging Workflow** (Recommended)

Work in your project directory like git (recommended for AI agents and normal development):

```bash
# 1. Initialize project with .templedb/ marker
cd ~/myproject
./templedb project init

# 2. Edit files normally (they're already in the directory!)
vim src/auth.py
grep -r "TODO" .

# 3. Stage and commit changes (git-like)
./templedb vcs add -p myproject src/auth.py
./templedb vcs commit -p myproject -m "Fix auth bug"

# Or stage all changes
./templedb vcs add -p myproject --all
./templedb vcs commit -p myproject -m "Multiple fixes"
```

### 4b. **Checkout/Edit/Commit Workflow** (Isolated Workspaces)

Extract to temporary directory for isolated edits (checkouts are read-only by default):

```bash
# 1. Extract project to filesystem (read-only)
./templedb project checkout myproject /tmp/workspace

# 2. Make checkout writable
./templedb vcs edit myproject

# 3. Edit with ANY tool (vim, vscode, grep, etc)
cd /tmp/workspace
vim file.py
grep -r "TODO" .

# 4a. Commit changes back to database
./templedb project commit myproject /tmp/workspace -m "Fixed bug"

# 4b. OR discard changes and return to read-only
./templedb vcs discard myproject

# Multi-agent conflict detection included!
```

### 4c. **File Edit Commands** (Quick Single-File Changes)

For quick edits to individual files:

```bash
# Edit file in $EDITOR (opens from project directory)
./templedb file edit myproject src/config.py

# Stage and commit
./templedb vcs add -p myproject src/config.py
./templedb vcs commit -p myproject -m "Update config"

# Or programmatically set content
echo "new content" | ./templedb file set myproject file.txt --stage
./templedb vcs commit -p myproject -m "Update via script"
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

### 6. **Workflow Orchestration & Code Intelligence**

Execute multi-phase operations with systematic safety checks:

```bash
# Bootstrap code intelligence (symbol extraction, dependency graphs)
templedb_workflow_execute {
  "workflow": "code_intelligence_bootstrap",
  "project": "myapp"
}

# Safe deployment with impact analysis and auto-rollback
templedb_workflow_execute {
  "workflow": "safe_deployment",
  "project": "myapp",
  "variables": {
    "primary_symbol": "authenticate_user",
    "production_health_url": "https://myapp.com/health",
    "previous_version": "v2.1.0"
  }
}

# Impact-aware refactoring with blast radius checks
templedb_workflow_execute {
  "workflow": "impact_aware_refactoring",
  "project": "myapp",
  "variables": {
    "target_symbol": "process_payment",
    "max_blast_radius": "150"
  }
}
```

**Features:**
- 3 production workflows (bootstrap, deployment, refactoring)
- Code intelligence: symbol extraction, dependency graphs, impact analysis
- Hybrid search (BM25 + graph ranking)
- Leiden algorithm for architectural boundaries
- Automatic rollback on failure
- Health checks with retries
- Test validation with coverage thresholds

**See [docs/WORKFLOWS.md](docs/WORKFLOWS.md) for complete guide.**

### 7. **Database-Native Git Server**

Serve repositories directly from SQLite as standard git repositories via HTTP:

```bash
# Configure git server (stored in database)
./templedb gitserver config get
./templedb gitserver config set git_server.port 9418

# Start the server
./templedb gitserver start
# → Git server started at http://localhost:9418

# Clone from database (no filesystem checkout!)
git clone http://localhost:9418/myproject

# Use in Nix flakes
{
  inputs = {
    myproject.url = "git+http://localhost:9418/myproject";
  };
}

# List available repositories
./templedb gitserver list-repos
```

**Features:**
- Zero filesystem checkouts - serve directly from SQLite
- Standard git smart HTTP protocol
- Works with git, Nix flakes, and all git clients
- Configurable host/port via database
- Automatic URL generation for templates
- On-the-fly git object generation from database

**See [docs/GIT_SERVER.md](docs/GIT_SERVER.md) for complete guide.**

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

See **[GETTING_STARTED.md](docs/GETTING_STARTED.md)** for detailed installation instructions.

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

## Documentation

### Essential Reading
- **[README.md](README.md)** - You are here! Overview and quick start
- **[DESIGN_PHILOSOPHY.md](docs/DESIGN_PHILOSOPHY.md)** - Why TempleDB exists (read this first!)
- **[GETTING_STARTED.md](docs/GETTING_STARTED.md)** - Installation and beginner's guide
- **[docs/WORKFLOWS.md](docs/WORKFLOWS.md)** ⭐ NEW - Workflow orchestration with code intelligence

### Workflows & Code Intelligence
- **[Workflows Guide](docs/WORKFLOWS.md)** - Execute multi-phase operations (deployment, refactoring, etc.)
- **[Code Intelligence Status](CODE_INTELLIGENCE_STATUS.md)** - Symbol extraction, dependency graphs, impact analysis
- **[Phase 2 Design](docs/phases/PHASE_2_DESIGN.md)** - Workflow orchestration architecture
- **[Documentation Index](docs/README.md)** - Complete docs organized by topic

### User Guides
- **[GUIDE.md](GUIDE.md)** - Complete usage guide (checkout/commit workflow, SQL queries, CLI commands)
- **[QUICKSTART.md](QUICKSTART.md)** - Advanced workflows for existing users
- **[DIRENV_INTEGRATION.md](docs/DIRENV_INTEGRATION.md)** ⭐ NEW - Auto-load environments with direnv (v2.0)
- **[docs/VIBE.md](docs/VIBE.md)** ⭐ NEW - Vibe coding: Interactive learning from AI-generated code changes
- **[FILES.md](FILES.md)** - How file tracking and versioning works
- **[TUI.md](docs/TUI.md)** - Terminal UI guide
- **[EXAMPLES.md](docs/EXAMPLES.md)** - SQL query examples and common patterns
- **[WORK_COORDINATION.md](docs/WORK_COORDINATION.md)** ⭐ - Work items and multi-agent coordination
- **[VCS_METADATA_GUIDE.md](docs/VCS_METADATA_GUIDE.md)** - Commit metadata and AI attribution

### Critical Reference
- **[QUERY_BEST_PRACTICES.md](docs/QUERY_BEST_PRACTICES.md)** - ⚠️ **Critical**: Query constraints and best practices (read this!)
- **[DATABASE_CONSTRAINTS.md](docs/DATABASE_CONSTRAINTS.md)** - ⚠️ **Critical**: All uniqueness constraints and foreign keys

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
- **[MIGRATIONS.md](docs/MIGRATIONS.md)** - Schema evolution history

### Implementation Details
- **[Implementation Docs](docs/implementation/)** - Historical analyses, refactors, and completed work

---

## CLI Commands

```bash
# Projects
templedb project init                 # Initialize .templedb/ marker in current directory
templedb project import <path>        # Import git project
templedb project list                 # List all projects
templedb project show <slug>          # Show project details
templedb project sync <proj>          # Re-import project from filesystem

# Checkout/Edit/Commit Workflow (with read-only protection)
templedb project checkout <proj> <dir>            # Checkout to filesystem (read-only)
templedb vcs edit <proj>                          # Make checkout writable
templedb project commit <proj> <dir> -m <msg>     # Commit changes back
templedb vcs discard <proj>                       # Discard changes, return to read-only
templedb project checkout-list [<proj>]           # List active checkouts
templedb project checkout-status <proj>           # Show checkout status
templedb project checkout-pull <proj>             # Pull latest changes to checkout
templedb project checkout-diff <proj>             # Show diff between checkout and DB
templedb project checkout-cleanup [<proj>]        # Remove stale checkouts

# File Commands (quick single-file editing)
templedb file show <proj> <path>                  # Display file content
templedb file edit <proj> <path>                  # Open in $EDITOR
templedb file get <proj> <path>                   # Get content programmatically
templedb file set <proj> <path> [--content] [--stage]  # Set content and optionally stage

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

## Contributing

Contributions or other maintainers are welcome.

---

*"An operating system is a temple."* - Terry A. Davis

**TempleDB - Where your code finds sanctuary**
