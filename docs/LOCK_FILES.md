# Lock Files in TempleDB Deployments

**Status**: Implemented (2026-03-18)
**Related**: [FHS Deployments](./FHS_DEPLOYMENTS.md), [Deployment Caching](../migrations/034_add_deployment_cache.sql)

## Overview

TempleDB enforces lock files for reproducible deployments. This works in combination with Nix's `flake.lock` to provide **two-layer reproducibility**:

1. **System dependencies** (via Nix flake.lock) - Node.js, Python, PostgreSQL, etc.
2. **Application dependencies** (via language lock files) - npm packages, PyPI packages, etc.

## Why Two Layers?

### Nix flake.lock Provides:
- ✅ Exact nixpkgs commit (e.g., `d5f237872975a6...`)
- ✅ System-level packages pinned (Node.js 20.11.1, Python 3.11.8)
- ✅ Content hashes for verification

### Language Lock Files Provide:
- ✅ Exact application dependency versions (express@4.18.2, not ^4.18.0)
- ✅ Transitive dependency resolution (all sub-dependencies pinned)
- ✅ Package registry snapshots

**Example**: Without both layers:
```bash
# Nix ensures: node = 20.11.1 (exact)
# But package.json says: "express": "^4.18.0"
# Result: Could get 4.18.2 today, 4.18.3 tomorrow (non-reproducible)
```

## Supported Lock Files

### JavaScript/TypeScript

| Lock File | Command | When Used |
|-----------|---------|-----------|
| `package-lock.json` | `npm ci` | npm projects (default) |
| `yarn.lock` | `yarn install --frozen-lockfile` | Yarn projects |
| _(none)_ | `npm install` | Fallback (warns user) |

### Python

| Lock File | Command | When Used |
|-----------|---------|-----------|
| `poetry.lock` | `poetry install --no-dev` | Poetry projects |
| `Pipfile.lock` | `pipenv install --deploy` | Pipenv projects |
| _(none)_ | `pip install -r requirements.txt` | Fallback (warns user) |

## How It Works

### 1. Detection Phase

When TempleDB analyzes a project, it detects lock files:

```python
# In deployment_instructions.py
caps.has_package_lock = (work_dir / "package-lock.json").exists()
caps.has_yarn_lock = (work_dir / "yarn.lock").exists()
caps.has_poetry_lock = (work_dir / "poetry.lock").exists()
caps.has_pipfile_lock = (work_dir / "Pipfile.lock").exists()
```

### 2. Instruction Generation

Generated `DEPLOY_INSTRUCTIONS.md` uses appropriate commands:

**With lock file** (npm):
```bash
# 3. Install dependencies (if needed)
npm ci
```

**Without lock file** (warns):
```bash
# 3. Install dependencies (if needed)
npm install  # ⚠️ No lock file - builds may not be reproducible
```

### 3. Cache Integration

Lock file content is included in deployment cache hash:

```python
# In deployment_cache.py
def _hash_dependency_manifests(project_dir):
    manifest_files = [
        'package.json', 'package-lock.json',  # Both hashed
        'pyproject.toml', 'poetry.lock',      # Both hashed
        'requirements.txt',                   # Hashed
    ]
    # If lock file changes → hash changes → cache miss → rebuild
```

**Result**: Lock file updates automatically invalidate cache.

### 4. Validation

Projects without lock files get warnings:

```bash
templedb deploy myapp production

⚠️ WARNING: No lock file found (package-lock.json or yarn.lock)
   Recommendation: Run npm install locally and commit lock file for reproducible builds
```

## Best Practices

### For npm Projects

**Generate lock file**:
```bash
npm install  # Creates package-lock.json
git add package-lock.json
git commit -m "Add package-lock.json for reproducible builds"
```

**Update dependencies**:
```bash
npm update express  # Updates package.json AND package-lock.json
git add package.json package-lock.json
git commit -m "Update express to 4.19.0"
```

### For Poetry Projects

**Generate lock file**:
```bash
poetry lock  # Creates poetry.lock from pyproject.toml
git add poetry.lock
git commit -m "Add poetry.lock"
```

