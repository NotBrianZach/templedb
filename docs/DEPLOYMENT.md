# Deployment

Deploy projects from TempleDB to staging/production. Automated migrations, DNS, secrets, environment variables.

## Quick Start

```bash
# Setup
templedb target add myapp production --provider supabase --host db.example.com
templedb secret init myapp --age-recipient $(age-keygen -y ~/.config/age/keys.txt)
templedb secret edit myapp  # Add SUPABASE_SERVICE_KEY, etc.

# Deploy
templedb deploy run myapp --target production

# Rollback if needed
templedb deploy rollback myapp --target production
```

## Workflow

1. **Add target** → Define where to deploy
2. **Add secrets** → Store credentials encrypted
3. **Configure DNS** (optional) → Auto-configure domain
4. **Deploy** → Runs migrations, builds, tests
5. **Verify** → Check deployment status
6. **Rollback** (if needed) → Revert to previous version

## Deployment Targets

```bash
# Add targets
templedb target add myapp local --provider postgresql --host localhost:5432
templedb target add myapp staging --provider supabase --host staging.example.com
templedb target add myapp production --provider supabase --host db.example.com

# List all targets
templedb target list --project myapp

# Show target details
templedb target show myapp production
```

**Target config stored in database:**
```sql
SELECT * FROM deployment_targets WHERE project_slug = 'myapp';
```

## Secrets

```bash
# One-time: Generate age key
age-keygen -o ~/.config/age/keys.txt
export TEMPLEDB_AGE_KEY_FILE=~/.config/age/keys.txt

# Per-project: Initialize secrets
templedb secret init myapp --age-recipient $(age-keygen -y $TEMPLEDB_AGE_KEY_FILE)

# Edit secrets (opens $EDITOR with decrypted YAML)
templedb secret edit myapp

# Example secrets.yaml:
# supabase:
#   service_key: eyJhbGciOiJIUzI1...
#   anon_key: eyJhbGciOiJIUzI1...
# cloudflare:
#   api_token: xyz123...

# List secrets (shows keys only, not values)
templedb secret list myapp

# Export to environment
eval "$(templedb secret export myapp --format shell)"
```

Secrets encrypted with age, stored in database, decrypted on-demand during deployment.

## Deploy

```bash
# Dry run (preview what will happen)
templedb deploy run myapp --target production --dry-run

# Full deployment
templedb deploy run myapp --target production

# Skip specific steps
templedb deploy run myapp --target production --skip migrations
templedb deploy run myapp --target production --skip tests
```

**What happens:**
1. Load secrets for target
2. Generate environment variables (from DNS, secrets, target config)
3. Run pre-deploy hooks
4. Run migrations (SQL files)
5. Build project (npm/webpack/etc)
6. Run tests
7. Deploy edge functions / serverless
8. Run post-deploy hooks
9. Record deployment in database

## Deployment Groups

Configure deployment behavior in `.templedb/deploy.yaml`:

```yaml
project: myapp
targets:
  production:
    provider: supabase

groups:
  - name: migrations
    order: 1
    file_patterns: ["migrations/*.sql"]
    deploy_command: "psql $DATABASE_URL -f {file}"
    retry_attempts: 3
    retry_delay: 5
    timeout: 600

  - name: build
    order: 2
    deploy_command: "npm run build"
    timeout: 300

  - name: edge-functions
    order: 3
    file_patterns: ["supabase/functions/**/index.ts"]
    deploy_command: "supabase functions deploy {function_name}"

hooks:
  pre_deploy:
    - command: "npm install"
      timeout: 300
  post_deploy:
    - command: "npm run seed"
      critical: false  # Non-blocking
```

**Group execution:**
- Runs in `order` sequence
- Retries failures automatically
- Timeouts prevent hanging
- `critical: false` = failures don't stop deployment

## Resilience

**Automatic retries:**
```yaml
retry_attempts: 3    # Try 3 times
retry_delay: 5       # Wait 5 seconds between attempts
```

**Timeouts:**
```yaml
timeout: 600         # Kill if takes > 10 minutes
hook_timeout: 30     # Hook timeout (default: 30s)
```

**Non-critical operations:**
```yaml
critical: false      # Don't fail deployment if this fails
```

**Use cases:**
- Network timeouts (DB connections, npm registry)
- Lock conflicts (migration contention)
- Rate limits (cloud API throttling)

