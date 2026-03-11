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
