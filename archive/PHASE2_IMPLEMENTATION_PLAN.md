# Phase 2: Core Deployment Orchestration

**Date**: 2026-02-23
**Phase**: Phase 2 - Core Deployment Commands (MVP)
**Status**: In Progress
**Previous Phase**: Quick Wins (Completed)

---

## What We've Completed (Quick Wins)

✅ Basic deploy command (export + reconstruct + run script)
✅ Deploy status reporting
✅ Migration list/show commands
✅ Environment variable management (set/get/list/delete)
✅ Enhanced file type detection
✅ CLI integration

---

## Phase 2 Goals

Transform the basic deploy command into a full deployment orchestration system that can:
1. **Parse deployment configurations** stored in project metadata
2. **Orchestrate multi-component deployments** in correct order
3. **Track migration history** to avoid re-running migrations
4. **Validate environments** before deployment
5. **Manage deployment targets** (production, staging, etc.)

---

## Implementation Tasks

### Task 1: Deployment Configuration System

**Goal**: Enable projects to define deployment workflows in structured config

**Schema Changes**:
```sql
-- Add deployment_config column to projects table
ALTER TABLE projects ADD COLUMN deployment_config TEXT;

-- Config format (JSON):
{
  "groups": [
    {
      "name": "migrations",
      "order": 1,
      "file_patterns": ["migrations/*.sql", "woofsDB/migrations/*.sql"],
      "pre_deploy": ["psql --version"],
      "deploy_command": "psql $DATABASE_URL -f {file}",
      "post_deploy": ["echo 'Migrations applied'"],
      "required_env_vars": ["DATABASE_URL"]
    },
    {
      "name": "typescript_build",
      "order": 2,
      "file_patterns": ["src/**/*.ts"],
      "build_command": "npm run build",
      "test_command": "npm test",
      "required_env_vars": ["NODE_ENV"]
    },
    {
      "name": "edge_functions",
      "order": 3,
      "file_patterns": ["supabase/functions/*/index.ts"],
      "deploy_command": "supabase functions deploy {function_name}",
      "required_env_vars": ["SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"]
    }
  ],
  "health_check": {
    "url": "https://api.woofs.com/health",
    "expected_status": 200,
    "timeout_seconds": 30
  }
}
```

**Commands**:
```bash
# Initialize deployment config for a project
templedb deploy init <project>

# Edit deployment config
templedb deploy config <project> --edit

# Show deployment config
templedb deploy config <project> --show

# Validate deployment config
templedb deploy config <project> --validate
```

**Files to Create/Modify**:
- `src/cli/commands/deploy.py` - Add config management methods
- `src/deployment_config.py` - Config parser and validator (NEW)
- `migrations/012_add_deployment_config.sql` - Schema migration (NEW)

---

### Task 2: Migration Tracking System

**Goal**: Track which migrations have been applied to prevent re-running

**Schema**:
```sql
CREATE TABLE migration_history (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id),
    target_name TEXT NOT NULL,        -- 'production', 'staging', 'local'
    migration_file TEXT NOT NULL,     -- Relative path from project root
    migration_checksum TEXT NOT NULL, -- SHA256 of migration content
    applied_at TEXT NOT NULL DEFAULT (datetime('now')),
    applied_by TEXT,                  -- User who ran the migration
    execution_time_ms INTEGER,
    status TEXT NOT NULL DEFAULT 'success',  -- 'success', 'failed', 'rolled_back'
    error_message TEXT,
    UNIQUE(project_id, target_name, migration_file)
);

CREATE INDEX idx_migration_history_project_target
    ON migration_history(project_id, target_name);

CREATE INDEX idx_migration_history_status
    ON migration_history(status);
```

**Commands**:
```bash
# Show migration status (applied vs pending)
templedb migration status <project> --target production

# Apply pending migrations
templedb migration apply <project> --target production [--dry-run]

# Mark migration as applied (without running)
templedb migration mark-applied <project> <migration> --target production

# Show migration history
templedb migration history <project> --target production [--limit 20]
```

