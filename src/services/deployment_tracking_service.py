#!/usr/bin/env python3
"""
Deployment Tracking Service - Records deployment history and health checks
"""
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

# Optional import - only needed for health checks
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

from services.base import BaseService
from logger import get_logger
import db_utils

logger = get_logger(__name__)


@dataclass
class DeploymentRecord:
    """Record of a deployment"""
    id: int
    project_id: int
    target: str
    deployed_at: str
    status: str
    exit_code: Optional[int] = None
    deployment_hash: Optional[str] = None
    duration_seconds: Optional[float] = None
    work_dir: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class HealthCheckResult:
    """Result of a health check"""
    check_type: str
    check_name: str
    status: str  # 'pass', 'fail', 'skip', 'timeout'
    response_time_ms: Optional[int] = None
    endpoint: Optional[str] = None
    status_code: Optional[int] = None
    error_message: Optional[str] = None
    details: Optional[str] = None


class DeploymentTrackingService(BaseService):
    """
    Service for tracking deployments and running health checks.

    Provides:
    - Deployment history recording
    - Health check execution
    - Deployment statistics
    - Rollback support
    """

    def start_deployment(
        self,
        project_id: int,
        target: str,
        deployment_hash: Optional[str] = None,
        work_dir: Optional[Path] = None
    ) -> int:
        """
        Start tracking a deployment.

        Returns:
            deployment_id for tracking progress
        """
        import os
        deployed_by = os.environ.get('USER', 'system')

        deployment_id = db_utils.execute("""
            INSERT INTO deployment_history (
                project_id, target_name, deployment_type, deployed_by,
                status, cathedral_checksum, started_at
            ) VALUES (?, ?, 'standard', ?, 'in_progress', ?, CURRENT_TIMESTAMP)
        """, (project_id, target, deployed_by, deployment_hash))

        logger.info(f"📝 Started tracking deployment {deployment_id}")
        return deployment_id

    def complete_deployment(
        self,
        deployment_id: int,
        success: bool,
        exit_code: int = 0,
        duration_seconds: Optional[float] = None,
        notes: Optional[str] = None
    ):
        """Mark deployment as complete"""
        status = 'success' if success else 'failed'

        duration_ms = int(duration_seconds * 1000) if duration_seconds else None
        db_utils.execute("""
            UPDATE deployment_history
            SET status = ?,
                completed_at = CURRENT_TIMESTAMP,
                duration_ms = ?,
                error_message = ?
            WHERE id = ?
        """, (status, duration_ms, notes if not success else None, deployment_id))

        logger.info(f"✅ Deployment {deployment_id} completed with status: {status}")

    def add_health_check(
        self,
        deployment_id: int,
        check_result: HealthCheckResult
    ):
        """Record a health check result"""
        db_utils.execute("""
            INSERT INTO deployment_health_checks (
                deployment_id, check_type, check_name, checked_at,
                status, response_time_ms, endpoint, status_code,
                error_message, details
            ) VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?, ?, ?, ?, ?)
        """, (
            deployment_id,
            check_result.check_type,
            check_result.check_name,
            check_result.status,
            check_result.response_time_ms,
            check_result.endpoint,
            check_result.status_code,
            check_result.error_message,
            check_result.details
        ))

    def run_http_health_check(
        self,
        deployment_id: int,
        check_name: str,
        url: str,
        timeout: int = 10,
        expected_status: int = 200
    ) -> HealthCheckResult:
        """
        Run an HTTP health check.

        Args:
            deployment_id: Deployment ID to record check for
            check_name: Name of the check (e.g., "API Health")
            url: URL to check
            timeout: Request timeout in seconds
            expected_status: Expected HTTP status code

        Returns:
            HealthCheckResult
        """
        if not HAS_REQUESTS:
            result = HealthCheckResult(
                check_type='http',
                check_name=check_name,
                status='skip',
                endpoint=url,
                error_message="requests module not available (pip install requests)"
            )
            self.add_health_check(deployment_id, result)
            return result

        start_time = time.time()

        try:
            response = requests.get(url, timeout=timeout)
            elapsed_ms = int((time.time() - start_time) * 1000)

            status = 'pass' if response.status_code == expected_status else 'fail'

            result = HealthCheckResult(
                check_type='http',
                check_name=check_name,
                status=status,
                response_time_ms=elapsed_ms,
                endpoint=url,
                status_code=response.status_code,
                error_message=None if status == 'pass' else f"Expected {expected_status}, got {response.status_code}"
            )

        except requests.Timeout:
            result = HealthCheckResult(
                check_type='http',
                check_name=check_name,
                status='timeout',
                endpoint=url,
                error_message=f"Request timed out after {timeout}s"
            )
        except Exception as e:
            result = HealthCheckResult(
                check_type='http',
                check_name=check_name,
                status='fail',
                endpoint=url,
                error_message=str(e)
            )

        # Record the check
        self.add_health_check(deployment_id, result)
        return result

    def run_database_health_check(
        self,
        deployment_id: int,
        check_name: str,
        database_url: str
    ) -> HealthCheckResult:
        """
        Run a database connectivity check.

        Args:
            deployment_id: Deployment ID
            check_name: Name of the check
            database_url: Database connection string

        Returns:
            HealthCheckResult
        """
        start_time = time.time()

        try:
            import psycopg2
            conn = psycopg2.connect(database_url, connect_timeout=10)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
            cursor.close()
            conn.close()

            elapsed_ms = int((time.time() - start_time) * 1000)

            result = HealthCheckResult(
                check_type='database',
                check_name=check_name,
                status='pass',
                response_time_ms=elapsed_ms,
                endpoint='***' + database_url[-20:] if len(database_url) > 20 else '***'  # Masked
            )

        except Exception as e:
            result = HealthCheckResult(
                check_type='database',
                check_name=check_name,
                status='fail',
                error_message=str(e)
            )

        self.add_health_check(deployment_id, result)
        return result

    def get_deployment_history(
        self,
        project_slug: str,
        target: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get deployment history for a project"""
        if target:
            rows = db_utils.query_all("""
                SELECT dh.id, dh.project_id, dh.target_name as target,
                       dh.started_at as deployed_at, dh.status,
                       CAST(dh.duration_ms as REAL) / 1000.0 as duration_seconds,
                       dh.cathedral_checksum as deployment_hash,
                       dh.error_message as notes,
                       dh.deployed_by
                FROM deployment_history dh
                JOIN projects p ON dh.project_id = p.id
                WHERE p.slug = ? AND dh.target_name = ?
                ORDER BY dh.started_at DESC
                LIMIT ?
            """, (project_slug, target, limit))
        else:
            rows = db_utils.query_all("""
                SELECT dh.id, dh.project_id, dh.target_name as target,
                       dh.started_at as deployed_at, dh.status,
                       CAST(dh.duration_ms as REAL) / 1000.0 as duration_seconds,
                       dh.cathedral_checksum as deployment_hash,
                       dh.error_message as notes,
                       dh.deployed_by
                FROM deployment_history dh
                JOIN projects p ON dh.project_id = p.id
                WHERE p.slug = ?
                ORDER BY dh.started_at DESC
                LIMIT ?
            """, (project_slug, limit))

        return rows

    def get_health_checks(self, deployment_id: int) -> List[Dict[str, Any]]:
        """Get health check results for a deployment"""
        return db_utils.query_all("""
            SELECT * FROM deployment_health_checks
            WHERE deployment_id = ?
            ORDER BY checked_at ASC
        """, (deployment_id,))

    def get_deployment_stats(self, project_slug: str) -> List[Dict[str, Any]]:
        """Get deployment statistics for a project"""
        return db_utils.query_all("""
            SELECT
                p.slug as project_slug,
                dh.target_name as target,
                COUNT(*) as total_deployments,
                SUM(CASE WHEN dh.status = 'success' THEN 1 ELSE 0 END) as successful_deployments,
                SUM(CASE WHEN dh.status = 'failed' THEN 1 ELSE 0 END) as failed_deployments,
                AVG(CAST(dh.duration_ms as REAL) / 1000.0) as avg_duration_seconds,
                MAX(dh.started_at) as last_deployed_at
            FROM deployment_history dh
            JOIN projects p ON dh.project_id = p.id
            WHERE p.slug = ?
            GROUP BY p.id, dh.target_name
        """, (project_slug,))
