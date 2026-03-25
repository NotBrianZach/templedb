# TempleDB 2.0 - FHS Deployments Now Default

**Date:** 2026-03-16
**Version:** 2.0.0
**Breaking Change:** Yes (but with escape hatches)

## TL;DR

🎉 **Deployments now use Nix FHS isolation by default!**

```bash
# This command now automatically:
./templedb deploy run my-project

# 1. Detects your dependencies (nodejs, python, postgres, etc.)
# 2. Creates isolated Nix FHS environment
# 3. Runs deployment in complete isolation
# 4. Gives you reproducible deployments

# Need to edit files? Use mutable mode:
./templedb deploy run my-project --mutable
```

## What Changed

### Before (v1.x)

```bash
./templedb deploy run my-project
→ Uses system packages (npm, python from your PATH)
→ Can break if you update system packages
→ Not reproducible across machines
```

### After (v2.0)

```bash
./templedb deploy run my-project
→ Auto-detects dependencies from your project
→ Creates Nix FHS environment with exact versions
→ Completely isolated from system
→ Reproducible everywhere
```

## Benefits

### ✅ Reproducibility

Same deployment works on any machine with Nix:
- No "works on my machine" problems
- CI/CD uses exact same environment
- Team members get identical setups

### ✅ Isolation

Your deployments don't depend on system packages:
- System updates won't break deployments
- Multiple Node/Python versions possible
- No global package pollution

### ✅ Automatic

Just works - no configuration needed:
- Detects nodejs from package.json
- Detects python from requirements.txt
- Detects databases from connection strings
- Detects 20+ common tools automatically

## Migration Guide

### If It Just Works

Most projects will work immediately with no changes:

```bash
# Just deploy as normal
./templedb deploy run my-project

# Output will show:
# 📦 Detected dependencies: nodejs, python3, postgresql
# 🔧 Creating FHS environment...
# ✅ Deployment complete!
```

**No action needed!**

### If You Need to Edit Files

Use mutable mode:

```bash
# Deploy in mutable mode
./templedb deploy run my-project --mutable

# Now you can edit files directly
cd $(./templedb deploy path my-project)
vim deploy.sh
./deploy.sh
```

### If FHS Doesn't Work

Temporarily disable FHS:

```bash
# Use old behavior
./templedb deploy run my-project --no-fhs

# Or use mutable mode (preferred)
./templedb deploy run my-project --mutable
```

Then file a bug report with what went wrong!

### If You Don't Have Nix

Install Nix or use mutable mode:

```bash
# Option 1: Install Nix (recommended)
curl -L https://nixos.org/nix/install | sh

# Option 2: Use mutable mode
./templedb deploy run my-project --mutable
```

## New Features

### 1. `deploy shell` - Enter FHS Environment

```bash
./templedb deploy shell my-project

# Enters isolated shell with all packages:
(fhs:my-project) $ node --version  # From Nix
(fhs:my-project) $ python --version  # From Nix
(fhs:my-project) $ exit
```

### 2. `deploy exec` - Run Commands

```bash
# Run tests in FHS environment
./templedb deploy exec my-project 'npm test'

# Check versions
./templedb deploy exec my-project 'node --version'
```

### 3. Visual FHS Indicators

```bash
./templedb deploy list

📦 Deployed Projects:

  ✓ my-project 🔧 [FHS]    # 🔧 = FHS environment available
     Shell: ./templedb deploy shell my-project
```

### 4. Automatic Package Detection

Detects from:
- `package.json` → nodejs, npm
- `requirements.txt` → python3, pip
- `Cargo.toml` → rust, cargo
- `go.mod` → go
- Database URLs → postgresql, mysql, redis
- And 15+ more patterns

## Deployment Modes

### FHS Mode (Default)

```bash
./templedb deploy run my-project
```
- ✅ Isolated
- ✅ Reproducible
- ⚠️ Requires Nix
- ⚠️ Immutable (files from Nix store)

**Use for:** Production, staging, CI/CD

### Mutable Mode (Opt-In)

```bash
./templedb deploy run my-project --mutable
```
- ✅ Can edit files
- ✅ Fast iteration
- ❌ Uses system packages
- ❌ Not reproducible

**Use for:** Development, debugging

### No-FHS Mode (Discouraged)

```bash
./templedb deploy run my-project --no-fhs
```
- ⚠️ Completely disables FHS
- ⚠️ Old behavior
- ⚠️ Not recommended

**Use for:** Emergencies only

## Compatibility

### Backward Compatibility

| Old Command | New Behavior | Notes |
|-------------|--------------|-------|
| `deploy run` | Now uses FHS | Automatic upgrade |
| `deploy list` | Shows FHS status | New indicators |
| `deploy path` | Works same | Compatible |
| New: `deploy shell` | Enter FHS | New feature |
| New: `deploy exec` | Run in FHS | New feature |

