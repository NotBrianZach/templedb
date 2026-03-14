# Google Cloud Storage (GCS) Backup Setup

Complete guide to setting up automated backups to Google Cloud Storage for TempleDB.

## Prerequisites

- Google Cloud account
- `gcloud` CLI installed (available in TempleDB Nix environment)
- Age encryption key at `~/.age/key.txt` (or set `TEMPLEDB_AGE_KEY_FILE`)

## Quick Start

```bash
# 1. Authenticate with Google Cloud
gcloud auth login

# 2. Set your project
gcloud config set project YOUR_PROJECT_ID

# 3. Create GCS bucket
gcloud storage buckets create gs://your-unique-bucket-name \
  --location=us-central1 \
  --uniform-bucket-level-access

# 4. Create service account
gcloud iam service-accounts create templedb-backup \
  --description="Service account for TempleDB backups" \
  --display-name="TempleDB Backup"

# 5. Grant permissions
gcloud storage buckets add-iam-policy-binding gs://your-unique-bucket-name \
  --member="serviceAccount:templedb-backup@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.admin"

# 6. Create and download service account key
gcloud iam service-accounts keys create ~/templedb-gcs-key.json \
  --iam-account=templedb-backup@YOUR_PROJECT_ID.iam.gserviceaccount.com

# 7. Store credentials in TempleDB secrets
# See "Storing Credentials" section below

# 8. Test connection
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt ./templedb cloud-backup test \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json

# 9. Create your first backup
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt ./templedb cloud-backup backup \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json
```

## Detailed Setup

### 1. Install gcloud CLI

The gcloud CLI is included in TempleDB's Nix environment:

```bash
# Enter Nix development environment
nix develop

# Verify gcloud is available
gcloud --version
```

Or install separately: https://cloud.google.com/sdk/docs/install

### 2. Authenticate with Google Cloud

```bash
# Open browser for authentication
gcloud auth login

# List your projects
gcloud projects list

# Set active project (create one if needed at console.cloud.google.com)
gcloud config set project YOUR_PROJECT_ID
```

### 3. Enable Billing

GCS requires billing to be enabled on your project:

1. Go to https://console.cloud.google.com/billing
2. Link a billing account to your project
3. Verify: `gcloud beta billing projects describe YOUR_PROJECT_ID`

### 4. Create GCS Bucket

```bash
# Create bucket with globally unique name
gcloud storage buckets create gs://templedb-backups-$(whoami) \
  --location=us-central1 \
  --uniform-bucket-level-access

# Or use custom name
gcloud storage buckets create gs://your-company-templedb-backups \
  --location=us-central1
```

**Bucket naming:**
- Must be globally unique
- Use lowercase letters, numbers, hyphens
- No underscores or spaces
- Examples: `templedb-backups-mycompany`, `prod-templedb-backups`

**Location options:**
- `us-central1` - Iowa (recommended for US)
- `us-east1` - South Carolina
- `europe-west1` - Belgium
- `asia-northeast1` - Tokyo
- See all: `gcloud storage locations list`

### 5. Create Service Account

Service accounts provide programmatic access without user credentials:

```bash
# Create service account
gcloud iam service-accounts create templedb-backup \
  --description="Service account for TempleDB backups" \
  --display-name="TempleDB Backup"

# Verify creation
gcloud iam service-accounts list
```

### 6. Grant Bucket Permissions

The service account needs permission to read/write objects in your bucket:

```bash
# Grant storage admin role (allows create, read, delete)
gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET_NAME \
  --member="serviceAccount:templedb-backup@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.admin"

# Verify permissions
gcloud storage buckets get-iam-policy gs://YOUR_BUCKET_NAME
```

**Required permissions:**
- `storage.buckets.get` - Read bucket metadata
- `storage.objects.create` - Upload backups
- `storage.objects.list` - List backups
- `storage.objects.get` - Download backups
- `storage.objects.delete` - Cleanup old backups

