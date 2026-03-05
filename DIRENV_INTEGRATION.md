# Direnv Integration Guide

**Date**: 2026-03-04
**Status**: Complete
**Version**: 2.0

---

## Overview

TempleDB's direnv integration automatically loads your development environment when you `cd` into a project directory. It loads:

- **Nix environments** (flakes or legacy nix-shell)
- **Encrypted secrets** (from SOPS/age-encrypted store)
- **Environment variables** (per-environment configuration)
- **Compound values** (templated variables)

**Key improvements in v2.0**:
- ✅ Auto-reload when TempleDB data changes
- ✅ Profile auto-detection from git branch
- ✅ Environment-specific configuration
- ✅ Security validation
- ✅ `diff`/`verify` subcommands
- ✅ Direct `.envrc` writing

---

## Quick Start

### Basic Usage

```bash
# Navigate to your project
cd ~/myproject

# Initialize TempleDB project (one-time)
templedb project init

# Generate and write .envrc
templedb direnv generate --write

# Allow direnv to load it
direnv allow

# Done! Environment auto-loads when you cd into the directory
```

### Auto-Reload Setup

The generated `.envrc` includes a `watch_file` directive that automatically reloads when you update secrets or environment variables in TempleDB:

```bash
# Update a secret
templedb secret edit myproject

# cd into the directory - direnv auto-reloads!
cd ~/myproject
# direnv: loading .envrc
# direnv: export +DATABASE_URL +API_KEY ...
```

---

## Commands

### `templedb direnv generate`

Generate `.envrc` output (stdout or write to file)

**Syntax:**
```bash
templedb direnv generate [OPTIONS] [PROJECT_SLUG]
```

**Options:**
- `--profile PROFILE` - Secret profile (default, staging, production)
  - Auto-detected from git branch if not specified
- `--environment ENV`, `--env ENV` - Environment for env_vars (default, development, production)
- `--write`, `-w` - Write to `.envrc` file instead of stdout
- `--no-nix` - Don't emit Nix environment directives
- `--no-auto-reload` - Don't add `watch_file` for auto-reload
- `--no-validate` - Skip security validation
- `--branch BRANCH` - Override git branch detection
- `--ref REF` - Override git ref detection

**Examples:**
```bash
# Preview what would be generated (stdout)
templedb direnv generate

# Write to .envrc
templedb direnv generate --write

# Use production profile explicitly
templedb direnv generate --profile production --write

# Use development environment
templedb direnv generate --env development --write

# No Nix environment
templedb direnv generate --no-nix --write
```

### `templedb direnv diff`

Show diff between current `.envrc` and what would be generated

**Syntax:**
```bash
templedb direnv diff [OPTIONS] [PROJECT_SLUG]
```

**Examples:**
```bash
# See what changed since last generation
templedb direnv diff

# Check diff for production profile
templedb direnv diff --profile production
```

**Output:**
```diff
--- .envrc
+++ <generated>
@@ -10,7 +10,7 @@
 # --- Secrets (from SOPS-encrypted store) ---
-export DATABASE_URL='postgresql://localhost/old_db'
+export DATABASE_URL='postgresql://localhost/new_db'
 export API_KEY='sk-...'
```

### `templedb direnv verify`

Verify `.envrc` matches current TempleDB state

**Syntax:**
```bash
templedb direnv verify [OPTIONS] [PROJECT_SLUG]
```

**Examples:**
```bash
# Check if .envrc is up-to-date
templedb direnv verify

# Exit codes:
#   0 = up-to-date
#   1 = out of sync or missing
```

**Output:**
```
✓ .envrc is valid and up-to-date
```

Or:
```
⚠️  .envrc differs from TempleDB state
   Run 'templedb direnv diff' to see changes
   Run 'templedb direnv --write' to update
```

---

## Features

### 1. Auto-Reload with `watch_file`

Generated `.envrc` includes:
```bash
# Watch TempleDB database for changes
watch_file /home/user/.local/share/templedb/templedb.sqlite
```

