# Cloud Backup for TempleDB

Complete guide to backing up your TempleDB database to cloud storage.

---

## Overview

TempleDB supports pluggable cloud backup providers, allowing you to automatically backup your database to:
- **Google Drive** - Free 15GB, easy OAuth authentication
- **Local Filesystem** - Network drives, USB drives, etc.
- **AWS S3** - Enterprise-grade cloud storage (coming soon)
- **Dropbox** - Personal/business cloud storage (coming soon)

### Features

- ✅ **Automated backups** - Schedule with cron
- ✅ **Automatic cleanup** - Retention policies and max backup limits
- ✅ **Safe restores** - Automatic safety backup before restore
- ✅ **Pluggable providers** - Easy to add new cloud services
- ✅ **Online backups** - No downtime using SQLite backup API
- ✅ **Configurable** - JSON/YAML configuration files

---

## Quick Start

### 1. List Available Providers

```bash
./templedb cloud-backup providers
```

Output:
```
Available Backup Providers:

  ✓ gdrive
      Name: Google Drive
      Available: Yes

  ✓ local
      Name: Local Filesystem
      Available: Yes

  ✗ s3
      Name: AWS S3
      Available: No (missing dependencies)
```

### 2. Setup a Provider

```bash
# Google Drive
./templedb cloud-backup setup gdrive

# Local filesystem
./templedb cloud-backup setup local
```

### 3. Test Connection

```bash
./templedb cloud-backup test -p gdrive
```

### 4. Create Your First Backup

```bash
./templedb cloud-backup backup -p gdrive
```

---

## Google Drive Setup

### Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable the **Google Drive API**
4. Go to **APIs & Services** → **Credentials**
5. Click **Create Credentials** → **OAuth client ID**
6. Application type: **Desktop app**
7. Download the JSON file

### Step 2: Save Credentials

```bash
# Create config directory
mkdir -p ~/.config/templedb

# Save the downloaded file
mv ~/Downloads/client_secret_*.json ~/.config/templedb/gdrive_credentials.json
```

### Step 3: Authenticate

```bash
# Test connection (will open browser for OAuth)
./templedb cloud-backup test -p gdrive
```

This will:
1. Open your browser for Google OAuth
2. Ask you to grant access to Google Drive
3. Save authentication token to `~/.config/templedb/gdrive_token.json`
4. Create a folder "TempleDB Backups" in your Drive

### Step 4: Create Backup

```bash
# Create backup with default settings
./templedb cloud-backup backup -p gdrive

# Keep local copy
./templedb cloud-backup backup -p gdrive --keep-local

# Skip cleanup of old backups
./templedb cloud-backup backup -p gdrive --no-cleanup
```

---

## Local Filesystem Setup

Local backups are always available - no setup required!

### Default Location

Backups are stored in:
```
~/.local/share/templedb/backups/
```

### Custom Location

Create a configuration file:

```json
{
  "provider": "local",
  "config": {
    "backup_dir": "/mnt/nas/templedb_backups",
    "retention_days": 30,
    "max_backups": 10
  }
}
```

Use with:
```bash
./templedb cloud-backup backup -p local --config config.json
```

### Network Drives

You can backup to network drives:

```bash
# Mount network drive
sudo mount -t cifs //server/share /mnt/backup

# Create config pointing to network drive
cat > backup_config.json <<EOF
{
  "provider": "local",
  "config": {
    "backup_dir": "/mnt/backup/templedb",
    "retention_days": 60,
    "max_backups": 20
  }
}
EOF

# Backup
./templedb cloud-backup backup -p local --config backup_config.json
```

---

## CLI Commands

### backup

Create a backup to cloud storage.

```bash
./templedb cloud-backup backup -p PROVIDER [OPTIONS]
```

**Options:**
- `--db-path PATH` - Path to database (default: `~/.local/share/templedb/templedb.sqlite`)
- `--config FILE` - Provider configuration file
- `--keep-local` - Keep temporary local backup file
- `--no-cleanup` - Skip cleanup of old backups

**Examples:**
```bash
# Basic backup
./templedb cloud-backup backup -p gdrive

# Backup with config file
./templedb cloud-backup backup -p gdrive --config gdrive_config.json

# Backup and keep local copy
./templedb cloud-backup backup -p gdrive --keep-local

# Backup without cleanup
./templedb cloud-backup backup -p gdrive --no-cleanup
```

### list

List all backups in cloud storage.

```bash
./templedb cloud-backup list -p PROVIDER [OPTIONS]
```

**Options:**
- `--config FILE` - Provider configuration file

