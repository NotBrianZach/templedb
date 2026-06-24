#!/usr/bin/env python3
"""
NixOS Deployment Backend - TempleDB's native deployment engine.

TempleDB's native deployment engine. Provides:

- nix build: Build system closures from flake
- nix copy: Transfer closures to targets via SSH
- switch-to-configuration: Activate new system profile
- Magic rollback watchdog: systemd transient timer auto-reverts
  if deployer can't SSH back after activation
- Parallel fleet deployment via concurrent.futures
- Per-machine status tracking via DB
"""
import subprocess
import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

from services.base import BaseService

WATCHDOG_UNIT = "templedb-deploy-watchdog"
DEFAULT_WATCHDOG_TIMEOUT = 90
DEFAULT_SSH_TIMEOUT = 10
DEFAULT_CONFIRM_RETRIES = 5
DEFAULT_CONFIRM_INTERVAL = 5


@dataclass
class MachineTarget:
    """A machine to deploy to."""
    machine_id: int
    machine_name: str
    target_host: str
    target_user: str = "root"
    target_port: int = 22
    flake_attr: Optional[str] = None  # nixosConfigurations.<attr>
    tags: List[str] = field(default_factory=list)

    @property
    def ssh_dest(self) -> str:
        if self.target_port != 22:
            return f"ssh://{self.target_user}@{self.target_host}:{self.target_port}"
        return f"ssh://{self.target_user}@{self.target_host}"

    @property
    def ssh_args(self) -> List[str]:
        args = ["-o", "StrictHostKeyChecking=accept-new",
                "-o", f"ConnectTimeout={DEFAULT_SSH_TIMEOUT}"]
        if self.target_port != 22:
            args.extend(["-p", str(self.target_port)])
        return args


@dataclass
class MachineDeployResult:
    """Result of deploying to a single machine."""
    machine: MachineTarget
    success: bool
    phase: str  # 'build', 'copy', 'activate', 'confirm'
    message: str
    store_path: Optional[str] = None
    old_profile: Optional[str] = None
    new_profile: Optional[str] = None
    duration_seconds: float = 0.0
    watchdog_active: bool = False
    error: Optional[str] = None

    # Per-phase timing
    build_seconds: float = 0.0
    copy_seconds: float = 0.0
    activate_seconds: float = 0.0


@dataclass
class FleetDeployResult:
    """Result of deploying to multiple machines."""
    results: List[MachineDeployResult]
    total_seconds: float = 0.0

    @property
    def success(self) -> bool:
        return all(r.success for r in self.results)

    @property
    def succeeded(self) -> List[MachineDeployResult]:
        return [r for r in self.results if r.success]

    @property
    def failed(self) -> List[MachineDeployResult]:
        return [r for r in self.results if not r.success]

    @property
    def summary(self) -> str:
        total = len(self.results)
        ok = len(self.succeeded)
        return f"{ok}/{total} machines deployed successfully in {self.total_seconds:.1f}s"


