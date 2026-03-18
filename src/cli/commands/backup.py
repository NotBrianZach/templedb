#!/usr/bin/env python3
"""
Unified Backup Commands - Local and Cloud backups
Consolidates system.py (backup/restore) and cloud_backup.py
"""
import sys
import sqlite3
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from db_utils import DB_PATH
from repositories import BaseRepository
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)

# Default DB path for cloud backups
DEFAULT_DB_PATH = Path.home() / '.local' / 'share' / 'templedb' / 'templedb.sqlite'


class BackupCommands(Command):
    """Unified backup command handlers"""

    def __init__(self):
        super().__init__()
        self.system_repo = BaseRepository()
        self.config_dir = Path.home() / '.config' / 'templedb'

    # ========== Local Backup Commands ==========

    def local_backup(self, args) -> int:
        """Backup database locally"""
        if hasattr(args, 'path') and args.path:
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
            print(f"✅ Backup complete: {backup_path} ({size_mb:.2f} MB)")
            return 0
        except Exception as e:
            logger.error(f"Backup failed: {e}")
            return 1

    def restore(self, args) -> int:
        """Restore database from local backup"""
        backup_path = Path(args.path).resolve()

        if not backup_path.exists():
            logger.error(f"Backup file not found: {backup_path}")
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
            print(f"✅ Database restored from {backup_path}")
            return 0
        except Exception as e:
            logger.error(f"Restore failed: {e}")
            return 1

    # ========== Cloud Backup Commands ==========

    def _load_config(self, config_path: Optional[Path]) -> Optional[dict]:
        """Load provider configuration from file"""
        if not config_path:
            return {}

        if not config_path.exists():
            logger.error(f"Configuration file not found: {config_path}")
            return None

        import json

        try:
            with open(config_path) as f:
                if config_path.suffix in ['.yaml', '.yml']:
                    try:
                        import yaml
                        return yaml.safe_load(f)
                    except ImportError:
                        logger.error("PyYAML not installed. Cannot parse YAML config.")
                        return None
                else:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
            return None

    def _create_manager(self, provider_name: str, config_path: Optional[Path], **kwargs):
        """Create backup manager instance"""
        from backup.manager import BackupManager

        try:
            config = self._load_config(config_path) if config_path else {}

            if config is None:
                return None

            return BackupManager.from_provider_name(provider_name, config, **kwargs)

        except Exception as e:
            logger.error(f"Failed to create backup manager: {e}")
            return None

    def cloud_init(self, args) -> int:
        """Initialize cloud backup setup"""
        provider_name = args.provider.lower()

        if provider_name in ['gdrive', 'google-drive']:
            return self._setup_gdrive()
        elif provider_name == 'gcs':
            return self._setup_gcs()
        elif provider_name == 'local':
            return self._setup_local()
        else:
            print(f"Setup not implemented for provider: {provider_name}")
            print("Please create a configuration file manually.")
            return 1

    def cloud_push(self, args) -> int:
        """Push database backup to cloud"""
        db_path = Path(args.db_path) if hasattr(args, 'db_path') and args.db_path else Path(DB_PATH)
        config_path = Path(args.config) if hasattr(args, 'config') and args.config else None

        manager = self._create_manager(args.provider, config_path, db_path=db_path)

        if not manager:
            return 1

        logger.info(f"Starting backup to {manager.provider.get_provider_name()}...")

        no_cleanup = hasattr(args, 'no_cleanup') and args.no_cleanup
        keep_local = hasattr(args, 'keep_local') and args.keep_local

        if manager.backup(cleanup=not no_cleanup, keep_local=keep_local):
            print(f"✅ Backup uploaded to {manager.provider.get_provider_name()}")
            return 0
        else:
            print(f"❌ Backup failed")
            return 1

    def cloud_pull(self, args) -> int:
        """Pull database backup from cloud"""
        db_path = Path(args.db_path) if hasattr(args, 'db_path') and args.db_path else Path(DB_PATH)
        config_path = Path(args.config) if hasattr(args, 'config') and args.config else None

        manager = self._create_manager(args.provider, config_path, db_path=db_path)

        if not manager:
            return 1

        logger.info(f"Restoring from {manager.provider.get_provider_name()}...")

        no_safety = hasattr(args, 'no_safety_backup') and args.no_safety_backup

        if manager.restore(
            args.backup_id,
            db_path,
            create_backup=not no_safety
        ):
            print(f"✅ Restore completed successfully")
            return 0
        else:
            print(f"❌ Restore failed")
            return 1

    def cloud_status(self, args) -> int:
        """Show cloud backup status"""
        config_path = Path(args.config) if hasattr(args, 'config') and args.config else None
        manager = self._create_manager(args.provider, config_path)

        if not manager:
            return 1

        logger.info(f"Listing backups from {manager.provider.get_provider_name()}...")

        backups = manager.list_backups()

        if not backups:
            print(f"📦 No backups found in {manager.provider.get_provider_name()}")
            return 0

        print(f"☁️  Cloud Backups ({manager.provider.get_provider_name()})")
        print(f"=" * 70)
        print(f"\nFound {len(backups)} backup(s):\n")

        for backup in backups:
            size_mb = backup.get('size', 0) / (1024 * 1024)
            created = backup.get('created', 'unknown')

            print(f"  📄 {backup['name']}")
            print(f"     ID: {backup['id']}")
            print(f"     Size: {size_mb:.2f} MB")
            print(f"     Created: {created}")
            print()

        return 0

    def cloud_providers(self, args) -> int:
        """List available cloud backup providers"""
        from backup import list_providers

        providers = list_providers()

        if not providers:
            print("No backup providers available")
            return 1

        print("☁️  Available Cloud Backup Providers")
        print("=" * 70)
        print()

        for name, info in sorted(providers.items()):
            status = "✅" if info['available'] else "❌"
            print(f"{status} {name}")
            print(f"   Name: {info['friendly_name']}")
            print(f"   Available: {'Yes' if info['available'] else 'No (missing dependencies)'}")

            if info['required_config']:
                print(f"   Required config: {', '.join(info['required_config'])}")

            print()

        return 0

    def cloud_cleanup(self, args) -> int:
        """Cleanup old cloud backups"""
        config_path = Path(args.config) if hasattr(args, 'config') and args.config else None
        manager = self._create_manager(args.provider, config_path)

        if not manager:
            return 1

        logger.info(f"Cleaning up old backups from {manager.provider.get_provider_name()}...")

        deleted = manager.cleanup()
        print(f"✅ Cleaned up {deleted} old backup(s)")

        return 0

    def cloud_test(self, args) -> int:
        """Test cloud backup connection"""
        config_path = Path(args.config) if hasattr(args, 'config') and args.config else None
        manager = self._create_manager(args.provider, config_path)

        if not manager:
            return 1

        print(f"Testing connection to {manager.provider.get_provider_name()}...")

        if manager.test_connection():
            print(f"✅ Connection successful")
            return 0
        else:
            print(f"❌ Connection failed")
            return 1

    # ========== Setup Helpers ==========

    def _setup_gdrive(self) -> int:
        """Setup Google Drive backup"""
        print("☁️  Google Drive Backup Setup")
        print("=" * 70)
        print()
        print("To use Google Drive backups, you need:")
        print("1. Google Cloud Project with Drive API enabled")
        print("2. OAuth 2.0 credentials (credentials.json)")
        print()
        print("Steps:")
        print("1. Go to: https://console.cloud.google.com/")
        print("2. Create a new project or select existing")
        print("3. Enable the Google Drive API")
        print("4. Create OAuth 2.0 credentials (Desktop app)")
        print("5. Download credentials.json")
        print("6. Save to: ~/.config/templedb/gdrive_credentials.json")
        print()
        print("Then run:")
        print("  ./templedb backup cloud test --provider gdrive")
        print()

        # Check if credentials exist
        creds_path = self.config_dir / 'gdrive_credentials.json'
        if creds_path.exists():
            print(f"✅ Credentials found: {creds_path}")
        else:
            print(f"❌ Credentials not found: {creds_path}")
            print("   Please download and save your credentials.json there")

        return 0

    def _setup_gcs(self) -> int:
        """Setup Google Cloud Storage backup"""
        print("☁️  Google Cloud Storage Backup Setup")
        print("=" * 70)
        print()
        print("See detailed setup guide:")
        print("  docs/GCS_BACKUP_SETUP.md")
        print()
        print("Quick start:")
        print("1. Create GCS bucket")
        print("2. Create service account with Storage Object Admin role")
        print("3. Download service account key JSON")
        print("4. Store credentials in TempleDB secrets:")
        print()
        print("   ./templedb secret init system_config")
        print("   ./templedb secret edit system_config")
        print()
        print("   Add to secrets:")
        print("   GCS_BUCKET_NAME=your-bucket-name")
        print("   GCS_SERVICE_ACCOUNT_KEY=<paste JSON key>")
        print()
        print("Then test:")
        print("  ./templedb backup cloud test --provider gcs")
        print()

        return 0

    def _setup_local(self) -> int:
        """Setup local filesystem backup"""
        print("💾 Local Filesystem Backup Setup")
        print("=" * 70)
        print()
        print("Local backups are always available!")
        print()
        print("Default backup directory:")
        print(f"  {Path.home() / '.local' / 'share' / 'templedb' / 'backups'}")
        print()
        print("To use a custom directory, create a config file:")
        print()
        print("Example config.json:")
        print('{')
        print('  "provider": "local",')
        print('  "config": {')
        print('    "backup_dir": "/path/to/backups",')
        print('    "retention_days": 30,')
        print('    "max_backups": 10')
        print('  }')
        print('}')
        print()
        print("Then use:")
        print("  ./templedb backup cloud push --provider local --config config.json")
        print()

        return 0


