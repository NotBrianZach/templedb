#!/usr/bin/env python3
"""
Blue-Green Deployment Strategy for TempleDB.

Manages two identical deployment slots (blue/green) per target.
Deploys to the inactive slot, health checks it, then swaps traffic.
Rollback is instant — just swap back.

Supports multiple backends:
- cloudflare: Swap Cloudflare Workers route rules
- dns: Swap DNS CNAME (generic)
- symlink: Swap local symlink (for testing)

Usage in deployment_config:
    "blue_green": {
        "enabled": true,
        "backend": "cloudflare",
        "slots": {
            "blue": {"worker_name": "aireadalong-blue"},
            "green": {"worker_name": "aireadalong-green"}
        },
        "route_pattern": "aireadalong.com/*",
        "health_check_url_template": "https://{slot_host}/health"
    }
"""
import json
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, Tuple

from services.base import BaseService


@dataclass
class SlotConfig:
    """Configuration for a single blue/green slot."""
    worker_name: Optional[str] = None
    host: Optional[str] = None
    url: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'SlotConfig':
        return cls(
            worker_name=data.get('worker_name'),
            host=data.get('host'),
            url=data.get('url'),
            extra={k: v for k, v in data.items()
                   if k not in ('worker_name', 'host', 'url')},
        )


@dataclass
class BlueGreenConfig:
    """Blue-green deployment configuration."""
    enabled: bool = False
    backend: str = "cloudflare"
    slots: Dict[str, SlotConfig] = field(default_factory=dict)
    route_pattern: Optional[str] = None
    health_check_url_template: Optional[str] = None
    swap_timeout: int = 30

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'BlueGreenConfig':
        if not data:
            return cls()
        slots = {
            name: SlotConfig.from_dict(cfg)
            for name, cfg in data.get('slots', {}).items()
        }
        return cls(
            enabled=data.get('enabled', False),
            backend=data.get('backend', 'cloudflare'),
            slots=slots,
            route_pattern=data.get('route_pattern'),
            health_check_url_template=data.get('health_check_url_template'),
            swap_timeout=data.get('swap_timeout', 30),
        )

    def to_dict(self) -> Dict[str, Any]:
        d = {'enabled': self.enabled, 'backend': self.backend}
        if self.slots:
            d['slots'] = {
                name: {k: v for k, v in {
                    'worker_name': cfg.worker_name,
                    'host': cfg.host,
                    'url': cfg.url,
                    **cfg.extra
                }.items() if v is not None}
                for name, cfg in self.slots.items()
            }
        if self.route_pattern:
            d['route_pattern'] = self.route_pattern
        if self.health_check_url_template:
            d['health_check_url_template'] = self.health_check_url_template
        if self.swap_timeout != 30:
            d['swap_timeout'] = self.swap_timeout
        return d


@dataclass
class SwapResult:
    success: bool
    previous_active: str
    new_active: str
    message: str
    health_check_passed: bool = False
    duration_seconds: float = 0.0