**Behavior:**
- When you modify secrets/env vars in TempleDB
- Next `cd` into the directory auto-reloads `.envrc`
- No manual `templedb direnv` re-run needed

**Disable if not wanted:**
```bash
templedb direnv generate --no-auto-reload --write
```

### 2. Profile Auto-Detection from Git Branch

If no `--profile` specified, auto-detects from git branch:

| Git Branch | Auto-Selected Profile |
|------------|-----------------------|
| `main`, `master` | `production` |
| `develop`, `dev`, `development` | `development` |
| `staging*` | `staging` |
| Other | `default` |

**Example:**
```bash
# On main branch
git checkout main
templedb direnv generate --write
# Auto-detects profile='production'

# On develop branch
git checkout develop
templedb direnv generate --write
# Auto-detects profile='development'
```

**Override auto-detection:**
```bash
# Force specific profile
templedb direnv generate --profile staging --write
```

### 3. Environment-Specific Configuration

Use `--env` to select different environment variable sets:

```bash
# Development environment
templedb direnv generate --env development --write

# Production environment
templedb direnv generate --env production --write
```

This loads different values from the `env_vars` table based on the `environment` column.

### 4. Security Validation

Generated `.envrc` is validated for:
- Command injection patterns (`$(...)`, backticks, pipes)
- Unquoted values with spaces
- Dangerous shell constructs

**Example warning:**
```
# VALIDATION WARNINGS:
#   - Line 15: Possible command injection risk
#   - Line 23: Unquoted value with spaces
```

**Disable if needed:**
```bash
templedb direnv generate --no-validate --write
```

### 5. Comprehensive Output Comments

Generated `.envrc` includes helpful comments:

```bash
# .envrc - Generated by TempleDB
# Generated: 2026-03-04 10:30:45
# Project: myproject
# Profile: production
# Environment: default
# Git Branch: main

# Watch TempleDB database for changes
watch_file /home/user/.local/share/templedb/templedb.sqlite

# --- Nix Environment ---
use flake /home/user/myproject/.templedb-nix

# --- Secrets (from SOPS-encrypted store) ---
export DATABASE_URL='...'
export API_KEY='...'
# Loaded 2 secret(s) from profile 'production'

# --- Environment Variables (environment: default) ---
export NODE_ENV='production'
export PORT='3000'
# Loaded 2 environment variable(s)

# --- Compound Values (templated variables) ---
export MIGRATION_URL='...'
# Loaded 1 compound value(s)

# --- Summary ---
# Total: 5 variable(s) exported
#   Secrets: 2
#   Env Vars: 2
#   Compound: 1
```

### 6. Backup on Overwrite

When using `--write`, existing `.envrc` is backed up:

```bash
$ templedb direnv generate --write
⚠️  .envrc exists, will be overwritten
   Backup saved to .envrc.backup
✓ Set .envrc permissions to 600 (secrets present)
✓ Wrote .envrc (5 variables)

Run 'direnv allow' to activate the environment
```

### 7. Smart Permissions

- **600 (owner-only)**: If secrets are present
- **644 (readable)**: If no secrets

Prevents accidental secret exposure.

### 8. Project Auto-Detection

Slug is auto-detected from:
1. `.templedb/config` file (if project initialized with `templedb project init`)
2. Current directory name (fallback)

```bash
# No need to specify project if in project directory
cd ~/myproject
templedb direnv generate --write
# Auto-detects project="myproject"
```

---

## Workflows

### Initial Setup

```bash
# 1. Navigate to project
cd ~/myproject

# 2. Initialize TempleDB tracking
templedb project init

# 3. Configure secrets (one-time)
templedb secret edit myproject
# Add secrets in YAML format:
#   env:
#     DATABASE_URL: postgresql://...
#     API_KEY: sk-...

# 4. Generate .envrc
templedb direnv generate --write

# 5. Allow direnv
direnv allow

# Done! Environment auto-loads on cd
```

### Updating Secrets

