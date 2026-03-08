# TempleDB Large Binary Blob Strategy

**Version**: 1.0
**Date**: 2026-03-06
**Status**: Design Proposal
**Priority**: P1 (High)

---

## Executive Summary

This document proposes a comprehensive large binary blob storage strategy for TempleDB, inspired by Git LFS but adapted for database-native version control. The strategy addresses current limitations where all file content is stored directly in SQLite, causing memory exhaustion and performance issues with large binary files.

**Key Goals:**
1. Support files larger than 10MB (current hard limit)
2. Prevent memory exhaustion during import/export
3. Enable lazy fetching (download on-demand)
4. Maintain content deduplication
5. Preserve database-first philosophy
6. Seamless Cathedral package integration

---

## Current State Analysis

### Existing Architecture (src/importer/content.py:21-54)

```python
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB hard limit
```

**Current Flow:**
1. File content read into memory
2. SHA-256 hash calculated
3. Content stored in `content_blobs` table (TEXT or BLOB)
4. File references blob via `file_contents.content_hash`

**Problems:**
- Files >10MB silently skipped (returns `None`)
- All content loaded into SQLite → memory bloat
- Cathedral packages include full content → huge archives
- No streaming or chunked operations
- Binary files stored as BLOB in database

---

## Design Principles

1. **Database-First**: Metadata stays in SQLite, blobs stored separately
2. **Content-Addressable**: SHA-256 hash remains primary key
3. **Transparent**: Existing queries work without modification
4. **Opt-In**: Small files (<10MB) use existing path by default
5. **Deduplication**: Identical content stored once, regardless of size
6. **Offline-Capable**: External blobs cached locally, work without network
7. **Cathedral-Compatible**: Large blobs travel with packages

---

## Proposed Architecture

### 1. Three-Tier Storage System

```
┌─────────────────────────────────────────────────────────────┐
│                        SQLite Database                       │
│  ┌────────────────┐           ┌─────────────────┐          │
│  │ content_blobs  │           │ file_contents   │          │
│  │ (metadata)     │◄──────────│ (references)    │          │
│  └────────────────┘           └─────────────────┘          │
│         │                                                    │
│         │ storage_location: 'inline' | 'external' | 'remote'│
└─────────┼────────────────────────────────────────────────────┘
          │
          ├──► 'inline': content_text/content_blob in DB
          │
          ├──► 'external': Local filesystem blobs
          │              ~/.local/share/templedb/blobs/<hash>
          │
          └──► 'remote': Remote blob storage (future)
                        S3, GCS, CDN, etc.
```

### 2. Enhanced content_blobs Schema

```sql
-- Migration: 002_large_blob_support.sql

ALTER TABLE content_blobs ADD COLUMN storage_location TEXT DEFAULT 'inline';
-- Values: 'inline' (in DB), 'external' (local FS), 'remote' (S3/GCS)

ALTER TABLE content_blobs ADD COLUMN external_path TEXT;
-- Path to blob file (for external/remote storage)

ALTER TABLE content_blobs ADD COLUMN chunk_count INTEGER DEFAULT 1;
-- Number of chunks (for streaming large files)

ALTER TABLE content_blobs ADD COLUMN compression TEXT;
-- Compression algorithm: null, 'zstd', 'gzip'

ALTER TABLE content_blobs ADD COLUMN remote_url TEXT;
-- URL for remote storage (future)

ALTER TABLE content_blobs ADD COLUMN fetch_count INTEGER DEFAULT 0;
-- Track access frequency (for caching decisions)

ALTER TABLE content_blobs ADD COLUMN last_fetched_at TEXT;
-- When blob was last accessed

-- Create index for external blobs
CREATE INDEX idx_content_blobs_storage ON content_blobs(storage_location);
CREATE INDEX idx_content_blobs_size ON content_blobs(file_size_bytes);
```

**Migration Strategy**: Backwards compatible - all existing blobs default to `storage_location='inline'`

