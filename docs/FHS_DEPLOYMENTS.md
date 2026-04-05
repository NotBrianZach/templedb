# FHS-Style Deployments in TempleDB

**Version:** 1.0
**Date:** 2026-03-16
**Status:** ✅ Production Ready

## Overview

TempleDB now supports **FHS-style deployments** as an alternative to deploying projects into `/tmp`. This provides cleaner, more organized deployment management with optional Nix FHS environment integration.

## What Changed

### Before (Traditional `/tmp` Deployments)

```
/tmp/
├── templedb_deploy_project1/
├── templedb_deploy_project2/
└── templedb_deploy_project3/
```

**Problems:**
- `/tmp` gets cluttered with deployment directories
- Can be cleaned up automatically by system
- No clear organization or isolation
- Mixed with other temporary files

### After (FHS-Style Deployments)

```
~/.local/share/templedb/fhs-deployments/
├── project1/
│   ├── working/          # Reconstructed project files
│   ├── project1.cathedral/
│   └── env-info.json
├── project2/
│   └── working/
└── project3/
    └── working/
```

**Benefits:**
- ✅ Clean, organized directory structure
- ✅ Persistent across reboots (not in `/tmp`)
- ✅ Clear separation by project
- ✅ Ready for Nix FHS integration
- ✅ Easy to locate and manage deployments

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `TEMPLEDB_DEPLOYMENT_USE_FHS` | `true` | Enable FHS-style deployments |
| `TEMPLEDB_DEPLOYMENT_FHS_DIR` | `~/.local/share/templedb/fhs-deployments` | FHS deployment directory |
| `TEMPLEDB_DEPLOYMENT_FALLBACK_DIR` | `/tmp` | Fallback directory (when FHS disabled) |

### Enabling/Disabling FHS Deployments

```bash
# Use FHS-style deployments (default)
export TEMPLEDB_DEPLOYMENT_USE_FHS=true
./templedb deploy run my-project

# Use traditional /tmp deployments
export TEMPLEDB_DEPLOYMENT_USE_FHS=false
./templedb deploy run my-project

# Custom FHS directory
export TEMPLEDB_DEPLOYMENT_FHS_DIR=/data/templedb-deployments
./templedb deploy run my-project
```

## Usage

### Deploying Projects

FHS-style deployments work exactly the same as before:

```bash
# Deploy project (uses FHS by default)
./templedb deploy run my-project

# Deployment locations:
#   FHS: ~/.local/share/templedb/fhs-deployments/my-project/working
#   /tmp: /tmp/templedb_deploy_my-project/working
```

### Listing Deployed Projects

```bash
./templedb deploy list
```

Output shows deployment location:

```
📦 Deployed Projects (3):

  ✓ my-project [FHS]
     Path: /home/user/.local/share/templedb/fhs-deployments/my-project/working
     Updated: 5 minutes ago

  ✓ old-project [/tmp]
     Path: /tmp/templedb_deploy_old-project/working
     Updated: 2 days ago

💡 Tips:
   Jump to project:  cd $(./templedb deploy path my-project)
   FHS deployments:  /home/user/.local/share/templedb/fhs-deployments
```

### Getting Deployment Path

```bash
# Get deployment path (checks FHS first, then /tmp)
./templedb deploy path my-project

# Use in cd command
cd $(./templedb deploy path my-project)

# Or with tdb alias
cd $(tdb deploy path my-project)
```

## Directory Structure

### FHS Deployment Directory

```
~/.local/share/templedb/fhs-deployments/
└── <project-slug>/
    ├── <project-slug>.cathedral/    # Exported cathedral package
    │   ├── metadata.json
    │   ├── files/
    │   └── commits/
    ├── working/                     # Reconstructed project files
    │   ├── .envrc                  # Direnv integration
    │   ├── <project files>
    │   └── ...
    └── env-info.json               # FHS environment metadata (optional)
```

