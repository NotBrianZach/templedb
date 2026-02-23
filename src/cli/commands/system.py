#!/usr/bin/env python3
"""
System commands (backup, restore, status)
"""
import sys
import os
import sqlite3
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from db_utils import DB_PATH, query_one, query_all
from cli.core import Command


class SystemCommands(Command):
    """System command handlers"""

    def backup(self, args) -> int:
        """Backup database"""
        if args.path:
            backup_path = Path(args.path).resolve()
        else:
            # Default backup location
            backup_dir = Path(DB_PATH).parent / "backups"
            backup_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"templedb_backup_{timestamp}.sqlite"

        print(f"💾 Backing up database to {backup_path}...")

        try:
            # Use SQLite backup API for safe backup
            source = sqlite3.connect(str(DB_PATH))
            dest = sqlite3.connect(str(backup_path))
            source.backup(dest)
            source.close()
            dest.close()

            # Get size
            size_mb = backup_path.stat().st_size / (1024 * 1024)
            print(f"✓ Backup complete: {backup_path} ({size_mb:.2f} MB)")
            return 0
        except Exception as e:
            print(f"✗ Backup failed: {e}", file=sys.stderr)
            return 1

    def restore(self, args) -> int:
        """Restore database from backup"""
        backup_path = Path(args.path).resolve()

        if not backup_path.exists():
            print(f"Error: Backup file not found: {backup_path}", file=sys.stderr)
            return 1

        # Confirm
        print(f"⚠️  WARNING: This will replace your current database!")
        print(f"   Current: {DB_PATH}")
        print(f"   Backup:  {backup_path}")
        response = input("Continue? (yes/no): ")

        if response.lower() != 'yes':
            print("Restore cancelled")
            return 0

        try:
            # Backup current database first
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            safety_backup = f"{DB_PATH}.before_restore_{timestamp}"
            shutil.copy2(DB_PATH, safety_backup)
            print(f"📦 Created safety backup: {safety_backup}")

            # Restore
            shutil.copy2(backup_path, DB_PATH)
            print(f"✓ Database restored from {backup_path}")
            return 0
        except Exception as e:
            print(f"✗ Restore failed: {e}", file=sys.stderr)
            return 1

    def status(self, args) -> int:
        """Show database status"""
        # Database info
        db_path = Path(DB_PATH)
        if db_path.exists():
            size_mb = db_path.stat().st_size / (1024 * 1024)
            print(f"\n📊 TempleDB Status\n")
            print(f"Database: {DB_PATH}")
            print(f"Size: {size_mb:.2f} MB")
        else:
            print(f"Database not found: {DB_PATH}")
            return 1

        # Project count
        project_count = query_one("SELECT COUNT(*) as count FROM projects")
        print(f"\nProjects: {project_count['count']}")

        # File statistics
        file_stats = query_one("""
            SELECT
                COUNT(*) as file_count,
                SUM(lines_of_code) as total_lines,
                COUNT(DISTINCT file_type_id) as file_types
            FROM project_files
        """)
        if file_stats:
            print(f"Files: {file_stats['file_count']}")
            print(f"Lines of code: {file_stats['total_lines']:,}")
            print(f"File types: {file_stats['file_types']}")

        # VCS statistics
        vcs_stats = query_one("""
            SELECT
                COUNT(DISTINCT id) as branch_count
            FROM vcs_branches
        """)
        commit_stats = query_one("""
            SELECT COUNT(*) as commit_count FROM vcs_commits
        """)
        if vcs_stats and commit_stats:
            print(f"\nVCS Branches: {vcs_stats['branch_count']}")
            print(f"VCS Commits: {commit_stats['commit_count']}")

        # Performance settings
        pragmas = query_one("PRAGMA journal_mode")
        cache_size = query_one("PRAGMA cache_size")
        print(f"\nPerformance:")
        print(f"Journal mode: {pragmas['journal_mode'] if pragmas else 'unknown'}")
        print(f"Cache size: {abs(cache_size['cache_size']) // 1024 if cache_size and cache_size['cache_size'] < 0 else 'default'} MB")

        print()
        return 0



def register(cli):
    """Register system commands"""
    cmd = SystemCommands()

    # backup
    backup_parser = cli.register_command('backup', cmd.backup, help_text='Backup database')
    backup_parser.add_argument('path', nargs='?', help='Backup file path (default: auto-generated)')

    # restore
    restore_parser = cli.register_command('restore', cmd.restore, help_text='Restore database')
    restore_parser.add_argument('path', help='Backup file path')

    # status
    cli.register_command('status', cmd.status, help_text='Show database status')