The `roles/storage.admin` role includes all of these.

### 7. Create Service Account Key

Generate JSON credentials for the service account:

```bash
# Create and download key
gcloud iam service-accounts keys create ~/templedb-gcs-key.json \
  --iam-account=templedb-backup@YOUR_PROJECT_ID.iam.gserviceaccount.com

# View the key (for verification)
cat ~/templedb-gcs-key.json
```

**Security note:** This JSON file contains credentials. Store it securely in TempleDB secrets (see next section), then delete the local copy.

## Storing Credentials in TempleDB

TempleDB stores GCS credentials encrypted in the `system_config` project secrets.

### Initialize system_config secrets (if not already done)

```bash
# Get your age public key
age-keygen -y ~/.age/key.txt

# Initialize secrets for system_config
./templedb secret init system_config \
  --profile default \
  --age-recipient YOUR_AGE_PUBLIC_KEY
```

### Store GCS credentials

You need to store the service account JSON in the TempleDB database. Here's a Python script to do this:

```python
#!/usr/bin/env python3
import sqlite3
import subprocess
from pathlib import Path

# Read the GCS service account JSON
with open(Path.home() / 'templedb-gcs-key.json', 'r') as f:
    gcs_json = f.read()

# Get age identity and recipient
age_identity = Path.home() / ".age" / "key.txt"
proc = subprocess.run(
    ["age-keygen", "-y", str(age_identity)],
    capture_output=True,
    text=True
)
age_recipient = proc.stdout.strip()

# Encrypt the JSON
proc = subprocess.run(
    ["age", "-r", age_recipient, "-a"],
    input=gcs_json.encode('utf-8'),
    capture_output=True
)

if proc.returncode != 0:
    print(f"Failed to encrypt: {proc.stderr.decode()}")
    exit(1)

encrypted_blob = proc.stdout

# Store in database
db_path = Path.home() / '.local' / 'share' / 'templedb' / 'templedb.sqlite'
conn = sqlite3.connect(str(db_path))
cursor = conn.cursor()

# Get system_config project ID
cursor.execute("SELECT id FROM projects WHERE slug = 'system_config'")
result = cursor.fetchone()
if not result:
    print("Error: system_config project not found")
    exit(1)

project_id = result[0]

# Update or insert the secret
cursor.execute("""
    INSERT INTO secret_blobs (project_id, profile, secret_name, secret_blob, content_type)
    VALUES (?, 'default', 'gcs_service_account', ?, 'application/json')
    ON CONFLICT(project_id, profile) DO UPDATE SET
        secret_blob = excluded.secret_blob,
        secret_name = 'gcs_service_account',
        content_type = 'application/json',
        updated_at = CURRENT_TIMESTAMP
""", (project_id, encrypted_blob))

conn.commit()
conn.close()

print("✓ Successfully stored GCS credentials in TempleDB secrets!")
print("You can now delete ~/templedb-gcs-key.json")
```

Save this as `store_gcs_creds.py` and run:

```bash
python3 store_gcs_creds.py
rm ~/templedb-gcs-key.json  # Delete the plaintext key file
```

### Create GCS configuration file

```bash
mkdir -p ~/.config/templedb

cat > ~/.config/templedb/gcs_config.json << EOF
{
  "bucket_name": "YOUR_BUCKET_NAME",
  "project_id": "YOUR_PROJECT_ID"
}
EOF
```

The service account credentials will be loaded from TempleDB secrets automatically.

## Using GCS Backups

### Test Connection

```bash
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt ./templedb cloud-backup test \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json
```

Expected output:
```
Testing connection to Google Cloud Storage...
INFO     Credentials file not found, checking TempleDB secrets...
INFO     Loaded GCS service account credentials from TempleDB secrets
INFO     Successfully authenticated with GCS bucket: your-bucket-name
✓ Connection successful
```

### Create Backup

```bash
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt ./templedb cloud-backup backup \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json
```

