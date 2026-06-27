-- Blue-green deployment state tracking.
-- Tracks which slot (blue/green) is active per project+target.

CREATE TABLE IF NOT EXISTS blue_green_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    target TEXT NOT NULL,                    -- deployment target name
    active_slot TEXT NOT NULL DEFAULT 'blue', -- 'blue' or 'green'

    -- Per-slot version tracking
    blue_version TEXT,                       -- content hash or commit of blue deploy
    blue_deployed_at TIMESTAMP,
    green_version TEXT,
    green_deployed_at TIMESTAMP,

    -- Swap history
    last_swap_at TIMESTAMP,
    swap_count INTEGER DEFAULT 0,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(project_id, target)
);

CREATE INDEX IF NOT EXISTS idx_blue_green_state_lookup
    ON blue_green_state(project_id, target);