---

## Configuration & Thresholds

### Size Thresholds (src/config.py additions)

```python
# Large Blob Configuration
BLOB_INLINE_THRESHOLD = int(os.environ.get(
    'TEMPLEDB_BLOB_INLINE_THRESHOLD',
    10 * 1024 * 1024  # 10MB default
))

BLOB_MAX_SIZE = int(os.environ.get(
    'TEMPLEDB_BLOB_MAX_SIZE',
    1024 * 1024 * 1024  # 1GB default
))

BLOB_CHUNK_SIZE = int(os.environ.get(
    'TEMPLEDB_BLOB_CHUNK_SIZE',
    50 * 1024 * 1024  # 50MB chunks for streaming
))

# Blob Storage Paths
BLOB_STORAGE_DIR = os.path.join(DB_DIR, "blobs")
BLOB_CACHE_DIR = os.path.join(DB_DIR, "blob-cache")

# Compression
BLOB_COMPRESSION_ENABLED = os.environ.get(
    'TEMPLEDB_BLOB_COMPRESSION',
    'true'
).lower() in ('true', '1', 'yes')

BLOB_COMPRESSION_THRESHOLD = int(os.environ.get(
    'TEMPLEDB_BLOB_COMPRESSION_THRESHOLD',
    1 * 1024 * 1024  # Compress blobs >1MB
))

# Lazy Fetch
BLOB_LAZY_FETCH = os.environ.get(
    'TEMPLEDB_BLOB_LAZY_FETCH',
    'false'  # Disabled by default for reliability
).lower() in ('true', '1', 'yes')
```

### Decision Matrix

| File Size | Storage Location | Compressed | Notes |
|-----------|-----------------|------------|-------|
| < 10MB | `inline` | No | In database (current behavior) |
| 10MB - 100MB | `external` | Yes (if text/compressible) | Local filesystem |
| 100MB - 1GB | `external` | Yes | Local filesystem, chunked |
| > 1GB | `external` or `remote` | Yes | Requires explicit handling |

**Binary File Types** (already defined in src/importer/content.py:12-19):
- Images: `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.ico`, `.svg`
- Archives: `.zip`, `.tar`, `.gz`, `.bz2`, `.xz`
- Executables: `.exe`, `.dll`, `.so`, `.dylib`
- Fonts: `.woff`, `.woff2`, `.ttf`, `.eot`
- Media: `.mp3`, `.mp4`, `.avi`, `.mov`
- Databases: `.db`, `.sqlite`, `.sqlite3`

---

## Implementation Components

### 1. Enhanced ContentStore (src/importer/content.py)

