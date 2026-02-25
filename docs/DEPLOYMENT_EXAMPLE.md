# Deploying Complex Applications with TempleDB

Complete step-by-step guide to deploying multi-tier applications with database migrations, build steps, and multiple environments using TempleDB's deployment system.

---

## Overview

This guide demonstrates deploying a complex application tracked in TempleDB with:
- Multiple files (hundreds or thousands of lines of code)
- Database migrations (schema changes)
- Build system (TypeScript, webpack, or other compilation)
- Edge functions or serverless components
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
./templedb project show myproject
```

### Deployment Targets

A typical multi-environment setup has 3 deployment targets:

| Target | Host | Provider | Purpose |
|--------|------|----------|---------|
| **local** | localhost:5432 | PostgreSQL | Local development |
| **staging** | staging.example.com | Supabase/AWS/etc | Pre-production testing |
| **production** | db.example.com | Supabase/AWS/etc | Live production |

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
./templedb secret init myproject --age-recipient "$AGE_KEY"

# 4. Edit secrets and add required variables
./templedb secret edit myproject
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
./templedb secret init myproject --age-recipient "$YUBIKEY"

# With backup:
./templedb secret init myproject --age-recipient "$YUBIKEY,$BACKUP"

# 5. Edit secrets
./templedb secret edit myproject
# (Will prompt for PIN)
```

### Required Environment Variables

When editing secrets, add these required variables:

```yaml
env:
  # Database connection (required for all deployments)
  DATABASE_URL: "postgresql://user:pass@host:5432/dbname"

  # Cloud provider specific (for staging/production)
  SUPABASE_URL: "https://xxxxx.supabase.co"
  SUPABASE_ANON_KEY: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  SUPABASE_SERVICE_ROLE_KEY: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."

  # Or AWS credentials
  AWS_ACCESS_KEY_ID: "AKIA..."
  AWS_SECRET_ACCESS_KEY: "..."
  AWS_REGION: "us-east-1"

  # Optional: Third-party API keys
  TWILIO_ACCOUNT_SID: "ACxxxxx..."
  TWILIO_AUTH_TOKEN: "xxxxx..."
  STRIPE_SECRET_KEY: "sk_test_xxxxx..."
  SENDGRID_API_KEY: "SG.xxxxx..."
```

Save and exit your editor (`:wq` in vim, `Ctrl+X` in nano).

### Verify Secrets

```bash
# Export secrets to verify (doesn't show on screen by default)
./templedb secret export myproject --format shell

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
  --host staging.example.com \
  --provider supabase

# Update production target
./templedb target update production \
  --host db.example.com \
  --provider supabase
```

---

## Test Deployment (Dry Run)

**Always dry-run first!** This shows what will be deployed without making changes.

### Dry Run to Staging

```bash
./templedb deploy run myproject --target staging --dry-run
```

**Expected Output:**
```
🚀 Deploying myproject to staging...
📋 DRY RUN - No actual deployment will occur

📦 Exporting project from TempleDB...
✓ Exported to /tmp/templedb_deploy_myproject/myproject.cathedral

🔧 Reconstructing project from cathedral package...
   Reconstructed 1357 files
✓ Project reconstructed to /tmp/templedb_deploy_myproject/working

📋 Found deployment configuration - using orchestrator

🚀 Deploying myproject to staging
📋 DRY RUN - No actual changes will be made

🔧 [1] Deploying: migrations
   Found 8 pending migrations
      [DRY RUN] Would apply: migrations/001_create_users_table.sql
      [DRY RUN] Would apply: migrations/002_create_orders_table.sql
      [DRY RUN] Would apply: migrations/003_add_payment_methods.sql
      [DRY RUN] Would apply: migrations/004_create_indexes.sql
      [DRY RUN] Would apply: migrations/005_add_audit_log.sql
      [DRY RUN] Would apply: migrations/006_add_webhooks_table.sql
      [DRY RUN] Would apply: migrations/007_add_rate_limiting.sql
      [DRY RUN] Would apply: migrations/008_create_materialized_views.sql
   ✅ Completed in 0ms

🔧 [2] Deploying: typescript_build
   [DRY RUN] Would run build: npm run build
   ⏭️  Skipped: Dry run

✅ Deployment complete! (0.0s total)
```

