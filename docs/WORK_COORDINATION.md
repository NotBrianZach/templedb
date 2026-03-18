# Work Coordination System

**Status**: Production Ready ✅
**Version**: 2.0
**Last Updated**: 2026-03-04

---

## Overview

TempleDB's work coordination system provides lightweight, database-native task coordination using simple TEXT identifiers. No complex agent lifecycle management, no registration requirements - just work items with ACID transaction guarantees.

**Philosophy**: Keep it simple. TEXT identifiers beat complex state machines.

---

## Quick Start

```python
import sqlite3

conn = sqlite3.connect('templedb.sqlite')

# Create work item
conn.execute("""
    INSERT INTO work_items (id, project_id, title, priority, item_type)
    VALUES (?, ?, ?, ?, ?)
""", ('fix-auth', 1, 'Fix authentication bug', 'high', 'bug'))

# Assign to agent/user
conn.execute("""
    UPDATE work_items SET assigned_to = ?, status = 'assigned'
    WHERE id = ?
""", ('claude-agent-1', 'fix-auth'))
# Trigger automatically creates notification

# Agent polls for work
cursor = conn.execute("""
    SELECT work_item_id, message_content
    FROM work_item_notifications
    WHERE recipient = ? AND status = 'unread'
    ORDER BY priority DESC
""", ('claude-agent-1',))

# Complete work
conn.execute("""
    UPDATE work_items SET status = 'completed' WHERE id = ?
""", ('fix-auth',))
# Trigger updates completed_at timestamp

conn.commit()
```

---

## Core Tables

### 1. work_items

Main table for tracking work.

```sql
CREATE TABLE work_items (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    priority TEXT DEFAULT 'medium',
    item_type TEXT DEFAULT 'task',

    -- Assignment (TEXT identifiers - no foreign keys)
    assigned_to TEXT,
    created_by TEXT,
    parent_item_id TEXT,

    -- Metadata
    estimated_effort TEXT,
    tags TEXT,
    metadata TEXT,

    -- Timestamps (auto-managed by triggers)
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    assigned_at TEXT,
    started_at TEXT,
    completed_at TEXT,

    CHECK (status IN ('pending', 'assigned', 'in_progress', 'completed', 'blocked', 'cancelled')),
    CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    CHECK (item_type IN ('task', 'bug', 'feature', 'refactor', 'research', 'documentation'))
);
```

**Key Design**:
- `assigned_to` and `created_by` are TEXT (can be agent names, emails, session IDs)
- No database enforcement of agent existence
- Flexible for different coordination scenarios

### 2. work_item_notifications

Lightweight message passing.

```sql
CREATE TABLE work_item_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient TEXT NOT NULL,
    message_type TEXT NOT NULL,
    work_item_id TEXT,
    convoy_id INTEGER,
    message_content TEXT NOT NULL,  -- JSON
    priority TEXT DEFAULT 'normal',
    status TEXT NOT NULL DEFAULT 'unread',
    delivered_at TEXT DEFAULT (datetime('now')),
    read_at TEXT,
    acknowledged_at TEXT,

    CHECK (message_type IN ('work_assignment', 'notification', 'coordination_request', 'status_update')),
    CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    CHECK (status IN ('unread', 'read', 'acknowledged', 'completed'))
);
```

**Usage**: Agents poll `WHERE recipient = ? AND status = 'unread'`

### 3. work_item_transitions

Audit trail for status changes.

```sql
CREATE TABLE work_item_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    changed_by TEXT,
    reason TEXT,
    transitioned_at TEXT DEFAULT (datetime('now'))
);
```

**Auto-populated**: `record_work_item_transition` trigger fires on status changes

### 4. work_convoys

Group related work items (Gas Town inspired).

```sql
CREATE TABLE work_convoys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convoy_name TEXT NOT NULL,
    project_id INTEGER NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    coordinator TEXT,  -- TEXT identifier, not FK
    created_at TEXT DEFAULT (datetime('now')),
    started_at TEXT,
    completed_at TEXT,

    CHECK (status IN ('pending', 'active', 'completed', 'cancelled'))
);
```

**Junction table**:
```sql
CREATE TABLE convoy_work_items (
    convoy_id INTEGER NOT NULL,
    work_item_id TEXT NOT NULL,
    sequence_order INTEGER,
    added_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (convoy_id, work_item_id)
);
```

---

## Triggers

### 1. update_work_item_timestamp
Updates `updated_at` on any change.

