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

    def check(self, args) -> int:
        """Comprehensive DB health check: integrity, locks, WAL, and processes."""
        import os
        import sqlite3
        import subprocess
        from db_utils import DB_PATH

        db_path = args.db_path or DB_PATH

        if not Path(db_path).exists():
            print(f"Database not found: {db_path}")
            return 1

        print(f"Database: {db_path}")
        problems = []

        # 1. File sizes
        db_size = os.path.getsize(db_path)
        wal_path = db_path + "-wal"
        shm_path = db_path + "-shm"
        wal_size = os.path.getsize(wal_path) if os.path.exists(wal_path) else 0
        shm_size = os.path.getsize(shm_path) if os.path.exists(shm_path) else 0
        print(f"  DB size:  {db_size / 1024 / 1024:.1f} MB")
        print(f"  WAL size: {wal_size / 1024 / 1024:.1f} MB")
        print(f"  SHM size: {shm_size} bytes")
        if wal_size > 50 * 1024 * 1024:
            problems.append(f"WAL is large ({wal_size / 1024 / 1024:.0f} MB) — checkpoint may be blocked")

        # 2. Read access
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
            conn.execute("SELECT 1")
            conn.close()
            print(f"  Read:     OK")
        except Exception as e:
            print(f"  Read:     FAILED ({e})")
            problems.append(f"Cannot read DB: {e}")

        # 3. Write access (with short timeout)
        try:
            conn = sqlite3.connect(db_path, timeout=3)
            conn.execute("PRAGMA busy_timeout=3000")
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
            conn.close()
            print(f"  Write:    OK")
        except sqlite3.OperationalError as e:
            print(f"  Write:    LOCKED ({e})")
            problems.append("Database is write-locked by another process")

        # 4. Integrity check
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
            result = conn.execute("PRAGMA integrity_check").fetchone()
            conn.close()
            if result and result[0] == "ok":
                print(f"  Integrity: OK")
            else:
                msg = result[0] if result else "unknown"
                print(f"  Integrity: FAILED ({msg})")
                problems.append(f"Integrity check failed: {msg}")
        except Exception as e:
            print(f"  Integrity: ERROR ({e})")
            problems.append(f"Integrity check error: {e}")

        # 5. Processes using the DB
        print(f"\nProcesses using DB:")
        try:
            result = subprocess.run(
                ["lsof", db_path, wal_path, shm_path],
                capture_output=True, text=True, timeout=5
            )
            if result.stdout.strip():
                for line in result.stdout.strip().split("\n"):
                    print(f"  {line}")
            else:
                print(f"  (none)")
        except FileNotFoundError:
            # lsof not available, try /proc
            try:
                found = False
                for pid_dir in Path("/proc").iterdir():
                    if not pid_dir.name.isdigit():
                        continue
                    try:
                        fd_dir = pid_dir / "fd"
                        for fd in fd_dir.iterdir():
                            target = os.readlink(str(fd))
                            if db_path in target:
                                cmdline = (pid_dir / "cmdline").read_text().replace('\0', ' ').strip()
                                print(f"  PID {pid_dir.name}: {cmdline[:80]}")
                                found = True
                                break
                    except (PermissionError, FileNotFoundError):
                        continue
                if not found:
                    print(f"  (none found)")
            except Exception:
                print(f"  (could not enumerate — lsof not available)")
        except Exception as e:
            print(f"  (error: {e})")

        # 6. Summary
        if problems:
            print(f"\nProblems found:")
            for p in problems:
                print(f"  - {p}")
            return 1
        else:
            print(f"\nAll checks passed.")
            return 0

    def repair(self, args) -> int:
        """Repair database via dump and restore (fixes freelist corruption)."""
        import os
        import sqlite3
        import shutil
        import tempfile
        from db_utils import DB_PATH

        db_path = args.db_path or DB_PATH

        if not Path(db_path).exists():
            print(f"Database not found: {db_path}")
            return 1

        # Check for write lock first
        try:
            conn = sqlite3.connect(db_path, timeout=3)
            conn.execute("PRAGMA busy_timeout=3000")
            conn.execute("BEGIN IMMEDIATE")
            conn.rollback()
            conn.close()
        except sqlite3.OperationalError:
            print("ERROR: Database is write-locked. Stop all TempleDB processes first:")
            print("  systemctl --user stop templedb-mount.service")
            print("  pkill -f 'templedb ai vibe'")
            return 1

        db_size = os.path.getsize(db_path)
        print(f"Database: {db_path} ({db_size / 1024 / 1024:.1f} MB)")

        if not args.yes:
            print("This will dump and restore the database to fix corruption.")
            print("A backup will be created at {db_path}.bak")
            resp = input("Continue? [y/N] ").strip().lower()
            if resp != 'y':
                print("Aborted.")
                return 1

        # 1. Checkpoint WAL
        print("Checkpointing WAL...")
        try:
            conn = sqlite3.connect(db_path, timeout=30)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            conn.close()
        except Exception as e:
            print(f"  Warning: WAL checkpoint failed ({e}), continuing anyway")

        # 2. Backup
        bak_path = db_path + ".bak"
        print(f"Backing up to {bak_path}...")
        shutil.copy2(db_path, bak_path)

        # 3. Dump to SQL
        print("Dumping database to SQL...")
        tmp_sql = tempfile.mktemp(suffix=".sql")
        try:
            conn = sqlite3.connect(db_path, timeout=30)
            with open(tmp_sql, 'w') as f:
                for line in conn.iterdump():
                    f.write(line + '\n')
            conn.close()
        except Exception as e:
            print(f"ERROR: Dump failed: {e}")
            print(f"Backup preserved at {bak_path}")
            return 1

        dump_size = os.path.getsize(tmp_sql)
        print(f"  Dumped {dump_size / 1024 / 1024:.1f} MB of SQL")

        # 4. Restore to new DB
        print("Restoring to clean database...")
        tmp_db = tempfile.mktemp(suffix=".sqlite")
        try:
            conn = sqlite3.connect(tmp_db)
            with open(tmp_sql, 'r') as f:
                conn.executescript(f.read())
            conn.execute("PRAGMA integrity_check")
            result = conn.execute("PRAGMA integrity_check").fetchone()
            conn.close()

            if result and result[0] != "ok":
                print(f"ERROR: Restored DB still has issues: {result[0]}")
                print(f"Backup preserved at {bak_path}")
                os.unlink(tmp_db)
                os.unlink(tmp_sql)
                return 1
        except Exception as e:
            print(f"ERROR: Restore failed: {e}")
            print(f"Backup preserved at {bak_path}")
            if os.path.exists(tmp_db):
                os.unlink(tmp_db)
            os.unlink(tmp_sql)
            return 1

        # 5. Swap in the repaired DB
        os.replace(tmp_db, db_path)
        os.unlink(tmp_sql)

        # Clean up stale WAL/SHM
        for suffix in ["-wal", "-shm"]:
            p = db_path + suffix
            if os.path.exists(p):
                os.unlink(p)

        new_size = os.path.getsize(db_path)
        print(f"Repair complete. New size: {new_size / 1024 / 1024:.1f} MB (was {db_size / 1024 / 1024:.1f} MB)")
        print(f"Backup preserved at {bak_path}")
        return 0


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

    # db check
    check_p = subparsers.add_parser('check', help='Comprehensive DB health check (integrity, locks, WAL, processes)')
    check_p.add_argument('--db-path', help='Database path (default: auto)')
    cli.commands['db.check'] = cmd.check

    # db repair
    repair_p = subparsers.add_parser('repair', help='Repair database via dump/restore (fixes corruption)')
    repair_p.add_argument('--db-path', help='Database path (default: auto)')
    repair_p.add_argument('-y', '--yes', action='store_true', help='Skip confirmation prompt')
    cli.commands['db.repair'] = cmd.repair
