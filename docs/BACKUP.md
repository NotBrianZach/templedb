# Backup & Restore

Backup TempleDB database to cloud storage (Google Drive, S3, Backblaze) or local files. Yubikey hardware backup supported.

## Quick Start

```bash
# Local backup
templedb backup local ~/backups/templedb-$(date +%Y%m%d).sqlite

# Cloud backup (Google Cloud Storage)
templedb backup cloud push --provider gcs

# Restore from local backup
templedb backup restore ~/backups/templedb-20260311.sqlite

# Restore from cloud
templedb backup cloud pull --provider gcs --backup-id <backup-id>
```

## Local Backup

### Using TempleDB CLI

```bash
# Create local backup (auto-generated filename)
templedb backup local

# Create backup with specific path
templedb backup local ~/backups/templedb-$(date +%Y%m%d).sqlite

# Restore from backup
templedb backup restore ~/backups/templedb-20260311.sqlite
```

### Manual Backup

```bash
# Manual copy
cp ~/.local/share/templedb/templedb.sqlite ~/backups/

# With timestamp
cp ~/.local/share/templedb/templedb.sqlite ~/backups/templedb-$(date +%Y%m%d-%H%M%S).sqlite

# Automated (cron)
0 2 * * * /path/to/templedb backup local ~/backups/templedb-$(date +\%Y\%m\%d).sqlite
```

**Database location:** `~/.local/share/templedb/templedb.sqlite`

## Cloud Backup

TempleDB supports multiple cloud storage providers for automated backups:
- **Google Cloud Storage (GCS)** - Recommended, highly reliable, generous free tier
- **Google Drive** - OAuth-based, easy setup, good for personal use
- **AWS S3** - Enterprise-grade, global availability
- **Backblaze B2** - Cost-effective alternative to S3

### Google Cloud Storage (Recommended)

**Best for:** Production environments, automated backups, cost-sensitive deployments

```bash
# Initialize GCS backup setup
templedb backup cloud init gcs

# Test connection
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt templedb backup cloud test \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json

# Push backup to cloud
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt templedb backup cloud push \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json

# List cloud backups
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt templedb backup cloud status \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json

# Pull backup from cloud
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt templedb backup cloud pull \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json \
  --backup-id templedb-backups/templedb_backup_YYYYMMDD_HHMMSS.sqlite

# Cleanup old backups
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt templedb backup cloud cleanup \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json
```

**Setup:** See [GCS_BACKUP_SETUP.md](GCS_BACKUP_SETUP.md) for complete setup guide.

**What's uploaded:**
- Database file (SQLite)
- Automatic compression
- Metadata (timestamp, size, checksum)
- Stored in `gs://your-bucket/templedb-backups/`

**Cost:** ~$0.12/month for 200MB database with 30-day retention (within GCP free tier)

### Google Drive

**Best for:** Personal use, simple OAuth-based setup

```bash
# One-time setup
templedb backup cloud init google-drive
# Opens browser for OAuth, saves credentials encrypted in database

# Upload backup
templedb backup cloud push --provider google-drive

# List backups
templedb backup cloud status --provider google-drive

# Restore
templedb backup cloud pull --provider google-drive --backup-id <id>

# Automated (cron)
0 3 * * * /path/to/templedb backup cloud push --provider google-drive
```

### AWS S3

**Best for:** Enterprise deployments, multi-region replication

```bash
# Setup
templedb backup cloud init --provider s3 \
  --bucket my-backups \
  --region us-east-1 \
  --access-key $AWS_ACCESS_KEY \
  --secret-key $AWS_SECRET_KEY

# Upload
templedb backup cloud push --provider s3

# List
templedb backup cloud status --provider s3

# Restore
templedb backup cloud pull --provider s3 --backup-id <id>
```

### Backblaze B2

**Best for:** Cost-effective cloud storage (~1/4 the price of S3)

```bash
# Setup
templedb backup cloud init --provider backblaze \
  --bucket my-backups \
  --key-id $B2_KEY_ID \
  --app-key $B2_APP_KEY

# Upload/list/restore same as S3
templedb backup cloud push --provider backblaze
```

