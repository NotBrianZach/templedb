-- Migration 024: Create missing work_item_transitions table and recreate views
-- The work_items and work_item_notifications tables already exist with correct schema

-- Create work_item_transitions table
CREATE TABLE IF NOT EXISTS work_item_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    changed_by TEXT,
    reason TEXT,
    transitioned_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (work_item_id) REFERENCES work_items(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_transitions_work_item
    ON work_item_transitions(work_item_id, transitioned_at);

-- Recreate active_work_items_view
DROP VIEW IF EXISTS active_work_items_view;
CREATE VIEW active_work_items_view AS
SELECT
    wi.id,
    wi.title,
    wi.status,
    wi.priority,
    wi.item_type,
    p.slug as project_slug,
    p.name as project_name,
    wi.assigned_to,
    wi.created_at,
    wi.assigned_at,
    wi.started_at,
    (SELECT COUNT(*) FROM work_items sub WHERE sub.parent_item_id = wi.id) as subtask_count
FROM work_items wi
JOIN projects p ON wi.project_id = p.id
WHERE wi.status IN ('pending', 'assigned', 'in_progress', 'blocked');

-- Recreate work_item_stats_view
DROP VIEW IF EXISTS work_item_stats_view;
CREATE VIEW work_item_stats_view AS
SELECT
    p.slug as project_slug,
    p.name as project_name,
    COUNT(*) as total_items,
    SUM(CASE WHEN wi.status = 'pending' THEN 1 ELSE 0 END) as pending_count,
    SUM(CASE WHEN wi.status = 'in_progress' THEN 1 ELSE 0 END) as in_progress_count,
    SUM(CASE WHEN wi.status = 'completed' THEN 1 ELSE 0 END) as completed_count,
    SUM(CASE WHEN wi.status = 'blocked' THEN 1 ELSE 0 END) as blocked_count,
    SUM(CASE WHEN wi.priority = 'critical' THEN 1 ELSE 0 END) as critical_count,
    SUM(CASE WHEN wi.priority = 'high' THEN 1 ELSE 0 END) as high_priority_count
FROM projects p
LEFT JOIN work_items wi ON p.id = wi.project_id
GROUP BY p.id;

-- Recreate assignee_workload_view
DROP VIEW IF EXISTS assignee_workload_view;
CREATE VIEW assignee_workload_view AS
SELECT
    wi.assigned_to,
    p.slug as project_slug,
    COUNT(wi.id) as assigned_items,
    SUM(CASE WHEN wi.status = 'in_progress' THEN 1 ELSE 0 END) as active_items,
    SUM(CASE WHEN wi.priority IN ('high', 'critical') THEN 1 ELSE 0 END) as high_priority_items,
    (SELECT COUNT(*) FROM work_item_notifications WHERE recipient = wi.assigned_to AND status = 'unread') as unread_messages
FROM work_items wi
JOIN projects p ON wi.project_id = p.id
WHERE wi.assigned_to IS NOT NULL
GROUP BY wi.assigned_to, p.slug;

-- Recreate convoy_progress_view if work_convoys table exists
DROP VIEW IF EXISTS convoy_progress_view;
CREATE VIEW IF NOT EXISTS convoy_progress_view AS
SELECT
    wc.id as convoy_id,
    wc.name as convoy_name,
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
