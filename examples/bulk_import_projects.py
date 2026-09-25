#!/usr/bin/env python3
"""
Example: Bulk Import Projects

Demonstrates how to use the service layer to bulk import multiple projects
from a directory structure.

Usage:
    python3 examples/bulk_import_projects.py /path/to/projects/

This script:
1. Scans a directory for subdirectories
2. Imports each subdirectory as a project
3. Reports statistics for each import
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from services.context import ServiceContext
from error_handler import ValidationError


def bulk_import(projects_dir: Path, dry_run: bool = False):
    """
    Import all subdirectories in projects_dir as TempleDB projects.

    Args:
        projects_dir: Directory containing project subdirectories
        dry_run: If True, simulate import without making changes
    """
    # Create service context
    ctx = ServiceContext()
    service = ctx.get_project_service()

    # Track statistics
    total_projects = 0
    successful = 0
    failed = 0
    total_files = 0

    print(f"🔍 Scanning {projects_dir} for projects...")
    print(f"   Dry run: {'Yes' if dry_run else 'No'}\n")

    # Iterate through subdirectories
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue

        # Skip hidden directories and special directories
        if project_dir.name.startswith('.') or project_dir.name in ['node_modules', 'venv', '__pycache__']:
            continue

        total_projects += 1
        slug = project_dir.name

        try:
            print(f"📦 Importing {slug}...")

            # Import project
            stats = service.import_project(
                project_path=project_dir,
                slug=slug,
                dry_run=dry_run
            )

            # Report statistics
            print(f"   ✓ Success!")
            print(f"     Files scanned: {stats.total_files_scanned}")
            print(f"     Files imported: {stats.files_imported}")
            print(f"     Content stored: {stats.content_stored}")
            print(f"     SQL objects: {stats.sql_objects_found}")
            print()

            successful += 1
            total_files += stats.files_imported

        except ValidationError as e:
            print(f"   ✗ Failed: {e}")
            if e.solution:
                print(f"     💡 {e.solution}")
            print()
            failed += 1

        except Exception as e:
            print(f"   ✗ Unexpected error: {e}")
            print()
            failed += 1

    # Print summary
    print("=" * 60)
    print("📊 Bulk Import Summary")
    print("=" * 60)
    print(f"Projects found:      {total_projects}")
    print(f"Successfully imported: {successful}")
    print(f"Failed:              {failed}")
    print(f"Total files imported: {total_files}")
    print()

    if dry_run:
        print("💡 This was a dry run - no changes were made")
        print("   Run without --dry-run to actually import projects")


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Bulk import projects into TempleDB',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (no changes)
  python3 examples/bulk_import_projects.py /path/to/projects --dry-run

  # Actually import
  python3 examples/bulk_import_projects.py /path/to/projects

  # Import from specific directory
  python3 examples/bulk_import_projects.py ~/repos
        """
    )

    parser.add_argument(
        'directory',
        type=Path,
        help='Directory containing project subdirectories'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Simulate import without making changes'
    )

    args = parser.parse_args()

    # Validate directory exists
    if not args.directory.exists():
        print(f"❌ Error: Directory does not exist: {args.directory}", file=sys.stderr)
        sys.exit(1)

    if not args.directory.is_dir():
        print(f"❌ Error: Not a directory: {args.directory}", file=sys.stderr)
        sys.exit(1)

    # Run bulk import
    try:
        bulk_import(args.directory, dry_run=args.dry_run)
    except KeyboardInterrupt:
        print("\n\n⚠️  Import cancelled by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
