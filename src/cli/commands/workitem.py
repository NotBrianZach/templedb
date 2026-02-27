"""CLI commands for work item and multi-agent coordination management."""

import sys
import os
import json
import random
import string
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cli.core import Command
from repositories import ProjectRepository
from repositories.agent_repository import AgentRepository
from logger import get_logger
from config import DB_PATH
import db_utils
from agent_coordinator import AgentCoordinator

logger = get_logger(__name__)


def generate_work_item_id() -> str:
    """Generate a work item ID in format 'tdb-xxxxx' (5 alphanumeric chars)"""
    chars = string.ascii_lowercase + string.digits
    random_part = ''.join(random.choices(chars, k=5))
    return f'tdb-{random_part}'


class WorkItemCommands(Command):
    """Work item and coordination command handlers"""

    def __init__(self):
        super().__init__()
        self.project_repo = ProjectRepository()
        self.agent_repo = AgentRepository(DB_PATH)
        self.coordinator = AgentCoordinator()

    def _get_project_id(self, project: str) -> Optional[int]:
        """
        Get project ID from slug or ID string.

        Args:
            project: Project slug or ID string

        Returns:
            Project ID or None if not found
        """
        try:
            project_id = int(project)
            project_obj = self.project_repo.get_by_id(project_id)
        except ValueError:
            project_obj = self.project_repo.get_by_slug(project)

        if not project_obj:
            logger.error(f"Project '{project}' not found")
            return None

        return project_obj['id']

    def _format_table(self, data, headers):
        """Simple table formatting"""
        if not data:
            return ""

        # Calculate column widths
        col_widths = [len(str(h)) for h in headers]
        for row in data:
            for i, cell in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(cell)))

        # Format header
        header_row = " | ".join(str(h).ljust(col_widths[i]) for i, h in enumerate(headers))
        separator = "-+-".join("-" * w for w in col_widths)

        # Format rows
        rows = []
        for row in data:
            rows.append(" | ".join(str(cell).ljust(col_widths[i]) for i, cell in enumerate(row)))

        return "\n".join([header_row, separator] + rows)

    def create_item(self, args) -> int:
        """Create a new work item."""
        project = args.project
        title = args.title
        description = getattr(args, 'description', None)
        item_type = getattr(args, 'type', 'task')
        priority = getattr(args, 'priority', 'medium')
        parent_id = getattr(args, 'parent', None)

        # Get project
        project_id = self._get_project_id(project)
        if not project_id:
            return 1

        # Check for TEMPLEDB_SESSION_ID to link to creating session
        session_id = os.environ.get('TEMPLEDB_SESSION_ID')
        if session_id:
            try:
                session_id = int(session_id)
                session = self.agent_repo.get_session(session_id)
                if not session:
                    logger.warning(f"Session ID {session_id} from TEMPLEDB_SESSION_ID not found, ignoring")
                    session_id = None
            except ValueError:
                logger.warning(f"Invalid TEMPLEDB_SESSION_ID value: {session_id}, ignoring")
                session_id = None
        else:
            session_id = None

        # Generate work item ID
        work_item_id = generate_work_item_id()

        # Check for collisions (very unlikely but possible)
        max_attempts = 10
        for _ in range(max_attempts):
            existing = db_utils.query_one(
                "SELECT id FROM work_items WHERE id = ?",
                (work_item_id,)
            )
            if not existing:
                break
            work_item_id = generate_work_item_id()

        # Insert work item
        db_utils.execute("""
            INSERT INTO work_items (
                id, project_id, title, description, status, priority, item_type,
                created_by_session_id, parent_item_id
            ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?)
        """, (
            work_item_id,
            project_id,
            title,
            description,
            priority,
            item_type,
            session_id,
            parent_id
        ))

        print(f"Created work item: {work_item_id}")
        print(f"  Title: {title}")
        print(f"  Type: {item_type}")
        print(f"  Priority: {priority}")
        print(f"  Status: pending")
        if parent_id:
            print(f"  Parent: {parent_id}")
        if session_id:
            print(f"  Created by session: {session_id}")

        return 0

    def list_items(self, args) -> int:
        """List work items."""
        project = getattr(args, 'project', None)
        status = getattr(args, 'status', None)
        priority = getattr(args, 'priority', None)
        assigned_session = getattr(args, 'assigned_session', None)
        show_all = getattr(args, 'all', False)

        # Build query
        where_clauses = []
        params = []

        if project:
            # Get project ID
            project_id = self._get_project_id(project)
            if not project_id:
                return 1

            where_clauses.append("wi.project_id = ?")
            params.append(project_id)

        if status:
            where_clauses.append("wi.status = ?")
            params.append(status)
        elif not show_all:
            # By default, show only active items
            where_clauses.append("wi.status IN ('pending', 'assigned', 'in_progress', 'blocked')")

        if priority:
            where_clauses.append("wi.priority = ?")
            params.append(priority)

        if assigned_session:
            where_clauses.append("wi.assigned_session_id = ?")
            params.append(int(assigned_session))

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

        # Query items
        items = db_utils.query_all(f"""
            SELECT
                wi.id,
                wi.title,
                wi.status,
                wi.priority,
                wi.item_type,
                p.slug as project_slug,
                s.session_uuid as assigned_session,
                wi.created_at,
                (SELECT COUNT(*) FROM work_items sub WHERE sub.parent_item_id = wi.id) as subtask_count
            FROM work_items wi
            JOIN projects p ON wi.project_id = p.id
            LEFT JOIN agent_sessions s ON wi.assigned_session_id = s.id
            WHERE {where_sql}
            ORDER BY
                CASE wi.priority
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    WHEN 'low' THEN 4
                END,
                wi.created_at DESC
        """, tuple(params))

        if not items:
            print("No work items found")
            return 0

        # Format output
        headers = ["ID", "Project", "Title", "Type", "Status", "Priority", "Assigned", "Subtasks"]
        rows = []
        for item in items:
            rows.append([
                item['id'],
                item['project_slug'],
                item['title'][:40] + ('...' if len(item['title']) > 40 else ''),
                item['item_type'],
                item['status'],
                item['priority'],
                item['assigned_session'][:8] if item['assigned_session'] else '-',
                str(item['subtask_count']) if item['subtask_count'] > 0 else '-'
            ])

        print(self._format_table(rows, headers))
        print(f"\nTotal: {len(items)} items")

        return 0

    def show_item(self, args) -> int:
        """Show detailed information about a work item."""
        item_id = args.item_id

        # Get item
        item = db_utils.query_one("""
            SELECT
                wi.*,
                p.slug as project_slug,
                p.name as project_name,
                s.session_uuid as assigned_session_uuid,
                s.agent_type as assigned_agent_type,
                cs.session_uuid as created_by_session_uuid
            FROM work_items wi
            JOIN projects p ON wi.project_id = p.id
            LEFT JOIN agent_sessions s ON wi.assigned_session_id = s.id
            LEFT JOIN agent_sessions cs ON wi.created_by_session_id = cs.id
            WHERE wi.id = ?
        """, (item_id,))

        if not item:
            logger.error(f"Work item '{item_id}' not found")
            return 1

        # Print details
        print(f"Work Item: {item['id']}")
        print(f"  Title: {item['title']}")
        print(f"  Project: {item['project_name']} ({item['project_slug']})")
        print(f"  Type: {item['item_type']}")
        print(f"  Status: {item['status']}")
        print(f"  Priority: {item['priority']}")

        if item['description']:
            print(f"  Description: {item['description']}")

        if item['parent_item_id']:
            print(f"  Parent: {item['parent_item_id']}")

        if item['assigned_session_id']:
            print(f"  Assigned to: Session {item['assigned_session_id']} ({item['assigned_session_uuid'][:16]}...)")
            print(f"    Agent: {item['assigned_agent_type']}")
            print(f"    Assigned at: {item['assigned_at']}")

        if item['created_by_session_id']:
            print(f"  Created by: Session {item['created_by_session_id']} ({item['created_by_session_uuid'][:16]}...)")

        print(f"  Created: {item['created_at']}")
        print(f"  Updated: {item['updated_at']}")

        if item['started_at']:
            print(f"  Started: {item['started_at']}")
        if item['completed_at']:
            print(f"  Completed: {item['completed_at']}")

        # Show subtasks if any
        subtasks = db_utils.query_all("""
            SELECT id, title, status, priority
            FROM work_items
            WHERE parent_item_id = ?
            ORDER BY created_at
        """, (item_id,))

        if subtasks:
            print(f"\n  Subtasks ({len(subtasks)}):")
            for sub in subtasks:
                print(f"    {sub['id']}: {sub['title']} [{sub['status']}]")

        # Show state transitions
        transitions = db_utils.query_all("""
            SELECT
                from_status,
                to_status,
                transitioned_at,
                s.session_uuid
            FROM work_item_transitions wt
            LEFT JOIN agent_sessions s ON wt.session_id = s.id
            WHERE wt.work_item_id = ?
            ORDER BY wt.transitioned_at DESC
            LIMIT 10
        """, (item_id,))

        if transitions:
            print(f"\n  Recent Transitions:")
            for t in transitions:
                session_info = f" (by {t['session_uuid'][:8]}...)" if t['session_uuid'] else ""
                print(f"    {t['from_status']} → {t['to_status']} at {t['transitioned_at']}{session_info}")

        return 0

    def assign_item(self, args) -> int:
        """Assign a work item to an agent session."""
        item_id = args.item_id
        session_id = args.session_id

        # Verify item exists
        item = db_utils.query_one("SELECT id, status FROM work_items WHERE id = ?", (item_id,))
        if not item:
            logger.error(f"Work item '{item_id}' not found")
            return 1

        # Verify session exists and is active
        session = self.agent_repo.get_session(session_id)
        if not session:
            logger.error(f"Session {session_id} not found")
            return 1

        if session['status'] != 'active':
            logger.error(f"Session {session_id} is not active (status: {session['status']})")
            return 1

        # Assign item
        db_utils.execute("""
            UPDATE work_items
            SET assigned_session_id = ?,
                status = CASE
                    WHEN status = 'pending' THEN 'assigned'
                    ELSE status
                END
            WHERE id = ?
        """, (session_id, item_id))

        print(f"Assigned work item {item_id} to session {session_id} ({session['session_uuid'][:16]}...)")

        # Show mailbox message was created
        print(f"✓ Work assignment notification sent to agent mailbox")

        return 0

    def update_status(self, args) -> int:
        """Update work item status."""
        item_id = args.item_id
        new_status = args.status

        # Verify item exists
        item = db_utils.query_one("SELECT id, status FROM work_items WHERE id = ?", (item_id,))
        if not item:
            logger.error(f"Work item '{item_id}' not found")
            return 1

        old_status = item['status']
        if old_status == new_status:
            print(f"Work item {item_id} is already in status '{new_status}'")
            return 0

        # Update status
        db_utils.execute("""
            UPDATE work_items
            SET status = ?
            WHERE id = ?
        """, (new_status, item_id))

        print(f"Updated work item {item_id}: {old_status} → {new_status}")

        return 0

    def stats(self, args) -> int:
        """Show work item statistics."""
        project = getattr(args, 'project', None)

        where_sql = ""
        params = []
        if project:
            # Get project ID
            project_id = self._get_project_id(project)
            if not project_id:
                return 1

            where_sql = "WHERE project_id = ?"
            params.append(project_id)

        # Get statistics
        stats = db_utils.query_one(f"""
            SELECT
                COUNT(*) as total_items,
                SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN status = 'assigned' THEN 1 ELSE 0 END) as assigned,
                SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END) as blocked,
                SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) as cancelled,
                SUM(CASE WHEN priority = 'critical' THEN 1 ELSE 0 END) as critical,
                SUM(CASE WHEN priority = 'high' THEN 1 ELSE 0 END) as high_priority
            FROM work_items
            {where_sql}
        """, tuple(params))

        if stats['total_items'] == 0:
            print("No work items found")
            return 0

        print("Work Item Statistics")
        print("=" * 40)
        print(f"Total Items: {stats['total_items']}")
        print()
        print("By Status:")
        print(f"  Pending:     {stats['pending']}")
        print(f"  Assigned:    {stats['assigned']}")
        print(f"  In Progress: {stats['in_progress']}")
        print(f"  Completed:   {stats['completed']}")
        print(f"  Blocked:     {stats['blocked']}")
        print(f"  Cancelled:   {stats['cancelled']}")
        print()
        print("By Priority:")
        print(f"  Critical:    {stats['critical']}")
        print(f"  High:        {stats['high_priority']}")

        # Active items percentage
        active = stats['assigned'] + stats['in_progress']
        if stats['total_items'] > 0:
            completion_rate = (stats['completed'] / stats['total_items']) * 100
            print()
            print(f"Completion Rate: {completion_rate:.1f}%")
            print(f"Active Items: {active}")

        return 0

    def mailbox(self, args) -> int:
        """Show agent mailbox messages."""
        session_id = args.session_id
        status_filter = getattr(args, 'status', None)

        # Verify session exists
        session = self.agent_repo.get_session(session_id)
        if not session:
            logger.error(f"Session {session_id} not found")
            return 1

        # Build query
        where_sql = "WHERE session_id = ?"
        params = [session_id]

        if status_filter:
            where_sql += " AND status = ?"
            params.append(status_filter)

        # Get messages
        messages = db_utils.query_all(f"""
            SELECT
                id,
                message_type,
                work_item_id,
                priority,
                status,
                delivered_at,
                read_at,
                message_content
            FROM agent_mailbox
            {where_sql}
            ORDER BY delivered_at DESC
            LIMIT 50
        """, tuple(params))

        if not messages:
            print(f"No messages in mailbox for session {session_id}")
            return 0

        print(f"Mailbox for Session {session_id} ({session['session_uuid'][:16]}...)")
        print("=" * 80)

        for msg in messages:
            status_icon = {
                'unread': '📬',
                'read': '📭',
                'acknowledged': '✓',
                'completed': '✓✓'
            }.get(msg['status'], '?')

            priority_icon = {
                'urgent': '🔴',
                'high': '🟠',
                'normal': '🟢',
                'low': '⚪'
            }.get(msg['priority'], '')

            print(f"\n{status_icon} {priority_icon} [{msg['message_type']}] {msg['delivered_at']}")

            if msg['work_item_id']:
                print(f"   Work Item: {msg['work_item_id']}")

            # Parse and show message content
            try:
                content = json.loads(msg['message_content'])
                if 'title' in content:
                    print(f"   Title: {content['title']}")
                if 'priority' in content:
                    print(f"   Priority: {content['priority']}")
            except json.JSONDecodeError:
                print(f"   Content: {msg['message_content'][:100]}")

        unread_count = sum(1 for m in messages if m['status'] == 'unread')
        print(f"\n{len(messages)} messages shown ({unread_count} unread)")

        return 0

    def dispatch(self, args) -> int:
        """Auto-dispatch pending work items to available agents."""
        project = getattr(args, 'project', None)
        priority = getattr(args, 'priority', None)

        project_id = None
        if project:
            project_id = self._get_project_id(project)
            if not project_id:
                return 1

        dispatched = self.coordinator.dispatch_pending_work(
            project_id=project_id,
            priority_filter=priority
        )

        print(f"Dispatched {dispatched} work items to available agents")
        return 0

    def agents(self, args) -> int:
        """List available agents with workload info."""
        project = getattr(args, 'project', None)

        project_id = None
        if project:
            project_id = self._get_project_id(project)
            if not project_id:
                return 1

        agents = self.coordinator.get_available_agents(project_id=project_id)

        if not agents:
            print("No active agents available")
            return 0

        headers = ["Session ID", "UUID", "Type", "Project", "Active Work", "Unread Msgs"]
        rows = []
        for agent in agents:
            rows.append([
                str(agent['id']),
                agent['session_uuid'][:16] + '...' if agent['session_uuid'] else '-',
                agent['agent_type'],
                agent['project_slug'] or '-',
                str(agent['active_work_count']),
                str(agent['unread_messages'])
            ])

        print(self._format_table(rows, headers))
        print(f"\nTotal: {len(agents)} active agents")

        return 0

    def metrics(self, args) -> int:
        """Show coordination metrics."""
        project = getattr(args, 'project', None)

        project_id = None
        if project:
            project_id = self._get_project_id(project)
            if not project_id:
                return 1

        metrics = self.coordinator.get_coordination_metrics(project_id=project_id)

        print("Multi-Agent Coordination Metrics")
        print("=" * 50)
        print()

        print("Work Items:")
        work = metrics['work_items']
        print(f"  Total:        {work.get('total_items', 0)}")
        print(f"  Pending:      {work.get('pending', 0)}")
        print(f"  Assigned:     {work.get('assigned', 0)}")
        print(f"  In Progress:  {work.get('in_progress', 0)}")
        print(f"  Completed:    {work.get('completed', 0)}")
        print(f"  Blocked:      {work.get('blocked', 0)}")
        print()

        print("Agents:")
        agents = metrics['agents']
        print(f"  Active:       {agents.get('active_agents', 0)}")
        print(f"  Busy:         {agents.get('busy_agents', 0)}")
        print()

        print("Efficiency:")
        eff = metrics['efficiency']
        utilization = eff.get('utilization_rate', 0.0) * 100
        print(f"  Agent Utilization: {utilization:.1f}%")

        return 0


