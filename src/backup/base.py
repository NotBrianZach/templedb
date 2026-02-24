"""
Abstract base class for cloud backup providers
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime


class CloudBackupProvider(ABC):
    """
    Abstract base class for cloud backup providers.

    All backup providers must implement these methods to be compatible
    with TempleDB's backup system.
    """

    def __init__(
        self,
        retention_days: int = 30,
        max_backups: int = 10,
        **kwargs
    ):
        """
        Initialize the backup provider.

        Args:
            retention_days: Days to keep backups
            max_backups: Maximum number of backups to keep
            **kwargs: Provider-specific configuration
        """
        self.retention_days = retention_days
        self.max_backups = max_backups
        self.config = kwargs
        self.authenticated = False

    @abstractmethod
    def authenticate(self) -> bool:
        """
        Authenticate with the cloud service.

        Returns:
            True if authentication successful, False otherwise
        """
        pass

    @abstractmethod
    def upload_file(self, file_path: Path, remote_name: Optional[str] = None) -> Optional[str]:
        """
        Upload a file to cloud storage.

        Args:
            file_path: Path to local file
            remote_name: Optional remote filename (defaults to local filename)

        Returns:
            Remote file identifier (URL, ID, etc.) or None on failure
        """
        pass

    @abstractmethod
    def download_file(self, remote_id: str, destination: Path) -> bool:
        """
        Download a file from cloud storage.

        Args:
            remote_id: Remote file identifier
            destination: Local path to save file

        Returns:
            True if successful, False otherwise
        """
        pass

    @abstractmethod
    def list_backups(self) -> List[Dict[str, Any]]:
        """
        List all backups in cloud storage.

        Returns:
            List of backup metadata dictionaries. Each dict must contain:
                - id: Remote file identifier
                - name: Filename
                - size: Size in bytes
                - created: Creation datetime (ISO format string or datetime object)
        """
        pass

    @abstractmethod
    def delete_backup(self, remote_id: str) -> bool:
        """
        Delete a backup from cloud storage.

        Args:
            remote_id: Remote file identifier

        Returns:
            True if successful, False otherwise
        """
        pass

    def cleanup_old_backups(self) -> int:
        """
        Clean up old backups based on retention policy.

        This is a default implementation that can be overridden by providers.

        Returns:
            Number of backups deleted
        """
        from datetime import timedelta
        from src.logger import get_logger

        logger = get_logger(__name__)
        backups = self.list_backups()

        if not backups:
            return 0

        deleted_count = 0
        cutoff_date = datetime.now() - timedelta(days=self.retention_days)

        # Sort by creation time (oldest first)
        def get_created_time(backup):
            created = backup.get('created')
            if isinstance(created, str):
                # Parse ISO format
                return datetime.fromisoformat(created.replace('Z', '+00:00'))
            return created

        backups_sorted = sorted(backups, key=get_created_time)

        for backup in backups_sorted:
            created_time = get_created_time(backup)

            # Delete if too old or exceeds max count
            should_delete = (
                created_time < cutoff_date or
                (len(backups) - deleted_count) > self.max_backups
            )

            if should_delete:
                logger.info(f"Deleting old backup: {backup['name']} (created: {backup.get('created')})")
                if self.delete_backup(backup['id']):
                    deleted_count += 1

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old backup(s)")

        return deleted_count

    @classmethod
    def get_provider_name(cls) -> str:
        """
        Get the provider name.

        Can be overridden to provide a friendly name.
        """
        return cls.__name__.replace('Provider', '').replace('Backup', '')

    @classmethod
    def get_required_config(cls) -> List[str]:
        """
        Get list of required configuration keys.

        Override to specify provider-specific required config.
        """
        return []

    @classmethod
    def is_available(cls) -> bool:
        """
        Check if this provider is available (dependencies installed, etc).

        Override to check for required dependencies.
        """
        return True

    def test_connection(self) -> bool:
        """
        Test connection to cloud service.

        Returns:
            True if connection successful, False otherwise
        """
        if not self.authenticate():
            return False

        # Try to list backups as a connection test
        try:
            self.list_backups()
            return True
        except Exception:
            return False
