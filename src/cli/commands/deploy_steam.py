#!/usr/bin/env python3
"""
Steam Deployment Commands - Phase 3 Implementation

Commands for deploying games to Steam platform.
"""
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger
from services.deployment.steam_deployment_service import SteamDeploymentService

logger = get_logger(__name__)


class SteamDeployCommands(Command):
    """Steam deployment command handlers"""

    def __init__(self):
        super().__init__()
        self.steam_service = SteamDeploymentService(self.get_connection())

    def build_unity(self, args) -> int:
        """Build Unity game for specified platforms"""
        project_slug = args.slug

        # Get project
        project = self.get_project_or_exit(project_slug)
        project_path = Path(project['git_path']) if project.get('git_path') else None

        if not project_path or not project_path.exists():
            logger.error(f"Project path not found: {project_path}")
            return 1

        # Args
        build_targets = args.targets.split(',') if hasattr(args, 'targets') and args.targets else ["StandaloneWindows64"]
        development = hasattr(args, 'development') and args.development
        output_path = Path(args.output) if hasattr(args, 'output') and args.output else None

        print(f"🎮 Building Unity game: {project_slug}")
        print(f"   Targets: {', '.join(build_targets)}\n")

        success_count = 0
        for target in build_targets:
            print(f"🔨 Building for {target}...")
            result = self.steam_service.build_unity_game(
                project_path=project_path,
                build_target=target,
                output_path=output_path,
                development_build=development
            )

            if result.success:
                print(f"✅ {result.message}")
                print(f"   Build path: {result.build_path}\n")
                success_count += 1
            else:
                print(f"❌ {result.message}")
                if result.error:
                    print(f"   Error: {result.error}\n")

        if success_count == len(build_targets):
            print(f"🎉 All {success_count} builds completed successfully!")
            return 0
        elif success_count > 0:
            print(f"⚠️  {success_count}/{len(build_targets)} builds succeeded")
            return 1
        else:
            print(f"❌ All builds failed")
            return 1

    def build_godot(self, args) -> int:
        """Build Godot game using export presets"""
        project_slug = args.slug

        # Get project
        project = self.get_project_or_exit(project_slug)
        project_path = Path(project['git_path']) if project.get('git_path') else None

        if not project_path or not project_path.exists():
            logger.error(f"Project path not found: {project_path}")
            return 1

        # Args
        export_presets = args.presets.split(',') if hasattr(args, 'presets') and args.presets else ["Linux/X11"]
        output_path = Path(args.output) if hasattr(args, 'output') and args.output else None

        print(f"🎮 Building Godot game: {project_slug}")
        print(f"   Presets: {', '.join(export_presets)}\n")

        success_count = 0
        for preset in export_presets:
            print(f"🔨 Exporting {preset}...")
            result = self.steam_service.build_godot_game(
                project_path=project_path,
                export_preset=preset,
                output_path=output_path
            )

            if result.success:
                print(f"✅ {result.message}")
                print(f"   Build path: {result.build_path}\n")
                success_count += 1
            else:
                print(f"❌ {result.message}")
                if result.error:
                    print(f"   Error: {result.error}\n")

        if success_count == len(export_presets):
            print(f"🎉 All {success_count} exports completed successfully!")
            return 0
        elif success_count > 0:
            print(f"⚠️  {success_count}/{len(export_presets)} exports succeeded")
            return 1
        else:
            print(f"❌ All exports failed")
            return 1

    def package_html5(self, args) -> int:
        """Package HTML5 game for Steam"""
        project_slug = args.slug

        # Get project
        project = self.get_project_or_exit(project_slug)
        project_path = Path(project['git_path']) if project.get('git_path') else None

        if not project_path or not project_path.exists():
            logger.error(f"Project path not found: {project_path}")
            return 1

        # Args
        game_name = args.name if hasattr(args, 'name') and args.name else project.get('name', project_slug)
        output_path = Path(args.output) if hasattr(args, 'output') and args.output else None

        print(f"🌐 Packaging HTML5 game: {project_slug}\n")

        result = self.steam_service.package_html5_game(
            project_path=project_path,
            game_name=game_name,
            output_path=output_path
        )

        if result.success:
            print(f"✅ {result.message}")
            print(f"   Package path: {result.build_path}")
            print(f"\n💡 Next steps:")
            print(f"   1. Upload to Steam using deploy-steam upload")
            print(f"   2. Configure Steam to launch launch_steam.sh")
            return 0
        else:
            print(f"❌ {result.message}")
            if result.error:
                print(f"   Error: {result.error}")
            return 1

    def install_steamworks(self, args) -> int:
        """Install Steamworks.NET for Unity project"""
        project_slug = args.slug

        # Get project
        project = self.get_project_or_exit(project_slug)
        project_path = Path(project['git_path']) if project.get('git_path') else None

        if not project_path or not project_path.exists():
            logger.error(f"Project path not found: {project_path}")
            return 1

        # Args
        version = args.version if hasattr(args, 'version') and args.version else "20.2.0"

        print(f"📦 Installing Steamworks.NET {version} for {project_slug}...\n")

        result = self.steam_service.install_steamworks_net(
            project_path=project_path,
            steamworks_net_version=version
        )

        if result.success:
            print(f"✅ {result.message}")
            print(f"\n💡 Next steps:")
            print(f"   1. Open Unity project")
            print(f"   2. Wait for package resolution")
            print(f"   3. Configure Steam App ID in SteamManager")
            return 0
        else:
            print(f"❌ {result.message}")
            if result.error:
                print(f"   Error: {result.error}")
            return 1

    def install_godot_steam(self, args) -> int:
        """Install GodotSteam plugin for Godot project"""
        project_slug = args.slug

        # Get project
        project = self.get_project_or_exit(project_slug)
        project_path = Path(project['git_path']) if project.get('git_path') else None

        if not project_path or not project_path.exists():
            logger.error(f"Project path not found: {project_path}")
            return 1

        # Args
        version = args.version if hasattr(args, 'version') and args.version else "latest"

        print(f"📦 Installing GodotSteam {version} for {project_slug}...\n")

        result = self.steam_service.install_godot_steam(
            project_path=project_path,
            godot_steam_version=version
        )

        if result.success:
            print(f"✅ {result.message}")
            print(f"\n💡 Next steps:")
            print(f"   1. Download GodotSteam binaries from GitHub")
            print(f"   2. Place in addons/godotsteam/")
            print(f"   3. Enable plugin in Project Settings")
            print(f"   4. Configure Steam App ID")
            return 0
        else:
            print(f"❌ {result.message}")
            if result.error:
                print(f"   Error: {result.error}")
            return 1

    def upload_to_steam(self, args) -> int:
        """Upload game build to Steam"""
        project_slug = args.slug

        # Get project
        project = self.get_project_or_exit(project_slug)

        # Required args
        app_id = args.app_id if hasattr(args, 'app_id') and args.app_id else None
        depot_id = args.depot_id if hasattr(args, 'depot_id') and args.depot_id else None
        build_path = Path(args.build_path) if hasattr(args, 'build_path') and args.build_path else None
        steam_username = args.username if hasattr(args, 'username') and args.username else None

        if not all([app_id, depot_id, build_path, steam_username]):
            logger.error("Missing required arguments: --app-id, --depot-id, --build-path, --username")
            return 1

        if not build_path.exists():
            logger.error(f"Build path not found: {build_path}")
            return 1

        # Optional
        steam_password = args.password if hasattr(args, 'password') and args.password else None
        description = args.description if hasattr(args, 'description') and args.description else "Build from TempleDB"

        print(f"🚀 Uploading {project_slug} to Steam")
        print(f"   App ID: {app_id}")
        print(f"   Depot ID: {depot_id}")
        print(f"   Build path: {build_path}\n")

        # Generate VDF config
        vdf_dir = Path("/tmp/templedb-steam") / f"config-{app_id}"
        vdf_dir.mkdir(parents=True, exist_ok=True)

        print("📝 Generating Steam configuration files...")
        app_vdf = self.steam_service.generate_app_build_vdf(
            app_id=app_id,
            depot_id=depot_id,
            content_root=build_path,
            output_path=vdf_dir,
            build_description=description
        )
        print(f"   Created: {app_vdf}")

        depot_vdf = self.steam_service.generate_depot_build_vdf(
            depot_id=depot_id,
            content_root=build_path,
            output_path=vdf_dir
        )
        print(f"   Created: {depot_vdf}\n")

        # Upload
        print("☁️  Uploading to Steam...")
        result = self.steam_service.upload_to_steam(
            app_build_vdf=app_vdf,
            steam_username=steam_username,
            steam_password=steam_password
        )

        if result.success:
            print(f"✅ {result.message}")
            print(f"\n🎉 Build uploaded to Steam!")
            print(f"\n💡 Next steps:")
            print(f"   1. Log into Steamworks")
            print(f"   2. Set build live for testing")
            print(f"   3. Configure store page")
            return 0
        else:
            print(f"❌ {result.message}")
            if result.error:
                print(f"   Error: {result.error}")
            return 1

    def deploy_unity(self, args) -> int:
        """Complete Unity to Steam deployment workflow"""
        project_slug = args.slug

        # Get project
        project = self.get_project_or_exit(project_slug)
        project_path = Path(project['git_path']) if project.get('git_path') else None

        if not project_path or not project_path.exists():
            logger.error(f"Project path not found: {project_path}")
            return 1

        # Required args
        app_id = args.app_id if hasattr(args, 'app_id') and args.app_id else None
        depot_id = args.depot_id if hasattr(args, 'depot_id') and args.depot_id else None
        steam_username = args.username if hasattr(args, 'username') and args.username else None

        if not all([app_id, depot_id, steam_username]):
            logger.error("Missing required arguments: --app-id, --depot-id, --username")
            return 1

        # Optional
        build_targets = args.targets.split(',') if hasattr(args, 'targets') and args.targets else ["StandaloneWindows64"]
        steam_password = args.password if hasattr(args, 'password') and args.password else None

        print(f"🎮 Complete Unity → Steam deployment: {project_slug}")
        print(f"   Targets: {', '.join(build_targets)}")
        print(f"   App ID: {app_id}")
        print(f"   Depot ID: {depot_id}\n")

        # Deploy
        results = self.steam_service.deploy_unity_to_steam(
            project_path=project_path,
            app_id=app_id,
            depot_id=depot_id,
            build_targets=build_targets,
            steam_username=steam_username,
            steam_password=steam_password
        )

        # Report
        success_count = sum(1 for r in results if r.success)
        for i, result in enumerate(results):
            target = build_targets[i] if i < len(build_targets) else f"Build {i+1}"
            if result.success:
                print(f"✅ {target}: {result.message}")
            else:
                print(f"❌ {target}: {result.message}")
                if result.error:
                    print(f"   Error: {result.error}")

        if success_count == len(results):
            print(f"\n🎉 All {success_count} deployments successful!")
            return 0
        elif success_count > 0:
            print(f"\n⚠️  {success_count}/{len(results)} deployments succeeded")
            return 1
        else:
            print(f"\n❌ All deployments failed")
            return 1

    def deploy_godot(self, args) -> int:
        """Complete Godot to Steam deployment workflow"""
        project_slug = args.slug

        # Get project
        project = self.get_project_or_exit(project_slug)
        project_path = Path(project['git_path']) if project.get('git_path') else None

        if not project_path or not project_path.exists():
            logger.error(f"Project path not found: {project_path}")
            return 1

        # Required args
        app_id = args.app_id if hasattr(args, 'app_id') and args.app_id else None
        depot_id = args.depot_id if hasattr(args, 'depot_id') and args.depot_id else None
        steam_username = args.username if hasattr(args, 'username') and args.username else None

        if not all([app_id, depot_id, steam_username]):
            logger.error("Missing required arguments: --app-id, --depot-id, --username")
            return 1

        # Optional
        export_presets = args.presets.split(',') if hasattr(args, 'presets') and args.presets else ["Linux/X11"]
        steam_password = args.password if hasattr(args, 'password') and args.password else None

        print(f"🎮 Complete Godot → Steam deployment: {project_slug}")
        print(f"   Presets: {', '.join(export_presets)}")
        print(f"   App ID: {app_id}")
        print(f"   Depot ID: {depot_id}\n")

        # Deploy
        results = self.steam_service.deploy_godot_to_steam(
            project_path=project_path,
            app_id=app_id,
            depot_id=depot_id,
            export_presets=export_presets,
            steam_username=steam_username,
            steam_password=steam_password
        )

        # Report
        success_count = sum(1 for r in results if r.success)
        for i, result in enumerate(results):
            preset = export_presets[i] if i < len(export_presets) else f"Build {i+1}"
            if result.success:
                print(f"✅ {preset}: {result.message}")
            else:
                print(f"❌ {preset}: {result.message}")
                if result.error:
                    print(f"   Error: {result.error}")

        if success_count == len(results):
            print(f"\n🎉 All {success_count} deployments successful!")
            return 0
        elif success_count > 0:
            print(f"\n⚠️  {success_count}/{len(results)} deployments succeeded")
            return 1
        else:
            print(f"\n❌ All deployments failed")
            return 1


