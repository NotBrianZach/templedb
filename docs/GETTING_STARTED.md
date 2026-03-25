# Getting Started

**TempleDB** - Database-native code management. One SQLite database replaces git checkouts, node_modules duplication, and filesystem chaos.

## Install

```bash
git clone https://github.com/yourusername/templedb.git
cd templedb
./install.sh
```

**Requirements:** Python 3.9+, SQLite 3.35+, git

## Quick Start (60 Seconds)

```bash
# Import a project
./templedb project import https://github.com/user/myapp

# Launch Claude Code with full context
./tdb claude myapp

# Or work directly
./templedb project list
./templedb project show myapp
sqlite3 ~/.local/share/templedb/templedb.sqlite
```

Done.

## Core Workflow: Checkout → Edit → Commit

**Database = source of truth. Filesystem = temporary workspace.**

```bash
# 1. Checkout files to edit
./templedb project checkout myapp /tmp/workspace

# 2. Edit with any tools
cd /tmp/workspace
vim src/main.py
npm run build
pytest

# 3. Commit changes back
./templedb project commit myapp /tmp/workspace -m "Fix auth bug"
```

Workspace is ephemeral. Database is permanent. No git merge conflicts.

## Why TempleDB?

**Traditional Dev Team (5 developers):**
- 5 devs × 3 branches each = 15 full checkouts
- 50K LOC × 15 = 750K lines duplicated on disk
- 500MB node_modules × 15 = 7.5GB dependencies
- "Did I merge the latest? Which auth.js is truth?"

**With TempleDB:**
- 50K LOC stored once in database
- Query database instead of git pull (10ms)
- Zero merge conflicts (ACID transactions)
- Single source of truth

## Claude Code Integration

```bash
# One command - auto-approves all MCP tools
./tdb claude myapp
```

No more clicking "Approve" 50 times. Full project context loaded automatically.

**Available MCP tools:**
- `templedb_project_list/show/import/sync`
- `templedb_search_files/content`
- `templedb_query` (run SQL)
- `templedb_context_generate` (full project context)
- `templedb_commit_list/create`
- `templedb_vcs_status/add/commit/log/diff`

## Multi-Agent Coordination

```bash
# Terminal 1 - Agent A
export TEMPLEDB_USER=agent-a
./tdb claude myapp

# Terminal 2 - Agent B
export TEMPLEDB_USER=agent-b
./tdb claude myapp

# Terminal 3 - Coordinator
./templedb work create --project myapp --title "Refactor auth"
./templedb work assign tdb-abc123 agent-a
./templedb work assign tdb-def456 agent-b
```

Agents coordinate via database. No git conflicts. Atomic commits.

## Secrets Management

```bash
# One-time setup
age-keygen -o ~/.config/sops/age/keys.txt
export TEMPLEDB_AGE_KEY_FILE=~/.config/sops/age/keys.txt

# Per-project
./templedb secret init myapp --age-recipient $(age-keygen -y $TEMPLEDB_AGE_KEY_FILE)
./templedb secret edit myapp
eval "$(./templedb secret export myapp --format shell)"
```

Secrets encrypted with age, stored in database, loaded on-demand.

## Query Anything

```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite

-- Find all Python files
SELECT file_path FROM project_files WHERE file_path LIKE '%.py';

-- Find auth-related code
SELECT file_path, line_content FROM file_lines
WHERE line_content LIKE '%authenticate%';

-- Compare file versions
SELECT v1.content, v2.content FROM file_versions v1
JOIN file_versions v2 ON v1.file_id = v2.file_id
WHERE v1.version = 1 AND v2.version = 2;

-- Cross-project dependency analysis
SELECT project_slug, COUNT(*) FROM project_files
WHERE file_path LIKE '%package.json%'
GROUP BY project_slug;
```

Your entire codebase is a SQL database. Query it.

## Terminal UI

```bash
pip install textual
./templedb tui
```

Keyboard-driven interface for projects, files, VCS, secrets, search.

**Keys:** `p` (projects), `v` (VCS), `x` (secrets), `s` (status), `?` (help), `q` (quit)

## Deployment

```bash
# Set up target
./templedb target add myapp production --provider supabase --host db.example.com

# Register domain + DNS
./templedb domain register myapp example.com --registrar cloudflare
./templedb domain dns configure myapp example.com --target production

# Deploy
./templedb deploy run myapp --target production
```

DNS, secrets, environment variables auto-configured. No manual steps.

## Installation Options

**Standalone (recommended):**
```bash
git clone https://github.com/yourusername/templedb.git
./templedb/templedb --help
```

**NixOS:**
```nix
{
  inputs.templedb.url = "github:yourusername/templedb";
  environment.systemPackages = [ inputs.templedb.packages.${system}.default ];
}
```

**Nix (non-NixOS):**
```bash
nix profile install github:yourusername/templedb
```

**Development:**
```bash
git clone https://github.com/yourusername/templedb.git
cd templedb
python3 src/main.py --help
```

## Command Reference

```bash
# Projects
./templedb project import <url>          # Add project from git
./templedb project list                  # List all
./templedb project show <slug>           # Details
./templedb project checkout <slug> <dir> # Extract to filesystem
./templedb project commit <slug> <dir>   # Save changes

# Version Control
./templedb vcs status <project>          # Show changes
./templedb vcs add <project> <file>      # Stage files
./templedb vcs commit -m "msg" -p <proj> # Commit
./templedb vcs log <project>             # History
./templedb vcs diff <project>            # Show diffs

# Secrets
./templedb secret init <proj> --age-recipient <key>
./templedb secret edit <project>
./templedb secret export <proj> --format shell

# Work Items (multi-agent)
./templedb work create --project <proj> --title "Task"
./templedb work list --assigned-to <agent>
./templedb work assign <work-id> <agent>
./templedb work complete <work-id>

# Search
./templedb search files <pattern>
./templedb search content <query>

# Deployment
./templedb target add <proj> <name> --provider <prov> --host <host>
./templedb domain register <proj> <domain> --registrar <reg>
./templedb deploy run <proj> --target <target>

# Database
./templedb status                        # Overall stats
./templedb tui                           # Interactive UI
sqlite3 ~/.local/share/templedb/templedb.sqlite
```

## Troubleshooting

**"templedb: command not found"**
```bash
export PATH="/path/to/templedb:$PATH"
```

**"age not found"**
```bash
# Ubuntu 22.04+
sudo apt install age

# macOS
brew install age

# Manual
wget https://github.com/FiloSottile/age/releases/latest/download/age-linux-amd64.tar.gz
tar xzf age-linux-amd64.tar.gz
sudo mv age/age /usr/local/bin/
```

**"Database is locked"**
```bash
lsof ~/.local/share/templedb/templedb.sqlite
# Wait or kill the process
```

## Next Steps

- **[DESIGN_PHILOSOPHY.md](DESIGN_PHILOSOPHY.md)** - Why database-native code management
- **[EXAMPLES.md](EXAMPLES.md)** - SQL query examples
- **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** - Full deployment guide
- **[docs/VCS.md](docs/VCS.md)** - Version control details
- **[docs/SECURITY.md](docs/SECURITY.md)** - Security best practices

## Database Location

`~/.local/share/templedb/templedb.sqlite`

To backup: `cp ~/.local/share/templedb/templedb.sqlite ~/backup/`

## Community

- **Issues:** https://github.com/yourusername/templedb/issues
- **Docs:** See `docs/` directory
- **Philosophy:** Read DESIGN_PHILOSOPHY.md

---

**Status:** v0.0.1 - Active development. Use for personal projects, not production infrastructure yet.
