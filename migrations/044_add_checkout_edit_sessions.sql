-- ============================================================================
-- CHECKOUT EDIT SESSIONS AND SYNC CACHE
-- ============================================================================
-- Support for read-only checkouts with explicit edit mode
-- Git-like workflow with hash-based change detection
-- ============================================================================

-- Edit Sessions - Track when checkouts are in writable mode
-- ============================================================================
CREATE TABLE IF NOT EXISTS edit_sessions (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Session metadata
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    hostname TEXT,                      -- Machine where edit session started
    pid INTEGER,                        -- Process ID that started edit

    -- Context
    reason TEXT,                        -- Why editing (optional)
    auto_commit BOOLEAN DEFAULT 0,      -- Auto-commit on exit?

    UNIQUE(project_id)                  -- Only one edit session per project
);

-- Sync Cache - Hash-based change detection
-- ============================================================================
-- Stores file hashes at checkout time for three-way merge detection
CREATE TABLE IF NOT EXISTS sync_cache (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,

    -- Hash at checkout/last sync time
    content_hash TEXT NOT NULL,         -- sha256 of file content

    -- Metadata
    cached_at TEXT NOT NULL DEFAULT (datetime('now')),
    file_size INTEGER,

    UNIQUE(project_id, file_path)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_edit_sessions_project ON edit_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_sync_cache_project ON sync_cache(project_id);
CREATE INDEX IF NOT EXISTS idx_sync_cache_lookup ON sync_cache(project_id, file_path);

-- Cleanup view - Find stale edit sessions (>24h old or dead process)
CREATE VIEW IF NOT EXISTS stale_edit_sessions AS
SELECT
    es.id,
    es.project_id,
    p.slug as project_slug,
    es.started_at,
    es.hostname,
    es.pid,
    -- Session is stale if >24 hours old
    (julianday('now') - julianday(es.started_at)) * 24 as hours_old
FROM edit_sessions es
JOIN projects p ON p.id = es.project_id
WHERE (julianday('now') - julianday(es.started_at)) * 24 > 24;
