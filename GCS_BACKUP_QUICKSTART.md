# Google Cloud Storage Backup - Quick Start

Three ways to back up TempleDB to Google Cloud Storage, from easiest to most control.

## 🚀 Method 1: Automatic Setup Script (Recommended)

**Takes 2 minutes. Does everything for you.**

```bash
# Run the setup script
./scripts/setup-gcs-backup.sh
```

This will:
- ✓ Check your Google Cloud authentication
- ✓ Create a GCS bucket for backups
- ✓ Generate configuration file
- ✓ Test the connection
- ✓ Create backup script
- ✓ Optionally set up automatic daily backups
- ✓ Run a test backup

Then you're done! Your database will back up automatically.

## ⚡ Method 2: Quick Manual Setup

**For when you already have a GCS bucket.**

```bash
# 1. Authenticate with Google Cloud
gcloud auth application-default login

# 2. Create config file
mkdir -p ~/.config/templedb
cat > ~/.config/templedb/backup-gcs.json << 'EOF'
{
  "provider": "gcs",
  "bucket_name": "YOUR-BUCKET-NAME",
  "project_id": "your-project-id",
  "compression": true
}
EOF

# 3. Test it
templedb backup cloud push gcs

# 4. Verify
templedb backup cloud status gcs
```

Done! Now you can run `templedb backup cloud push gcs` anytime.

## 🎯 Method 3: One-Time Backup (No Setup)

**Just want to backup once right now?**

```bash
# Install gsutil if not already installed
# (Part of Google Cloud SDK)

# 1. Authenticate
gcloud auth login

# 2. Create bucket (if you don't have one)
gsutil mb gs://templedb-backup-$(whoami)

# 3. Upload database
gzip -c ~/.local/share/templedb/templedb.sqlite | \
  gsutil cp - gs://templedb-backup-$(whoami)/backup-$(date +%Y%m%d).sqlite.gz

# Done! Your database is in the cloud.
```

## 📊 Comparison

| Method | Setup Time | Automation | Flexibility |
|--------|------------|------------|-------------|
| Script | 2 min | ✓ Full | ✓ High |
| Manual | 5 min | ✓ Basic | ✓✓ Very High |
| One-time | 30 sec | ✗ None | Basic |

## Common Commands

Once set up, use these commands:

```bash
# Upload backup to cloud
templedb backup cloud push gcs

# List all backups
templedb backup cloud status gcs

# Restore specific backup
templedb backup cloud pull gcs BACKUP_ID

# Clean up old backups (keep last 30 days)
templedb backup cloud cleanup gcs --days 30

# Test connection
templedb backup cloud test gcs
```

## Cost

**Typical costs for daily backups:**

| Database Size | Monthly Storage | Monthly Cost |
|---------------|-----------------|--------------|
| 100 MB | 3 GB (30 days) | ~$0.06 |
| 1 GB | 30 GB (30 days) | ~$0.60 |
| 10 GB | 300 GB (30 days) | ~$6.00 |

**Free tier:** 5 GB storage + operations for first year

## Troubleshooting

**"Permission denied"**
```bash
gcloud auth application-default login
```

**"Bucket not found"**
```bash
# List your buckets
gsutil ls

# Create one
gsutil mb gs://templedb-backups-$(whoami)
```

**"gcloud not found"**
```bash
# NixOS:
nix-shell -p google-cloud-sdk

# Other:
curl https://sdk.cloud.google.com | bash
```

## Full Documentation

For advanced features, security, automation, and more:

📖 **[Complete Guide](docs/BACKUP_GOOGLE_CLOUD.md)**

Topics covered:
- Service accounts for automation
- Client-side encryption
- Lifecycle policies
- Monitoring and alerts
- Recovery scenarios
- Cost optimization
- And much more...

## Quick Reference

```bash
# Setup
./scripts/setup-gcs-backup.sh

# Backup now
templedb backup cloud push gcs

# List backups
templedb backup cloud status gcs

# Restore
templedb backup cloud pull gcs <backup-id>

# View logs
tail -f ~/.local/share/templedb/backup.log

# Manual backup with gsutil
gsutil cp ~/.local/share/templedb/templedb.sqlite \
  gs://YOUR-BUCKET/backup-$(date +%Y%m%d).sqlite
```

## Security Checklist

- [ ] Bucket is private (not public)
- [ ] Using service account for automation (optional)
- [ ] Versioning enabled on bucket
- [ ] Lifecycle policy set for old backups
- [ ] Test restore monthly
- [ ] Backup logs monitored

## Next Steps

1. Run setup script: `./scripts/setup-gcs-backup.sh`
2. Test a backup: `templedb backup cloud push gcs`
3. Verify it worked: `templedb backup cloud status gcs`
4. Test restore: `templedb backup cloud pull gcs <backup-id> --db-path /tmp/test.sqlite`
5. Set it and forget it! ✨

---

Everything in the cloud. Everything in the temple. 🏛️☁️