**Files to Create/Modify**:
- `migrations/013_add_migration_history.sql` - Schema migration (NEW)
- `src/cli/commands/migration.py` - Add status, apply, history commands
- `src/migration_tracker.py` - Migration tracking logic (NEW)

---

### Task 3: Deployment Group Orchestration

**Goal**: Execute deployment groups in order with pre/post hooks

**Architecture**:
```python
# src/deployment_orchestrator.py (NEW)
class DeploymentOrchestrator:
    def __init__(self, project, target, config):
        self.project = project
        self.target = target
        self.config = config
        self.results = []

    def deploy(self, dry_run=False):
        """Execute deployment groups in order"""
        for group in sorted(self.config.groups, key=lambda g: g.order):
            result = self.deploy_group(group, dry_run)
            self.results.append(result)
            if not result.success:
                self.handle_failure(group, result)
                break

        if self.config.health_check and not dry_run:
            self.run_health_check()

        return DeploymentResult(self.results)

    def deploy_group(self, group, dry_run):
        """Deploy a single group"""
        # Run pre-deploy hooks
        for hook in group.pre_deploy:
            self.run_hook(hook, dry_run)

        # Deploy components
        files = self.get_matching_files(group.file_patterns)
        for file in files:
            self.deploy_file(file, group, dry_run)

        # Run post-deploy hooks
        for hook in group.post_deploy:
            self.run_hook(hook, dry_run)
```

**Enhanced Deploy Command**:
```bash
# Deploy using config (orchestrated)
templedb deploy run <project> --target production [OPTIONS]

OPTIONS:
  --dry-run              Show what would be deployed
  --group <name>         Deploy only specific group (migrations, functions, etc.)
  --skip-group <name>    Skip specific group
  --validate-env         Validate required env vars before deploying
  --no-health-check      Skip health check after deployment
  --continue-on-failure  Continue if a group fails
```

**Files to Create/Modify**:
- `src/deployment_orchestrator.py` - Core orchestration logic (NEW)
- `src/cli/commands/deploy.py` - Update deploy() method to use orchestrator
- `src/deployment_result.py` - Result tracking (NEW)

---

### Task 4: Deployment Target Management

**Goal**: Better CLI for managing deployment targets

**Current State**: deployment_targets table exists but no commands

**Commands to Add**:
```bash
# Add deployment target
templedb target add <project> <target_name> \
  --type <database|edge_function|static_site> \
  --provider <supabase|vercel|aws> \
  --host <hostname> \
  --region <region>

# List deployment targets
templedb target list <project>

# Update target
templedb target update <project> <target_name> --host <new_host>

# Remove target
templedb target remove <project> <target_name>

# Test target connectivity
templedb target test <project> <target_name>
```

**Files to Create**:
- `src/cli/commands/target.py` - Target management commands (NEW)
- Update `src/cli/__init__.py` to register target commands

---

### Task 5: Environment Validation

**Goal**: Validate required env vars before deployment

**Implementation**:
```python
# src/env_validator.py (NEW)
class EnvironmentValidator:
    def __init__(self, project, target):
        self.project = project
        self.target = target

    def validate(self, required_vars):
        """Check all required env vars are set"""
        missing = []
        for var_name in required_vars:
            value = self.get_env_var(var_name)
            if not value:
                missing.append(var_name)

        if missing:
            raise MissingEnvironmentVariables(missing)

        return ValidationResult(success=True)
```

**Integration**:
- Automatically run before deployment if config has required_env_vars
- Can be disabled with --skip-validation flag
- Shows helpful error message with instructions to set missing vars

---

## Implementation Order

### Week 1: Foundation
1. ✅ Day 1-2: Create migration_history table and schema
2. ✅ Day 3-4: Implement deployment config parser
3. ✅ Day 5: Add deployment_config column to projects table

### Week 2: Core Features
4. Day 1-2: Implement migration tracking (status, apply commands)
5. Day 3-4: Build deployment orchestrator
6. Day 5: Add target management commands