```python
import zstandard as zstd
import os
from pathlib import Path
from typing import Optional, Tuple

class ContentStore:
    """Enhanced content store with large blob support"""

    def __init__(self, blob_dir: Path = None):
        self.blob_dir = blob_dir or Path(config.BLOB_STORAGE_DIR)
        self.blob_dir.mkdir(parents=True, exist_ok=True)

    def store_content(self, file_path: Path) -> Optional[BlobMetadata]:
        """
        Store file content, automatically choosing storage strategy

        Returns BlobMetadata with:
        - storage_location: 'inline' | 'external'
        - content_hash: SHA-256
        - file_size: bytes
        - compression: algorithm used
        - external_path: path if external storage
        """
        file_size = file_path.stat().st_size

        # Size validation
        if file_size > config.BLOB_MAX_SIZE:
            raise ValueError(
                f"File too large: {file_size} bytes "
                f"(max: {config.BLOB_MAX_SIZE})"
            )

        # Calculate hash while reading
        content_hash = self._hash_file(file_path)

        # Decide storage strategy
        if file_size < config.BLOB_INLINE_THRESHOLD:
            return self._store_inline(file_path, content_hash)
        else:
            return self._store_external(file_path, content_hash)

    def _store_inline(self, file_path: Path, content_hash: str) -> BlobMetadata:
        """Store small files directly in database"""
        # Existing logic from ContentStore.read_file_content()
        # Returns metadata with storage_location='inline'
        ...

    def _store_external(self, file_path: Path, content_hash: str) -> BlobMetadata:
        """Store large files on filesystem"""
        # Create blob directory using first 2 chars of hash (sharding)
        # e.g., hash abc123... → blobs/ab/abc123...
        blob_subdir = self.blob_dir / content_hash[:2]
        blob_subdir.mkdir(exist_ok=True)

        blob_path = blob_subdir / content_hash

        # Compress if beneficial
        if self._should_compress(file_path):
            blob_path = blob_path.with_suffix('.zst')
            self._compress_file(file_path, blob_path)
            compression = 'zstd'
        else:
            # Hard link or copy to blob storage
            try:
                os.link(file_path, blob_path)
            except OSError:
                shutil.copy2(file_path, blob_path)
            compression = None

        return BlobMetadata(
            storage_location='external',
            content_hash=content_hash,
            file_size=file_path.stat().st_size,
            compression=compression,
            external_path=str(blob_path.relative_to(self.blob_dir))
        )

    def retrieve_content(self, content_hash: str,
                        storage_location: str,
                        external_path: Optional[str] = None,
                        compression: Optional[str] = None) -> bytes:
        """
        Retrieve blob content from storage

        Handles all storage locations transparently
        """
        if storage_location == 'inline':
            # Query database (existing behavior)
            return self._fetch_inline(content_hash)

        elif storage_location == 'external':
            # Read from local filesystem
            blob_path = self.blob_dir / external_path

            if not blob_path.exists():
                raise FileNotFoundError(
                    f"Blob not found: {content_hash} "
                    f"(expected at {blob_path})"
                )

            if compression == 'zstd':
                return self._decompress_file(blob_path)
            else:
                return blob_path.read_bytes()

        elif storage_location == 'remote':
            # Future: Fetch from S3/GCS
            # For now: Check local cache first
            cache_path = self._get_cache_path(content_hash)
            if cache_path.exists():
                return cache_path.read_bytes()

            # Download from remote
            # return self._fetch_remote(remote_url, content_hash)
            raise NotImplementedError("Remote blob storage not yet implemented")

    def _should_compress(self, file_path: Path) -> bool:
        """Determine if file should be compressed"""
        # Don't compress already-compressed formats
        COMPRESSED_EXTENSIONS = {
            '.zip', '.gz', '.bz2', '.xz', '.zst',
            '.jpg', '.jpeg', '.png', '.gif',
            '.mp3', '.mp4', '.avi', '.mov'
        }

        if file_path.suffix.lower() in COMPRESSED_EXTENSIONS:
            return False

        file_size = file_path.stat().st_size
        return file_size >= config.BLOB_COMPRESSION_THRESHOLD

    def _compress_file(self, source: Path, dest: Path):
        """Compress file using zstandard"""
        cctx = zstd.ZstdCompressor(level=3)
        with open(source, 'rb') as src, open(dest, 'wb') as dst:
            cctx.copy_stream(src, dst)

    def _decompress_file(self, source: Path) -> bytes:
        """Decompress zstandard file"""
        dctx = zstd.ZstdDecompressor()
        with open(source, 'rb') as src:
            return dctx.decompress(src.read())

    def _hash_file(self, file_path: Path) -> str:
        """Calculate SHA-256 hash of file (streaming)"""
        import hashlib
        hasher = hashlib.sha256()

        with open(file_path, 'rb') as f:
            # Read in chunks to handle large files
            while chunk := f.read(8192):
                hasher.update(chunk)

        return hasher.hexdigest()
```

### 2. Blob Management Commands