### 2. record_work_item_transition
- Tracks status changes in `work_item_transitions`
- Updates timestamps: `assigned_at`, `started_at`, `completed_at`

### 3. notify_on_assignment
Creates notification when work item assigned:

```sql
-- Fires when assigned_to changes
INSERT INTO work_item_notifications (
    recipient, message_type, work_item_id, message_content, priority
) VALUES (
    NEW.assigned_to, 'work_assignment', NEW.id,
    json_object('work_item_id', NEW.id, 'title', NEW.title, ...),
    CASE NEW.priority WHEN 'critical' THEN 'urgent' ... END
);
```

### 4. update_convoy_on_completion
Marks convoy complete when all items done:

```sql
-- Fires when work item completed
UPDATE work_convoys SET status = 'completed', completed_at = datetime('now')
WHERE id IN (SELECT convoy_id FROM convoy_work_items WHERE work_item_id = NEW.id)
AND NOT EXISTS (
    SELECT 1 FROM convoy_work_items cwi
    JOIN work_items wi ON cwi.work_item_id = wi.id
    WHERE cwi.convoy_id = work_convoys.id AND wi.status != 'completed'
);
```

---

## Views

### active_work_items_view
Non-completed work items:

```sql
SELECT wi.id, wi.title, wi.status, wi.priority, wi.item_type,
       p.slug as project_slug, wi.assigned_to,
       (SELECT COUNT(*) FROM work_items sub WHERE sub.parent_item_id = wi.id) as subtask_count
FROM work_items wi
JOIN projects p ON wi.project_id = p.id
WHERE wi.status IN ('pending', 'assigned', 'in_progress', 'blocked');
```

### work_item_stats_view
Project-level statistics:

```sql
SELECT p.slug, p.name,
       COUNT(*) as total_items,
       SUM(CASE WHEN wi.status = 'pending' THEN 1 ELSE 0 END) as pending_count,
       SUM(CASE WHEN wi.status = 'in_progress' THEN 1 ELSE 0 END) as in_progress_count,
       SUM(CASE WHEN wi.status = 'completed' THEN 1 ELSE 0 END) as completed_count,
       ...
FROM projects p LEFT JOIN work_items wi ON p.id = wi.project_id
GROUP BY p.id;
```

### assignee_workload_view
Per-assignee workload:

```sql
SELECT wi.assigned_to, p.slug,
       COUNT(wi.id) as assigned_items,
       SUM(CASE WHEN wi.status = 'in_progress' THEN 1 ELSE 0 END) as active_items,
       (SELECT COUNT(*) FROM work_item_notifications
        WHERE recipient = wi.assigned_to AND status = 'unread') as unread_messages
FROM work_items wi JOIN projects p ON wi.project_id = p.id
WHERE wi.assigned_to IS NOT NULL
GROUP BY wi.assigned_to, p.slug;
```

### convoy_progress_view
Convoy completion:

```sql
SELECT c.id, c.convoy_name, c.status,
       COUNT(cwi.work_item_id) as total_items,
       SUM(CASE WHEN wi.status = 'completed' THEN 1 ELSE 0 END) as completed_items,
       ...
FROM work_convoys c
LEFT JOIN convoy_work_items cwi ON c.id = cwi.convoy_id
LEFT JOIN work_items wi ON cwi.work_item_id = wi.id
GROUP BY c.id;
```

---

## Usage Patterns

### Single Work Item

```python
# Create
conn.execute("""
    INSERT INTO work_items (id, project_id, title, description, priority, item_type)
    VALUES (?, ?, ?, ?, ?, ?)
""", ('fix-auth', 1, 'Fix authentication bug', 'Users cannot log in', 'high', 'bug'))

# Assign
conn.execute("""
    UPDATE work_items SET assigned_to = ?, status = 'assigned' WHERE id = ?
""", ('agent-1', 'fix-auth'))

# Start work
conn.execute("UPDATE work_items SET status = 'in_progress' WHERE id = ?", ('fix-auth',))

# Complete
conn.execute("UPDATE work_items SET status = 'completed' WHERE id = ?", ('fix-auth',))
```

### Multi-Agent Convoy

