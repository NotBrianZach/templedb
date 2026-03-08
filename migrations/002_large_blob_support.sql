-- Migration: Large Blob Support (Phase 1)
-- Date: 2026-03-06
-- Purpose: Add external blob storage capability for files >10MB
--
-- This migration adds columns to content_blobs to support:
-- 1. External filesystem storage
-- 2. Compression metadata
-- 3. Remote storage (future)
-- 4. Access tracking
--
-- Backwards Compatible: All existing blobs default to storage_location='inline'

-- =============================================================================
-- STEP 1: Add new columns to content_blobs table
-- =============================================================================

-- Storage location: 'inline' (in DB), 'external' (filesystem), 'remote' (S3/GCS)
ALTER TABLE content_blobs ADD COLUMN storage_location TEXT DEFAULT 'inline' CHECK(storage_location IN ('inline', 'external', 'remote'));

-- Path to external blob file (relative to blob storage directory)
-- Example: 'ab/abc123...' or 'ab/abc123....zst' (compressed)
ALTER TABLE content_blobs ADD COLUMN external_path TEXT;

-- Number of chunks (for streaming large files, future use)
ALTER TABLE content_blobs ADD COLUMN chunk_count INTEGER DEFAULT 1;

-- Compression algorithm: NULL, 'zstd', 'gzip'
ALTER TABLE content_blobs ADD COLUMN compression TEXT CHECK(compression IS NULL OR compression IN ('zstd', 'gzip'));

-- Remote URL for remote storage (future)
ALTER TABLE content_blobs ADD COLUMN remote_url TEXT;

-- Access tracking for cache eviction decisions
ALTER TABLE content_blobs ADD COLUMN fetch_count INTEGER DEFAULT 0;
ALTER TABLE content_blobs ADD COLUMN last_fetched_at TEXT;

-- =============================================================================
-- STEP 2: Create indexes for performance
-- =============================================================================

-- Index for querying by storage location
CREATE INDEX IF NOT EXISTS idx_content_blobs_storage_location ON content_blobs(storage_location);

-- Index for finding large blobs (already exists but let's be explicit)
-- DROP and recreate to ensure it exists
DROP INDEX IF EXISTS idx_content_blobs_size;
CREATE INDEX idx_content_blobs_size ON content_blobs(file_size_bytes);

-- Index for external blobs (for verification and cleanup)
CREATE INDEX IF NOT EXISTS idx_content_blobs_external_path ON content_blobs(external_path) WHERE external_path IS NOT NULL;

-- Index for access patterns (for cache optimization)
CREATE INDEX IF NOT EXISTS idx_content_blobs_fetch_count ON content_blobs(fetch_count);

-- =============================================================================
-- STEP 3: Create views for blob statistics
-- =============================================================================

-- View for blob storage statistics
CREATE VIEW IF NOT EXISTS blob_storage_stats AS
SELECT
    storage_location,
    COUNT(*) as blob_count,
    SUM(file_size_bytes) as total_size_bytes,
    AVG(file_size_bytes) as avg_size_bytes,
    MIN(file_size_bytes) as min_size_bytes,
    MAX(file_size_bytes) as max_size_bytes,
    COUNT(CASE WHEN compression IS NOT NULL THEN 1 END) as compressed_count
FROM content_blobs
GROUP BY storage_location;

-- View for external blobs needing verification
CREATE VIEW IF NOT EXISTS external_blobs_view AS
SELECT
    hash_sha256,
    external_path,
    file_size_bytes,
    compression,
    created_at,
    fetch_count,
    last_fetched_at
FROM content_blobs
WHERE storage_location = 'external';

-- View for large inline blobs that could be migrated
CREATE VIEW IF NOT EXISTS migratable_inline_blobs AS
SELECT
    hash_sha256,
    file_size_bytes,
    content_type,
    reference_count,
    created_at
FROM content_blobs
WHERE storage_location = 'inline'
  AND file_size_bytes > 10485760  -- 10MB threshold
ORDER BY file_size_bytes DESC;

-- =============================================================================
-- STEP 4: Create triggers for access tracking
-- =============================================================================

-- Trigger to update fetch count when blob is accessed
-- Note: This will be called from application code, not automatically
-- But we define the structure here for consistency

-- =============================================================================
-- STEP 5: Validation and verification queries
-- =============================================================================

-- These queries verify the migration was successful

-- SELECT 'Migration 002: Large Blob Support' as info;

-- Check all existing blobs are marked as inline
-- SELECT COUNT(*) as inline_blob_count
-- FROM content_blobs
-- WHERE storage_location = 'inline';
-- -- Should equal total blob count

-- Check new columns exist
-- SELECT
--     hash_sha256,
--     storage_location,
--     external_path,
--     compression,
--     chunk_count,
--     fetch_count
-- FROM content_blobs
-- LIMIT 1;

-- Check indexes were created
-- SELECT name, sql
-- FROM sqlite_master
-- WHERE type = 'index'
--   AND name LIKE '%content_blobs%';

-- Check views were created
-- SELECT name
-- FROM sqlite_master
-- WHERE type = 'view'
--   AND name LIKE '%blob%';

-- =============================================================================
-- ROLLBACK INSTRUCTIONS (if needed)
-- =============================================================================

-- To rollback this migration (SQLite doesn't support DROP COLUMN easily):
-- 1. Create new content_blobs table without new columns
-- 2. Copy data from old table
-- 3. Drop old table and rename new one
-- 4. Recreate triggers and foreign keys
--
-- Alternatively, the new columns can be left unused (they default to safe values)
-- and won't affect existing functionality since all existing blobs are 'inline'

-- =============================================================================
-- NOTES
-- =============================================================================

-- Backwards Compatibility:
-- - All existing blobs have storage_location='inline' (default)
-- - Existing queries work unchanged (they ignore new columns)
-- - New columns are NULL or have safe defaults
-- - Content deduplication still works (hash_sha256 is still primary key)
--
-- Storage Location Decision:
-- - storage_location='inline': content_text or content_blob contains data
-- - storage_location='external': external_path points to file on disk
-- - storage_location='remote': remote_url points to blob (+ local cache)
--
-- External Path Format:
-- - Stored as relative path: 'ab/abc123...' or 'ab/abc123....zst'
-- - Base directory: ~/.local/share/templedb/blobs/
-- - Full path: ~/.local/share/templedb/blobs/ab/abc123...
-- - First 2 chars of hash used for sharding (like git objects)
--
-- Compression:
-- - NULL: No compression
-- - 'zstd': Zstandard compression (fast, good ratio)
-- - 'gzip': Gzip compression (universal, slower)
--
-- Access Tracking:
-- - fetch_count: Number of times blob was accessed
-- - last_fetched_at: Timestamp of last access
-- - Used for cache eviction decisions (LRU, LFU)
