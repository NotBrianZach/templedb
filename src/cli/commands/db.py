#!/usr/bin/env python3
"""
Database management commands: migrate, status, stamp, integrity checks.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class DBCommands(Command):
    """Database management command handlers"""

    def migrate(self, args) -> int:
        """Apply pending migrations."""
        from db_utils import DB_PATH
        from migrator import Migrator

        db_path = args.db_path or DB_PATH

        # Ensure parent dir exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        m = Migrator(db_path)
        print(f"Database: {db_path}")

        applied, skipped = m.migrate(dry_run=args.dry_run)

        if applied == 0 and skipped > 0:
            print(f"Database is up to date ({skipped} migrations already applied)")
        elif applied > 0:
            print(f"Applied {applied} migration(s), {skipped} already applied")
        else:
            print("Nothing to do")

        return 0

    def status(self, args) -> int:
        """Show migration status."""
        from db_utils import DB_PATH
        from migrator import Migrator

        db_path = args.db_path or DB_PATH

        if not Path(db_path).exists():
            print(f"Database not found: {db_path}")
            print(f"  Create with: templedb admin db migrate")
            return 1

        m = Migrator(db_path)
        entries = m.status()

        pending = sum(1 for e in entries if not e["applied"])
        applied = sum(1 for e in entries if e["applied"])

        print(f"Database: {db_path}")
        print(f"Migrations: {applied} applied, {pending} pending\n")

        for e in entries:
            if e["applied"]:
                marker = "OK"
                date = e["applied_at"][:10] if e["applied_at"] else "?"
                print(f"  [{marker:>7}] {e['filename']:<55} ({date})")
            else:
                print(f"  [PENDING] {e['filename']}")

        if pending > 0:
            print(f"\nRun 'templedb admin db migrate' to apply {pending} pending migration(s)")

        return 0

    def stamp(self, args) -> int:
        """Mark all migrations as applied without running them.
        Use this for existing databases that predate the migration framework."""
        from db_utils import DB_PATH
        from migrator import Migrator

        db_path = args.db_path or DB_PATH

        if not Path(db_path).exists():
            print(f"Database not found: {db_path}")
            return 1

        m = Migrator(db_path)
        stamped = m.stamp_existing()

        if stamped > 0:
            print(f"Stamped {stamped} migration(s) as pre-existing")
        else:
            print("All migrations already tracked")

        return 0

    def integrity(self, args) -> int:
        """Check database integrity."""
        from db_utils import DB_PATH, check_integrity, get_db_stats

        db_path = args.db_path or DB_PATH

        if not Path(db_path).exists():
            print(f"Database not found: {db_path}")
            return 1

        print(f"Database: {db_path}")

        ok = check_integrity()
        print(f"Integrity: {'OK' if ok else 'FAILED'}")

        stats = get_db_stats()
        print(f"Size: {stats['size_mb']:.1f} MB")
        print(f"Tables:")
        for table, count in stats['tables'].items():
            print(f"  {table}: {count} rows")

        return 0 if ok else 1


def register(cli):
    """Register db commands with CLI"""
    cmd = DBCommands()

    db_parser = cli.register_command('db', None, help_text='Database management')
    subparsers = db_parser.add_subparsers(dest='db_subcommand', required=True)

    # db migrate
    migrate_p = subparsers.add_parser('migrate', help='Apply pending migrations')
    migrate_p.add_argument('--db-path', help='Database path (default: auto)')
    migrate_p.add_argument('--dry-run', action='store_true', help='Show what would be applied')
    cli.commands['db.migrate'] = cmd.migrate

    # db status
    status_p = subparsers.add_parser('status', help='Show migration status')
    status_p.add_argument('--db-path', help='Database path (default: auto)')
    cli.commands['db.status'] = cmd.status

    # db stamp
    stamp_p = subparsers.add_parser('stamp', help='Mark all migrations as applied (for pre-existing DBs)')
    stamp_p.add_argument('--db-path', help='Database path (default: auto)')
    cli.commands['db.stamp'] = cmd.stamp

    # db integrity
    integrity_p = subparsers.add_parser('integrity', help='Check database integrity')
    integrity_p.add_argument('--db-path', help='Database path (default: auto)')
    cli.commands['db.integrity'] = cmd.integrity