## Encryption

**Encrypt backups with age:**

```bash
# Generate backup key
age-keygen -o ~/.config/templedb/backup-key.txt

# Upload encrypted
templedb backup upload --provider google-drive --encrypt --age-key ~/.config/templedb/backup-key.txt

# Download + decrypt
templedb backup download --provider google-drive --backup-id <id> \
  --decrypt --age-key ~/.config/templedb/backup-key.txt \
  --output ~/restore.sqlite
```

**Encryption happens before upload:**
1. Compress database (gzip)
2. Encrypt with age
3. Upload encrypted file
4. Store encryption metadata in database

## Yubikey Backup

Hardware-secured backups using Yubikey + age-plugin-yubikey.

```bash
# Setup Yubikey
age-plugin-yubikey --generate
# Stores key on Yubikey, outputs recipient public key

# Backup encrypted to Yubikey
templedb backup upload --provider google-drive \
  --encrypt --yubikey --age-recipient <yubikey-public-key>

# Restore (requires Yubikey inserted)
templedb backup download --provider google-drive --backup-id <id> \
  --decrypt --yubikey \
  --output ~/restore.sqlite
# Prompts for Yubikey PIN
```

**Security:**
- Private key never leaves Yubikey
- Requires physical device + PIN
- Decrypt fails without Yubikey

See [advanced/YUBIKEY.md](advanced/YUBIKEY.md) for full Yubikey setup.

## Restore

```bash
# From local file
templedb backup restore ~/backups/templedb-20260311.sqlite

# From cloud (downloads first)
templedb backup restore --provider google-drive --backup-id <id>

# Restore to different location
templedb backup restore ~/backups/old.sqlite --output ~/test-restore.sqlite
```

**What restore does:**
1. Validates backup integrity (checksum)
2. Stops all database connections
3. Backs up current database to `templedb.sqlite.before-restore`
4. Replaces database with backup
5. Verifies restored database (integrity check)
6. Restarts database connections

**Rollback if restore fails:**
```bash
mv ~/.local/share/templedb/templedb.sqlite.before-restore \
   ~/.local/share/templedb/templedb.sqlite
```

## Automated Backups

### Cron (Linux/macOS)

```bash
# Edit crontab
crontab -e

# Daily GCS backup at 3 AM
0 3 * * * TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt /path/to/templedb backup cloud push --provider gcs --config ~/.config/templedb/gcs_config.json

# Weekly Google Drive backup (Sundays at 2 AM)
0 2 * * 0 /path/to/templedb backup cloud push --provider google-drive

# Hourly backup for production (S3)
0 * * * * /path/to/templedb backup cloud push --provider s3 --config ~/.config/templedb/s3_config.json
```

### systemd Timer (Linux)

```ini
# /etc/systemd/user/templedb-backup.service
[Unit]
Description=TempleDB Cloud Backup

[Service]
Type=oneshot
Environment="TEMPLEDB_AGE_KEY_FILE=%h/.age/key.txt"
ExecStart=/usr/local/bin/templedb backup cloud push \
  --provider gcs \
  --config %h/.config/templedb/gcs_config.json
```

```ini
# /etc/systemd/user/templedb-backup.timer
[Unit]
Description=TempleDB Backup Timer

[Timer]
OnCalendar=daily
OnCalendar=03:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl --user enable templedb-backup.timer
systemctl --user start templedb-backup.timer
systemctl --user status templedb-backup.timer
```

### Manual Script

```bash
#!/bin/bash
# backup.sh - Manual backup with retention

export TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt
BACKUP_DIR=~/backups/templedb
mkdir -p $BACKUP_DIR

# Backup with timestamp
DATE=$(date +%Y%m%d-%H%M%S)
cp ~/.local/share/templedb/templedb.sqlite $BACKUP_DIR/templedb-$DATE.sqlite

# Upload to cloud (GCS)
/path/to/templedb backup cloud push \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json

# Keep only last 30 days locally
find $BACKUP_DIR -name "templedb-*.sqlite" -mtime +30 -delete

echo "Backup complete: templedb-$DATE.sqlite"
```

