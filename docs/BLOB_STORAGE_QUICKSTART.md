# Blob Storage Quick Start Guide

Quick reference for using TempleDB's large blob storage (Phase 1).

---

## Overview

TempleDB now supports files up to 1GB with automatic storage tier selection:
- **< 10MB**: Stored in database (inline)
- **10MB - 1GB**: Stored on filesystem (external)
- **> 1GB**: Rejected (configurable)

---

## For Developers

### Using New API (Recommended)

```python
from pathlib import Path
from importer.content import ContentStore, BlobMetadata

# Initialize
store = ContentStore()

# Store a file (automatic strategy)
metadata = store.store_content(Path("myfile.zip"))

if metadata:
    print(f"Hash: {metadata.content_hash}")
    print(f"Location: {metadata.storage_location}")
    print(f"Size: {metadata.file_size} bytes")

    # For external blobs
    if metadata.storage_location == 'external':
        # Retrieve content
        content = store.retrieve_content(
            metadata.content_hash,
            'external',
            metadata.external_path
        )

        # Verify integrity
        is_valid, error = store.verify_blob(
            metadata.content_hash,
            metadata.external_path
        )
        if not is_valid:
            print(f"Corruption: {error}")
```

### Using Legacy API (Still Works)

```python
from pathlib import Path
from importer.content import ContentStore

# Old method (for files < 10MB)
file_content = ContentStore.read_file_content(Path("small.txt"))

if file_content:
    print(file_content.hash_sha256)
    print(file_content.content_text)
```

---

## Configuration

### Environment Variables

```bash
# Storage thresholds
export TEMPLEDB_BLOB_INLINE_THRESHOLD=$((10*1024*1024))  # 10MB
export TEMPLEDB_BLOB_MAX_SIZE=$((1024*1024*1024))        # 1GB

# Compression (Phase 2)
export TEMPLEDB_BLOB_COMPRESSION=true
export TEMPLEDB_BLOB_COMPRESSION_THRESHOLD=$((1*1024*1024))

# Cache settings
export TEMPLEDB_BLOB_CACHE_MAX_SIZE=$((10*1024*1024*1024))
```

### Blob Storage Location

```
~/.local/share/templedb/
├── templedb.sqlite          # Database (metadata)
├── blobs/                   # External blob storage
│   ├── ab/abc123...
│   ├── cd/cdef456...
│   └── ...
└── blob-cache/              # Remote blob cache (Phase 4)
```

---

## Database Queries

### Check Storage Statistics

```sql
-- Quick stats by storage type
SELECT * FROM blob_storage_stats;

-- Find large inline blobs
SELECT * FROM migratable_inline_blobs;

-- List all external blobs
SELECT * FROM external_blobs_view;

-- Storage distribution
SELECT storage_location,
       COUNT(*) as count,
       ROUND(SUM(file_size_bytes)/1024.0/1024.0, 2) as total_mb
FROM content_blobs
GROUP BY storage_location;
```

### Find Specific Blobs

```sql
-- Find blob by hash
SELECT * FROM content_blobs WHERE hash_sha256 = 'abc123...';

-- Find large files
SELECT hash_sha256, file_size_bytes, storage_location
FROM content_blobs
WHERE file_size_bytes > 10485760  -- >10MB
ORDER BY file_size_bytes DESC;

-- Find external blobs
SELECT * FROM content_blobs WHERE storage_location = 'external';
```

---

## Migration Guide

### Apply Migration 002

```bash
# Backup database (recommended)
cp ~/.local/share/templedb/templedb.sqlite{,.backup}

# Apply migration
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  < migrations/002_large_blob_support.sql

# Verify
python3 tests/test_migration_002.py
```

### Verify Migration

```bash
# Check schema
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "PRAGMA table_info(content_blobs)"

# Check statistics
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM blob_storage_stats"
```

---

## Troubleshooting

### Blob Not Found

