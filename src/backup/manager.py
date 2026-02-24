"""
Unified backup manager for TempleDB

Handles database backups using pluggable cloud providers.
"""

import sqlite3
from pathlib import Path
from typing import Optional
from datetime import datetime

from src.backup.base import CloudBackupProvider
from src.backup.registry import get_provider, load_provider_from_config
from src.logger import get_logger

logger = get_logger(__name__)

DEFAULT_DB_PATH = Path.home() / '.local' / 'share' / 'templedb' / 'templedb.sqlite'
DEFAULT_TEMP_DIR = Path.home() / '.local' / 'share' / 'templedb' / 'tmp'


class BackupManager:
    """
    Unified backup manager for TempleDB.

    Handles database backups using any registered cloud provider.
    """

    def __init__(
        self,
        provider: CloudBackupProvider,
        db_path: Path = DEFAULT_DB_PATH,
        temp_dir: Path = DEFAULT_TEMP_DIR
    ):
        """
        Initialize backup manager.

        Args:
            provider: Cloud backup provider instance
            db_path: Path to database file
            temp_dir: Temporary directory for local backups
        """
        self.provider = provider
        self.db_path = db_path
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_config(cls, config_path: Path, **kwargs) -> 'BackupManager':
        """
        Create backup manager from configuration file.

        Args:
            config_path: Path to configuration file
            **kwargs: Additional arguments for BackupManager

        Returns:
            BackupManager instance
        """
        provider = load_provider_from_config(config_path)
        return cls(provider, **kwargs)

    @classmethod
    def from_provider_name(cls, provider_name: str, config: Optional[dict] = None, **kwargs) -> 'BackupManager':
        """
        Create backup manager from provider name.

        Args:
            provider_name: Provider identifier (e.g., 'gdrive', 's3')
            config: Provider configuration
            **kwargs: Additional arguments for BackupManager

        Returns:
            BackupManager instance
        """
        provider = get_provider(provider_name, config)
        return cls(provider, **kwargs)

    def create_local_backup(self) -> Optional[Path]:
        """
        Create local database backup.

        Returns:
            Path to backup file or None on error
        """
        if not self.db_path.exists():
            logger.error(f"Database not found: {self.db_path}")
            return None

        # Generate backup filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"templedb_backup_{timestamp}.sqlite"
        backup_path = self.temp_dir / backup_filename

        try:
            logger.info(f"Creating local backup: {backup_path}")

            # Use SQLite backup API for online backup
            source = sqlite3.connect(str(self.db_path))
            dest = sqlite3.connect(str(backup_path))

            with dest:
                source.backup(dest)

            source.close()
            dest.close()

            # Get file size
            size_mb = backup_path.stat().st_size / (1024 * 1024)
            logger.info(f"Local backup created successfully ({size_mb:.2f} MB)")

            return backup_path

        except Exception as e:
            logger.error(f"Failed to create local backup: {e}", exc_info=True)
            if backup_path.exists():
                backup_path.unlink()
            return None

    def backup(
        self,
        cleanup: bool = True,
        keep_local: bool = False
    ) -> bool:
        """
        Perform full backup to cloud storage.

        Args:
            cleanup: Whether to cleanup old backups
            keep_local: Whether to keep local backup file

        Returns:
            True if successful, False otherwise
        """
        # Authenticate with provider
        if not self.provider.authenticate():
            logger.error("Failed to authenticate with backup provider")
            return False

        # Create local backup
        backup_path = self.create_local_backup()
        if not backup_path:
            return False

        try:
            # Upload to cloud
            logger.info(f"Uploading to {self.provider.get_provider_name()}...")
            remote_id = self.provider.upload_file(backup_path)

            if not remote_id:
                logger.error("Failed to upload backup")
                return False

            logger.info(f"Backup uploaded successfully (ID: {remote_id})")

            # Cleanup old backups
            if cleanup:
                logger.info("Cleaning up old backups...")
                deleted = self.provider.cleanup_old_backups()
                if deleted > 0:
                    logger.info(f"Deleted {deleted} old backup(s)")

            logger.info("Backup completed successfully")
            return True

        except Exception as e:
            logger.error(f"Backup failed: {e}", exc_info=True)
            return False

        finally:
            # Remove local backup unless requested to keep
            if not keep_local and backup_path.exists():
                try:
                    backup_path.unlink()
                    logger.debug(f"Removed temporary backup: {backup_path}")
                except Exception as e:
                    logger.warning(f"Failed to remove temporary backup: {e}")

    def list_backups(self):
        """
        List all available backups.

        Returns:
            List of backup metadata dictionaries
        """
        if not self.provider.authenticate():
            logger.error("Failed to authenticate with backup provider")
            return []

        return self.provider.list_backups()

    def restore(
        self,
        remote_id: str,
        destination: Optional[Path] = None,
        create_backup: bool = True
    ) -> bool:
        """
        Restore database from backup.

        Args:
            remote_id: Remote backup identifier
            destination: Where to restore (defaults to current db_path)
            create_backup: Create safety backup before restoring

        Returns:
            True if successful, False otherwise
        """
        if not self.provider.authenticate():
            logger.error("Failed to authenticate with backup provider")
            return False

        destination = destination or self.db_path

        # Create safety backup of current database
        if create_backup and destination.exists():
            logger.info("Creating safety backup of current database...")
            safety_backup = destination.parent / f"{destination.stem}_pre_restore_{int(datetime.now().timestamp())}.sqlite"

            try:
                import shutil
                shutil.copy2(destination, safety_backup)
                logger.info(f"Safety backup created: {safety_backup}")
            except Exception as e:
                logger.error(f"Failed to create safety backup: {e}")
                return False

        # Download backup to temporary location
        temp_restore = self.temp_dir / f"restore_{int(datetime.now().timestamp())}.sqlite"

        try:
            logger.info("Downloading backup...")
            if not self.provider.download_file(remote_id, temp_restore):
                logger.error("Failed to download backup")
                return False

            # Verify it's a valid SQLite database
            try:
                conn = sqlite3.connect(str(temp_restore))
                conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
                conn.close()
                logger.info("Backup file validated")
            except Exception as e:
                logger.error(f"Downloaded file is not a valid SQLite database: {e}")
                temp_restore.unlink()
                return False

            # Move to destination
            logger.info(f"Restoring to {destination}...")
            import shutil
            shutil.move(str(temp_restore), str(destination))

            logger.info("Restore completed successfully")
            return True

        except Exception as e:
            logger.error(f"Restore failed: {e}", exc_info=True)
            if temp_restore.exists():
                temp_restore.unlink()
            return False

    def cleanup(self) -> int:
        """
        Cleanup old backups based on retention policy.

        Returns:
            Number of backups deleted
        """
        if not self.provider.authenticate():
            logger.error("Failed to authenticate with backup provider")
            return 0

        return self.provider.cleanup_old_backups()

    def test_connection(self) -> bool:
        """
        Test connection to backup provider.

        Returns:
            True if connection successful, False otherwise
        """
        return self.provider.test_connection()
