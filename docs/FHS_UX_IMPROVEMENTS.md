# FHS User Experience Improvements

**Date:** 2026-03-16
**Status:** ✅ Implemented

## Problem

Original FHS integration required users to:
1. Know about the `enter-fhs.sh` script
2. Find the deployment directory
3. Navigate there and run the script

This was **not discoverable** and had poor UX.

## Solution

Integrated FHS access directly into the TempleDB CLI with intuitive commands.

## New Commands

### `deploy shell` - Enter FHS Environment

Enter an interactive shell in the deployment environment (automatically uses FHS if available).

```bash
# Enter shell for a deployed project
templedb deploy shell my-project

# Output:
🔧 Entering FHS environment for my-project
📁 Project: ~/.templedb/fhs-deployments/my-project/working
📦 FHS: ~/.templedb/fhs-deployments/my-project/fhs-env.nix

💡 Type 'exit' to leave the FHS environment

(fhs:my-project) $  # Now in FHS shell with all packages
```

**Features:**
- ✅ Automatically detects FHS environment
- ✅ Falls back to regular shell if no FHS
- ✅ Sets working directory correctly
- ✅ Shows clear status messages
- ✅ Intuitive `exit` to leave

### `deploy exec` - Run Command in FHS

Execute a single command in the deployment environment (in FHS if available).

```bash
# Run a single command
templedb deploy exec my-project 'npm run build'

# Run tests
templedb deploy exec my-project 'pytest tests/'

# Check node version (from FHS, not system)
templedb deploy exec my-project 'node --version'
```

**Features:**
- ✅ One-off command execution
- ✅ No need to enter/exit shell
- ✅ Uses FHS automatically if available
- ✅ Perfect for CI/CD

## Improved `deploy list` Output

Now shows FHS status with visual indicators:

```bash
templedb deploy list

📦 Deployed Projects (3):

  ✓ my-project 🔧 [FHS]
     Path: ~/.templedb/fhs-deployments/my-project/working
     Updated: 5 minutes ago
     Shell: templedb deploy shell my-project

  ✓ old-project [/tmp]
     Path: /tmp/templedb_deploy_old-project/working
     Updated: 2 days ago

  ✓ test-project [FHS]
     Path: ~/.templedb/fhs-deployments/test-project/working
     Updated: 1 hour ago

💡 Tips:
   Enter shell:      templedb deploy shell <project>
   Run command:      templedb deploy exec <project> '<command>'
   Jump to project:  cd $(templedb deploy path <project>)
   FHS deployments:  ~/.templedb/fhs-deployments
```

**Indicators:**
- `🔧` - FHS environment available
- `[FHS]` - Deployed to FHS directory
- `[/tmp]` - Legacy /tmp deployment
- Shows direct `deploy shell` command

## Improved `deploy run` Output

After successful deployment, shows next steps:

```bash
templedb deploy run my-project

🚀 Deploying my-project to production...
[deployment output...]

✅ Deployment complete!

🔧 FHS environment available
   Enter shell:  templedb deploy shell my-project
   Run command:  templedb deploy exec my-project '<command>'
```

**Clear next steps** - User immediately knows how to access FHS.

## Usage Examples

### Example 1: Quick Debug

```bash
# Deploy project
templedb deploy run my-app

# Enter FHS shell to debug
templedb deploy shell my-app

# Inside FHS, all packages available
(fhs:my-app) $ npm run test
(fhs:my-app) $ python manage.py shell
(fhs:my-app) $ psql $DATABASE_URL
(fhs:my-app) $ exit

# Done!
```

### Example 2: Run Single Command

```bash
# Check what's deployed
templedb deploy exec my-app 'ls -la'

# Run build
templedb deploy exec my-app 'npm run build'

# Check env vars
templedb deploy exec my-app 'env | grep NODE'
```

### Example 3: CI/CD Pipeline

```bash
#!/bin/bash
# deploy.sh for CI

# Deploy project
templedb deploy run my-app --target production

# Run tests in FHS environment
templedb deploy exec my-app 'npm test'

# Run migrations
templedb deploy exec my-app 'npm run migrate'

# Check deployment
templedb deploy exec my-app 'curl http://localhost:3000/health'
```