```bash
# Check blob storage status
./templedb blob status [project]
# Shows: inline count, external count, total size, compression ratio

# List large blobs
./templedb blob list --min-size 10MB [project]

# Migrate inline blobs to external
./templedb blob migrate --to-external --min-size 10MB [project]

# Migrate external blobs to inline
./templedb blob migrate --to-inline --max-size 10MB [project]

# Compress external blobs
./templedb blob compress [project]

# Verify blob integrity
./templedb blob verify [project]
# Checks: hash matches, file exists, readable

# Prune unreferenced blobs
./templedb blob prune --dry-run
./templedb blob prune  # Actually delete

# Cache statistics
./templedb blob cache-stats
# Shows: cache size, hit rate, evictions
```

### 3. Cathedral Package Integration

**Enhanced Package Structure:**

```
project.cathedral/
├── manifest.json          # Package metadata
├── project.json           # Project metadata
├── files/                 # File metadata
│   ├── manifest.json
│   ├── 1.json
│   └── ...
├── blobs/                 # 🆕 External blob storage
│   ├── manifest.json      # Blob index
│   ├── ab/
│   │   └── abc123....zst  # Content-addressed blobs
│   ├── cd/
│   │   └── cdef456...zst
│   └── ...
├── vcs/                   # Version control data
└── environments/          # Nix environments
```

**blobs/manifest.json** (new):
```json
{
  "format_version": "1.0",
  "compression": "zstd",
  "total_blobs": 42,
  "total_size_bytes": 524288000,
  "compressed_size_bytes": 312172800,
  "blobs": [
    {
      "hash": "abc123...",
      "size": 52428800,
      "compressed_size": 31457280,
      "compression": "zstd",
      "path": "ab/abc123....zst",
      "content_type": "binary"
    }
  ]
}
```

**Export behavior:**
- Small blobs (<10MB): Inline in database, exported as before
- Large blobs (>10MB): External files, copied to `blobs/` directory
- Compression: Applied during export if not already compressed
- Lazy export option: `--skip-large-blobs` creates manifest without content

**Import behavior:**
- Small blobs: Imported into database (inline)
- Large blobs: Stored in `~/.local/share/templedb/blobs/`
- Deduplication: Check if blob already exists before copying
- Streaming: Process blobs one at a time to avoid memory spike

### 4. Lazy Fetching & Caching

**Concept**: For projects with many large binaries (e.g., ML models, media assets), allow importing metadata without downloading all blobs.

```bash
# Import without large blobs
./templedb cathedral import project.cathedral --lazy-fetch

# This imports:
# ✓ Project metadata
# ✓ File tree structure
# ✓ VCS history
# ✓ Inline blobs (<10MB)
# ⊘ External blobs (>10MB) - only metadata

# Fetch specific blob on demand
./templedb blob fetch <hash>

# Fetch all blobs for a file
./templedb blob fetch --file src/assets/logo.png

# Fetch all blobs (hydrate)
./templedb blob fetch-all [project]
```

**Use Cases:**
1. **CI/CD pipelines**: Import project structure, only fetch blobs needed for build
2. **Code review**: Review code without downloading media assets
3. **Partial clone**: Work on subset of project files

**Cache Management:**
```python
# LRU cache for remote blobs
BLOB_CACHE_MAX_SIZE = 10 * 1024 * 1024 * 1024  # 10GB
BLOB_CACHE_EVICTION_POLICY = 'lru'  # lru, lfu, fifo
```

---

## Migration Path

### Phase 1: Foundation (Week 1-2)

**Goal**: Add external blob storage without breaking existing functionality

- [ ] Create migration `002_large_blob_support.sql`
- [ ] Add configuration to `src/config.py`
- [ ] Enhance `ContentStore` class
- [ ] Update `content_blobs` table schema
- [ ] Add blob storage directory structure
- [ ] Write unit tests

**Backwards Compatibility**: All existing blobs remain inline, new blobs use threshold

### Phase 2: Core Features (Week 3-4)

**Goal**: Essential blob management capabilities

