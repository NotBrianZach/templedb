"""
TempleDB Cloud Backup System

Pluggable cloud backup providers for TempleDB database backups.
"""

from pathlib import Path
from typing import Optional

from backup.base import CloudBackupProvider
from backup.registry import BackupProviderRegistry, get_provider

# Import available providers
try:
    from backup.gdrive_provider import GDriveBackupProvider
    BackupProviderRegistry.register('gdrive', GDriveBackupProvider)
    BackupProviderRegistry.register('google-drive', GDriveBackupProvider)
except ImportError:
    pass

try:
    from backup.dropbox_provider import DropboxBackupProvider
    BackupProviderRegistry.register('dropbox', DropboxBackupProvider)
except ImportError:
    pass

try:
    from backup.s3_provider import S3BackupProvider
    BackupProviderRegistry.register('s3', S3BackupProvider)
    BackupProviderRegistry.register('aws', S3BackupProvider)
except ImportError:
    pass

# Always available
from backup.local_provider import LocalBackupProvider
BackupProviderRegistry.register('local', LocalBackupProvider)
BackupProviderRegistry.register('filesystem', LocalBackupProvider)

try:
    from backup.gcs_provider import GCSBackupProvider
    BackupProviderRegistry.register('gcs', GCSBackupProvider)
    BackupProviderRegistry.register('google-cloud-storage', GCSBackupProvider)
except ImportError:
    pass

__all__ = [
    'CloudBackupProvider',
    'BackupProviderRegistry',
    'get_provider',
    'list_providers',
]


def list_providers():
    """List all available backup providers"""
    return BackupProviderRegistry.list_providers()