Output:
```
INFO     Starting backup to Google Cloud Storage...
INFO     Creating local backup: /home/user/.local/share/templedb/tmp/templedb_backup_20260313_213000.sqlite
INFO     Local backup created successfully (189.11 MB)
INFO     Uploading to Google Cloud Storage...
INFO     Upload successful: templedb-backups/templedb_backup_20260313_213000.sqlite
✓ Backup completed successfully
```

### List Backups

```bash
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt ./templedb cloud-backup list \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json
```

Output:
```
Found 3 backup(s) in Google Cloud Storage:

  templedb_backup_20260313_213000.sqlite
    ID: templedb-backups/templedb_backup_20260313_213000.sqlite
    Size: 189.11 MB
    Created: 2026-03-14T02:30:08.251000+00:00
```

### Restore Backup

```bash
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt ./templedb cloud-backup restore \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json \
  --backup-id templedb-backups/templedb_backup_20260313_213000.sqlite
```

### Cleanup Old Backups

```bash
TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt ./templedb cloud-backup cleanup \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json
```

## Automated Backups

### Simplify Commands with Environment Variable

Create a wrapper script to avoid repeating the age key path:

```bash
#!/bin/bash
# ~/bin/templedb-gcs-backup

export TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt
/path/to/templedb cloud-backup "$@" \
  --provider gcs \
  --config ~/.config/templedb/gcs_config.json
```

Make it executable:
```bash
chmod +x ~/bin/templedb-gcs-backup
```

Now you can use:
```bash
templedb-gcs-backup test
templedb-gcs-backup backup
templedb-gcs-backup list
```

### Cron (Daily Backups)

```bash
# Edit crontab
crontab -e

# Add daily backup at 3 AM
0 3 * * * /home/user/bin/templedb-gcs-backup backup >> /var/log/templedb-backup.log 2>&1
```

### systemd Timer (Linux)

```ini
# /etc/systemd/user/templedb-backup.service
[Unit]
Description=TempleDB GCS Backup

[Service]
Type=oneshot
Environment="TEMPLEDB_AGE_KEY_FILE=/home/user/.age/key.txt"
ExecStart=/usr/local/bin/templedb cloud-backup backup \
  --provider gcs \
  --config /home/user/.config/templedb/gcs_config.json
```

```ini
# /etc/systemd/user/templedb-backup.timer
[Unit]
Description=TempleDB GCS Backup Timer

[Timer]
OnCalendar=daily
OnCalendar=03:00
Persistent=true

[Install]
WantedBy=timers.target
```

Enable and start:
```bash
systemctl --user enable templedb-backup.timer
systemctl --user start templedb-backup.timer
systemctl --user status templedb-backup.timer
```

## Cost Estimation

### GCS Pricing (as of 2026)

**Storage costs (Standard class, us-central1):**
- $0.020 per GB/month

**Network costs:**
- Upload: Free
- Download: $0.12 per GB

**Operations:**
- Upload/Create: $0.05 per 10,000 operations
- List: $0.05 per 10,000 operations
- Download: $0.004 per 10,000 operations

**Example: 200 MB database, daily backups, 30-day retention:**
- Storage: 200 MB × 30 days = 6 GB = $0.12/month
- Operations: 30 uploads + 30 lists = ~$0.00
- **Total: ~$0.12/month** (essentially free)

**Larger example: 10 GB database, daily backups:**
- Storage: 10 GB × 30 days = 300 GB = $6/month
- Operations: negligible
- **Total: ~$6/month**

### Free Tier

Google Cloud offers:
- 5 GB free storage per month (Regional)
- 5,000 Class A operations per month (uploads)
- 50,000 Class B operations per month (lists)

Most TempleDB backups will stay within free tier limits!

## Troubleshooting

### "TEMPLEDB_AGE_KEY_FILE not set"