### Example 4: Development Workflow

```bash
# List deployed projects
templedb deploy list

# Enter shell for quick iteration
templedb deploy shell my-app

# Inside shell:
(fhs:my-app) $ npm install new-package
(fhs:my-app) $ npm run dev
(fhs:my-app) $ exit

# Or run commands directly
templedb deploy exec my-app 'npm run dev'
```

## Comparison: Before vs After

### Before (Poor UX)

```bash
# Deploy
templedb deploy run my-project

# ✅ Deployment complete!
# 📁 Deployed to: ~/.templedb/fhs-deployments/my-project/working

# Now what? User has to:
1. Remember FHS is a thing
2. Know about enter-fhs.sh
3. Navigate to deployment dir
4. Find and run the script

cd ~/.templedb/fhs-deployments/my-project/working
./enter-fhs.sh  # If they can find it!
```

**Problems:**
- ❌ Not discoverable
- ❌ Too many steps
- ❌ Hidden functionality
- ❌ Easy to forget

### After (Good UX)

```bash
# Deploy
templedb deploy run my-project

# ✅ Deployment complete!
#
# 🔧 FHS environment available
#    Enter shell:  templedb deploy shell my-project
#    Run command:  templedb deploy exec my-project '<command>'

# Clear next step!
templedb deploy shell my-project

# Or run a command
templedb deploy exec my-project 'npm test'
```

**Benefits:**
- ✅ Discoverable (shown in output)
- ✅ One command to enter
- ✅ Clear and intuitive
- ✅ Hard to miss

## Help Text

```bash
templedb deploy --help

# Shows new commands:
...
  shell               Enter interactive shell in deployment (FHS if available)
  exec                Execute command in deployment environment
...
```

## Backward Compatibility

Old workflows still work:

```bash
# Can still navigate manually
cd $(templedb deploy path my-project)

# Can still use enter-fhs.sh if it exists
./enter-fhs.sh

# But new way is easier:
templedb deploy shell my-project
```

## Command Aliases (Future)

Could add shorter aliases:

```bash
# Short aliases
tdb deploy shell my-project  # Current
tdb shell my-project          # Future: even shorter?
tdb exec my-project 'npm test'

# Or use subcommand directly
tdb my-project shell          # Namespace under project?
tdb my-project exec 'npm test'
```

## Integration with Other Commands

### With `deploy list`

```bash
templedb deploy list

# Shows shell command directly
Shell: templedb deploy shell my-project
```

### With `deploy path`

```bash
# Still works for cd
cd $(templedb deploy path my-project)

# But shell is easier
templedb deploy shell my-project
```

### With `deploy status`

Could enhance to show FHS info:

```bash
templedb deploy status my-project

📊 Deployment Status: my-project

🔧 FHS Environment: Available
   Packages: nodejs, python3, postgresql (15 total)
   Enter: templedb deploy shell my-project
...
```

## Summary

### What Changed

1. **Added `deploy shell`** - Enter FHS interactively
2. **Added `deploy exec`** - Run commands in FHS
3. **Updated `deploy list`** - Show FHS indicators
4. **Updated `deploy run`** - Show FHS next steps

### UX Improvements

| Aspect | Before | After |
|--------|--------|-------|
| **Discoverability** | Hidden | Shown in output |
| **Steps** | 4-5 steps | 1 command |
| **Intuitive** | No | Yes |
| **Documentation** | Required | Self-explanatory |
| **Memorability** | Hard | Easy |

### Key Benefits

- ✅ **One command** to enter FHS
- ✅ **Discoverable** from deploy output
- ✅ **Intuitive** naming (shell, exec)
- ✅ **Visual feedback** (indicators, status)
- ✅ **Helpful tips** in all output

---

**Status:** ✅ Ready to use
**Commands:** `deploy shell`, `deploy exec`
**Documentation:** Self-explanatory via CLI output
