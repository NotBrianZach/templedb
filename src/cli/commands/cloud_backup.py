"""
Cloud backup CLI commands for TempleDB
"""

import sys
from pathlib import Path
from typing import Optional

from src.cli.commands.base import Command
from src.backup import get_provider, list_providers
from src.backup.manager import BackupManager, DEFAULT_DB_PATH
from src.logger import get_logger

logger = get_logger(__name__)


class CloudBackupCommands(Command):
    """Cloud backup commands"""

    def __init__(self):
        super().__init__()
        self.default_db_path = DEFAULT_DB_PATH
        self.config_dir = Path.home() / '.config' / 'templedb'

    def setup_parser(self, subparsers):
        """Setup cloud backup subcommands"""

        # Main cloud-backup command
        backup_parser = subparsers.add_parser(
            'cloud-backup',
            aliases=['cb', 'cloud'],
            help='Cloud backup operations'
        )
        backup_subparsers = backup_parser.add_subparsers(dest='backup_command')

        # cloud-backup providers
        providers_parser = backup_subparsers.add_parser(
            'providers',
            help='List available backup providers'
        )
        providers_parser.set_defaults(func=self.list_providers)

        # cloud-backup backup
        do_backup_parser = backup_subparsers.add_parser(
            'backup',
            help='Backup database to cloud storage'
        )
        do_backup_parser.add_argument(
            '-p', '--provider',
            required=True,
            help='Backup provider (gdrive, s3, dropbox, local)'
        )
        do_backup_parser.add_argument(
            '--db-path',
            type=Path,
            default=self.default_db_path,
            help='Path to database file'
        )
        do_backup_parser.add_argument(
            '--config',
            type=Path,
            help='Provider configuration file'
        )
        do_backup_parser.add_argument(
            '--keep-local',
            action='store_true',
            help='Keep local backup file'
        )
        do_backup_parser.add_argument(
            '--no-cleanup',
            action='store_true',
            help='Skip cleanup of old backups'
        )
        do_backup_parser.set_defaults(func=self.do_backup)

        # cloud-backup list
        list_parser = backup_subparsers.add_parser(
            'list',
            help='List cloud backups'
        )
        list_parser.add_argument(
            '-p', '--provider',
            required=True,
            help='Backup provider'
        )
        list_parser.add_argument(
            '--config',
            type=Path,
            help='Provider configuration file'
        )
        list_parser.set_defaults(func=self.list_backups)

        # cloud-backup restore
        restore_parser = backup_subparsers.add_parser(
            'restore',
            help='Restore database from cloud backup'
        )
        restore_parser.add_argument(
            '-p', '--provider',
            required=True,
            help='Backup provider'
        )
        restore_parser.add_argument(
            '--backup-id',
            required=True,
            help='Backup identifier to restore'
        )
        restore_parser.add_argument(
            '--db-path',
            type=Path,
            default=self.default_db_path,
            help='Path to restore database to'
        )
        restore_parser.add_argument(
            '--config',
            type=Path,
            help='Provider configuration file'
        )
        restore_parser.add_argument(
            '--no-safety-backup',
            action='store_true',
            help='Skip creating safety backup before restore'
        )
        restore_parser.set_defaults(func=self.restore_backup)

        # cloud-backup cleanup
        cleanup_parser = backup_subparsers.add_parser(
            'cleanup',
            help='Clean up old backups'
        )
        cleanup_parser.add_argument(
            '-p', '--provider',
            required=True,
            help='Backup provider'
        )
        cleanup_parser.add_argument(
            '--config',
            type=Path,
            help='Provider configuration file'
        )
        cleanup_parser.set_defaults(func=self.cleanup_backups)

        # cloud-backup test
        test_parser = backup_subparsers.add_parser(
            'test',
            help='Test connection to backup provider'
        )
        test_parser.add_argument(
            '-p', '--provider',
            required=True,
            help='Backup provider'
        )
        test_parser.add_argument(
            '--config',
            type=Path,
            help='Provider configuration file'
        )
        test_parser.set_defaults(func=self.test_connection)

        # cloud-backup setup
        setup_parser = backup_subparsers.add_parser(
            'setup',
            help='Setup backup provider (creates config)'
        )
        setup_parser.add_argument(
            'provider',
            help='Backup provider to setup'
        )
        setup_parser.set_defaults(func=self.setup_provider)

    def list_providers(self, args) -> int:
        """List available backup providers"""
        providers = list_providers()

        if not providers:
            print("No backup providers available")
            return 1

        print("Available Backup Providers:\n")

        for name, info in sorted(providers.items()):
            status = "✓" if info['available'] else "✗"
            print(f"  {status} {name}")
            print(f"      Name: {info['friendly_name']}")
            print(f"      Available: {'Yes' if info['available'] else 'No (missing dependencies)'}")

            if info['required_config']:
                print(f"      Required config: {', '.join(info['required_config'])}")

            print()

        return 0

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

    def _create_manager(self, provider_name: str, config_path: Optional[Path], **kwargs) -> Optional[BackupManager]:
        """Create backup manager instance"""
        try:
            config = self._load_config(config_path) if config_path else {}

            if config is None:
                return None

            return BackupManager.from_provider_name(provider_name, config, **kwargs)

        except Exception as e:
            logger.error(f"Failed to create backup manager: {e}")
            return None

    def do_backup(self, args) -> int:
        """Perform cloud backup"""
        manager = self._create_manager(args.provider, args.config, db_path=args.db_path)

        if not manager:
            return 1

        logger.info(f"Starting backup to {manager.provider.get_provider_name()}...")

        if manager.backup(cleanup=not args.no_cleanup, keep_local=args.keep_local):
            print(f"✓ Backup completed successfully")
            return 0
        else:
            print(f"✗ Backup failed")
            return 1

    def list_backups(self, args) -> int:
        """List cloud backups"""
        manager = self._create_manager(args.provider, args.config)

        if not manager:
            return 1

        logger.info(f"Listing backups from {manager.provider.get_provider_name()}...")

        backups = manager.list_backups()

        if not backups:
            print("No backups found")
            return 0

        print(f"Found {len(backups)} backup(s) in {manager.provider.get_provider_name()}:\n")

        for backup in backups:
            size_mb = backup.get('size', 0) / (1024 * 1024)
            created = backup.get('created', 'unknown')

            print(f"  {backup['name']}")
            print(f"    ID: {backup['id']}")
            print(f"    Size: {size_mb:.2f} MB")
            print(f"    Created: {created}")
            print()

        return 0

    def restore_backup(self, args) -> int:
        """Restore from cloud backup"""
        manager = self._create_manager(args.provider, args.config, db_path=args.db_path)

        if not manager:
            return 1

        logger.info(f"Restoring from {manager.provider.get_provider_name()}...")

        if manager.restore(
            args.backup_id,
            args.db_path,
            create_backup=not args.no_safety_backup
        ):
            print(f"✓ Restore completed successfully")
            return 0
        else:
            print(f"✗ Restore failed")
            return 1

    def cleanup_backups(self, args) -> int:
        """Cleanup old backups"""
        manager = self._create_manager(args.provider, args.config)

        if not manager:
            return 1

        logger.info(f"Cleaning up old backups from {manager.provider.get_provider_name()}...")

        deleted = manager.cleanup()
        print(f"✓ Cleaned up {deleted} old backup(s)")

        return 0

    def test_connection(self, args) -> int:
        """Test connection to backup provider"""
        manager = self._create_manager(args.provider, args.config)

        if not manager:
            return 1

        print(f"Testing connection to {manager.provider.get_provider_name()}...")

        if manager.test_connection():
            print(f"✓ Connection successful")
            return 0
        else:
            print(f"✗ Connection failed")
            return 1

    def setup_provider(self, args) -> int:
        """Setup backup provider"""
        provider_name = args.provider.lower()

        if provider_name in ['gdrive', 'google-drive']:
            return self._setup_gdrive()
        elif provider_name == 'local':
            return self._setup_local()
        else:
            print(f"Setup not implemented for provider: {provider_name}")
            print("Please create a configuration file manually.")
            return 1

    def _setup_gdrive(self) -> int:
        """Setup Google Drive backup"""
        print("Google Drive Backup Setup")
        print("=" * 50)
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
        print("  templedb cloud-backup test -p gdrive")
        print()

        # Check if credentials exist
        creds_path = self.config_dir / 'gdrive_credentials.json'
        if creds_path.exists():
            print(f"✓ Credentials found: {creds_path}")
        else:
            print(f"✗ Credentials not found: {creds_path}")
            print("  Please download and save your credentials.json there")

        return 0

    def _setup_local(self) -> int:
        """Setup local filesystem backup"""
        print("Local Filesystem Backup Setup")
        print("=" * 50)
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
        print("  templedb cloud-backup backup -p local --config config.json")
        print()

        return 0