### Understanding the Output

**Group 1: migrations**
- SQL migrations will be applied to database
- Creates tables, views, indexes, and schema changes
- **Critical:** These are applied in order and cannot be rolled back automatically

**Group 2: typescript_build**
- Compiles TypeScript to JavaScript (or other build processes)
- Runs `npm run build` or equivalent
- Required before application can run

### Skip Validation (for testing)

If you're not ready to configure secrets:

```bash
./templedb deploy run myproject --target staging --dry-run --skip-validation
```

---

## Deploy to Staging

Once dry-run looks good, deploy for real!

### Step 1: Ensure Secrets Are Configured

```bash
# Test that secrets can be decrypted
./templedb secret export myproject --format shell > /dev/null
echo "✓ Secrets OK"
```

**With Yubikey:** Make sure your Yubikey is inserted and you know the PIN.

### Step 2: Deploy

```bash
./templedb deploy run myproject --target staging
```

**You will be prompted:**
- For Yubikey PIN (if using Yubikey)
- To confirm deployment (unless you add `--yes`)

### Step 3: Watch the Deployment

**Expected Output:**
```
🚀 Deploying myproject to staging...

📦 Exporting project from TempleDB...
✓ Exported to /tmp/templedb_deploy_myproject/myproject.cathedral

🔧 Reconstructing project from cathedral package...
   Reconstructed 1357 files
✓ Project reconstructed to /tmp/templedb_deploy_myproject/working

🚀 Deploying myproject to staging

🔧 [1] Deploying: migrations
   Running pre-deploy hooks...
      ✓ Verified psql is available
   Applying 8 pending migrations...
      ✓ Applied: migrations/001_create_users_table.sql (127ms)
      ✓ Applied: migrations/002_create_orders_table.sql (43ms)
      ✓ Applied: migrations/003_add_payment_methods.sql (89ms)
      ✓ Applied: migrations/004_create_indexes.sql (156ms)
      ✓ Applied: migrations/005_add_audit_log.sql (234ms)
      ✓ Applied: migrations/006_add_webhooks_table.sql (91ms)
      ✓ Applied: migrations/007_add_rate_limiting.sql (312ms)
      ✓ Applied: migrations/008_create_materialized_views.sql (67ms)
   Running post-deploy hooks...
      ✓ Verified all migrations applied
   ✅ Completed in 1.2s

🔧 [2] Deploying: typescript_build
   Running build: npm run build
      > myproject@1.0.0 build
      > tsc && vite build

      vite v4.0.0 building for production...
      ✓ 127 modules transformed.
      dist/index.html                   0.45 kB
      dist/assets/index-abc123.js     432.18 kB │ gzip: 142.35 kB
      ✓ built in 5.43s
   ✅ Completed in 5.5s

✅ Deployment complete! (6.7s total)

🎯 Deployed to: https://staging.example.com
```

### Step 4: Verify Deployment

```bash
# Check deployment status
./templedb deploy status myproject

# Test the staging site
curl https://staging.example.com/health
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
- [ ] Performance acceptable
- [ ] No errors in logs
- [ ] Team approved for production
- [ ] Rollback plan documented

### Production Deployment

```bash
# 1. Final dry-run to production
./templedb deploy run myproject --target production --dry-run

# 2. Review what will be deployed
# Make sure migration list matches what you tested on staging

# 3. Deploy to production
./templedb deploy run myproject --target production

# 4. Monitor closely
watch -n 5 'curl -s https://db.example.com/health'
```

### Post-Deployment Verification

```bash
# Check deployment status
./templedb deploy status myproject

# Verify migrations applied
psql $PRODUCTION_DATABASE_URL -c "SELECT version, description, applied_at FROM schema_migrations ORDER BY version DESC LIMIT 10;"

# Check application health
curl https://db.example.com/health
curl https://db.example.com/api/status

# Monitor logs (if available)
# For Supabase:
# - Check Supabase dashboard logs
# - Monitor edge function logs
# - Check database performance

# For AWS:
# - Check CloudWatch logs
# - Monitor Lambda function metrics
# - Check RDS performance
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
\i migrations/rollback/008_rollback_materialized_views.sql
\i migrations/rollback/007_rollback_rate_limiting.sql
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
./templedb project sync myproject
./templedb deploy run myproject --target production
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

