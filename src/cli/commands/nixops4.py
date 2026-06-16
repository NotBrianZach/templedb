#!/usr/bin/env python3
"""
NixOps4 deployment orchestration commands for TempleDB

Provides declarative infrastructure deployment using NixOps4.
Manages networks, machines, deployments, and resources.
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


class NixOps4Commands(Command):
    """NixOps4 orchestration command handlers"""

    def __init__(self):
        super().__init__()

    # ========================================================================
    # Network Management
    # ========================================================================

    def network_create(self, args) -> int:
        """Create a new nixops4 network"""
        try:
            project = db_utils.get_project_by_slug(args.project)
            if not project:
                print(f"❌ Project '{args.project}' not found")
                return 1

            # Generate UUID for network
            network_uuid = str(uuid.uuid4())

            # Insert network
            db_utils.execute("""
                INSERT INTO nixops4_networks
                (project_id, network_name, network_uuid, config_file_path, flake_uri, description, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                project['id'],
                args.name,
                network_uuid,
                args.config_file or f"{args.project}/network.nix",
                args.flake_uri,
                args.description,
                args.created_by or 'user'
            ))

            print(f"✅ Created network '{args.name}' for project '{args.project}'")
            print(f"   UUID: {network_uuid}")
            print(f"   Config: {args.config_file or f'{args.project}/network.nix'}")

            return 0

        except Exception as e:
            logger.error(f"Error creating network: {e}")
            print(f"❌ Failed to create network: {e}")
            return 1

    def network_list(self, args) -> int:
        """List nixops4 networks"""
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
                SELECT * FROM nixops4_network_summary
                {project_filter}
                ORDER BY network_name
            """)

            if not networks:
                print("No nixops4 networks found")
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
                SELECT * FROM nixops4_machines
                WHERE network_id = ?
                ORDER BY machine_name
            """, (network['id'],))

            # Get recent deployments
            deployments = db_utils.query_all("""
                SELECT * FROM nixops4_deployment_history
                WHERE network_id = ?
                LIMIT 10
            """, (network['id'],))

            # Get resources
            resources = db_utils.query_all("""
                SELECT * FROM nixops4_resources
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

            # Insert machine
            db_utils.execute("""
                INSERT INTO nixops4_machines
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
                json.dumps(args.config) if hasattr(args, 'config') and args.config else '{}'
            ))

            print(f"✅ Added machine '{args.machine}' to network '{args.network}'")
            print(f"   UUID: {machine_uuid}")
            print(f"   Host: {args.host}")
            print(f"   Type: {args.system_type or 'nixos'}")

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
                SELECT * FROM nixops4_machines
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
                SELECT * FROM nixops4_machines
                WHERE network_id = ? AND machine_name = ?
            """, (network['id'], args.machine))

            if not machine:
                print(f"❌ Machine '{args.machine}' not found in network '{args.network}'")
                return 1

            # Remove machine (cascades to deployments)
            db_utils.execute("""
                DELETE FROM nixops4_machines
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
        """Deploy a nixops4 network"""
        try:
            network = self._get_network(args.network, args.project)
            if not network:
                return 1

            # Get machines to deploy
            if hasattr(args, 'machines') and args.machines:
                target_machines = args.machines
                machines = db_utils.query_all("""
                    SELECT * FROM nixops4_machines
                    WHERE network_id = ? AND machine_name IN ({})
                """.format(','.join('?' * len(target_machines))),
                (network['id'], *target_machines))
            else:
                target_machines = None
                machines = db_utils.query_all("""
                    SELECT * FROM nixops4_machines
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
                INSERT INTO nixops4_deployments
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
                    INSERT INTO nixops4_machine_deployments
                    (deployment_id, machine_id, status)
                    VALUES (?, ?, ?)
                """, (deployment_id, machine['id'], 'pending'))

            # Execute nixops4 deployment
            success = self._run_nixops4_deploy(
                network=network,
                deployment_id=deployment_id,
                machines=machines,
                dry_run=hasattr(args, 'dry_run') and args.dry_run,
                build_only=hasattr(args, 'build_only') and args.build_only
            )

            if success:
                db_utils.execute("""
                    UPDATE nixops4_deployments
                    SET status = 'success', completed_at = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), deployment_id))
                print(f"\n✅ Deployment completed successfully")
                return 0
            else:
                db_utils.execute("""
                    UPDATE nixops4_deployments
                    SET status = 'failed', completed_at = ?
                    WHERE id = ?
                """, (datetime.now().isoformat(), deployment_id))
                print(f"\n❌ Deployment failed")
                return 1

        except Exception as e:
            logger.error(f"Error deploying network: {e}")
            print(f"❌ Deployment error: {e}")
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
                    SELECT * FROM nixops4_deployment_history
                    WHERE deployment_uuid = ?
                """, (args.deployment_uuid,))

                if not deployment:
                    print(f"❌ Deployment '{args.deployment_uuid}' not found")
                    return 1

                self._show_deployment_detail(deployment)
            else:
                # Show recent deployments
                deployments = db_utils.query_all("""
                    SELECT * FROM nixops4_deployment_history
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
            SELECT * FROM nixops4_networks
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

    def _run_nixops4_deploy(
        self,
        network: Dict[str, Any],
        deployment_id: int,
        machines: List[Dict[str, Any]],
        dry_run: bool = False,
        build_only: bool = False
    ) -> bool:
        """Execute nixops4 deployment"""
        try:
            # Build nixops4 command
            cmd = ['nixops4', 'deploy', '--network', network['network_uuid']]

            if network['flake_uri']:
                cmd.extend(['--flake', network['flake_uri']])
            else:
                cmd.extend(['--config', network['config_file_path']])

            if dry_run:
                cmd.append('--dry-run')
            if build_only:
                cmd.append('--build-only')

            # Run deployment
            print(f"\n🔨 Running: {' '.join(cmd)}\n")

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True
            )

            # Store output
            db_utils.execute("""
                UPDATE nixops4_deployments
                SET stdout_log = ?, stderr_log = ?, exit_code = ?
                WHERE id = ?
            """, (result.stdout, result.stderr, result.returncode, deployment_id))

            # Update machine deployment statuses
            # (This is simplified - real implementation would parse nixops4 output)
            for machine in machines:
                status = 'success' if result.returncode == 0 else 'failed'
                db_utils.execute("""
                    UPDATE nixops4_machine_deployments
                    SET status = ?, deploy_completed_at = ?
                    WHERE deployment_id = ? AND machine_id = ?
                """, (status, datetime.now().isoformat(), deployment_id, machine['id']))

                # Update machine status
                if result.returncode == 0:
                    db_utils.execute("""
                        UPDATE nixops4_machines
                        SET deployment_status = 'deployed', last_deployed_at = ?
                        WHERE id = ?
                    """, (datetime.now().isoformat(), machine['id']))

            print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)

            return result.returncode == 0

        except Exception as e:
            logger.error(f"Error running nixops4 deploy: {e}")
            print(f"❌ Deployment execution error: {e}")
            return False

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
            FROM nixops4_machine_deployments md
            JOIN nixops4_machines m ON md.machine_id = m.id
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


def _register_nixops4_commands(handler, subparsers, cli, prefix='nixops4'):
    """Register nixops4 commands with customizable prefix

    Args:
        handler: NixOps4Commands instance
        subparsers: Subparser to register under
        cli: CLI instance
        prefix: Command prefix (e.g., 'nixops4' or 'deploy.nixops4')
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


def register_under_deploy(deploy_subparsers, cli):
    """Register nixops4 commands under deploy command (NEW: deploy nixops4 ...)"""
    handler = NixOps4Commands()

    # Create nixops4 subcommand under deploy
    nixops4_parser = deploy_subparsers.add_parser(
        'nixops4',
        help='NixOps4 declarative deployment orchestration'
    )
    nixops4_subparsers = nixops4_parser.add_subparsers(dest='nixops4_subcommand', required=True)

    # Register all commands with 'deploy.nixops4' prefix
    _register_nixops4_commands(handler, nixops4_subparsers, cli, prefix='deploy.nixops4')