## Backup Verification

```bash
# List backups (includes size and timestamp)
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt templedb backup cloud status \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json

# Verify with gcloud (for GCS)
gcloud storage ls -L gs://your-bucket/templedb-backups/

# Database integrity check (local)
sqlite3 ~/.local/share/templedb/templedb.sqlite "PRAGMA integrity_check;"

# Test restore to verify backup is valid
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt templedb backup cloud pull \
  --provider gcs \
  --backup-id <id> \
  --db-path /tmp/test-restore.sqlite
sqlite3 /tmp/test-restore.sqlite "PRAGMA integrity_check;"
```

## Retention Policies

**Cloud providers:**
```bash
# Automatic cleanup (removes old backups based on retention policy)
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt templedb backup cloud cleanup \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json

# Manual deletion (GCS)
gcloud storage rm gs://your-bucket/templedb-backups/old_backup.sqlite
```

**Local cleanup:**
```bash
# Keep last 7 days
find ~/backups -name "templedb-*.sqlite" -mtime +7 -delete

# Keep only 10 most recent
ls -t ~/backups/templedb-*.sqlite | tail -n +11 | xargs rm
```

## Disaster Recovery

**Complete restore from cloud:**

```bash
# 1. Fresh install
git clone git@github.com:user/templedb.git
cd templedb
nix develop  # or ./install.sh

# 2. Set up age key (must be the same key used for backups)
mkdir -p ~/.age
# Copy your age key to ~/.age/key.txt

# 3. Create GCS config
mkdir -p ~/.config/templedb
cat > ~/.config/templedb/gcs_config.json << EOF
{
  "bucket_name": "your-bucket-name",
  "project_id": "your-project-id"
}
EOF

# 4. List available backups
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt templedb backup cloud status \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json

# 5. Restore latest backup
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt templedb backup cloud pull \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json \
  --backup-id templedb-backups/templedb_backup_YYYYMMDD_HHMMSS.sqlite

# 6. Verify
templedb status
templedb project list
```

**Partial restore (specific projects):**

```bash
# Export project from backup
sqlite3 ~/backups/old.sqlite <<SQL
.mode insert projects
SELECT * FROM projects WHERE slug = 'myapp';
.mode insert project_files
SELECT * FROM project_files WHERE project_id = (SELECT id FROM projects WHERE slug = 'myapp');
SQL

# Import to current database
sqlite3 ~/.local/share/templedb/templedb.sqlite < exported.sql
```

## Database Size Management

```bash
# Check database size
du -h ~/.local/share/templedb/templedb.sqlite

# Vacuum (reclaim space)
sqlite3 ~/.local/share/templedb/templedb.sqlite "VACUUM;"

# Analyze (optimize queries)
sqlite3 ~/.local/share/templedb/templedb.sqlite "ANALYZE;"

# Check largest tables
sqlite3 ~/.local/share/templedb/templedb.sqlite <<SQL
SELECT name, SUM(pgsize) as size
FROM dbstat
GROUP BY name
ORDER BY size DESC
LIMIT 10;
SQL
```

## Commands Reference

```bash
# Local backup
cp ~/.local/share/templedb/templedb.sqlite ~/backups/

# List available cloud providers
templedb backup cloud providers

# Test cloud connection
templedb backup cloud test --provider <provider> [--config <file>]

# Create cloud backup
templedb backup cloud push --provider <provider> [--config <file>]

# List cloud backups
templedb backup cloud status --provider <provider> [--config <file>]

# Restore from cloud
templedb backup cloud pull --provider <provider> --backup-id <id> [--config <file>]

# Cleanup old backups
templedb backup cloud cleanup --provider <provider> [--config <file>]

# Local restore
templedb backup restore <file>
```

**Environment variables:**
- `TEMPLEDB_AGE_KEY_FILE` - Path to age identity file (default: `~/.config/sops/age/keys.txt`)
- `SOPS_AGE_KEY_FILE` - Alternative age key path

## Database Schema