def register(cli):
    """Register work item commands with CLI"""
    cmd = WorkItemCommands()

    # Main work item parser
    work_parser = cli.register_command(
        'work',
        None,  # No handler for parent
        help_text='Work item and coordination management'
    )
    subparsers = work_parser.add_subparsers(dest='work_subcommand', required=True)

    # Create item
    create_parser = subparsers.add_parser('create', help='Create a new work item')
    create_parser.add_argument('-p', '--project', required=True, help='Project slug or ID')
    create_parser.add_argument('-t', '--title', required=True, help='Work item title')
    create_parser.add_argument('-d', '--description', help='Work item description')
    create_parser.add_argument('--type', default='task',
                               choices=['task', 'bug', 'feature', 'refactor', 'research', 'documentation'],
                               help='Work item type')
    create_parser.add_argument('--priority', default='medium',
                               choices=['low', 'medium', 'high', 'critical'],
                               help='Priority level')
    create_parser.add_argument('--parent', help='Parent work item ID (for subtasks)')
    cli.commands['work.create'] = cmd.create_item

    # List items
    list_parser = subparsers.add_parser('list', help='List work items')
    list_parser.add_argument('-p', '--project', help='Filter by project slug or ID')
    list_parser.add_argument('-s', '--status',
                            choices=['pending', 'assigned', 'in_progress', 'completed', 'blocked', 'cancelled'],
                            help='Filter by status')
    list_parser.add_argument('--priority',
                            choices=['low', 'medium', 'high', 'critical'],
                            help='Filter by priority')
    list_parser.add_argument('--assigned-session', type=int, help='Filter by assigned session ID')
    list_parser.add_argument('-a', '--all', action='store_true', help='Show all items including completed/cancelled')
    cli.commands['work.list'] = cmd.list_items

    # Show item
    show_parser = subparsers.add_parser('show', help='Show work item details')
    show_parser.add_argument('item_id', help='Work item ID')
    cli.commands['work.show'] = cmd.show_item

    # Assign item
    assign_parser = subparsers.add_parser('assign', help='Assign work item to agent session')
    assign_parser.add_argument('item_id', help='Work item ID')
    assign_parser.add_argument('session_id', type=int, help='Agent session ID')
    cli.commands['work.assign'] = cmd.assign_item

    # Update status
    status_parser = subparsers.add_parser('status', help='Update work item status')
    status_parser.add_argument('item_id', help='Work item ID')
    status_parser.add_argument('status',
                              choices=['pending', 'assigned', 'in_progress', 'completed', 'blocked', 'cancelled'],
                              help='New status')
    cli.commands['work.status'] = cmd.update_status

    # Stats
    stats_parser = subparsers.add_parser('stats', help='Show work item statistics')
    stats_parser.add_argument('-p', '--project', help='Filter by project slug or ID')
    cli.commands['work.stats'] = cmd.stats

    # Mailbox
    mailbox_parser = subparsers.add_parser('mailbox', help='Show agent mailbox messages')
    mailbox_parser.add_argument('session_id', type=int, help='Agent session ID')
    mailbox_parser.add_argument('-s', '--status',
                                choices=['unread', 'read', 'acknowledged', 'completed'],
                                help='Filter by message status')
    cli.commands['work.mailbox'] = cmd.mailbox

    # Dispatch (coordinator)
    dispatch_parser = subparsers.add_parser('dispatch', help='Auto-dispatch pending work to agents')
    dispatch_parser.add_argument('-p', '--project', help='Filter by project slug or ID')
    dispatch_parser.add_argument('--priority',
                                 choices=['low', 'medium', 'high', 'critical'],
                                 help='Filter by priority')
    cli.commands['work.dispatch'] = cmd.dispatch

    # Agents (coordinator)
    agents_parser = subparsers.add_parser('agents', help='List available agents with workload')
    agents_parser.add_argument('-p', '--project', help='Filter by project slug or ID')
    cli.commands['work.agents'] = cmd.agents

    # Metrics (coordinator)
    metrics_parser = subparsers.add_parser('metrics', help='Show coordination metrics')
    metrics_parser.add_argument('-p', '--project', help='Filter by project slug or ID')
    cli.commands['work.metrics'] = cmd.metrics
