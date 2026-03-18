# TempleDB Deployment Modes

**Version:** 2.0
**Date:** 2026-03-16
**Status:** ✅ FHS is Now Default

## Overview

TempleDB deployments now use **FHS isolation by default**, providing reproducible, isolated deployments with automatic package detection. You can opt into **mutable mode** when you need direct file editing.

## Deployment Modes

### 1. FHS Mode (Default) ✅

**Isolated, reproducible deployment in Nix FHS environment**

```bash
./templedb deploy run my-project
```

**What happens:**
1. 📦 Auto-detects packages (nodejs, python, postgres, etc.)
2. 🔧 Creates Nix FHS environment with those packages
3. 🚀 Runs deployment in complete isolation
4. ✅ Reproducible across all machines

**Characteristics:**
- ✅ **Isolated** - No system package dependencies
- ✅ **Reproducible** - Exact same environment every time
- ✅ **Automatic** - Detects what you need
- ⚠️ **Immutable** - Files from Nix store (read-only during deploy)
- ⚠️ **Requires Nix** - Must have Nix installed

**Use when:**
- Deploying to production
- Need reproducibility
- Want isolation from system
- Standard deployment workflow

### 2. Mutable Mode (Opt-In) 🔓

**Direct file access, allows editing during deployment**

```bash
./templedb deploy run my-project --mutable
```

**What happens:**
1. 📁 Deploys to FHS directory
2. 🔓 No FHS environment wrapper
3. ✏️ Files can be edited directly
4. 🚀 Uses system packages

**Characteristics:**
- ✅ **Editable** - Can modify files directly
- ✅ **Fast iteration** - No FHS overhead
- ⚠️ **Not isolated** - Uses system packages
- ⚠️ **Not reproducible** - Depends on system state
- ❌ **Less safe** - Can break if system changes

**Use when:**
- Debugging deployments
- Quick iteration/testing
- Need to edit files directly
- Developing deployment scripts

### 3. No-FHS Mode (Discouraged) ⚠️

**Completely disable FHS (legacy behavior)**

```bash
./templedb deploy run my-project --no-fhs
```

**What happens:**
1. ⚠️ Shows warning
2. 📁 Uses system packages entirely
3. 🚨 Not recommended

**Use when:**
- FHS is broken
- Emergency situations only
- Debugging FHS issues

## Usage

### Default Deployment (FHS)

```bash
# Just deploy - FHS automatically
./templedb deploy run my-project

# Output:
🚀 Deploying my-project to production

📦 Detected dependencies:
   • nodejs 20.x
   • python3 3.11
   • postgresql 15
   • 12 more packages

🔧 Creating FHS environment...
   ✓ FHS environment ready

🏗️  Running deployment...
   ✓ npm install
   ✓ Build successful

✅ Deployment complete!

🔧 FHS environment available
   Enter shell:  ./templedb deploy shell my-project
   Run command:  ./templedb deploy exec my-project '<cmd>'
```

### Mutable Mode Deployment

```bash
# Deploy in mutable mode
./templedb deploy run my-project --mutable

# Output:
⚠️  MUTABLE MODE: Files can be edited directly
   Note: Deployment will not be isolated or reproducible

🚀 Deploying my-project to production
📁 Deployed to: ~/.templedb/fhs-deployments/my-project/working

# Now you can edit files:
cd ~/.templedb/fhs-deployments/my-project/working
vim deploy.sh  # Make changes
./deploy.sh    # Test immediately
```

### Accessing Deployed Projects

Both modes support the same access commands:

```bash
# Enter shell (FHS if available, regular shell if mutable)
./templedb deploy shell my-project

# Run command
./templedb deploy exec my-project 'npm test'

# Get path
cd $(./templedb deploy path my-project)
```

## Workflows

### Production Deployment (FHS - Default)

```bash
# 1. Deploy with FHS
./templedb deploy run my-app --target production

# 2. Test in isolated environment
./templedb deploy shell my-app
(fhs:my-app) $ npm test
(fhs:my-app) $ exit

# 3. Check logs
./templedb deploy exec my-app 'tail -f logs/app.log'
```

### Development Iteration (Mutable)

```bash
# 1. Deploy in mutable mode
./templedb deploy run my-app --mutable

# 2. Edit deployment script
cd $(./templedb deploy path my-app)
vim deploy.sh

# 3. Test immediately
./deploy.sh

# 4. Repeat until working

# 5. Final deploy with FHS
./templedb deploy run my-app
```

### Debugging (Mixed)

```bash
# 1. Deploy with FHS
./templedb deploy run my-app

# 2. Something's wrong - enter mutable shell
./templedb deploy shell my-app

# 3. Debug interactively
(fhs:my-app) $ echo "Debug info" >> deploy.sh
(fhs:my-app) $ ./deploy.sh  # Test fix

# 4. If FHS is the problem, redeploy mutable
./templedb deploy run my-app --mutable

# 5. Fix and redeploy with FHS
./templedb deploy run my-app
```

## Comparison

| Feature | FHS Mode | Mutable Mode | No-FHS Mode |
|---------|----------|--------------|-------------|
| **Default** | ✅ Yes | No | No |
| **Isolation** | ✅ Full | ❌ None | ❌ None |
| **Reproducible** | ✅ Yes | ❌ No | ❌ No |
| **File editing** | ⚠️ Limited | ✅ Full | ✅ Full |
| **System deps** | ❌ None | ✅ Uses system | ✅ Uses system |
| **Performance** | ~500ms overhead | Fast | Fast |
| **Debugging** | Use `deploy shell` | Direct editing | Direct editing |
| **Recommended** | ✅ Production | ⚠️ Development | ❌ Avoid |

