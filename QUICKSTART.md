# TempleDB Quick Start

> **New to TempleDB?** Start with [GETTING_STARTED.md](GETTING_STARTED.md) for a beginner-friendly introduction.

This guide covers workflows and advanced usage for users who already have TempleDB installed.

## Installation

### For NixOS Users

1. **Rebuild NixOS configuration:**
   ```bash
   cd /home/user/projects/my-config
   sudo nixos-rebuild switch --flake .#hostname
   ```

2. **Verify installation:**
   ```bash
   which templedb
   templedb --help
   ```

### For Non-NixOS Users

See [GETTING_STARTED.md](GETTING_STARTED.md) for installation instructions.

## Core Concepts

TempleDB uses a **checkout/commit workflow**:

1. **Database is source of truth** - All files stored in SQLite with full version history
2. **Checkout to edit** - Extract files to filesystem temporarily
3. **Commit to save** - Atomic commits back to database
4. **Query with SQL** - Search and analyze across all projects

This enables:
- Zero file duplication (content-addressed storage)
- Multi-agent coordination (ACID transactions)
- Cross-project queries
- Version control without git commands

## Basic Workflow

### 1. Import a Project

```bash
# Import from existing git repository
cd ~/projects/my-app
templedb project import .

# Or specify path explicitly
templedb project import /path/to/project

# List all projects
templedb project list
```

### 2. Edit Files (Checkout/Commit)

```bash
# Checkout project to temporary workspace
templedb project checkout my-app /tmp/workspace

# Edit files with any tool
cd /tmp/workspace
vim src/main.py
grep -r "TODO" .
npm test

# Commit changes back to database
templedb project commit my-app /tmp/workspace -m "Fixed bug in authentication"

# Cleanup (workspace can be deleted)
rm -rf /tmp/workspace
```

### 3. Version Control

```bash
# View commit history
templedb vcs log my-app

# Show working directory status
templedb vcs status my-app

# Create a commit without checkout/commit workflow
templedb vcs commit -m "Update docs" -p my-app -a "Your Name"

# Branch management
templedb vcs branch my-app              # List branches
templedb vcs branch my-app feature-x    # Create branch
```

### 4. Query Your Projects

```bash
# Open database directly
sqlite3 ~/.local/share/templedb/templedb.sqlite

# Find all Python files across projects
SELECT project_slug, file_path, lines_of_code
FROM files_with_types_view
WHERE type_name = 'python';

# View recent commits
SELECT * FROM vcs_commit_history_view
ORDER BY created_at DESC LIMIT 10;

# Get project statistics
SELECT slug,
  (SELECT COUNT(*) FROM project_files WHERE project_id = p.id) as files
FROM projects p;
```

## Common Workflows

### New Project Workflow

```bash
# 1. Navigate to your project
cd ~/projects/new-app

# 2. Import into TempleDB
templedb project import .

# 3. View in database
templedb project show new-app

# 4. Make changes using checkout/commit
templedb project checkout new-app /tmp/work
# ... edit files ...
templedb project commit new-app /tmp/work -m "Initial setup"
```

### Re-sync Project from Filesystem

If you edit files outside the checkout/commit workflow:

```bash
# Re-import from filesystem to update database
templedb project sync my-app

# Or specify path
templedb project sync my-app /path/to/project
```

### Multiple Checkouts

```bash
# List active checkouts
templedb project checkout-list

# List checkouts for specific project
templedb project checkout-list my-app

# Cleanup stale checkouts (if workspace was deleted)
templedb project checkout-cleanup my-app
```

### Environment Management

```bash
# List available Nix environments
templedb env list

# List environments for specific project
templedb env list my-app

# Enter Nix shell for project
templedb env enter my-app

# Detect dependencies and generate Nix config
templedb env detect my-app
templedb env generate my-app default
```

### Search and Query

```bash
# Search file contents
templedb search content "authentication" -p my-app

# Case-insensitive search
templedb search content "TODO" -i

# Search file names
templedb search files "test" -p my-app

# Search across all projects
templedb search content "api_key"
```

### Backup and Restore

```bash
# Backup database
templedb backup ~/backups/templedb-$(date +%Y%m%d).sqlite

# Restore from backup
templedb restore ~/backups/templedb-20240101.sqlite

# View database status
templedb status
```

## Advanced Features

### Cathedral: Share Projects

Export and import complete projects with all history:

```bash
# Export project as portable package
templedb cathedral export my-app -o my-app.cathedral

# Verify package integrity
templedb cathedral verify my-app.cathedral

# Import on another machine
templedb cathedral import my-app.cathedral
```

### Deployment Targets

```bash
# Add deployment target
templedb target add production \
  --type ssh \
  --host prod.example.com \
  --user deploy

# Deploy project
templedb deploy my-app production
```

### Database Migrations

```bash
# View migration status
templedb migration status

# Apply pending migrations
templedb migration apply

# Rollback last migration
templedb migration rollback
```

## Troubleshooting

### Command not found

```bash
# Verify installation
which templedb

# If using local checkout:
./templedb --help

# Add to PATH
export PATH="/path/to/templedb:$PATH"
```

### Database locked

Another process is using the database. Wait a moment and try again, or check:

```bash
lsof ~/.local/share/templedb/templedb.sqlite
```

### Checkout conflicts

If workspace was modified outside of TempleDB:

```bash
# List checkouts
templedb project checkout-list my-app

# Cleanup stale checkouts
templedb project checkout-cleanup my-app

# Start fresh
rm -rf /tmp/workspace
templedb project checkout my-app /tmp/workspace
```

### Import fails

Make sure you're in a git repository:

```bash
cd /path/to/project
git status  # Should show repo status

# If not a git repo, initialize:
git init
git add .
git commit -m "Initial commit"

# Then import
templedb project import .
```

## Database Location

The SQLite database is stored at:
```
~/.local/share/templedb/templedb.sqlite
```

You can query it directly:
```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite '.schema'
```

Or in Emacs: `SPC p d d`

## Next Steps

- **[README.md](README.md)** - Complete overview and philosophy
- **[GUIDE.md](GUIDE.md)** - Detailed usage guide
- **[DESIGN_PHILOSOPHY.md](DESIGN_PHILOSOPHY.md)** - Why TempleDB exists
- **[EXAMPLES.md](EXAMPLES.md)** - SQL query examples
- **[CATHEDRAL.md](CATHEDRAL.md)** - Sharing projects with teams
- **[PERFORMANCE.md](PERFORMANCE.md)** - Performance tuning
