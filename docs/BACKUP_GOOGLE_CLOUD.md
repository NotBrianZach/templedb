# Backup TempleDB to Google Cloud Storage

Complete guide for backing up your TempleDB database to Google Cloud Storage (GCS).

## Prerequisites

### 1. Google Cloud Account
- Sign up at https://cloud.google.com
- Create a new project or use existing
- Enable billing (free tier available)

### 2. Install Google Cloud SDK

```bash
# On Linux/NixOS
# Option 1: Using Nix
nix-shell -p google-cloud-sdk

# Option 2: Using package manager
# Arch/Manjaro:
sudo pacman -S google-cloud-sdk

# Debian/Ubuntu:
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg | sudo apt-key add -
echo "deb https://packages.cloud.google.com/apt cloud-sdk main" | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list
sudo apt update && sudo apt install google-cloud-sdk

# On macOS:
brew install google-cloud-sdk
```

### 3. Authenticate

```bash
# Initialize and authenticate
gcloud init

# Login to your Google account
gcloud auth login

# Set default project
gcloud config set project YOUR_PROJECT_ID

# Create application default credentials for TempleDB
gcloud auth application-default login
```

## Setup Google Cloud Storage

### 1. Create a GCS Bucket

```bash
# Create bucket (choose unique name)
gsutil mb -p YOUR_PROJECT_ID -c STANDARD -l US gs://templedb-backups-YOURNAME

# Or use the web console:
# https://console.cloud.google.com/storage
```

**Bucket naming tips:**
- Must be globally unique
- Use lowercase letters, numbers, hyphens
- Example: `templedb-backups-john-2024`

**Recommended settings:**
- Location: Choose region near you (e.g., `us-central1`, `europe-west1`)
- Storage class: `STANDARD` for frequently accessed backups
- Public access: **Disabled** (keep private!)

### 2. Set Bucket Permissions

```bash
# Make sure you have access
gsutil iam ch user:YOUR_EMAIL@gmail.com:objectAdmin gs://YOUR-BUCKET-NAME

# Enable versioning (optional but recommended)
gsutil versioning set on gs://YOUR-BUCKET-NAME

# Set lifecycle policy for automatic cleanup of old backups (optional)
cat > lifecycle.json << 'EOF'
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {
          "age": 90,
          "matchesPrefix": ["templedb_backup_"]
        }
      }
    ]
  }
}
EOF

gsutil lifecycle set lifecycle.json gs://YOUR-BUCKET-NAME
```

## Initialize TempleDB Cloud Backup

### Option 1: Interactive Setup

```bash
./templedb backup cloud init gcs
```

This will guide you through creating the configuration file.

### Option 2: Manual Configuration

Create `~/.config/templedb/backup-gcs.json`:

```json
{
  "provider": "gcs",
  "bucket_name": "templedb-backups-yourname",
  "project_id": "your-project-id",
  "credentials_path": null,
  "prefix": "templedb/backups/",
  "compression": true,
  "encryption": false,
  "retention_days": 90,
  "enable_versioning": true
}
```

**Configuration options:**

- `bucket_name` (required): Your GCS bucket name
- `project_id` (optional): GCP project ID (uses default if not specified)
- `credentials_path` (optional): Path to service account JSON key file
  - If null, uses application default credentials from `gcloud auth`
- `prefix` (optional): Directory prefix within bucket (default: "")
- `compression` (optional): Compress before upload (default: true)
- `encryption` (optional): Client-side encryption (default: false)
- `retention_days` (optional): Auto-delete backups older than N days
- `enable_versioning` (optional): Use bucket versioning (default: true)

## Usage

### Create and Upload Backup

```bash
# Push backup to Google Cloud Storage
./templedb backup cloud push gcs --config ~/.config/templedb/backup-gcs.json

# Or if config is in default location:
./templedb backup cloud push gcs
```

**What happens:**
1. Creates compressed backup of TempleDB
2. Uploads to GCS bucket
3. Verifies upload integrity
4. Optionally deletes local backup copy

**Options:**
```bash
# Keep local backup copy after upload
./templedb backup cloud push gcs --keep-local

# Don't cleanup old backups
./templedb backup cloud push gcs --no-cleanup

# Specify custom database path
./templedb backup cloud push gcs --db-path /custom/path/db.sqlite
```

### List Cloud Backups

```bash
# See all backups in GCS
./templedb backup cloud status gcs --config ~/.config/templedb/backup-gcs.json
```

Example output:
```
☁️  Cloud Backups (Google Cloud Storage)
======================================================================

Found 5 backup(s):

  📄 templedb_backup_20240315_143022.sqlite.gz
     ID: gs://templedb-backups-john/templedb_backup_20240315_143022.sqlite.gz
     Size: 45.23 MB
     Created: 2024-03-15 14:30:22

  📄 templedb_backup_20240314_090015.sqlite.gz
     ID: gs://templedb-backups-john/templedb_backup_20240314_090015.sqlite.gz
     Size: 44.87 MB
     Created: 2024-03-14 09:00:15
```