./templedb secret init myproject --profile ci --age-recipient "$CI_KEY"

# 2. Store CI key in GitHub Secrets / GitLab CI Variables
# Variable name: TEMPLEDB_AGE_KEY_FILE
# Value: <contents of ci-key.txt>

# 3. In CI pipeline:
export TEMPLEDB_AGE_KEY_FILE=/tmp/ci-key.txt
echo "$TEMPLEDB_AGE_KEY" > /tmp/ci-key.txt

./templedb deploy run myproject --profile ci --target staging --yes
```

### Staged Rollout

Deploy incrementally:

```bash
# 1. Deploy to staging
./templedb deploy run myproject --target staging

# 2. Test for 24-48 hours
# Monitor metrics, errors, user feedback

# 3. Deploy to production during low-traffic window
# Early morning or weekend
./templedb deploy run myproject --target production
```

### Blue-Green Deployment

For zero-downtime deployments:

```bash
# 1. Setup blue and green targets
./templedb target add blue --host blue.example.com --provider supabase
./templedb target add green --host green.example.com --provider supabase

# 2. Deploy to inactive target (green)
./templedb deploy run myproject --target green

# 3. Test green
curl https://green.example.com/health

# 4. Switch DNS/load balancer to green
# (Manual step or via DNS provider API)

# 5. Blue becomes the standby for next deployment
```

---

## Monitoring Deployment

### Real-Time Monitoring

```bash
# Watch deployment progress
./templedb deploy run myproject --target staging | tee deploy.log

# Monitor logs in another terminal
tail -f ~/.local/share/templedb/logs/backup.log

# Watch application health
watch -n 2 'curl -s https://staging.example.com/health | jq'
```

### Post-Deployment Health Checks

```bash
# Check database connection
psql $DATABASE_URL -c "SELECT NOW();"

# Check migrations applied
psql $DATABASE_URL -c "SELECT COUNT(*) FROM schema_migrations;"

# Test API endpoints
curl https://staging.example.com/api/health
curl https://staging.example.com/api/users
curl https://staging.example.com/api/orders

# Check serverless functions (if using)
curl https://staging.example.com/functions/v1/webhook-handler
```

---

## Troubleshooting

### Error: "No secrets found"

```bash
# Check if secrets exist
./templedb secret export myproject --format yaml

# If not found, initialize
./templedb secret init myproject --age-recipient <your-key>
./templedb secret edit myproject
```

### Error: "Missing required environment variables: DATABASE_URL"

```bash
# Edit secrets and add DATABASE_URL
./templedb secret edit myproject

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
./templedb deploy run myproject --target staging
```

### Error: "npm run build failed"

```bash
# Check Node.js version
node --version  # Should match project requirements

# Install dependencies
cd /tmp/templedb_deploy_myproject/working
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
./templedb deploy run myproject --target staging
```

---

## Advanced Configuration

### Skip Deployment Groups

If you only want to deploy certain parts:

```bash
# Skip build step (if already built)
./templedb deploy run myproject --target staging --skip-group typescript_build

# Deploy only migrations
./templedb deploy run myproject --target staging --skip-group typescript_build
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

  - name: serverless_functions
    order: 3
    commands:
      - supabase functions deploy --all
      # Or for AWS Lambda:
      # - aws lambda update-function-code --function-name myfunction

  - name: post_deploy
    order: 4
    commands:
      - curl -X POST https://api.example.com/deploy-webhook
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

**Deploying complex applications with TempleDB:**

1. **Setup Secrets** → `./templedb secret init` + `edit`
2. **Dry Run** → `--dry-run --target staging`
3. **Deploy Staging** → `--target staging`
4. **Test Thoroughly** → Verify all features work
5. **Deploy Production** → `--target production`
6. **Monitor** → Check health, logs, metrics

**Key Commands:**
```bash
# Dry run
./templedb deploy run myproject --target staging --dry-run

# Deploy staging
./templedb deploy run myproject --target staging

# Deploy production
./templedb deploy run myproject --target production

# Check status
./templedb deploy status myproject
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
