-- Add deployment caching for faster repeated deployments
-- Tracks content hashes and reuses builds when nothing changed

CREATE TABLE IF NOT EXISTS deployment_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    target TEXT NOT NULL,

    -- Content addressing
    content_hash TEXT NOT NULL,  -- SHA-256 of project files + dependencies
    files_hash TEXT NOT NULL,    -- Hash of file contents only
    deps_hash TEXT NOT NULL,     -- Hash of package manifests (package.json, requirements.txt, etc.)

    -- Cached artifacts
    cathedral_path TEXT,         -- Path to cached cathedral export
    fhs_env_path TEXT,          -- Path to cached FHS environment (fhs-env.nix)
    work_dir_path TEXT,         -- Path to cached working directory

    -- Cache metadata
    cache_created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT NOT NULL DEFAULT (datetime('now')),
    use_count INTEGER DEFAULT 1,

    -- Size tracking
    total_size_bytes INTEGER,
    file_count INTEGER,

    -- Cache validation
    is_valid BOOLEAN DEFAULT 1,  -- Invalidated on project changes
    invalidated_at TEXT,
    invalidation_reason TEXT,

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, target, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_deployment_cache_project ON deployment_cache(project_id, target);
CREATE INDEX IF NOT EXISTS idx_deployment_cache_hash ON deployment_cache(content_hash);
CREATE INDEX IF NOT EXISTS idx_deployment_cache_valid ON deployment_cache(is_valid) WHERE is_valid = 1;
CREATE INDEX IF NOT EXISTS idx_deployment_cache_last_used ON deployment_cache(last_used_at DESC);

-- Deployment cache hits tracking (analytics)
CREATE TABLE IF NOT EXISTS deployment_cache_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    target TEXT NOT NULL,

    deployed_at TEXT NOT NULL DEFAULT (datetime('now')),
    cache_hit BOOLEAN NOT NULL,  -- Did we use cache?
    content_hash TEXT,           -- Hash for this deployment

    -- Performance metrics
    build_time_seconds REAL,     -- Time to build (0 if cache hit)
    export_time_seconds REAL,    -- Time to export cathedral
    total_time_seconds REAL,     -- Total deployment time

    -- What was cached/skipped
    skipped_cathedral_export BOOLEAN DEFAULT 0,
    skipped_fhs_generation BOOLEAN DEFAULT 0,
    skipped_file_reconstruction BOOLEAN DEFAULT 0,

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cache_stats_project ON deployment_cache_stats(project_id, deployed_at DESC);
CREATE INDEX IF NOT EXISTS idx_cache_stats_hits ON deployment_cache_stats(cache_hit);

-- Cache size limits (configurable per-project)
CREATE TABLE IF NOT EXISTS deployment_cache_config (
    project_id INTEGER PRIMARY KEY,

    -- Size limits
    max_cache_size_mb INTEGER DEFAULT 1024,      -- Max 1GB cache per project
    max_cache_entries INTEGER DEFAULT 10,        -- Keep last 10 cached versions

    -- Time limits
    cache_ttl_days INTEGER DEFAULT 30,           -- Expire cache after 30 days

    -- Behavior
    auto_cleanup BOOLEAN DEFAULT 1,              -- Auto-delete old entries
    enable_caching BOOLEAN DEFAULT 1,            -- Can disable per-project

    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- Trigger: Update last_used_at on cache hit
CREATE TRIGGER IF NOT EXISTS update_cache_last_used
AFTER UPDATE ON deployment_cache
WHEN NEW.use_count > OLD.use_count
BEGIN
    UPDATE deployment_cache
    SET last_used_at = datetime('now')
    WHERE id = NEW.id;
END;

-- View: Cache efficiency per project
CREATE VIEW IF NOT EXISTS deployment_cache_efficiency_view AS
SELECT
    p.slug AS project_slug,
    COUNT(*) AS total_deployments,
    SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END) AS cache_hits,
    SUM(CASE WHEN cache_hit = 0 THEN 1 ELSE 0 END) AS cache_misses,
    ROUND(100.0 * SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS hit_rate_percent,
    ROUND(AVG(CASE WHEN cache_hit = 1 THEN total_time_seconds ELSE NULL END), 2) AS avg_cached_time_sec,
    ROUND(AVG(CASE WHEN cache_hit = 0 THEN total_time_seconds ELSE NULL END), 2) AS avg_uncached_time_sec,
    ROUND(AVG(CASE WHEN cache_hit = 0 THEN total_time_seconds ELSE NULL END) -
          AVG(CASE WHEN cache_hit = 1 THEN total_time_seconds ELSE NULL END), 2) AS time_saved_per_hit_sec
FROM deployment_cache_stats dcs
JOIN projects p ON dcs.project_id = p.id
GROUP BY p.id, p.slug;

-- View: Active cache entries
CREATE VIEW IF NOT EXISTS deployment_cache_active_view AS
SELECT
    p.slug AS project_slug,
    dc.target,
    dc.content_hash,
    dc.cache_created_at,
    dc.last_used_at,
    dc.use_count,
    dc.file_count,
    ROUND(dc.total_size_bytes / 1024.0 / 1024.0, 2) AS size_mb,
    ROUND((julianday('now') - julianday(dc.last_used_at)) * 24, 1) AS hours_since_use
FROM deployment_cache dc
JOIN projects p ON dc.project_id = p.id
WHERE dc.is_valid = 1
ORDER BY dc.last_used_at DESC;