- [ ] Implement `./templedb blob status` command
- [ ] Implement `./templedb blob verify` command
- [ ] Add compression support (zstd)
- [ ] Add blob migration tools
- [ ] Update Cathedral export/import
- [ ] Integration tests

### Phase 3: Advanced Features (Week 5-6)

**Goal**: Performance and optimization

- [ ] Implement lazy fetching
- [ ] Add blob caching layer
- [ ] Implement `./templedb blob prune` (GC)
- [ ] Add streaming for huge files (>1GB)
- [ ] Performance benchmarks
- [ ] Documentation

### Phase 4: Remote Storage (Future)

**Goal**: Network-backed blob storage (optional)

- [ ] S3 backend implementation
- [ ] GCS backend implementation
- [ ] CDN integration
- [ ] Multi-machine sync
- [ ] Access control (for shared storage)

---

## Edge Cases & Error Handling

### 1. Missing External Blobs

**Scenario**: External blob referenced in DB but file missing

```python
# Detection
def verify_blob_exists(content_hash: str, external_path: str) -> bool:
    blob_path = BLOB_STORAGE_DIR / external_path
    return blob_path.exists()

# Recovery strategies
1. Mark blob as 'missing' in database
2. Attempt recovery from Cathedral backup
3. Re-import from original source
4. Fail gracefully with clear error message
```

### 2. Corrupted Blobs

**Scenario**: Blob exists but hash doesn't match

```python
def verify_blob_integrity(content_hash: str, blob_path: Path) -> bool:
    actual_hash = ContentStore._hash_file(blob_path)
    return actual_hash == content_hash

# On corruption:
1. Log error with file details
2. Quarantine corrupted blob
3. Attempt restoration from backup
4. Notify user with recovery steps
```

### 3. Disk Space Exhaustion

**Scenario**: Not enough space for external blob

```python
def check_available_space(required_bytes: int) -> bool:
    import shutil
    stat = shutil.disk_usage(BLOB_STORAGE_DIR)
    return stat.free >= required_bytes * 1.1  # 10% buffer

# Before storing large blob:
if not check_available_space(file_size):
    raise DiskSpaceError(
        f"Insufficient disk space for blob "
        f"(need {file_size} bytes)"
    )
```

### 4. Orphaned Blobs

**Scenario**: Blob exists on disk but no database references

```python
# Garbage collection
./templedb blob prune --dry-run

# Algorithm:
1. Scan all blobs in storage directory
2. Check if each blob is referenced in content_blobs
3. List orphaned blobs (unreferenced)
4. Optionally delete with confirmation
```

### 5. Concurrent Access

**Scenario**: Multiple processes accessing same blob

```python
# Use file locking for writes
import fcntl

def write_blob_atomic(blob_path: Path, content: bytes):
    temp_path = blob_path.with_suffix('.tmp')

    with open(temp_path, 'wb') as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        f.write(content)
        f.flush()
        os.fsync(f.fileno())

    # Atomic rename
    temp_path.rename(blob_path)
```

---

## Performance Characteristics

### Storage Efficiency

**Expected Improvements:**

| Scenario | Before | After | Improvement |
|----------|--------|-------|-------------|
| 100 files, 50MB each | 5GB in SQLite | 50MB DB + 5GB blobs | DB 100x smaller |
| 1000 files, 10MB each (50% duplicates) | 10GB in SQLite | 50MB DB + 5GB blobs | 50% dedup + external |
| ML project with models | 5GB+ SQLite | 100MB DB + 5GB blobs | Faster queries |

**Compression Ratios** (typical):
- Text files: 60-70% reduction
- JSON/XML: 70-80% reduction
- Binary executables: 20-30% reduction
- Already compressed (images/video): 0-5% reduction

### Import/Export Performance

**Before** (all inline):
- Import 1GB project: ~30s, memory spike to 2GB
- Export 1GB project: ~40s, memory spike to 2GB

