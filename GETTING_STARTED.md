# Getting Started with TempleDB

**TempleDB** is a developer-centric database for managing projects, environments, secrets, and file versioning in a single SQLite database with full version control.

## What Can TempleDB Do?

- **Project Management**: Track all your projects in one place with metadata, git history, and dependencies
- **Environment Management**: Manage Nix environments per-project with easy activation
- **File Versioning**: Track file changes with database-native VCS, query file history, and compare versions
- **Checkout/Commit Workflow**: Edit files with familiar tools, then commit changes back to the database
- **Cross-Project Analysis**: Query across all projects to find patterns, dependencies, or technical debt

## Quick Start (5 Minutes)

### 1. Install Dependencies

TempleDB needs:
- Python 3.9+
- SQLite 3.35+
- git

**Ubuntu/Debian:**
```bash
sudo apt install python3 sqlite3 git
```

**macOS:**
```bash
brew install python sqlite git
```

### 2. Install TempleDB

**Option A: Clone and run directly**
```bash
git clone https://github.com/yourusername/templedb.git
cd templedb
chmod +x templedb
./templedb --help
```

**Option B: Add to PATH**
```bash
# After cloning:
echo 'export PATH="$HOME/templedb:$PATH"' >> ~/.bashrc
source ~/.bashrc
templedb --help
```

### 3. Initialize Your First Project

```bash
# Navigate to a project directory
cd ~/projects/my-app

# Add project to TempleDB (auto-detects name, git remote, etc.)
templedb project add-from-dir .

# List all projects
templedb project ls
```

### 4. Explore Your Database

```bash
# Open the database directly
sqlite3 ~/.local/share/templedb/templedb.sqlite

# Try some queries:
SELECT slug, name, repo_url FROM projects;
SELECT * FROM vcs_commits LIMIT 10;
SELECT file_path, size FROM files WHERE project_slug = 'my-app';
```

## Next Steps

- **[QUICKSTART.md](QUICKSTART.md)** - Detailed usage guide and workflows
- **[CATHEDRAL.md](CATHEDRAL.md)** - Export/import projects for sharing
- **[SECURITY.md](SECURITY.md)** - Security best practices
- **[VCS_INTEGRATION.md](VCS_INTEGRATION.md)** - File versioning and git integration

## Installation Options

### Option 1: Standalone Script (Recommended for trying it out)

No installation needed - just clone and run:
```bash
git clone https://github.com/yourusername/templedb.git
cd templedb
./templedb --help
```

### Option 2: NixOS Integration

If you're using NixOS with a flake-based config:

```nix
# In your flake.nix
{
  inputs.templedb.url = "github:yourusername/templedb";

  # In your NixOS configuration:
  environment.systemPackages = [
    inputs.templedb.packages.${system}.default
  ];
}
```

Then rebuild:
```bash
sudo nixos-rebuild switch --flake .#hostname
```

### Option 3: Nix (Non-NixOS)

```bash
nix profile install github:yourusername/templedb
```

### Option 4: From Source (Development)

```bash
git clone https://github.com/yourusername/templedb.git
cd templedb

# Install Python dependencies (if any)
pip install -r requirements.txt  # Currently none!

# Run directly
python3 src/main.py --help

# Or use the wrapper
./templedb --help
```

## Common First-Time Questions

**Q: Do I need NixOS?**
A: No! TempleDB works on any Linux/macOS system with Python 3.9+.

**Q: Do I need Emacs?**
A: No! Emacs integration is optional. The CLI works standalone.

**Q: Where is the database stored?**
A: `~/.local/share/templedb/templedb.sqlite` (standard XDG location)

**Q: Can I use my existing projects?**
A: Yes! Use `templedb project add-from-dir .` in any git repository.

**Q: How do I back up my data?**
A: Just copy the SQLite file: `cp ~/.local/share/templedb/templedb.sqlite ~/backups/`

**Q: Is this production-ready?**
A: TempleDB v0.0.1 is in active development. Use for personal projects, not production infrastructure yet.

**Q: What's the checkout/commit workflow?**
A: Extract files from the database to a temporary directory, edit with any tool, then commit changes back. See README.md for details.

## Troubleshooting

### "templedb: command not found"

Either:
1. Run with full path: `/path/to/templedb/templedb --help`
2. Add to PATH: `export PATH="/path/to/templedb:$PATH"`
3. Create symlink: `ln -s /path/to/templedb/templedb ~/bin/templedb`

### "Database is locked"

Another process might be using the database. Check:
```bash
lsof ~/.local/share/templedb/templedb.sqlite
```

Or just wait a moment and try again.

## Community & Support

- **Issues**: https://github.com/yourusername/templedb/issues
- **Discussions**: https://github.com/yourusername/templedb/discussions
- **Documentation**: See the `docs/` directory

## Quick Reference

```bash
# Projects
templedb project import /path/to/project
templedb project list
templedb project show my-app

# Checkout/Commit Workflow
templedb project checkout my-app /tmp/workspace
# ... edit files in /tmp/workspace ...
templedb project commit my-app /tmp/workspace -m "Changes"

# Environments
templedb env list
templedb env enter my-app

# Version Control
templedb vcs status my-app
templedb vcs log my-app
templedb vcs commit -m "message" -p my-app

# Querying
sqlite3 ~/.local/share/templedb/templedb.sqlite
```
