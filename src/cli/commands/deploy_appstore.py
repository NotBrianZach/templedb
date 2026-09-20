#!/usr/bin/env python3
"""
App Store Deployment Commands - Phase 2 Implementation

Commands for deploying CLI tools to app stores and package managers.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger
from services.deployment.appstore_deployment_service import AppStoreDeploymentService

logger = get_logger(__name__)


class AppStoreDeployCommands(Command):
    """App store deployment command handlers"""

    def __init__(self):
        super().__init__()
        self.appstore_service = AppStoreDeploymentService(self.get_connection())

    def homebrew(self, args) -> int:
        """Generate Homebrew formula and optionally publish to tap"""
        project_slug = args.slug

        # Get project
        project = self.get_project_or_exit(project_slug)

        # Required args
        version = args.version if hasattr(args, 'version') and args.version else "1.0.0"
        description = args.description if hasattr(args, 'description') and args.description else project.get('name', project_slug)
        homepage = args.homepage if hasattr(args, 'homepage') and args.homepage else f"https://github.com/{args.org}/{project_slug}"
        tarball_url = args.tarball_url if hasattr(args, 'tarball_url') and args.tarball_url else ""
        tarball_sha256 = args.sha256 if hasattr(args, 'sha256') and args.sha256 else ""

        # Optional
        tap_org = args.org if hasattr(args, 'org') and args.org else "yourorg"
        tap_repo = args.tap if hasattr(args, 'tap') and args.tap else "homebrew-tap"
        publish = hasattr(args, 'publish') and args.publish

        print(f"🍺 Generating Homebrew formula for {project_slug}...\n")

        # Generate formula
        formula = self.appstore_service.generate_homebrew_formula(
            project_slug=project_slug,
            project_name=project.get('name', project_slug),
            description=description,
            homepage=homepage,
            version=version,
            tarball_url=tarball_url,
            tarball_sha256=tarball_sha256
        )

        # Create tap structure
        result = self.appstore_service.create_homebrew_tap(
            project_slug=project_slug,
            formula=formula,
            tap_org=tap_org,
            tap_repo=tap_repo
        )

        if result.success:
            print(f"✅ {result.message}")
            print(f"\n📦 Tap location: {result.package_path}")
            print(f"\n📋 Formula preview:")
            print("=" * 70)
            print(formula)
            print("=" * 70)

            if publish:
                print(f"\n🚀 Publishing to GitHub...")
                publish_result = self.appstore_service.publish_homebrew_tap(
                    tap_dir=result.package_path,
                    tap_org=tap_org,
                    tap_repo=tap_repo
                )

                if publish_result.success:
                    print(f"✅ {publish_result.message}")
                    print(f"\n🌐 Tap URL: {publish_result.formula_url}")
                    print(f"\n📥 Users can install via:")
                    print(f"   brew tap {tap_org}/{tap_repo}")
                    print(f"   brew install {project_slug}")
                else:
                    print(f"❌ Publish failed: {publish_result.message}")
                    if publish_result.error:
                        print(f"\nError: {publish_result.error}")
                    return 1
            else:
                print(f"\n💡 Next steps:")
                print(f"   1. Review the formula")
                print(f"   2. Create GitHub repo: gh repo create {tap_org}/{tap_repo}")
                print(f"   3. Push: cd {result.package_path} && git init && git add . && git commit -m 'Initial commit' && git push")
                print(f"\n   Or use --publish flag to publish automatically")

            return 0
        else:
            print(f"❌ {result.message}")
            if result.error:
                print(f"\nError: {result.error}")
            return 1

    def snap(self, args) -> int:
        """Generate Snap package and optionally publish"""
        project_slug = args.slug

        # Get project
        project = self.get_project_or_exit(project_slug)
        project_path = Path(project['git_path']) if project.get('git_path') else None

        if not project_path or not project_path.exists():
            logger.error(f"Project path not found: {project_path}")
            return 1

        # Args
        version = args.version if hasattr(args, 'version') and args.version else "1.0.0"
        summary = args.summary if hasattr(args, 'summary') and args.summary else project.get('name', project_slug)
        description = args.description if hasattr(args, 'description') and args.description else summary
        publish = hasattr(args, 'publish') and args.publish

        print(f"📦 Building Snap package for {project_slug}...\n")

        # Generate snapcraft.yaml
        snapcraft_yaml = self.appstore_service.generate_snapcraft_yaml(
            project_slug=project_slug,
            project_name=project.get('name', project_slug),
            version=version,
            summary=summary[:79],  # Max 79 chars
            description=description
        )

        print("📋 snapcraft.yaml:")
        print("=" * 70)
        print(snapcraft_yaml)
        print("=" * 70)

        # Build snap
        print(f"\n🔨 Building Snap...")
        result = self.appstore_service.build_snap(
            project_path=project_path,
            snapcraft_yaml=snapcraft_yaml
        )

        if result.success:
            print(f"✅ {result.message}")
            print(f"\n📦 Snap package: {result.package_path}")

            if publish:
                print(f"\n🚀 Publishing to Snap Store...")
                channel = args.channel if hasattr(args, 'channel') and args.channel else "stable"

                publish_result = self.appstore_service.publish_snap(
                    snap_file=result.package_path,
                    channel=channel
                )

                if publish_result.success:
                    print(f"✅ {publish_result.message}")
                    print(f"\n🌐 Store URL: {publish_result.store_url}")
                    print(f"\n📥 Users can install via:")
                    print(f"   snap install {project_slug}")
                else:
                    print(f"❌ Publish failed: {publish_result.message}")
                    if publish_result.error:
                        print(f"\nError: {publish_result.error}")
                    return 1
            else:
                print(f"\n💡 To publish:")
                print(f"   snapcraft login")
                print(f"   snapcraft upload --release=stable {result.package_path}")
                print(f"\n   Or use --publish flag")

            return 0
        else:
            print(f"❌ {result.message}")
            if result.error:
                print(f"\nError: {result.error}")
            return 1

    def macos_app(self, args) -> int:
        """Create macOS .app bundle with code signing and notarization"""
        project_slug = args.slug

        # Get project
        project = self.get_project_or_exit(project_slug)
        executable_path = Path(args.executable) if hasattr(args, 'executable') and args.executable else None

        if not executable_path or not executable_path.exists():
            logger.error(f"Executable not found: {executable_path}")
            logger.info("Build the executable first, then provide --executable path")
            return 1

        # Args
        version = args.version if hasattr(args, 'version') and args.version else "1.0.0"
        project_name = args.name if hasattr(args, 'name') and args.name else project.get('name', project_slug)
        icon_path = Path(args.icon) if hasattr(args, 'icon') and args.icon else None
        bundle_id = args.bundle_id if hasattr(args, 'bundle_id') and args.bundle_id else None

        print(f"🍎 Creating macOS app bundle for {project_slug}...\n")

        # Create .app bundle
        result = self.appstore_service.create_macos_app_bundle(
            project_slug=project_slug,
            project_name=project_name,
            version=version,
            executable_path=executable_path,
            icon_path=icon_path,
            bundle_identifier=bundle_id
        )

        if result.success:
            print(f"✅ {result.message}")
            print(f"\n📦 App bundle: {result.package_path}")

            # Code signing (if requested)
            if hasattr(args, 'sign') and args.sign:
                signing_identity = args.signing_identity if hasattr(args, 'signing_identity') and args.signing_identity else None
                if not signing_identity:
                    logger.error("--signing-identity required for code signing")
                    return 1

                print(f"\n✍️  Signing app bundle...")
                sign_result = self.appstore_service.sign_macos_app(
                    app_bundle=result.package_path,
                    signing_identity=signing_identity
                )

                if not sign_result.success:
                    print(f"❌ Signing failed: {sign_result.message}")
                    return 1

                print(f"✅ {sign_result.message}")

                # Notarization (if requested)
                if hasattr(args, 'notarize') and args.notarize:
                    apple_id = args.apple_id if hasattr(args, 'apple_id') and args.apple_id else None
                    team_id = args.team_id if hasattr(args, 'team_id') and args.team_id else None
                    password = args.password if hasattr(args, 'password') and args.password else None

                    if not all([apple_id, team_id, password]):
                        logger.error("--apple-id, --team-id, and --password required for notarization")
                        return 1

                    print(f"\n📝 Notarizing app...")
                    notarize_result = self.appstore_service.notarize_macos_app(
                        app_bundle=result.package_path,
                        apple_id=apple_id,
                        team_id=team_id,
                        password=password
                    )

                    if not notarize_result.success:
                        print(f"❌ Notarization failed: {notarize_result.message}")
                        return 1

                    print(f"✅ {notarize_result.message}")

            print(f"\n💡 Next steps:")
            if not hasattr(args, 'sign') or not args.sign:
                print(f"   1. Sign: templedb deploy-appstore macos {project_slug} --sign --signing-identity 'Developer ID'")
            if not hasattr(args, 'notarize') or not args.notarize:
                print(f"   2. Notarize: Add --notarize --apple-id ... --team-id ... --password ...")
            print(f"   3. Distribute .app bundle or create installer")

            return 0
        else:
            print(f"❌ {result.message}")
            if result.error:
                print(f"\nError: {result.error}")
            return 1


def register(cli):
    """Register app store deployment commands with CLI"""
    cmd = AppStoreDeployCommands()

    # deploy-appstore command group
    deploy_appstore_parser = cli.register_command(
        'deploy-appstore',
        None,
        help_text='Deploy CLI tools to app stores and package managers (Phase 2)'
    )
    subparsers = deploy_appstore_parser.add_subparsers(dest='deploy_appstore_subcommand', required=True)

    # deploy-appstore homebrew
    homebrew_parser = subparsers.add_parser('homebrew', help='Generate Homebrew formula')
    homebrew_parser.add_argument('slug', help='Project slug')
    homebrew_parser.add_argument('--version', default='1.0.0', help='Version string')
    homebrew_parser.add_argument('--description', help='Project description')
    homebrew_parser.add_argument('--homepage', help='Project homepage URL')
    homebrew_parser.add_argument('--tarball-url', help='Source tarball URL')
    homebrew_parser.add_argument('--sha256', help='Tarball SHA256 hash')
    homebrew_parser.add_argument('--org', default='yourorg', help='GitHub organization')
    homebrew_parser.add_argument('--tap', default='homebrew-tap', help='Tap repository name')
    homebrew_parser.add_argument('--publish', action='store_true', help='Publish to GitHub')
    cli.commands['deploy-appstore.homebrew'] = cmd.homebrew

    # deploy-appstore snap
    snap_parser = subparsers.add_parser('snap', help='Build Snap package')
    snap_parser.add_argument('slug', help='Project slug')
    snap_parser.add_argument('--version', default='1.0.0', help='Version string')
    snap_parser.add_argument('--summary', help='Short summary (max 79 chars)')
    snap_parser.add_argument('--description', help='Long description')
    snap_parser.add_argument('--publish', action='store_true', help='Publish to Snap Store')
    snap_parser.add_argument('--channel', default='stable', help='Release channel (stable, candidate, beta, edge)')
    cli.commands['deploy-appstore.snap'] = cmd.snap

    # deploy-appstore macos
    macos_parser = subparsers.add_parser('macos', help='Create macOS .app bundle')
    macos_parser.add_argument('slug', help='Project slug')
    macos_parser.add_argument('--executable', required=True, help='Path to executable')
    macos_parser.add_argument('--version', default='1.0.0', help='Version string')
    macos_parser.add_argument('--name', help='Display name')
    macos_parser.add_argument('--icon', help='Path to .icns icon file')
    macos_parser.add_argument('--bundle-id', help='Bundle identifier (e.g., com.yourcompany.app)')
    macos_parser.add_argument('--sign', action='store_true', help='Code sign the app')
    macos_parser.add_argument('--signing-identity', help='Signing identity (e.g., "Developer ID Application: Your Name")')
    macos_parser.add_argument('--notarize', action='store_true', help='Notarize with Apple')
    macos_parser.add_argument('--apple-id', help='Apple ID email')
    macos_parser.add_argument('--team-id', help='Team ID')
    macos_parser.add_argument('--password', help='App-specific password')
    cli.commands['deploy-appstore.macos'] = cmd.macos_app


def register_under_deploy(deploy_subparsers, cli):
    """Register app store deployment under deploy command (deploy appstore ...)"""
    cmd = AppStoreDeployCommands()

    # Create appstore subcommand under deploy
    appstore_parser = deploy_subparsers.add_parser(
        'appstore',
        help='Deploy CLI tools to app stores and package managers',
        description='Generate and publish packages for Homebrew, Snap, macOS App Store, and Windows Store.'
    )
    appstore_subparsers = appstore_parser.add_subparsers(dest='appstore_action', required=True)

    # deploy appstore homebrew
    homebrew_parser = appstore_subparsers.add_parser('homebrew', help='Generate Homebrew formula')
    homebrew_parser.add_argument('slug', help='Project slug')
    homebrew_parser.add_argument('--version', default='1.0.0', help='Version string')
    homebrew_parser.add_argument('--description', help='Project description')
    homebrew_parser.add_argument('--homepage', help='Project homepage URL')
    homebrew_parser.add_argument('--tarball-url', help='Source tarball URL')
    homebrew_parser.add_argument('--sha256', help='Tarball SHA256 hash')
    homebrew_parser.add_argument('--org', default='yourorg', help='GitHub organization')
    homebrew_parser.add_argument('--tap', default='homebrew-tap', help='Tap repository name')
    homebrew_parser.add_argument('--publish', action='store_true', help='Publish to GitHub')
    cli.commands['deploy.appstore.homebrew'] = cmd.homebrew

    # deploy appstore snap
    snap_parser = appstore_subparsers.add_parser('snap', help='Build Snap package')
    snap_parser.add_argument('slug', help='Project slug')
    snap_parser.add_argument('--version', default='1.0.0', help='Version string')
    snap_parser.add_argument('--summary', help='Short summary (max 79 chars)')
    snap_parser.add_argument('--description', help='Long description')
    snap_parser.add_argument('--publish', action='store_true', help='Publish to Snap Store')
    snap_parser.add_argument('--channel', default='stable', help='Release channel')
    cli.commands['deploy.appstore.snap'] = cmd.snap

    # TODO: Add macOS and Windows deployment when implemented
    # macos_parser = appstore_subparsers.add_parser('macos', help='Create macOS .app bundle')
    # windows_parser = appstore_subparsers.add_parser('windows', help='Create Windows installer')
