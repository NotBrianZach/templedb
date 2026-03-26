# TempleDB File Editing Feature

Easy file checkout and editing for TempleDB-tracked files across CLI, MCP, and Emacs.

## Overview

Three integrated ways to work with TempleDB-tracked files:

1. **CLI** - Direct terminal commands
2. **MCP** - Model Context Protocol integration (for Claude Code)
3. **Emacs** - Magit-like interface

## Quick Start

### CLI

```bash
# Show file content
templedb file show woofs_projects src/main.py

# Edit in $EDITOR
templedb file edit woofs_projects src/config.py

# Get content programmatically
templedb file get myproject README.md > /tmp/backup.md

# Set content from string or stdin
echo "new content" | templedb file set myproject file.txt --stage
templedb file set myproject config.json --content '{"key": "value"}'
```

### MCP (Claude Code)

```python
# In Claude Code, these tools are available automatically:
templedb_file_show(project="woofs_projects", file_path="src/main.py")
templedb_file_get(project="myproject", file_path="README.md")
templedb_file_set(project="myproject", file_path="config.js",
                   content="console.log('hello');", stage=True)
```

### Emacs

```elisp
;; Open status buffer
M-x templedb-magit-status

;; Navigate to file, press RET to edit
;; Or directly edit a file:
M-x templedb-magit-file-edit RET myproject RET src/main.py RET
```

## Implementation Details

### CLI Commands (`src/cli/commands/file.py`)

- `templedb file show <project> <file_path>` - Display content to stdout
- `templedb file cat <project> <file_path>` - Alias for show
- `templedb file get <project> <file_path>` - Programmatic alias (same as show)
- `templedb file edit <project> <file_path>` - Open in $EDITOR
- `templedb file checkout <project> <file_path> [-o path]` - Checkout to filesystem
- `templedb file set <project> <file_path> [--content text] [--stage]` - Write content

**String-based versions for programmatic use:**
- `get` - Returns content as string (stdout)
- `set` - Takes content from stdin or `--content` flag

### MCP Tools (`src/mcp_server.py`)

Registered MCP tools for Claude Code integration:

- `templedb_file_get` - Get file content as string
- `templedb_file_set` - Set file content with optional staging

**Usage in Claude Code:**
```
User: "Show me the main.py file from woofs_projects"
Claude: [calls templedb_file_show tool]

User: "Update config.json to set debug=true"
Claude: [calls templedb_file_get, modifies, calls templedb_file_set with stage=true]
```

### Emacs Integration (`integrations/emacs/templedb-magit.el`)

Magit-like interface with key bindings:

| Key | Command | Description |
|-----|---------|-------------|
| `RET` / `e` | `templedb-magit-edit-file` | Edit file at point |
| `v` | `templedb-magit-show-file` | View in read-only buffer |
| `s` | `templedb-magit-stage-file` | Stage file |
| `u` | `templedb-magit-unstage-file` | Unstage file |
| `c` | `templedb-magit-commit` | Commit staged changes |
| `g` | `templedb-magit-refresh` | Refresh status |
| `q` | `quit-window` | Close buffer |

**Status Buffer Example:**
```
TempleDB Status: woofs_projects

Staged changes (2)
  src/main.py
  src/config.py

Modified (1)
  README.md

Untracked (1)
  temp.txt
```

## Architecture

```
┌─────────────────────────────────────────────┐
│                  User Layer                  │
│  CLI Commands  │  MCP Tools  │  Emacs UI    │
└────────┬─────────────┬───────────────┬───────┘
         │             │               │
         ├─────────────┴───────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│            TempleDB Core Services            │
│  - ProjectRepository (get project path)     │
│  - FileRepository (get file metadata)       │
│  - VCSService (staging operations)          │
└────────┬────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────┐
│              Filesystem Layer                │
│  - Read file content                         │
│  - Write file content                        │
│  - Open in $EDITOR                           │
└──────────────────────────────────────────────┘
```

## Workflow Examples

### 1. Quick Bug Fix (CLI)

```bash
# Check current status
templedb vcs status woofs_projects

# Edit file
templedb file edit woofs_projects src/bug.py

# Stage and commit
templedb vcs add woofs_projects src/bug.py
templedb vcs commit woofs_projects -m "Fix bug in bug.py"
```

### 2. Scripted Config Update (CLI + set/get)

```bash
# Backup current config
templedb file get myproject config.yaml > /tmp/config.backup

# Update config programmatically
cat config.yaml | sed 's/old/new/' | \
  templedb file set myproject config.yaml --stage

# Commit
templedb vcs commit myproject -m "Update config"
```

### 3. Interactive Review (Emacs)

1. `M-x templedb-magit-status`
2. Navigate to modified file
3. Press `v` to view changes
4. Press `e` to edit if needed
5. Save changes
6. Press `s` to stage
7. Press `c` to commit

### 4. AI-Assisted Editing (MCP + Claude)

```
User: "In woofs_projects, update the database URL in config.py to use PostgreSQL"

Claude:
1. Calls templedb_file_get("woofs_projects", "config.py")
2. Analyzes content, makes change
3. Calls templedb_file_set("woofs_projects", "config.py",
                            content=updated_content, stage=True)
4. Calls templedb_vcs_commit("woofs_projects", ...)
```

## Benefits

1. **Unified Interface** - Same operations available in CLI, MCP, and Emacs
2. **Programmatic Access** - `get`/`set` enable scripting and automation
3. **Editor Integration** - Works with any $EDITOR or Emacs
4. **MCP Integration** - AI assistants can read/write files directly
5. **Staging Support** - `--stage` flag auto-stages after write
6. **Type Safety** - All operations work through TempleDB's VCS layer

## Future Enhancements

- [ ] File history browsing in Emacs
- [ ] Diff preview before set
- [ ] Batch operations (`set` multiple files)
- [ ] Transaction support (set multiple files atomically)
- [ ] File templates
- [ ] Auto-formatting on set
- [ ] Conflict resolution UI
- [ ] Remote file editing (via SSH)

## Related Documentation

- [FILE_COMMANDS.md](FILE_COMMANDS.md) - Detailed CLI usage
- [README-MAGIT.md](../integrations/emacs/README-MAGIT.md) - Emacs integration
- [MCP_INTEGRATION.md](MCP_INTEGRATION.md) - Model Context Protocol details

## Credits

Inspired by:
- Magit (Emacs Git interface)
- `git checkout` workflow
- Claude Code's file operations
