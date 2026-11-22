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
        work_dir: Optional[Path] = None,
        commit_hash: Optional[str] = None,
        started_at: Optional[str] = None,
    ) -> int:
        """
        Start tracking a deployment.

        commit_hash is what was deployed. It was never passed by either caller
        in cli/commands/deploy.py, so every one of the 436 rows this table held
        on 2026-11-22 had it NULL — the table recorded that a deploy happened
        and not what it shipped. That is the reason "is production current?"
        needed an HTTP probe and a human to think of running it, rather than
        being a join. The column already existed; only the argument was
        missing.

        started_at is an override, because both callers record the deployment
        AFTER the deploy process has exited: CURRENT_TIMESTAMP is then the
        moment the row was written, not the moment the work began, and
        `completed_at - started_at` disagrees with duration_ms. Row 439 read
        2m44s against a duration_ms of 199s. Pass the real start and the two
        agree.

        Returns:
            deployment_id for tracking progress
        """
        import os
        deployed_by = os.environ.get('USER', 'system')

        deployment_id = db_utils.execute("""
            INSERT INTO deployment_history (
                project_id, target_name, deployment_type, deployed_by,
                status, cathedral_checksum, commit_hash, started_at
            ) VALUES (?, ?, 'standard', ?, 'in_progress', ?, ?,
                      COALESCE(?, CURRENT_TIMESTAMP))
        """, (project_id, target, deployed_by, deployment_hash, commit_hash,
              started_at))

        logger.info(f"📝 Started tracking deployment {deployment_id}")
        return deployment_id

    @staticmethod
    def default_branch_head(project_id: int) -> Optional[str]:
        """
        The commit a deploy of this project would be shipping.

        `vcs_branches.head_commit_id` on the default branch, which is
        maintained — checked against `MAX(id)` over the branch's commits on
        2026-11-22 and they agreed. Preferred over the MAX(id) form anyway,
        because that one silently answers with a feature branch's tip when one
        is newer.

        Returns None rather than raising: a project with no commits is a real
        state and must not be a reason a deploy fails to be recorded.
        """
        row = db_utils.query_one(
            """SELECT c.commit_hash
                 FROM vcs_branches b
                 JOIN vcs_commits c ON c.id = b.head_commit_id
                WHERE b.project_id = ? AND b.is_default = 1""",
            (project_id,),
        )
        return row['commit_hash'] if row else None

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

    def run_version_health_check(
        self,
        deployment_id: int,
        base_url: str,
        expected_commit: str,
        path: str = '/api/version',
        field: str = 'sha',
        timeout: int = 20,
    ) -> HealthCheckResult:
        """
        Ask the deployed thing which commit it is, and compare.

        This is the one check worth running after every deploy, because it is
        the only one that can tell a deploy that SUCCEEDED from a deploy that
        ARRIVED. A wrangler upload reporting success and a live site still
        serving last week's bundle look identical from this side of the wire;
        the difference is a field at an endpoint.

        It was already written, twice, as bash: bza's scripts/verify-live-sha.sh
        does exactly this and is good at it. The trouble is where it lived —
        step 4 of a deploy script, so it was lost precisely when the deploy was
        interrupted, which is when it matters. On 2026-11-21 a deploy shipped
        correctly, was cut off before its own verification, and the result had
        to be confirmed by hand. Worse, the same script is the only thing that
        ever asks the question, so "production is sixteen commits behind" was
        discoverable only by someone choosing to ask.

        As a health check it becomes a row: recorded per deployment, queryable
        after the fact, and runnable on a timer by something that is not the
        deploy.

        `path` and `field` are arguments rather than conventions because the
        endpoint is the project's business — templedb cannot know that a thing
        it deployed exposes its build sha, let alone where. The defaults match
        bza because bza is the project that has one; anything else passes its
        own.

        A mismatch is a `fail`, not an error. The deploy may well have worked
        and the edge may simply not have caught up, so this records what it saw
        and lets the caller decide. Prefix matching, because a build may stamp
        a short sha: either side being a prefix of the other counts, which is
        the same latitude `--if-match` gives a content hash.
        """
        url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"

        if not HAS_REQUESTS:
            result = HealthCheckResult(
                check_type='http',
                check_name='live commit matches graph',
                status='skip',
                endpoint=url,
                error_message="requests module not available (pip install requests)",
            )
            self.add_health_check(deployment_id, result)
            return result

        start_time = time.time()
        try:
            response = requests.get(url, timeout=timeout)
            elapsed_ms = int((time.time() - start_time) * 1000)

            live = None
            try:
                live = (response.json() or {}).get(field)
            except ValueError:
                pass

            if live is None:
                result = HealthCheckResult(
                    check_type='http',
                    check_name='live commit matches graph',
                    status='fail',
                    response_time_ms=elapsed_ms,
                    endpoint=url,
                    status_code=response.status_code,
                    error_message=f"no '{field}' in the response body",
                )
            else:
                live = str(live)
                expected = str(expected_commit)
                agrees = live.startswith(expected) or expected.startswith(live)
                result = HealthCheckResult(
                    check_type='http',
                    check_name='live commit matches graph',
                    status='pass' if agrees else 'fail',
                    response_time_ms=elapsed_ms,
                    endpoint=url,
                    status_code=response.status_code,
                    error_message=None if agrees else f"live {live}, graph {expected}",
                    details=f'{{"live": "{live}", "expected": "{expected}"}}',
                )

        except requests.Timeout:
            result = HealthCheckResult(
                check_type='http',
                check_name='live commit matches graph',
                status='timeout',
                endpoint=url,
                error_message=f"Request timed out after {timeout}s",
            )
        except Exception as e:
            result = HealthCheckResult(
                check_type='http',
                check_name='live commit matches graph',
                status='fail',
                endpoint=url,
                error_message=str(e),
            )

        self.add_health_check(deployment_id, result)
        return result

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
