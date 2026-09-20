---
name: templedb-environments
description: Manage Nix development environments for TempleDB projects - detect dependencies, create environments, and enter reproducible shells
allowed-tools:
  - Bash(./templedb env:*)
  - Bash(templedb env:*)
  - Bash(sqlite3:*)
argument-hint: "[list|enter|detect|new|generate] [project] [env-name]"
---

# TempleDB Environment Management

You are a TempleDB environment management assistant. TempleDB integrates with Nix to provide reproducible, project-specific development environments.

## Core Commands

### List Environments
```bash
# List all environments for all projects
templedb env list

# List environments for a specific project
templedb env list <project-slug>
```

### Enter a Nix Environment
```bash
# Enter the default environment for a project
templedb env enter <project-slug>

# Enter a specific named environment
templedb env enter <project-slug> <env-name>
```

This drops you into a Nix FHS (Filesystem Hierarchy Standard) shell with all dependencies available.

### Detect Dependencies
```bash
templedb env detect <project-slug>
```

Auto-detects project dependencies by analyzing:
- `package.json` (Node.js projects)
- `requirements.txt`, `pyproject.toml` (Python projects)
- `Cargo.toml` (Rust projects)
- `go.mod` (Go projects)
- Other language-specific files

Suggests appropriate Nix packages to include.

### Create New Environment
```bash
templedb env new <project-slug> <env-name>
```

Interactively creates a new environment:
1. Prompts for packages to include
2. Allows customization of shell hooks
3. Saves configuration to database
4. Generates Nix expression

### Generate Nix Expression
```bash
templedb env generate <project-slug> <env-name>
```

Generates a Nix shell expression from the stored environment configuration. Useful for:
- Exporting environments to `shell.nix` files
- Reviewing generated Nix code
- Creating standalone Nix configurations

## Workflow Examples

### Complete Setup for New Project

```bash
# 1. Import project
templedb project import /path/to/project my-project

# 2. Auto-detect dependencies
templedb env detect my-project

# 3. Create development environment
templedb env new my-project dev

# 4. Enter environment
templedb env enter my-project dev

# 5. Verify environment
which node npm python3  # Or whatever tools you need
```

### Multiple Environments per Project

```bash
# Create development environment (with debugging tools)
templedb env new my-project dev

# Create production-like environment (minimal)
templedb env new my-project prod

# Create testing environment (with test runners)
templedb env new my-project test

# Switch between them
templedb env enter my-project dev
templedb env enter my-project prod
```

### Export Environment Configuration

```bash
# Generate Nix expression
templedb env generate my-project dev > shell.nix

# Now others can use this without TempleDB
nix-shell shell.nix
```

## Database Queries for Environments

```bash
# List all environments with details
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT
    p.slug as project,
    e.env_name,
    e.description,
    e.created_at
  FROM nix_environments e
  JOIN projects p ON e.project_id = p.id
"

# Get environment configuration
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT nix_expression
  FROM nix_environments
  WHERE project_id = (SELECT id FROM projects WHERE slug = 'my-project')
    AND env_name = 'dev'
"
```

## Key Features

1. **Reproducibility**: Same environment on any machine with Nix
2. **Isolation**: Each project has its own dependencies
3. **Version Control**: Environments stored in database, can be versioned
4. **Auto-Detection**: Smart dependency detection from project files
5. **Multiple Profiles**: Dev, prod, test environments per project
6. **Fast Boot**: < 1s environment activation (cached Nix expressions)

## Common Packages

When creating environments, common packages include:

**Node.js:**
- `nodejs`, `nodejs-18_x`, `nodejs-20_x`
- `nodePackages.npm`, `yarn`, `pnpm`

**Python:**
- `python3`, `python310`, `python311`
- `python3Packages.pip`, `python3Packages.virtualenv`

**Build Tools:**
- `gcc`, `gnumake`, `cmake`
- `pkg-config`, `autoconf`, `automake`

**Databases:**
- `postgresql`, `mysql`, `sqlite`
- `redis`, `mongodb`

**Other:**
- `git`, `jq`, `curl`, `wget`
- `docker`, `docker-compose`

## Guidelines

1. **Always list first**: See existing environments before creating new ones
2. **Use detect**: Let TempleDB auto-detect dependencies when possible
3. **Meaningful names**: Use descriptive environment names (dev, prod, test, staging)
4. **Test after creation**: Enter the environment and verify tools are available
5. **Cache awareness**: First entry may take longer (Nix building), subsequent entries are instant
6. **Export for sharing**: Generate shell.nix files for team members

## Performance Notes

- TempleDB caches Nix expressions (< 1s boot time)
- First environment creation downloads packages (may take minutes)
- Subsequent uses are nearly instant
- Nix store shared across all projects (efficient)

## Troubleshooting

**Environment not found:**
```bash
templedb env list <project>  # Verify environment exists
```

**Dependencies missing in environment:**
```bash
# Re-detect and update
templedb env detect <project>
templedb env new <project> <env-name>  # Recreate with detected packages
```

**Slow environment entry:**
- First time: Nix is building/downloading (expected)
- Subsequent times: Check Nix store disk space

Always confirm operations succeeded and show user the environment details.
