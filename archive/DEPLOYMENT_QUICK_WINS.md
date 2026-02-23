# TempleDB Deployment Quick Wins

**Context**: Immediate actionable improvements for deploying projects like woofs

---

## What Works Today

✅ **Cathedral Export/Import** - Projects can be packaged and moved
✅ **File Tracking** - All project files tracked with types
✅ **Deployment Tables Exist** - Schema ready, just needs commands

---

## Quick Wins (1-2 Days Each)

### 1. Add Basic Deploy Command

**File**: `src/cli/commands/deploy.py`

```python
class DeployCommands(Command):
    def deploy(self, args):
        """Deploy project - Phase 1 MVP"""
        project_slug = args.slug
        target = args.target or 'production'

        print(f"🚀 Deploying {project_slug} to {target}...")

        # Step 1: Export cathedral package
        print("📦 Exporting project...")
        from cathedral_export import export_project
        export_dir = Path(f"/tmp/deploy_{project_slug}")
        export_project(project_slug, export_dir)

        # Step 2: Run deploy script if exists
        deploy_script = export_dir / f"{project_slug}.cathedral" / "deploy.sh"
        if deploy_script.exists():
            print("🔧 Running deployment script...")
            subprocess.run(["bash", str(deploy_script)], check=True)
        else:
            print("⚠️  No deploy.sh found - manual deployment required")

        print("✅ Deployment complete!")
```

**Usage**:
```bash
templedb deploy woofs_projects
```

**Time**: 2-3 hours

---

### 2. Detect Additional File Types

**File**: `src/file_types.py`

```python
# Add to detect_file_type()
def detect_file_type(file_path: str) -> str:
    """Enhanced detection for deployment files"""

    # Existing detection...

    # Deployment-related files
    if file_path.endswith('.service'):
        return 'systemd_service'

    if file_path.endswith('ecosystem.config.js'):
        return 'pm2_config'

    if 'supabase/functions/' in file_path and file_path.endswith('index.ts'):
        return 'edge_function'

    if file_path.endswith('deploy.sh') or file_path.endswith('deploy.py'):
        return 'deployment_script'

    # Existing return statement...
```

**Benefit**: Better organization and queries

**Time**: 1 hour

---

### 3. Add Deployment Config to Project Import

**File**: `src/project_import.py`

```python
# During project import, look for deployment config
def import_project(project_path: Path):
    # ... existing import logic ...

    # Look for deployment config
    deploy_config = project_path / 'deployment_config.yaml'
    if deploy_config.exists():
        config_content = deploy_config.read_text()
        # Store in projects.deployment_config JSON field
        cursor.execute(
            "UPDATE projects SET deployment_config = ? WHERE slug = ?",
            (config_content, slug)
        )
        print(f"  ✓ Imported deployment configuration")
```

**Benefit**: Deployment config tracked in DB

**Time**: 2 hours

---

### 4. Environment Variable Commands

**File**: `src/cli/commands/env.py`

Add simple env var management:

```python
class EnvCommands(Command):
    def set(self, args):
        """Set environment variable for project/target"""
        # Basic version - just store in environment_variables table
        cursor.execute("""
            INSERT OR REPLACE INTO environment_variables
            (project_id, env_name, env_value, target_name)
            VALUES (?, ?, ?, ?)
        """, (project_id, args.var_name, args.value, args.target))
        print(f"✓ Set {args.var_name} for {args.target}")

    def list(self, args):
        """List environment variables"""
        cursor.execute("""
            SELECT env_name, target_name, created_at
            FROM environment_variables
            WHERE project_id = ?
            ORDER BY target_name, env_name
        """, (project_id,))
        # Print results
```

**Usage**:
```bash
templedb env set woofs_projects SUPABASE_URL "https://..." --target production
templedb env list woofs_projects
```

**Time**: 3-4 hours

---

### 5. Migration Status Command

**File**: `src/cli/commands/migration.py`

```python
class MigrationCommands(Command):
    def list(self, args):
        """List migrations for project"""
        project = self.get_project_or_exit(args.slug)

        # Find all sql_migration files
        cursor.execute("""
            SELECT file_path, lines_of_code
            FROM files_with_types_view
            WHERE project_slug = ? AND type_name = 'sql_migration'
            ORDER BY file_path
        """, (args.slug,))

        migrations = cursor.fetchall()

        print(f"\n📝 Migrations for {args.slug}:\n")
        for file_path, loc in migrations:
            print(f"  • {file_path} ({loc} lines)")

        print(f"\n✓ Found {len(migrations)} migration files")
```

**Usage**:
```bash
templedb migration list woofs_projects
```

**Time**: 2 hours

---

## Medium-Term Improvements (1 Week)

### 6. Full Deployment Orchestration

- Parse deployment_config.yaml
- Run deployment groups in order
- Pre/post deploy hooks
- Environment validation
- Health checks

**See**: `DEPLOYMENT_ENHANCEMENTS.md` for full spec

---

## Usage Pattern

### Today (Manual)
```bash
cd woofs_projects
./deploy.sh
```

### With Quick Wins (Tomorrow)
```bash
templedb deploy woofs_projects
# Still runs deploy.sh but from TempleDB
```

### With Full Implementation (2-3 Weeks)
```bash
templedb deploy woofs_projects --target production
# Orchestrates: migrations → build → functions → services
# No manual scripts needed
```

---

## Implementation Order

**Day 1:**
1. Add basic `templedb deploy` command (Quick Win #1)
2. Detect new file types (Quick Win #2)

**Day 2:**
3. Import deployment config (Quick Win #3)
4. Add env var commands (Quick Win #4)

**Day 3:**
5. Add migration list command (Quick Win #5)
6. Test with woofs_projects
7. Document in README.md

**Week 2:**
- Full deployment orchestration
- Migration tracking
- Testing

---

## Testing Plan

```bash
# Test with woofs_projects
cd ~/templeDB

# 1. Re-import with new detection
./templedb project sync woofs_projects

# 2. Verify new file types detected
./templedb search files -p woofs_projects "deploy.sh"
# Should show: deployment_script

./templedb search files -p woofs_projects ".service"
# Should show: systemd_service

# 3. Test deploy command
./templedb deploy woofs_projects

# 4. Test env commands
./templedb env set woofs_projects TEST_VAR "test_value" --target local
./templedb env list woofs_projects

# 5. Test migration command
./templedb migration list woofs_projects
```

---

## Benefits

✅ **Immediate value**: Basic deployment from TempleDB today
✅ **Incremental**: Each quick win adds value independently
✅ **Low risk**: Doesn't break existing functionality
✅ **Foundation**: Sets up for full deployment system later

---

## Next Steps

1. Implement Quick Wins #1-2 (Day 1)
2. Test with woofs_projects
3. Implement Quick Wins #3-5 (Day 2-3)
4. Gather feedback
5. Plan full implementation (Week 2+)

See `DEPLOYMENT_ENHANCEMENTS.md` for complete vision and roadmap.
