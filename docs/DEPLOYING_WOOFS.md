# Deploying Woofs Projects with TempleDB

Complete step-by-step guide to deploying the woofs_projects application using TempleDB's deployment system.

---

## Overview

**woofs_projects** is tracked in TempleDB with:
- 455 files (355,407 lines of code)
- 8 database migrations
- 13 edge functions
- TypeScript build system
- Multiple deployment targets (local, staging, production)

This guide walks through the entire deployment process from secrets setup to production deployment.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Setup Secrets](#setup-secrets)
3. [Configure Deployment Targets](#configure-deployment-targets)
4. [Test Deployment (Dry Run)](#test-deployment-dry-run)
5. [Deploy to Staging](#deploy-to-staging)
6. [Deploy to Production](#deploy-to-production)
7. [Rollback](#rollback)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Tools

```bash
# Check TempleDB is installed
./templedb --version

# Check age encryption is available
age --version

# Optional: Yubikey support
age-plugin-yubikey --version

# Check project is synced
./templedb project show woofs_projects
```

### Deployment Targets

Your woofs_projects has 3 deployment targets:

| Target | Host | Provider | Purpose |
|--------|------|----------|---------|
| **local** | localhost:5432 | PostgreSQL | Local development |
| **staging** | staging.woofs.com | Supabase | Pre-production testing |
| **production** | db.woofs.com | Supabase | Live production |

View targets:
```bash
./templedb target list
```

---

## Setup Secrets

Secrets are required for deployment. You have two options:

### Option 1: Standard Age Encryption (Fastest)

```bash
# 1. Generate age key
mkdir -p ~/.config/age
age-keygen -o ~/.config/age/keys.txt

# 2. Get your public key
AGE_KEY=$(age-keygen -y ~/.config/age/keys.txt)
echo "Your age key: $AGE_KEY"

# 3. Initialize secrets
./templedb secret init woofs_projects --age-recipient "$AGE_KEY"

# 4. Edit secrets and add required variables
./templedb secret edit woofs_projects
```

### Option 2: Yubikey (Recommended for Production)

```bash
# 1. Setup Yubikey (interactive)
./scripts/setup_yubikey_secrets.sh

# 2. Get Yubikey recipient
YUBIKEY=$(age-plugin-yubikey --identity | grep age1yubikey)

# 3. Optional: Setup backup Yubikey
# Switch Yubikeys and repeat
BACKUP=$(age-plugin-yubikey --identity | grep age1yubikey)

# 4. Initialize with recipient(s)
# Single Yubikey:
./templedb secret init woofs_projects --age-recipient "$YUBIKEY"

# With backup:
./templedb secret init woofs_projects --age-recipient "$YUBIKEY,$BACKUP"

# 5. Edit secrets
./templedb secret edit woofs_projects
# (Will prompt for PIN)
```

### Required Environment Variables

When editing secrets, add these required variables:

```yaml
env:
  # Database connection (required for all deployments)
  DATABASE_URL: "postgresql://user:pass@host:5432/dbname"

  # Supabase specific (for staging/production)
  SUPABASE_URL: "https://xxxxx.supabase.co"
  SUPABASE_ANON_KEY: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  SUPABASE_SERVICE_ROLE_KEY: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

  # Optional: Additional secrets
  TWILIO_ACCOUNT_SID: "ACxxxxx..."
  TWILIO_AUTH_TOKEN: "xxxxx..."
  STRIPE_SECRET_KEY: "sk_test_xxxxx..."
```

Save and exit your editor (`:wq` in vim, `Ctrl+X` in nano).

### Verify Secrets

```bash
# Export secrets to verify (doesn't show on screen by default)
./templedb secret export woofs_projects --format shell

# Should show:
# export DATABASE_URL='postgresql://...'
# export SUPABASE_URL='https://...'
# etc.
```

---

## Configure Deployment Targets

Your deployment targets are already configured. To view or modify:

```bash
# View all targets
./templedb target list

# Show specific target details
./templedb target show local
./templedb target show staging
./templedb target show production
```

### Update Target (if needed)

```bash
# Update staging target
./templedb target update staging \
  --host staging.woofs.com \
  --provider supabase

# Update production target
./templedb target update production \
  --host db.woofs.com \
  --provider supabase
```

---

## Test Deployment (Dry Run)

**Always dry-run first!** This shows what will be deployed without making changes.

### Dry Run to Staging

```bash
./templedb deploy run woofs_projects --target staging --dry-run
```

**Expected Output:**
```
🚀 Deploying woofs_projects to staging...
📋 DRY RUN - No actual deployment will occur

📦 Exporting project from TempleDB...
✓ Exported to /tmp/templedb_deploy_woofs_projects/woofs_projects.cathedral

🔧 Reconstructing project from cathedral package...
   Reconstructed 1357 files
✓ Project reconstructed to /tmp/templedb_deploy_woofs_projects/working

📋 Found deployment configuration - using orchestrator

🚀 Deploying woofs_projects to staging
📋 DRY RUN - No actual changes will be made

🔧 [1] Deploying: migrations
   Found 8 pending migrations
      [DRY RUN] Would apply: migrations/001_add_phone_lookup_table.sql
      [DRY RUN] Would apply: migrations/002_create_client_context_view.sql
      [DRY RUN] Would apply: migrations/003_create_sync_state_table.sql
      [DRY RUN] Would apply: supabase/migrations/20240415000000_storage_rate_limit.sql
      [DRY RUN] Would apply: woofsDB/migrations/20251027_add_payment_tables.sql
      [DRY RUN] Would apply: woofsDB/migrations/20260223_add_sync_state_table.sql
      [DRY RUN] Would apply: woofsDB/migrations/20260224_add_online_booking_system.sql
      [DRY RUN] Would apply: woofsDB/verify_cell_phone_migration.sql
   ✅ Completed in 0ms

🔧 [2] Deploying: typescript_build
   [DRY RUN] Would run build: npm run build
   ⏭️  Skipped: Dry run

✅ Deployment complete! (0.0s total)
```

### Understanding the Output

**Group 1: migrations**
- 8 SQL migrations will be applied to database
- Creates tables, views, and schema changes
- **Critical:** These are applied in order and cannot be rolled back automatically

**Group 2: typescript_build**
- Compiles TypeScript to JavaScript
- Runs `npm run build`
- Required before edge functions can run

### Skip Validation (for testing)

If you're not ready to configure secrets:

```bash
./templedb deploy run woofs_projects --target staging --dry-run --skip-validation
```

---

## Deploy to Staging

Once dry-run looks good, deploy for real!

### Step 1: Ensure Secrets Are Configured

```bash
# Test that secrets can be decrypted
./templedb secret export woofs_projects --format shell > /dev/null
echo "✓ Secrets OK"
```

**With Yubikey:** Make sure your Yubikey is inserted and you know the PIN.

### Step 2: Deploy

```bash
./templedb deploy run woofs_projects --target staging
```

**You will be prompted:**
- For Yubikey PIN (if using Yubikey)
- To confirm deployment (unless you add `--yes`)

### Step 3: Watch the Deployment

**Expected Output:**
```
🚀 Deploying woofs_projects to staging...

📦 Exporting project from TempleDB...
✓ Exported to /tmp/templedb_deploy_woofs_projects/woofs_projects.cathedral

🔧 Reconstructing project from cathedral package...
   Reconstructed 1357 files
✓ Project reconstructed to /tmp/templedb_deploy_woofs_projects/working

🚀 Deploying woofs_projects to staging

🔧 [1] Deploying: migrations
   Running pre-deploy hooks...
      ✓ Verified psql is available
   Applying 8 pending migrations...
      ✓ Applied: migrations/001_add_phone_lookup_table.sql (127ms)
      ✓ Applied: migrations/002_create_client_context_view.sql (43ms)
      ✓ Applied: migrations/003_create_sync_state_table.sql (89ms)
      ✓ Applied: supabase/migrations/20240415000000_storage_rate_limit.sql (156ms)
      ✓ Applied: woofsDB/migrations/20251027_add_payment_tables.sql (234ms)
      ✓ Applied: woofsDB/migrations/20260223_add_sync_state_table.sql (91ms)
      ✓ Applied: woofsDB/migrations/20260224_add_online_booking_system.sql (312ms)
      ✓ Applied: woofsDB/verify_cell_phone_migration.sql (67ms)
   Running post-deploy hooks...
      ✓ Verified all migrations applied
   ✅ Completed in 1.2s

🔧 [2] Deploying: typescript_build
   Running build: npm run build
      > woofs@1.0.0 build
      > tsc && vite build

      vite v4.0.0 building for production...
      ✓ 127 modules transformed.
      dist/index.html                   0.45 kB
      dist/assets/index-abc123.js     432.18 kB │ gzip: 142.35 kB
      ✓ built in 5.43s
   ✅ Completed in 5.5s

✅ Deployment complete! (6.7s total)

🎯 Deployed to: https://staging.woofs.com
```

### Step 4: Verify Deployment

```bash
# Check deployment status
./templedb deploy status woofs_projects

# Test the staging site
curl https://staging.woofs.com/health
# Should return: {"status": "ok"}

# Check database migrations
psql $DATABASE_URL -c "SELECT * FROM schema_migrations ORDER BY version DESC LIMIT 5;"
```

---

## Deploy to Production

**⚠️ IMPORTANT:** Always deploy to staging first and test thoroughly!

### Pre-Production Checklist

- [ ] Staging deployment successful
- [ ] All features tested on staging
- [ ] Database migrations verified
- [ ] Edge functions working
- [ ] Performance acceptable
- [ ] No errors in logs
- [ ] Team approved for production

### Production Deployment

```bash
# 1. Final dry-run to production
./templedb deploy run woofs_projects --target production --dry-run

# 2. Review what will be deployed
# Make sure migration list matches what you tested on staging

# 3. Deploy to production
./templedb deploy run woofs_projects --target production

# 4. Monitor closely
watch -n 5 'curl -s https://db.woofs.com/health'
```

### Post-Deployment Verification

```bash
# Check deployment status
./templedb deploy status woofs_projects

# Verify migrations applied
psql $PRODUCTION_DATABASE_URL -c "SELECT version, description, applied_at FROM schema_migrations ORDER BY version DESC LIMIT 10;"

# Check application health
curl https://db.woofs.com/health
curl https://db.woofs.com/api/status

# Monitor logs (if available)
# For Supabase:
# - Check Supabase dashboard logs
# - Monitor edge function logs
# - Check database performance
```

---

## Rollback

If deployment fails or issues are found:

### Rollback Database Migrations

**⚠️ Warning:** Database rollbacks are NOT automatic. You must manually revert.

```bash
# 1. Connect to database
psql $DATABASE_URL

# 2. Check current migrations
SELECT * FROM schema_migrations ORDER BY version DESC LIMIT 10;

# 3. Run rollback migrations (if you have them)
\i migrations/rollback/008_rollback_online_booking.sql
\i migrations/rollback/007_rollback_sync_state.sql
# etc.

# 4. Or restore from backup
pg_restore --clean -d $DATABASE_URL /path/to/backup.sql
```

### Rollback Application Code

```bash
# 1. Find previous successful deployment
git log --oneline | grep "deploy"

# 2. Checkout previous version
git checkout <previous-commit>

# 3. Deploy previous version
./templedb project sync woofs_projects
./templedb deploy run woofs_projects --target production
```

### Rollback Strategy

**Best practice:** Keep database backups before major deployments

```bash
# Before production deployment
pg_dump $PRODUCTION_DATABASE_URL > backups/pre-deploy-$(date +%Y%m%d-%H%M%S).sql

# After testing, can delete old backups
ls -lh backups/
```

---

## Deployment Workflows

### Continuous Deployment

For automated deployments from CI/CD:

```bash
# 1. Setup CI secrets profile (file-based, not Yubikey)
age-keygen -o ~/.config/age/ci-key.txt
CI_KEY=$(age-keygen -y ~/.config/age/ci-key.txt)

./templedb secret init woofs_projects --profile ci --age-recipient "$CI_KEY"

# 2. Store CI key in GitHub Secrets / GitLab CI Variables
# Variable name: TEMPLEDB_AGE_KEY_FILE
# Value: <contents of ci-key.txt>

# 3. In CI pipeline:
export TEMPLEDB_AGE_KEY_FILE=/tmp/ci-key.txt
echo "$TEMPLEDB_AGE_KEY" > /tmp/ci-key.txt

./templedb deploy run woofs_projects --profile ci --target staging --yes
```

### Staged Rollout

Deploy incrementally:

```bash
# 1. Deploy to staging
./templedb deploy run woofs_projects --target staging

# 2. Test for 24-48 hours
# Monitor metrics, errors, user feedback

# 3. Deploy to production during low-traffic window
# Early morning or weekend
./templedb deploy run woofs_projects --target production
```

### Blue-Green Deployment

For zero-downtime deployments:

```bash
# 1. Setup blue and green targets
./templedb target add blue --host blue.woofs.com --provider supabase
./templedb target add green --host green.woofs.com --provider supabase

# 2. Deploy to inactive target (green)
./templedb deploy run woofs_projects --target green

# 3. Test green
curl https://green.woofs.com/health

# 4. Switch DNS/load balancer to green
# (Manual step or via DNS provider API)

# 5. Blue becomes the standby for next deployment
```

---

## Monitoring Deployment

### Real-Time Monitoring

```bash
# Watch deployment progress
./templedb deploy run woofs_projects --target staging | tee deploy.log

# Monitor logs in another terminal
tail -f ~/.local/share/templedb/logs/backup.log

# Watch application health
watch -n 2 'curl -s https://staging.woofs.com/health | jq'
```

### Post-Deployment Health Checks

```bash
# Check database connection
psql $DATABASE_URL -c "SELECT NOW();"

# Check migrations applied
psql $DATABASE_URL -c "SELECT COUNT(*) FROM schema_migrations;"

# Test API endpoints
curl https://staging.woofs.com/api/health
curl https://staging.woofs.com/api/bookings
curl https://staging.woofs.com/api/clients

# Check edge functions (if using Supabase)
curl https://staging.woofs.com/functions/v1/receiveDialpadSMSWebhook
```

---

## Troubleshooting

### Error: "No secrets found"

```bash
# Check if secrets exist
./templedb secret export woofs_projects --format yaml

# If not found, initialize
./templedb secret init woofs_projects --age-recipient <your-key>
./templedb secret edit woofs_projects
```

### Error: "Missing required environment variables: DATABASE_URL"

```bash
# Edit secrets and add DATABASE_URL
./templedb secret edit woofs_projects

# Add:
env:
  DATABASE_URL: "postgresql://user:pass@host:5432/dbname"
```

### Error: "Yubikey not found"

```bash
# Check Yubikey is detected
lsusb | grep -i yubi

# Check pcscd service
sudo systemctl status pcscd
sudo systemctl start pcscd

# Re-seat Yubikey (unplug and replug)
```

### Error: "age encryption failed"

```bash
# Check age is installed
age --version

# Check key file exists
ls -la ~/.config/age/keys.txt

# Or check Yubikey identity
age-plugin-yubikey --list
```

### Error: "Migration failed"

```bash
# Check database connection
psql $DATABASE_URL -c "SELECT 1;"

# Check which migrations are already applied
psql $DATABASE_URL -c "SELECT * FROM schema_migrations ORDER BY version;"

# Manually apply failed migration
psql $DATABASE_URL < migrations/XXX_failed_migration.sql

# Continue deployment
./templedb deploy run woofs_projects --target staging
```

### Error: "npm run build failed"

```bash
# Check Node.js version
node --version  # Should be 18+

# Install dependencies
cd /tmp/templedb_deploy_woofs_projects/working
npm install

# Try build manually
npm run build

# Check for TypeScript errors
npx tsc --noEmit
```

### Deployment Hangs

```bash
# Check what's running
ps aux | grep templedb

# Check tmp directory
ls -lh /tmp/templedb_deploy_*/

# Clean up old deployments
rm -rf /tmp/templedb_deploy_*

# Retry with verbose logging
export TEMPLEDB_LOG_LEVEL=DEBUG
./templedb deploy run woofs_projects --target staging
```

---

## Advanced Configuration

### Skip Deployment Groups

If you only want to deploy certain parts:

```bash
# Skip TypeScript build (if already built)
./templedb deploy run woofs_projects --target staging --skip-group typescript_build

# Deploy only migrations
./templedb deploy run woofs_projects --target staging --skip-group typescript_build
```

### Custom Deployment Scripts

Create custom deployment configuration:

```yaml
# deployment.yml in project root
groups:
  - name: migrations
    order: 1
    commands:
      - psql $DATABASE_URL < migrations/*.sql

  - name: build
    order: 2
    commands:
      - npm ci
      - npm run build

  - name: edge_functions
    order: 3
    commands:
      - supabase functions deploy --all

  - name: post_deploy
    order: 4
    commands:
      - curl -X POST https://api.woofs.com/deploy-webhook
```

---

## Best Practices

### Deployment Checklist

Before every deployment:

- [ ] Code reviewed and merged
- [ ] Tests passing locally
- [ ] Database backup created
- [ ] Secrets configured for target environment
- [ ] Dry-run completed successfully
- [ ] Low-traffic window scheduled (for production)
- [ ] Team notified
- [ ] Rollback plan documented

### Security Best Practices

- ✅ Use Yubikey for production secrets
- ✅ Rotate secrets quarterly
- ✅ Use separate secrets per environment
- ✅ Never commit secrets to git
- ✅ Audit secret access regularly
- ✅ Use least-privilege database credentials

### Performance Best Practices

- ✅ Test migrations on staging first
- ✅ Index new columns before deploying
- ✅ Run heavy migrations during low-traffic
- ✅ Monitor database performance during deployment
- ✅ Keep deployment packages small (exclude node_modules)

---

## Summary

**Deploying woofs_projects:**

1. **Setup Secrets** → `./templedb secret init` + `edit`
2. **Dry Run** → `--dry-run --target staging`
3. **Deploy Staging** → `--target staging`
4. **Test Thoroughly** → Verify all features work
5. **Deploy Production** → `--target production`
6. **Monitor** → Check health, logs, metrics

**Key Commands:**
```bash
# Dry run
./templedb deploy run woofs_projects --target staging --dry-run

# Deploy staging
./templedb deploy run woofs_projects --target staging

# Deploy production
./templedb deploy run woofs_projects --target production

# Check status
./templedb deploy status woofs_projects
```

---

## Need Help?

- 📖 **Deployment Documentation:** `docs/advanced/`
- 🔐 **Yubikey Guide:** `docs/advanced/YUBIKEY_SECRETS.md`
- 💾 **Backup Guide:** `docs/advanced/CLOUD_BACKUP.md`
- 🐛 **Troubleshooting:** See above section

---

*"Simplicity is the ultimate sophistication."* - Leonardo da Vinci

**TempleDB - Deploy with confidence** 🚀
