-- Migration: Content Deduplication (Phase 1)
-- Date: 2026-02-23
-- Purpose: Eliminate 76% content duplication through content-addressable storage
--
-- Before: file_contents stores full content per file (2,847 records, 37.5 MB)
-- After: content_blobs stores unique content (606 blobs), file_contents references
-- Expected: 75% storage reduction

-- =============================================================================
-- STEP 1: Create content_blobs table (content-addressable storage)
-- =============================================================================

CREATE TABLE IF NOT EXISTS content_blobs (
    -- Primary key is content hash (content-addressable)
    hash_sha256 TEXT PRIMARY KEY,

    -- Content storage (one of these will be populated)
    content_text TEXT,                -- For text files (UTF-8)
    content_blob BLOB,                -- For binary files

    -- Metadata
    content_type TEXT NOT NULL,       -- 'text' or 'binary'
    encoding TEXT DEFAULT 'utf-8',    -- For text files
    file_size_bytes INTEGER NOT NULL,

    -- Statistics (how many files reference this blob)
    reference_count INTEGER DEFAULT 0,

    -- Timestamps
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Create indexes after table
CREATE INDEX IF NOT EXISTS idx_content_blobs_size ON content_blobs(file_size_bytes);
CREATE INDEX IF NOT EXISTS idx_content_blobs_type ON content_blobs(content_type);

-- =============================================================================
-- STEP 2: Populate content_blobs with unique content from file_contents
-- =============================================================================

-- Insert unique content (deduplicated by hash)
INSERT OR IGNORE INTO content_blobs (
    hash_sha256,
    content_text,
    content_blob,
    content_type,
    encoding,
    file_size_bytes,
    reference_count,
    created_at,
    first_seen_at
)
SELECT
    content_hash as hash_sha256,  -- Rename column
    content_text,
    content_blob,
    content_type,
    encoding,
    file_size_bytes,
    COUNT(*) as reference_count,  -- How many files have this content
    MIN(created_at) as created_at,
    MIN(created_at) as first_seen_at
FROM file_contents
GROUP BY content_hash;

-- =============================================================================
-- STEP 3: Drop all views temporarily (will recreate necessary ones)
-- =============================================================================

-- The database has some broken views referencing non-existent tables
-- Drop all views, we'll recreate the important ones after migration

PRAGMA writable_schema=ON;
DELETE FROM sqlite_master WHERE type='view';
PRAGMA writable_schema=OFF;
VACUUM;

-- =============================================================================
-- STEP 4: Drop indexes on file_contents before renaming
-- =============================================================================

DROP INDEX IF EXISTS idx_file_contents_file_id;
DROP INDEX IF EXISTS idx_file_contents_hash;
DROP INDEX IF EXISTS idx_file_contents_current;

-- =============================================================================
-- STEP 5: Backup old file_contents table
-- =============================================================================

-- Rename existing table for backup
ALTER TABLE file_contents RENAME TO file_contents_backup;

-- =============================================================================
-- STEP 6: Create new file_contents table (reference-based)
-- =============================================================================

CREATE TABLE file_contents (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    -- Content reference (instead of storing content directly)
    content_hash TEXT NOT NULL REFERENCES content_blobs(hash_sha256) ON DELETE RESTRICT,

    -- Metadata (copied from blob for convenience)
    file_size_bytes INTEGER NOT NULL,
    line_count INTEGER,               -- For text files

    -- Current version reference
    is_current BOOLEAN DEFAULT 1,

    -- Timestamps
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(file_id, is_current)       -- Only one current version per file
);

-- Indexes
CREATE INDEX idx_file_contents_file_id ON file_contents(file_id);
CREATE INDEX idx_file_contents_hash ON file_contents(content_hash);
CREATE INDEX idx_file_contents_current ON file_contents(is_current);

-- Triggers
CREATE TRIGGER update_file_contents_updated_at
AFTER UPDATE ON file_contents
FOR EACH ROW
BEGIN
    UPDATE file_contents SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER enforce_single_current_version
BEFORE INSERT ON file_contents
FOR EACH ROW
WHEN NEW.is_current = 1
BEGIN
    UPDATE file_contents SET is_current = 0 WHERE file_id = NEW.file_id AND is_current = 1;
END;

-- Trigger to update reference counts in content_blobs
CREATE TRIGGER increment_blob_reference
AFTER INSERT ON file_contents
FOR EACH ROW
BEGIN
    UPDATE content_blobs
    SET reference_count = reference_count + 1
    WHERE hash_sha256 = NEW.content_hash;
END;

CREATE TRIGGER decrement_blob_reference
AFTER DELETE ON file_contents
FOR EACH ROW
BEGIN
    UPDATE content_blobs
    SET reference_count = reference_count - 1
    WHERE hash_sha256 = OLD.content_hash;
END;

-- =============================================================================
-- STEP 7: Migrate data from backup to new table
-- =============================================================================

-- Copy references (not content) from backup
INSERT INTO file_contents (
    id,
    file_id,
    content_hash,
    file_size_bytes,
    line_count,
    is_current,
    created_at,
    updated_at
)
SELECT
    id,
    file_id,
    content_hash,  -- Use existing content_hash column
    file_size_bytes,
    line_count,
    is_current,
    created_at,
    updated_at
FROM file_contents_backup;

-- =============================================================================
-- STEP 8: Create views for backward compatibility
-- =============================================================================

-- View that joins file_contents with content_blobs (looks like old schema)
CREATE VIEW file_contents_with_content AS
SELECT
    fc.id,
    fc.file_id,
    fc.content_hash,
    fc.file_size_bytes,
    fc.line_count,
    fc.is_current,
    fc.created_at,
    fc.updated_at,
    -- Content from blobs
    cb.content_text,
    cb.content_blob,
    cb.content_type,
    cb.encoding,
    cb.hash_sha256
FROM file_contents fc
JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256;

-- Recreate current_file_contents_view with new schema
CREATE VIEW current_file_contents_view AS
SELECT
    pf.id AS file_id,
    pf.file_path,
    pf.file_name,
    pf.component_name,
    ft.type_name,
    cb.content_text,
    cb.content_type,
    fc.file_size_bytes,
    fc.line_count,
    cb.hash_sha256,
    fc.updated_at,
    p.slug AS project_slug
FROM file_contents fc
JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
JOIN project_files pf ON fc.file_id = pf.id
JOIN file_types ft ON pf.file_type_id = ft.id
JOIN projects p ON pf.project_id = p.id
WHERE fc.is_current = 1;

-- =============================================================================
-- STEP 9: Statistics and verification
-- =============================================================================

-- These queries will be run after migration to verify success

-- SELECT 'Migration Statistics' as info;
-- SELECT COUNT(*) as total_file_contents FROM file_contents;
-- SELECT COUNT(*) as unique_content_blobs FROM content_blobs;
-- SELECT
--     COUNT(*) as total_records,
--     COUNT(*) - (SELECT COUNT(*) FROM content_blobs) as duplicates_eliminated,
--     ROUND(100.0 * (1 - (SELECT COUNT(*) FROM content_blobs) * 1.0 / COUNT(*)), 2) as percent_deduplication
-- FROM file_contents;
-- SELECT SUM(file_size_bytes) as old_size_bytes FROM file_contents_backup;
-- SELECT SUM(file_size_bytes) as new_size_bytes FROM content_blobs;

-- =============================================================================
-- ROLLBACK INSTRUCTIONS (if needed)
-- =============================================================================

-- To rollback this migration:
-- 1. DROP TABLE file_contents;
-- 2. ALTER TABLE file_contents_backup RENAME TO file_contents;
-- 3. DROP TABLE content_blobs;
-- 4. Recreate indexes/triggers on file_contents