def register(cli):
    """Register Steam deployment commands with CLI"""
    cmd = SteamDeployCommands()

    # deploy-steam command group
    deploy_steam_parser = cli.register_command(
        'deploy-steam',
        None,
        help_text='Deploy games to Steam platform (Phase 3)'
    )
    subparsers = deploy_steam_parser.add_subparsers(dest='deploy_steam_subcommand', required=True)

    # deploy-steam build-unity
    build_unity_parser = subparsers.add_parser('build-unity', help='Build Unity game')
    build_unity_parser.add_argument('slug', help='Project slug')
    build_unity_parser.add_argument('--targets', default='StandaloneWindows64',
                                    help='Comma-separated build targets (StandaloneWindows64,StandaloneOSX,StandaloneLinux64)')
    build_unity_parser.add_argument('--output', help='Output directory')
    build_unity_parser.add_argument('--development', action='store_true', help='Development build')
    cli.commands['deploy-steam.build-unity'] = cmd.build_unity

    # deploy-steam build-godot
    build_godot_parser = subparsers.add_parser('build-godot', help='Build Godot game')
    build_godot_parser.add_argument('slug', help='Project slug')
    build_godot_parser.add_argument('--presets', default='Linux/X11',
                                    help='Comma-separated export presets (Windows Desktop,Linux/X11,macOS)')
    build_godot_parser.add_argument('--output', help='Output directory')
    cli.commands['deploy-steam.build-godot'] = cmd.build_godot

    # deploy-steam package-html5
    package_html5_parser = subparsers.add_parser('package-html5', help='Package HTML5 game')
    package_html5_parser.add_argument('slug', help='Project slug')
    package_html5_parser.add_argument('--name', help='Game name')
    package_html5_parser.add_argument('--output', help='Output directory')
    cli.commands['deploy-steam.package-html5'] = cmd.package_html5

    # deploy-steam install-steamworks
    install_steamworks_parser = subparsers.add_parser('install-steamworks', help='Install Steamworks.NET for Unity')
    install_steamworks_parser.add_argument('slug', help='Project slug')
    install_steamworks_parser.add_argument('--version', default='20.2.0', help='Steamworks.NET version')
    cli.commands['deploy-steam.install-steamworks'] = cmd.install_steamworks

    # deploy-steam install-godotsteam
    install_godotsteam_parser = subparsers.add_parser('install-godotsteam', help='Install GodotSteam plugin')
    install_godotsteam_parser.add_argument('slug', help='Project slug')
    install_godotsteam_parser.add_argument('--version', default='latest', help='GodotSteam version')
    cli.commands['deploy-steam.install-godotsteam'] = cmd.install_godot_steam

    # deploy-steam upload
    upload_parser = subparsers.add_parser('upload', help='Upload build to Steam')
    upload_parser.add_argument('slug', help='Project slug')
    upload_parser.add_argument('--app-id', required=True, help='Steam App ID')
    upload_parser.add_argument('--depot-id', required=True, help='Steam Depot ID')
    upload_parser.add_argument('--build-path', required=True, help='Path to build directory')
    upload_parser.add_argument('--username', required=True, help='Steam username')
    upload_parser.add_argument('--password', help='Steam password (optional, can use cached)')
    upload_parser.add_argument('--description', help='Build description')
    cli.commands['deploy-steam.upload'] = cmd.upload_to_steam

    # deploy-steam deploy-unity
    deploy_unity_parser = subparsers.add_parser('deploy-unity', help='Complete Unity → Steam workflow')
    deploy_unity_parser.add_argument('slug', help='Project slug')
    deploy_unity_parser.add_argument('--app-id', required=True, help='Steam App ID')
    deploy_unity_parser.add_argument('--depot-id', required=True, help='Steam Depot ID')
    deploy_unity_parser.add_argument('--username', required=True, help='Steam username')
    deploy_unity_parser.add_argument('--password', help='Steam password')
    deploy_unity_parser.add_argument('--targets', default='StandaloneWindows64',
                                     help='Comma-separated build targets')
    cli.commands['deploy-steam.deploy-unity'] = cmd.deploy_unity

    # deploy-steam deploy-godot
    deploy_godot_parser = subparsers.add_parser('deploy-godot', help='Complete Godot → Steam workflow')
    deploy_godot_parser.add_argument('slug', help='Project slug')
    deploy_godot_parser.add_argument('--app-id', required=True, help='Steam App ID')
    deploy_godot_parser.add_argument('--depot-id', required=True, help='Steam Depot ID')
    deploy_godot_parser.add_argument('--username', required=True, help='Steam username')
    deploy_godot_parser.add_argument('--password', help='Steam password')
    deploy_godot_parser.add_argument('--presets', default='Linux/X11',
                                     help='Comma-separated export presets')
    cli.commands['deploy-steam.deploy-godot'] = cmd.deploy_godot