## Mode Detection

The system automatically detects and shows the mode:

```bash
# FHS mode
./templedb deploy list

  ✓ my-app 🔧 [FHS]              # 🔧 = FHS environment
     Shell: ./templedb deploy shell my-app

# Mutable mode
  ✓ test-app [FHS]               # No 🔧 = No FHS wrapper
     Shell: ./templedb deploy shell test-app
```

## Configuration

### Environment Variables

```bash
# Disable FHS by default (not recommended)
export TEMPLEDB_DEPLOYMENT_USE_FULL_FHS=false

# Change FHS directory
export TEMPLEDB_DEPLOYMENT_FHS_DIR=/data/deployments
```

### Per-Project Configuration

`.templedb/deploy-config.toml`:

```toml
[deployment]
# Force mutable mode for this project
force_mutable = true

# Or force FHS
force_fhs = true

[deployment.fhs]
# Extra packages to include
extra_packages = ["docker", "kubectl"]
```

## Migration Guide

### From Old TempleDB (No FHS)

**Before:**
```bash
./templedb deploy run my-project
# Used system packages
```

**After (automatic):**
```bash
./templedb deploy run my-project
# Now uses FHS automatically!
```

**If it breaks:**
```bash
# Temporarily use old behavior
./templedb deploy run my-project --no-fhs

# Or use mutable mode
./templedb deploy run my-project --mutable
```

### To Mutable When Needed

**Scenario:** Need to quickly edit and test deploy script

```bash
# Before: Manual navigation
./templedb deploy run my-project
cd /complicated/path/to/deployment
vim deploy.sh
./deploy.sh

# After: Mutable mode
./templedb deploy run my-project --mutable
cd $(./templedb deploy path my-project)
vim deploy.sh
./deploy.sh
```

## Best Practices

### ✅ Do This

1. **Use FHS for production**
   ```bash
   ./templedb deploy run my-app --target production
   ```

2. **Use mutable for development**
   ```bash
   ./templedb deploy run my-app --target dev --mutable
   ```

3. **Test in FHS before production**
   ```bash
   ./templedb deploy run my-app --target staging
   ./templedb deploy shell my-app  # Test
   ```

4. **Use deploy shell for debugging**
   ```bash
   ./templedb deploy shell my-app
   # Better than cd + manual exploration
   ```

### ❌ Don't Do This

1. **Don't use --no-fhs without reason**
   ```bash
   # Bad: Loses reproducibility
   ./templedb deploy run my-app --no-fhs
   ```

2. **Don't edit files in FHS mode**
   ```bash
   # Won't work - FHS files are from Nix store
   cd $(./templedb deploy path my-app)
   vim some-file  # Changes may not persist
   ```

3. **Don't deploy mutable to production**
   ```bash
   # Bad: Not reproducible
   ./templedb deploy run my-app --target prod --mutable
   ```

## Troubleshooting

### FHS Environment Not Working

**Problem:** Deployment fails in FHS

**Solution:**
```bash
# Check what packages were detected
./templedb deploy run my-app --dry-run

# Try mutable mode to debug
./templedb deploy run my-app --mutable

# Add missing packages
export TEMPLEDB_FHS_EXTRA_PACKAGES="missing-pkg"
./templedb deploy run my-app
```

### Need to Edit Files

**Problem:** Can't edit files in FHS deployment

**Solution:**
```bash
# Use mutable mode
./templedb deploy run my-app --mutable

# Or edit source and redeploy
./templedb project sync my-app
./templedb deploy run my-app
```

### FHS Too Slow

**Problem:** FHS adds overhead

**Solution:**
```bash
# FHS is cached - only slow first time
# Subsequent deploys are fast (~500ms)

# Or use mutable for rapid iteration
./templedb deploy run my-app --mutable

# Then final deploy with FHS
./templedb deploy run my-app
```

## FAQ

### Why is FHS default now?

**Reproducibility.** Every deployment gets the exact same environment, regardless of what's installed on the system.

### Can I disable FHS globally?

Yes, but not recommended:
```bash
export TEMPLEDB_DEPLOYMENT_USE_FULL_FHS=false
```

### What's the difference between --mutable and --no-fhs?

- `--mutable`: Deploys to FHS directory, but doesn't wrap in FHS environment
- `--no-fhs`: Completely disables FHS (uses /tmp or old behavior)

Both allow file editing, but `--mutable` is preferred.

### Does FHS work without Nix?

No. FHS requires Nix installed. Use `--mutable` or `--no-fhs` if Nix unavailable.

### Can I use FHS for some projects and not others?

Yes, use `--mutable` or `--no-fhs` per-project as needed.

## Summary

### Quick Reference

| Command | Mode | Use Case |
|---------|------|----------|
| `deploy run my-app` | FHS (default) | Production, reproducible |
| `deploy run my-app --mutable` | Mutable | Development, quick edits |
| `deploy run my-app --no-fhs` | No FHS | Emergency only |
| `deploy shell my-app` | Auto-detect | Access deployment |
| `deploy exec my-app 'cmd'` | Auto-detect | Run command |

### Key Takeaways

- ✅ **FHS is now default** - Automatic, isolated, reproducible
- 🔓 **Mutable mode available** - Use `--mutable` when needed
- 🚀 **Easy access** - `deploy shell` and `deploy exec` work in all modes
- ⚠️ **No-FHS discouraged** - Only for emergencies

---

**Status:** ✅ FHS is default (can opt-out with --mutable or --no-fhs)
**Recommendation:** Use FHS for production, mutable for development
