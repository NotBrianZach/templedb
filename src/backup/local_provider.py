"""
Local filesystem backup provider for TempleDB

Provides a simple file-based backup system for local or network storage.
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import shutil

from src.backup.base import CloudBackupProvider
from src.logger import get_logger

logger = get_logger(__name__)


class LocalBackupProvider(CloudBackupProvider):
    """Local filesystem backup provider"""

    def __init__(
        self,
        backup_dir: Optional[Path] = None,
        **kwargs
    ):
        """
        Initialize local backup provider.

        Args:
            backup_dir: Directory to store backups
            **kwargs: Base class arguments (retention_days, max_backups)
        """
        super().__init__(**kwargs)

        self.backup_dir = backup_dir or self._default_backup_dir()
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def _default_backup_dir(self) -> Path:
        """Get default backup directory"""
        return Path.home() / '.local' / 'share' / 'templedb' / 'backups'

    def authenticate(self) -> bool:
        """No authentication needed for local filesystem"""
        if not self.backup_dir.exists():
            try:
                self.backup_dir.mkdir(parents=True, exist_ok=True)
                logger.debug(f"Created backup directory: {self.backup_dir}")
            except Exception as e:
                logger.error(f"Failed to create backup directory: {e}")
                return False

        self.authenticated = True
        return True

    def upload_file(self, file_path: Path, remote_name: Optional[str] = None) -> Optional[str]:
        """Copy file to backup directory"""
        if not self.authenticated:
            if not self.authenticate():
                return None

        remote_name = remote_name or file_path.name
        destination = self.backup_dir / remote_name

        try:
            logger.info(f"Copying {file_path.name} to {destination}")
            shutil.copy2(file_path, destination)

            size_mb = destination.stat().st_size / (1024 * 1024)
            logger.info(f"Backup saved: {destination} ({size_mb:.2f} MB)")

            # Return path as ID
            return str(destination)

        except Exception as e:
            logger.error(f"Failed to copy file: {e}")
            return None

    def download_file(self, remote_id: str, destination: Path) -> bool:
        """Copy backup file to destination"""
        if not self.authenticated:
            if not self.authenticate():
                return False

        source = Path(remote_id)

        if not source.exists():
            logger.error(f"Backup file not found: {source}")
            return False

        try:
            logger.info(f"Copying {source} to {destination}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

            size_mb = destination.stat().st_size / (1024 * 1024)
            logger.info(f"Restore complete: {destination} ({size_mb:.2f} MB)")

            return True

        except Exception as e:
            logger.error(f"Failed to copy file: {e}")
            return False

    def list_backups(self) -> List[Dict[str, Any]]:
        """List all backup files in directory"""
        if not self.authenticated:
            if not self.authenticate():
                return []

        try:
            backups = []

            for file_path in self.backup_dir.glob('*.sqlite'):
                stat = file_path.stat()

                backups.append({
                    'id': str(file_path),
                    'name': file_path.name,
                    'size': stat.st_size,
                    'created': datetime.fromtimestamp(stat.st_ctime).isoformat(),
                    'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                })

            # Sort by creation time (newest first)
            backups.sort(key=lambda x: x['created'], reverse=True)

            logger.debug(f"Found {len(backups)} backups in {self.backup_dir}")
            return backups

        except Exception as e:
            logger.error(f"Failed to list backups: {e}")
            return []

    def delete_backup(self, remote_id: str) -> bool:
        """Delete backup file"""
        if not self.authenticated:
            if not self.authenticate():
                return False

        file_path = Path(remote_id)

        if not file_path.exists():
            logger.warning(f"Backup file not found: {file_path}")
            return False

        try:
            file_path.unlink()
            logger.info(f"Deleted backup: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete backup: {e}")
            return False

    @classmethod
    def get_provider_name(cls) -> str:
        return "Local Filesystem"

    @classmethod
    def get_required_config(cls) -> List[str]:
        return []  # Optional: backup_dir

    @classmethod
    def is_available(cls) -> bool:
        return True  # Always available
