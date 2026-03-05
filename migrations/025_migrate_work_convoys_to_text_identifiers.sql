-- Migration 025: Migrate work_convoys from agent_sessions to text identifiers
-- Remove foreign key to agent_sessions table

-- Drop trigger that references work_convoys
DROP TRIGGER IF EXISTS update_convoy_on_completion;

-- Drop view that references work_convoys
DROP VIEW IF EXISTS convoy_progress_view;

-- Create new work_convoys without agent_sessions FK
CREATE TABLE work_convoys_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convoy_name TEXT NOT NULL,
    project_id INTEGER NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending',

    -- Coordinator as TEXT identifier (not foreign key)
    coordinator TEXT,

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),
    started_at TEXT,
    completed_at TEXT,

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,

    CHECK (status IN ('pending', 'active', 'completed', 'cancelled'))
);

-- Copy data (convert coordinator_session_id to TEXT)
INSERT INTO work_convoys_new
SELECT
    id,
    convoy_name,
    project_id,
    description,
    status,
    CAST(coordinator_session_id AS TEXT),
    created_at,
    started_at,
    completed_at
FROM work_convoys;

-- Drop old table and rename new one
DROP TABLE work_convoys;
ALTER TABLE work_convoys_new RENAME TO work_convoys;

-- Recreate index
CREATE INDEX idx_convoys_project_status
    ON work_convoys(project_id, status);

-- Recreate trigger without agent_sessions references
CREATE TRIGGER update_convoy_on_completion
AFTER UPDATE OF status ON work_items
WHEN NEW.status = 'completed'
BEGIN
    UPDATE work_convoys
    SET
        status = 'completed',
        completed_at = datetime('now')
    WHERE id IN (
        SELECT convoy_id
        FROM convoy_work_items
        WHERE work_item_id = NEW.id
    )
    AND NOT EXISTS (
        SELECT 1
        FROM convoy_work_items cwi
        JOIN work_items wi ON cwi.work_item_id = wi.id
        WHERE cwi.convoy_id = work_convoys.id
        AND wi.status != 'completed'
    );
END;

-- Recreate view
CREATE VIEW convoy_progress_view AS
SELECT
    wc.id as convoy_id,
    wc.convoy_name,
    wc.status as convoy_status,
    COUNT(cwi.work_item_id) as total_items,
    SUM(CASE WHEN wi.status = 'completed' THEN 1 ELSE 0 END) as completed_items,
    SUM(CASE WHEN wi.status = 'in_progress' THEN 1 ELSE 0 END) as in_progress_items,
    SUM(CASE WHEN wi.status = 'blocked' THEN 1 ELSE 0 END) as blocked_items,
    wc.created_at,
    wc.completed_at
FROM work_convoys wc
LEFT JOIN convoy_work_items cwi ON wc.id = cwi.convoy_id
LEFT JOIN work_items wi ON cwi.work_item_id = wi.id
GROUP BY wc.id;

-- Migration complete
