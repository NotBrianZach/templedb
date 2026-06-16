-- Migration 020: Add Work Items and Multi-Agent Coordination
-- Implements Gas Town-inspired Beads system for structured work items
-- and multi-agent task coordination with mailbox-style assignment
--
-- NOTE: This migration has been updated to remove convoy-related objects
-- that were later removed in migration 040 (work_convoys, convoy_work_items,
-- convoy_progress_view, update_convoy_on_completion trigger).
-- The convoy system was never fully implemented and has been deprecated.

-- Work items table (inspired by Gas Town's Beads)
CREATE TABLE IF NOT EXISTS work_items (
    id TEXT PRIMARY KEY,                    -- Format: 'tdb-xxxxx' (5 alphanumeric chars)
    project_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending', -- pending, assigned, in_progress, completed, blocked, cancelled
    priority TEXT DEFAULT 'medium',         -- low, medium, high, critical
    item_type TEXT DEFAULT 'task',          -- task, bug, feature, refactor, research

    -- Assignment and coordination
    assigned_to TEXT,                       -- User/agent identifier working on this
    created_by TEXT,                        -- User/agent that created this item
    parent_item_id TEXT,                    -- For sub-tasks/dependencies

    -- Metadata
    estimated_effort TEXT,                  -- Optional: small, medium, large
    tags TEXT,                              -- JSON array of tags
    metadata TEXT,                          -- JSON for extensibility

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    assigned_at TEXT,
    started_at TEXT,
    completed_at TEXT,

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_item_id) REFERENCES work_items(id) ON DELETE SET NULL,

    CHECK (status IN ('pending', 'assigned', 'in_progress', 'completed', 'blocked', 'cancelled')),
    CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    CHECK (item_type IN ('task', 'bug', 'feature', 'refactor', 'research', 'documentation'))
);

-- Indexes for work item queries
CREATE INDEX IF NOT EXISTS idx_work_items_project_status
    ON work_items(project_id, status);
CREATE INDEX IF NOT EXISTS idx_work_items_assigned
    ON work_items(assigned_to, status);
CREATE INDEX IF NOT EXISTS idx_work_items_status_priority
    ON work_items(status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_work_items_parent
    ON work_items(parent_item_id);

-- NOTE: Convoy tables (work_convoys, convoy_work_items) were removed in migration 040
-- They were part of the original Gas Town-inspired design but were never fully implemented
-- See migrations/040_safe_cleanup_verified_unused.sql for removal details

-- Workflow templates table (TOML-style formulas)
CREATE TABLE IF NOT EXISTS workflow_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    template_type TEXT DEFAULT 'sequential',    -- sequential, parallel, conditional
    steps TEXT NOT NULL,                        -- JSON array of workflow steps
    default_priority TEXT DEFAULT 'medium',

    -- Metadata
    tags TEXT,                                  -- JSON array
    metadata TEXT,                              -- JSON for extensibility

    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),

    CHECK (template_type IN ('sequential', 'parallel', 'conditional'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_workflow_templates_name
    ON workflow_templates(name);

-- Work item state transitions (audit log)
CREATE TABLE IF NOT EXISTS work_item_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    changed_by TEXT,                            -- User/agent that made the transition
    reason TEXT,
    transitioned_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (work_item_id) REFERENCES work_items(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_transitions_work_item
    ON work_item_transitions(work_item_id, transitioned_at);

-- Work item notifications table (asynchronous task assignment)
CREATE TABLE IF NOT EXISTS work_item_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient TEXT NOT NULL,                    -- User/agent identifier
    message_type TEXT NOT NULL,                 -- work_assignment, notification, coordination_request
    work_item_id TEXT,                          -- Related work item if applicable
    convoy_id INTEGER,                          -- Legacy column (convoys removed in migration 040)
    message_content TEXT NOT NULL,              -- JSON message content
    priority TEXT DEFAULT 'normal',             -- low, normal, high, urgent

    -- Status
    status TEXT NOT NULL DEFAULT 'unread',      -- unread, read, acknowledged, completed
    delivered_at TEXT DEFAULT (datetime('now')),
    read_at TEXT,
    acknowledged_at TEXT,

    FOREIGN KEY (work_item_id) REFERENCES work_items(id) ON DELETE CASCADE,
    -- Removed: FOREIGN KEY (convoy_id) REFERENCES work_convoys(id) ON DELETE CASCADE

    CHECK (message_type IN ('work_assignment', 'notification', 'coordination_request', 'status_update')),
    CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    CHECK (status IN ('unread', 'read', 'acknowledged', 'completed'))
);

CREATE INDEX IF NOT EXISTS idx_notifications_recipient_status
    ON work_item_notifications(recipient, status, priority);
CREATE INDEX IF NOT EXISTS idx_notifications_work_item
    ON work_item_notifications(work_item_id);

-- Views for work item queries

-- Active work items by project
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

-- Work item statistics by project
CREATE VIEW IF NOT EXISTS work_item_stats_view AS
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

-- Assignee workload view
CREATE VIEW IF NOT EXISTS assignee_workload_view AS
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

-- NOTE: convoy_progress_view was removed in migration 040
-- It was part of the Gas Town convoy system that was never fully implemented

-- Triggers for work item management

-- Update work item timestamp on changes
CREATE TRIGGER IF NOT EXISTS update_work_item_timestamp
AFTER UPDATE ON work_items
FOR EACH ROW
BEGIN
    UPDATE work_items
    SET updated_at = datetime('now')
    WHERE id = NEW.id;
END;

-- Record state transitions
CREATE TRIGGER IF NOT EXISTS record_work_item_transition
AFTER UPDATE OF status ON work_items
WHEN OLD.status != NEW.status
BEGIN
    INSERT INTO work_item_transitions (
        work_item_id,
        from_status,
        to_status,
        changed_by,
        transitioned_at
    ) VALUES (
        NEW.id,
        OLD.status,
        NEW.status,
        NEW.assigned_to,
        datetime('now')
    );

    -- Update timestamps based on new status
    UPDATE work_items
    SET
        assigned_at = CASE WHEN NEW.status = 'assigned' THEN datetime('now') ELSE assigned_at END,
        started_at = CASE WHEN NEW.status = 'in_progress' THEN datetime('now') ELSE started_at END,
        completed_at = CASE WHEN NEW.status = 'completed' THEN datetime('now') ELSE completed_at END
    WHERE id = NEW.id;
END;

-- Automatically send notification on work assignment
CREATE TRIGGER IF NOT EXISTS notify_on_assignment
AFTER UPDATE OF assigned_to ON work_items
WHEN NEW.assigned_to IS NOT NULL
    AND (OLD.assigned_to IS NULL OR OLD.assigned_to != NEW.assigned_to)
BEGIN
    INSERT INTO work_item_notifications (
        recipient,
        message_type,
        work_item_id,
        message_content,
        priority
    ) VALUES (
        NEW.assigned_to,
        'work_assignment',
        NEW.id,
        json_object(
            'work_item_id', NEW.id,
            'title', NEW.title,
            'priority', NEW.priority,
            'item_type', NEW.item_type,
            'assigned_at', datetime('now')
        ),
        CASE NEW.priority
            WHEN 'critical' THEN 'urgent'
            WHEN 'high' THEN 'high'
            ELSE 'normal'
        END
    );
END;

-- NOTE: update_convoy_on_completion trigger was removed in migration 040
-- It was part of the Gas Town convoy system that was never fully implemented

-- Migration complete
-- Run: ./templedb migration apply 020
