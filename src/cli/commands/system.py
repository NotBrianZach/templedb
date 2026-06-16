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
from db_utils import DB_PATH
from repositories import BaseRepository
from cli.core import Command
from logger import get_logger
from cli.error_handling_utils import (
    handle_errors,
    ResourceNotFoundError,
    confirm_action,
    print_success
)

logger = get_logger(__name__)


class SystemCommands(Command):
    """System command handlers"""

    def __init__(self):
        super().__init__()
        """Initialize with repositories"""
        self.system_repo = BaseRepository()  # Generic repository for system queries

    @handle_errors("system backup")
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

        # Use SQLite backup API for safe backup
        source = sqlite3.connect(str(DB_PATH))
        dest = sqlite3.connect(str(backup_path))
        source.backup(dest)
        source.close()
        dest.close()

        # Get size
        size_mb = backup_path.stat().st_size / (1024 * 1024)
        print_success(f"Backup complete: {backup_path} ({size_mb:.2f} MB)")
        return 0

    @handle_errors("system restore")
    def restore(self, args) -> int:
        """Restore database from backup"""
        backup_path = Path(args.path).resolve()

        if not backup_path.exists():
            raise ResourceNotFoundError(
                f"Backup file not found: {backup_path}\n"
                f"Verify the path and try again"
            )

        # Confirm
        if not confirm_action(
            f"⚠️  WARNING: This will replace your current database!\n"
            f"   Current: {DB_PATH}\n"
            f"   Backup:  {backup_path}\n"
            f"Continue?",
            default=False
        ):
            print("Restore cancelled")
            return 0

        # Backup current database first
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safety_backup = f"{DB_PATH}.before_restore_{timestamp}"
        shutil.copy2(DB_PATH, safety_backup)
        print(f"📦 Created safety backup: {safety_backup}")

        # Restore
        shutil.copy2(backup_path, DB_PATH)
        print_success(f"Database restored from {backup_path}")
        return 0

    @handle_errors("system status")
    def status(self, args) -> int:
        """Show database status"""
        # Database info
        db_path = Path(DB_PATH)
        if not db_path.exists():
            raise ResourceNotFoundError(
                f"Database not found: {DB_PATH}\n"
                f"Run './templedb project import <repo>' to create the database"
            )

        size_mb = db_path.stat().st_size / (1024 * 1024)

        # Header
        print()
        print("╔════════════════════════════════════════════════════════════════╗")
        print("║                     TempleDB Status                            ║")
        print("║            In Honor of Terry Davis (1969-2018)                 ║")
        print("╚════════════════════════════════════════════════════════════════╝")
        print()

        # Overall Statistics
        print("═════ Overall Statistics ═════")
        print()

        stats = [
            ("Projects", self.system_repo.query_one("SELECT COUNT(*) as count FROM projects")['count']),
            ("Files", self.system_repo.query_one("SELECT COUNT(*) as count FROM project_files")['count']),
            ("Lines of Code", self.system_repo.query_one("SELECT SUM(lines_of_code) as total FROM project_files")['total'] or 0),
            ("File Contents Stored", self.system_repo.query_one("SELECT COUNT(*) as count FROM file_contents")['count']),
            ("VCS Commits", self.system_repo.query_one("SELECT COUNT(*) as count FROM vcs_commits")['count']),
            ("VCS Branches", self.system_repo.query_one("SELECT COUNT(*) as count FROM vcs_branches")['count']),
            ("Database Size", f"{size_mb:.2f} MB")
        ]

        max_label = max(len(label) for label, _ in stats)
        for label, value in stats:
            print(f"{label:<{max_label}} {value}")

        # Projects
        print()
        print("═════ Projects ═════")
        print()

        projects = self.system_repo.query_all("""
            SELECT
                p.slug,
                p.repo_url,
                (SELECT COUNT(*) FROM project_files WHERE project_id = p.id) as files,
                (SELECT SUM(lines_of_code) FROM project_files WHERE project_id = p.id) as lines,
                (SELECT branch_name FROM vcs_branches WHERE project_id = p.id AND is_default = 1) as branch
            FROM projects p
            ORDER BY p.slug
        """)

        if projects:
            print(self.format_table(projects, ['slug', 'repo_url', 'files', 'lines', 'branch']))
        else:
            print("No projects found")
            print()

        # File Types Distribution
        print("═════ File Types Distribution ═════")
        print()

        file_types = self.system_repo.query_all("""
            SELECT
                type_name,
                COUNT(*) as count,
                SUM(lines_of_code) as lines,
                PRINTF('%.1f%%', 100.0 * COUNT(*) / (SELECT COUNT(*) FROM project_files)) as pct
            FROM files_with_types_view
            GROUP BY type_name
            HAVING COUNT(*) > 0
            ORDER BY COUNT(*) DESC
            LIMIT 15
        """)

        if file_types:
            print(self.format_table(file_types, ['type_name', 'count', 'lines', 'pct']))
        else:
            print("No file types found")
            print()

        # Top Largest Files
        print("═════ Top 10 Largest Files ═════")
        print()

        largest_files = self.system_repo.query_all("""
            SELECT
                SUBSTR(file_path, 1, 45) as file,
                project_slug,
                lines_of_code as lines
            FROM files_with_types_view
            ORDER BY lines_of_code DESC
            LIMIT 10
        """)

        if largest_files:
            print(self.format_table(largest_files, ['file', 'project_slug', 'lines']))
        else:
            print("No files found")
            print()

        # Recent Activity
        print("═════ Recent Activity ═════")
        print()

        try:
            recent_commits = self.system_repo.query_all("""
                SELECT
                    SUBSTR(c.commit_message, 1, 40) as message,
                    p.slug as project_slug,
                    SUBSTR(c.commit_timestamp, 1, 16) as time
                FROM vcs_commits c
                JOIN projects p ON c.project_id = p.id
                ORDER BY c.commit_timestamp DESC
                LIMIT 10
            """)

            if recent_commits:
                print(self.format_table(recent_commits, ['message', 'project_slug', 'time']))
            else:
                print("No commits found")
                print()
        except Exception as e:
            print(f"No recent activity available")
            print()

        # Footer
        print("═════════════════════════════════════════════════════════════════")
        print(f"Database: {DB_PATH}")
        print()
        print("Quick commands:")
        print("  ./templedb project list              # List all projects")
        print("  ./templedb vcs status <project>      # View VCS status")
        print("  ./templedb status                    # Show this status")
        print("═════════════════════════════════════════════════════════════════")
        print()

        return 0



def register(cli):
    """Register system commands"""
    cmd = SystemCommands()

    # status - only command still registered here (backup/restore moved to backup.py)
    cli.register_command('status', cmd.status, help_text='Show database status')
