#!/usr/bin/env python3
"""
Nix Deployment Commands - Phase 1 Implementation

Commands for deploying web services using Nix closures and systemd.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger
from services.deployment.nix_deployment_service import NixDeploymentService

logger = get_logger(__name__)


class NixDeployCommands(Command):
    """Nix deployment command handlers"""

    def __init__(self):
        super().__init__()
        self.nix_service = NixDeploymentService(self.get_connection())

    def build_closure(self, args) -> int:
        """Build Nix closure for project"""
        project_slug = args.slug

        # Get project from database
        project = self.get_project_or_exit(project_slug)

        # Get project path
        project_path = Path(project['git_path']) if project.get('git_path') else None
        if not project_path or not project_path.exists():
            logger.error(f"Project path not found: {project_path}")
            return 1

        print(f"🔨 Building Nix closure for {project_slug}...")
        print(f"📁 Project path: {project_path}\n")

        # Build closure
        result = self.nix_service.build_nix_closure(project_path, project_slug)

        if result.success:
            print(f"✅ {result.message}")
            print(f"\n📦 Closure location: {result.closure_path}")
            print(f"\nNext steps:")
            print(f"  1. Transfer: templedb deploy-nix transfer {project_slug} --host <target-host>")
            print(f"  2. Import:   templedb deploy-nix import {project_slug} --host <target-host>")
            print(f"  3. Activate: templedb deploy-nix activate {project_slug} --host <target-host>")
            return 0
        else:
            print(f"❌ {result.message}")
            if result.error:
                print(f"\nError details:\n{result.error}")
            return 1

    def transfer(self, args) -> int:
        """Transfer Nix closure to target VPS"""
        project_slug = args.slug
        target_host = args.host
        target_user = args.user if hasattr(args, 'user') and args.user else 'deploy'

        # Find closure
        temp_dir = Path('/tmp/templedb-deploy')
        closure_path = temp_dir / f"{project_slug}-closure"

        if not closure_path.exists():
            logger.error(f"Closure not found at {closure_path}")
            logger.info(f"Build closure first: templedb deploy-nix build {project_slug}")
            return 1

        print(f"📤 Transferring closure to {target_user}@{target_host}...")

        result = self.nix_service.transfer_closure(
            closure_path,
            target_host,
            target_user
        )

        if result.success:
            print(f"✅ {result.message}")
            return 0
        else:
            print(f"❌ {result.message}")
            if result.error:
                print(f"\nError: {result.error}")
            return 1

    def import_closure(self, args) -> int:
        """Import Nix closure on target VPS"""
        project_slug = args.slug
        target_host = args.host
        target_user = args.user if hasattr(args, 'user') and args.user else 'deploy'

        print(f"📥 Importing closure on {target_host}...")

        closure_name = f"{project_slug}-closure"
        result = self.nix_service.import_closure(
            closure_name,
            target_host,
            target_user
        )

        if result.success:
            print(f"✅ {result.message}")
            return 0
        else:
            print(f"❌ {result.message}")
            if result.error:
                print(f"\nError: {result.error}")
            return 1

    def activate(self, args) -> int:
        """Activate systemd service on target"""
        project_slug = args.slug
        target_host = args.host
        target_user = args.user if hasattr(args, 'user') and args.user else 'deploy'
        port = args.port if hasattr(args, 'port') and args.port else 8000

        print(f"🚀 Activating service on {target_host}...")

        # Read metadata to get executable path
        temp_dir = Path('/tmp/templedb-deploy')
        closure_path = temp_dir / f"{project_slug}-closure"
        metadata_path = closure_path / "metadata.json"

        if not metadata_path.exists():
            logger.error(f"Metadata not found. Did you build and transfer the closure?")
            return 1

        import json
        with open(metadata_path) as f:
            metadata = json.load(f)

        executable_path = metadata['main_executable']

        # Get environment variables from TempleDB
        env_vars = self._get_env_vars(project_slug, target='production')

        # Generate systemd unit
        systemd_unit = self.nix_service.generate_systemd_unit(
            project_slug,
            executable_path,
            port,
            env_vars
        )

        # Activate
        result = self.nix_service.activate_service(
            project_slug,
            systemd_unit,
            target_host,
            target_user
        )

        if result.success:
            print(f"✅ {result.message}")
            print(f"\n📊 Service status:")
            print(f"  Check status: ssh {target_user}@{target_host} 'sudo systemctl status {project_slug}'")
            print(f"  View logs:    ssh {target_user}@{target_host} 'sudo journalctl -u {project_slug} -f'")
            return 0
        else:
            print(f"❌ {result.message}")
            if result.error:
                print(f"\nError: {result.error}")
            return 1

    def deploy_full(self, args) -> int:
        """
        Full deployment workflow: build → transfer → import → activate.

        This is the all-in-one command for production deployments.
        """
        project_slug = args.slug
        target_host = args.host
        target_user = args.user if hasattr(args, 'user') and args.user else 'deploy'
        port = args.port if hasattr(args, 'port') and args.port else 8000

        # Get project
        project = self.get_project_or_exit(project_slug)
        project_path = Path(project['git_path']) if project.get('git_path') else None

        if not project_path or not project_path.exists():
            logger.error(f"Project path not found: {project_path}")
            return 1

        print("=" * 70)
        print(f"🚀 TempleDB Nix Deployment - {project_slug}")
        print("=" * 70)
        print(f"\n📁 Project: {project_path}")
        print(f"🎯 Target:  {target_user}@{target_host}:{port}\n")

        # Get environment variables
        env_vars = self._get_env_vars(project_slug, target='production')

        # Run full deployment
        result = self.nix_service.full_deployment(
            project_path,
            project_slug,
            target_host,
            target_user,
            port,
            env_vars
        )

        if result.success:
            print("\n" + "=" * 70)
            print(f"✅ Deployment Complete!")
            print("=" * 70)
            print(f"\n🌐 Service URL: {result.service_url}")
            print(f"\n📊 Management Commands:")
            print(f"  Status:  ssh {target_user}@{target_host} 'sudo systemctl status {project_slug}'")
            print(f"  Logs:    ssh {target_user}@{target_host} 'sudo journalctl -u {project_slug} -f'")
            print(f"  Restart: ssh {target_user}@{target_host} 'sudo systemctl restart {project_slug}'")
            print(f"  Stop:    ssh {target_user}@{target_host} 'sudo systemctl stop {project_slug}'")

            if result.error:
                print(f"\n⚠️  Note: {result.error}")

            return 0
        else:
            print("\n" + "=" * 70)
            print(f"❌ Deployment Failed")
            print("=" * 70)
            print(f"\n{result.message}")
            if result.error:
                print(f"\nError details:\n{result.error}")
            return 1

    def health_check(self, args) -> int:
        """Run health check on deployed service"""
        target_host = args.host
        port = args.port if hasattr(args, 'port') and args.port else 8000
        endpoint = args.endpoint if hasattr(args, 'endpoint') and args.endpoint else '/health'

        print(f"🏥 Running health check on {target_host}:{port}{endpoint}...")

        success, message = self.nix_service.health_check(target_host, port, endpoint)

        if success:
            print(f"✅ {message}")
            return 0
        else:
            print(f"❌ {message}")
            return 1

    def _get_env_vars(self, project_slug: str, target: str = 'production') -> dict:
        """Get environment variables for project from TempleDB"""
        # Query environment variables
        rows = self.query_all("""
            SELECT ev.name, ev.value
            FROM env_vars ev
            JOIN project_env_vars pev ON ev.id = pev.env_var_id
            JOIN projects p ON pev.project_id = p.id
            WHERE p.slug = ?
              AND pev.profile = ?
        """, (project_slug, target))

        return {row['name']: row['value'] for row in rows}

    # ========================================================================
    # CLI Tool Packaging Commands
    # ========================================================================

    def generate_flake(self, args) -> int:
        """Generate Nix flake for CLI tool"""
        project_slug = args.slug

        # Get project
        project = self.get_project_or_exit(project_slug)
        project_path = Path(project['git_path']) if project.get('git_path') else None

        if not project_path or not project_path.exists():
            logger.error(f"Project path not found: {project_path}")
            return 1

        # Optional args
        description = args.description if hasattr(args, 'description') and args.description else None
        version = args.version if hasattr(args, 'version') and args.version else "1.0.0"

        print(f"📦 Generating Nix flake for CLI tool: {project_slug}")
        print(f"   Path: {project_path}\n")

        # Generate flake
        result = self.nix_service.generate_cli_flake(
            project_path,
            project_slug,
            description,
            version
        )

        if result.success:
            print(f"✅ {result.message}")
            print(f"\n📄 Flake location: {result.flake_path}")
            print(f"\n💡 Next steps:")
            print(f"   1. Review and customize flake.nix")
            print(f"   2. Test build: nix build {project_path}")
            print(f"   3. Test run: nix run {project_path}")
            print(f"   4. Install locally: templedb deploy-nix install {project_slug}")
            print(f"   5. Add to system config: templedb deploy-nix add-to-config {project_slug}")
            return 0
        else:
            print(f"❌ {result.message}")
            if result.error:
                print(f"\nError: {result.error}")
            return 1

    def install_local(self, args) -> int:
        """Install CLI tool to local Nix profile"""
        project_slug = args.slug

        # Get project
        project = self.get_project_or_exit(project_slug)
        project_path = Path(project['git_path']) if project.get('git_path') else None

        if not project_path or not project_path.exists():
            logger.error(f"Project path not found: {project_path}")
            return 1

        print(f"📥 Installing {project_slug} to local Nix profile...")
        print(f"   This will make '{project_slug}' available in your PATH\n")

        # Install
        result = self.nix_service.install_local(project_path, project_slug)

        if result.success:
            print(f"✅ {result.message}")
            print(f"\n🎉 Installation complete!")
            print(f"\n💡 You can now run: {project_slug}")
            print(f"\n📋 Manage installed packages:")
            print(f"   List:   nix profile list")
            print(f"   Remove: nix profile remove {project_slug}")
            return 0
        else:
            print(f"❌ {result.message}")
            if result.error:
                print(f"\nError: {result.error}")
            return 1

    def add_to_config(self, args) -> int:
        """Generate system configuration snippet for CLI tool"""
        project_slug = args.slug

        # Get project
        project = self.get_project_or_exit(project_slug)
        project_path = Path(project['git_path']) if project.get('git_path') else None

        if not project_path or not project_path.exists():
            logger.error(f"Project path not found: {project_path}")
            return 1

        print(f"⚙️  Generating NixOS/home-manager configuration snippet...")
        print(f"   Project: {project_slug}\n")

        # Generate config
        result = self.nix_service.add_to_system_config(
            project_path,
            project_slug
        )

        if result.success:
            print(f"✅ {result.message}")
            print(f"\n📄 Configuration snippet saved to: {result.flake_path}")
            print(f"\n💡 To add to your system:")
            print(f"   1. Copy the snippet from {result.flake_path}")
            print(f"   2. Add to your configuration.nix or home.nix")
            print(f"   3. Rebuild: sudo nixos-rebuild switch (or home-manager switch)")
            return 0
        else:
            print(f"❌ {result.message}")
            if result.error:
                print(f"\nError: {result.error}")
            return 1


def register_under_deploy(deploy_subparsers, cli):
    """Register as nested subcommand under 'deploy nix'"""
    cmd = NixDeployCommands()

    # deploy nix command group
    nix_parser = deploy_subparsers.add_parser('nix', help='Nix closure deployment backend')
    subparsers = nix_parser.add_subparsers(dest='deploy_nix_subcommand', required=True)

    _register_nix_commands(cmd, subparsers, cli, prefix='deploy.nix')


def _register_nix_commands(cmd, subparsers, cli, prefix='deploy.nix'):
    """Register Nix deployment subcommands (reusable for both nested and top-level)"""

    # build
    build_parser = subparsers.add_parser('build', help='Build Nix closure')
    build_parser.add_argument('slug', help='Project slug')
    cli.commands[f'{prefix}.build'] = cmd.build_closure

    # transfer
    transfer_parser = subparsers.add_parser('transfer', help='Transfer closure to target')
    transfer_parser.add_argument('slug', help='Project slug')
    transfer_parser.add_argument('--host', required=True, help='Target hostname')
    transfer_parser.add_argument('--user', default='deploy', help='SSH user (default: deploy)')
    cli.commands[f'{prefix}.transfer'] = cmd.transfer

    # import
    import_parser = subparsers.add_parser('import', help='Import closure on target')
    import_parser.add_argument('slug', help='Project slug')
    import_parser.add_argument('--host', required=True, help='Target hostname')
    import_parser.add_argument('--user', default='deploy', help='SSH user (default: deploy)')
    cli.commands[f'{prefix}.import'] = cmd.import_closure

    # activate
    activate_parser = subparsers.add_parser('activate', help='Activate systemd service')
    activate_parser.add_argument('slug', help='Project slug')
    activate_parser.add_argument('--host', required=True, help='Target hostname')
    activate_parser.add_argument('--user', default='deploy', help='SSH user (default: deploy)')
    activate_parser.add_argument('--port', type=int, default=8000, help='Service port (default: 8000)')
    cli.commands[f'{prefix}.activate'] = cmd.activate

    # run (full deployment)
    run_parser = subparsers.add_parser('run', help='Full deployment (build + transfer + import + activate)')
    run_parser.add_argument('slug', help='Project slug')
    run_parser.add_argument('--host', required=True, help='Target hostname')
    run_parser.add_argument('--user', default='deploy', help='SSH user (default: deploy)')
    run_parser.add_argument('--port', type=int, default=8000, help='Service port (default: 8000)')
    cli.commands[f'{prefix}.run'] = cmd.deploy_full

    # health
    health_parser = subparsers.add_parser('health', help='Run health check')
    health_parser.add_argument('--host', required=True, help='Target hostname')
    health_parser.add_argument('--port', type=int, default=8000, help='Service port (default: 8000)')
    health_parser.add_argument('--endpoint', default='/health', help='Health check endpoint (default: /health)')
    cli.commands[f'{prefix}.health'] = cmd.health_check

    # CLI Tool Packaging Commands
    # generate-flake
    generate_flake_parser = subparsers.add_parser('generate-flake', help='Generate Nix flake for CLI tool')
    generate_flake_parser.add_argument('slug', help='Project slug')
    generate_flake_parser.add_argument('--description', help='Project description')
    generate_flake_parser.add_argument('--version', default='1.0.0', help='Version string (default: 1.0.0)')
    cli.commands[f'{prefix}.generate-flake'] = cmd.generate_flake

    # install
    install_parser = subparsers.add_parser('install', help='Install CLI tool to local Nix profile')
    install_parser.add_argument('slug', help='Project slug')
    cli.commands[f'{prefix}.install'] = cmd.install_local

    # add-to-config
    add_config_parser = subparsers.add_parser('add-to-config', help='Generate NixOS/home-manager config snippet')
    add_config_parser.add_argument('slug', help='Project slug')
    cli.commands[f'{prefix}.add-to-config'] = cmd.add_to_config
