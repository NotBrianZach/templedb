#!/usr/bin/env python3
"""
Deployment pipeline service: auto-deploy on commit, notifications, rollback.

Provides:
- Trigger management: branch→target mapping for auto-deploy
- Notification dispatch: webhook/command hooks on deploy events
- Rollback execution: restore previous deployment state
- Multi-target deployment: deploy to all matching targets
"""
import json
import fnmatch
import subprocess
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TriggerMatch:
    trigger_id: int
    target_name: str
    auto_rollback: bool
    require_health_check: bool


class DeploymentPipelineService:
    """Orchestrates automated deployment pipelines."""

    def __init__(self):
        from db_utils import get_connection, query_one, query_all, execute
        self.get_connection = get_connection
        self.query_one = query_one
        self.query_all = query_all
        self.execute = execute

    # ------------------------------------------------------------------
    # Trigger management
    # ------------------------------------------------------------------

    def add_trigger(self, project_id: int, branch_pattern: str, target_name: str,
                    auto_rollback: bool = False, require_health_check: bool = True) -> int:
        """Register a branch→target auto-deploy trigger."""
        conn = self.get_connection()
        cursor = conn.execute("""
            INSERT OR REPLACE INTO deployment_triggers
                (project_id, branch_pattern, target_name, auto_rollback, require_health_check)
            VALUES (?, ?, ?, ?, ?)
        """, (project_id, branch_pattern, target_name,
              1 if auto_rollback else 0, 1 if require_health_check else 0))
        conn.commit()
        return cursor.lastrowid

    def remove_trigger(self, trigger_id: int):
        self.execute("DELETE FROM deployment_triggers WHERE id = ?", (trigger_id,))

    def list_triggers(self, project_id: Optional[int] = None) -> List[Dict]:
        if project_id:
            return self.query_all("""
                SELECT dt.*, p.slug as project_slug
                FROM deployment_triggers dt
                JOIN projects p ON dt.project_id = p.id
                WHERE dt.project_id = ?
                ORDER BY dt.branch_pattern
            """, (project_id,))
        return self.query_all("""
            SELECT dt.*, p.slug as project_slug
            FROM deployment_triggers dt
            JOIN projects p ON dt.project_id = p.id
            ORDER BY p.slug, dt.branch_pattern
        """)

    def enable_trigger(self, trigger_id: int, enabled: bool = True):
        self.execute("UPDATE deployment_triggers SET enabled = ?, updated_at = datetime('now') WHERE id = ?",
                     (1 if enabled else 0, trigger_id))

    def match_triggers(self, project_id: int, branch_name: str) -> List[TriggerMatch]:
        """Find all triggers that match a project+branch."""
        triggers = self.query_all("""
            SELECT id, target_name, auto_rollback, require_health_check
            FROM deployment_triggers
            WHERE project_id = ? AND enabled = 1
        """, (project_id,))

        matches = []
        for t in triggers:
            if fnmatch.fnmatch(branch_name, t['branch_pattern']):
                matches.append(TriggerMatch(
                    trigger_id=t['id'],
                    target_name=t['target_name'],
                    auto_rollback=bool(t['auto_rollback']),
                    require_health_check=bool(t['require_health_check']),
                ))
        return matches

    # ------------------------------------------------------------------
    # Auto-deploy on commit
    # ------------------------------------------------------------------

    def on_commit(self, project_slug: str, project_id: int, branch_name: str,
                  commit_hash: str) -> List[Dict]:
        """Called after a VCS commit. Checks triggers and auto-deploys.
        Returns list of deployment results."""
        matches = self.match_triggers(project_id, branch_name)
        if not matches:
            return []

        logger.info(f"Auto-deploy triggered: {project_slug}@{branch_name} "
                    f"→ {len(matches)} target(s)")

        results = []
        for match in matches:
            result = self._auto_deploy(
                project_slug=project_slug,
                project_id=project_id,
                target=match.target_name,
                commit_hash=commit_hash,
                branch_name=branch_name,
                trigger=match,
            )
            results.append(result)

        return results

    def _auto_deploy(self, project_slug: str, project_id: int, target: str,
                     commit_hash: str, branch_name: str,
                     trigger: TriggerMatch) -> Dict:
        """Execute a single auto-deploy."""
        from services.context import ServiceContext

        ctx = ServiceContext()
        deploy_service = ctx.get_deployment_service()

        logger.info(f"  Deploying {project_slug} → {target}")

        try:
            result = deploy_service.deploy(
                project_slug=project_slug,
                target=target,
                dry_run=False,
            )

            outcome = {
                'project_slug': project_slug,
                'target': target,
                'success': result.success,
                'message': result.message,
                'commit_hash': commit_hash,
                'triggered_by': 'auto-commit',
            }

            # Record trigger metadata
            conn = self.get_connection()
            conn.execute("""
                UPDATE deployment_history
                SET triggered_by = 'auto-commit', branch_name = ?, commit_hash = ?
                WHERE project_id = ? AND target_name = ?
                ORDER BY started_at DESC LIMIT 1
            """, (branch_name, commit_hash, project_id, target))
            conn.commit()

            # Notifications
            event = 'deploy.success' if result.success else 'deploy.failure'
            self.send_notifications(project_id, event, outcome)

            # Auto-rollback on failure
            if not result.success and trigger.auto_rollback:
                logger.warning(f"  Deploy failed, auto-rolling back {project_slug}@{target}")
                rollback_result = self.rollback(project_slug, target, reason="auto-rollback after failed deploy")
                outcome['rollback'] = rollback_result
                self.send_notifications(project_id, 'deploy.rollback', outcome)

            return outcome

        except Exception as e:
            logger.error(f"  Auto-deploy failed: {e}")
            outcome = {
                'project_slug': project_slug,
                'target': target,
                'success': False,
                'message': str(e),
                'triggered_by': 'auto-commit',
            }
            self.send_notifications(project_id, 'deploy.failure', outcome)
            return outcome

    # ------------------------------------------------------------------
    # Multi-target deploy
    # ------------------------------------------------------------------

    def deploy_multi(self, project_slug: str, targets: Optional[List[str]] = None,
                     dry_run: bool = False) -> List[Dict]:
        """Deploy to multiple targets. If targets is None, deploy to all project targets."""
        from services.context import ServiceContext

        project = self.query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if not project:
            return [{'success': False, 'message': f'Project not found: {project_slug}'}]

        if targets is None:
            rows = self.query_all("""
                SELECT DISTINCT target_name FROM deployment_targets
                WHERE project_id = ?
            """, (project['id'],))
            targets = [r['target_name'] for r in rows]

        if not targets:
            return [{'success': False, 'message': 'No deployment targets configured'}]

        ctx = ServiceContext()
        deploy_service = ctx.get_deployment_service()
        results = []

        for target in targets:
            logger.info(f"Deploying {project_slug} → {target}" +
                       (" (dry-run)" if dry_run else ""))
            try:
                result = deploy_service.deploy(
                    project_slug=project_slug,
                    target=target,
                    dry_run=dry_run,
                )
                outcome = {
                    'project_slug': project_slug,
                    'target': target,
                    'success': result.success,
                    'message': result.message,
                }
                results.append(outcome)

                if not dry_run:
                    event = 'deploy.success' if result.success else 'deploy.failure'
                    self.send_notifications(project['id'], event, outcome)

            except Exception as e:
                results.append({
                    'project_slug': project_slug,
                    'target': target,
                    'success': False,
                    'message': str(e),
                })

        return results

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def rollback(self, project_slug: str, target: str,
                 to_deployment_id: Optional[int] = None,
                 reason: Optional[str] = None) -> Dict:
        """Roll back to a previous successful deployment.

        Restores environment variables from the snapshot and re-deploys
        using the previous deployment's cathedral export.
        """
        project = self.query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if not project:
            return {'success': False, 'message': f'Project not found: {project_slug}'}

        # Find the deployment to roll back to
        if to_deployment_id:
            prev = self.query_one("""
                SELECT * FROM deployment_history
                WHERE id = ? AND project_id = ? AND status = 'success'
            """, (to_deployment_id, project['id']))
        else:
            # Find the most recent successful deployment before the latest
            prev = self.query_one("""
                SELECT * FROM deployment_history
                WHERE project_id = ? AND target_name = ? AND status = 'success'
                ORDER BY started_at DESC LIMIT 1 OFFSET 1
            """, (project['id'], target))

        if not prev:
            return {'success': False, 'message': 'No previous successful deployment found to roll back to'}

        logger.info(f"Rolling back {project_slug}@{target} to deployment #{prev['id']}")

        # Restore environment variables from snapshot if available
        if prev.get('deployment_snapshot'):
            try:
                snapshot = json.loads(prev['deployment_snapshot'])
                env_vars = snapshot.get('environment_variables', {})
                if env_vars:
                    logger.info(f"  Restoring {len(env_vars)} environment variables from snapshot")
                    for key, value in env_vars.items():
                        self.execute("""
                            INSERT OR REPLACE INTO environment_variables
                                (scope_type, scope_id, var_name, var_value, deployment_target)
                            VALUES ('project', ?, ?, ?, ?)
                        """, (project['id'], key, value, target))
            except (json.JSONDecodeError, TypeError):
                logger.warning("  Could not restore environment snapshot")

        # Re-deploy
        from services.context import ServiceContext
        ctx = ServiceContext()
        deploy_service = ctx.get_deployment_service()

        try:
            result = deploy_service.deploy(
                project_slug=project_slug,
                target=target,
                dry_run=False,
            )

            # Mark in history
            conn = self.get_connection()
            conn.execute("""
                UPDATE deployment_history
                SET triggered_by = 'rollback', commit_hash = ?
                WHERE project_id = ? AND target_name = ?
                ORDER BY started_at DESC LIMIT 1
            """, (prev.get('commit_hash'), project['id'], target))
            conn.commit()

            return {
                'success': result.success,
                'message': f"Rolled back to deployment #{prev['id']}" if result.success
                           else f"Rollback deploy failed: {result.message}",
                'rolled_back_to': prev['id'],
                'reason': reason,
            }

        except Exception as e:
            return {'success': False, 'message': f'Rollback failed: {e}'}

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------

    def add_notification(self, project_id: Optional[int], event: str,
                         notification_type: str, config: Dict) -> int:
        """Register a notification hook."""
        conn = self.get_connection()
        cursor = conn.execute("""
            INSERT INTO deployment_notifications (project_id, event, notification_type, config)
            VALUES (?, ?, ?, ?)
        """, (project_id, event, notification_type, json.dumps(config)))
        conn.commit()
        return cursor.lastrowid

    def remove_notification(self, notification_id: int):
        self.execute("DELETE FROM deployment_notifications WHERE id = ?", (notification_id,))

    def list_notifications(self, project_id: Optional[int] = None) -> List[Dict]:
        if project_id:
            return self.query_all("""
                SELECT * FROM deployment_notifications
                WHERE project_id = ? OR project_id IS NULL
                ORDER BY event
            """, (project_id,))
        return self.query_all("SELECT * FROM deployment_notifications ORDER BY event")

    def send_notifications(self, project_id: int, event: str, context: Dict):
        """Dispatch notifications for a deploy event."""
        # Match event patterns: 'deploy.success' matches 'deploy.success' and 'deploy.*'
        notifications = self.query_all("""
            SELECT * FROM deployment_notifications
            WHERE (project_id = ? OR project_id IS NULL) AND enabled = 1
        """, (project_id,))

        for notif in notifications:
            pattern = notif['event']
            if not fnmatch.fnmatch(event, pattern) and pattern != event:
                continue

            try:
                config = json.loads(notif['config'])
                if notif['notification_type'] == 'webhook':
                    self._send_webhook(config, event, context)
                elif notif['notification_type'] == 'command':
                    self._run_notification_command(config, event, context)
            except Exception as e:
                logger.error(f"Notification failed ({notif['notification_type']}): {e}")

    def _send_webhook(self, config: Dict, event: str, context: Dict):
        """POST deployment event to a webhook URL."""
        import urllib.request
        url = config.get('url')
        if not url:
            return

        payload = json.dumps({
            'event': event,
            'project': context.get('project_slug'),
            'target': context.get('target'),
            'success': context.get('success'),
            'message': context.get('message'),
            'commit_hash': context.get('commit_hash'),
            'triggered_by': context.get('triggered_by'),
        }).encode('utf-8')

        headers = config.get('headers', {})
        headers['Content-Type'] = 'application/json'

        req = urllib.request.Request(url, data=payload, headers=headers, method='POST')
        try:
            urllib.request.urlopen(req, timeout=10)
            logger.info(f"  Webhook sent to {url}")
        except Exception as e:
            logger.warning(f"  Webhook failed: {e}")

    def _run_notification_command(self, config: Dict, event: str, context: Dict):
        """Execute a shell command as notification."""
        command = config.get('command')
        if not command:
            return

        env = {
            'TEMPLEDB_DEPLOY_EVENT': event,
            'TEMPLEDB_DEPLOY_PROJECT': context.get('project_slug', ''),
            'TEMPLEDB_DEPLOY_TARGET': context.get('target', ''),
            'TEMPLEDB_DEPLOY_SUCCESS': '1' if context.get('success') else '0',
            'TEMPLEDB_DEPLOY_MESSAGE': context.get('message', ''),
            'TEMPLEDB_DEPLOY_COMMIT': context.get('commit_hash', ''),
        }

        import os
        full_env = {**os.environ, **env}

        try:
            result = subprocess.run(
                command, shell=True, env=full_env,
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                logger.warning(f"  Notification command exited {result.returncode}: {result.stderr[:200]}")
            else:
                logger.info(f"  Notification command executed")
        except subprocess.TimeoutExpired:
            logger.warning(f"  Notification command timed out")
