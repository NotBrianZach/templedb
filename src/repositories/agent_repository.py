"""Repository for managing agent sessions and interactions."""

import sqlite3
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path


class AgentRepository:
    """Handles database operations for agent sessions."""

    def __init__(self, db_path: str):
        """Initialize repository with database path."""
        self.db_path = db_path
        self._ensure_tables()

    def _ensure_tables(self):
        """Ensure agent session tables exist."""
        schema_file = Path(__file__).parent.parent.parent / "database_agent_schema.sql"
        if schema_file.exists():
            with sqlite3.connect(self.db_path) as conn:
                with open(schema_file, 'r') as f:
                    conn.executescript(f.read())
                conn.commit()

    def create_session(
        self,
        project_id: Optional[int],
        agent_type: str,
        agent_version: Optional[str] = None,
        initial_context: Optional[str] = None,
        session_goal: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[int, str]:
        """
        Create a new agent session.

        Returns:
            Tuple of (session_id, session_uuid)
        """
        session_uuid = str(uuid.uuid4())
        metadata_json = json.dumps(metadata) if metadata else None

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO agent_sessions
                (session_uuid, project_id, agent_type, agent_version,
                 initial_context, session_goal, metadata, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
            """, (session_uuid, project_id, agent_type, agent_version,
                  initial_context, session_goal, metadata_json))
            conn.commit()
            return cursor.lastrowid, session_uuid

    def get_session(self, session_id: Optional[int] = None,
                   session_uuid: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get session by ID or UUID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if session_id:
                cursor.execute("SELECT * FROM agent_sessions WHERE id = ?", (session_id,))
            elif session_uuid:
                cursor.execute("SELECT * FROM agent_sessions WHERE session_uuid = ?", (session_uuid,))
            else:
                return None

            row = cursor.fetchone()
            if row:
                result = dict(row)
                if result.get('metadata'):
                    result['metadata'] = json.loads(result['metadata'])
                return result
            return None

    def get_active_session(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Get active session for a project."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM agent_sessions
                WHERE project_id = ? AND status = 'active'
                ORDER BY started_at DESC LIMIT 1
            """, (project_id,))

            row = cursor.fetchone()
            if row:
                result = dict(row)
                if result.get('metadata'):
                    result['metadata'] = json.loads(result['metadata'])
                return result
            return None

    def list_sessions(
        self,
        project_id: Optional[int] = None,
        agent_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """List agent sessions with optional filters."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = "SELECT * FROM agent_sessions WHERE 1=1"
            params = []

            if project_id:
                query += " AND project_id = ?"
                params.append(project_id)
            if agent_type:
                query += " AND agent_type = ?"
                params.append(agent_type)
            if status:
                query += " AND status = ?"
                params.append(status)

            query += " ORDER BY started_at DESC LIMIT ?"
            params.append(limit)

            cursor.execute(query, params)
            results = []
            for row in cursor.fetchall():
                result = dict(row)
                if result.get('metadata'):
                    result['metadata'] = json.loads(result['metadata'])
                results.append(result)
            return results

    def update_session_status(
        self,
        session_id: int,
        status: str,
        end_session: bool = False
    ):
        """Update session status and optionally set end time."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            if end_session:
                cursor.execute("""
                    UPDATE agent_sessions
                    SET status = ?, ended_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                """, (status, session_id))
            else:
                cursor.execute("""
                    UPDATE agent_sessions
                    SET status = ?
                    WHERE id = ?
                """, (status, session_id))
            conn.commit()

    def add_interaction(
        self,
        session_id: int,
        interaction_type: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Add an interaction to a session."""
        metadata_json = json.dumps(metadata) if metadata else None

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO agent_interactions
                (session_id, interaction_type, content, metadata)
                VALUES (?, ?, ?, ?)
            """, (session_id, interaction_type, content, metadata_json))
            conn.commit()
            return cursor.lastrowid

    def get_interactions(
        self,
        session_id: int,
        interaction_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get interactions for a session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            if interaction_type:
                cursor.execute("""
                    SELECT * FROM agent_interactions
                    WHERE session_id = ? AND interaction_type = ?
                    ORDER BY timestamp DESC LIMIT ?
                """, (session_id, interaction_type, limit))
            else:
                cursor.execute("""
                    SELECT * FROM agent_interactions
                    WHERE session_id = ?
                    ORDER BY timestamp DESC LIMIT ?
                """, (session_id, limit))

            results = []
            for row in cursor.fetchall():
                result = dict(row)
                if result.get('metadata'):
                    result['metadata'] = json.loads(result['metadata'])
                results.append(result)
            return results

    def link_commit_to_session(
        self,
        session_id: int,
        commit_id: int,
        is_primary: bool = True
    ):
        """Link a commit to an agent session."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO agent_session_commits
                (session_id, commit_id, is_primary)
                VALUES (?, ?, ?)
            """, (session_id, commit_id, is_primary))
            conn.commit()

    def get_session_commits(self, session_id: int) -> List[Dict[str, Any]]:
        """Get all commits linked to a session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT c.*, asc.is_primary, asc.created_at as linked_at
                FROM vcs_commits c
                JOIN agent_session_commits asc ON c.id = asc.commit_id
                WHERE asc.session_id = ?
                ORDER BY c.commit_timestamp
            """, (session_id,))

            return [dict(row) for row in cursor.fetchall()]

    def save_context_snapshot(
        self,
        session_id: int,
        snapshot_type: str,
        context_data: Dict[str, Any],
        file_count: Optional[int] = None,
        token_estimate: Optional[int] = None
    ) -> int:
        """Save a context snapshot for a session."""
        context_json = json.dumps(context_data)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO agent_context_snapshots
                (session_id, snapshot_type, context_data, file_count, token_estimate)
                VALUES (?, ?, ?, ?, ?)
            """, (session_id, snapshot_type, context_json, file_count, token_estimate))
            conn.commit()
            return cursor.lastrowid

    def get_context_snapshots(self, session_id: int) -> List[Dict[str, Any]]:
        """Get context snapshots for a session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM agent_context_snapshots
                WHERE session_id = ?
                ORDER BY created_at
            """, (session_id,))

            results = []
            for row in cursor.fetchall():
                result = dict(row)
                if result.get('context_data'):
                    result['context_data'] = json.loads(result['context_data'])
                results.append(result)
            return results

    def record_metric(
        self,
        session_id: int,
        metric_type: str,
        metric_value: float,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Record a performance metric for a session."""
        metadata_json = json.dumps(metadata) if metadata else None

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO agent_session_metrics
                (session_id, metric_type, metric_value, metadata)
                VALUES (?, ?, ?, ?)
            """, (session_id, metric_type, metric_value, metadata_json))
            conn.commit()
            return cursor.lastrowid

    def get_session_metrics(self, session_id: int) -> List[Dict[str, Any]]:
        """Get all metrics for a session."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM agent_session_metrics
                WHERE session_id = ?
                ORDER BY recorded_at
            """, (session_id,))

            results = []
            for row in cursor.fetchall():
                result = dict(row)
                if result.get('metadata'):
                    result['metadata'] = json.loads(result['metadata'])
                results.append(result)
            return results

    def get_session_summary(self, session_id: int) -> Dict[str, Any]:
        """Get a comprehensive summary of a session."""
        session = self.get_session(session_id=session_id)
        if not session:
            return {}

        commits = self.get_session_commits(session_id)
        interactions = self.get_interactions(session_id)
        metrics = self.get_session_metrics(session_id)

        return {
            'session': session,
            'commits': commits,
            'interaction_count': len(interactions),
            'metrics': metrics,
            'duration_seconds': self._calculate_duration(session)
        }

    def _calculate_duration(self, session: Dict[str, Any]) -> Optional[float]:
        """Calculate session duration in seconds."""
        if not session.get('ended_at'):
            return None

        start = datetime.fromisoformat(session['started_at'])
        end = datetime.fromisoformat(session['ended_at'])
        return (end - start).total_seconds()
