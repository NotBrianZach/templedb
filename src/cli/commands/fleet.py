#!/usr/bin/env python3
"""
Fleet deployment commands for TempleDB.

TempleDB's native multi-machine NixOS deployment engine.
Manages networks, machines, deployments, and resources with:
- Parallel fleet deployment via nix build + copy + switch
- Magic rollback watchdog (auto-revert on connectivity loss)
- Tag-based machine targeting
- Full deployment history and per-machine tracking
"""
import sys
import subprocess
import json
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime
import uuid

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger
import db_utils

logger = get_logger(__name__)


class FleetCommands(Command):
    """Fleet deployment command handlers"""

    def __init__(self):
        super().__init__()

    # ========================================================================
    # Network Management
    # ========================================================================

    def network_create(self, args) -> int:
        """Create a new fleet network"""
        try:
            project = db_utils.get_project_by_slug(args.project)
            if not project:
                print(f"❌ Project '{args.project}' not found")
                return 1

            # Generate UUID for network
            network_uuid = str(uuid.uuid4())

            flake_uri = args.flake_uri
            config_file = args.config_file or f"{args.project}/network.nix"

            # Record in DB
            db_utils.execute("""
                INSERT INTO fleet_networks
                (project_id, network_name, network_uuid, config_file_path, flake_uri, description, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                project['id'],
                args.name,
                network_uuid,
                config_file,
                flake_uri,
                args.description,
                args.created_by or 'user'
            ))

            print(f"✅ Created network '{args.name}' for project '{args.project}'")
            print(f"   UUID: {network_uuid}")
            print(f"   Config: {config_file}")

            return 0

        except Exception as e:
            logger.error(f"Error creating network: {e}")
            print(f"❌ Failed to create network: {e}")
            return 1

    def network_list(self, args) -> int:
        """List fleet networks"""
        try:
            # Filter by project if specified
            if hasattr(args, 'project') and args.project:
                project = db_utils.get_project_by_slug(args.project)
                if not project:
                    print(f"❌ Project '{args.project}' not found")
                    return 1
                project_filter = f"WHERE n.project_id = {project['id']}"
            else:
                project_filter = ""

            networks = db_utils.query_all(f"""
                SELECT * FROM fleet_network_summary
                {project_filter}
                ORDER BY network_name
            """)

            if not networks:
                print("No fleet networks found")
                return 0

            print(f"\n{'Network':<20} {'Project':<15} {'Machines':<10} {'Deployed':<10} {'Last Deployment':<20}")
            print("=" * 85)

            for net in networks:
                last_deploy = net['last_deployment_at'] or 'Never'
                if last_deploy != 'Never':
                    last_deploy = datetime.fromisoformat(last_deploy).strftime('%Y-%m-%d %H:%M')

                print(f"{net['network_name']:<20} {net['project_slug']:<15} "
                      f"{net['machine_count']:<10} {net['deployed_machines']:<10} {last_deploy:<20}")

            return 0

        except Exception as e:
            logger.error(f"Error listing networks: {e}")
            print(f"❌ Failed to list networks: {e}")
            return 1

    def network_info(self, args) -> int:
        """Show detailed network information"""
        try:
            network = self._get_network(args.network, args.project)
            if not network:
                return 1

            # Get machines
            machines = db_utils.query_all("""
                SELECT * FROM fleet_machines
                WHERE network_id = ?
                ORDER BY machine_name
            """, (network['id'],))

            # Get recent deployments
            deployments = db_utils.query_all("""
                SELECT * FROM fleet_deployment_history
                WHERE network_id = ?
                LIMIT 10
            """, (network['id'],))

            # Get resources
            resources = db_utils.query_all("""
                SELECT * FROM fleet_resources
                WHERE network_id = ?
                ORDER BY resource_type, resource_name
            """, (network['id'],))

            print(f"\n🌐 Network: {network['network_name']}")
            print(f"   Project: {args.project}")
            print(f"   UUID: {network['network_uuid']}")
            print(f"   Config: {network['config_file_path']}")
            if network['flake_uri']:
                print(f"   Flake: {network['flake_uri']}")
            print(f"   Active: {'Yes' if network['is_active'] else 'No'}")

            print(f"\n📦 Machines ({len(machines)}):")
            if machines:
                print(f"   {'Name':<20} {'Host':<25} {'Status':<15} {'Health':<15}")
                print("   " + "=" * 75)
                for m in machines:
                    print(f"   {m['machine_name']:<20} {m['target_host'] or 'N/A':<25} "
                          f"{m['deployment_status']:<15} {m['health_status'] or 'unknown':<15}")
            else:
                print("   No machines configured")

            if resources:
                print(f"\n🔧 Resources ({len(resources)}):")
                for r in resources:
                    print(f"   - {r['resource_name']} ({r['resource_type']}) - {r['status']}")

            if deployments:
                print(f"\n📜 Recent Deployments:")
                for d in deployments:
                    started = datetime.fromisoformat(d['started_at']).strftime('%Y-%m-%d %H:%M')
                    status_icon = '✅' if d['status'] == 'success' else '❌' if d['status'] == 'failed' else '⏳'
                    print(f"   {status_icon} {started} - {d['operation']} - {d['status']} "
                          f"({d['successful_machines']}/{d['total_machines']} machines)")

            return 0

        except Exception as e:
            logger.error(f"Error showing network info: {e}")
            print(f"❌ Failed to show network info: {e}")
            return 1

    # ========================================================================
    # Machine Management
    # ========================================================================

    def machine_add(self, args) -> int:
        """Add a machine to a network"""
        try:
            network = self._get_network(args.network, args.project)
            if not network:
                return 1

            # Generate UUID for machine
            machine_uuid = str(uuid.uuid4())

            # Build machine config from args
            tags = getattr(args, 'tags', None) or []
            flake_attr = getattr(args, 'flake_attr', None)
            machine_config = {}
            if tags:
                machine_config['tags'] = tags
            if flake_attr:
                machine_config['flake_attr'] = flake_attr

            # Insert machine
            db_utils.execute("""
                INSERT INTO fleet_machines
                (network_id, machine_name, machine_uuid, target_host, target_user, target_port,
                 system_type, target_env, machine_config)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                network['id'],
                args.machine,
                machine_uuid,
                args.host,
                args.user or 'root',
                args.port or 22,
                args.system_type or 'nixos',
                args.target_env or 'none',
                json.dumps(machine_config)
            ))

            print(f"✅ Added machine '{args.machine}' to network '{args.network}'")
            print(f"   UUID: {machine_uuid}")
            print(f"   Host: {args.host}")
            print(f"   Type: {args.system_type or 'nixos'}")
            if tags:
                print(f"   Tags: {', '.join(tags)}")
            if flake_attr:
                print(f"   Flake attr: {flake_attr}")

            return 0

        except Exception as e:
            logger.error(f"Error adding machine: {e}")
            print(f"❌ Failed to add machine: {e}")
            return 1

    def machine_list(self, args) -> int:
        """List machines in a network"""
        try:
            network = self._get_network(args.network, args.project)
            if not network:
                return 1

            machines = db_utils.query_all("""
                SELECT * FROM fleet_machines
                WHERE network_id = ?
                ORDER BY machine_name
            """, (network['id'],))

            if not machines:
                print(f"No machines in network '{args.network}'")
                return 0

            print(f"\n{'Machine':<20} {'Host':<25} {'Status':<15} {'Health':<15} {'Last Deployed':<20}")
            print("=" * 95)

            for m in machines:
                last_deploy = m['last_deployed_at'] or 'Never'
                if last_deploy != 'Never':
                    last_deploy = datetime.fromisoformat(last_deploy).strftime('%Y-%m-%d %H:%M')

                print(f"{m['machine_name']:<20} {m['target_host'] or 'N/A':<25} "
                      f"{m['deployment_status']:<15} {m['health_status'] or 'unknown':<15} {last_deploy:<20}")

            return 0

        except Exception as e:
            logger.error(f"Error listing machines: {e}")
            print(f"❌ Failed to list machines: {e}")
            return 1

    def machine_remove(self, args) -> int:
        """Remove a machine from a network"""
        try:
            network = self._get_network(args.network, args.project)
            if not network:
                return 1

            # Check if machine exists
            machine = db_utils.query_one("""
                SELECT * FROM fleet_machines
                WHERE network_id = ? AND machine_name = ?
            """, (network['id'], args.machine))

            if not machine:
                print(f"❌ Machine '{args.machine}' not found in network '{args.network}'")
                return 1

            # Remove machine (cascades to deployments)
            db_utils.execute("""
                DELETE FROM fleet_machines
                WHERE id = ?
            """, (machine['id'],))

            print(f"✅ Removed machine '{args.machine}' from network '{args.network}'")
            return 0

        except Exception as e:
            logger.error(f"Error removing machine: {e}")
            print(f"❌ Failed to remove machine: {e}")
            return 1

    # ========================================================================
    # Deployment Operations
    # ========================================================================

    def deploy(self, args) -> int:
        """Deploy a fleet network"""
        try:
            network = self._get_network(args.network, args.project)
            if not network:
                return 1

            # Get machines to deploy
            if hasattr(args, 'machines') and args.machines:
                target_machines = args.machines
                machines = db_utils.query_all("""
                    SELECT * FROM fleet_machines
                    WHERE network_id = ? AND machine_name IN ({})
                """.format(','.join('?' * len(target_machines))),
                (network['id'], *target_machines))
            else:
                target_machines = None
                machines = db_utils.query_all("""
                    SELECT * FROM fleet_machines
                    WHERE network_id = ?
                """, (network['id'],))

            if not machines:
                print(f"❌ No machines to deploy in network '{args.network}'")
                return 1

            # Render templates for all machines before deployment
            print(f"\n📝 Rendering configuration templates...")
            templates_rendered = self._render_network_templates(network, machines)
            if templates_rendered > 0:
                print(f"   ✓ Rendered {templates_rendered} template(s) across {len(machines)} machine(s)")

            # Create deployment record
            deployment_uuid = str(uuid.uuid4())
            deployment_id = db_utils.execute("""
                INSERT INTO fleet_deployments
                (network_id, deployment_uuid, operation, target_machines, started_at,
                 triggered_by, triggered_reason, config_revision, deploy_options)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                network['id'],
                deployment_uuid,
                'deploy',
                json.dumps(target_machines) if target_machines else None,
                datetime.now().isoformat(),
                args.triggered_by or 'user',
                args.reason or 'Manual deployment',
                args.config_revision or self._get_git_revision(),
                json.dumps({
                    'dry_run': args.dry_run if hasattr(args, 'dry_run') else False,
                    'build_only': args.build_only if hasattr(args, 'build_only') else False,
                    'force_reboot': args.force_reboot if hasattr(args, 'force_reboot') else False
                })
            ))

            print(f"\n🚀 Deploying network '{args.network}'")
            print(f"   Deployment UUID: {deployment_uuid}")
            print(f"   Machines: {len(machines)}")

            if hasattr(args, 'dry_run') and args.dry_run:
                print("\n📋 DRY RUN - No actual deployment will occur\n")

            # Create machine deployment records
            for machine in machines:
                db_utils.execute("""
                    INSERT INTO fleet_machine_deployments
                    (deployment_id, machine_id, status)
                    VALUES (?, ?, ?)
                """, (deployment_id, machine['id'], 'pending'))

            # Execute deployment via TempleDB nix backend
            use_watchdog = not (hasattr(args, 'no_watchdog') and args.no_watchdog)
            watchdog_timeout = getattr(args, 'watchdog_timeout', 90) or 90
            tag_filter = getattr(args, 'on_tags', None)

            success = self._run_fleet_deploy(
                network=network,
                deployment_id=deployment_id,
                machines=machines,
                dry_run=hasattr(args, 'dry_run') and args.dry_run,
                build_only=hasattr(args, 'build_only') and args.build_only,
                use_watchdog=use_watchdog,
                watchdog_timeout=watchdog_timeout,
                tag_filter=tag_filter,
            )

            if success:
                db_utils.execute("""
                    UPDATE fleet_deployments
                    SET status = 'success', completed_at = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), deployment_id))
                print(f"\n✅ Deployment completed successfully")
                return 0
            else:
                db_utils.execute("""
                    UPDATE fleet_deployments
                    SET status = 'failed', completed_at = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), deployment_id))
                print(f"\n❌ Deployment failed")
                return 1

        except Exception as e:
            logger.error(f"Error deploying network: {e}")
            print(f"❌ Deployment error: {e}")
            return 1

    def destroy(self, args) -> int:
        """Destroy a fleet network (deactivate and remove from DB)"""
        try:
            network = self._get_network(args.network, args.project)
            if not network:
                return 1

            if not (hasattr(args, 'yes') and args.yes):
                response = input(f"Destroy network '{args.network}'? This will terminate all machines. [y/N] ").strip().lower()
                if response != 'y':
                    print("Cancelled")
                    return 0

            # Record destruction in deployment history
            db_utils.execute("""
                INSERT INTO fleet_deployments
                (network_id, deployment_uuid, operation, started_at, completed_at,
                 status, triggered_by, triggered_reason)
                VALUES (?, ?, 'destroy', ?, ?, ?, 'user', ?)
            """, (network['id'], str(uuid.uuid4()),
                  datetime.now().isoformat(), datetime.now().isoformat(),
                  'success' if result.returncode == 0 else 'failed',
                  args.reason if hasattr(args, 'reason') else 'Manual destroy'))

            # Update all machines to terminated
            db_utils.execute("""
                UPDATE fleet_machines SET deployment_status = 'terminated'
                WHERE network_id = ?
            """, (network['id'],))

            # Deactivate network
            db_utils.execute("""
                UPDATE fleet_networks SET is_active = 0 WHERE id = ?
            """, (network['id'],))

            print(f"✅ Network '{args.network}' destroyed")
            return 0

        except Exception as e:
            logger.error(f"Error destroying network: {e}")
            print(f"❌ Failed to destroy network: {e}")
            return 1

    def check(self, args) -> int:
        """Check health of deployed machines via SSH"""
        try:
            network = self._get_network(args.network, args.project)
            if not network:
                return 1

            from services.nix_deploy_backend import NixDeployBackend

            backend = NixDeployBackend()
            targets = backend.machines_from_db(network['id'])

            if not targets:
                print("No machines configured")
                return 0

            print(f"\nChecking {len(targets)} machine(s)...\n")
            print(f"{'Machine':<20} {'Host':<25} {'Reachable':<12} {'Version':<20} {'Watchdog':<10}")
            print("=" * 87)

            all_healthy = True
            for target in targets:
                info = backend.check_machine(target)
                reachable = info.get('reachable', False)
                version = info.get('nixos_version', 'N/A') if reachable else 'N/A'
                watchdog = 'ACTIVE' if info.get('watchdog_active') else '-'
                icon = '✅' if reachable else '❌'

                print(f"{target.machine_name:<20} {target.target_host:<25} "
                      f"{icon} {'yes':<9} {version:<20} {watchdog:<10}")

                # Update DB
                now = datetime.now().isoformat()
                health = 'healthy' if reachable else 'unreachable'
                db_utils.execute("""
                    UPDATE fleet_machines
                    SET health_status = ?, health_check_at = ?, nixos_version = ?
                    WHERE id = ?
                """, (health, now, version if reachable else None, target.machine_id))

                if not reachable:
                    all_healthy = False

            print(f"\n{'✅ All machines healthy' if all_healthy else '⚠️  Some machines unreachable'}")
            return 0 if all_healthy else 1

        except Exception as e:
            logger.error(f"Error checking network: {e}")
            print(f"❌ Health check error: {e}")
            return 1

    def ssh(self, args) -> int:
        """SSH into a machine in a fleet network"""
        try:
            network = self._get_network(args.network, args.project)
            if not network:
                return 1

            machine = db_utils.query_one("""
                SELECT * FROM fleet_machines
                WHERE network_id = ? AND machine_name = ?
            """, (network['id'], args.machine))

            if not machine:
                print(f"❌ Machine '{args.machine}' not found in network '{args.network}'")
                return 1

            if not machine['target_host']:
                print(f"❌ Machine '{args.machine}' has no target host configured")
                return 1

            user = machine['target_user'] or 'root'
            port = machine['target_port'] or 22
            host = machine['target_host']

            ssh_cmd = ['ssh', '-p', str(port), f'{user}@{host}']
            if hasattr(args, 'ssh_command') and args.ssh_command:
                ssh_cmd.extend(args.ssh_command)

            print(f"Connecting to {user}@{host}:{port}...")
            import os
            os.execvp('ssh', ssh_cmd)

        except Exception as e:
            logger.error(f"Error: {e}")
            print(f"❌ SSH error: {e}")
            return 1

    def diff(self, args) -> int:
        """Show what would change if deployed"""
        try:
            network = self._get_network(args.network, args.project)
            if not network:
                return 1

            from services.nix_deploy_backend import NixDeployBackend

            backend = NixDeployBackend()
            targets = backend.machines_from_db(network['id'])
            flake_path = network['flake_uri'] or network['config_file_path']

            if hasattr(args, 'machine') and args.machine:
                targets = [t for t in targets if t.machine_name == args.machine]

            if not targets:
                print("No machines found")
                return 1

            for target in targets:
                print(f"\n--- {target.machine_name} ({target.target_host}) ---")
                diff_output = backend.diff_system(flake_path, target)
                print(diff_output or "(no output)")

            return 0

        except Exception as e:
            logger.error(f"Error computing diff: {e}")
            print(f"❌ Diff error: {e}")
            return 1

    def deploy_status(self, args) -> int:
        """Show deployment status"""
        try:
            network = self._get_network(args.network, args.project)
            if not network:
                return 1

            if hasattr(args, 'deployment_uuid') and args.deployment_uuid:
                # Show specific deployment
                deployment = db_utils.query_one("""
                    SELECT * FROM fleet_deployment_history
                    WHERE deployment_uuid = ?
                """, (args.deployment_uuid,))

                if not deployment:
                    print(f"❌ Deployment '{args.deployment_uuid}' not found")
                    return 1

                self._show_deployment_detail(deployment)
            else:
                # Show recent deployments
                deployments = db_utils.query_all("""
                    SELECT * FROM fleet_deployment_history
                    WHERE network_id = ?
                    LIMIT 20
                """, (network['id'],))

                if not deployments:
                    print(f"No deployments for network '{args.network}'")
                    return 0

                print(f"\n{'Started':<20} {'Operation':<10} {'Status':<10} {'Machines':<15} {'Duration':<10} {'By':<15}")
                print("=" * 90)

                for d in deployments:
                    started = datetime.fromisoformat(d['started_at']).strftime('%Y-%m-%d %H:%M')
                    duration = f"{d['duration_seconds']}s" if d['duration_seconds'] else 'Running'
                    machines_str = f"{d['successful_machines']}/{d['total_machines']}"
                    status_icon = '✅' if d['status'] == 'success' else '❌' if d['status'] == 'failed' else '⏳'

                    print(f"{started:<20} {d['operation']:<10} {status_icon} {d['status']:<8} "
                          f"{machines_str:<15} {duration:<10} {d['triggered_by'] or 'N/A':<15}")

            return 0

        except Exception as e:
            logger.error(f"Error showing deployment status: {e}")
            print(f"❌ Failed to show deployment status: {e}")
            return 1

    # ========================================================================
    # Helper Methods
    # ========================================================================

    def _get_network(self, network_name: str, project_slug: str) -> Optional[Dict[str, Any]]:
        """Get network by name and project"""
        project = db_utils.get_project_by_slug(project_slug)
        if not project:
            print(f"❌ Project '{project_slug}' not found")
            return None

        network = db_utils.query_one("""
            SELECT * FROM fleet_networks
            WHERE project_id = ? AND network_name = ?
        """, (project['id'], network_name))

        if not network:
            print(f"❌ Network '{network_name}' not found in project '{project_slug}'")
            return None

        return network

    def _get_git_revision(self) -> Optional[str]:
        """Get current git revision"""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', 'HEAD'],
                capture_output=True,
                text=True,
                check=True
            )
            return result.stdout.strip()
        except:
            return None

    def _render_network_templates(self, network: Dict[str, Any], machines: List[Dict[str, Any]]) -> int:
        """Render configuration templates for all machines in network

        Uses naming convention:
        - machine_name.template.var: Machine-specific value
        - template.var: System-wide default value

        Args:
            network: Network dict from database
            machines: List of machine dicts to render templates for

        Returns:
            Total number of templates rendered across all machines
        """
        from template_renderer import TemplateRenderer
        from services.system_service import SystemService

        total_count = 0

        # Get project info
        project = db_utils.query_one(
            "SELECT slug FROM projects WHERE id = ?",
            (network['project_id'],)
        )

        if not project:
            logger.warning(f"Project not found for network {network['network_name']}")
            return 0

        # Get project checkout path
        system_service = SystemService()
        checkout_path = system_service.get_project_checkout_path(project['slug'])

        if not checkout_path:
            logger.warning(f"No checkout found for project {project['slug']}, skipping template rendering")
            return 0

        # Render templates for each machine
        renderer = TemplateRenderer()

        for machine in machines:
            machine_name = machine['machine_name']
            machine_id = machine['id']
            print(f"   Rendering templates for machine: {machine_name} (ID: {machine_id})")

            # Render with scoped configuration (machine > network > project > system)
            count = renderer.render_project_templates(
                project['slug'],
                checkout_path,
                machine_id=machine_id,
                network_id=network['id'],
                project_id=network['project_id']
            )

            total_count += count

        # Auto-commit generated files for Nix flakes
        # Nix flakes only see files tracked in git
        if total_count > 0:
            try:
                subprocess.run(
                    ["git", "add", "modules/*/config.nix", "*.nix"],
                    cwd=checkout_path,
                    check=False,
                    capture_output=True
                )

                result = subprocess.run(
                    ["git", "commit", "-m", f"Auto-update generated configs for network {network['network_name']}"],
                    cwd=checkout_path,
                    capture_output=True,
                    text=True
                )

                if result.returncode == 0:
                    logger.info(f"Auto-committed generated config files for {len(machines)} machines")
            except Exception as e:
                logger.warning(f"Could not auto-commit generated files: {e}")

        return total_count

    def _run_fleet_deploy(
        self,
        network: Dict[str, Any],
        deployment_id: int,
        machines: List[Dict[str, Any]],
        dry_run: bool = False,
        build_only: bool = False,
        use_watchdog: bool = True,
        watchdog_timeout: int = 90,
        tag_filter: Optional[List[str]] = None,
    ) -> bool:
        """Execute deployment using TempleDB's native nix deploy backend.

        Uses direct nix build + copy +
        switch-to-configuration, with optional magic rollback watchdog.
        """
        from services.nix_deploy_backend import NixDeployBackend, MachineTarget

        backend = NixDeployBackend()

        # Determine flake path
        flake_path = network['flake_uri'] or network['config_file_path']

        # Convert DB machine rows to MachineTarget objects
        targets = []
        for m in machines:
            config = json.loads(m.get('machine_config') or '{}')
            tags = config.get('tags', [])

            # Apply tag filter if specified
            if tag_filter and not any(t in tags for t in tag_filter):
                continue

            targets.append(MachineTarget(
                machine_id=m['id'],
                machine_name=m['machine_name'],
                target_host=m.get('target_host') or '',
                target_user=m.get('target_user') or 'root',
                target_port=m.get('target_port') or 22,
                flake_attr=config.get('flake_attr', m['machine_name']),
                tags=tags,
            ))

        if not targets:
            print("❌ No machines match the deployment criteria")
            return False

        action = "switch"
        if build_only:
            action = "dry-activate"
            use_watchdog = False

        # Progress callback
        def on_result(result):
            icon = '✅' if result.success else '❌'
            print(f"   {icon} {result.machine.machine_name}: {result.message}")
            if result.error:
                print(f"      Error: {result.error[:200]}")

            # Update DB status
            backend.update_machine_status(result, deployment_id)

        print(f"\n🚀 Deploying {len(targets)} machine(s) via TempleDB nix backend")
        if use_watchdog:
            print(f"   🛡️  Magic rollback enabled (auto-revert in {watchdog_timeout}s on connectivity loss)")
        if dry_run:
            print(f"   📋 DRY RUN — build only, no activation\n")
        else:
            print()

        # Run fleet deployment
        fleet_result = backend.deploy_fleet(
            flake_path=flake_path,
            machines=targets,
            action=action,
            use_watchdog=use_watchdog,
            watchdog_timeout=watchdog_timeout,
            dry_run=dry_run,
            on_machine_result=on_result,
        )

        # Store summary in deployment record
        summary_lines = []
        for r in fleet_result.results:
            summary_lines.append(
                f"{r.machine.machine_name}: {r.phase} "
                f"{'ok' if r.success else 'FAIL'} "
                f"(build={r.build_seconds:.1f}s copy={r.copy_seconds:.1f}s "
                f"activate={r.activate_seconds:.1f}s total={r.duration_seconds:.1f}s)"
            )

        db_utils.execute("""
            UPDATE fleet_deployments
            SET stdout_log = ?, exit_code = ?
            WHERE id = ?
        """, ("\n".join(summary_lines), 0 if fleet_result.success else 1, deployment_id))

        print(f"\n{'✅' if fleet_result.success else '❌'} {fleet_result.summary}")
        return fleet_result.success

    def _show_deployment_detail(self, deployment: Dict[str, Any]):
        """Show detailed deployment information"""
        print(f"\n📦 Deployment: {deployment['deployment_uuid']}")
        print(f"   Network: {deployment['network_name']}")
        print(f"   Operation: {deployment['operation']}")
        print(f"   Status: {deployment['status']}")
        print(f"   Started: {deployment['started_at']}")
        if deployment['completed_at']:
            print(f"   Completed: {deployment['completed_at']}")
            print(f"   Duration: {deployment['duration_seconds']}s")
        print(f"   Triggered by: {deployment['triggered_by']}")

        # Get machine-level details
        machine_deployments = db_utils.query_all("""
            SELECT md.*, m.machine_name, m.target_host
            FROM fleet_machine_deployments md
            JOIN fleet_machines m ON md.machine_id = m.id
            WHERE md.deployment_id = ?
            ORDER BY m.machine_name
        """, (deployment['id'],))

        if machine_deployments:
            print(f"\n   Machines ({len(machine_deployments)}):")
            for md in machine_deployments:
                status_icon = '✅' if md['status'] == 'success' else '❌' if md['status'] == 'failed' else '⏳'
                duration = f"{md['deploy_duration_seconds']}s" if md['deploy_duration_seconds'] else 'N/A'
                print(f"   {status_icon} {md['machine_name']:<20} {md['target_host'] or 'N/A':<25} "
                      f"{md['status']:<10} {duration:<10}")
                if md['error_message']:
                    print(f"      Error: {md['error_message']}")


def _register_fleet_commands(handler, subparsers, cli, prefix='fleet'):
    """Register fleet deployment commands with customizable prefix.

    Args:
        handler: FleetCommands instance
        subparsers: Subparser to register under
        cli: CLI instance
        prefix: Command prefix (e.g., 'fleet' or 'deploy.fleet')
    """
    # Network commands
    network_parser = subparsers.add_parser('network', help='Manage deployment networks')
    network_subparsers = network_parser.add_subparsers(dest='network_command', required=True, help='Network operations')

    # network create
    create_parser = network_subparsers.add_parser('create', help='Create a new deployment network')
    create_parser.add_argument('project', help='Project slug')
    create_parser.add_argument('name', help='Network name')
    create_parser.add_argument('--config-file', help='Path to network configuration file')
    create_parser.add_argument('--flake-uri', help='Flake URI for network configuration')
    create_parser.add_argument('--description', help='Network description')
    create_parser.add_argument('--created-by', help='Creator identifier')
    cli.commands[f'{prefix}.network.create'] = handler.network_create

    # network list
    list_parser = network_subparsers.add_parser('list', help='List deployment networks')
    list_parser.add_argument('--project', help='Filter by project')
    cli.commands[f'{prefix}.network.list'] = handler.network_list

    # network info
    info_parser = network_subparsers.add_parser('info', help='Show network details')
    info_parser.add_argument('project', help='Project slug')
    info_parser.add_argument('network', help='Network name')
    cli.commands[f'{prefix}.network.info'] = handler.network_info

    # Machine commands
    machine_parser = subparsers.add_parser('machine', help='Manage machines in networks')
    machine_subparsers = machine_parser.add_subparsers(dest='machine_command', required=True, help='Machine operations')

    # machine add
    add_parser = machine_subparsers.add_parser('add', help='Add a machine to a network')
    add_parser.add_argument('project', help='Project slug')
    add_parser.add_argument('network', help='Network name')
    add_parser.add_argument('machine', help='Machine name')
    add_parser.add_argument('--host', required=True, help='Target host (hostname or IP)')
    add_parser.add_argument('--user', default='root', help='SSH user (default: root)')
    add_parser.add_argument('--port', type=int, default=22, help='SSH port (default: 22)')
    add_parser.add_argument('--system-type', default='nixos', help='System type (default: nixos)')
    add_parser.add_argument('--target-env', default='none', help='Target environment (default: none)')
    add_parser.add_argument('--tags', nargs='+', metavar='TAG', help='Machine tags for targeting (e.g. --tags web austin)')
    add_parser.add_argument('--flake-attr', help='Flake attribute name (default: machine name)')
    cli.commands[f'{prefix}.machine.add'] = handler.machine_add

    # machine list
    mlist_parser = machine_subparsers.add_parser('list', help='List machines in a network')
    mlist_parser.add_argument('project', help='Project slug')
    mlist_parser.add_argument('network', help='Network name')
    cli.commands[f'{prefix}.machine.list'] = handler.machine_list

    # machine remove
    remove_parser = machine_subparsers.add_parser('remove', help='Remove a machine from a network')
    remove_parser.add_argument('project', help='Project slug')
    remove_parser.add_argument('network', help='Network name')
    remove_parser.add_argument('machine', help='Machine name')
    cli.commands[f'{prefix}.machine.remove'] = handler.machine_remove

    # Deployment commands
    # deploy
    deploy_parser = subparsers.add_parser('deploy', help='Deploy a network')
    deploy_parser.add_argument('project', help='Project slug')
    deploy_parser.add_argument('network', help='Network name')
    deploy_parser.add_argument('--machines', nargs='+', help='Specific machines to deploy (default: all)')
    deploy_parser.add_argument('--dry-run', action='store_true', help='Dry run (no actual deployment)')
    deploy_parser.add_argument('--build-only', action='store_true', help='Build only, do not deploy')
    deploy_parser.add_argument('--force-reboot', action='store_true', help='Force reboot after deployment')
    deploy_parser.add_argument('--no-watchdog', action='store_true', help='Disable magic rollback watchdog')
    deploy_parser.add_argument('--watchdog-timeout', type=int, default=90, help='Watchdog auto-revert timeout in seconds (default: 90)')
    deploy_parser.add_argument('--on', dest='on_tags', nargs='+', metavar='TAG', help='Deploy only to machines with these tags (e.g. --on web austin)')
    deploy_parser.add_argument('--config-revision', help='Config revision (git commit hash)')
    deploy_parser.add_argument('--triggered-by', help='Who triggered the deployment')
    deploy_parser.add_argument('--reason', help='Deployment reason')
    cli.commands[f'{prefix}.deploy'] = handler.deploy

    # status
    status_parser = subparsers.add_parser('status', help='Show deployment status')
    status_parser.add_argument('project', help='Project slug')
    status_parser.add_argument('network', help='Network name')
    status_parser.add_argument('--deployment-uuid', help='Show specific deployment')
    cli.commands[f'{prefix}.status'] = handler.deploy_status

    # destroy
    destroy_parser = subparsers.add_parser('destroy', help='Destroy a network (terminate all machines)')
    destroy_parser.add_argument('project', help='Project slug')
    destroy_parser.add_argument('network', help='Network name')
    destroy_parser.add_argument('--yes', action='store_true', help='Skip confirmation')
    destroy_parser.add_argument('--force', action='store_true', help='Force destroy')
    destroy_parser.add_argument('--reason', help='Reason for destruction')
    cli.commands[f'{prefix}.destroy'] = handler.destroy

    # diff
    diff_parser = subparsers.add_parser('diff', help='Show what would change if deployed')
    diff_parser.add_argument('project', help='Project slug')
    diff_parser.add_argument('network', help='Network name')
    diff_parser.add_argument('--machine', help='Diff a specific machine (default: all)')
    cli.commands[f'{prefix}.diff'] = handler.diff

    # check
    check_parser = subparsers.add_parser('check', help='Check health of deployed machines')
    check_parser.add_argument('project', help='Project slug')
    check_parser.add_argument('network', help='Network name')
    cli.commands[f'{prefix}.check'] = handler.check

    # ssh
    ssh_parser = subparsers.add_parser('ssh', help='SSH into a machine')
    ssh_parser.add_argument('project', help='Project slug')
    ssh_parser.add_argument('network', help='Network name')
    ssh_parser.add_argument('machine', help='Machine name')
    ssh_parser.add_argument('ssh_command', nargs='*', help='Command to run (default: interactive shell)')
    cli.commands[f'{prefix}.ssh'] = handler.ssh


def register_under_deploy(deploy_subparsers, cli):
    """Register fleet commands under deploy command (deploy fleet ...)"""
    handler = FleetCommands()

    fleet_parser = deploy_subparsers.add_parser(
        'fleet',
        help='Multi-machine NixOS deployment with magic rollback'
    )
    fleet_subparsers = fleet_parser.add_subparsers(dest='fleet_subcommand', required=True)

    _register_fleet_commands(handler, fleet_subparsers, cli, prefix='deploy.fleet')
