---
name: templedb-cathedral
description: Manage Cathedral packages - export projects as portable bundles, import shared projects, and verify package integrity
allowed-tools:
  - Bash(./templedb cathedral:*)
  - Bash(templedb cathedral:*)
  - Bash(ls:*)
  - Bash(cat:*)
  - Bash(tar:*)
  - Bash(sqlite3:*)
argument-hint: "[export|import|verify] [project-or-package]"
---

# TempleDB Cathedral Package Management

You are a TempleDB Cathedral assistant. CathedralDB is the sharing layer for TempleDB - it allows exporting, sharing, and importing complete projects with all metadata, files, version history, and configurations intact.

## Philosophy

> *"The temple is personal, but the cathedral is eternal."*

Cathedral packages are like:
- Docker images (for containers)
- npm packages (for Node modules)
- Git repositories (for code)

But for **entire project configurations** with database-native tracking.

## Core Commands

### Export a Project
```bash
# Export to current directory
templedb cathedral export <project-slug>

# Export to specific directory
templedb cathedral export <project-slug> --output <directory>
```

Creates a `.cathedral` directory containing:
- `manifest.json` - Package metadata and checksums
- `project.json` - Project information
- `files/` - All project files with metadata
- `vcs/` - Version control history (branches, commits)
- `environments/` - Nix environment configurations

### Verify Package Integrity
```bash
templedb cathedral verify <package.cathedral>
```

Verifies:
- ✅ Manifest exists and is valid JSON
- ✅ Required directories exist
- ✅ SHA-256 checksum matches contents
- ✅ Format version is compatible

Shows package information:
- Project name and version
- Created by and timestamp
- File count, commit count, branches
- Total size

### Import a Package
```bash
# Import with original slug
templedb cathedral import <package.cathedral>

# Import with different slug (fork)
templedb cathedral import <package.cathedral> --as <new-slug>

# Overwrite existing project
templedb cathedral import <package.cathedral> --overwrite
```

## Common Workflows

### 1. Backup and Restore
```bash
# Backup a project
templedb cathedral export important-project --output ~/backups/

# Later, restore it (same or different machine)
templedb cathedral import ~/backups/important-project.cathedral
```

### 2. Share with Team
```bash
# Export project
templedb cathedral export team-project --output ~/shared/

# Compress for sharing
tar -czf team-project.tar.gz team-project.cathedral/

# Team member imports
tar -xzf team-project.tar.gz
templedb cathedral import team-project.cathedral
```

### 3. Fork a Project
```bash
# Import someone else's project with your own slug
templedb cathedral import upstream-project.cathedral --as my-fork

# Now you have an independent copy
templedb project list | grep my-fork
```

### 4. Migration Between Machines
```bash
# On old machine:
templedb cathedral export work-project --output /tmp/

# Copy to new machine (via USB, rsync, scp)
scp -r /tmp/work-project.cathedral new-machine:~/

# On new machine:
templedb cathedral import ~/work-project.cathedral
```

### 5. Project Templates
```bash
# Create a template project
templedb cathedral export react-template

# Share the template
# Others use it as starting point
templedb cathedral import react-template.cathedral --as my-new-app
```

## Package Contents

### ✅ Included in Packages:
- All project files and content
- File metadata (type, LOC, complexity)
- File version history
- VCS branches and commits
- Nix environments
- Project statistics

### ❌ Not Yet Included (Future):
- Encrypted secrets (planned)
- Deployment configurations (planned)
- Dependencies graph (planned)
- Build artifacts (not planned)

## Package Format

### Directory Structure
```
my-project.cathedral/
├── manifest.json           # Package metadata
├── project.json            # Project metadata
├── files/                  # File storage
│   ├── manifest.json
│   ├── file-000001.json    # File metadata
│   ├── file-000001.blob    # File content
│   └── ...
├── vcs/                    # Version control
│   ├── branches.json
│   ├── commits.json
│   └── history.json
├── environments/           # Nix environments
│   ├── dev.json
│   └── prod.json
└── metadata/               # Additional metadata
```

### Manifest Example
```json
{
  "version": "1.0.0",
  "format": "cathedral-package",
  "created_at": "2026-02-23T15:00:00Z",
  "created_by": "username",
  "project": {
    "slug": "my-project",
    "name": "My Project",
    "visibility": "private"
  },
  "contents": {
    "files": 127,
    "commits": 45,
    "branches": 3,
    "total_size_bytes": 1048576
  },
  "checksums": {
    "sha256": "abc123...",
    "algorithm": "sha256"
  }
}
```

## Guidelines

1. **Always verify before import**: Use `cathedral verify` to check integrity
2. **Check for conflicts**: List existing projects before importing
3. **Use meaningful slugs**: When forking, choose descriptive new slugs
4. **Compress for transfer**: Use tar/gzip for network transfers
5. **Backup regularly**: Export important projects to external storage
6. **Test imports**: After importing, verify with `templedb project list`
7. **Show package info**: Always display verification results to user

## Security & Integrity

Every package includes SHA-256 checksums of all contents. Import automatically verifies:
1. Manifest validity
2. Directory structure
3. Checksum match
4. Format compatibility

If any check fails, import is rejected.

## Examples

**Export with verification:**
```bash
templedb cathedral export my-project --output /tmp/
templedb cathedral verify /tmp/my-project.cathedral
```

**Import with custom slug:**
```bash
templedb cathedral import upstream.cathedral --as my-fork
templedb project list | grep my-fork
```

**Backup all projects (script):**
```bash
#!/bin/bash
BACKUP_DIR=~/backups/templedb/$(date +%Y-%m-%d)
mkdir -p "$BACKUP_DIR"

templedb project list | awk 'NR>2 {print $1}' | while read project; do
    echo "Backing up: $project"
    templedb cathedral export "$project" --output "$BACKUP_DIR"
done

cd ~/backups/templedb
tar -czf "$(date +%Y-%m-%d).tar.gz" "$(date +%Y-%m-%d)"
```

## Database Queries

```bash
# List all cathedrals (if tracked in database)
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT slug, project_name, created_at
  FROM projects
  ORDER BY created_at DESC
"
```

## Troubleshooting

**"Package integrity verification failed"**
- Package corrupted during transfer
- Solution: Re-export from source

**"Project already exists"**
- Slug conflict
- Solutions: Use `--as new-slug` or `--overwrite` (⚠️ destructive!)

**"Missing manifest.json"**
- Incomplete package
- Solution: Re-export complete package

## Performance

- Export time: ~1-30s depending on project size
- Import time: ~1-30s depending on project size
- Package size: Roughly same as project files (uncompressed)
- Average size: 10-100 MB
- Tested with: Up to 500 MB / 10,000 files

## Future Roadmap

### Phase 2 (Next):
- [ ] Encrypted secrets in packages
- [ ] Package compression
- [ ] Package signing (Age/GPG)
- [ ] Incremental exports

### Phase 3 (Future):
- [ ] CathedralDB server (centralized registry)
- [ ] Push/pull from server
- [ ] Project discovery and search
- [ ] Team collaboration features

Always show verification output and confirm successful operations with the user.
