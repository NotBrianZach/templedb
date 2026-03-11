#!/usr/bin/env python3
"""
NixOS integration commands for TempleDB
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class NixOSCommand(Command):
    """NixOS integration command handlers"""

    def __init__(self):
        super().__init__()

    def generate(self, args) -> int:
        """Generate NixOS modules from a project"""
        try:
            from nixos_generator import NixOSGenerator

            project_slug = args.slug
            output_dir = Path(args.output) if args.output else Path('/tmp/nixos-gen')
            output_dir.mkdir(parents=True, exist_ok=True)

            print(f"\n🔧 Generating NixOS configuration for {project_slug}...")
            print(f"   Output: {output_dir}\n")

            with NixOSGenerator() as gen:
                config = gen.generate_config(
                    project_slug,
                    cathedral_path=args.cathedral_path,
                    include_home_manager=not args.no_home_manager,
                    include_templedb=args.include_templedb
                )

                # Write NixOS module
                nixos_path = output_dir / f"{project_slug}-nixos.nix"
                nixos_module = gen.generate_nix_module(config)
                nixos_path.write_text(nixos_module)
                print(f"✓ NixOS module: {nixos_path}")

                # Write Home Manager module
                if not args.no_home_manager:
                    hm_path = output_dir / f"{project_slug}-home.nix"
                    hm_module = gen.generate_home_manager_module(config)
                    hm_path.write_text(hm_module)
                    print(f"✓ Home Manager module: {hm_path}")

                # Show summary
                print(f"\n📊 Configuration Summary:")
                print(f"   System packages: {len(config.system_packages)}")
                print(f"   Home packages: {len(config.home_packages)}")
                print(f"   Environment vars: {len(config.environment_vars)}")
                print(f"   Secrets: {len(config.secrets)}")

                print(f"\n💡 Next steps:")
                print(f"   1. Review generated modules in {output_dir}")
                print(f"   2. Copy to /etc/nixos/")
                print(f"   3. Import in your flake.nix")
                print(f"   4. Run: sudo nixos-rebuild test")

            return 0

        except Exception as e:
            logger.error(f"Failed to generate NixOS config: {e}", exc_info=True)
            return 1

    def export(self, args) -> int:
        """Export Cathedral package with NixOS modules"""
        try:
            from nixos_generator import NixOSGenerator

            project_slug = args.slug
            output_dir = Path(args.output) if args.output else Path('/tmp/nixos-gen')

            print(f"\n📦 Exporting {project_slug} with NixOS integration...")
            print(f"   Output: {output_dir}\n")

            with NixOSGenerator() as gen:
                nixos_path, hm_path = gen.export_cathedral_with_nix(
                    project_slug,
                    output_dir
                )

                print(f"\n✅ Export complete!")
                print(f"\n📁 Generated files:")
                print(f"   - Cathedral package: {project_slug}.cathedral.tar.zst")
                print(f"   - NixOS module: {nixos_path.name}")
                print(f"   - Home Manager module: {hm_path.name}")
                print(f"   - Integration guide: {project_slug}-INTEGRATION.md")

                print(f"\n💡 Read the integration guide:")
                print(f"   cat {output_dir}/{project_slug}-INTEGRATION.md")

            return 0

        except Exception as e:
            logger.error(f"Failed to export: {e}", exc_info=True)
            return 1

    def detect(self, args) -> int:
        """Detect dependencies and show what would be generated"""
        try:
            from nixos_generator import NixOSGenerator

            project_slug = args.slug

            print(f"\n🔍 Analyzing {project_slug}...\n")

            with NixOSGenerator() as gen:
                # Get file types
                file_types = gen.get_project_file_types(project_slug)

                print(f"📊 File Type Distribution:")
                for ftype, count in sorted(file_types.items(), key=lambda x: x[1], reverse=True)[:10]:
                    print(f"   {ftype}: {count} files")

                # Detect packages
                packages = gen.detect_system_packages(file_types)

                print(f"\n📦 Detected Packages ({len(packages)}):")
                for pkg in sorted(packages):
                    print(f"   - {pkg}")

                # Get environment variables
                env_vars = gen.get_project_env_vars(project_slug)

                print(f"\n🔐 Environment Variables ({len(env_vars)}):")
                for key, value in list(env_vars.items())[:5]:
                    display_value = value[:40] + '...' if len(value) > 40 else value
                    print(f"   {key} = {display_value}")
                if len(env_vars) > 5:
                    print(f"   ... and {len(env_vars) - 5} more")

                # Get secrets
                secrets = gen.get_project_secrets(project_slug)

                print(f"\n🔑 Secrets ({len(secrets)}):")
                for secret in secrets[:5]:
                    print(f"   - {secret['key_name']} ({secret.get('profile', 'default')})")
                if len(secrets) > 5:
                    print(f"   ... and {len(secrets) - 5} more")

                print(f"\n💡 To generate NixOS modules:")
                print(f"   ./templedb nixos generate {project_slug}")
                print(f"\n💡 To export with Cathedral package:")
                print(f"   ./templedb nixos export {project_slug}")

            return 0

        except Exception as e:
            logger.error(f"Failed to detect dependencies: {e}", exc_info=True)
            return 1

    def system_test(self, args) -> int:
        """Test system configuration (nixos-rebuild test)"""
        try:
            from services.system_service import SystemService, SystemServiceError

            service = SystemService()
            print(f"🔧 Testing system configuration: {args.slug}")

            if args.dry_run:
                print("⚠️  DRY RUN MODE - No changes will be made")

            result = service.test_system(args.slug, dry_run=args.dry_run)

            if result['success']:
                print("\n✅ Test successful!")
                if result.get('nixos_generation'):
                    print(f"   NixOS generation: {result['nixos_generation']}")
                print("\n💡 To apply permanently: ./templedb nixos system-switch {args.slug}")
            else:
                print(f"\n❌ Test failed (exit code {result['exit_code']})")

            if result['stdout']:
                print("\n📋 Output:")
                print(result['stdout'])

            if result['stderr']:
                print("\n⚠️  Errors/Warnings:")
                print(result['stderr'])

            return 0 if result['success'] else 1

        except Exception as e:
            logger.error(f"Failed to test system: {e}", exc_info=True)
            return 1

    def system_switch(self, args) -> int:
        """Switch to system configuration (nixos-rebuild switch)"""
        try:
            from services.system_service import SystemService, SystemServiceError

            service = SystemService()
            print(f"🚀 Switching to system configuration: {args.slug}")

            if args.dry_run:
                print("⚠️  DRY RUN MODE - No changes will be made")
            else:
                print("⚠️  This will activate the configuration permanently!")
                print("   Consider running 'nixos system-test' first.")
                response = input("\nContinue? (yes/no): ")
                if response.lower() != 'yes':
                    print("Cancelled")
                    return 0

            result = service.switch_system(args.slug, dry_run=args.dry_run)

            if result['success']:
                print("\n✅ Switch successful!")
                if result.get('nixos_generation'):
                    print(f"   NixOS generation: {result['nixos_generation']}")
                print("\n✨ System configuration is now active and will persist across reboots.")
            else:
                print(f"\n❌ Switch failed (exit code {result['exit_code']})")

            if result['stdout']:
                print("\n📋 Output:")
                print(result['stdout'])

            if result['stderr']:
                print("\n⚠️  Errors/Warnings:")
                print(result['stderr'])

            return 0 if result['success'] else 1

        except Exception as e:
            logger.error(f"Failed to switch system: {e}", exc_info=True)
            return 1

    def system_status(self, args) -> int:
        """Show current system deployment status"""
        try:
            from services.system_service import SystemService

            service = SystemService()
            active = service.get_active_deployment()

            if not active:
                print("⚠️  No active system deployment found")
                return 0

            print("\n╔══════════════════════════════════════════════════════════╗")
            print("║          Active System Deployment                       ║")
            print("╚══════════════════════════════════════════════════════════╝")
            print(f"\nProject:    {active['project_name']} ({active['project_slug']})")
            print(f"Deployed:   {active['deployed_at']}")
            print(f"Checkout:   {active['checkout_path']}")
            print(f"Config:     {active['config_path']}")
            print(f"Generation: {active['nixos_generation'] or 'N/A'}")
            print(f"Command:    {active['command']}")
            print()

            return 0

        except Exception as e:
            logger.error(f"Failed to get status: {e}", exc_info=True)
            return 1

    def system_history(self, args) -> int:
        """Show deployment history"""
        try:
            from services.system_service import SystemService

            service = SystemService()
            history = service.get_deployment_history(
                project_slug=args.project,
                limit=args.limit
            )

            if not history:
                print("⚠️  No deployment history found")
                return 0

            print("\n╔══════════════════════════════════════════════════════════╗")
            print("║          System Deployment History                      ║")
            print("╚══════════════════════════════════════════════════════════╝")
            print()

            for dep in history:
                status = "✅ ACTIVE" if dep['is_active'] else ("✓" if dep['exit_code'] == 0 else "✗")
                print(f"ID {dep['id']:>3} | {status} | {dep['project_slug']:15} | Gen {dep['nixos_generation'] or 'N/A':>3} | {dep['command']:15} | {dep['deployed_at'][:19]}")

            print()
            print("💡 To rollback: ./templedb nixos system-rollback <deployment_id>")
            print()

            return 0

        except Exception as e:
            logger.error(f"Failed to get history: {e}", exc_info=True)
            return 1

    def system_rollback(self, args) -> int:
        """Rollback to previous deployment"""
        try:
            from services.system_service import SystemService

            service = SystemService()

            if args.deployment_id:
                print(f"⏪ Rolling back to deployment {args.deployment_id}")
                deployment_id = args.deployment_id
            else:
                # Get previous non-active deployment
                history = service.get_deployment_history(limit=2)
                if len(history) < 2:
                    print("❌ No previous deployment found to rollback to")
                    return 1

                deployment_id = history[1]['id']
                print(f"⏪ Rolling back to previous deployment (ID: {deployment_id})")

            result = service.rollback_to_deployment(deployment_id)

            if result['success']:
                print("\n✅ Rollback successful!")
            else:
                print(f"\n❌ Rollback failed (exit code {result['exit_code']})")

            if result['stdout']:
                print("\n📋 Output:")
                print(result['stdout'])

            if result['stderr']:
                print("\n⚠️  Errors/Warnings:")
                print(result['stderr'])

            return 0 if result['success'] else 1

        except Exception as e:
            logger.error(f"Failed to rollback: {e}", exc_info=True)
            return 1

    def set_type(self, args) -> int:
        """Set project type"""
        try:
            from services.system_service import SystemService

            service = SystemService()
            service.set_project_type(args.slug, args.type)
            print(f"✅ Set {args.slug} type to {args.type}")

            if args.type == 'nixos-config':
                print("\n💡 You can now use:")
                print(f"   ./templedb nixos system-test {args.slug}")
                print(f"   ./templedb nixos system-switch {args.slug}")

            return 0

        except Exception as e:
            logger.error(f"Failed to set type: {e}", exc_info=True)
            return 1

    def list_configs(self, args) -> int:
        """List all nixos-config projects"""
        try:
            from services.system_service import SystemService

            service = SystemService()
            projects = service.get_nixos_config_projects()

            if not projects:
                print("⚠️  No nixos-config projects found")
                print("\n💡 To mark a project as nixos-config:")
                print("   ./templedb nixos set-type <project> nixos-config")
                return 0

            print("\n╔══════════════════════════════════════════════════════════╗")
            print("║          NixOS Configuration Projects                   ║")
            print("╚══════════════════════════════════════════════════════════╝")
            print()

            for proj in projects:
                print(f"  {proj['slug']:20} | {proj['project_type']:12} | {proj['created_at'][:10]}")

            print()
            return 0

        except Exception as e:
            logger.error(f"Failed to list configs: {e}", exc_info=True)
            return 1


def register(cli):
    """Register NixOS commands with CLI"""
    cmd = NixOSCommand()

    # Create nixos command group
    nixos_parser = cli.register_command('nixos', None, help_text='NixOS integration and module generation')
    subparsers = nixos_parser.add_subparsers(dest='nixos_subcommand', required=True)

    # nixos detect command
    detect_parser = subparsers.add_parser('detect', help='Detect dependencies and show what would be generated')
    detect_parser.add_argument('slug', help='Project slug')
    cli.commands['nixos.detect'] = cmd.detect

    # nixos generate command
    gen_parser = subparsers.add_parser('generate', help='Generate NixOS modules')
    gen_parser.add_argument('slug', help='Project slug')
    gen_parser.add_argument('-o', '--output', help='Output directory (default: /tmp/nixos-gen)')
    gen_parser.add_argument('--cathedral-path', help='Path to existing Cathedral package')
    gen_parser.add_argument('--no-home-manager', action='store_true', help='Skip Home Manager module')
    gen_parser.add_argument('--include-templedb', action='store_true', default=True,
                           help='Include TempleDB itself as a dependency (default: true)')
    gen_parser.add_argument('--no-templedb', dest='include_templedb', action='store_false',
                           help='Do not include TempleDB as a dependency')
    cli.commands['nixos.generate'] = cmd.generate

    # nixos export command
    export_parser = subparsers.add_parser('export', help='Export Cathedral package with NixOS modules')
    export_parser.add_argument('slug', help='Project slug')
    export_parser.add_argument('-o', '--output', help='Output directory (default: /tmp/nixos-gen)')
    cli.commands['nixos.export'] = cmd.export

    # nixos system-test command
    test_parser = subparsers.add_parser('system-test', help='Test system configuration (nixos-rebuild test)')
    test_parser.add_argument('slug', help='Project slug (must be nixos-config type)')
    test_parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    cli.commands['nixos.system-test'] = cmd.system_test

    # nixos system-switch command
    switch_parser = subparsers.add_parser('system-switch', help='Switch to system configuration (nixos-rebuild switch)')
    switch_parser.add_argument('slug', help='Project slug (must be nixos-config type)')
    switch_parser.add_argument('--dry-run', action='store_true', help='Show what would be done')
    cli.commands['nixos.system-switch'] = cmd.system_switch

    # nixos system-status command
    status_parser = subparsers.add_parser('system-status', help='Show current system deployment status')
    cli.commands['nixos.system-status'] = cmd.system_status

    # nixos system-history command
    history_parser = subparsers.add_parser('system-history', help='Show deployment history')
    history_parser.add_argument('--project', help='Filter by project')
    history_parser.add_argument('--limit', type=int, default=10, help='Number of records')
    cli.commands['nixos.system-history'] = cmd.system_history

    # nixos system-rollback command
    rollback_parser = subparsers.add_parser('system-rollback', help='Rollback to previous deployment')
    rollback_parser.add_argument('deployment_id', type=int, nargs='?', help='Deployment ID (default: previous)')
    cli.commands['nixos.system-rollback'] = cmd.system_rollback

    # nixos set-type command
    set_type_parser = subparsers.add_parser('set-type', help='Set project type')
    set_type_parser.add_argument('slug', help='Project slug')
    set_type_parser.add_argument('type', choices=['regular', 'nixos-config', 'service', 'library'], help='Project type')
    cli.commands['nixos.set-type'] = cmd.set_type

    # nixos list-configs command
    list_parser = subparsers.add_parser('list-configs', help='List all nixos-config projects')
    cli.commands['nixos.list-configs'] = cmd.list_configs
