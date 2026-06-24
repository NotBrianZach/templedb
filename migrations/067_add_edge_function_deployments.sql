-- Track edge function deployments with content hashes.
-- Only redeploys functions whose source has changed.

CREATE TABLE IF NOT EXISTS edge_function_deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    target TEXT NOT NULL,                    -- deployment target (staging, production)
    function_name TEXT NOT NULL,             -- e.g. 'chat-with-book', 'stripe-webhook'
    content_hash TEXT NOT NULL,              -- sha256 of function source files
    file_count INTEGER,                     -- number of source files
    status TEXT NOT NULL DEFAULT 'pending',  -- 'success', 'failed', 'pending'
    message TEXT,                            -- stdout/stderr snippet
    duration_seconds REAL,                  -- deploy time
    deployed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- metadata
    deployed_by TEXT DEFAULT 'templedb'
);

CREATE INDEX IF NOT EXISTS idx_edge_func_deploy_lookup
    ON edge_function_deployments(project_id, target, function_name, deployed_at DESC);

CREATE INDEX IF NOT EXISTS idx_edge_func_deploy_hash
    ON edge_function_deployments(project_id, target, function_name, content_hash);
