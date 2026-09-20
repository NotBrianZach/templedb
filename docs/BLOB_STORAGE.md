# Blob Storage

Store large files (images, videos, binaries) outside the database. Supports local filesystem, S3, Backblaze, Cloudflare R2.

## Quick Start

```bash
# Setup S3 storage
templedb storage blob setup --provider s3 \
  --bucket my-blobs \
  --region us-east-1 \
  --access-key $AWS_ACCESS_KEY \
  --secret-key $AWS_SECRET_KEY

# Store file
templedb storage blob upload myapp assets/logo.png

# Retrieve file
templedb storage blob download myapp logo.png --output ./logo.png

# List blobs
templedb storage blob list myapp
```

## Why Blob Storage?

**SQLite limitations:**
- Max database size: ~281 TB (theoretical, practical limit ~100GB)
- Large blobs slow down VACUUM, backup, queries
- Better to store metadata in database, files elsewhere

**When to use:**
- Images, videos (> 1MB)
- PDFs, documents (> 5MB)
- Build artifacts, archives (> 10MB)
- Any binary > 100KB

**Keep in database:**
- Source code (text, always < 1MB)
- Configuration files (< 100KB)
- Small icons, CSS, JS (< 100KB)

## Providers

### Local Filesystem

```bash
# Setup (default)
templedb storage blob setup --provider local --path ~/templedb-blobs

# Upload
templedb storage blob upload myapp large-file.zip

# Stored at: ~/templedb-blobs/<project-slug>/<hash>
```

**Pros:** Simple, fast, no external dependencies
**Cons:** No redundancy, not scalable

### AWS S3

```bash
# Setup
templedb storage blob setup --provider s3 \
  --bucket my-project-blobs \
  --region us-east-1 \
  --access-key $AWS_ACCESS_KEY_ID \
  --secret-key $AWS_SECRET_ACCESS_KEY

# Upload
templedb storage blob upload myapp assets/video.mp4

# Download
templedb storage blob download myapp video.mp4 --output ./video.mp4
```

**Pros:** Scalable, durable (99.999999999%), CDN integration
**Cons:** Cost ($0.023/GB/month + transfer)

### Backblaze B2

```bash
# Setup
templedb storage blob setup --provider backblaze \
  --bucket my-blobs \
  --key-id $B2_KEY_ID \
  --app-key $B2_APPLICATION_KEY

# Upload/download same as S3
templedb storage blob upload myapp large-dataset.tar.gz
```

**Pros:** Cheap ($0.005/GB/month), S3-compatible API
**Cons:** Slower than S3 for some regions

### Cloudflare R2

```bash
# Setup
templedb storage blob setup --provider r2 \
  --bucket my-blobs \
  --account-id $CF_ACCOUNT_ID \
  --access-key $R2_ACCESS_KEY \
  --secret-key $R2_SECRET_KEY

# Upload/download same as S3
templedb storage blob upload myapp build-artifacts.zip
```

**Pros:** Free egress (no transfer costs), fast CDN
**Cons:** Newer service, fewer regions

## Usage

### Upload

```bash
# Basic upload
templedb storage blob upload myapp file.pdf

# With content type
templedb storage blob upload myapp image.png --content-type image/png

# With metadata
templedb storage blob upload myapp report.pdf --metadata '{"author": "alice", "version": "1.0"}'

# Multiple files
templedb storage blob upload myapp assets/*.jpg
```

### Download

```bash
# Download to current directory
templedb storage blob download myapp file.pdf

# Download to specific path
templedb storage blob download myapp file.pdf --output ~/downloads/file.pdf

# Download specific version
templedb storage blob download myapp file.pdf --version 2
```

### List

```bash
# List all blobs for project
templedb storage blob list myapp

# Filter by pattern
templedb storage blob list myapp --pattern "*.png"

# Show sizes
templedb storage blob list myapp --show-size

# Show metadata
templedb storage blob list myapp --show-metadata
```

### Delete

```bash
# Delete blob
templedb storage blob delete myapp file.pdf

# Delete all versions
templedb storage blob delete myapp file.pdf --all-versions

# Cleanup unused blobs
templedb storage blob cleanup myapp --dry-run
templedb storage blob cleanup myapp
```

## Versioning

Blobs are automatically versioned (content-addressed by hash).

```bash
# Upload same filename, different content
templedb storage blob upload myapp config.json
# Version 1: hash abc123...

# Modify config.json locally
templedb storage blob upload myapp config.json
# Version 2: hash def456...

# List versions
templedb storage blob versions myapp config.json

# Download specific version
templedb storage blob download myapp config.json --version 1
```

**Deduplication:**
- Same content = same hash = stored once
- Saves storage for duplicates

## Metadata

Store metadata alongside blobs:

```bash
# Upload with metadata
templedb storage blob upload myapp photo.jpg --metadata '{
  "camera": "Canon EOS",
  "location": "San Francisco",
  "date": "2026-03-11"
}'

# Query metadata
sqlite3 ~/.local/share/templedb/templedb.sqlite
SELECT filename, metadata FROM blob_storage WHERE project_slug = 'myapp';

# Update metadata
templedb storage blob update-metadata myapp photo.jpg --metadata '{"tags": ["landscape", "city"]}'
```

## CDN Integration

