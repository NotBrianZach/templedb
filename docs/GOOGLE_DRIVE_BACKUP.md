# Google Drive Backup Guide for TempleDB

Complete guide for backing up your TempleDB database to Google Drive.

## Quick Start

```bash
# 1. Setup Google Drive backup
./templedb cloud-backup setup gdrive

# 2. Follow the setup instructions to get credentials

# 3. Test connection
./templedb cloud-backup test -p gdrive

# 4. Create a backup
./templedb cloud-backup backup -p gdrive

# 5. List your backups
./templedb cloud-backup list -p gdrive
```

## Setup Instructions

### 1. Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select an existing one
3. Note the project name

### 2. Enable Google Drive API

1. In your project, go to **APIs & Services** → **Library**
2. Search for "Google Drive API"
3. Click on it and click **Enable**

### 3. Create OAuth 2.0 Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth client ID**
3. If prompted, configure the OAuth consent screen:
   - User Type: **External**
   - App name: "TempleDB Backup"
   - User support email: your email
   - Developer contact: your email
   - Click **Save and Continue**
   - Scopes: Click **Save and Continue** (no additional scopes needed)
   - Test users: Add your email
   - Click **Save and Continue**
4. Back at Create OAuth client ID:
   - Application type: **Desktop app**
   - Name: "TempleDB Desktop"
   - Click **Create**
5. **Download** the credentials JSON file

### 4. Install Credentials

```bash
# Create config directory
mkdir -p ~/.config/templedb

# Move downloaded credentials file
mv ~/Downloads/client_secret_*.json ~/.config/templedb/gdrive_credentials.json
```

### 5. Dependencies (Managed by Nix)

Dependencies are automatically provided by the Nix development shell:

```bash
# Enter the development shell
nix develop
```

The following packages are included:
- `google-api-python-client` - Google Drive API
- `google-auth` - Authentication
- `google-auth-oauthlib` - OAuth flow
- `google-auth-httplib2` - HTTP transport

**Note:** If you're not using Nix, install manually:
```bash
pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
```

### 6. Test Connection

```bash
./templedb cloud-backup test -p gdrive
```

This will:
1. Open a browser for OAuth authentication
2. Ask you to sign in with your Google account
3. Request permission to access Google Drive
4. Save the authentication token for future use

## Usage

### Create Backup

```bash
# Backup to Google Drive
./templedb cloud-backup backup -p gdrive

# Backup and keep local copy
./templedb cloud-backup backup -p gdrive --keep-local

# Skip cleanup of old backups
./templedb cloud-backup backup -p gdrive --no-cleanup
```

**What happens:**
1. Creates a timestamped backup: `templedb_2026-03-08_12-30-45.sqlite`
2. Uploads to Google Drive folder "TempleDB Backups"
3. Cleans up old backups (keeps most recent 10 by default)

### List Backups

```bash
./templedb cloud-backup list -p gdrive
```

**Output:**
```
Found 5 backup(s) in Google Drive:

  templedb_2026-03-08_12-30-45.sqlite
    ID: 1abc123def456
    Size: 2.45 MB
    Created: 2026-03-08T12:30:45.000Z

  templedb_2026-03-07_18-15-30.sqlite
    ID: 1xyz789ghi012
    Size: 2.42 MB
    Created: 2026-03-07T18:15:30.000Z
```

### Restore from Backup

```bash
# Restore specific backup
./templedb cloud-backup restore -p gdrive --backup-id 1abc123def456

# Restore without safety backup
./templedb cloud-backup restore -p gdrive --backup-id 1abc123def456 --no-safety-backup

# Restore to different location
./templedb cloud-backup restore -p gdrive --backup-id 1abc123def456 --db-path /path/to/restore.sqlite
```

**Safety features:**
- By default, creates a local backup before restoring
- Prevents accidental data loss

### Cleanup Old Backups

```bash
./templedb cloud-backup cleanup -p gdrive
```

This removes old backups, keeping only the most recent 10 (configurable).

### Check Providers

```bash
./templedb cloud-backup providers
```

**Output:**
```
Available Backup Providers:

  ✓ gdrive
      Name: Google Drive
      Available: Yes
      Required config: credentials_path, folder_name

  ✓ local
      Name: Local Filesystem
      Available: Yes
      Required config: backup_dir
```

## Automation

### Daily Backups with Cron

Add to your crontab:

```bash
# Edit crontab
crontab -e

# Add daily backup at 2 AM
0 2 * * * /path/to/templedb cloud-backup backup -p gdrive
```

### Systemd Timer

Create `/etc/systemd/system/templedb-backup.service`:

```ini
[Unit]
Description=TempleDB Google Drive Backup
After=network.target

[Service]
Type=oneshot
User=your-username
ExecStart=/path/to/templedb cloud-backup backup -p gdrive
```

Create `/etc/systemd/system/templedb-backup.timer`:

```ini
[Unit]
Description=Run TempleDB backup daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

Enable:

```bash
sudo systemctl enable templedb-backup.timer
sudo systemctl start templedb-backup.timer
```

### GitHub Actions

```yaml
name: Backup TempleDB

on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM
  workflow_dispatch:  # Manual trigger

jobs:
  backup:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v2

      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.10'

      - name: Install dependencies
        run: |
          pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib

      - name: Setup credentials
        run: |
          mkdir -p ~/.config/templedb
          echo '${{ secrets.GDRIVE_CREDENTIALS }}' > ~/.config/templedb/gdrive_credentials.json
          echo '${{ secrets.GDRIVE_TOKEN }}' > ~/.config/templedb/gdrive_token.json

      - name: Backup to Google Drive
        run: |
          ./templedb cloud-backup backup -p gdrive