### Breaking Changes

1. **FHS Required (for default mode)**
   - Need Nix installed
   - Use `--mutable` if no Nix

2. **~500ms Overhead (first deploy)**
   - FHS environment creation
   - Subsequent deploys are fast (cached)

3. **Files Are Immutable (in FHS mode)**
   - Can't edit files directly in FHS
   - Use `--mutable` if needed

### Non-Breaking Changes

- FHS directory structure (backward compatible)
- Commands work in both modes
- Old deployments still accessible

## Configuration

### Disable FHS Globally (Not Recommended)

```bash
# Add to ~/.bashrc or ~/.zshrc
export TEMPLEDB_DEPLOYMENT_USE_FULL_FHS=false
```

### Configure FHS Directory

```bash
export TEMPLEDB_DEPLOYMENT_FHS_DIR=/data/deployments
```

### Add Extra Packages

```bash
export TEMPLEDB_FHS_EXTRA_PACKAGES="docker,kubectl,terraform"
```

## Examples

### Example 1: Node.js App

**Before:**
```bash
./templedb deploy run my-app
# Used system npm (whatever version installed)
```

**After:**
```bash
./templedb deploy run my-app

# Output:
📦 Detected dependencies: nodejs 20.x, npm 10.x
🔧 Creating FHS environment...
✅ Deployment complete!

# Uses Nix nodejs, isolated from system
```

### Example 2: Python + Postgres

**Before:**
```bash
./templedb deploy run api
# Used system python and psql
```

**After:**
```bash
./templedb deploy run api

# Output:
📦 Detected dependencies: python3 3.11, postgresql 15
🔧 Creating FHS environment...
✅ Deployment complete!
```

### Example 3: Development Workflow

**Before:**
```bash
./templedb deploy run my-app
cd /some/path
vim deploy.sh
./deploy.sh
```

**After:**
```bash
./templedb deploy run my-app --mutable
cd $(./templedb deploy path my-app)
vim deploy.sh
./deploy.sh

# Final deploy with FHS:
./templedb deploy run my-app
```

## Performance

### Overhead

| Operation | Time | Notes |
|-----------|------|-------|
| Package detection | <100ms | File scanning |
| FHS creation | ~1-2s | First time only |
| FHS entry | ~500ms | Cached |
| Deployment | Same | No overhead |

### Optimization

FHS environments are cached:
```bash
# First deploy: ~2s overhead
./templedb deploy run my-project

# Subsequent deploys: ~500ms overhead
./templedb deploy run my-project
```

## Troubleshooting

### Deploy Fails in FHS

```bash
# Check what was detected
./templedb deploy run my-app --dry-run

# Try mutable mode
./templedb deploy run my-app --mutable

# Report issue with output
```

### Missing Package

```bash
# Add manually
export TEMPLEDB_FHS_EXTRA_PACKAGES="missing-package"
./templedb deploy run my-app
```

### Can't Edit Files

```bash
# Use mutable mode
./templedb deploy run my-app --mutable
```

### Nix Not Installed

```bash
# Option 1: Install Nix
curl -L https://nixos.org/nix/install | sh

# Option 2: Use mutable mode
./templedb deploy run my-app --mutable
```

## Rollback

If you need to completely disable FHS:

```bash
# Temporary (single command)
./templedb deploy run my-app --no-fhs

# Permanent (add to shell config)
echo 'export TEMPLEDB_DEPLOYMENT_USE_FULL_FHS=false' >> ~/.bashrc
```

## Feedback

This is a major change! Please report:
- ✅ **What works** - Help us verify
- ❌ **What breaks** - We'll fix it
- 💡 **Ideas** - Make it better

File issues at: [templedb/issues](https://github.com/yourusername/templedb/issues)

## Summary

### What You Need to Know

1. **FHS is now default** - Deployments are isolated and reproducible
2. **Most projects work immediately** - No changes needed
3. **Use `--mutable` if you need to edit files** - Development/debugging
4. **Use `--no-fhs` as emergency escape** - If something breaks

### Commands Cheat Sheet

```bash
# Default (FHS isolation)
./templedb deploy run my-app

# Mutable mode (file editing)
./templedb deploy run my-app --mutable

# Disable FHS (emergency)
./templedb deploy run my-app --no-fhs

# Enter shell
./templedb deploy shell my-app

# Run command
./templedb deploy exec my-app 'npm test'

# List deployments (shows FHS status)
./templedb deploy list
```

---

**Status:** ✅ Released
**Version:** 2.0.0
**Breaking:** Yes (with escape hatches)
**Recommendation:** Try it! Use `--mutable` if needed.

Welcome to reproducible deployments! 🎉