**CloudFlare + R2:**
```bash
# Upload to R2
templedb storage blob upload myapp assets/logo.png

# Get CDN URL
templedb storage blob url myapp logo.png
# https://cdn.example.com/myapp/logo.png
```

**AWS S3 + CloudFront:**
```bash
# Setup CloudFront distribution pointing to S3 bucket
# Configure in blob provider settings
templedb storage blob setup --provider s3 --cdn-domain cdn.example.com

# Upload
templedb storage blob upload myapp image.jpg

# Get CDN URL
templedb storage blob url myapp image.jpg --cdn
# https://cdn.example.com/myapp/image.jpg
```

## Migration

### Move blobs between providers

```bash
# Copy from local to S3
templedb storage blob migrate myapp --from local --to s3

# Verify migration
templedb storage blob verify myapp --provider s3

# Switch provider
templedb storage blob set-provider myapp s3
```

### Import existing files

```bash
# Import directory
templedb storage blob import myapp ~/assets/*.png

# Import with pattern
templedb storage blob import myapp ~/media --pattern "*.{jpg,png,mp4}"

# Dry run
templedb storage blob import myapp ~/assets --dry-run
```

## Database Schema

```sql
-- Blob providers
CREATE TABLE blob_providers (
  id INTEGER PRIMARY KEY,
  project_id INTEGER,
  name TEXT,                     -- 'local', 's3', 'backblaze', 'r2'
  config JSON,
  is_active BOOLEAN
);

-- Blob storage
CREATE TABLE blob_storage (
  id INTEGER PRIMARY KEY,
  project_id INTEGER,
  provider_id INTEGER,
  filename TEXT,
  content_hash TEXT,             -- SHA256 of content
  content_type TEXT,
  size_bytes INTEGER,
  metadata JSON,
  uploaded_at TIMESTAMP,
  version INTEGER
);

-- Query blobs
SELECT
  filename,
  size_bytes / 1024 / 1024 as size_mb,
  content_type,
  uploaded_at
FROM blob_storage
WHERE project_id = (SELECT id FROM projects WHERE slug = 'myapp')
ORDER BY uploaded_at DESC;

-- Find duplicates (same hash)
SELECT content_hash, COUNT(*) as count, SUM(size_bytes) as total_bytes
FROM blob_storage
GROUP BY content_hash
HAVING count > 1;
```

## Best Practices

**1. Compress before upload:**
```bash
gzip large-file.log
templedb storage blob upload myapp large-file.log.gz
```

**2. Use CDN for public assets:**
```bash
templedb storage blob upload myapp public-image.jpg --public
templedb storage blob url myapp public-image.jpg --cdn
```

**3. Set content types:**
```bash
templedb storage blob upload myapp file.pdf --content-type application/pdf
templedb storage blob upload myapp image.png --content-type image/png
```

**4. Tag blobs with metadata:**
```bash
templedb storage blob upload myapp report.pdf --metadata '{"category": "reports", "year": 2026}'
```

**5. Regular cleanup:**
```bash
# Find unused blobs
templedb storage blob list myapp --unused

# Delete blobs older than 90 days
templedb storage blob cleanup myapp --older-than 90d
```

## Storage Costs

**Estimates (as of 2026):**

| Provider | Storage | Egress | API Calls |
|----------|---------|--------|-----------|
| **Local** | Free (disk space) | Free | Free |
| **S3** | $0.023/GB/month | $0.09/GB | $0.0004/1K |
| **Backblaze B2** | $0.005/GB/month | Free (3× storage) | $0.004/10K |
| **Cloudflare R2** | $0.015/GB/month | Free | $0.36/million |

**Example (100GB project):**
- Local: Free
- S3: $2.30/month + egress
- B2: $0.50/month
- R2: $1.50/month

## Commands Reference

```bash
# Setup
templedb storage blob setup --provider <prov> --bucket <name> --region <region>

# Upload
templedb storage blob upload <proj> <file> [--content-type <type>] [--metadata <json>]

# Download
templedb storage blob download <proj> <filename> [--output <path>] [--version <n>]

# List
templedb storage blob list <proj> [--pattern <glob>] [--show-size] [--show-metadata]

# Delete
templedb storage blob delete <proj> <filename> [--all-versions]

# Metadata
templedb storage blob update-metadata <proj> <filename> --metadata <json>

# Versioning
templedb storage blob versions <proj> <filename>

# Migration
templedb storage blob migrate <proj> --from <prov> --to <prov>
templedb storage blob import <proj> <path> [--pattern <glob>]

# Maintenance
templedb storage blob cleanup <proj> [--dry-run] [--older-than <days>]
templedb storage blob verify <proj> --provider <prov>

# CDN
templedb storage blob url <proj> <filename> [--cdn]
```

## Troubleshooting

**"Provider not configured"**
```bash
templedb storage blob setup --provider s3 --bucket my-blobs
```

**"Upload failed: access denied"**
```bash
# Check S3 bucket policy allows PutObject
# Verify access key has correct permissions
```

**"Blob not found"**
```bash
# List all blobs
templedb storage blob list myapp

# Check specific version
templedb storage blob versions myapp filename.pdf
```

**"Out of disk space" (local)**
```bash
# Check usage
du -sh ~/templedb-blobs

# Cleanup old blobs
templedb storage blob cleanup myapp --older-than 90d
```

---

**Next:** [DEPLOYMENT.md](DEPLOYMENT.md), [BACKUP.md](BACKUP.md)
