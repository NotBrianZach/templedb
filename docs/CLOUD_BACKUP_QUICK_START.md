# Cloud Backup Quick Start

Quick reference for backing up TempleDB to Google Drive.

## 5-Minute Setup

```bash
# 1. Setup
./templedb cloud-backup setup gdrive

# 2. Get Google OAuth credentials
#    - Go to: https://console.cloud.google.com/
#    - Enable Google Drive API
#    - Create OAuth Desktop credentials
#    - Download as: ~/.config/templedb/gdrive_credentials.json

# 3. Enter nix development shell (dependencies managed by Nix)
nix develop

# 4. Test (will open browser for auth)
./templedb cloud-backup test -p gdrive

# 5. Backup!
./templedb cloud-backup backup -p gdrive
```

## Daily Use

```bash
# Create backup
./templedb cloud-backup backup -p gdrive

# List backups
./templedb cloud-backup list -p gdrive

# Restore backup
./templedb cloud-backup restore -p gdrive --backup-id BACKUP_ID
```

## Common Commands

| Command | Description |
|---------|-------------|
| `cloud-backup providers` | List available backup providers |
| `cloud-backup setup gdrive` | Show Google Drive setup instructions |
| `cloud-backup test -p gdrive` | Test connection to Google Drive |
| `cloud-backup backup -p gdrive` | Backup database to Google Drive |
| `cloud-backup list -p gdrive` | List all backups in Google Drive |
| `cloud-backup restore -p gdrive --backup-id ID` | Restore from backup |
| `cloud-backup cleanup -p gdrive` | Clean up old backups |

## Automated Backups

### Cron (Daily at 2 AM)

```bash
crontab -e
# Add:
0 2 * * * /path/to/templedb cloud-backup backup -p gdrive
```

### Systemd Timer

```bash
# Create service and timer files (see full guide)
sudo systemctl enable templedb-backup.timer
sudo systemctl start templedb-backup.timer
```

## Features

- ✅ Automatic OAuth authentication
- ✅ Timestamped backups
- ✅ Automatic cleanup of old backups
- ✅ Safety backups before restore
- ✅ Resume interrupted uploads
- ✅ Multiple Google account support

## Storage

- Backups stored in: "TempleDB Backups" folder
- Format: `templedb_YYYY-MM-DD_HH-MM-SS.sqlite`
- Default retention: 10 most recent backups
- Typical size: 1-10 MB per backup

## Troubleshooting

| Error | Solution |
|-------|----------|
| Credentials not found | Download from Google Cloud Console |
| Module not found | `pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib` |
| Access denied | Add email to Test Users in OAuth consent screen |
| Connection failed | Check internet and firewall |

## Documentation

- **[Complete Guide](./GOOGLE_DRIVE_BACKUP.md)** - Full documentation
- **[Google Cloud Console](https://console.cloud.google.com/)** - Get credentials
- **[Google Drive API](https://developers.google.com/drive/api/v3/about-sdk)** - API docs

## Next Steps

1. ✅ Complete 5-minute setup above
2. ✅ Test backup: `./templedb cloud-backup backup -p gdrive`
3. ✅ Verify: `./templedb cloud-backup list -p gdrive`
4. ✅ Setup automation (cron or systemd)
5. ✅ Test restore procedure

## Pro Tips

💡 **Test restores regularly** - Backups are useless if you can't restore!

💡 **Monitor backup size** - Run `VACUUM` if database grows large

💡 **Keep local copy** - Use `--keep-local` for extra safety

💡 **Multiple accounts** - Use different configs for work/personal

💡 **Encrypt sensitive data** - Add age encryption for extra security

Ready to protect your TempleDB data! 🚀
