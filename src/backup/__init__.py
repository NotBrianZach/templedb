"""
TempleDB Cloud Backup System

Pluggable cloud backup providers for TempleDB database backups.
"""

from pathlib import Path
from typing import Optional

from src.backup.base import CloudBackupProvider
from src.backup.registry import BackupProviderRegistry, get_provider

# Import available providers
try:
    from src.backup.gdrive_provider import GDriveBackupProvider
    BackupProviderRegistry.register('gdrive', GDriveBackupProvider)
    BackupProviderRegistry.register('google-drive', GDriveBackupProvider)
except ImportError:
    pass

try:
    from src.backup.dropbox_provider import DropboxBackupProvider
    BackupProviderRegistry.register('dropbox', DropboxBackupProvider)
except ImportError:
    pass

try:
    from src.backup.s3_provider import S3BackupProvider
    BackupProviderRegistry.register('s3', S3BackupProvider)
    BackupProviderRegistry.register('aws', S3BackupProvider)
except ImportError:
    pass

# Always available
from src.backup.local_provider import LocalBackupProvider
BackupProviderRegistry.register('local', LocalBackupProvider)
BackupProviderRegistry.register('filesystem', LocalBackupProvider)

__all__ = [
    'CloudBackupProvider',
    'BackupProviderRegistry',
    'get_provider',
    'list_providers',
]


def list_providers():
    """List all available backup providers"""
    return BackupProviderRegistry.list_providers()