```python
# Check if blob exists
blob_path = Path(config.BLOB_STORAGE_DIR) / external_path
if not blob_path.exists():
    print(f"Blob missing: {blob_path}")
    # Recovery options:
    # 1. Restore from Cathedral backup
    # 2. Re-import from source
```

### Verify Blob Integrity

```python
store = ContentStore()
is_valid, error = store.verify_blob(content_hash, external_path)

if not is_valid:
    print(f"Corruption detected: {error}")
    # Recovery: Re-import file
```

### Check Disk Space

```bash
# Check blob storage size
du -sh ~/.local/share/templedb/blobs/

# Check database size
du -sh ~/.local/share/templedb/templedb.sqlite
```

---

## Best Practices

### When to Use External Storage

✅ **Good for external storage:**
- Large binary files (images, videos, archives)
- ML models and datasets
- Build artifacts
- Large log files

❌ **Keep inline:**
- Source code (< 10MB)
- Configuration files
- Small assets
- Frequently queried content

### Performance Tips

1. **Use streaming for large files**
   - `calculate_hash_streaming()` instead of loading into memory
   - Let `store_content()` handle strategy automatically

2. **Batch operations**
   - Process multiple files without reloading
   - Use single ContentStore instance

3. **Verify critical blobs**
   - Run periodic integrity checks
   - Verify after imports/exports

### Safety Tips

1. **Always backup before migration**
2. **Test migration on copy first**
3. **Verify blob integrity regularly**
4. **Monitor disk space**
5. **Keep Cathedral backups**

---

## Testing

### Run Unit Tests

```bash
# All blob storage tests
python3 tests/test_large_blob_storage.py

# Migration tests
python3 tests/test_migration_002.py

# Both
python3 tests/test_large_blob_storage.py && \
python3 tests/test_migration_002.py
```

### Manual Testing

```python
# Test with real file
store = ContentStore()

# Create large test file
test_file = Path("/tmp/large.bin")
test_file.write_bytes(b'X' * (20 * 1024 * 1024))  # 20MB

# Store and verify
metadata = store.store_content(test_file)
assert metadata.storage_location == 'external'

content = store.retrieve_content(
    metadata.content_hash,
    'external',
    metadata.external_path
)
assert len(content) == 20 * 1024 * 1024

is_valid, _ = store.verify_blob(
    metadata.content_hash,
    metadata.external_path
)
assert is_valid
```

---

## What's Coming (Phase 2)

🔜 **Compression** (zstd)
- Automatic compression for large blobs
- 30-70% space savings
- Transparent decompression

🔜 **Blob Commands**
- `./templedb blob status` - Storage stats
- `./templedb blob verify` - Integrity check
- `./templedb blob migrate` - Move inline↔external
- `./templedb blob list` - List large blobs
- `./templedb blob prune` - Garbage collection

🔜 **Cathedral Integration**
- Export with external blobs
- Import with deduplication
- Blob manifest in packages

---

## Getting Help

### Documentation
- `docs/LARGE_BLOB_STRATEGY.md` - Complete design
- `docs/LARGE_BLOB_PHASE1_COMPLETE.md` - Implementation details
- `PHASE1_IMPLEMENTATION_SUMMARY.md` - Quick summary

### Source Code
- `src/importer/content.py` - ContentStore implementation
- `src/config.py` - Configuration settings
- `migrations/002_large_blob_support.sql` - Database schema

### Tests
- `tests/test_large_blob_storage.py` - 23 unit tests
- `tests/test_migration_002.py` - 8 integration tests

---

## Quick Reference

| Task | Command/Code |
|------|--------------|
| Store file | `store.store_content(path)` |
| Retrieve blob | `store.retrieve_content(hash, 'external', path)` |
| Verify integrity | `store.verify_blob(hash, path)` |
| Check stats | `SELECT * FROM blob_storage_stats` |
| Find large blobs | `SELECT * FROM migratable_inline_blobs` |
| Apply migration | `sqlite3 db < migrations/002_large_blob_support.sql` |
| Run tests | `python3 tests/test_large_blob_storage.py` |

---

**Phase 1 is complete and production-ready!** 🚀
