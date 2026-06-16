# TempleDB Deployment Quick Reference

**Version:** 2.0 (FHS by default)
**Date:** 2026-03-17

## TL;DR

```bash
# Default deployment (FHS isolation - reproducible)
templedb deploy run my-project

# Mutable deployment (file editing enabled)
templedb deploy run my-project --mutable

# Access deployed project
templedb deploy shell my-project
templedb deploy exec my-project 'npm test'
```

## Deployment Modes

### FHS Mode (Default) ✅

**Command:**
```bash
templedb deploy run my-project
```

**What happens:**
- 📦 Auto-detects dependencies (nodejs, python, postgres, etc.)
- 🔧 Creates Nix FHS environment
- 🚀 Runs deployment in isolation
- ✅ Reproducible across machines

**Requirements:**
- Nix installed on system
- ~500ms overhead (first deploy)

**Use for:**
- Production deployments
- Staging environments
- CI/CD pipelines
- Team collaboration

### Mutable Mode (File Editing) 📝

**Command:**
```bash
templedb deploy run my-project --mutable
```

**What happens:**
- 📁 Deploys to FHS directory
- 🔓 No FHS isolation wrapper
- ✏️ Files can be edited directly
- 🚀 Uses system packages

**Requirements:**
- None (works without Nix)
- Faster iteration

**Use for:**
- Development
- Debugging
- Quick testing
- Editing deploy scripts

### No-FHS Mode (Discouraged) ⚠️

**Command:**
```bash
templedb deploy run my-project --no-fhs
```

**What happens:**
- ⚠️ Shows warning
- Uses old behavior
- Not recommended

**Use for:**
- Emergency only
- When FHS is broken

## Common Tasks

### Deploy with FHS (Default)

```bash
# Standard production deploy
templedb deploy run my-app

# Deploy to specific target
templedb deploy run my-app --target staging

# Dry run (see what would happen)
templedb deploy run my-app --dry-run
```

### Edit and Redeploy

```bash
# Deploy in mutable mode
templedb deploy run my-app --mutable

# Edit files
cd ~/.templedb/fhs-deployments/my-app/working
vim deploy.sh

# Test changes
./deploy.sh

# Final deploy with FHS
templedb deploy run my-app
```

### Access Deployment

```bash
# Enter interactive shell
templedb deploy shell my-app

# Run single command
templedb deploy exec my-app 'npm test'

# Get deployment path
templedb deploy path my-app
```

### List Deployments

```bash
templedb deploy list
```

**Output:**
```
📦 Deployed Projects:

  ✓ my-app 🔧 [FHS]
     Shell: templedb deploy shell my-app
```

Legend:
- `🔧` = FHS environment available
- `[FHS]` = Using FHS directory structure

## Package Detection

FHS mode automatically detects packages from:

| File | Detected Packages | Reason |
|------|------------------|--------|
| `package.json` | nodejs, npm | Node.js project |
| `requirements.txt` | python3, pip | Python project |
| `Cargo.toml` | rustc, cargo | Rust project |
| `go.mod` | go | Go project |
| `Gemfile` | ruby, bundler | Ruby project |
| `composer.json` | php, composer | PHP project |
| Database URLs | postgresql/mysql | Database client |
| `deploy.sh` | bash, curl, jq | Common tools |

Plus base packages: coreutils, git, openssl, cacert, wget

## Output Examples

### FHS Deployment

```
🚀 Deploying my-app to production...

📦 Detected dependencies:
   • nodejs
   • npm
   • postgresql
   • ... and 7 more

🔧 Creating FHS environment...
   ✓ FHS environment ready

🏗️  Running deployment...
   (Running in FHS environment)
   ✓ Build successful

✅ Deployment complete!

🔧 FHS environment available:
   Enter shell:  templedb deploy shell my-app
   Run command:  templedb deploy exec my-app '<command>'
```

### Mutable Deployment

