-- Migration 020: Add Work Items and Multi-Agent Coordination
-- Implements Gas Town-inspired Beads system for structured work items
-- and multi-agent task coordination with mailbox-style assignment

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
    assigned_session_id INTEGER,            -- Current agent session working on this
    created_by_session_id INTEGER,          -- Agent session that created this item
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
    FOREIGN KEY (assigned_session_id) REFERENCES agent_sessions(id) ON DELETE SET NULL,
    FOREIGN KEY (created_by_session_id) REFERENCES agent_sessions(id) ON DELETE SET NULL,
    FOREIGN KEY (parent_item_id) REFERENCES work_items(id) ON DELETE SET NULL,

    CHECK (status IN ('pending', 'assigned', 'in_progress', 'completed', 'blocked', 'cancelled')),
    CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    CHECK (item_type IN ('task', 'bug', 'feature', 'refactor', 'research', 'documentation'))
);

-- Indexes for work item queries
CREATE INDEX IF NOT EXISTS idx_work_items_project_status
    ON work_items(project_id, status);
CREATE INDEX IF NOT EXISTS idx_work_items_assigned_session
    ON work_items(assigned_session_id, status);
CREATE INDEX IF NOT EXISTS idx_work_items_status_priority
    ON work_items(status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_work_items_parent
    ON work_items(parent_item_id);

-- Convoys table (inspired by Gas Town - bundles of related work items)
CREATE TABLE IF NOT EXISTS work_convoys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convoy_name TEXT NOT NULL,
    project_id INTEGER NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending',     -- pending, active, completed, cancelled

    -- Coordination
    coordinator_session_id INTEGER,             -- Mayor/coordinator agent

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),
    started_at TEXT,
    completed_at TEXT,

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (coordinator_session_id) REFERENCES agent_sessions(id) ON DELETE SET NULL,

    CHECK (status IN ('pending', 'active', 'completed', 'cancelled'))
);

CREATE INDEX IF NOT EXISTS idx_convoys_project_status
    ON work_convoys(project_id, status);