### Environment Info File

`env-info.json` (optional, for full Nix FHS integration):

```json
{
  "project_slug": "my-project",
  "packages": [
    "nodejs",
    "python3",
    "postgresql"
  ],
  "env_vars": {
    "NODE_ENV": "production"
  },
  "work_dir": "/home/user/.local/share/templedb/fhs-deployments/my-project/working",
  "created_at": "2026-03-16T10:30:00"
}
```

## Nix FHS Environment Integration

### Full FHS Environment (Advanced)

For full Nix FHS isolation, use the `FHSDeploymentManager`:

```python
from fhs_deployment import FHSDeploymentManager

# Create FHS environment
manager = FHSDeploymentManager()
fhs_env = manager.create_fhs_env(
    project_slug="my-project",
    packages=["nodejs", "python3", "postgresql"],
    env_vars={"NODE_ENV": "production"}
)

# Run command in FHS environment
result = manager.run_in_fhs(
    "my-project",
    ["npm", "run", "build"]
)

# Enter FHS shell
manager.enter_fhs_env(fhs_env, ["bash"])
```

### FHS Environment Features

- **Isolated filesystem** - Complete FHS hierarchy in Nix
- **Package availability** - All specified packages available
- **Environment variables** - Custom env vars automatically set
- **Working directory** - Starts in project workspace
- **No system pollution** - Completely isolated from host system

## Migration Guide

### Existing Deployments

Existing deployments in `/tmp` continue to work:

1. **Backward compatible** - Both `/tmp` and FHS locations are checked
2. **Automatic detection** - `deploy path` checks both locations
3. **Gradual migration** - New deployments use FHS, old ones remain
4. **No data loss** - Old deployments still accessible

### Cleaning Up Old Deployments

```bash
# List all deployments (shows location)
./templedb deploy list

# Old /tmp deployments can be safely removed
rm -rf /tmp/templedb_deploy_*

# FHS deployments persist and can be managed
ls ~/.local/share/templedb/fhs-deployments/
```

## Troubleshooting

### FHS Directory Not Created

**Problem:** FHS directory doesn't exist

**Solution:**
```bash
# Check configuration
cd src && python3 -c "from config import DEPLOYMENT_FHS_DIR; print(DEPLOYMENT_FHS_DIR)"

# Create manually if needed
mkdir -p ~/.local/share/templedb/fhs-deployments
```

### Can't Find Deployed Project

**Problem:** `deploy path` can't find project

**Solution:**
```bash
# List all deployments
./templedb deploy list

# Check both locations
ls -la ~/.local/share/templedb/fhs-deployments/
ls -la /tmp/templedb_deploy_*

# Redeploy if needed
./templedb deploy run my-project
```

### Want to Use /tmp Again

**Problem:** Prefer traditional `/tmp` deployments

**Solution:**
```bash
# Disable FHS in environment
export TEMPLEDB_DEPLOYMENT_USE_FHS=false

# Or add to ~/.bashrc or ~/.zshrc
echo 'export TEMPLEDB_DEPLOYMENT_USE_FHS=false' >> ~/.bashrc
```

## Performance Considerations

### FHS vs /tmp

| Aspect | FHS | /tmp |
|--------|-----|------|
| **Speed** | Same | Same |
| **Persistence** | ✅ Persists across reboots | ❌ May be cleared |
| **Organization** | ✅ Clean structure | ❌ Mixed with other files |
| **Disk space** | User home directory | Tmpfs (RAM) or disk |
| **Cleanup** | Manual | Automatic (system) |

### Disk Space

FHS deployments use your home directory, so ensure adequate space:

```bash
# Check disk space
df -h ~/.local/share/templedb

# Each deployment typically uses 10MB - 100MB depending on project size
du -sh ~/.local/share/templedb/fhs-deployments/*
```

## Future Enhancements

**Planned features:**

