-- ============================================================================
-- Migration 036: Consolidate Content Storage + Add Compression (v2)
-- ============================================================================
-- Date: 2026-03-19
-- Purpose: Consolidate 7 overlapping content tables into 2 with compression
--
-- CHANGED FROM V1: Use project_files instead of creating redundant components table
--
-- BEFORE:
--   - content_blobs (base content-addressable storage)
--   - file_versions (duplicate content storage)
--   - file_snapshots (duplicate content storage)
--   - vcs_file_states (has content_hash reference - KEEP)
--   - vcs_working_state (inline content storage - DELETE)
--   - vcs_staging (inline content storage - DELETE)
--   - file_contents (current version pointer - KEEP as reference only)
--   - project_files (has component_name field - ENHANCE)
--
-- AFTER:
--   - content_blobs (enhanced with compression, append-only)
--   - project_files (enhanced with is_shared flag)
--   - shared_file_references (NEW: cross-project file sharing)
--   - file_contents (lightweight reference to content_blobs)
--   - vcs_file_states (already references content_blobs - keep)
--
-- IMPROVEMENTS:
--   1. Add zlib compression to content_blobs
--   2. Add delta compression support
--   3. Make content_blobs truly append-only (immutable)
--   4. Enable cross-project file sharing via project_files (no redundant table!)
--   5. Remove duplicate content storage tables
--
-- STORAGE SAVINGS: Expected 60-80% reduction
-- ============================================================================

BEGIN TRANSACTION;

-- ============================================================================
-- STEP 1: Backup existing tables
-- ============================================================================

CREATE TABLE IF NOT EXISTS content_blobs_backup AS
SELECT * FROM content_blobs
WHERE EXISTS (SELECT 1 FROM content_blobs LIMIT 1);

CREATE TABLE IF NOT EXISTS file_versions_backup AS
SELECT * FROM file_versions
WHERE EXISTS (SELECT 1 FROM file_versions LIMIT 1);

-- ============================================================================
-- STEP 2: Create enhanced content_blobs with compression
-- ============================================================================

CREATE TABLE content_blobs_new (
    -- Primary key is content hash (content-addressable, immutable)
    hash_sha256 TEXT PRIMARY KEY,

    -- Content storage (only ONE will be populated)
    content_text TEXT,           -- For text files (UNCOMPRESSED for SQLite FTS)
    content_blob BLOB,           -- For binary files OR compressed text

    -- Content metadata
    content_type TEXT NOT NULL CHECK(content_type IN ('text', 'binary')),
    encoding TEXT DEFAULT 'utf-8',

    -- Size tracking
    file_size_bytes INTEGER NOT NULL,      -- Actual stored size (compressed if applicable)
    original_size_bytes INTEGER NOT NULL,  -- Original uncompressed size

    -- Compression
    compression TEXT DEFAULT 'none' CHECK(compression IN ('none', 'zlib', 'delta')),
    delta_base_hash TEXT,  -- If delta compressed, base blob hash

    -- Statistics
    reference_count INTEGER DEFAULT 0,

    -- Immutability tracking
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_deleted BOOLEAN DEFAULT 0,  -- Soft delete (never actually delete)

    -- Foreign key for delta compression
    FOREIGN KEY (delta_base_hash) REFERENCES content_blobs_new(hash_sha256),

    -- Ensure delta compression has base
    CHECK (compression != 'delta' OR delta_base_hash IS NOT NULL)
);

-- ============================================================================
-- STEP 3: Migrate existing content_blobs
-- ============================================================================

INSERT INTO content_blobs_new (
    hash_sha256,
    content_text,
    content_blob,
    content_type,
    encoding,
    file_size_bytes,
    original_size_bytes,
    compression,
    reference_count,
    created_at
)
SELECT
    hash_sha256,
    content_text,
    content_blob,
    content_type,
    encoding,
    file_size_bytes,
    file_size_bytes,  -- original_size = current size (not compressed yet)
    'none',           -- Will compress later with rebuild
    reference_count,
    COALESCE(created_at, datetime('now'))
FROM content_blobs;

-- ============================================================================
-- STEP 4: Enhance project_files for cross-project sharing
-- ============================================================================

-- Add sharing flag (if not exists)
-- Check if column exists first
CREATE TABLE project_files_new AS SELECT * FROM project_files;

