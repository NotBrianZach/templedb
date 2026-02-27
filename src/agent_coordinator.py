#!/usr/bin/env python3
"""
Agent Coordinator - Multi-Agent Task Orchestration

Inspired by Gas Town's Mayor/Polecat architecture, this coordinator manages
multiple AI agent sessions working on different tasks in parallel.
"""

import sys
import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

import db_utils
from repositories.agent_repository import AgentRepository
from logger import get_logger
from config import DB_PATH

logger = get_logger(__name__)


class AgentCoordinator:
    """
    Coordinates multiple AI agents working on tasks.

    Architecture inspired by Gas Town:
    - Mayor: This coordinator manages high-level orchestration
    - Worker Agents: Individual agent sessions assigned to work items
    - Mailbox: Asynchronous task assignment via agent_mailbox table
    """

    def __init__(self, coordinator_session_id: Optional[int] = None):
        """
        Initialize coordinator.

        Args:
            coordinator_session_id: Optional session ID for the coordinator agent itself
        """
        self.agent_repo = AgentRepository(DB_PATH)
        self.coordinator_session_id = coordinator_session_id

    def get_available_agents(self, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get list of active agent sessions that can accept work.

        Args:
            project_id: Optional filter by project

        Returns:
            List of agent session dicts with workload info
        """
        where_clause = "WHERE s.status = 'active'"
        params = []

        if project_id:
            where_clause += " AND sp.project_id = ?"
            params.append(project_id)

        agents = db_utils.query_all(f"""
            SELECT
                s.id,
                s.session_uuid,
                s.agent_type,
                s.status,
                p.slug as project_slug,
                (SELECT COUNT(*) FROM work_items wi
                 WHERE wi.assigned_session_id = s.id
                 AND wi.status IN ('assigned', 'in_progress')) as active_work_count,
                (SELECT COUNT(*) FROM agent_mailbox am
                 WHERE am.session_id = s.id
                 AND am.status = 'unread') as unread_messages
            FROM agent_sessions s
            LEFT JOIN agent_sessions_projects sp ON s.id = sp.session_id
            LEFT JOIN projects p ON sp.project_id = p.id
            {where_clause}
            ORDER BY active_work_count ASC, s.started_at DESC
        """, tuple(params))

        return agents

    def assign_work_item_to_agent(
        self,
        work_item_id: str,
        session_id: Optional[int] = None,
        auto_select: bool = False
    ) -> bool:
        """
        Assign a work item to an agent session.

        Args:
            work_item_id: Work item ID to assign
            session_id: Target session ID, or None to auto-select
            auto_select: If True and session_id is None, automatically select
                        the least-busy available agent

        Returns:
            True if successfully assigned, False otherwise
        """
        # Get work item
        item = db_utils.query_one("""
            SELECT wi.*, p.id as project_id, p.slug as project_slug
            FROM work_items wi
            JOIN projects p ON wi.project_id = p.id
            WHERE wi.id = ?
        """, (work_item_id,))

        if not item:
            logger.error(f"Work item {work_item_id} not found")
            return False

        # Auto-select agent if needed
        if session_id is None and auto_select:
            available = self.get_available_agents(project_id=item['project_id'])
            if not available:
                logger.error(f"No available agents for project {item['project_slug']}")
                return False

            # Select least-busy agent
            session_id = available[0]['id']
            logger.info(f"Auto-selected agent session {session_id} (workload: {available[0]['active_work_count']} items)")

        if session_id is None:
            logger.error("No session_id provided and auto_select=False")
            return False

        # Verify session exists and is active
        session = self.agent_repo.get_session(session_id)
        if not session or session['status'] != 'active':
            logger.error(f"Session {session_id} not available")
            return False

        # Assign work item
        db_utils.execute("""
            UPDATE work_items
            SET assigned_session_id = ?,
                status = CASE
                    WHEN status = 'pending' THEN 'assigned'
                    ELSE status
                END
            WHERE id = ?
        """, (session_id, work_item_id))

        logger.info(f"Assigned work item {work_item_id} to session {session_id}")
        return True

    def create_convoy(
        self,
        project_id: int,
        convoy_name: str,
        work_item_ids: List[str],
        description: Optional[str] = None
    ) -> int:
        """
        Create a convoy (bundle of related work items).

        Args:
            project_id: Project ID
            convoy_name: Name for the convoy
            work_item_ids: List of work item IDs to include
            description: Optional description

        Returns:
            Convoy ID
        """
        # Create convoy
        convoy_id = db_utils.execute("""
            INSERT INTO work_convoys (
                convoy_name,
                project_id,
                description,
                status,
                coordinator_session_id
            ) VALUES (?, ?, ?, 'pending', ?)
        """, (convoy_name, project_id, description, self.coordinator_session_id))

        # Add work items to convoy
        for idx, item_id in enumerate(work_item_ids):
            db_utils.execute("""
                INSERT INTO convoy_work_items (convoy_id, work_item_id, sequence_order)
                VALUES (?, ?, ?)
            """, (convoy_id, item_id, idx + 1))

        logger.info(f"Created convoy {convoy_id} with {len(work_item_ids)} items")
        return convoy_id

    def start_convoy(self, convoy_id: int, auto_assign: bool = False) -> bool:
        """
        Start a convoy, optionally auto-assigning work items to agents.

        Args:
            convoy_id: Convoy ID to start
            auto_assign: If True, automatically assign items to available agents

        Returns:
            True if successfully started
        """
        # Get convoy
        convoy = db_utils.query_one("""
            SELECT c.*, p.slug as project_slug
            FROM work_convoys c
            JOIN projects p ON c.project_id = p.id
            WHERE c.id = ?
        """, (convoy_id,))

        if not convoy:
            logger.error(f"Convoy {convoy_id} not found")
            return False

        # Get work items in convoy
        items = db_utils.query_all("""
            SELECT wi.id, wi.status, wi.assigned_session_id
            FROM convoy_work_items cwi
            JOIN work_items wi ON cwi.work_item_id = wi.id
            WHERE cwi.convoy_id = ?
            ORDER BY cwi.sequence_order
        """, (convoy_id,))

        # Update convoy status
        db_utils.execute("""
            UPDATE work_convoys
            SET status = 'active',
                started_at = datetime('now')
            WHERE id = ?
        """, (convoy_id,))

        # Auto-assign unassigned items
        if auto_assign:
            for item in items:
                if item['assigned_session_id'] is None and item['status'] == 'pending':
                    self.assign_work_item_to_agent(
                        item['id'],
                        auto_select=True
                    )

        logger.info(f"Started convoy {convoy_id} with {len(items)} items")
        return True

    def get_agent_workload(self, session_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Get workload summary for agents.

        Args:
            session_id: Optional filter by specific session

        Returns:
            List of workload summaries
        """
        where_clause = "WHERE s.status = 'active'"
        params = []

        if session_id:
            where_clause += " AND s.id = ?"
            params.append(session_id)

        return db_utils.query_all(f"""
            SELECT
                s.id as session_id,
                s.session_uuid,
                s.agent_type,
                p.slug as project_slug,
                COUNT(wi.id) as assigned_items,
                SUM(CASE WHEN wi.status = 'in_progress' THEN 1 ELSE 0 END) as active_items,
                SUM(CASE WHEN wi.status = 'assigned' THEN 1 ELSE 0 END) as queued_items,
                SUM(CASE WHEN wi.priority IN ('high', 'critical') THEN 1 ELSE 0 END) as high_priority_items,
                (SELECT COUNT(*) FROM agent_mailbox WHERE session_id = s.id AND status = 'unread') as unread_messages
            FROM agent_sessions s
            LEFT JOIN agent_sessions_projects sp ON s.id = sp.session_id
            LEFT JOIN projects p ON sp.project_id = p.id
            LEFT JOIN work_items wi ON s.id = wi.assigned_session_id
            {where_clause}
            GROUP BY s.id
            ORDER BY assigned_items DESC
        """, tuple(params))

    def get_convoy_status(self, convoy_id: int) -> Optional[Dict[str, Any]]:
        """
        Get detailed status of a convoy.

        Args:
            convoy_id: Convoy ID

        Returns:
            Convoy status dict or None if not found
        """
        return db_utils.query_one("""
            SELECT
                c.id,
                c.convoy_name,
                c.status,
                c.description,
                p.slug as project_slug,
                c.created_at,
                c.started_at,
                c.completed_at,
                COUNT(cwi.work_item_id) as total_items,
                SUM(CASE WHEN wi.status = 'completed' THEN 1 ELSE 0 END) as completed_items,
                SUM(CASE WHEN wi.status IN ('in_progress', 'assigned') THEN 1 ELSE 0 END) as active_items,
                SUM(CASE WHEN wi.status = 'blocked' THEN 1 ELSE 0 END) as blocked_items
            FROM work_convoys c
            JOIN projects p ON c.project_id = p.id
            LEFT JOIN convoy_work_items cwi ON c.id = cwi.convoy_id
            LEFT JOIN work_items wi ON cwi.work_item_id = wi.id
            WHERE c.id = ?
            GROUP BY c.id
        """, (convoy_id,))

    def get_mailbox_summary(self, session_id: int) -> Dict[str, Any]:
        """
        Get mailbox summary for an agent session.

        Args:
            session_id: Agent session ID

        Returns:
            Mailbox summary dict
        """
        counts = db_utils.query_one("""
            SELECT
                COUNT(*) as total_messages,
                SUM(CASE WHEN status = 'unread' THEN 1 ELSE 0 END) as unread,
                SUM(CASE WHEN status = 'read' THEN 1 ELSE 0 END) as read,
                SUM(CASE WHEN priority = 'urgent' THEN 1 ELSE 0 END) as urgent,
                SUM(CASE WHEN message_type = 'work_assignment' THEN 1 ELSE 0 END) as work_assignments
            FROM agent_mailbox
            WHERE session_id = ?
        """, (session_id,))

        return counts or {
            'total_messages': 0,
            'unread': 0,
            'read': 0,
            'urgent': 0,
            'work_assignments': 0
        }

    def dispatch_pending_work(
        self,
        project_id: Optional[int] = None,
        priority_filter: Optional[str] = None
    ) -> int:
        """
        Automatically dispatch pending work items to available agents.

        Args:
            project_id: Optional filter by project
            priority_filter: Optional filter by priority ('critical', 'high', etc)

        Returns:
            Number of items dispatched
        """
        # Get pending work items
        where_clauses = ["wi.status = 'pending'"]
        params = []

        if project_id:
            where_clauses.append("wi.project_id = ?")
            params.append(project_id)

        if priority_filter:
            where_clauses.append("wi.priority = ?")
            params.append(priority_filter)

        where_sql = " AND ".join(where_clauses)

        items = db_utils.query_all(f"""
            SELECT wi.id, wi.priority, wi.project_id
            FROM work_items wi
            WHERE {where_sql}
            ORDER BY
                CASE wi.priority
                    WHEN 'critical' THEN 1
                    WHEN 'high' THEN 2
                    WHEN 'medium' THEN 3
                    WHEN 'low' THEN 4
                END,
                wi.created_at ASC
        """, tuple(params))

        dispatched = 0
        for item in items:
            if self.assign_work_item_to_agent(item['id'], auto_select=True):
                dispatched += 1

        logger.info(f"Dispatched {dispatched}/{len(items)} pending work items")
        return dispatched

    def get_coordination_metrics(self, project_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get overall coordination metrics.

        Args:
            project_id: Optional filter by project

        Returns:
            Metrics dict with overall system stats
        """
        where_clause = ""
        params = []

        if project_id:
            where_clause = "WHERE wi.project_id = ?"
            params.append(project_id)

        work_stats = db_utils.query_one(f"""
            SELECT
                COUNT(*) as total_items,
                SUM(CASE WHEN wi.status = 'pending' THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN wi.status = 'assigned' THEN 1 ELSE 0 END) as assigned,
                SUM(CASE WHEN wi.status = 'in_progress' THEN 1 ELSE 0 END) as in_progress,
                SUM(CASE WHEN wi.status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN wi.status = 'blocked' THEN 1 ELSE 0 END) as blocked
            FROM work_items wi
            {where_clause}
        """, tuple(params))

        agent_stats = db_utils.query_one("""
            SELECT
                COUNT(*) as active_agents,
                SUM(CASE WHEN (
                    SELECT COUNT(*) FROM work_items
                    WHERE assigned_session_id = s.id
                    AND status IN ('assigned', 'in_progress')
                ) > 0 THEN 1 ELSE 0 END) as busy_agents
            FROM agent_sessions s
            WHERE s.status = 'active'
        """)

        return {
            'work_items': work_stats or {},
            'agents': agent_stats or {'active_agents': 0, 'busy_agents': 0},
            'efficiency': {
                'utilization_rate': (
                    agent_stats['busy_agents'] / agent_stats['active_agents']
                    if agent_stats and agent_stats['active_agents'] > 0
                    else 0.0
                )
            }
        }