## Rollback

```bash
# List deployments
templedb deploy list myapp --target production

# Show deployment details
templedb deploy show myapp <deployment-id>

# Rollback to previous version
templedb deploy rollback myapp --target production

# Rollback to specific deployment
templedb deploy rollback myapp --target production --to <deployment-id>
```

**What rollback does:**
1. Find previous successful deployment
2. Restore files from that deployment
3. Run rollback hooks (if configured)
4. Update deployment status
5. NO automatic migration rollback (too dangerous - do manually)

## DNS Integration

```bash
# Register domain + configure DNS
templedb domain register myapp example.com --registrar cloudflare
templedb domain dns configure myapp example.com --target production
templedb domain dns apply myapp example.com --target production

# Deploy (uses DNS config automatically)
templedb deploy run myapp --target production
```

Auto-generated environment variables:
```
DOMAIN=example.com
API_URL=https://api.example.com
SUPABASE_URL=https://abc123.supabase.co
```

See [DNS.md](DNS.md) for full DNS documentation.

## Environment Variables

**Auto-generated from:**
- Target config (host, provider)
- DNS records (domain, API URLs)
- Secrets (decrypted on-demand)

**Check variables:**
```bash
# Show environment for target
templedb deploy env myapp --target production

# Query database
sqlite3 ~/.local/share/templedb/templedb.sqlite
SELECT key, value FROM deployment_env_vars
WHERE target_id = (SELECT id FROM deployment_targets WHERE name = 'production');
```

**Manual variables:**
```sql
INSERT INTO deployment_env_vars (target_id, key, value)
VALUES (
  (SELECT id FROM deployment_targets WHERE name = 'production'),
  'CUSTOM_VAR',
  'value'
);
```

## Monitoring

```bash
# View deployment history
templedb deploy list myapp

# Show latest deployment
templedb deploy show myapp --latest

# Check status
templedb deploy status myapp --target production
```

**Database queries:**
```sql
-- Recent deployments
SELECT id, target_name, status, created_at
FROM deployments
WHERE project_slug = 'myapp'
ORDER BY created_at DESC
LIMIT 10;

-- Failed deployments
SELECT id, target_name, error_message
FROM deployments
WHERE status = 'failed'
ORDER BY created_at DESC;

-- Deployment duration
SELECT target_name,
       AVG((julianday(completed_at) - julianday(started_at)) * 86400) as avg_seconds
FROM deployments
WHERE status = 'success'
GROUP BY target_name;
```

## Complete Example

```bash
# 1. Setup project + target
templedb project import https://github.com/user/myapp
templedb target add myapp production --provider supabase --host db.example.com

# 2. Setup secrets
age-keygen -o ~/.config/age/keys.txt
export TEMPLEDB_AGE_KEY_FILE=~/.config/age/keys.txt
templedb secret init myapp --age-recipient $(age-keygen -y $TEMPLEDB_AGE_KEY_FILE)
templedb secret edit myapp
# Add: supabase.service_key, supabase.anon_key

# 3. Setup DNS (optional)
templedb domain register myapp example.com --registrar cloudflare
templedb domain dns configure myapp example.com --target production
templedb domain dns apply myapp example.com --target production

# 4. Configure deployment
cat > .templedb/deploy.yaml <<EOF
project: myapp
groups:
  - name: migrations
    order: 1
    file_patterns: ["migrations/*.sql"]
    deploy_command: "psql \$DATABASE_URL -f {file}"
    retry_attempts: 3
  - name: build
    order: 2
    deploy_command: "npm run build"
hooks:
  pre_deploy:
    - command: "npm install"
EOF

# 5. Test deployment (dry run)
templedb deploy run myapp --target production --dry-run

# 6. Deploy
templedb deploy run myapp --target production

# 7. Verify
templedb deploy status myapp --target production
curl https://example.com/health

# 8. Rollback if needed
templedb deploy rollback myapp --target production
```

## Multi-Environment

```bash
# Deploy to staging first
templedb deploy run myapp --target staging
templedb deploy status myapp --target staging

# Verify staging
curl https://staging.example.com/health

# Deploy to production
templedb deploy run myapp --target production

# Compare environments
templedb deploy diff myapp --from staging --to production
```

## Troubleshooting