class BlueGreenService(BaseService):
    """Manages blue-green deployment slots and traffic swaps."""

    def __init__(self):
        super().__init__()

    def get_active_slot(self, project_id: int, target: str) -> str:
        """Get which slot (blue/green) is currently receiving traffic."""
        import db_utils
        row = db_utils.query_one("""
            SELECT active_slot FROM blue_green_state
            WHERE project_id = ? AND target = ?
        """, (project_id, target))
        return row['active_slot'] if row else 'blue'

    def get_inactive_slot(self, project_id: int, target: str) -> str:
        active = self.get_active_slot(project_id, target)
        return 'green' if active == 'blue' else 'blue'

    def get_state(self, project_id: int, target: str) -> Dict[str, Any]:
        """Get full blue-green state."""
        import db_utils
        row = db_utils.query_one("""
            SELECT * FROM blue_green_state
            WHERE project_id = ? AND target = ?
        """, (project_id, target))
        if row:
            return dict(row)
        return {
            'active_slot': 'blue',
            'blue_version': None,
            'green_version': None,
            'last_swap_at': None,
        }

    def record_deploy(self, project_id: int, target: str,
                      slot: str, version: str) -> None:
        """Record that a deployment was made to a slot."""
        import db_utils
        now = datetime.now().isoformat()

        db_utils.execute("""
            INSERT INTO blue_green_state (project_id, target, active_slot,
                blue_version, green_version, updated_at)
            VALUES (?, ?, 'blue', NULL, NULL, ?)
            ON CONFLICT(project_id, target) DO NOTHING
        """, (project_id, target, now))

        col = f"{slot}_version"
        db_utils.execute(f"""
            UPDATE blue_green_state
            SET {col} = ?, {slot}_deployed_at = ?, updated_at = ?
            WHERE project_id = ? AND target = ?
        """, (version, now, now, project_id, target))

    def health_check_slot(self, config: BlueGreenConfig,
                          slot: str) -> bool:
        """Run health check against a specific slot."""
        slot_config = config.slots.get(slot)
        if not slot_config:
            self.logger.warning(f"No config for slot {slot}")
            return False

        template = config.health_check_url_template
        if not template:
            self.logger.info(f"No health check URL template, skipping")
            return True

        # Build health check URL from template
        url = template.replace('{slot_host}',
                               slot_config.host or slot_config.worker_name or slot)
        url = url.replace('{worker_name}', slot_config.worker_name or '')

        self.logger.info(f"Health checking {slot}: {url}")

        for attempt in range(3):
            try:
                req = urllib.request.Request(url, method='GET')
                resp = urllib.request.urlopen(req, timeout=10)
                if resp.status == 200:
                    self.logger.info(f"  Health check passed (attempt {attempt+1})")
                    return True
            except Exception as e:
                self.logger.warning(f"  Attempt {attempt+1} failed: {e}")
                if attempt < 2:
                    time.sleep(3)

        return False

    def swap(self, project_id: int, target: str,
             config: BlueGreenConfig,
             skip_health_check: bool = False) -> SwapResult:
        """Swap traffic from active to inactive slot.

        Sequence:
        1. Identify active/inactive slots
        2. Health check the inactive slot (the one we just deployed to)
        3. Swap traffic using the configured backend
        4. Update state in DB
        """
        start = time.time()

        active = self.get_active_slot(project_id, target)
        inactive = self.get_inactive_slot(project_id, target)

        self.logger.info(f"Swapping {active} -> {inactive} for {target}")

        # Health check inactive slot before swapping
        health_ok = True
        if not skip_health_check:
            health_ok = self.health_check_slot(config, inactive)
            if not health_ok:
                return SwapResult(
                    success=False,
                    previous_active=active,
                    new_active=active,
                    message=f"Health check failed on {inactive} slot — swap aborted",
                    health_check_passed=False,
                    duration_seconds=time.time() - start,
                )

        # Perform the swap using the configured backend
        if config.backend == 'cloudflare':
            swap_ok, msg = self._swap_cloudflare(config, active, inactive)
        elif config.backend == 'symlink':
            swap_ok, msg = self._swap_symlink(config, active, inactive)
        else:
            swap_ok, msg = False, f"Unknown backend: {config.backend}"

        if not swap_ok:
            return SwapResult(
                success=False,
                previous_active=active,
                new_active=active,
                message=f"Swap failed: {msg}",
                health_check_passed=health_ok,
                duration_seconds=time.time() - start,
            )

        # Update DB state
        import db_utils
        now = datetime.now().isoformat()
        db_utils.execute("""
            UPDATE blue_green_state
            SET active_slot = ?, last_swap_at = ?, updated_at = ?,
                swap_count = COALESCE(swap_count, 0) + 1
            WHERE project_id = ? AND target = ?
        """, (inactive, now, now, project_id, target))

        elapsed = time.time() - start
        return SwapResult(
            success=True,
            previous_active=active,
            new_active=inactive,
            message=f"Traffic swapped {active} -> {inactive} in {elapsed:.1f}s",
            health_check_passed=health_ok,
            duration_seconds=elapsed,
        )

    def rollback(self, project_id: int, target: str,
                 config: BlueGreenConfig) -> SwapResult:
        """Roll back by swapping traffic to the previous slot.

        This is just a swap in the other direction — instant because
        the old version is still deployed on the other slot.
        """
        self.logger.info(f"Rolling back {target} — swapping to previous slot")
        return self.swap(project_id, target, config, skip_health_check=True)

    def _swap_cloudflare(self, config: BlueGreenConfig,
                         old_slot: str, new_slot: str) -> Tuple[bool, str]:
        """Swap Cloudflare Workers route to point to the new slot's worker."""
        new_config = config.slots.get(new_slot)
        if not new_config or not new_config.worker_name:
            return False, f"No worker_name for slot {new_slot}"

        route_pattern = config.route_pattern
        if not route_pattern:
            return False, "No route_pattern configured"

        # Use wrangler to update the route
        # wrangler route update requires zone-id; use the Workers route API
        # For simplicity, we re-deploy the inactive worker as the primary
        # by updating the route via wrangler
        cmd = [
            "npx", "wrangler", "routes", "update",
            route_pattern,
            "--worker", new_config.worker_name,
        ]

        self.logger.info(f"  Routing {route_pattern} -> {new_config.worker_name}")

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                return True, f"Route updated to {new_config.worker_name}"
            else:
                # Fallback: try using the Cloudflare API directly
                return self._swap_cloudflare_api(config, new_config, route_pattern)
        except Exception as e:
            return False, str(e)

    def _swap_cloudflare_api(self, config: BlueGreenConfig,
                             new_config: SlotConfig,
                             route_pattern: str) -> Tuple[bool, str]:
        """Fallback: swap via Cloudflare API when wrangler route update isn't available."""
        import os
        api_token = os.environ.get('CLOUDFLARE_API_TOKEN')
        zone_id = os.environ.get('CLOUDFLARE_ZONE_ID')

        if not api_token or not zone_id:
            return False, "CLOUDFLARE_API_TOKEN and CLOUDFLARE_ZONE_ID required for API swap"

        # List existing routes to find the one matching our pattern
        try:
            req = urllib.request.Request(
                f"https://api.cloudflare.com/client/v4/zones/{zone_id}/workers/routes",
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
            )
            resp = urllib.request.urlopen(req, timeout=10)
            data = json.loads(resp.read())

            route_id = None
            for route in data.get('result', []):
                if route.get('pattern') == route_pattern:
                    route_id = route['id']
                    break

            if not route_id:
                return False, f"Route pattern '{route_pattern}' not found in zone"

            # Update the route to point to the new worker
            update_data = json.dumps({
                'pattern': route_pattern,
                'script': new_config.worker_name,
            }).encode()

            req = urllib.request.Request(
                f"https://api.cloudflare.com/client/v4/zones/{zone_id}/workers/routes/{route_id}",
                data=update_data,
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
                method='PUT',
            )
            resp = urllib.request.urlopen(req, timeout=10)
            result = json.loads(resp.read())

            if result.get('success'):
                return True, f"Route {route_pattern} -> {new_config.worker_name}"
            else:
                errors = result.get('errors', [])
                return False, f"API error: {errors}"

        except Exception as e:
            return False, f"Cloudflare API error: {e}"

    def _swap_symlink(self, config: BlueGreenConfig,
                      old_slot: str, new_slot: str) -> Tuple[bool, str]:
        """Swap a local symlink for testing blue-green locally."""
        from pathlib import Path

        new_config = config.slots.get(new_slot)
        if not new_config or not new_config.extra.get('path'):
            return False, f"No path for slot {new_slot}"

        link_path = Path(config.slots.get(old_slot, SlotConfig()).extra.get(
            'link_path', '/tmp/bg-active'))
        target_path = Path(new_config.extra['path'])

        try:
            link_path.unlink(missing_ok=True)
            link_path.symlink_to(target_path)
            return True, f"Symlink {link_path} -> {target_path}"
        except Exception as e:
            return False, str(e)