**Example:**
```bash
./templedb cloud-backup list -p gdrive
```

Output:
```
Found 5 backup(s) in Google Drive:

  templedb_backup_20260224_140530.sqlite
    ID: 1a2b3c4d5e6f
    Size: 52.34 MB
    Created: 2026-02-24T14:05:30.123Z

  templedb_backup_20260223_140530.sqlite
    ID: 9z8y7x6w5v4u
    Size: 51.89 MB
    Created: 2026-02-23T14:05:30.456Z
```

### restore

Restore database from cloud backup.

```bash
./templedb cloud-backup restore -p PROVIDER --backup-id ID [OPTIONS]
```

**Options:**
- `--db-path PATH` - Where to restore database
- `--config FILE` - Provider configuration file
- `--no-safety-backup` - Skip creating safety backup

**Example:**
```bash
# List backups to get ID
./templedb cloud-backup list -p gdrive

# Restore specific backup
./templedb cloud-backup restore -p gdrive --backup-id 1a2b3c4d5e6f

# Restore to different location
./templedb cloud-backup restore -p gdrive --backup-id 1a2b3c4d5e6f --db-path /tmp/restored.sqlite
```

**Safety:**
- Creates automatic safety backup before restore
- Validates downloaded file is a valid SQLite database
- Fails safely if anything goes wrong

### cleanup

Clean up old backups based on retention policy.

```bash
./templedb cloud-backup cleanup -p PROVIDER [OPTIONS]
```

**Options:**
- `--config FILE` - Provider configuration file

**Example:**
```bash
./templedb cloud-backup cleanup -p gdrive
```

**Retention Rules:**
- Deletes backups older than `retention_days` (default: 30)
- Keeps only `max_backups` most recent (default: 10)
- Oldest backups deleted first

### test

Test connection to backup provider.

```bash
./templedb cloud-backup test -p PROVIDER [OPTIONS]
```

**Options:**
- `--config FILE` - Provider configuration file

**Example:**
```bash
./templedb cloud-backup test -p gdrive
```

---

## Configuration Files

### Google Drive

```json
{
  "provider": "gdrive",
  "config": {
    "credentials_path": "~/.config/templedb/gdrive_credentials.json",
    "token_path": "~/.config/templedb/gdrive_token.json",
    "folder_name": "TempleDB Backups",
    "retention_days": 30,
    "max_backups": 10
  }
}
```

### Local Filesystem

```json
{
  "provider": "local",
  "config": {
    "backup_dir": "~/.local/share/templedb/backups",
    "retention_days": 30,
    "max_backups": 10
  }
}
```

### AWS S3 (Coming Soon)

```json
{
  "provider": "s3",
  "config": {
    "bucket_name": "my-templedb-backups",
    "aws_access_key_id": "YOUR_ACCESS_KEY",
    "aws_secret_access_key": "YOUR_SECRET_KEY",
    "region": "us-east-1",
    "prefix": "backups/",
    "retention_days": 30,
    "max_backups": 10
  }
}
```

---

## Automated Backups

### Using the Setup Script

```bash
# Run interactive setup
./scripts/setup_automated_backup.sh
```

This will:
1. Test connection to your chosen provider
2. Ask for backup schedule (daily, every 6h, etc.)
3. Create cron job automatically
4. Set up logging

### Manual Cron Setup

```bash
# Open crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * /path/to/templedb cloud-backup backup -p gdrive >> ~/.local/share/templedb/logs/backup.log 2>&1

# Add backup every 6 hours
0 */6 * * * /path/to/templedb cloud-backup backup -p gdrive >> ~/.local/share/templedb/logs/backup.log 2>&1
```

### Cron Examples

```bash
# Daily at 2 AM
0 2 * * * /path/to/templedb cloud-backup backup -p gdrive

# Every 6 hours
0 */6 * * * /path/to/templedb cloud-backup backup -p gdrive

# Every 12 hours
0 */12 * * * /path/to/templedb cloud-backup backup -p gdrive

# Weekly on Sunday at 3 AM
0 3 * * 0 /path/to/templedb cloud-backup backup -p gdrive

# First day of month at 1 AM
0 1 1 * * /path/to/templedb cloud-backup backup -p gdrive
```

### Viewing Logs

```bash
# View recent logs
tail -n 50 ~/.local/share/templedb/logs/backup.log

# Follow logs in real-time
tail -f ~/.local/share/templedb/logs/backup.log

# Search for errors
grep -i error ~/.local/share/templedb/logs/backup.log
```

---

## Advanced Usage

### Multiple Backup Destinations

You can backup to multiple providers:

