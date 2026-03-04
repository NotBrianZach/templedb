#!/usr/bin/env python3
"""
Deployment History Tracker

Tracks all deployments to enable:
- Deployment history viewing
- Rollback to previous versions
- Audit trail for compliance
- Deployment analytics
"""

import json
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path

from logger import get_logger

logger = get_logger(__name__)


@dataclass
class DeploymentRecord:
    """Represents a deployment in history"""
    id: Optional[int] = None
    project_id: int = 0
    target_name: str = ""
    deployment_type: str = "deploy"  # 'deploy' or 'rollback'

    # Version info
    commit_hash: Optional[str] = None
    cathedral_checksum: Optional[str] = None

    # Status
    status: str = "in_progress"  # 'in_progress', 'success', 'failed', 'rolled_back'
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_ms: int = 0

    # Execution
    deployed_by: Optional[str] = None
    deployment_method: str = "orchestrator"

    # Results
    groups_deployed: List[str] = field(default_factory=list)
    files_deployed: List[str] = field(default_factory=list)
    error_message: Optional[str] = None

    # Snapshot
    deployment_snapshot: Dict[str, Any] = field(default_factory=dict)


class DeploymentTracker:
    """Tracks deployment history for rollback support"""

    def __init__(self, db_utils):
        """
        Initialize deployment tracker

        Args:
            db_utils: Database utilities module
        """
        self.db_utils = db_utils

    def start_deployment(
        self,
        project_id: int,
        target_name: str,
        deployment_type: str = "deploy",
        commit_hash: Optional[str] = None,
        deployed_by: Optional[str] = None
    ) -> int:
        """
        Record start of a deployment

        Args:
            project_id: Project ID
            target_name: Deployment target (production, staging, etc.)
            deployment_type: 'deploy' or 'rollback'
            commit_hash: VCS commit being deployed
            deployed_by: User or system triggering deployment

        Returns:
            Deployment ID
        """
        import os

        deployed_by = deployed_by or os.getenv('USER', 'unknown')

        deployment_id = self.db_utils.execute("""
            INSERT INTO deployment_history (
                project_id, target_name, deployment_type,
                commit_hash, status, started_at, deployed_by, deployment_method
            )
            VALUES (?, ?, ?, ?, 'in_progress', datetime('now'), ?, 'orchestrator')
        """, (project_id, target_name, deployment_type, commit_hash, deployed_by))

        logger.info(f"Started deployment {deployment_id} for {target_name}")
        return deployment_id

    def complete_deployment(
        self,
        deployment_id: int,
        success: bool,
        duration_ms: int,
        groups_deployed: List[str] = None,
        files_deployed: List[str] = None,
        error_message: Optional[str] = None,
        deployment_snapshot: Optional[Dict] = None
    ):
        """
        Mark deployment as complete

        Args:
            deployment_id: Deployment ID
            success: Whether deployment succeeded
            duration_ms: Deployment duration
            groups_deployed: List of deployment groups executed
            files_deployed: List of files deployed
            error_message: Error message if failed
            deployment_snapshot: Snapshot of deployment state
        """
        status = 'success' if success else 'failed'

        self.db_utils.execute("""
            UPDATE deployment_history
            SET status = ?,
                completed_at = datetime('now'),
                duration_ms = ?,
                groups_deployed = ?,
                files_deployed = ?,
                error_message = ?,
                deployment_snapshot = ?
            WHERE id = ?
        """, (
            status,
            duration_ms,
            json.dumps(groups_deployed or []),
            json.dumps(files_deployed or []),
            error_message,
            json.dumps(deployment_snapshot or {}),
            deployment_id
        ))

        logger.info(f"Deployment {deployment_id} completed with status: {status}")

    def save_deployment_snapshot(
        self,
        deployment_id: int,
        files: List[Dict[str, Any]],
        store_content: bool = False
    ):
        """
        Save snapshot of deployed files for rollback

        Args:
            deployment_id: Deployment ID
            files: List of file dicts with path, hash, size
            store_content: Whether to store actual content (for critical files)
        """
        for file in files:
            self.db_utils.execute("""
                INSERT OR REPLACE INTO deployment_snapshots (
                    deployment_id, file_path, content_hash,
                    file_size_bytes, content_stored
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                deployment_id,
                file[' path'],
                file['hash'],
                file.get('size', 0),
                1 if store_content else 0
            ))

        logger.debug(f"Saved snapshot of {len(files)} files for deployment {deployment_id}")

    def get_deployment_history(
        self,
        project_id: int,
        target_name: Optional[str] = None,
        limit: int = 10,
        status: Optional[str] = None
    ) -> List[DeploymentRecord]:
        """
        Get deployment history

        Args:
            project_id: Project ID
            target_name: Filter by target (optional)
            limit: Max number of records
            status: Filter by status (optional)

        Returns:
            List of deployment records
        """
        query = """
            SELECT id, project_id, target_name, deployment_type,
                   commit_hash, cathedral_checksum,
                   status, started_at, completed_at, duration_ms,
                   deployed_by, deployment_method,
                   groups_deployed, files_deployed, error_message,
                   deployment_snapshot
            FROM deployment_history
            WHERE project_id = ?
        """
        params = [project_id]

        if target_name:
            query += " AND target_name = ?"
            params.append(target_name)

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)

        rows = self.db_utils.query_all(query, tuple(params))

        records = []
        for row in rows:
            record = DeploymentRecord(
                id=row['id'],
                project_id=row['project_id'],
                target_name=row['target_name'],
                deployment_type=row['deployment_type'],
                commit_hash=row['commit_hash'],
                cathedral_checksum=row['cathedral_checksum'],
                status=row['status'],
                started_at=row['started_at'],
                completed_at=row['completed_at'],
                duration_ms=row['duration_ms'] or 0,
                deployed_by=row['deployed_by'],
                deployment_method=row['deployment_method'],
                groups_deployed=json.loads(row['groups_deployed'] or '[]'),
                files_deployed=json.loads(row['files_deployed'] or '[]'),
                error_message=row['error_message'],
                deployment_snapshot=json.loads(row['deployment_snapshot'] or '{}')
            )
            records.append(record)

        return records

    def get_last_successful_deployment(
        self,
        project_id: int,
        target_name: str,
        before_deployment_id: Optional[int] = None
    ) -> Optional[DeploymentRecord]:
        """
        Get last successful deployment

        Args:
            project_id: Project ID
            target_name: Target name
            before_deployment_id: Get deployment before this ID (for rollback)

        Returns:
            Last successful deployment or None
        """
        query = """
            SELECT id, project_id, target_name, deployment_type,
                   commit_hash, cathedral_checksum,
                   status, started_at, completed_at, duration_ms,
                   deployed_by, deployment_method,
                   groups_deployed, files_deployed, error_message,
                   deployment_snapshot
            FROM deployment_history
            WHERE project_id = ?
              AND target_name = ?
              AND status = 'success'
              AND deployment_type = 'deploy'
        """
        params = [project_id, target_name]

        if before_deployment_id:
            query += " AND id < ?"
            params.append(before_deployment_id)

        query += " ORDER BY started_at DESC LIMIT 1"

        row = self.db_utils.query_one(query, tuple(params))

        if not row:
            return None

        return DeploymentRecord(
            id=row['id'],
            project_id=row['project_id'],
            target_name=row['target_name'],
            deployment_type=row['deployment_type'],
            commit_hash=row['commit_hash'],
            cathedral_checksum=row['cathedral_checksum'],
            status=row['status'],
            started_at=row['started_at'],
            completed_at=row['completed_at'],
            duration_ms=row['duration_ms'] or 0,
            deployed_by=row['deployed_by'],
            deployment_method=row['deployment_method'],
            groups_deployed=json.loads(row['groups_deployed'] or '[]'),
            files_deployed=json.loads(row['files_deployed'] or '[]'),
            error_message=row['error_message'],
            deployment_snapshot=json.loads(row['deployment_snapshot'] or '{}')
        )

    def mark_deployment_rolled_back(self, deployment_id: int):
        """Mark a deployment as rolled back"""
        self.db_utils.execute("""
            UPDATE deployment_history
            SET status = 'rolled_back'
            WHERE id = ?
        """, (deployment_id,))

        logger.info(f"Marked deployment {deployment_id} as rolled back")

    def record_rollback(
        self,
        from_deployment_id: int,
        to_deployment_id: Optional[int],
        rollback_deployment_id: int,
        reason: Optional[str] = None
    ):
        """
        Record rollback relationship

        Args:
            from_deployment_id: Deployment being rolled back FROM
            to_deployment_id: Deployment being rolled back TO (None for initial)
            rollback_deployment_id: The rollback deployment itself
            reason: Reason for rollback
        """
        self.db_utils.execute("""
            INSERT INTO deployment_rollbacks (
                from_deployment_id, to_deployment_id,
                rollback_deployment_id, rollback_reason
            )
            VALUES (?, ?, ?, ?)
        """, (from_deployment_id, to_deployment_id, rollback_deployment_id, reason))

        # Mark original deployment as rolled back
        self.mark_deployment_rolled_back(from_deployment_id)

        logger.info(f"Recorded rollback from deployment {from_deployment_id} "
                   f"to {to_deployment_id or 'initial state'}")

    def get_deployment_snapshot_files(self, deployment_id: int) -> List[Dict]:
        """
        Get files from a deployment snapshot

        Args:
            deployment_id: Deployment ID

        Returns:
            List of files with path, hash, size
        """
        rows = self.db_utils.query_all("""
            SELECT file_path, content_hash, file_size_bytes, content_stored
            FROM deployment_snapshots
            WHERE deployment_id = ?
            ORDER BY file_path
        """, (deployment_id,))

        return [
            {
                'path': row['file_path'],
                'hash': row['content_hash'],
                'size': row['file_size_bytes'],
                'content_stored': bool(row['content_stored'])
            }
            for row in rows
        ]

    def get_rollback_history(self, project_id: int, target_name: str) -> List[Dict]:
        """
        Get rollback history for a target

        Args:
            project_id: Project ID
            target_name: Target name

        Returns:
            List of rollback records
        """
        rows = self.db_utils.query_all("""
            SELECT
                dr.id,
                dr.from_deployment_id,
                dr.to_deployment_id,
                dr.rollback_deployment_id,
                dr.rollback_reason,
                dr.created_at,
                dh_from.started_at as from_deployment_time,
                dh_to.started_at as to_deployment_time,
                dh_rollback.started_at as rollback_time,
                dh_rollback.status as rollback_status
            FROM deployment_rollbacks dr
            JOIN deployment_history dh_from ON dr.from_deployment_id = dh_from.id
            LEFT JOIN deployment_history dh_to ON dr.to_deployment_id = dh_to.id
            JOIN deployment_history dh_rollback ON dr.rollback_deployment_id = dh_rollback.id
            WHERE dh_from.project_id = ? AND dh_from.target_name = ?
            ORDER BY dr.created_at DESC
        """, (project_id, target_name))

        return [dict(row) for row in rows]