**"Target not found"**
```bash
templedb target list --project myapp
templedb target add myapp production --provider supabase --host db.example.com
```

**"Secrets not found"**
```bash
templedb secret list myapp
templedb secret init myapp --age-recipient <key>
templedb secret edit myapp
```

**"Migration failed"**
```bash
# Check migration error
templedb deploy show myapp --latest

# Run migration manually
psql $DATABASE_URL -f migrations/001_init.sql

# Skip migrations on retry
templedb deploy run myapp --target production --skip migrations
```

**"Deployment timeout"**
```yaml
# Increase timeout in .templedb/deploy.yaml
groups:
  - name: build
    timeout: 1200  # 20 minutes
```

**"Hook failed"**
```bash
# Check hook output
templedb deploy show myapp --latest

# Make hook non-critical
hooks:
  post_deploy:
    - command: "npm run seed"
      critical: false
```

## Commands Reference

```bash
# Targets
templedb target add <proj> <name> --provider <prov> --host <host>
templedb target list [--project <proj>]
templedb target show <proj> <name>
templedb target remove <proj> <name>

# Deployment
templedb deploy run <proj> --target <target> [--dry-run] [--skip <step>]
templedb deploy list <proj>
templedb deploy show <proj> [<deploy-id>] [--latest]
templedb deploy status <proj> --target <target>
templedb deploy env <proj> --target <target>
templedb deploy rollback <proj> --target <target> [--to <id>]
templedb deploy diff <proj> --from <target1> --to <target2>

# Secrets (see docs/SECURITY.md)
templedb secret init <proj> --age-recipient <key>
templedb secret edit <proj>
templedb secret list <proj>
templedb secret export <proj> --format shell

# DNS (see docs/DNS.md)
templedb domain register <proj> <domain> --registrar <reg>
templedb domain dns configure <proj> <domain> --target <target>
templedb domain dns apply <proj> <domain> --target <target>
```

## Database Schema

```sql
-- Targets
CREATE TABLE deployment_targets (
  id INTEGER PRIMARY KEY,
  project_id INTEGER,
  name TEXT,
  provider TEXT,
  host TEXT,
  config JSON
);

-- Deployments
CREATE TABLE deployments (
  id INTEGER PRIMARY KEY,
  project_id INTEGER,
  target_id INTEGER,
  status TEXT,  -- pending, running, success, failed
  started_at TIMESTAMP,
  completed_at TIMESTAMP,
  error_message TEXT
);

-- Environment variables
CREATE TABLE deployment_env_vars (
  id INTEGER PRIMARY KEY,
  target_id INTEGER,
  key TEXT,
  value TEXT,
  source TEXT  -- 'dns', 'secrets', 'manual'
);

-- Query deployment history
SELECT
  d.id,
  t.name as target,
  d.status,
  d.started_at,
  (julianday(d.completed_at) - julianday(d.started_at)) * 86400 as duration_seconds
FROM deployments d
JOIN deployment_targets t ON d.target_id = t.id
WHERE d.project_id = (SELECT id FROM projects WHERE slug = 'myapp')
ORDER BY d.started_at DESC;
```

---

**Next:** [DNS.md](DNS.md), [SECURITY.md](SECURITY.md)


<!-- AUTO-GENERATED-INDEX:START -->
## Related Documentation

### Other

- **[Backup & Restore](../docs/BACKUP.md)**
- **[Error Handling Migration Guide](../docs/ERROR_HANDLING_MIGRATION.md)**
- **[Multi-Key Secret Management](../docs/MULTI_KEY_SECRET_MANAGEMENT.md)**

### Api

- **[TempleDB MCP Tools - Quick Reference](../docs/MCP_QUICK_REFERENCE.md)**

### Architecture

- **[Phase 2: Hierarchical Agent Dispatch - Design Document](../docs/phases/PHASE_2_DESIGN.md)**

### Deployment

- **[TempleDB Deployment Architecture Review (v2)](../docs/DEPLOYMENT_ARCHITECTURE_V2.md)**
- **[Phase 2.3 Complete: Safe Deployment Workflow](../docs/phases/PHASE_2_3_COMPLETE.md)**

### Setup

- **[Schema Consolidation Summary](../docs/fixes/SCHEMA_CONSOLIDATION.md)**

<!-- AUTO-GENERATED-INDEX:END -->