```bash
# Edit secrets
templedb secret edit myproject

# Auto-reload happens on next cd
cd ~/myproject
# direnv: loading .envrc (automatically picks up changes)
```

Or force reload:
```bash
direnv reload
```

### Branch-Specific Profiles

```bash
# On production branch - uses production secrets
git checkout main
cd ~/myproject
templedb direnv generate --write
direnv allow
# Uses profile='production' (auto-detected)

# On development branch - uses dev secrets
git checkout develop
cd ~/myproject
templedb direnv generate --write
direnv allow
# Uses profile='development' (auto-detected)
```

### Multi-Environment Setup

```bash
# Development environment
templedb env set NODE_ENV development --environment development
templedb env set DEBUG 'true' --environment development

# Production environment
templedb env set NODE_ENV production --environment production
templedb env set DEBUG 'false' --environment production

# Generate for development
templedb direnv generate --env development --write

# Or for production
templedb direnv generate --env production --write
```

### Checking for Changes

```bash
# See if .envrc is out of date
templedb direnv verify

# See what changed
templedb direnv diff

# Update if needed
templedb direnv generate --write
direnv allow
```

---

## Troubleshooting

### Issue: `.envrc` not auto-reloading

**Symptoms:**
- Change secrets in TempleDB
- `cd` into directory
- Environment variables not updated

**Solutions:**

1. **Check `watch_file` directive is present:**
   ```bash
   grep watch_file .envrc
   # Should show: watch_file /home/user/.local/share/templedb/templedb.sqlite
   ```

2. **Regenerate with auto-reload:**
   ```bash
   templedb direnv generate --write
   direnv allow
   ```

3. **Force reload:**
   ```bash
   direnv reload
   ```

### Issue: Secrets not decrypting

**Symptoms:**
```
# ERROR: Failed to decrypt secrets: ...
```

**Solutions:**

1. **Check SOPS age key is set:**
   ```bash
   echo $SOPS_AGE_KEY_FILE
   # Should point to your age key file
   export SOPS_AGE_KEY_FILE=~/.age/key.txt
   ```

2. **Verify secrets exist:**
   ```bash
   templedb secret export myproject --format yaml
   ```

3. **Re-initialize secrets:**
   ```bash
   templedb secret init myproject --age-recipient age1...
   templedb secret edit myproject
   ```

### Issue: Validation warnings

**Symptoms:**
```
# VALIDATION WARNINGS:
#   - Line 15: Possible command injection risk
```

**Solutions:**

1. **Review the line:**
   ```bash
   sed -n '15p' .envrc
   ```

2. **Check for dangerous patterns:**
   - Command substitution: `$(...)`
   - Backticks: `` `command` ``
   - Pipes: `| command`

3. **Fix or disable validation:**
   ```bash
   # Fix the issue in TempleDB, then:
   templedb direnv generate --write

   # Or skip validation if false positive:
   templedb direnv generate --no-validate --write
   ```

### Issue: Wrong profile loaded

**Symptoms:**
- Expected production secrets
- Getting development secrets

**Solutions:**

1. **Check auto-detection:**
   ```bash
   git branch --show-current
   # If on 'main' -> should use 'production'
   # If on 'develop' -> should use 'development'
   ```

2. **Override explicitly:**
   ```bash
   templedb direnv generate --profile production --write
   ```

3. **Check .envrc header:**
   ```bash
   head -10 .envrc
   # Should show: # Profile: production
   ```

### Issue: Compound value resolution failures

**Symptoms:**
```
# ERROR: Failed to resolve 'API_URL': template error
```

**Solutions:**

1. **Check compound value template:**
   ```bash
   templedb compound show myproject API_URL
   ```

2. **Verify dependencies exist:**
   ```bash
   # If template is: https://${DOMAIN}/api
   # Ensure DOMAIN is defined:
   templedb env show DOMAIN
   ```

3. **Test resolution:**
   ```bash
   templedb compound resolve myproject API_URL
   ```

---

## Best Practices

### 1. Use `.envrc.local` for personal overrides