**After** (external blobs):
- Import 1GB project: ~15s, memory stable at 200MB (streaming)
- Export 1GB project: ~20s, memory stable at 200MB (streaming)

**Lazy fetch**:
- Import metadata only: ~3s, 50MB memory
- Fetch blob on-demand: ~1s per 100MB blob

---

## Security Considerations

### 1. Path Traversal Prevention

```python
def sanitize_blob_path(external_path: str) -> Path:
    """Prevent path traversal attacks"""
    # external_path should be: "ab/abc123..."
    # NOT: "../../etc/passwd"

    blob_path = (BLOB_STORAGE_DIR / external_path).resolve()

    # Ensure resolved path is within blob directory
    if not blob_path.is_relative_to(BLOB_STORAGE_DIR):
        raise SecurityError("Invalid blob path: path traversal detected")

    return blob_path
```

### 2. Hash Verification

Always verify content hash matches filename and database record:

```python
def retrieve_and_verify(content_hash: str, external_path: str) -> bytes:
    content = retrieve_content(content_hash, 'external', external_path)

    actual_hash = hashlib.sha256(content).hexdigest()
    if actual_hash != content_hash:
        raise IntegrityError(
            f"Blob corruption detected: {content_hash} "
            f"(expected {content_hash}, got {actual_hash})"
        )

    return content
```

### 3. Access Control (Future)

For remote blob storage:
- Pre-signed URLs with expiration
- Role-based access (read/write permissions)
- Audit logging for blob access
- Encryption at rest and in transit

---

## User Experience

### Progressive Enhancement

**Default behavior** (no configuration):
- Files <10MB: Inline (existing behavior)
- Files >10MB: External storage (transparent)
- No user action required

**Power user features**:
- Adjust thresholds via environment variables
- Opt into lazy fetching for specific projects
- Manual blob migration for optimization
- Compression tuning

### Error Messages

**Good error messages are critical:**

```python
# Bad
"Error: Blob not found"

# Good
"Blob not found: abc123...
  Expected location: ~/.local/share/templedb/blobs/ab/abc123...

  This blob may have been deleted or corrupted.

  To recover:
  1. Check if blob exists in a Cathedral backup:
     ./templedb cathedral import backup.cathedral --verify

  2. Re-import from original source:
     ./templedb project sync myproject

  3. Or remove the file from tracking:
     ./templedb vcs rm src/large-file.bin
"
```

### CLI Output

```bash
$ ./templedb blob status myproject

📊 Blob Storage Status - myproject
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Inline Blobs (in database):
  Count: 1,247 files
  Size: 87.3 MB (uncompressed)

External Blobs (on filesystem):
  Count: 42 files
  Size: 2.1 GB (uncompressed)
  Compressed: 1.3 GB (38% reduction)
  Location: ~/.local/share/templedb/blobs/

Remote Blobs (not yet fetched):
  Count: 0 files

Total Storage: 1.39 GB
Database Size: 127 MB
Blob Directory: 1.3 GB

Deduplication: 156 duplicate blobs detected (saving 384 MB)

Recommendations:
  • Run './templedb blob compress' to compress 12 uncompressed blobs
  • Run './templedb blob prune' to remove 3 orphaned blobs (42 MB)
```

---

## Testing Strategy

### Unit Tests

```python
# tests/test_large_blobs.py

def test_inline_storage_for_small_files():
    """Files <10MB stored inline"""
    ...

def test_external_storage_for_large_files():
    """Files >10MB stored externally"""
    ...

def test_content_deduplication_across_storage_types():
    """Same content hash, regardless of storage location"""
    ...

def test_compression_applied_correctly():
    """Compressible files are compressed"""
    ...

def test_retrieval_from_external_storage():
    """Can retrieve and verify external blobs"""
    ...

def test_missing_blob_error_handling():
    """Clear error when blob missing"""
    ...

def test_corrupted_blob_detection():
    """Hash mismatch detected"""
    ...
```

