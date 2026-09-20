-- Editor state persistence (syncs across machines via DB)
CREATE TABLE IF NOT EXISTS editor_sessions (
    id INTEGER PRIMARY KEY,
    hostname TEXT NOT NULL,
    project_slug TEXT,
    -- Open buffers (JSON array of {file, point, mark, mode})
    open_buffers TEXT,
    -- Window layout (JSON: split config + buffer assignments)
    window_layout TEXT,
    -- Active project context
    active_project TEXT,
    last_branch TEXT,
    -- Metadata
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(hostname)
);
