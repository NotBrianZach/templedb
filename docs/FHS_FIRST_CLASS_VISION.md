# FHS First-Class Integration - Vision

**Status:** 🎯 Vision Document
**Current State:** Partial (opt-in)
**Goal:** Make FHS the default deployment method

## Current Reality: FHS is NOT First-Class

### What We Have Now

```bash
# Default deployment (no FHS)
templedb deploy run my-project
# → Deploys to directory
# → Runs deploy.sh with system packages
# → FHS not used

# FHS deployment (opt-in)
templedb deploy run my-project --use-fhs
# → Deploys to FHS directory
# → Creates FHS environment
# → Runs deploy.sh in FHS
# → FHS IS used
```

**Problem:** FHS is a **separate feature**, not the core deployment method.

## What First-Class Actually Means

### Definition

**First-class:** The primary, default, and recommended way to do something. Not an addon or optional feature.

### Examples in Other Tools

**Docker:** Containers are first-class
```bash
# This IS Docker's deployment model:
docker run my-app

# Not "docker run --use-containers my-app"
# Containers aren't optional - they're what Docker IS
```

**Nix:** Derivations are first-class
```bash
# This IS Nix's build model:
nix-build

# Not "nix-build --use-derivations"
# Derivations aren't optional - they're what Nix IS
```

**TempleDB (Current):** Regular deployment is first-class, FHS is opt-in
```bash
# Default:
templedb deploy run my-project
# Uses system packages (not FHS)

# FHS is an addon:
templedb deploy run my-project --use-fhs
```

**TempleDB (Vision):** FHS is first-class
```bash
# Default:
templedb deploy run my-project
# ALWAYS uses FHS (automatic package detection)

# System packages is opt-out:
templedb deploy run my-project --no-fhs
```

## Path to First-Class FHS

### Phase 1: Current State (✅ Done)

- [x] FHS directory structure
- [x] `deploy shell` command
- [x] `deploy exec` command
- [x] Visual indicators
- [x] Package detection code exists

**Status:** FHS is available but opt-in

### Phase 2: Make FHS Default (Not Done)

```python
# Change default behavior
DEPLOYMENT_METHOD = "fhs"  # Not "directory"

# Every deployment:
def deploy(project_slug):
    # 1. Auto-detect packages (always)
    packages = detect_packages(project_dir)
    print(f"📦 Detected: {', '.join(packages[:5])}...")

    # 2. Create FHS env (always)
    fhs_env = create_fhs_env(packages)

    # 3. Run in FHS (always)
    result = run_in_fhs(fhs_env, deployment_cmd)

    return result
```

**No `--use-fhs` flag needed** - it's just how deployment works.

### Phase 3: Remove the Distinction (Not Done)

Current code has two paths:

```python
# deploy.py (current - BAD)
if args.use_fhs:
    deploy_with_fhs()  # Special path
else:
    deploy_normally()  # Default path
```

First-class integration has one path:

```python
# deploy.py (vision - GOOD)
def deploy():
    # FHS is just how deployment works
    # No if/else needed
    packages = detect_packages()
    fhs_env = create_fhs_env(packages)
    run_in_fhs(fhs_env, commands)
```

### Phase 4: Show FHS is Core (Not Done)

**Default output shows FHS info:**

```bash
templedb deploy run my-project

🚀 Deploying my-project to production

📦 Detected dependencies:
   • nodejs 20.x
   • python3 3.11
   • postgresql 15
   • 12 more packages

🔧 Creating FHS environment...
   ✓ FHS environment ready

🏗️  Running deployment in isolated environment...
   ✓ npm install (using Nix nodejs)
   ✓ Build successful
   ✓ Tests passed

✅ Deployment complete!

💡 Access your deployment:
   Shell:   templedb deploy shell my-project
   Command: templedb deploy exec my-project '<cmd>'
```

**FHS is mentioned prominently** - it's not hidden.

## What Makes Something First-Class?

### Checklist

| Criteria | Current | First-Class |
|----------|---------|-------------|
| **Default behavior** | ❌ Regular deploy | ✅ FHS deploy |
| **Requires flag** | ❌ Yes (`--use-fhs`) | ✅ No flag needed |
| **Shown in output** | ⚠️ Only if using FHS | ✅ Always shown |
| **Documentation emphasis** | ⚠️ Separate doc | ✅ Main deploy docs |
| **User awareness** | ❌ Optional feature | ✅ Core concept |
| **Code structure** | ❌ Separate path | ✅ Integrated |
| **Error messages** | ❌ System packages | ✅ FHS packages |

### Score: 2/7 ⚠️

We've made FHS **available** but not **first-class**.

## Concrete Changes Needed

### 1. Change Default Behavior

```python
# config.py
DEPLOYMENT_USE_FULL_FHS = os.environ.get(
    'TEMPLEDB_DEPLOYMENT_USE_FULL_FHS',
    'true'  # Default to TRUE
).lower() in ('true', '1', 'yes')
```

### 2. Integrate into Core Deployment Flow

```python
# deployment_service.py
def deploy(project_slug, target, dry_run):
    # No if/else for FHS - it's always used

    # Step 1: Always detect packages
    logger.info("Detecting project dependencies...")
    packages = package_detector.detect(project_dir)

    logger.info(f"Detected {len(packages)} packages")
    for pkg in packages[:5]:  # Show first 5
        logger.info(f"  • {pkg}")

    # Step 2: Always create FHS
    logger.info("Creating FHS environment...")
    fhs_context = fhs_integration.prepare_fhs_deployment(
        project_slug, project_dir, env_vars, packages
    )

    # Step 3: Always run in FHS
    logger.info("Running deployment in FHS environment...")
    result = fhs_integration.run_deployment_in_fhs(
        fhs_context, deployment_command
    )

    return result
```