**Update dependencies**:
```bash
poetry update flask  # Updates poetry.lock
git add poetry.lock
git commit -m "Update Flask to 3.0.0"
```

### For Yarn Projects

**Generate lock file**:
```bash
yarn install  # Creates yarn.lock
git add yarn.lock
git commit -m "Add yarn.lock"
```

**Update dependencies**:
```bash
yarn upgrade express  # Updates yarn.lock
git add yarn.lock
git commit -m "Update express to 4.19.0"
```

## Commands

### Check Lock File Status

```bash
# Validate deployment (shows lock file warnings)
templedb deploy validate myapp production
```

### See What Changed

```bash
# Deployment cache tracks lock file changes
templedb cache list --project myapp

# Output shows content hash includes lock files:
#   Hash:       abc123def456  # Changes when lock files change
```

## Troubleshooting

### "Module not found" Errors After Deploy

**Symptom**: App crashes with missing module errors

**Cause**: Lock file not committed or out of sync

**Fix**:
```bash
# Locally: regenerate lock file
rm -rf node_modules package-lock.json
npm install
git add package-lock.json
git commit -m "Update lock file"

# Redeploy
templedb deploy myapp production
```

### Lock File Conflicts During Git Merge

**Symptom**: Git merge conflicts in `package-lock.json`

**Fix**:
```bash
# Accept one side and regenerate
git checkout --ours package-lock.json  # or --theirs
npm install  # Regenerates lock file
git add package-lock.json
git commit
```

### Different Lock File Versions

**Symptom**: `package-lock.json` changes between `lockfileVersion: 2` and `lockfileVersion: 3`

**Cause**: Different npm versions on dev machines

**Fix**: Pin npm version in `.npmrc`:
```
engine-strict=true  # Force package.json engines field
```

And in `package.json`:
```json
{
  "engines": {
    "npm": ">=10.0.0",
    "node": ">=20.0.0"
  }
}
```

## Implementation Details

### Files Modified

- `src/deployment_instructions.py` (+80 lines)
  - Lock file detection in `_detect_capabilities()`
  - Conditional install commands in `_generate_getting_started()`
  - Validation warnings in `_validate_dependencies()`
  - Troubleshooting updates in `_generate_failure_modes()`

### ProjectCapabilities Schema

```python
@dataclass
class ProjectCapabilities:
    has_package_lock: bool = False      # npm lock file
    has_yarn_lock: bool = False         # yarn lock file
    has_poetry_lock: bool = False       # poetry lock file
    has_pipfile_lock: bool = False      # pipenv lock file
    has_requirements_txt: bool = False  # pip requirements
```

## Future Enhancements

### Potential Additions

1. **Lock File Diffing**
   ```bash
   templedb deploy diff myapp production
   # Shows which dependencies changed in lock file
   ```

2. **Automatic Lock File Validation**
   - Detect lock file drift (out of sync with package.json)
   - Fail deployment if lock file invalid

3. **Lock File in Cathedral Packages**
   - Include lock files in exported `.cathedral` bundles
   - Ensure imported projects are reproducible

4. **Nix-native Package Management**
   - Use `dream2nix` or `node2nix` to convert lock files → Nix derivations
   - Fully Nix-managed dependencies (no npm/pip at runtime)

## Related Documentation

- [FHS Deployments](./FHS_DEPLOYMENTS.md) - How Nix FHS environments work
- [Deployment Caching](../migrations/034_add_deployment_cache.sql) - How cache uses lock file hashes
- [Error Handling](./ERROR_HANDLING_MIGRATION.md) - Deployment error patterns

## Summary

**Lock files ensure reproducible builds** by pinning exact dependency versions. TempleDB automatically detects and uses lock files when available:

- ✅ `npm ci` for package-lock.json
- ✅ `yarn install --frozen-lockfile` for yarn.lock
- ✅ `poetry install --no-dev` for poetry.lock
- ✅ `pipenv install --deploy` for Pipfile.lock
- ✅ Cache invalidation on lock file changes
- ⚠️ Warnings for projects without lock files

Combined with Nix's flake.lock, this provides **complete reproducibility** from operating system to application dependencies.