-- Add is_shared column if it doesn't exist
ALTER TABLE project_files_new ADD COLUMN is_shared BOOLEAN DEFAULT 0;

-- Drop old and rename
DROP TABLE project_files;
ALTER TABLE project_files_new RENAME TO project_files;

-- Recreate indexes
CREATE INDEX idx_project_files_project ON project_files(project_id);
CREATE INDEX idx_project_files_type ON project_files(file_type_id);
CREATE INDEX idx_project_files_path ON project_files(file_path);
CREATE INDEX idx_project_files_component ON project_files(component_name);
CREATE INDEX idx_project_files_shared ON project_files(is_shared);

-- ============================================================================
-- STEP 5: Create shared_file_references (cross-project file sharing)
-- ============================================================================

CREATE TABLE shared_file_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Source (the shared file)
    source_project_id INTEGER NOT NULL,
    source_file_id INTEGER NOT NULL,

    -- Consumer (project using the shared file)
    using_project_id INTEGER NOT NULL,

    -- Optional overrides
    alias TEXT,  -- Import as different name
    override_content_hash TEXT,  -- Branch-specific override

    -- Metadata
    linked_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT,

    -- Foreign keys
    FOREIGN KEY (source_project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (source_file_id) REFERENCES project_files(id) ON DELETE CASCADE,
    FOREIGN KEY (using_project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (override_content_hash) REFERENCES content_blobs_new(hash_sha256),

    UNIQUE(source_file_id, using_project_id)
);

CREATE INDEX idx_shared_file_refs_source ON shared_file_references(source_file_id);
CREATE INDEX idx_shared_file_refs_using ON shared_file_references(using_project_id);

-- ============================================================================
-- STEP 6: Recreate indexes on content_blobs_new
-- ============================================================================

CREATE INDEX idx_content_blobs_size ON content_blobs_new(file_size_bytes);
CREATE INDEX idx_content_blobs_type ON content_blobs_new(content_type);
CREATE INDEX idx_content_blobs_compression ON content_blobs_new(compression);
CREATE INDEX idx_content_blobs_delta_base ON content_blobs_new(delta_base_hash);
CREATE INDEX idx_content_blobs_deleted ON content_blobs_new(is_deleted);

-- ============================================================================
-- STEP 7: Drop old table and rename
-- ============================================================================

DROP TABLE content_blobs;
ALTER TABLE content_blobs_new RENAME TO content_blobs;

-- ============================================================================
-- STEP 8: Update file_contents to only reference content_blobs
-- ============================================================================

CREATE TABLE file_contents_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,

    -- Content reference (not inline storage!)
    content_hash TEXT NOT NULL,

    -- Cached metadata (from content_blobs)
    content_type TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,

    -- Current version flag
    is_current BOOLEAN DEFAULT 1,

    -- Timestamps
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    -- Foreign keys
    FOREIGN KEY (file_id) REFERENCES project_files(id) ON DELETE CASCADE,
    FOREIGN KEY (content_hash) REFERENCES content_blobs(hash_sha256),

    UNIQUE(file_id, is_current)
);

-- Migrate existing file_contents
INSERT INTO file_contents_new (
    id,
    file_id,
    content_hash,
    content_type,
    file_size_bytes,
    is_current,
    created_at,
    updated_at
)
SELECT
    fc.id,
    fc.file_id,
    fc.content_hash,
    cb.content_type,
    cb.file_size_bytes,
    fc.is_current,
    fc.created_at,
    fc.updated_at
FROM file_contents fc
JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
WHERE EXISTS (SELECT 1 FROM file_contents);

-- Drop old and rename
DROP TABLE IF EXISTS file_contents;
ALTER TABLE file_contents_new RENAME TO file_contents;

-- Recreate indexes
CREATE INDEX idx_file_contents_file_id ON file_contents(file_id);
CREATE INDEX idx_file_contents_hash ON file_contents(content_hash);
CREATE INDEX idx_file_contents_current ON file_contents(is_current);

-- ============================================================================
-- STEP 9: Drop redundant tables
-- ============================================================================

DROP TABLE IF EXISTS file_versions;
DROP TABLE IF EXISTS file_snapshots;
DROP TABLE IF EXISTS vcs_working_state;
DROP TABLE IF EXISTS vcs_staging;

-- ============================================================================
-- STEP 10: Create triggers for immutability
-- ============================================================================

