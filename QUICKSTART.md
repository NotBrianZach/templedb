# TempleDB Quick Start

## Simple Workflow (What You Asked For!)

### Launch Claude with Project Context

```bash
# One command - that's it!
./tdb claude woofs_project
```

This will:
- ✅ Verify the project exists in TempleDB
- ✅ Set your agent identifier (TEMPLEDB_USER)
- ✅ Launch Claude Code with instructions to load project context
- ✅ All TempleDB MCP tools are auto-approved (no permission prompts!)

### First Time Setup

```bash
# 1. Import your project into TempleDB
./tdb import https://github.com/user/woofs_project woofs_project

# 2. Launch Claude
./tdb claude woofs_project
```

That's it! No more:
- ❌ Manual context generation commands
- ❌ Permission approval dialogs
- ❌ Setting environment variables
- ❌ Complex workflows

## What Just Got Better

### Before (Annoying):
```bash
# Import project
./templedb project import https://github.com/user/woofs_project --name woofs_project

# Open Claude Code
claude

# Wait for Claude to start...
# Type: "Generate context for woofs_project"
# Click "Approve" for templedb_context_generate
# Click "Approve" for templedb_search_files
# Click "Approve" for templedb_query
# ...click approve 10 more times...
```

### After (Easy):
```bash
./tdb claude woofs_project
```

Done! 🎉

## Available TempleDB Tools (All Auto-Approved)

When you use `./tdb claude`, all these MCP tools work without permission prompts:

### Project & Context
- `templedb_project_list` - List all projects
- `templedb_project_show` - Get project details
- `templedb_project_import` - Import a git repo
- `templedb_project_sync` - Sync with filesystem
- `templedb_context_generate` - Generate full project context

### Search & Query
- `templedb_search_files` - Find files by pattern
- `templedb_search_content` - Search code content
- `templedb_query` - Run SQL queries

### Version Control
- `templedb_commit_list` - List commits
- `templedb_commit_create` - Record commits

## Other Useful Commands

```bash
# List all projects
./tdb list

# Sync project with filesystem (after making changes)
./tdb sync woofs_project

# Import another project
./tdb import https://github.com/user/another-repo another_project

# Use the full CLI for advanced features
./templedb --help
./templedb work --help      # Work items / task management
./templedb vcs --help       # Version control
./templedb search --help    # Advanced search
```

## Work Items / AI Swarms

Work items still work great - now with simpler agent identifiers:

```bash
# Set your agent identity
export TEMPLEDB_USER=agent-1

# Create work items
./templedb work create --project woofs_project --title "Deploy to staging"

# Assign to agents (any identifier)
./templedb work assign tdb-abc12 agent-1
./templedb work assign tdb-def34 agent-2

# Query your work
./templedb work list --assigned-to agent-1

# Check notifications
./templedb work mailbox agent-1
```

### Multiple Agents Working in Parallel

```bash
# Terminal 1 - Agent 1
export TEMPLEDB_USER=agent-1
./tdb claude woofs_project

# Terminal 2 - Agent 2
export TEMPLEDB_USER=agent-2
./tdb claude woofs_project

# Terminal 3 - Coordinator
./templedb work create --project woofs_project --title "Update API"
./templedb work assign tdb-abc12 agent-1
./templedb work assign tdb-def34 agent-2
```

Each agent can query their work items and coordinate via the database!

## Tips

1. **Set a permanent agent ID** (optional):
   ```bash
   # Add to ~/.bashrc or ~/.zshrc
   export TEMPLEDB_USER=claude-myname
   ```

2. **Project location**: The `tdb` command automatically changes to your project directory if it exists

3. **Already in Claude?** If you run `./tdb claude project` while already in a Claude session, it just shows you what MCP tools are available

4. **Full power**: Use `./templedb` for the full CLI when you need advanced features

## Configuration

Auto-approvals are configured in `.claude/settings.local.json` - you can edit this file to add/remove permissions.

The MCP server is configured in `.mcp.json` at the project root - Claude Code discovers this automatically.