```
⚠️  MUTABLE MODE: FHS isolation disabled
   Files can be edited directly, but deployment is not reproducible

🚀 Deploying my-app to production...

🏗️  Running deployment...
   ✓ Build successful

✅ Deployment complete!

📁 Deployed to: ~/.templedb/fhs-deployments/my-app/working
   💡 Deploy with --use-fhs for FHS environment
```

## Configuration

### Environment Variables

```bash
# Disable FHS globally (not recommended)
export TEMPLEDB_DEPLOYMENT_USE_FULL_FHS=false

# Change FHS directory
export TEMPLEDB_DEPLOYMENT_FHS_DIR=/data/deployments

# Add extra packages
export TEMPLEDB_FHS_EXTRA_PACKAGES="docker,kubectl"
```

### Per-Project Config

`.templedb/deploy-config.toml`:
```toml
[deployment]
force_mutable = true  # Always use mutable mode
```

## Troubleshooting

### FHS Deployment Fails

**Problem:** `No such file or directory: 'nix-shell'`

**Solution:**
```bash
# Option 1: Install Nix
curl -L https://nixos.org/nix/install | sh

# Option 2: Use mutable mode
templedb deploy run my-app --mutable
```

### Need to Edit Files

**Problem:** Can't edit files in FHS deployment

**Solution:**
```bash
# Use mutable mode
templedb deploy run my-app --mutable

# Edit and test
cd $(templedb deploy path my-app)
vim some-file

# Redeploy with FHS when ready
templedb deploy run my-app
```

### Missing Package

**Problem:** Package not detected automatically

**Solution:**
```bash
# Add manually
export TEMPLEDB_FHS_EXTRA_PACKAGES="missing-package"
templedb deploy run my-app
```

### Too Slow

**Problem:** FHS adds overhead

**Solution:**
```bash
# FHS is cached - only slow first time
# Subsequent deploys: ~500ms

# Or use mutable for rapid iteration
templedb deploy run my-app --mutable

# Final deploy with FHS
templedb deploy run my-app
```

## Cheat Sheet

| Task | Command |
|------|---------|
| Deploy (FHS) | `templedb deploy run my-app` |
| Deploy (mutable) | `templedb deploy run my-app --mutable` |
| Deploy (no FHS) | `templedb deploy run my-app --no-fhs` |
| Enter shell | `templedb deploy shell my-app` |
| Run command | `templedb deploy exec my-app 'cmd'` |
| List deployments | `templedb deploy list` |
| Get path | `templedb deploy path my-app` |

## Migration from v1.x

### Before (v1.x)
```bash
templedb deploy run my-app
# Used system packages, deployed to /tmp
```

### After (v2.0)
```bash
templedb deploy run my-app
# Auto-detects packages, uses FHS, reproducible!
```

**If it breaks:**
```bash
# Temporary fallback
templedb deploy run my-app --mutable

# Or completely disable FHS
export TEMPLEDB_DEPLOYMENT_USE_FULL_FHS=false
```

## Best Practices

✅ **Do:**
- Use FHS for production
- Use mutable for development
- Test in FHS before deploying
- Use `deploy shell` for debugging

❌ **Don't:**
- Don't use `--no-fhs` without reason
- Don't edit files in FHS mode
- Don't deploy mutable to production

## FAQ

**Q: Do I need Nix?**
A: For FHS mode, yes. Use `--mutable` if Nix unavailable.

**Q: Is FHS slower?**
A: ~500ms overhead (cached). First time: ~2s.

**Q: Can I disable FHS?**
A: Yes, use `--mutable` or `--no-fhs`.

**Q: How do I edit files?**
A: Use `--mutable` mode or edit source and redeploy.

---

**See Also:**
- `CHANGELOG_FHS_DEFAULT.md` - Full migration guide
- `DEPLOYMENT_MODES.md` - Detailed mode comparison
- `docs/FHS_DEPLOYMENTS.md` - Architecture details