```bash
# Backup to Google Drive
./templedb cloud-backup backup -p gdrive

# Also backup to local NAS
./templedb cloud-backup backup -p local --config nas_config.json

# Also backup to S3
./templedb cloud-backup backup -p s3 --config s3_config.json
```

### Custom Retention Policies

```json
{
  "provider": "gdrive",
  "config": {
    "retention_days": 90,
    "max_backups": 50
  }
}
```

### Environment Variables

Set log level for verbose output:

```bash
export TEMPLEDB_LOG_LEVEL=DEBUG
./templedb cloud-backup backup -p gdrive
```

---

## Adding New Providers

Want to add support for another cloud service? It's easy!

### 1. Create Provider Class

```python
# src/backup/mycloud_provider.py

from src.backup.base import CloudBackupProvider

class MyCloudProvider(CloudBackupProvider):
    def authenticate(self) -> bool:
        # Implement authentication
        pass

    def upload_file(self, file_path, remote_name=None):
        # Implement upload
        pass

    def download_file(self, remote_id, destination):
        # Implement download
        pass

    def list_backups(self):
        # Implement listing
        pass

    def delete_backup(self, remote_id):
        # Implement deletion
        pass
```

### 2. Register Provider

```python
# src/backup/__init__.py

from src.backup.mycloud_provider import MyCloudProvider
BackupProviderRegistry.register('mycloud', MyCloudProvider)
```

That's it! Your provider is now available:

```bash
./templedb cloud-backup backup -p mycloud
```

---

## Troubleshooting

### Google Drive Authentication Fails

**Problem:** OAuth flow doesn't complete

**Solution:**
1. Check credentials file exists: `~/.config/templedb/gdrive_credentials.json`
2. Ensure Google Drive API is enabled in your project
3. Try deleting token and re-authenticating:
   ```bash
   rm ~/.config/templedb/gdrive_token.json
   ./templedb cloud-backup test -p gdrive
   ```

### Backup Fails with "Database locked"

**Problem:** Another process is using the database

**Solution:**
1. Stop other TempleDB processes
2. Wait a few seconds and try again
3. Check for zombie processes: `ps aux | grep templedb`

### Out of Space on Google Drive

**Problem:** Google Drive quota exceeded

**Solution:**
1. Clean up old backups:
   ```bash
   ./templedb cloud-backup cleanup -p gdrive
   ```
2. Adjust retention policy to keep fewer backups
3. Upgrade Google Drive storage

### Slow Upload Speeds

**Problem:** Backup takes too long to upload

**Solution:**
1. Check your internet connection
2. Consider using local backups for speed
3. Run backups during off-peak hours
4. Compress database before upload (future feature)

---

## Security Best Practices

### Credentials

- ✅ **Never commit credentials** to version control
- ✅ **Use OAuth** when available (Google Drive)
- ✅ **Rotate access keys** periodically (S3)
- ✅ **Use read-write-only keys** (not admin keys)
- ✅ **Store credentials securely** (`~/.config/templedb/`)

### Access Control

```bash
# Secure credentials directory
chmod 700 ~/.config/templedb
chmod 600 ~/.config/templedb/gdrive_credentials.json
chmod 600 ~/.config/templedb/gdrive_token.json
```

### Backup Encryption

For sensitive data, encrypt backups before upload:

```bash
# Encrypt backup
gpg -c backup.sqlite

# Upload encrypted file
# ... custom script ...

# Decrypt when restoring
gpg -d backup.sqlite.gpg > backup.sqlite
```

---

## Performance

### Backup Times

Typical backup times:
- **50 MB database:** ~10-30 seconds (local)
- **50 MB database:** ~1-3 minutes (Google Drive)
- **50 MB database:** ~30-90 seconds (S3)

### Optimization Tips

1. **Schedule during off-hours** - Less impact on users
2. **Use local backups first** - Then sync to cloud
3. **Adjust retention** - Fewer backups = faster cleanup
4. **Monitor database size** - Vacuum/compress regularly

---

## Summary

TempleDB cloud backup provides:
- ✅ **Multiple providers** - Google Drive, local, S3, etc.
- ✅ **Easy setup** - OAuth authentication, simple config
- ✅ **Automated** - Cron scheduling with cleanup
- ✅ **Safe restores** - Automatic safety backups
- ✅ **Extensible** - Add new providers easily

**Next Steps:**
1. Run `./templedb cloud-backup setup gdrive`
2. Create your first backup
3. Set up automated backups with cron
4. Test restore procedure

---

*"An operating system is a temple."* - Terry A. Davis

**TempleDB - Where your code finds sanctuary**
