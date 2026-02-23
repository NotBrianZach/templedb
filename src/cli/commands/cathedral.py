#!/usr/bin/env python3
"""
Cathedral package management commands - Export/import projects as .cathedral packages
"""
import sys
from pathlib import Path
from typing import Optional

# Import will be resolved at runtime
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command


class CathedralCommands(Command):
    """Cathedral package management command handlers"""

    def export(self, args) -> int:
        """Export project to .cathedral package"""
        try:
            from cathedral_export import export_project

            slug = args.slug
            output_dir = Path(args.output) if args.output else Path.cwd()
            compress = args.compress
            compression_level = args.level if hasattr(args, 'level') and args.level else None
            exclude_patterns = args.exclude if hasattr(args, 'exclude') and args.exclude else []

            # Check if project exists
            project = self.get_project_or_exit(slug)

            success = export_project(
                slug=slug,
                output_dir=output_dir,
                compress=compress,
                compression_level=compression_level,
                exclude_patterns=exclude_patterns,
                include_files=not args.no_files,
                include_vcs=not args.no_vcs,
                include_environments=not args.no_environments
            )

            return 0 if success else 1

        except Exception as e:
            print(f"✗ Export failed: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    def import_package(self, args) -> int:
        """Import .cathedral package into database"""
        try:
            from cathedral_import import import_project

            package_path = Path(args.package_path)

            if not package_path.exists():
                print(f"Error: Package not found: {package_path}", file=sys.stderr)
                return 1

            success = import_project(
                package_path=package_path,
                overwrite=args.overwrite,
                new_slug=args.as_slug if hasattr(args, 'as_slug') else None
            )

            return 0 if success else 1

        except Exception as e:
            print(f"✗ Import failed: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    def verify(self, args) -> int:
        """Verify .cathedral package integrity"""
        try:
            from cathedral_format import CathedralPackage
            from cathedral_compression import detect_compression, auto_decompress

            package_path = Path(args.package_path)

            if not package_path.exists():
                print(f"Error: Package not found: {package_path}", file=sys.stderr)
                return 1

            # Auto-decompress if needed
            compression = detect_compression(package_path)
            if compression != 'none':
                print(f"🗜️  Detected {compression} compression, decompressing for verification...")
                package_path = auto_decompress(package_path)

            if not package_path.is_dir():
                print(f"Error: Package must be a directory: {package_path}", file=sys.stderr)
                return 1

            # Load and verify package
            package = CathedralPackage(package_path)

            if package.verify_integrity():
                print("✅ Package integrity verified!")

                # Show package info
                manifest = package.read_manifest()
                print(f"\nPackage: {manifest.project['slug']}")
                print(f"Created: {manifest.created_at}")
                print(f"Creator: {manifest.created_by}")
                print(f"Files: {manifest.contents.get('total_files', 0)}")
                print(f"Format: {manifest.format} v{manifest.version}")

                return 0
            else:
                print("❌ Package integrity verification failed!", file=sys.stderr)
                return 1

        except Exception as e:
            print(f"✗ Verification failed: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1


def register(cli):
    """Register cathedral commands with CLI"""
    cmd = CathedralCommands()

    # Create cathedral command group
    cathedral_parser = cli.register_command(
        'cathedral',
        None,  # No handler for parent
        help_text='Cathedral package management (export/import projects)'
    )
    subparsers = cathedral_parser.add_subparsers(dest='cathedral_subcommand', required=True)

    # cathedral export
    export_parser = subparsers.add_parser('export', help='Export project as .cathedral package')
    export_parser.add_argument('slug', help='Project slug to export')
    export_parser.add_argument('--output', '-o', help='Output directory (default: current directory)')
    export_parser.add_argument('--compress', '-c', action='store_true', help='Compress package (gzip or zstd)')
    export_parser.add_argument('--level', '-l', type=int, metavar='N', help='Compression level: gzip 1-9 (default 6), zstd 1-22 (default 3)')
    export_parser.add_argument('--exclude', '-e', action='append', metavar='PATTERN', help='Exclude files matching pattern (can be used multiple times, e.g. "*.log" "node_modules/*")')
    export_parser.add_argument('--no-files', action='store_true', help='Exclude file contents')
    export_parser.add_argument('--no-vcs', action='store_true', help='Exclude VCS data')
    export_parser.add_argument('--no-environments', action='store_true', help='Exclude Nix environments')
    cli.commands['cathedral.export'] = cmd.export

    # cathedral import
    import_parser = subparsers.add_parser('import', help='Import .cathedral package')
    import_parser.add_argument('package_path', help='Path to .cathedral package (compressed or uncompressed)')
    import_parser.add_argument('--overwrite', action='store_true', help='Overwrite existing project')
    import_parser.add_argument('--as', dest='as_slug', help='Import with different slug')
    cli.commands['cathedral.import'] = cmd.import_package

    # cathedral verify
    verify_parser = subparsers.add_parser('verify', help='Verify package integrity')
    verify_parser.add_argument('package_path', help='Path to .cathedral package')
    cli.commands['cathedral.verify'] = cmd.verify