```bash
# .envrc - Committed to git
source_env .envrc.templedb

# .envrc.local - In .gitignore, personal settings
export DEBUG=true
export LOCAL_OVERRIDE=something
```

Then in `.envrc`:
```bash
# Source TempleDB-generated config
source .envrc.templedb

# Load personal overrides if present
if [ -f .envrc.local ]; then
  source .envrc.local
fi
```

### 2. Don't commit `.envrc` with secrets

**If `.envrc` contains secrets:**
- Add `.envrc` to `.gitignore`
- Document the generation command in README
- Use `templedb direnv generate --write` in setup scripts

**If no secrets (only Nix environment):**
- Can commit `.envrc`
- Add note: "Generated by TempleDB, regenerate with: `templedb direnv generate --write`"

### 3. Use profile-per-branch strategy

```bash
# .git/hooks/post-checkout
#!/bin/bash
# Auto-regenerate .envrc on branch change

BRANCH=$(git branch --show-current)

case "$BRANCH" in
  main|master)
    templedb direnv generate --profile production --write
    ;;
  develop|dev)
    templedb direnv generate --profile development --write
    ;;
  staging*)
    templedb direnv generate --profile staging --write
    ;;
esac
```

### 4. Validate before committing deployment configs

```bash
# In CI/CD or pre-deploy check
templedb direnv verify --profile production
if [ $? -ne 0 ]; then
  echo "ERROR: .envrc out of sync with TempleDB"
  exit 1
fi
```

### 5. Document required environment setup

In `README.md`:
```markdown
## Development Setup

1. Install direnv: `brew install direnv` (or `apt install direnv`)
2. Initialize project: `templedb project init`
3. Configure secrets: `templedb secret edit myproject`
4. Generate .envrc: `templedb direnv generate --write`
5. Allow direnv: `direnv allow`

Now `cd` into the directory auto-loads your environment!
```

---

## Comparison: Before vs After

### Before v2.0

```bash
# Generate .envrc (manual redirect)
templedb direnv > .envrc

# No auto-reload - must regenerate manually
templedb secret edit myproject
templedb direnv > .envrc  # Manual step!

# No diff/verify
# Can't see what changed

# Hardcoded environment
# No --env flag

# No validation
# Security issues not caught
```

### After v2.0

```bash
# Generate .envrc (direct write)
templedb direnv generate --write

# Auto-reload via watch_file
templedb secret edit myproject
cd ~/myproject  # Auto-reloads!

# Diff and verify
templedb direnv diff    # See changes
templedb direnv verify  # Check sync

# Environment selection
templedb direnv generate --env production --write

# Security validation
# Warns about injection risks
```

---

## Summary

✅ **All improvements implemented:**

| Feature | Status | Description |
|---------|--------|-------------|
| `.templedb-nix/` in .gitignore | ✅ | Prevents accidental commits |
| `--env` flag | ✅ | Environment-specific config |
| `--write` flag | ✅ | Direct .envrc writing |
| `watch_file` directive | ✅ | Auto-reload on changes |
| Improved error handling | ✅ | Better compound value errors |
| `diff`/`verify` commands | ✅ | Check .envrc sync |
| Profile auto-detection | ✅ | From git branch |
| Security validation | ✅ | Injection detection |
| Backup on overwrite | ✅ | `.envrc.backup` created |
| Smart permissions | ✅ | 600 for secrets, 644 otherwise |
| Comprehensive comments | ✅ | Helpful output headers |

**TempleDB direnv integration is now production-ready with enterprise-grade features!**

---

## Related Documentation

- **[GETTING_STARTED.md](GETTING_STARTED.md)** - TempleDB setup
- **[docs/advanced/SECURITY.md](docs/advanced/SECURITY.md)** - Secret management
- **[DEPLOYMENT_RESILIENCE.md](DEPLOYMENT_RESILIENCE.md)** - Production deployments

---

**Last Updated**: 2026-03-04
**Version**: 2.0
**Status**: Production Ready ✅
