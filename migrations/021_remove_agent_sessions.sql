-- Migration 021: Remove Agent Sessions
-- Removes the legacy agent session management system in favor of MCP-based approach

-- Drop agent session tables
DROP TABLE IF EXISTS agent_mailbox;
DROP TABLE IF EXISTS agent_session_watchers;
DROP TABLE IF EXISTS agent_session_state;
DROP TABLE IF EXISTS agent_session_metrics;
DROP TABLE IF EXISTS agent_context_snapshots;
DROP TABLE IF EXISTS agent_session_commits;
DROP TABLE IF EXISTS agent_interactions;
DROP TABLE IF EXISTS agent_sessions;

-- Drop views that reference agent sessions
DROP VIEW IF EXISTS active_sessions_with_watchers;
DROP VIEW IF EXISTS active_work_items_view;
DROP VIEW IF EXISTS agent_workload_view;

-- Recreate active_work_items_view without agent session references
CREATE VIEW IF NOT EXISTS active_work_items_view AS
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

-- Migration complete
-- Run: ./templedb migration apply 021