```

**Secrets to add:**
- `GDRIVE_CREDENTIALS`: Contents of `gdrive_credentials.json`
- `GDRIVE_TOKEN`: Contents of `gdrive_token.json` (after first auth)

## Configuration

### Custom Settings

Create a config file `gdrive-config.json`:

```json
{
  "credentials_path": "/custom/path/to/credentials.json",
  "token_path": "/custom/path/to/token.json",
  "folder_name": "My Custom Backup Folder",
  "retention_days": 30,
  "max_backups": 20
}
```

Use with:

```bash
./templedb cloud-backup backup -p gdrive --config gdrive-config.json
```

### Retention Policy

Control how many backups to keep:

- **retention_days**: Delete backups older than N days
- **max_backups**: Keep only N most recent backups

## Troubleshooting

### "Credentials not found"

```
✗ Credentials not found: ~/.config/templedb/gdrive_credentials.json
```

**Solution:**
1. Download OAuth credentials from Google Cloud Console
2. Save to `~/.config/templedb/gdrive_credentials.json`

### "Failed to refresh credentials"

Token expired. Re-authenticate:

```bash
rm ~/.config/templedb/gdrive_token.json
./templedb cloud-backup test -p gdrive
```

### "Access denied" or "Invalid scope"

Make sure Google Drive API is enabled:
1. Go to Google Cloud Console
2. APIs & Services → Library
3. Search "Google Drive API"
4. Click Enable

### "ModuleNotFoundError: No module named 'google'"

Install dependencies:

```bash
pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
```

### Backup fails with "HttpError 403"

Check OAuth consent screen:
1. Go to Google Cloud Console
2. APIs & Services → OAuth consent screen
3. Add your email to "Test users"

### "Connection timeout"

Check internet connection and firewall settings. Google Drive API needs outbound HTTPS access.

## Security Best Practices

1. **Protect credentials:**
   ```bash
   chmod 600 ~/.config/templedb/gdrive_credentials.json
   chmod 600 ~/.config/templedb/gdrive_token.json
   ```

2. **Use separate Google account** for backups

3. **Enable 2-Factor Authentication** on your Google account

4. **Regular token rotation:** Re-authenticate periodically

5. **Monitor API usage** in Google Cloud Console

6. **Encrypt backups before upload** (optional):
   ```bash
   # Encrypt with age
   age -r your-public-key ~/.local/share/templedb/templedb.sqlite > backup.sqlite.age
   # Upload encrypted backup
   ./templedb cloud-backup backup -p gdrive --db-path backup.sqlite.age
   ```

## Backup Size Optimization

Reduce backup size:

```bash
# Vacuum database before backup
sqlite3 ~/.local/share/templedb/templedb.sqlite "VACUUM;"

# Then backup
./templedb cloud-backup backup -p gdrive
```

## Google Drive Storage Limits

- **Free tier:** 15 GB (shared with Gmail and Photos)
- **Google One:** 100 GB, 200 GB, 2 TB plans available
- Typical TempleDB database: 1-10 MB
- With 10 MB backups, you can store 1,500 backups in free tier

## Monitoring

### Check last backup

```bash
./templedb cloud-backup list -p gdrive | head -n 10
```

### Verify backup integrity

```bash
# Download and test
./templedb cloud-backup restore -p gdrive --backup-id ID --db-path /tmp/test.sqlite
sqlite3 /tmp/test.sqlite "PRAGMA integrity_check;"
```

## Advanced Usage

### Multiple Google Accounts

Use different configs for different accounts:

```bash
# Work account
./templedb cloud-backup backup -p gdrive --config ~/work-gdrive.json

# Personal account
./templedb cloud-backup backup -p gdrive --config ~/personal-gdrive.json
```

### Selective Backups

Backup specific database:

```bash
./templedb cloud-backup backup -p gdrive --db-path /path/to/specific.sqlite
```

### Backup Hooks

Run commands before/after backup:

```bash
#!/bin/bash
# pre-backup.sh
echo "Starting backup at $(date)"
sqlite3 ~/.local/share/templedb/templedb.sqlite "VACUUM;"

# Run backup
./templedb cloud-backup backup -p gdrive

# post-backup.sh
echo "Backup completed at $(date)"
```

## FAQ

**Q: How long do backups take?**
A: Usually 5-30 seconds for typical databases (1-10 MB).

**Q: Can I backup to a shared folder?**
A: Yes, create the folder in Google Drive and set `folder_name` in config.

**Q: What if I lose my credentials?**
A: Download new ones from Google Cloud Console. Old backups remain accessible.

**Q: Can I use a service account?**
A: Yes, create a service account in Google Cloud Console and download JSON key. Use it as credentials_path.

**Q: Is data encrypted in transit?**
A: Yes, Google API uses HTTPS. Data is encrypted in transit.

**Q: Is data encrypted at rest in Google Drive?**
A: Google Drive encrypts data at rest, but you can add additional encryption with age/gpg if desired.

## See Also

- [TempleDB Backup System](../README.md#backups)
- [Local Backups](./LOCAL_BACKUP.md)
- [S3 Backups](./S3_BACKUP.md)
- [Google Drive API Documentation](https://developers.google.com/drive/api/v3/about-sdk)