### Restore from Cloud Backup

```bash
# List available backups first
./templedb backup cloud status gcs

# Restore specific backup
./templedb backup cloud pull gcs BACKUP_ID

# Example:
./templedb backup cloud pull gcs gs://templedb-backups-john/templedb_backup_20240315_143022.sqlite.gz
```

**Safety features:**
- Automatically creates local safety backup before restore
- Safety backup saved to: `~/.local/share/templedb/templedb.sqlite.before_restore_TIMESTAMP`
- Prompts for confirmation (unless `--yes` flag used)

### Test Connection

```bash
# Verify GCS configuration works
./templedb backup cloud test gcs --config ~/.config/templedb/backup-gcs.json
```

### Cleanup Old Backups

```bash
# Remove backups older than 30 days
./templedb backup cloud cleanup gcs --days 30

# Remove all but most recent N backups
./templedb backup cloud cleanup gcs --keep 10
```

## Automation

### Automatic Daily Backups (Cron)

Create a backup script:

```bash
cat > ~/bin/templedb-backup.sh << 'EOF'
#!/bin/bash

# TempleDB automatic backup to Google Cloud Storage

LOG_FILE="$HOME/.local/share/templedb/backup.log"
CONFIG="$HOME/.config/templedb/backup-gcs.json"

echo "[$(date)] Starting backup..." >> "$LOG_FILE"

if ~/templeDB/templedb backup cloud push gcs --config "$CONFIG" >> "$LOG_FILE" 2>&1; then
    echo "[$(date)] ✅ Backup successful" >> "$LOG_FILE"

    # Cleanup old backups
    ~/templeDB/templedb backup cloud cleanup gcs --days 30 --config "$CONFIG" >> "$LOG_FILE" 2>&1
else
    echo "[$(date)] ❌ Backup failed" >> "$LOG_FILE"

    # Optional: Send notification
    # notify-send "TempleDB Backup Failed" "Check $LOG_FILE for details"
fi
EOF

chmod +x ~/bin/templedb-backup.sh
```

Add to crontab:

```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * /home/YOUR_USERNAME/bin/templedb-backup.sh

# Or every 6 hours:
0 */6 * * * /home/YOUR_USERNAME/bin/templedb-backup.sh
```

### Automatic Backups (Systemd Timer)

For more control, use systemd:

```bash
# Create service
cat > ~/.config/systemd/user/templedb-backup.service << 'EOF'
[Unit]
Description=TempleDB Cloud Backup
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/home/YOUR_USERNAME/templeDB/templedb backup cloud push gcs --config %h/.config/templedb/backup-gcs.json
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
EOF

# Create timer
cat > ~/.config/systemd/user/templedb-backup.timer << 'EOF'
[Unit]
Description=TempleDB Cloud Backup Timer
Requires=templedb-backup.service

[Timer]
OnCalendar=daily
OnCalendar=02:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

# Enable and start timer
systemctl --user daemon-reload
systemctl --user enable templedb-backup.timer
systemctl --user start templedb-backup.timer

# Check status
systemctl --user status templedb-backup.timer
systemctl --user list-timers
```

## Security Best Practices

### 1. Use Service Account (Recommended for Automation)

```bash
# Create service account
gcloud iam service-accounts create templedb-backup \
    --display-name="TempleDB Backup Service Account"

# Grant storage permissions
gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
    --member="serviceAccount:templedb-backup@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
    --role="roles/storage.objectAdmin"

# Create and download key
gcloud iam service-accounts keys create ~/templedb-backup-key.json \
    --iam-account=templedb-backup@YOUR_PROJECT_ID.iam.gserviceaccount.com

# Secure the key file
chmod 600 ~/templedb-backup-key.json

# Update config to use service account
# Set "credentials_path": "/home/youruser/templedb-backup-key.json"
```

### 2. Enable Client-Side Encryption

Update config:
```json
{
  "encryption": true,
  "encryption_key_path": "~/.config/templedb/backup-encryption.key"
}
```

Generate encryption key:
```bash
openssl rand -base64 32 > ~/.config/templedb/backup-encryption.key
chmod 600 ~/.config/templedb/backup-encryption.key

# IMPORTANT: Store this key securely!
# If you lose it, you cannot decrypt your backups!
```

### 3. Bucket Security

```bash
# Disable public access (if not already)
gsutil iam ch -d allUsers:objectViewer gs://YOUR-BUCKET-NAME
gsutil iam ch -d allAuthenticatedUsers:objectViewer gs://YOUR-BUCKET-NAME

# Enable uniform bucket-level access
gsutil uniformbucketlevelaccess set on gs://YOUR-BUCKET-NAME

# Enable audit logging
# (Go to console: IAM & Admin > Audit Logs > Enable for Cloud Storage)
```