```python
# Create convoy
conn.execute("""
    INSERT INTO work_convoys (convoy_name, project_id, coordinator, status)
    VALUES (?, ?, ?, ?)
""", ('refactor-auth-system', 1, 'claude-mayor', 'active'))
convoy_id = cursor.lastrowid

# Create and add work items
items = [
    ('refactor-models', 'Refactor auth models'),
    ('update-tests', 'Update auth tests'),
    ('migrate-sessions', 'Migrate user sessions')
]

for item_id, title in items:
    conn.execute("""
        INSERT INTO work_items (id, project_id, title, item_type, status)
        VALUES (?, ?, ?, ?, ?)
    """, (item_id, 1, title, 'refactor', 'pending'))

    conn.execute("""
        INSERT INTO convoy_work_items (convoy_id, work_item_id)
        VALUES (?, ?)
    """, (convoy_id, item_id))

# Assign to different agents
conn.execute("UPDATE work_items SET assigned_to = ? WHERE id = ?", ('agent-1', 'refactor-models'))
conn.execute("UPDATE work_items SET assigned_to = ? WHERE id = ?", ('agent-2', 'update-tests'))
conn.execute("UPDATE work_items SET assigned_to = ? WHERE id = ?", ('agent-3', 'migrate-sessions'))

# When all complete, trigger auto-marks convoy complete
```

### Agent Work Loop

```python
def agent_work_loop(agent_id):
    while True:
        # Check for new assignments
        cursor = conn.execute("""
            SELECT work_item_id, message_content
            FROM work_item_notifications
            WHERE recipient = ? AND status = 'unread'
            AND message_type = 'work_assignment'
            ORDER BY priority DESC, delivered_at ASC
        """, (agent_id,))

        for row in cursor:
            work_item_id = row[0]
            details = json.loads(row[1])

            # Mark notification read
            conn.execute("""
                UPDATE work_item_notifications
                SET status = 'read', read_at = datetime('now')
                WHERE work_item_id = ? AND recipient = ?
            """, (work_item_id, agent_id))

            # Start work
            conn.execute("""
                UPDATE work_items SET status = 'in_progress' WHERE id = ?
            """, (work_item_id,))

            # Do the actual work
            result = perform_work(work_item_id, details)

            # Complete
            conn.execute("""
                UPDATE work_items SET status = 'completed' WHERE id = ?
            """, (work_item_id,))

            conn.commit()

        time.sleep(5)  # Poll interval
```

---

## Design Principles

### 1. No Database-Managed Identity
- Agents/users are TEXT strings, not database entities
- No registration required
- Flexible for different coordination models

### 2. Lightweight Message Passing
- Notifications are simple records
- Poll-based, not push-based
- Agent decides when to check for work

### 3. Gas Town Pattern
- Named after Terry Davis's coordination pattern
- "Mayor" agent coordinates multiple workers
- Convoy tracks related work items
- Automatic completion detection

### 4. ACID Guarantees
- All coordination is transactional
- No lost assignments
- No race conditions on status updates

### 5. Audit Trail
- All status changes tracked
- Timestamps auto-updated by triggers
- JSON metadata for custom properties

---

## History

### Previous System (Pre-2026-03-04)
- Complex `agent_sessions` table with lifecycle management
- `agent_mailbox` with foreign keys to agent_sessions
- Database-managed agent state
- **4,523 lines** of agent management code

**Problems**:
- Too complex for simple use cases
- Required agent registration
- Foreign key constraints prevented flexible coordination

### Current System (2026-03-04+)
- Simple TEXT identifiers
- No agent registration
- **~500 lines** (migrations only)

**Commit 22f64fe**: Removed legacy agent code
**Migrations 020-025**: Complete work coordination system

---

## Comparison: Old vs New

| Feature | Old (Agent Sessions) | New (TEXT Identifiers) |
|---------|---------------------|------------------------|
| Agent Identity | FK to agent_sessions | TEXT string |
| Registration | Required | Not required |
| Message Passing | agent_mailbox with FK | work_item_notifications |
| Assignment | assigned_session_id INTEGER | assigned_to TEXT |
| Coordination | Complex state machine | Simple convoy + TEXT |
| Code Complexity | 4,523 lines | ~500 lines |
| Flexibility | Low | High |

---

## Related Documentation

- **[migrations/020_add_work_items_coordination.sql](migrations/020_add_work_items_coordination.sql)** - Complete schema
- **[migrations/021_remove_agent_sessions.sql](migrations/021_remove_agent_sessions.sql)** - Agent cleanup
- **[ROADMAP.md](ROADMAP.md)** - Overall TempleDB direction

---

**Status**: ✅ Production Ready
**Complexity**: Minimal (500 lines vs 4,523)
**Philosophy**: Simple TEXT identifiers beat complex state machines