class NixDeployBackend(BaseService):
    """TempleDB's native NixOS deployment engine."""

    def __init__(self):
        super().__init__()

    # ------------------------------------------------------------------
    # Core operations
    # ------------------------------------------------------------------

    def build_system(self, flake_path: str, flake_attr: str,
                     build_host: Optional[str] = None) -> MachineDeployResult:
        """Build a NixOS system closure from a flake.

        Args:
            flake_path: Path to flake directory or flake URI
            flake_attr: Flake attribute (e.g. 'zMothership2')
            build_host: Optional remote build host

        Returns:
            MachineDeployResult with store_path set on success
        """
        target_attr = f"{flake_path}#nixosConfigurations.{flake_attr}.config.system.build.toplevel"

        cmd = ["nix", "build", target_attr, "--no-link", "--print-out-paths"]
        if build_host:
            cmd.extend(["--builders", f"ssh://{build_host}"])

        self.logger.info(f"Building {flake_attr}: nix build ...#{flake_attr}")

        start = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        elapsed = time.time() - start

        if result.returncode != 0:
            return MachineDeployResult(
                machine=MachineTarget(0, flake_attr, ""),
                success=False,
                phase="build",
                message=f"Build failed for {flake_attr}",
                error=result.stderr.strip()[-500:],
                build_seconds=elapsed,
                duration_seconds=elapsed,
            )

        store_path = result.stdout.strip().split("\n")[-1]
        return MachineDeployResult(
            machine=MachineTarget(0, flake_attr, ""),
            success=True,
            phase="build",
            message=f"Built {flake_attr} in {elapsed:.1f}s",
            store_path=store_path,
            build_seconds=elapsed,
            duration_seconds=elapsed,
        )

    def copy_closure(self, store_path: str, machine: MachineTarget) -> MachineDeployResult:
        """Copy a Nix closure to a remote machine.

        Uses nix copy which handles deduplication automatically.
        """
        cmd = ["nix", "copy", "--to", machine.ssh_dest, store_path]

        self.logger.info(f"Copying closure to {machine.machine_name} ({machine.target_host})")

        start = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        elapsed = time.time() - start

        if result.returncode != 0:
            return MachineDeployResult(
                machine=machine,
                success=False,
                phase="copy",
                message=f"Copy failed to {machine.machine_name}",
                store_path=store_path,
                error=result.stderr.strip()[-500:],
                copy_seconds=elapsed,
                duration_seconds=elapsed,
            )

        return MachineDeployResult(
            machine=machine,
            success=True,
            phase="copy",
            message=f"Copied to {machine.machine_name} in {elapsed:.1f}s",
            store_path=store_path,
            copy_seconds=elapsed,
            duration_seconds=elapsed,
        )

    def _ssh_cmd(self, machine: MachineTarget, remote_cmd: str,
                 timeout: int = 30) -> subprocess.CompletedProcess:
        """Run a command on a remote machine via SSH."""
        cmd = ["ssh"] + machine.ssh_args + [
            f"{machine.target_user}@{machine.target_host}",
            remote_cmd
        ]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def _get_current_profile(self, machine: MachineTarget) -> Optional[str]:
        """Get the current system profile path on a remote machine."""
        result = self._ssh_cmd(machine, "readlink /run/current-system")
        if result.returncode == 0:
            return result.stdout.strip()
        return None

    def _start_watchdog(self, machine: MachineTarget, old_profile: str,
                        timeout_secs: int = DEFAULT_WATCHDOG_TIMEOUT) -> bool:
        """Start a watchdog timer on the target that will revert to old_profile.

        Creates a systemd transient timer. If not cancelled within timeout_secs,
        it runs switch-to-configuration to revert to the previous profile.

        This is TempleDB's equivalent of deploy-rs magic rollback.
        """
        # The watchdog command: revert to old profile
        revert_cmd = f"{old_profile}/bin/switch-to-configuration switch"

        # Use systemd-run to create a transient timer
        # --on-active creates a timer that fires N seconds from now
        watchdog_cmd = (
            f"systemd-run --unit={WATCHDOG_UNIT} "
            f"--on-active={timeout_secs} "
            f"--timer-property=AccuracySec=1s "
            f'--description="TempleDB deploy watchdog: auto-revert in {timeout_secs}s" '
            f"-- {revert_cmd}"
        )

        self.logger.info(f"Starting watchdog on {machine.machine_name} "
                         f"(auto-revert in {timeout_secs}s)")

        result = self._ssh_cmd(machine, watchdog_cmd, timeout=15)

        if result.returncode != 0:
            self.logger.warning(f"Failed to start watchdog: {result.stderr.strip()}")
            return False

        return True

    def _cancel_watchdog(self, machine: MachineTarget) -> bool:
        """Cancel the watchdog timer, confirming the deployment."""
        cancel_cmd = (
            f"systemctl stop {WATCHDOG_UNIT}.timer {WATCHDOG_UNIT}.service 2>/dev/null; "
            f"systemctl reset-failed {WATCHDOG_UNIT}.timer {WATCHDOG_UNIT}.service 2>/dev/null; "
            f"echo confirmed"
        )

        result = self._ssh_cmd(machine, cancel_cmd, timeout=10)
        return result.returncode == 0 and "confirmed" in result.stdout

    def activate(self, store_path: str, machine: MachineTarget,
                 action: str = "switch",
                 use_watchdog: bool = True,
                 watchdog_timeout: int = DEFAULT_WATCHDOG_TIMEOUT) -> MachineDeployResult:
        """Activate a system profile on a remote machine.

        With watchdog enabled (default), the sequence is:
        1. Record current profile
        2. Start systemd watchdog timer (will revert after timeout)
        3. Run switch-to-configuration
        4. Return -- caller must confirm via confirm_deployment()

        If the new config breaks SSH/networking, the watchdog fires
        and reverts to the old profile automatically.

        Args:
            store_path: Nix store path of the system to activate
            machine: Target machine
            action: switch, boot, test, or dry-activate
            use_watchdog: Enable magic rollback watchdog
            watchdog_timeout: Seconds before auto-revert (default 90)
        """
        start = time.time()

        # Step 1: Record current profile
        old_profile = self._get_current_profile(machine)
        if not old_profile:
            return MachineDeployResult(
                machine=machine,
                success=False,
                phase="activate",
                message=f"Cannot read current profile on {machine.machine_name}",
                store_path=store_path,
                error="Failed to readlink /run/current-system",
                activate_seconds=time.time() - start,
                duration_seconds=time.time() - start,
            )

        # Step 2: Start watchdog (if enabled and action is 'switch')
        watchdog_active = False
        if use_watchdog and action == "switch":
            # Clean up any leftover watchdog from a previous deploy
            self._cancel_watchdog(machine)

            watchdog_active = self._start_watchdog(machine, old_profile, watchdog_timeout)
            if not watchdog_active:
                self.logger.warning(
                    f"Watchdog failed to start on {machine.machine_name}, "
                    f"proceeding without rollback protection"
                )

        # Step 3: Activate
        switch_cmd = f"{store_path}/bin/switch-to-configuration {action}"
        self.logger.info(f"Activating on {machine.machine_name}: {action}")

        try:
            result = self._ssh_cmd(machine, switch_cmd, timeout=300)
        except subprocess.TimeoutExpired:
            elapsed = time.time() - start
            return MachineDeployResult(
                machine=machine,
                success=False,
                phase="activate",
                message=f"Activation timed out on {machine.machine_name}",
                store_path=store_path,
                old_profile=old_profile,
                error="switch-to-configuration timed out after 300s",
                watchdog_active=watchdog_active,
                activate_seconds=elapsed,
                duration_seconds=elapsed,
            )

        elapsed = time.time() - start

        if result.returncode != 0:
            # Activation failed -- if watchdog is running it will revert
            return MachineDeployResult(
                machine=machine,
                success=False,
                phase="activate",
                message=f"Activation failed on {machine.machine_name}",
                store_path=store_path,
                old_profile=old_profile,
                error=result.stderr.strip()[-500:],
                watchdog_active=watchdog_active,
                activate_seconds=elapsed,
                duration_seconds=elapsed,
            )

        return MachineDeployResult(
            machine=machine,
            success=True,
            phase="activate",
            message=f"Activated on {machine.machine_name} in {elapsed:.1f}s",
            store_path=store_path,
            old_profile=old_profile,
            new_profile=store_path,
            watchdog_active=watchdog_active,
            activate_seconds=elapsed,
            duration_seconds=elapsed,
        )

    def confirm_deployment(self, machine: MachineTarget,
                           retries: int = DEFAULT_CONFIRM_RETRIES,
                           interval: int = DEFAULT_CONFIRM_INTERVAL) -> MachineDeployResult:
        """Confirm a deployment by SSH-ing back and cancelling the watchdog.

        Retries SSH connection multiple times, since the target may be
        restarting services (including sshd) during activation.

        This is the second half of the magic rollback protocol:
        - If we can SSH back: cancel watchdog, deployment confirmed
        - If we can't: watchdog timer expires, target auto-reverts
        """
        start = time.time()

        for attempt in range(1, retries + 1):
            self.logger.info(
                f"Confirming {machine.machine_name} "
                f"(attempt {attempt}/{retries})"
            )

            try:
                # Try a simple SSH command first
                result = self._ssh_cmd(machine, "echo reachable", timeout=DEFAULT_SSH_TIMEOUT)

                if result.returncode == 0 and "reachable" in result.stdout:
                    # Machine is reachable -- cancel watchdog
                    cancelled = self._cancel_watchdog(machine)
                    elapsed = time.time() - start

                    if cancelled:
                        new_profile = self._get_current_profile(machine)
                        return MachineDeployResult(
                            machine=machine,
                            success=True,
                            phase="confirm",
                            message=(
                                f"Deployment confirmed on {machine.machine_name} "
                                f"(attempt {attempt}, {elapsed:.1f}s)"
                            ),
                            new_profile=new_profile,
                            watchdog_active=False,
                            duration_seconds=elapsed,
                        )
                    else:
                        # Reachable but couldn't cancel watchdog --
                        # it may have already fired
                        return MachineDeployResult(
                            machine=machine,
                            success=False,
                            phase="confirm",
                            message=(
                                f"Reachable but watchdog cancel failed on "
                                f"{machine.machine_name}"
                            ),
                            error="Could not cancel watchdog timer",
                            watchdog_active=True,
                            duration_seconds=elapsed,
                        )

            except (subprocess.TimeoutExpired, Exception) as e:
                self.logger.warning(
                    f"  Attempt {attempt} failed: {e}"
                )

            if attempt < retries:
                time.sleep(interval)

        elapsed = time.time() - start
        return MachineDeployResult(
            machine=machine,
            success=False,
            phase="confirm",
            message=(
                f"Cannot reach {machine.machine_name} after {retries} attempts. "
                f"Watchdog will auto-revert in <=90s."
            ),
            error=f"SSH unreachable after {retries} attempts over {elapsed:.1f}s",
            watchdog_active=True,
            duration_seconds=elapsed,
        )

    # ------------------------------------------------------------------
    # Single-machine full pipeline
    # ------------------------------------------------------------------

    def deploy_machine(self, flake_path: str, machine: MachineTarget,
                       action: str = "switch",
                       use_watchdog: bool = True,
                       watchdog_timeout: int = DEFAULT_WATCHDOG_TIMEOUT,
                       dry_run: bool = False,
                       pre_built_path: Optional[str] = None,
                       ) -> MachineDeployResult:
        """Full deployment pipeline for a single machine.

        Pipeline: build -> copy -> activate (with watchdog) -> confirm

        Args:
            flake_path: Path to flake or flake URI
            machine: Target machine
            action: switch, boot, test, dry-activate
            use_watchdog: Enable magic rollback (default True)
            watchdog_timeout: Seconds before auto-revert
            dry_run: Only build, don't deploy
            pre_built_path: Skip build, use this store path
        """
        pipeline_start = time.time()
        flake_attr = machine.flake_attr or machine.machine_name

        # Phase 1: Build
        if pre_built_path:
            store_path = pre_built_path
            build_secs = 0.0
        else:
            build_result = self.build_system(flake_path, flake_attr)
            build_secs = build_result.build_seconds

            if not build_result.success:
                build_result.machine = machine
                return build_result

            store_path = build_result.store_path

        if dry_run:
            # In dry-run, show what would be deployed
            elapsed = time.time() - pipeline_start
            return MachineDeployResult(
                machine=machine,
                success=True,
                phase="build",
                message=f"[dry-run] Would deploy {store_path} to {machine.machine_name}",
                store_path=store_path,
                build_seconds=build_secs,
                duration_seconds=elapsed,
            )

        # Phase 2: Copy
        copy_result = self.copy_closure(store_path, machine)
        if not copy_result.success:
            copy_result.build_seconds = build_secs
            return copy_result

        # Phase 3: Activate (starts watchdog)
        activate_result = self.activate(
            store_path, machine,
            action=action,
            use_watchdog=use_watchdog,
            watchdog_timeout=watchdog_timeout,
        )
        if not activate_result.success:
            activate_result.build_seconds = build_secs
            activate_result.copy_seconds = copy_result.copy_seconds
            return activate_result

        # Phase 4: Confirm (cancel watchdog)
        if activate_result.watchdog_active:
            confirm_result = self.confirm_deployment(machine)
            elapsed = time.time() - pipeline_start

            # Merge timings into final result
            confirm_result.store_path = store_path
            confirm_result.old_profile = activate_result.old_profile
            confirm_result.build_seconds = build_secs
            confirm_result.copy_seconds = copy_result.copy_seconds
            confirm_result.activate_seconds = activate_result.activate_seconds
            confirm_result.duration_seconds = elapsed
            return confirm_result
        else:
            # No watchdog (disabled or action != switch) -- done
            elapsed = time.time() - pipeline_start
            activate_result.build_seconds = build_secs
            activate_result.copy_seconds = copy_result.copy_seconds
            activate_result.duration_seconds = elapsed
            activate_result.phase = "confirm"
            return activate_result

    # ------------------------------------------------------------------
    # Fleet deployment (parallel)
    # ------------------------------------------------------------------

    def deploy_fleet(self, flake_path: str, machines: List[MachineTarget],
                     action: str = "switch",
                     use_watchdog: bool = True,
                     watchdog_timeout: int = DEFAULT_WATCHDOG_TIMEOUT,
                     dry_run: bool = False,
                     max_parallel: int = 5,
                     shared_build: bool = True,
                     on_machine_result: Any = None,
                     ) -> FleetDeployResult:
        """Deploy to multiple machines in parallel.

        Build strategy:
        - shared_build=True (default): Build each unique flake_attr once,
          then copy to all machines using that attr. Saves rebuild time
          when multiple machines share the same config.
        - shared_build=False: Build per-machine (useful when machines
          have different flake attributes).

        Args:
            flake_path: Path to flake or flake URI
            machines: List of target machines
            action: switch, boot, test, dry-activate
            use_watchdog: Enable magic rollback
            watchdog_timeout: Seconds before auto-revert
            dry_run: Only build, don't deploy
            max_parallel: Max concurrent deployments
            shared_build: Share builds across machines with same flake_attr
            on_machine_result: Optional callback(MachineDeployResult) for progress
        """
        fleet_start = time.time()
        results: List[MachineDeployResult] = []

        if not machines:
            return FleetDeployResult(results=[], total_seconds=0)

        # Phase 1: Build (sequential, shared across machines)
        builds: Dict[str, str] = {}  # flake_attr -> store_path
        if shared_build:
            # Group machines by flake_attr
            attr_groups: Dict[str, List[MachineTarget]] = {}
            for m in machines:
                attr = m.flake_attr or m.machine_name
                attr_groups.setdefault(attr, []).append(m)

            for attr in attr_groups:
                self.logger.info(f"Building {attr} (for {len(attr_groups[attr])} machine(s))")
                build_result = self.build_system(flake_path, attr)

                if not build_result.success:
                    # Mark all machines with this attr as failed
                    for m in attr_groups[attr]:
                        fail = MachineDeployResult(
                            machine=m,
                            success=False,
                            phase="build",
                            message=f"Build failed for {attr}",
                            error=build_result.error,
                            build_seconds=build_result.build_seconds,
                            duration_seconds=build_result.duration_seconds,
                        )
                        results.append(fail)
                        if on_machine_result:
                            on_machine_result(fail)
                    continue

                builds[attr] = build_result.store_path

            # Filter to machines whose builds succeeded
            deployable = [m for m in machines
                          if (m.flake_attr or m.machine_name) in builds]
        else:
            deployable = machines

        if dry_run:
            for m in deployable:
                attr = m.flake_attr or m.machine_name
                store_path = builds.get(attr, "???")
                r = MachineDeployResult(
                    machine=m,
                    success=True,
                    phase="build",
                    message=f"[dry-run] Would deploy {store_path} to {m.machine_name}",
                    store_path=store_path,
                )
                results.append(r)
                if on_machine_result:
                    on_machine_result(r)

            return FleetDeployResult(
                results=results,
                total_seconds=time.time() - fleet_start,
            )

        # Phase 2-4: Copy + Activate + Confirm (parallel per machine)
        def _deploy_one(m: MachineTarget) -> MachineDeployResult:
            attr = m.flake_attr or m.machine_name
            store_path = builds.get(attr) if shared_build else None

            return self.deploy_machine(
                flake_path=flake_path,
                machine=m,
                action=action,
                use_watchdog=use_watchdog,
                watchdog_timeout=watchdog_timeout,
                pre_built_path=store_path,
            )

        with ThreadPoolExecutor(max_workers=max_parallel) as pool:
            futures = {pool.submit(_deploy_one, m): m for m in deployable}

            for future in as_completed(futures):
                machine = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    result = MachineDeployResult(
                        machine=machine,
                        success=False,
                        phase="unknown",
                        message=f"Unexpected error deploying {machine.machine_name}",
                        error=str(e),
                    )

                results.append(result)
                if on_machine_result:
                    on_machine_result(result)

        return FleetDeployResult(
            results=results,
            total_seconds=time.time() - fleet_start,
        )

    # ------------------------------------------------------------------
    # Diff / dry-activate
    # ------------------------------------------------------------------

    def diff_system(self, flake_path: str, machine: MachineTarget) -> Optional[str]:
        """Show what would change if deployed.

        Builds the new system, gets the current profile, and runs nix-diff.
        """
        flake_attr = machine.flake_attr or machine.machine_name
        build_result = self.build_system(flake_path, flake_attr)
        if not build_result.success:
            return f"Build failed: {build_result.error}"

        old_profile = self._get_current_profile(machine)
        if not old_profile:
            return "Cannot read current profile on target"

        if old_profile == build_result.store_path:
            return "No changes -- current system matches build output"

        # Try nix-diff if available, fall back to path comparison
        try:
            result = subprocess.run(
                ["nix", "store", "diff-closures", old_profile, build_result.store_path],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        return (
            f"Old: {old_profile}\n"
            f"New: {build_result.store_path}\n"
            f"(install nix-diff for detailed comparison)"
        )

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------

    def check_machine(self, machine: MachineTarget) -> Dict[str, Any]:
        """Health check a deployed machine."""
        info: Dict[str, Any] = {
            "machine": machine.machine_name,
            "host": machine.target_host,
            "reachable": False,
        }

        try:
            result = self._ssh_cmd(machine, "echo ok", timeout=DEFAULT_SSH_TIMEOUT)
            info["reachable"] = result.returncode == 0
        except (subprocess.TimeoutExpired, Exception):
            return info

        if info["reachable"]:
            # Get system info
            cmds = {
                "profile": "readlink /run/current-system",
                "nixos_version": "cat /run/current-system/nixos-version 2>/dev/null || echo unknown",
                "uptime": "cat /proc/uptime | cut -d' ' -f1",
                "boot_id": "cat /proc/sys/kernel/random/boot_id",
            }
            for key, cmd in cmds.items():
                try:
                    r = self._ssh_cmd(machine, cmd, timeout=10)
                    info[key] = r.stdout.strip() if r.returncode == 0 else None
                except Exception:
                    info[key] = None

            # Check if watchdog is active (stale from failed deploy)
            try:
                r = self._ssh_cmd(
                    machine,
                    f"systemctl is-active {WATCHDOG_UNIT}.timer 2>/dev/null || echo inactive",
                    timeout=10,
                )
                info["watchdog_active"] = "active" in r.stdout and "inactive" not in r.stdout
            except Exception:
                info["watchdog_active"] = None

        return info

    def machines_from_db(self, network_id: int,
                         tag_filter: Optional[List[str]] = None) -> List[MachineTarget]:
        """Load MachineTarget list from fleet_machines table.

        Args:
            network_id: Network ID to load machines from
            tag_filter: Optional list of tags to filter by
        """
        import db_utils

        machines = db_utils.query_all("""
            SELECT id, machine_name, target_host, target_user, target_port,
                   machine_config
            FROM fleet_machines
            WHERE network_id = ?
            ORDER BY machine_name
        """, (network_id,))

        targets = []
        for m in machines:
            config = json.loads(m["machine_config"]) if m.get("machine_config") else {}
            tags = config.get("tags", [])

            # Filter by tags if specified
            if tag_filter:
                if not any(t in tags for t in tag_filter):
                    continue

            targets.append(MachineTarget(
                machine_id=m["id"],
                machine_name=m["machine_name"],
                target_host=m["target_host"] or "",
                target_user=m["target_user"] or "root",
                target_port=m["target_port"] or 22,
                flake_attr=config.get("flake_attr", m["machine_name"]),
                tags=tags,
            ))

        return targets

    def update_machine_status(self, result: MachineDeployResult,
                              deployment_id: int) -> None:
        """Write deployment result back to nixops4 DB tables."""
        import db_utils

        now = datetime.now().isoformat()
        machine_id = result.machine.machine_id

        if not machine_id:
            return

        # Update machine status
        if result.success:
            db_utils.execute("""
                UPDATE fleet_machines
                SET deployment_status = 'deployed',
                    last_deployed_at = ?,
                    system_profile = ?,
                    health_status = 'healthy',
                    health_check_at = ?
                WHERE id = ?
            """, (now, result.new_profile, now, machine_id))
        else:
            db_utils.execute("""
                UPDATE fleet_machines
                SET deployment_status = 'failed',
                    health_status = ?
                WHERE id = ?
            """, (
                "reverting" if result.watchdog_active else "unhealthy",
                machine_id,
            ))

        # Update per-machine deployment record
        db_utils.execute("""
            UPDATE fleet_machine_deployments
            SET status = ?,
                deploy_completed_at = ?,
                old_system_profile = ?,
                new_system_profile = ?,
                error_message = ?
            WHERE deployment_id = ? AND machine_id = ?
        """, (
            "success" if result.success else "failed",
            now,
            result.old_profile,
            result.new_profile if result.success else None,
            result.error,
            deployment_id,
            machine_id,
        ))