### Integration Tests

```python
# tests/test_large_blob_integration.py

def test_import_project_with_large_files():
    """Import project containing files >10MB"""
    ...

def test_cathedral_export_with_large_blobs():
    """Export creates blobs/ directory"""
    ...

def test_cathedral_import_with_large_blobs():
    """Import restores external blobs correctly"""
    ...

def test_cathedral_roundtrip():
    """Export → Import preserves all blob data"""
    ...

def test_lazy_fetch_workflow():
    """Import without blobs, fetch on demand"""
    ...

def test_blob_migration():
    """Migrate inline → external and back"""
    ...
```

### Performance Tests

```python
# tests/test_blob_performance.py

def test_import_1gb_project_memory_usage():
    """Memory stays <500MB during import"""
    assert max_memory_used < 500 * 1024 * 1024
    ...

def test_import_1000_files_speed():
    """Import completes in reasonable time"""
    assert elapsed_time < 60  # seconds
    ...

def test_compression_ratio():
    """Compression achieves expected ratio"""
    assert compressed_size / original_size < 0.5
    ...
```

---

## Documentation Updates

### User-Facing Documentation

1. **docs/LARGE_FILES.md** - Complete guide to large file handling
2. **docs/BLOB_STORAGE.md** - Technical details of blob storage
3. **README.md** - Update with blob storage features
4. **EXAMPLES.md** - Add examples with large files

### Developer Documentation

1. **ARCHITECTURE.md** - Update with blob storage architecture
2. **CONTRIBUTING.md** - Add blob testing requirements
3. **MIGRATIONS.md** - Document migration 002

---

## Future Enhancements (v2.0+)

### 1. Smart Caching

```python
# Predict which blobs user will need
# Pre-fetch based on access patterns
# ML-based prefetching
```

### 2. Partial Blob Fetching

```python
# Fetch byte ranges (HTTP Range requests)
# Useful for streaming video, reading large logs
./templedb blob fetch <hash> --range=0-1024
```

### 3. Blob Deduplication Across Projects

```python
# Global blob storage (not per-project)
# Same blob used by multiple projects
# Saves disk space
```

### 4. Blob Analytics

```python
# Track blob access patterns
# Identify unused blobs
# Optimize storage tiers
./templedb blob analytics
```

### 5. Remote Sync

```python
# Sync blobs between machines
# Like git push/pull but for blobs
./templedb blob push origin
./templedb blob pull origin
```

---

## Success Metrics

**Phase 1 (Foundation) Success:**
- ✅ Can store files up to 1GB
- ✅ Memory usage stays <500MB during import
- ✅ All existing tests pass (backwards compatible)
- ✅ Cathedral export/import works with external blobs

**Phase 2 (Core Features) Success:**
- ✅ Compression reduces storage by >30%
- ✅ Blob verification detects corruption
- ✅ Clear error messages for all failure modes
- ✅ Documentation complete

**Phase 3 (Advanced) Success:**
- ✅ Lazy fetch reduces import time by 80%
- ✅ Blob pruning reclaims unused space
- ✅ Performance benchmarks meet targets
- ✅ Production-ready

---

## Summary

This strategy provides a comprehensive, pragmatic approach to large binary blob storage in TempleDB:

✅ **Solves current limitations**: Removes 10MB hard limit, prevents memory exhaustion
✅ **Preserves philosophy**: Database-first, content-addressable, offline-capable
✅ **Backwards compatible**: Existing projects work unchanged
✅ **Cathedral integration**: Large blobs travel with packages
✅ **Performance**: 100x smaller SQLite DB, streaming operations
✅ **Extensible**: Clear path to remote storage (S3, GCS)
✅ **User-friendly**: Transparent operation, clear errors, optional lazy fetch

**Estimated effort**: 4-6 weeks for Phase 1-3 (P1 features)

**Next steps**: Review proposal, create implementation tickets, begin Phase 1 migration