### Week 3: Integration & Testing
7. Day 1-2: Integrate orchestrator with deploy command
8. Day 3: Add environment validation
9. Day 4-5: End-to-end testing with woofs_projects

---

## Success Criteria

### Must Have
- ✅ Deployment config stored in database
- ✅ Migration tracking (no duplicate migrations)
- ✅ Multi-group orchestration (order preserved)
- ✅ Pre/post deployment hooks
- ✅ Environment validation
- ✅ Target management commands

### Nice to Have
- Deployment history visualization
- Rollback support (Phase 3)
- Deployment approval gates
- Slack/email notifications

---

## Testing Plan

### Unit Tests
- Config parser handles valid/invalid configs
- Migration tracker detects pending migrations
- Orchestrator respects group ordering
- Environment validator catches missing vars

### Integration Tests
- Full deployment workflow with woofs_projects
- Migration apply updates history correctly
- Pre/post hooks execute in correct order
- Dry-run mode doesn't modify anything

### Manual Testing
```bash
# Test workflow
cd /home/zach/templeDB

# 1. Initialize deployment config
./templedb deploy init woofs_projects

# 2. Add deployment target
./templedb target add woofs_projects production \
  --type database \
  --provider supabase \
  --host "db.woofs.com"

# 3. Set environment variables
./templedb env set woofs_projects DATABASE_URL "postgresql://..." --target production
./templedb env set woofs_projects SUPABASE_URL "https://..." --target production

# 4. Check migration status
./templedb migration status woofs_projects --target production

# 5. Dry run deployment
./templedb deploy run woofs_projects --target production --dry-run

# 6. Real deployment
./templedb deploy run woofs_projects --target production

# 7. Verify migration history
./templedb migration history woofs_projects --target production
```

---

## Example: Woofs Deployment Config

```json
{
  "groups": [
    {
      "name": "database_migrations",
      "order": 1,
      "file_patterns": [
        "migrations/*.sql",
        "woofsDB/migrations/*.sql"
      ],
      "pre_deploy": [
        "psql $DATABASE_URL -c 'SELECT version();'"
      ],
      "deploy_command": "psql $DATABASE_URL -f {file}",
      "post_deploy": [
        "psql $DATABASE_URL -c 'SELECT COUNT(*) FROM woofs.sync_state;'"
      ],
      "required_env_vars": ["DATABASE_URL"]
    },
    {
      "name": "typescript_build",
      "order": 2,
      "file_patterns": ["src/**/*.ts"],
      "build_command": "npm run build",
      "test_command": "npm test"
    },
    {
      "name": "edge_functions",
      "order": 3,
      "file_patterns": ["supabase/functions/*/index.ts"],
      "deploy_command": "cd /tmp/deploy_working && supabase functions deploy {function_name}",
      "required_env_vars": [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY"
      ]
    },
    {
      "name": "background_services",
      "order": 4,
      "file_patterns": ["*.service"],
      "deploy_command": "sudo systemctl restart {service_name}",
      "post_deploy": [
        "systemctl status woofs-snapshot-sync --no-pager"
      ]
    }
  ],
  "health_check": {
    "url": "https://api.woofs.com/health",
    "expected_status": 200,
    "timeout_seconds": 30
  }
}
```

---

## Migration from Quick Wins

The quick wins gave us:
- Basic deploy run (export + reconstruct + run script)
- Migration list/show
- Env var management

Phase 2 enhances these with:
- **Config-driven deployment** instead of just running deploy.sh
- **Migration tracking** to avoid re-running
- **Orchestration** for multi-component projects
- **Validation** before deployment

Both approaches can coexist:
- Projects without config → fallback to deploy.sh (current behavior)
- Projects with config → use orchestrator (new behavior)

---

## Next Steps

1. Start with Task 1: Create migration_history table
2. Then Task 2: Implement deployment config system
3. Build up to full orchestration
4. Test thoroughly with woofs_projects
5. Document everything

**Let's begin with the migration_history table schema!**
