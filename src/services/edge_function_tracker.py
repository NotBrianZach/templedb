#!/usr/bin/env python3
"""
Edge Function Deployment Tracker.

Tracks content hashes of Supabase/Cloudflare edge functions to avoid
redundant deploys. Only redeploys functions whose source has changed
since the last successful deployment.
"""
import hashlib
import subprocess
import json
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Optional, Tuple

from services.base import BaseService


@dataclass
class FunctionState:
    """Current state of an edge function."""
    name: str
    content_hash: str
    file_count: int
    last_deployed_hash: Optional[str] = None
    last_deployed_at: Optional[str] = None

    @property
    def needs_deploy(self) -> bool:
        return self.content_hash != self.last_deployed_hash


@dataclass
class FunctionDeployResult:
    name: str
    success: bool
    skipped: bool = False
    message: str = ""
    content_hash: str = ""
    duration_seconds: float = 0.0


class EdgeFunctionTracker(BaseService):
    """Tracks and deploys edge functions with content-hash deduplication."""

    def __init__(self):
        super().__init__()

    def hash_function_dir(self, func_dir: Path) -> Tuple[str, int]:
        """Compute a content hash for an edge function directory.

        Hashes all source files (ts, js, json) sorted by path for
        deterministic output. Returns (hash, file_count).
        """
        h = hashlib.sha256()
        count = 0
        for f in sorted(func_dir.rglob("*")):
            if f.is_file() and f.suffix in ('.ts', '.js', '.json', '.mjs', '.mts'):
                rel = str(f.relative_to(func_dir))
                h.update(rel.encode())
                h.update(f.read_bytes())
                count += 1
        return h.hexdigest()[:16], count

    def scan_functions(self, functions_dir: Path, project_id: int,
                       target: str) -> List[FunctionState]:
        """Scan a functions directory and compare against last deployed state."""
        import db_utils

        states = []
        if not functions_dir.exists():
            return states

        for func_dir in sorted(functions_dir.iterdir()):
            if not func_dir.is_dir() or func_dir.name.startswith('_') or func_dir.name.startswith('.'):
                continue

            content_hash, file_count = self.hash_function_dir(func_dir)

            # Look up last deployed state
            row = db_utils.query_one("""
                SELECT content_hash, deployed_at
                FROM edge_function_deployments
                WHERE project_id = ? AND target = ? AND function_name = ?
                  AND status = 'success'
                ORDER BY deployed_at DESC LIMIT 1
            """, (project_id, target, func_dir.name))

            states.append(FunctionState(
                name=func_dir.name,
                content_hash=content_hash,
                file_count=file_count,
                last_deployed_hash=row['content_hash'] if row else None,
                last_deployed_at=row['deployed_at'] if row else None,
            ))

        return states

    def deploy_functions(self, functions_dir: Path, project_id: int,
                         target: str, project_ref: str,
                         force: bool = False,
                         dry_run: bool = False) -> List[FunctionDeployResult]:
        """Deploy changed edge functions.

        Args:
            functions_dir: Path to supabase/functions/ directory
            project_id: TempleDB project ID
            target: Deployment target name
            project_ref: Supabase project reference
            force: Deploy all functions even if unchanged
            dry_run: Only show what would be deployed
        """
        import db_utils
        import time

        states = self.scan_functions(functions_dir, project_id, target)
        results = []

        changed = [s for s in states if s.needs_deploy or force]
        unchanged = [s for s in states if not s.needs_deploy and not force]

        if unchanged:
            self.logger.info(f"  Skipping {len(unchanged)} unchanged function(s)")

        if not changed:
            self.logger.info("  All functions up to date")
            return results

        for state in changed:
            if dry_run:
                results.append(FunctionDeployResult(
                    name=state.name,
                    success=True,
                    skipped=True,
                    message=f"[dry-run] Would deploy {state.name} ({state.content_hash})",
                    content_hash=state.content_hash,
                ))
                continue

            self.logger.info(f"  Deploying {state.name} ({state.content_hash[:8]})")

            start = time.time()
            try:
                result = subprocess.run(
                    ["supabase", "functions", "deploy", state.name,
                     "--project-ref", project_ref],
                    capture_output=True, text=True, timeout=120,
                    cwd=str(functions_dir.parent),
                )
                elapsed = time.time() - start

                success = result.returncode == 0
                message = result.stdout.strip()[-200:] if success else result.stderr.strip()[-200:]

                # Record deployment
                db_utils.execute("""
                    INSERT INTO edge_function_deployments
                        (project_id, target, function_name, content_hash,
                         file_count, status, message, duration_seconds, deployed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    project_id, target, state.name, state.content_hash,
                    state.file_count,
                    'success' if success else 'failed',
                    message[:500],
                    round(elapsed, 2),
                    datetime.now().isoformat(),
                ))

                results.append(FunctionDeployResult(
                    name=state.name,
                    success=success,
                    message=message,
                    content_hash=state.content_hash,
                    duration_seconds=elapsed,
                ))

            except subprocess.TimeoutExpired:
                results.append(FunctionDeployResult(
                    name=state.name,
                    success=False,
                    message=f"Timed out after 120s",
                    content_hash=state.content_hash,
                    duration_seconds=120.0,
                ))
            except Exception as e:
                results.append(FunctionDeployResult(
                    name=state.name,
                    success=False,
                    message=str(e),
                    content_hash=state.content_hash,
                ))

        return results

    def get_deployment_status(self, project_id: int, target: str) -> List[Dict]:
        """Get current deployment status of all functions."""
        import db_utils

        return db_utils.query_all("""
            SELECT function_name, content_hash, status, duration_seconds,
                   deployed_at, message
            FROM edge_function_deployments
            WHERE project_id = ? AND target = ?
              AND deployed_at = (
                  SELECT MAX(deployed_at) FROM edge_function_deployments e2
                  WHERE e2.project_id = edge_function_deployments.project_id
                    AND e2.target = edge_function_deployments.target
                    AND e2.function_name = edge_function_deployments.function_name
              )
            ORDER BY function_name
        """, (project_id, target))