```sql
-- Backup providers
CREATE TABLE backup_providers (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE,          -- 'google-drive', 's3', 'backblaze'
  credentials_encrypted TEXT,
  config JSON
);

-- Backup history
CREATE TABLE backups (
  id INTEGER PRIMARY KEY,
  provider_id INTEGER,
  backup_id TEXT UNIQUE,     -- Provider-specific ID
  file_size INTEGER,
  checksum TEXT,
  encrypted BOOLEAN,
  created_at TIMESTAMP
);

-- Query backup history
SELECT
  b.backup_id,
  p.name as provider,
  b.file_size / 1024 / 1024 as size_mb,
  b.encrypted,
  b.created_at
FROM backups b
JOIN backup_providers p ON b.provider_id = p.id
ORDER BY b.created_at DESC;
```

## Troubleshooting

**"GCS credentials not found in file or TempleDB secrets"**
```bash
# Verify secret exists
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT secret_name FROM secret_blobs WHERE secret_name = 'gcs_service_account'"

# Should return: gcs_service_account

# If missing, see GCS_BACKUP_SETUP.md for credential storage
```

**"TEMPLEDB_AGE_KEY_FILE not set"**
```bash
# Set environment variable
export TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt

# Or create symlink to default location
mkdir -p ~/.config/sops/age
ln -s ~/.age/key.txt ~/.config/sops/age/keys.txt
```

**"Permission denied on bucket" (GCS)**
```bash
# Check service account has permissions
gcloud storage buckets get-iam-policy gs://YOUR_BUCKET_NAME

# Re-grant permissions
gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET_NAME \
  --member="serviceAccount:templedb-backup@PROJECT.iam.gserviceaccount.com" \
  --role="roles/storage.admin"
```

**"Provider not configured"**
```bash
templedb backup cloud init --provider google-drive
```

**"OAuth failed" (Google Drive)**
```bash
# Revoke and re-authorize
templedb backup cloud init --provider google-drive --force
```

**"Restore failed: checksum mismatch"**
```bash
# Backup file corrupted, try different backup
templedb backup cloud status --provider gcs --config ~/.config/templedb/gcs_config.json
templedb backup cloud pull --provider gcs --backup-id <different-id>
```

**"Database locked during backup"**
```bash
# Close all connections
templedb status
# Kill any running processes
lsof ~/.local/share/templedb/templedb.sqlite
# Try again
templedb backup cloud push --provider gcs --config ~/.config/templedb/gcs_config.json
```

**"Billing account disabled" (GCS)**
```bash
# Enable billing at: https://console.cloud.google.com/billing
# Link billing account to your project
```

---

**Related Documentation:**
- [GCS_BACKUP_SETUP.md](GCS_BACKUP_SETUP.md) - Complete Google Cloud Storage setup guide
- [SECURITY_THREAT_MODEL.md](SECURITY_THREAT_MODEL.md) - Security best practices
- [MULTI_KEY_SECRET_MANAGEMENT.md](MULTI_KEY_SECRET_MANAGEMENT.md) - Multi-key encryption for backups


<!-- AUTO-GENERATED-INDEX:START -->
## Related Documentation

### Other

- **[Logging Migration Guide](../docs/implementation/LOGGING_MIGRATION_GUIDE.md)**

### Architecture

- **[Phase 2: Hierarchical Agent Dispatch - Design Document](../docs/phases/PHASE_2_DESIGN.md)**
- **[Phase 2.2 Complete: MCP Workflow Tools](../docs/phases/PHASE_2_2_COMPLETE.md)**
- **[Project Deletion Bug Fix](../docs/fixes/PROJECT_DELETION_FIX.md)**
- **[CathedralDB Design Document](../docs/advanced/CATHEDRAL.md)**

### Deployment

- **[Phase 2.3 Complete: Safe Deployment Workflow](../docs/phases/PHASE_2_3_COMPLETE.md)**
- **[Phase 3: Steam Game Deployment (IMPLEMENTED)](../docs/PHASE_3_STEAM_DEPLOYMENT.md)**
- **[TempleDB Performance Optimizations](../docs/advanced/ADVANCED.md)**

<!-- AUTO-GENERATED-INDEX:END -->