1. **Full Nix FHS integration** - Automatic FHS environment wrapping
2. **Deployment cleanup** - `./templedb deploy clean <project>` command
3. **FHS environment caching** - Reuse Nix FHS environments
4. **Custom package lists** - Per-project FHS package configuration
5. **Environment profiles** - Save/load FHS environment configurations

## Examples

### Basic Deployment

```bash
# Deploy with FHS (default)
./templedb deploy run my-project --target production

# Result:
#   Created: ~/.local/share/templedb/fhs-deployments/my-project/
#   Working: ~/.local/share/templedb/fhs-deployments/my-project/working/
```

### Jump to Deployment

```bash
# Navigate to deployed project
cd $(./templedb deploy path my-project)

# Or create alias
alias cdtdb='cd $(tdb deploy path $1)'
cdtdb my-project
```

### Custom FHS Directory

```bash
# Use custom location
export TEMPLEDB_DEPLOYMENT_FHS_DIR=/data/deployments
./templedb deploy run my-project

# Result: /data/deployments/my-project/
```

### Disable FHS Temporarily

```bash
# Single deployment to /tmp
TEMPLEDB_DEPLOYMENT_USE_FHS=false ./templedb deploy run my-project

# Result: /tmp/templedb_deploy_my-project/
```

## Best Practices

1. **Use FHS for production** - Better organization and persistence
2. **Use /tmp for testing** - Quick cleanup and ephemeral
3. **Set FHS directory** - Choose location with adequate space
4. **Clean old deployments** - Manually remove unused FHS deployments
5. **Monitor disk usage** - Check FHS directory size regularly

## Comparison with Other Systems

### TempleDB FHS vs Docker

| Feature | TempleDB FHS | Docker |
|---------|-------------|--------|
| Isolation | Nix FHS | Containers |
| Overhead | Low | Medium |
| Complexity | Low | High |
| Integration | Native TempleDB | Separate system |

### TempleDB FHS vs Nix Shells

| Feature | TempleDB FHS | Nix Shell |
|---------|-------------|-----------|
| Persistence | File-based | Declarative |
| Management | TempleDB CLI | Nix commands |
| Integration | Built-in | Manual |

## References

- [Filesystem Hierarchy Standard](https://en.wikipedia.org/wiki/Filesystem_Hierarchy_Standard)
- [Nix buildFHSUserEnv](https://nixos.org/manual/nixpkgs/stable/#sec-fhs-environments)
- [TempleDB Deployment Docs](DEPLOYMENT.md)
- [TempleDB Configuration](SYSTEM_CONFIG_REFERENCE.md)

---

**Status:** ✅ Enabled by default
**Configuration:** Environment variables
**Migration:** Automatic and backward compatible
**Cleanup:** Manual (FHS) or automatic (/tmp)


<!-- AUTO-GENERATED-INDEX:START -->
## Related Documentation

### Other

- **[Nix Packaging for CLI Tools](../docs/NIX_CLI_TOOL_PACKAGING.md)**
- **[Full Nix FHS Integration in TempleDB](../docs/FULL_FHS_INTEGRATION.md)**

### Architecture

- **[CathedralDB Design Document](../docs/advanced/CATHEDRAL.md)**

### Deployment

- **[Phase 3: Steam Game Deployment (IMPLEMENTED)](../docs/PHASE_3_STEAM_DEPLOYMENT.md)**
- **[Game Engine Deployment Guide](../docs/GAME_ENGINE_DEPLOYMENT.md)**
- **[FHS First-Class Integration - Vision](../docs/FHS_FIRST_CLASS_VISION.md)**
- **[TempleDB Deployment Architecture Review (v2)](../docs/DEPLOYMENT_ARCHITECTURE_V2.md)**
- **[TempleDB Deployment Architecture Review](../docs/DEPLOYMENT_ARCHITECTURE.md)**

<!-- AUTO-GENERATED-INDEX:END -->