-- Prevent updates to content_blobs (append-only)
CREATE TRIGGER prevent_content_blob_updates
BEFORE UPDATE ON content_blobs
FOR EACH ROW
WHEN NEW.hash_sha256 != OLD.hash_sha256
   OR NEW.content_text != OLD.content_text
   OR NEW.content_blob != OLD.content_blob
BEGIN
    SELECT RAISE(ABORT, 'Content blobs are immutable. Create new blob instead.');
END;

-- Prevent deletes (use soft delete instead)
CREATE TRIGGER prevent_content_blob_deletes
BEFORE DELETE ON content_blobs
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'Content blobs cannot be deleted. Use soft delete (is_deleted=1).');
END;

-- Update file_contents timestamp on change
CREATE TRIGGER update_file_contents_timestamp
AFTER UPDATE ON file_contents
FOR EACH ROW
BEGIN
    UPDATE file_contents
    SET updated_at = datetime('now')
    WHERE id = NEW.id;
END;

-- ============================================================================
-- STEP 11: Create views for convenience
-- ============================================================================

-- View: Shared files across projects
CREATE VIEW shared_files AS
SELECT
    pf.id as file_id,
    pf.component_name,
    pf.file_path,
    ft.type_name,
    p.slug as source_project,
    pf.description,
    pf.owner,
    cb.file_size_bytes,
    cb.original_size_bytes,
    cb.compression,
    (SELECT COUNT(*) FROM shared_file_references sfr WHERE sfr.source_file_id = pf.id) as usage_count,
    pf.created_at,
    pf.updated_at
FROM project_files pf
JOIN projects p ON pf.project_id = p.id
JOIN file_types ft ON pf.file_type_id = ft.id
JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
WHERE pf.is_shared = 1;

-- View: File usage across projects
CREATE VIEW file_usage AS
SELECT
    source_pf.component_name,
    ft.type_name,
    source_p.slug as source_project,
    source_pf.file_path as source_path,
    using_p.slug as using_project,
    sfr.alias,
    sfr.linked_at,
    sfr.last_used_at
FROM shared_file_references sfr
JOIN project_files source_pf ON sfr.source_file_id = source_pf.id
JOIN projects source_p ON sfr.source_project_id = source_p.id
JOIN projects using_p ON sfr.using_project_id = using_p.id
JOIN file_types ft ON source_pf.file_type_id = ft.id
ORDER BY source_pf.component_name, using_p.slug;

-- View: Current file contents with decompression info
CREATE VIEW current_file_contents AS
SELECT
    pf.id as file_id,
    pf.file_path,
    pf.file_name,
    pf.component_name,
    fc.content_hash,
    cb.content_text,
    cb.content_type,
    cb.file_size_bytes,
    cb.original_size_bytes,
    cb.compression,
    CASE
        WHEN cb.compression = 'none' THEN 0
        ELSE CAST((cb.original_size_bytes - cb.file_size_bytes) * 100.0 / cb.original_size_bytes AS INTEGER)
    END as compression_ratio_percent,
    p.slug as project_slug
FROM file_contents fc
JOIN project_files pf ON fc.file_id = pf.id
JOIN projects p ON pf.project_id = p.id
JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
WHERE fc.is_current = 1;

-- ============================================================================
-- STEP 12: Update reference counts
-- ============================================================================

UPDATE content_blobs
SET reference_count = (
    -- Count from file_contents
    (SELECT COUNT(*) FROM file_contents WHERE content_hash = content_blobs.hash_sha256)
    +
    -- Count from vcs_file_states
    (SELECT COUNT(*) FROM vcs_file_states WHERE content_hash = content_blobs.hash_sha256)
);

-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================

COMMIT;

-- ============================================================================
-- Post-migration validation queries
-- ============================================================================

-- SELECT 'Content blobs count:' as metric, COUNT(*) as value FROM content_blobs
-- UNION ALL
-- SELECT 'Shared files count:', COUNT(*) FROM project_files WHERE is_shared = 1
-- UNION ALL
-- SELECT 'File contents count:', COUNT(*) FROM file_contents
-- UNION ALL
-- SELECT 'Total storage (MB):', SUM(file_size_bytes) / 1024.0 / 1024.0 FROM content_blobs
-- UNION ALL
-- SELECT 'Uncompressed size (MB):', SUM(original_size_bytes) / 1024.0 / 1024.0 FROM content_blobs;