-- Junction table for work items in convoys
CREATE TABLE IF NOT EXISTS convoy_work_items (
    convoy_id INTEGER NOT NULL,
    work_item_id TEXT NOT NULL,
    sequence_order INTEGER,                     -- Order within convoy
    added_at TEXT DEFAULT (datetime('now')),

    PRIMARY KEY (convoy_id, work_item_id),
    FOREIGN KEY (convoy_id) REFERENCES work_convoys(id) ON DELETE CASCADE,
    FOREIGN KEY (work_item_id) REFERENCES work_items(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_convoy_items_convoy
    ON convoy_work_items(convoy_id, sequence_order);

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
    session_id INTEGER,                         -- Agent that made the transition
    reason TEXT,
    transitioned_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (work_item_id) REFERENCES work_items(id) ON DELETE CASCADE,
    FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_transitions_work_item
    ON work_item_transitions(work_item_id, transitioned_at);

-- Agent mailbox table (asynchronous task assignment)
CREATE TABLE IF NOT EXISTS agent_mailbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    message_type TEXT NOT NULL,                 -- work_assignment, notification, coordination_request
    work_item_id TEXT,                          -- Related work item if applicable
    convoy_id INTEGER,                          -- Related convoy if applicable
    message_content TEXT NOT NULL,              -- JSON message content
    priority TEXT DEFAULT 'normal',             -- low, normal, high, urgent

    -- Status
    status TEXT NOT NULL DEFAULT 'unread',      -- unread, read, acknowledged, completed
    delivered_at TEXT DEFAULT (datetime('now')),
    read_at TEXT,
    acknowledged_at TEXT,

    FOREIGN KEY (session_id) REFERENCES agent_sessions(id) ON DELETE CASCADE,
    FOREIGN KEY (work_item_id) REFERENCES work_items(id) ON DELETE CASCADE,
    FOREIGN KEY (convoy_id) REFERENCES work_convoys(id) ON DELETE CASCADE,

    CHECK (message_type IN ('work_assignment', 'notification', 'coordination_request', 'status_update')),
    CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    CHECK (status IN ('unread', 'read', 'acknowledged', 'completed'))
);

CREATE INDEX IF NOT EXISTS idx_mailbox_session_status
    ON agent_mailbox(session_id, status, priority);
CREATE INDEX IF NOT EXISTS idx_mailbox_work_item
    ON agent_mailbox(work_item_id);

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
    s.session_uuid as assigned_session,
    s.agent_type,
    wi.created_at,
    wi.assigned_at,
    wi.started_at,
    (SELECT COUNT(*) FROM work_items sub WHERE sub.parent_item_id = wi.id) as subtask_count
FROM work_items wi
JOIN projects p ON wi.project_id = p.id
LEFT JOIN agent_sessions s ON wi.assigned_session_id = s.id
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

-- Agent workload view
CREATE VIEW IF NOT EXISTS agent_workload_view AS
SELECT
    s.id as session_id,
    s.session_uuid,
    s.agent_type,
    s.status as session_status,
    p.slug as project_slug,
    COUNT(wi.id) as assigned_items,
    SUM(CASE WHEN wi.status = 'in_progress' THEN 1 ELSE 0 END) as active_items,
    SUM(CASE WHEN wi.priority IN ('high', 'critical') THEN 1 ELSE 0 END) as high_priority_items,
    (SELECT COUNT(*) FROM agent_mailbox WHERE session_id = s.id AND status = 'unread') as unread_messages
FROM agent_sessions s
LEFT JOIN agent_sessions_projects sp ON s.id = sp.session_id
LEFT JOIN projects p ON sp.project_id = p.id
LEFT JOIN work_items wi ON s.id = wi.assigned_session_id
WHERE s.status = 'active'
GROUP BY s.id;

-- Convoy progress view
CREATE VIEW IF NOT EXISTS convoy_progress_view AS
SELECT
    c.id as convoy_id,
    c.convoy_name,
    c.status as convoy_status,
    p.slug as project_slug,
    COUNT(cwi.work_item_id) as total_items,
    SUM(CASE WHEN wi.status = 'completed' THEN 1 ELSE 0 END) as completed_items,
    SUM(CASE WHEN wi.status IN ('in_progress', 'assigned') THEN 1 ELSE 0 END) as active_items,
    SUM(CASE WHEN wi.status = 'blocked' THEN 1 ELSE 0 END) as blocked_items,
    ROUND(
        CAST(SUM(CASE WHEN wi.status = 'completed' THEN 1 ELSE 0 END) AS FLOAT) /
        CAST(COUNT(cwi.work_item_id) AS FLOAT) * 100,
        2
    ) as completion_percentage
FROM work_convoys c
JOIN projects p ON c.project_id = p.id
LEFT JOIN convoy_work_items cwi ON c.id = cwi.convoy_id
LEFT JOIN work_items wi ON cwi.work_item_id = wi.id
GROUP BY c.id;

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
        session_id,
        transitioned_at
    ) VALUES (
        NEW.id,
        OLD.status,
        NEW.status,
        NEW.assigned_session_id,
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

-- Automatically send mailbox message on work assignment
CREATE TRIGGER IF NOT EXISTS notify_agent_on_assignment
AFTER UPDATE OF assigned_session_id ON work_items
WHEN NEW.assigned_session_id IS NOT NULL
    AND (OLD.assigned_session_id IS NULL OR OLD.assigned_session_id != NEW.assigned_session_id)
BEGIN
    INSERT INTO agent_mailbox (
        session_id,
        message_type,
        work_item_id,
        message_content,
        priority
    ) VALUES (
        NEW.assigned_session_id,
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

-- Update convoy status when all items complete
CREATE TRIGGER IF NOT EXISTS update_convoy_on_completion
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

-- Migration complete
-- Run: ./templedb migration apply 020
