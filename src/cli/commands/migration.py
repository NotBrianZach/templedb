#!/usr/bin/env python3
"""
Migration management commands for TempleDB
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from migration_tracker import MigrationTracker


class MigrationCommands(Command):
    """Migration command handlers"""

    def list(self, args) -> int:
        """List migrations for project"""
        try:
            project_slug = args.slug
            project = self.get_project_or_exit(project_slug)

            print(f"\n📝 Migrations for {project_slug}\n")

            # Find all sql_migration files
            migrations = self.query_all("""
                SELECT file_path, lines_of_code, component_name
                FROM files_with_types_view
                WHERE project_slug = ? AND type_name = 'sql_migration'
                ORDER BY file_path
            """, (project_slug,))

            if not migrations:
                print("⚠️  No migration files found")
                print(f"   Looked for SQL files in migrations/ directories")
                print(f"   Or SQL files with 'migration' in the filename\n")
                return 0

            print(f"Found {len(migrations)} migration files:\n")

            for i, migration in enumerate(migrations, 1):
                print(f"  {i}. {migration['file_path']}")
                print(f"     Lines: {migration['lines_of_code']}")
                if migration.get('component_name'):
                    print(f"     Name: {migration['component_name']}")

            print(f"\n✓ Total: {len(migrations)} migrations")
            print(f"\n💡 To apply migrations:")
            print(f"   1. Export project: ./templedb cathedral export {project_slug}")
            print(f"   2. Apply with psql or your database tool")
            print(f"   3. Or use: ./templedb deploy {project_slug}")

            return 0

        except Exception as e:
            print(f"✗ Failed to list migrations: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    def show(self, args) -> int:
        """Show migration file content"""
        try:
            project_slug = args.slug
            migration_path = args.migration

            project = self.get_project_or_exit(project_slug)

            # Find the migration file
            result = self.query_one("""
                SELECT pf.id, pf.file_path, cb.content_text
                FROM project_files pf
                JOIN file_contents fc ON fc.file_id = pf.id
                JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
                JOIN projects p ON pf.project_id = p.id
                WHERE p.slug = ? AND pf.file_path LIKE ?
            """, (project_slug, f"%{migration_path}%"))

            if not result:
                print(f"✗ Migration not found: {migration_path}", file=sys.stderr)
                print(f"   Use: ./templedb migration list {project_slug}")
                return 1

            print(f"\n📄 Migration: {result['file_path']}\n")
            print("=" * 60)
            print(result['content_text'])
            print("=" * 60)
            print()

            return 0

        except Exception as e:
            print(f"✗ Failed to show migration: {e}", file=sys.stderr)
            return 1

    def status(self, args) -> int:
        """Show migration status (applied vs pending)"""
        try:
            import db_utils
            tracker = MigrationTracker(db_utils)

            project_slug = args.slug
            target_name = args.target if hasattr(args, 'target') and args.target else 'production'
            project = self.get_project_or_exit(project_slug)

            print(f"\n📊 Migration Status: {project_slug} → {target_name}\n")

            # Get all migration statuses
            statuses = tracker.get_migration_statuses(project['id'], target_name)

            if not statuses:
                print("⚠️  No migrations found for this project")
                return 0

            # Count pending and applied
            pending = [s for s in statuses if not s.applied]
            applied = [s for s in statuses if s.applied]

            print(f"✅ Applied: {len(applied)}")
            print(f"⏳ Pending: {len(pending)}\n")

            if pending:
                print("📝 Pending Migrations:\n")
                for status in pending:
                    print(f"   • {status.migration.file_path}")
                print()

            if applied and (hasattr(args, 'show_applied') and args.show_applied):
                print("✅ Applied Migrations:\n")
                for status in applied:
                    print(f"   • {status.migration.file_path}")
                    print(f"     Applied: {status.applied_at}")
                    if status.execution_time_ms:
                        print(f"     Duration: {status.execution_time_ms}ms")
                print()

            if pending:
                print(f"💡 To apply pending migrations:")
                print(f"   ./templedb migration apply {project_slug} --target {target_name}")

            return 0

        except Exception as e:
            print(f"✗ Failed to get migration status: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    def history(self, args) -> int:
        """Show migration history"""
        try:
            import db_utils
            tracker = MigrationTracker(db_utils)

            project_slug = args.slug
            target_name = args.target if hasattr(args, 'target') and args.target else 'production'
            limit = args.limit if hasattr(args, 'limit') and args.limit else 20
            project = self.get_project_or_exit(project_slug)

            print(f"\n📜 Migration History: {project_slug} → {target_name}\n")

            history = tracker.get_migration_history(project['id'], target_name, limit)

            if not history:
                print("⚠️  No migrations have been applied yet")
                return 0

            for entry in history:
                status_icon = "✅" if entry['status'] == 'success' else "❌"
                print(f"{status_icon} {entry['migration_file']}")
                print(f"   Applied: {entry['applied_at']}")
                if entry['applied_by']:
                    print(f"   By: {entry['applied_by']}")
                if entry['execution_time_ms']:
                    print(f"   Duration: {entry['execution_time_ms']}ms")
                if entry['error_message']:
                    print(f"   Error: {entry['error_message']}")
                print()

            return 0

        except Exception as e:
            print(f"✗ Failed to get migration history: {e}", file=sys.stderr)
            return 1

    def mark_applied(self, args) -> int:
        """Mark migration as applied without running it"""
        try:
            import db_utils
            tracker = MigrationTracker(db_utils)

            project_slug = args.slug
            migration_file = args.migration
            target_name = args.target if hasattr(args, 'target') and args.target else 'production'
            project = self.get_project_or_exit(project_slug)

            # Find the migration
            migrations = tracker.get_project_migrations(project['id'])
            migration = None
            for m in migrations:
                if migration_file in m.file_path:
                    migration = m
                    break

            if not migration:
                print(f"✗ Migration not found: {migration_file}", file=sys.stderr)
                return 1

            # Mark as applied
            tracker.mark_migration_applied(
                project['id'],
                target_name,
                migration.file_path,
                migration.checksum,
                applied_by='manual'
            )

            print(f"✓ Marked migration as applied: {migration.file_path}")
            return 0

        except Exception as e:
            print(f"✗ Failed to mark migration: {e}", file=sys.stderr)
            return 1


def register(cli):
    """Register migration commands with CLI"""
    migration_handler = MigrationCommands()

    # Create migration command group
    migration_parser = cli.register_command('migration', None, help_text='Manage database migrations')
    subparsers = migration_parser.add_subparsers(dest='migration_subcommand', required=True)

    # list command
    list_parser = subparsers.add_parser('list', help='List all migrations')
    list_parser.add_argument('slug', help='Project slug')
    cli.commands['migration.list'] = migration_handler.list

    # show command
    show_parser = subparsers.add_parser('show', help='Show migration content')
    show_parser.add_argument('slug', help='Project slug')
    show_parser.add_argument('migration', help='Migration file path or name')
    cli.commands['migration.show'] = migration_handler.show

    # status command
    status_parser = subparsers.add_parser('status', help='Show migration status (applied vs pending)')
    status_parser.add_argument('slug', help='Project slug')
    status_parser.add_argument('--target', default='production', help='Deployment target (default: production)')
    status_parser.add_argument('--show-applied', action='store_true', help='Show applied migrations')
    cli.commands['migration.status'] = migration_handler.status

    # history command
    history_parser = subparsers.add_parser('history', help='Show migration history')
    history_parser.add_argument('slug', help='Project slug')
    history_parser.add_argument('--target', default='production', help='Deployment target (default: production)')
    history_parser.add_argument('--limit', type=int, default=20, help='Limit number of results (default: 20)')
    cli.commands['migration.history'] = migration_handler.history

    # mark-applied command
    mark_parser = subparsers.add_parser('mark-applied', help='Mark migration as applied without running')
    mark_parser.add_argument('slug', help='Project slug')
    mark_parser.add_argument('migration', help='Migration file path or name')
    mark_parser.add_argument('--target', default='production', help='Deployment target (default: production)')
    cli.commands['migration.mark-applied'] = migration_handler.mark_applied