The GCS provider looks for age keys in this order:
1. `$TEMPLEDB_AGE_KEY_FILE`
2. `$SOPS_AGE_KEY_FILE`
3. `~/.config/sops/age/keys.txt`
4. `~/.age/key.txt` (won't work without env var)

**Solution:** Always set `TEMPLEDB_AGE_KEY_FILE`:
```bash
export TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt
```

Or create symlink:
```bash
mkdir -p ~/.config/sops/age
ln -s ~/.age/key.txt ~/.config/sops/age/keys.txt
```

### "GCS credentials not found"

**Check if secret exists:**
```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite << SQL
SELECT id, secret_name FROM secret_blobs
WHERE project_id = (SELECT id FROM projects WHERE slug = 'system_config');
SQL
```

Should show: `secret_name = 'gcs_service_account'`

**Verify decryption:**
```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT secret_blob FROM secret_blobs WHERE secret_name = 'gcs_service_account'" \
  | age -d -i ~/.age/key.txt
```

Should output valid JSON with `"type": "service_account"`

### "Permission denied on bucket"

**Check service account has permissions:**
```bash
gcloud storage buckets get-iam-policy gs://YOUR_BUCKET_NAME
```

Look for:
```yaml
- members:
  - serviceAccount:templedb-backup@YOUR_PROJECT_ID.iam.gserviceaccount.com
  role: roles/storage.admin
```

**Re-grant if missing:**
```bash
gcloud storage buckets add-iam-policy-binding gs://YOUR_BUCKET_NAME \
  --member="serviceAccount:templedb-backup@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.admin"
```

### "Billing account disabled"

**Enable billing:**
1. Go to https://console.cloud.google.com/billing
2. Click "Link a billing account"
3. Select or create billing account
4. Link to your project

### "Bucket not found"

**List your buckets:**
```bash
gcloud storage buckets list
```

**Check project:**
```bash
gcloud config get-value project
```

**Verify config file points to correct bucket:**
```bash
cat ~/.config/templedb/gcs_config.json
```

## Security Best Practices

1. **Service Account Key Storage**
   - Store in TempleDB encrypted secrets
   - Never commit to git
   - Delete plaintext key file after storing

2. **Least Privilege**
   - Grant only `roles/storage.admin` on specific bucket
   - Don't use project-wide permissions
   - Create separate service account per environment

3. **Key Rotation**
   ```bash
   # Create new key
   gcloud iam service-accounts keys create ~/new-key.json \
     --iam-account=templedb-backup@PROJECT.iam.gserviceaccount.com

   # Update in TempleDB secrets (run store script)

   # Delete old key
   gcloud iam service-accounts keys delete OLD_KEY_ID \
     --iam-account=templedb-backup@PROJECT.iam.gserviceaccount.com
   ```

4. **Bucket Access**
   - Use uniform bucket-level access
   - Disable public access
   - Enable versioning for recovery

5. **Monitoring**
   - Enable Cloud Audit Logs
   - Set up alerts for unusual access
   - Review IAM permissions quarterly

## Alternative: Using Application Default Credentials

For production deployments, you can use ADC instead of service account keys:

```bash
# On GCP VM or Cloud Run
gcloud auth application-default login

# No config file needed, just bucket name
./templedb cloud-backup backup --provider gcs --bucket YOUR_BUCKET_NAME
```

This avoids storing credentials entirely - GCP provides them automatically to running instances.

## Next Steps

- Set up automated backups (cron/systemd)
- Configure retention policy
- Test disaster recovery process
- Consider multi-region backups for critical data
- Enable bucket versioning for additional safety

## References

- [GCS Documentation](https://cloud.google.com/storage/docs)
- [Service Account Best Practices](https://cloud.google.com/iam/docs/best-practices-service-accounts)
- [GCS Pricing](https://cloud.google.com/storage/pricing)
- [Age Encryption](https://age-encryption.org/)

---

**Related:** [BACKUP.md](BACKUP.md), [SECURITY_THREAT_MODEL.md](SECURITY_THREAT_MODEL.md)