## Cost Estimation

Google Cloud Storage pricing (as of 2024):

**Storage costs:**
- Standard: $0.020/GB/month (first 1TB)
- Example: 1GB database = ~$0.02/month
- With daily backups (30 copies): ~$0.60/month

**Operations:**
- Class A operations (writes): $0.05 per 10,000
- Class B operations (reads): $0.004 per 10,000
- Daily backup: ~2 operations = negligible cost

**Network egress:**
- Free to upload (ingress is free)
- Restore/download: $0.12/GB (first 1TB)

**Versioning:**
- Each version counts as separate storage
- Use lifecycle policies to limit versions

**Total estimate for typical usage:**
- 1GB database, daily backups, 30-day retention: **~$1-2/month**
- 10GB database, daily backups, 90-day retention: **~$10-15/month**

## Monitoring

### View Backup Logs

```bash
# Systemd logs
journalctl --user -u templedb-backup.service -n 50

# Manual backup logs
tail -f ~/.local/share/templedb/backup.log
```

### Verify Backup Integrity

```bash
# Test restore without overwriting current DB
./templedb backup cloud pull gcs BACKUP_ID \
  --db-path /tmp/test-restore.sqlite \
  --no-safety-backup

# Verify database
sqlite3 /tmp/test-restore.sqlite "PRAGMA integrity_check"
```

### Set Up Alerts

Use Google Cloud Monitoring:

```bash
# Enable Cloud Monitoring API
gcloud services enable monitoring.googleapis.com

# Create alert for failed uploads (via console)
# Or use gcloud monitoring policies
```

## Troubleshooting

### Authentication Errors

```bash
# Re-authenticate
gcloud auth application-default login

# Check current credentials
gcloud auth list

# Test gsutil access
gsutil ls gs://YOUR-BUCKET-NAME
```

### Permission Denied

```bash
# Check your permissions
gsutil iam get gs://YOUR-BUCKET-NAME

# Grant yourself admin access
gsutil iam ch user:YOUR_EMAIL@gmail.com:objectAdmin gs://YOUR-BUCKET-NAME
```

### Slow Uploads

```bash
# Use gsutil directly for large databases
gzip -c ~/.local/share/templedb/templedb.sqlite | \
  gsutil -o GSUtil:parallel_composite_upload_threshold=150M \
         cp - gs://YOUR-BUCKET-NAME/manual-backup-$(date +%Y%m%d).sqlite.gz
```

### Bucket Not Found

```bash
# List your buckets
gsutil ls

# Create if missing
gsutil mb -p YOUR_PROJECT_ID -c STANDARD -l US gs://YOUR-BUCKET-NAME
```

## Recovery Scenarios

### Full Database Loss

```bash
# 1. List available backups
./templedb backup cloud status gcs

# 2. Choose most recent backup
# 3. Restore (no current DB exists, so no safety backup needed)
./templedb backup cloud pull gcs BACKUP_ID --no-safety-backup
```

### Partial Corruption

```bash
# 1. Create local backup first
./templedb backup local

# 2. Try SQLite repair
sqlite3 ~/.local/share/templedb/templedb.sqlite ".recover" | \
  sqlite3 recovered.sqlite

# 3. If repair fails, restore from cloud
./templedb backup cloud pull gcs LATEST_BACKUP_ID
```

### Accidental Data Deletion

```bash
# If versioning is enabled, restore previous version
gsutil ls -a gs://YOUR-BUCKET-NAME/ | grep templedb_backup

# Restore specific version
gsutil cp gs://YOUR-BUCKET-NAME/FILE#VERSION /tmp/restore.sqlite.gz
gunzip /tmp/restore.sqlite.gz
./templedb backup restore /tmp/restore.sqlite
```

## Alternative: Google Drive Backup

TempleDB also supports Google Drive:

```bash
# Initialize Google Drive
./templedb backup cloud init gdrive

# Push to Google Drive
./templedb backup cloud push gdrive

# Advantage: 15GB free storage
# Disadvantage: Slower, less automation-friendly
```

## Best Practices Summary

✅ **Do:**
- Enable bucket versioning
- Use service accounts for automation
- Set up lifecycle policies for old backups
- Test restores regularly (monthly)
- Monitor backup logs
- Keep encryption keys secure and backed up separately
- Use regional buckets for better performance
- Enable audit logging

❌ **Don't:**
- Make buckets public
- Store credentials in git repos
- Disable encryption for sensitive data
- Forget to test restores
- Rely on single backup location
- Use weak encryption keys

## See Also

- [TempleDB Backup Documentation](BACKUP.md)
- [Google Cloud Storage Documentation](https://cloud.google.com/storage/docs)
- [gsutil Tool Documentation](https://cloud.google.com/storage/docs/gsutil)
- [GCS Pricing Calculator](https://cloud.google.com/products/calculator)