### 3. Update CLI

```python
# No --use-fhs flag needed (it's default)
# Add --no-fhs for opt-out

run_parser.add_argument(
    '--no-fhs',
    action='store_true',
    help='Skip FHS environment (use system packages - not recommended)'
)
```

### 4. Update Output

```python
# Always show FHS info
print(f"🚀 Deploying {project_slug} to {target}")
print(f"")
print(f"📦 Detected dependencies:")
for pkg in packages[:5]:
    print(f"   • {pkg}")
if len(packages) > 5:
    print(f"   • ... {len(packages)-5} more")
print(f"")
print(f"🔧 Creating FHS environment...")
# ... deployment continues
```

### 5. Update Documentation

**Main deployment docs mention FHS immediately:**

```markdown
# Deployment Guide

TempleDB deploys projects in isolated Nix FHS environments.

## How Deployment Works

1. **Package Detection** - Scans your project for dependencies
2. **FHS Environment** - Creates isolated environment with detected packages
3. **Deployment Execution** - Runs your deploy script in FHS

## Deploy a Project

\`\`\`bash
templedb deploy run my-project
\`\`\`

This automatically:
- Detects nodejs, python, postgres, etc. from your project
- Creates a Nix FHS environment with those packages
- Runs your deployment in complete isolation
```

Not a separate "FHS Integration" doc - it's in the main guide.

## Why First-Class Matters

### Current Problem

Users don't know FHS exists:

```
User: "My deploy broke because I updated node on my system"
You: "Oh, you should use --use-fhs"
User: "What's that? Where's it documented?"
You: "It's an optional feature..."
```

### With First-Class FHS

Users get FHS benefits automatically:

```
User: "I deployed my project"
Output: "📦 Detected nodejs 20.x, python3 3.11..."
User: "Oh cool, it detected my dependencies"
Output: "🔧 Creating FHS environment..."
User: "It's isolated? Nice!"
```

**They don't need to know** - it just works.

## Comparison: Current vs First-Class

### Current (FHS as Feature)

```bash
# Deployment (most users):
templedb deploy run my-project
→ Uses system packages
→ Can break if system changes
→ No isolation
→ Users don't know about FHS

# Power users only:
templedb deploy run my-project --use-fhs
→ Uses FHS
→ Isolated
→ Requires knowing about feature
```

**Result:** 90% of users get inferior experience.

### First-Class (FHS as Default)

```bash
# Deployment (all users):
templedb deploy run my-project
→ Auto-detects packages
→ Creates FHS environment
→ Fully isolated
→ Reproducible
→ Everyone gets best experience

# Escape hatch (rarely needed):
templedb deploy run my-project --no-fhs
→ Uses system packages
→ Only if FHS breaks
```

**Result:** 100% of users get FHS benefits by default.

## Trade-offs

### Why Not First-Class Yet?

**Concerns:**
1. **Nix dependency** - Requires Nix installed
2. **Overhead** - ~500ms to enter FHS
3. **Complexity** - More moving parts
4. **Unknown issues** - Haven't tested at scale

**Counterarguments:**
1. TempleDB already assumes Nix environment
2. 500ms is acceptable for reproducibility
3. Complexity is hidden from users
4. Can add `--no-fhs` escape hatch

### Decision Points

**Option A: Keep FHS Opt-In (Current)**
- ✅ Safe - doesn't break existing workflows
- ✅ Users can gradually adopt
- ❌ Most users won't use it
- ❌ Benefits not realized at scale

**Option B: Make FHS Default (First-Class)**
- ✅ All users get benefits
- ✅ Reproducibility by default
- ✅ Simpler mental model (one way to deploy)
- ❌ Breaking change for some users
- ❌ Requires Nix

**Recommendation:** Option B (gradual rollout)

## Rollout Plan

### Phase 1: Warn Users (Current Release)

```bash
templedb deploy run my-project

⚠️  Deploying without FHS environment
💡 Use --use-fhs for isolated, reproducible deployments
   Learn more: docs/FHS_INTEGRATION.md
```

### Phase 2: Make Default (Next Release)

```bash
# Change default
DEPLOYMENT_USE_FULL_FHS = 'true'

# Add prominent warning for opt-out
templedb deploy run my-project --no-fhs

⚠️  WARNING: Deploying without FHS isolation
⚠️  This uses system packages and may not be reproducible
💡 Remove --no-fhs to use FHS (recommended)
```

### Phase 3: Remove Old Path (Future)

```bash
# Only FHS path exists
# --no-fhs flag is deprecated/removed
templedb deploy run my-project
# Always uses FHS
```

## Success Criteria

FHS is truly first-class when:

- [ ] Default behavior uses FHS
- [ ] Documentation emphasizes FHS
- [ ] No flag needed to use FHS
- [ ] FHS info shown in all deploy output
- [ ] Users know they're using FHS
- [ ] FHS is the recommended path
- [ ] System package deployment is discouraged

## Summary

### Current State

FHS is an **optional add-on feature** that requires:
- Knowledge of its existence
- Passing a flag (`--use-fhs`)
- Reading separate documentation
- Opting in explicitly

**Most users don't use it.**

### First-Class Vision

FHS is **the deployment method** that:
- Works by default
- Requires no flags
- Is documented prominently
- Everyone gets automatically
- System packages is the opt-out

**All users benefit automatically.**

---

**Current Status:** 🟡 Partial (commands exist, but not default)
**Goal:** 🟢 First-class (FHS is the default deployment method)
**Next Step:** Change default behavior or keep as opt-in?
