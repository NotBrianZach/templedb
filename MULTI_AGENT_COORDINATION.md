# Multi-Agent Coordination in TempleDB

> Inspired by [Gas Town](https://github.com/steveyegge/gastown) - A multi-agent workspace manager

## Overview

TempleDB now includes a complete multi-agent coordination system that enables multiple AI agents to work on different tasks in parallel, with centralized orchestration and task management.

### Architecture

The system is inspired by Gas Town's hierarchical coordination model:

- **Work Items (Beads)**: Structured tasks stored as database records with unique IDs (`tdb-xxxxx`)
- **Agent Coordinator (Mayor)**: Orchestrates task assignment and monitors agent workload
- **Worker Agents**: Individual agent sessions assigned to specific work items
- **Mailbox System**: Asynchronous task assignment via database-backed mailbox
- **Convoys**: Bundles of related work items that can be dispatched together

### Key Advantages Over Gas Town

TempleDB's database-native approach provides several improvements:

| Feature | Gas Town | TempleDB |
|---------|----------|----------|
| Coordination Cost | O(k²) via git | **O(k) via database** ✅ |
| Conflict Detection | Content scanning | **Version numbers** ✅ |
| Multi-Agent Safety | Git merge conflicts | **ACID transactions** ✅ |
| State Persistence | Git hooks + Beads | **Database + VCS** ✅ |
| Query Capability | Dolt SQL layer | **Native SQLite** ✅ |

The single-source-of-truth database with ACID transactions makes multi-agent coordination fundamentally simpler and more reliable.

---

## Schema

### Work Items Table

```sql
CREATE TABLE work_items (
    id TEXT PRIMARY KEY,                    -- Format: 'tdb-xxxxx' (5 alphanumeric chars)
    project_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending', -- pending, assigned, in_progress, completed, blocked, cancelled
    priority TEXT DEFAULT 'medium',         -- low, medium, high, critical
    item_type TEXT DEFAULT 'task',          -- task, bug, feature, refactor, research, documentation

    -- Assignment
    assigned_session_id INTEGER,            -- Current agent session working on this
    created_by_session_id INTEGER,          -- Agent session that created this item
    parent_item_id TEXT,                    -- For sub-tasks/dependencies

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    assigned_at TEXT,
    started_at TEXT,
    completed_at TEXT,

    FOREIGN KEY (assigned_session_id) REFERENCES agent_sessions(id)
);
```

### Convoys (Work Bundles)

```sql
CREATE TABLE work_convoys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    convoy_name TEXT NOT NULL,
    project_id INTEGER NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    coordinator_session_id INTEGER,
    created_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (coordinator_session_id) REFERENCES agent_sessions(id)
);
```

### Agent Mailbox

```sql
CREATE TABLE agent_mailbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    message_type TEXT NOT NULL,             -- work_assignment, notification, coordination_request
    work_item_id TEXT,
    message_content TEXT NOT NULL,          -- JSON message content
    priority TEXT DEFAULT 'normal',
    status TEXT NOT NULL DEFAULT 'unread',  -- unread, read, acknowledged, completed
    delivered_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (session_id) REFERENCES agent_sessions(id)
);
```

---

## CLI Commands

### Work Item Management

#### Create Work Item

```bash
# Basic work item
./templedb work create -p myproject -t "Fix authentication bug" --type bug --priority high

# With description and parent
./templedb work create -p myproject -t "Add unit tests" \
  -d "Cover edge cases in auth module" \
  --type task \
  --parent tdb-abc12

# Auto-links to current agent session via TEMPLEDB_SESSION_ID
export TEMPLEDB_SESSION_ID=1
./templedb work create -p myproject -t "Refactor API endpoints" --type refactor
```

**Output:**
```
Created work item: tdb-09lry
  Title: Fix authentication bug
  Type: bug
  Priority: high
  Status: pending
```

#### List Work Items

```bash
# List all active items
./templedb work list

# Filter by project
./templedb work list -p myproject

# Filter by status and priority
./templedb work list -s in_progress --priority critical

# Show all items including completed
./templedb work list -a

# Filter by assigned agent
./templedb work list --assigned-session 5
```

**Output:**
```
ID        | Project  | Title                        | Type | Status      | Priority | Assigned | Subtasks
----------+----------+------------------------------+------+-------------+----------+----------+---------
tdb-09lry | templedb | Fix authentication bug       | bug  | in_progress | high     | abc12... | 2
tdb-2y6v6 | templedb | Add unit tests               | task | pending     | medium   | -        | -

Total: 2 items
```

#### Show Work Item Details

```bash
./templedb work show tdb-09lry
```

**Output:**
```
Work Item: tdb-09lry
  Title: Fix authentication bug
  Project: MyProject (myproject)
  Type: bug
  Status: in_progress
  Priority: high
  Description: Users unable to login with OAuth

  Assigned to: Session 5 (abc12345-67...)
    Agent: claude
    Assigned at: 2026-02-27 14:30:00

  Created by: Session 3 (xyz98765-43...)
  Created: 2026-02-27 10:00:00
  Updated: 2026-02-27 14:32:15
  Started: 2026-02-27 14:30:30

  Subtasks (2):
    tdb-x1y2z: Add OAuth error logging [completed]
    tdb-a3b4c: Update auth documentation [pending]

  Recent Transitions:
    pending → assigned at 2026-02-27 14:30:00 (by abc12...)
    assigned → in_progress at 2026-02-27 14:30:30 (by abc12...)
```

#### Assign Work Item

```bash
# Manually assign to specific agent session
./templedb work assign tdb-09lry 5

# Or use coordinator auto-dispatch (see below)
```

#### Update Status

```bash
./templedb work status tdb-09lry in_progress
./templedb work status tdb-09lry completed
```

#### Statistics

```bash
# Global stats
./templedb work stats

# Project-specific stats
./templedb work stats -p myproject
```

**Output:**
```
Work Item Statistics
========================================
Total Items: 15

By Status:
  Pending:     3
  Assigned:    2
  In Progress: 5
  Completed:   4
  Blocked:     1
  Cancelled:   0

By Priority:
  Critical:    2
  High:        5

Completion Rate: 26.7%
Active Items: 7
```

### Multi-Agent Coordination

#### List Available Agents

```bash
# Show all active agents with workload
./templedb work agents

# Filter by project
./templedb work agents -p myproject
```

**Output:**
```
Session ID | UUID             | Type   | Project  | Active Work | Unread Msgs
-----------+------------------+--------+----------+-------------+------------
5          | abc12345-67...   | claude | myproject| 3           | 2
8          | xyz98765-43...   | claude | myproject| 1           | 0
12         | def45678-90...   | cursor | myproject| 0           | 0

Total: 3 active agents
```

#### Auto-Dispatch Work

```bash
# Dispatch all pending work to available agents
./templedb work dispatch

# Dispatch for specific project
./templedb work dispatch -p myproject

# Dispatch only high-priority items
./templedb work dispatch --priority high
```

**Output:**
```
Dispatched 5 work items to available agents
```

The dispatcher uses a least-busy algorithm, automatically selecting agents with the lowest active workload.

#### View Coordination Metrics

```bash
# Global metrics
./templedb work metrics

# Project-specific metrics
./templedb work metrics -p myproject
```

**Output:**
```
Multi-Agent Coordination Metrics
==================================================

Work Items:
  Total:        15
  Pending:      3
  Assigned:     2
  In Progress:  5
  Completed:    4
  Blocked:      1

Agents:
  Active:       3
  Busy:         2

Efficiency:
  Agent Utilization: 66.7%
```

#### View Agent Mailbox

```bash
# Show all messages for an agent
./templedb work mailbox 5

# Filter by status
./templedb work mailbox 5 -s unread
```

**Output:**
```
Mailbox for Session 5 (abc12345-67...)
================================================================================

📬 🟠 [work_assignment] 2026-02-27 14:30:00
   Work Item: tdb-09lry
   Title: Fix authentication bug
   Priority: high

📭 🟢 [notification] 2026-02-27 14:25:00
   Content: Work item tdb-xyz99 was completed

2 messages shown (1 unread)
```

---

## Python API

### Using the Agent Coordinator

```python
from agent_coordinator import AgentCoordinator

# Initialize coordinator
coordinator = AgentCoordinator(coordinator_session_id=1)

# Get available agents
agents = coordinator.get_available_agents(project_id=5)
print(f"Available agents: {len(agents)}")

# Auto-assign work item to least-busy agent
coordinator.assign_work_item_to_agent(
    work_item_id='tdb-abc12',
    auto_select=True
)

# Create a convoy (bundle of related work)
work_item_ids = ['tdb-abc12', 'tdb-def34', 'tdb-ghi56']
convoy_id = coordinator.create_convoy(
    project_id=5,
    convoy_name='Authentication Refactor',
    work_item_ids=work_item_ids,
    description='Complete overhaul of auth system'
)

# Start convoy with auto-assignment
coordinator.start_convoy(convoy_id, auto_assign=True)

# Dispatch all pending work
dispatched = coordinator.dispatch_pending_work(
    project_id=5,
    priority_filter='high'
)
print(f"Dispatched {dispatched} items")

# Get coordination metrics
metrics = coordinator.get_coordination_metrics(project_id=5)
print(f"Agent utilization: {metrics['efficiency']['utilization_rate']:.1%}")
```

---

## Workflow Patterns

### Pattern 1: Manual Coordination

```bash
# 1. Create work items
./templedb work create -p myproject -t "Implement feature A" --type feature
./templedb work create -p myproject -t "Implement feature B" --type feature

# 2. Start agent sessions
./templedb agent start -p myproject --goal "Implement feature A"
# → Session ID: 5
./templedb agent start -p myproject --goal "Implement feature B"
# → Session ID: 6

# 3. Manually assign work
./templedb work assign tdb-abc12 5
./templedb work assign tdb-def34 6

# 4. Monitor progress
./templedb work list -p myproject
./templedb work metrics -p myproject
```

### Pattern 2: Auto-Dispatch Coordination

```bash
# 1. Create multiple work items
./templedb work create -p myproject -t "Task 1" --type task --priority high
./templedb work create -p myproject -t "Task 2" --type task --priority high
./templedb work create -p myproject -t "Task 3" --type task --priority medium

# 2. Start multiple agent sessions
./templedb agent start -p myproject --non-interactive &
./templedb agent start -p myproject --non-interactive &
./templedb agent start -p myproject --non-interactive &

# 3. Auto-dispatch all pending work
./templedb work dispatch -p myproject

# 4. Monitor coordination
watch -n 2 './templedb work metrics -p myproject'
```

### Pattern 3: Session-Linked Work Creation

```bash
# Start coordinator agent session
./templedb agent start -p myproject --goal "Coordinate team work"
# → Session ID: 1
export TEMPLEDB_SESSION_ID=1

# Create work items (automatically linked to coordinator)
./templedb work create -p myproject -t "Refactor module X" --type refactor
./templedb work create -p myproject -t "Add tests for Y" --type task
./templedb work create -p myproject -t "Update docs" --type documentation

# Dispatch to worker agents
./templedb work dispatch -p myproject

# View items created by this coordinator
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT id, title FROM work_items WHERE created_by_session_id = 1"
```

---

## Database Views

### Active Work Items View

```sql
SELECT * FROM active_work_items_view;
```

Shows all pending/in-progress/blocked items with project and assignment info.

### Agent Workload View

```sql
SELECT * FROM agent_workload_view;
```

Shows each active agent's workload including assigned items, active items, and unread messages.

### Convoy Progress View

```sql
SELECT * FROM convoy_progress_view WHERE convoy_id = 5;
```

Shows completion percentage and status breakdown for convoys.

---

## Integration with Agent Sessions

Work items integrate seamlessly with TempleDB's existing agent session tracking:

1. **Auto-linking**: Setting `TEMPLEDB_SESSION_ID` automatically links created work items to the creating session
2. **Commit tracking**: Work items can reference commits via the agent session relationship
3. **Context**: Agent sessions can query their assigned work items for context
4. **Mailbox**: Agents receive work assignment notifications in their mailbox

Example integration:

```bash
# Start agent session
./templedb agent start -p myproject --goal "Fix bugs"
# → Session ID: 5
export TEMPLEDB_SESSION_ID=5

# Create work item (auto-linked to session 5)
./templedb work create -p myproject -t "Fix bug #123" --type bug

# Do work and commit
./templedb project checkout myproject /tmp/work
cd /tmp/work && vim src/auth.py
./templedb project commit myproject /tmp/work -m "Fixed auth bug" --ai-assisted

# Work item and commits are now linked via session 5
./templedb agent status 5
# Shows: commits, work items, and interactions
```

---

## Future Enhancements

The following features are planned but not yet implemented:

1. **Workflow Templates**: TOML-based workflow definitions (Gas Town-style formulas)
2. **Web Dashboard**: Real-time monitoring UI for agent coordination
3. **Convoy Management CLI**: Commands for creating and managing convoys
4. **Work Item Dependencies**: DAG-based dependency resolution
5. **Agent Performance Metrics**: Track completion time, success rate per agent
6. **Work Item Templates**: Reusable templates for common task types
7. **Batch Operations**: Bulk create/assign/update operations

---

## Comparison with Gas Town

### What TempleDB Took from Gas Town

✅ **Beads System**: Structured work items with unique IDs
✅ **Mailbox-Style Assignment**: Asynchronous task coordination
✅ **Convoys**: Bundling related work items
✅ **Mayor/Worker Architecture**: Coordinator + worker agents
✅ **Multi-Agent Orchestration**: Parallel task execution

### Where TempleDB Improves on Gas Town

✅ **Database-Native**: Single source of truth, no git-based coordination overhead
✅ **ACID Transactions**: Conflict-free multi-agent coordination
✅ **O(k) Coordination**: Linear scaling vs. O(k²) git-based coordination
✅ **Rich Queries**: SQL-based work item queries and analytics
✅ **Integrated VCS**: Work items link directly to commits and file versions
✅ **No External Dependencies**: Self-contained SQLite database

---

## References

- **Gas Town Project**: https://github.com/steveyegge/gastown
- **Gas Town Blog Post**: https://steve-yegge.medium.com/welcome-to-gas-town-4f25ee16dd04
- **DoltHub Analysis**: https://www.dolthub.com/blog/2026-01-15-a-day-in-gas-town/
- **TempleDB Design Philosophy**: [DESIGN_PHILOSOPHY.md](DESIGN_PHILOSOPHY.md)
- **Agent Session Management**: [AGENT_SESSIONS.md](AGENT_SESSIONS.md)

---

**TempleDB - Where your code finds sanctuary, and your agents find purpose.**
