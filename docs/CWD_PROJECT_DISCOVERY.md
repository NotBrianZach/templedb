# CWD-Based Project Discovery

TempleDB now supports git-like current working directory (CWD) based project discovery using `.templedb/` markers.

## Overview

Instead of storing absolute filesystem paths in the database, projects are discovered by walking up the directory tree from your current working directory to find a `.templedb/` marker - just like git looks for `.git/`.

**Benefits:**
- **Portable projects**: Move or clone projects anywhere without updating the database
- **Multiple checkouts**: Same project in different locations work independently
- **Cathedral-friendly**: Exported projects work immediately after extraction
- **Intuitive**: Works like git - just `cd` into project and run commands
- **No registry sync issues**: No configuration to get stale or break

## Quick Start

### Initialize a New Project

```bash
cd ~/myproject
templedb project init
```

This creates a `.templedb/` marker in your project root containing:
- Project slug and database ID
- Configuration metadata

### Work with the Project

Commands automatically discover the project from your CWD:

```bash
cd ~/myproject

# Works from project root
templedb project sync

# Works from any subdirectory
cd src/components
templedb project sync    # Still finds the project root
```

### Run Commands from Anywhere

Use the `-C` flag (like git):

```bash
templedb -C ~/myproject project sync
templedb -C ~/myproject/src project sync  # Also works
```

## How It Works

### Project Marker Structure

```
myproject/
├── .templedb/
│   └── config          # JSON config file
├── src/
│   └── main.py
└── README.md
```

**`.templedb/config` format:**
```json
{
  "slug": "myproject",
  "project_id": 42,
  "version": "1.0"
}
```

### Discovery Algorithm

1. Start from current working directory
2. Check if `.templedb/` directory exists
3. If found, load config and use as project root
4. If not found, move up one directory and repeat
5. Stop at filesystem root

### File Path Storage

Files are stored with **project-relative paths**:

```
Database:           Filesystem:
-----------------   --------------------------
README.md           /home/user/myproject/README.md
src/main.py         /home/user/myproject/src/main.py
```

When you move the project, the paths remain valid because they're relative to the project root marker.

## Commands

### `project init`

Initialize current directory as a TempleDB project:

```bash
cd ~/myproject
templedb project init [--slug SLUG] [--name NAME]
```

**Options:**
- `--slug`: Project slug (default: directory name)
- `--name`: Project display name (default: slug)

**Creates:**
- `.templedb/config` marker file
- Project entry in database

### `project sync`

Scan and import files from project:

```bash
# From anywhere in project tree
templedb project sync

# Or specify project explicitly (legacy)
templedb project sync PROJECT_SLUG

# Or use -C flag
templedb -C ~/myproject project sync
```

### `project import`

Import an existing project (legacy command, creates marker automatically):

```bash
templedb project import /path/to/project [--slug SLUG]
```

This now automatically creates a `.templedb/` marker for future CWD-based access.

## Backward Compatibility

### Legacy Projects

Projects created before CWD support still work:
- `repo_url` field is still stored and used as fallback
- Running `project sync` or `project import` on legacy projects automatically adds `.templedb/` marker
- No breaking changes to existing workflows

### Migration Path

To upgrade legacy projects to CWD-based discovery:

```bash
# Option 1: Re-sync (adds marker automatically)
templedb project sync legacy-project

# Option 2: Import again (idempotent, adds marker)
templedb project import /path/to/legacy-project --slug legacy-project
```

After upgrade, you can use CWD-based commands.

## Use Cases

### 1. Multiple Checkouts

Work on same project in different locations:

```bash
# Checkout 1: feature branch
cd ~/work/myproject-feature
templedb project init --slug myproject-feature
templedb project sync

# Checkout 2: bugfix branch
cd ~/work/myproject-bugfix
templedb project init --slug myproject-bugfix
templedb project sync
```

Each checkout has its own `.templedb/` marker with different project ID.

### 2. Cathedral Packages

Export and import portable project bundles:

```bash
# Export project with cathedral
templedb cathedral export myproject

# Move to another machine, extract
tar -xzf myproject.cathedral.tar.gz
cd myproject

# Works immediately - marker is included
templedb project sync
```

### 3. Nested Projects

Parent and child projects:

```bash
myproject/               # Parent project
├── .templedb/
├── frontend/
│   ├── .templedb/      # Child project
│   └── src/
└── backend/
    ├── .templedb/      # Child project
    └── src/
```

Commands discover the **nearest** `.templedb/` marker walking up from CWD.

## Implementation Details

### Core Module

`src/project_context.py` provides:

```python
from project_context import ProjectContext, get_project_context

# Discover project from CWD
ctx = ProjectContext.discover()
if ctx:
    print(f"Project: {ctx.slug}")
    print(f"Root: {ctx.root}")

# Or require project (exit if not found)
ctx = ProjectContext.discover_or_exit()

# Convenience function
ctx = get_project_context(required=True)
```

### CLI Integration

`-C` flag changes directory before command execution:

```python
# In src/cli/core.py
if args.project_dir:
    os.chdir(args.project_dir)
    # Then execute command
```

### Path Resolution

```python
# Convert absolute to relative
rel_path = ctx.relativize_path(Path('/home/user/myproject/src/main.py'))
# Result: 'src/main.py'

# Convert relative to absolute
abs_path = ctx.resolve_path('src/main.py')
# Result: PosixPath('/home/user/myproject/src/main.py')
```

## Comparison with Other Approaches

### CWD vs Workspace Registry

| Feature | CWD (TempleDB) | Registry |
|---------|----------------|----------|
| Configuration | Zero - automatic | Must register projects |
| Portability | Perfect - works anywhere | Breaks when moved |
| Multi-checkout | Native support | Conflicts |
| Sync issues | Never | Constantly |
| Cathedral support | Excellent | Poor |

### CWD vs Absolute Paths

| Feature | CWD | Absolute |
|---------|-----|----------|
| Portability | ✅ Full | ❌ None |
| Cathedral | ✅ Works | ❌ Breaks |
| Flexibility | ✅ High | ❌ Low |
| Simplicity | ✅ Simple | ✅ Simple |

## Troubleshooting

### "not in a templedb project"

You're not in a project directory. Either:

```bash
cd /path/to/project      # Move to project
templedb -C /path/to/project project sync  # Or use -C
templedb project init    # Or initialize current directory
```

### Project Not Discovered from Subdirectory

Check that `.templedb/` exists at project root:

```bash
cd ~/myproject
ls -la .templedb/
cat .templedb/config
```

If missing, re-initialize:

```bash
templedb project init --slug myproject
```

### Wrong Project Discovered (Nested Projects)

TempleDB finds the **nearest** `.templedb/` walking up. If you have nested projects, make sure you're in the right subdirectory.

```bash
# See which project would be discovered
python3 -c "
from project_context import ProjectContext
ctx = ProjectContext.discover()
print(f'Would discover: {ctx.slug if ctx else None}')
print(f'Root: {ctx.root if ctx else None}')
"
```

## Future Enhancements

Potential additions:

1. **Project aliases**: Map short names to frequently-used projects
2. **Workspace scanning**: Auto-discover all projects under a directory
3. **Project templates**: Initialize with starter files and config
4. **Monorepo support**: Better handling of nested projects
5. **Remote projects**: Discover projects via network/cloud storage

## See Also

- [Cathedral Format](./CATHEDRAL_FORMAT.md) - Portable project bundles
- [Project Management](./PROJECT_MANAGEMENT.md) - Full command reference
- [File Tracking](./FILE_TRACKING.md) - How files are stored and versioned