def register(cli):
    """Register unified backup commands"""
    cmd = BackupCommands()

    # Main backup command with subcommands
    backup_parser = cli.register_command('backup', None, help_text='Database backup operations (local and cloud)')
    subparsers = backup_parser.add_subparsers(dest='backup_subcommand', required=True)

    # ========== Local Backup Subcommands ==========

    # backup local [path]
    local_parser = subparsers.add_parser('local', help='Create local database backup')
    local_parser.add_argument('path', nargs='?', help='Backup file path (default: auto-generated)')
    cli.commands['backup.local'] = cmd.local_backup

    # backup restore <path>
    restore_parser = subparsers.add_parser('restore', help='Restore database from local backup')
    restore_parser.add_argument('path', help='Backup file path')
    cli.commands['backup.restore'] = cmd.restore

    # ========== Cloud Backup Subcommands ==========

    # backup cloud - nested subcommands
    cloud_parser = subparsers.add_parser('cloud', help='Cloud backup operations')
    cloud_subparsers = cloud_parser.add_subparsers(dest='cloud_subcommand', required=True)

    # backup cloud init <provider>
    init_parser = cloud_subparsers.add_parser('init', help='Initialize cloud backup provider')
    init_parser.add_argument('provider', help='Provider name (gdrive, gcs, s3, dropbox)')
    cli.commands['backup.cloud.init'] = cmd.cloud_init

    # backup cloud push
    push_parser = cloud_subparsers.add_parser('push', help='Upload backup to cloud')
    push_parser.add_argument('-p', '--provider', required=True, help='Backup provider')
    push_parser.add_argument('--db-path', type=str, help='Path to database file')
    push_parser.add_argument('--config', type=str, help='Provider configuration file')
    push_parser.add_argument('--keep-local', action='store_true', help='Keep local backup file')
    push_parser.add_argument('--no-cleanup', action='store_true', help='Skip cleanup of old backups')
    cli.commands['backup.cloud.push'] = cmd.cloud_push

    # backup cloud pull
    pull_parser = cloud_subparsers.add_parser('pull', help='Download backup from cloud')
    pull_parser.add_argument('-p', '--provider', required=True, help='Backup provider')
    pull_parser.add_argument('--backup-id', required=True, help='Backup identifier to restore')
    pull_parser.add_argument('--db-path', type=str, help='Path to restore database to')
    pull_parser.add_argument('--config', type=str, help='Provider configuration file')
    pull_parser.add_argument('--no-safety-backup', action='store_true', help='Skip creating safety backup')
    cli.commands['backup.cloud.pull'] = cmd.cloud_pull

    # backup cloud status
    status_parser = cloud_subparsers.add_parser('status', help='List cloud backups')
    status_parser.add_argument('-p', '--provider', required=True, help='Backup provider')
    status_parser.add_argument('--config', type=str, help='Provider configuration file')
    cli.commands['backup.cloud.status'] = cmd.cloud_status

    # backup cloud providers
    providers_parser = cloud_subparsers.add_parser('providers', help='List available cloud providers')
    cli.commands['backup.cloud.providers'] = cmd.cloud_providers

    # backup cloud cleanup
    cleanup_parser = cloud_subparsers.add_parser('cleanup', help='Clean up old cloud backups')
    cleanup_parser.add_argument('-p', '--provider', required=True, help='Backup provider')
    cleanup_parser.add_argument('--config', type=str, help='Provider configuration file')
    cli.commands['backup.cloud.cleanup'] = cmd.cloud_cleanup

    # backup cloud test
    test_parser = cloud_subparsers.add_parser('test', help='Test cloud provider connection')
    test_parser.add_argument('-p', '--provider', required=True, help='Backup provider')
    test_parser.add_argument('--config', type=str, help='Provider configuration file')
    cli.commands['backup.cloud.test'] = cmd.cloud_test

    # Create wrapper handler for cloud subcommands
    def cloud_handler(args):
        """Route cloud subcommands to appropriate handlers"""
        subcommand = args.cloud_subcommand
        if subcommand == 'init':
            return cmd.cloud_init(args)
        elif subcommand == 'push':
            return cmd.cloud_push(args)
        elif subcommand == 'pull':
            return cmd.cloud_pull(args)
        elif subcommand == 'status':
            return cmd.cloud_status(args)
        elif subcommand == 'providers':
            return cmd.cloud_providers(args)
        elif subcommand == 'cleanup':
            return cmd.cloud_cleanup(args)
        elif subcommand == 'test':
            return cmd.cloud_test(args)
        else:
            print(f"Unknown cloud subcommand: {subcommand}")
            return 1

    cli.commands['backup.cloud'] = cloud_handler
