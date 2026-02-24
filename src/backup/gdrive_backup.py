#!/usr/bin/env python3
"""
Google Drive Backup Module for TempleDB

Provides automated backup to Google Drive with rotation and retention policies.
"""

import os
import sys
import json
import time
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
    GDRIVE_AVAILABLE = True
except ImportError:
    GDRIVE_AVAILABLE = False

from src.logger import get_logger

logger = get_logger(__name__)

# Google Drive API scopes
SCOPES = ['https://www.googleapis.com/auth/drive.file']

# Default backup settings
DEFAULT_BACKUP_DIR = Path.home() / '.local' / 'share' / 'templedb' / 'backups'
DEFAULT_GDRIVE_FOLDER = 'TempleDB Backups'
DEFAULT_RETENTION_DAYS = 30
DEFAULT_MAX_BACKUPS = 10


class GDriveBackupError(Exception):
    """Base exception for Google Drive backup errors"""
    pass


class GDriveBackup:
    """Google Drive backup manager for TempleDB"""

    def __init__(
        self,
        credentials_path: Optional[Path] = None,
        token_path: Optional[Path] = None,
        folder_name: str = DEFAULT_GDRIVE_FOLDER,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        max_backups: int = DEFAULT_MAX_BACKUPS
    ):
        """
        Initialize Google Drive backup manager.

        Args:
            credentials_path: Path to OAuth2 credentials.json
            token_path: Path to store authentication token
            folder_name: Name of folder in Google Drive
            retention_days: Days to keep backups
            max_backups: Maximum number of backups to keep
        """
        if not GDRIVE_AVAILABLE:
            raise GDriveBackupError(
                "Google Drive libraries not installed. "
                "Install with: pip install google-auth google-auth-oauthlib google-api-python-client"
            )

        self.credentials_path = credentials_path or self._default_credentials_path()
        self.token_path = token_path or self._default_token_path()
        self.folder_name = folder_name
        self.retention_days = retention_days
        self.max_backups = max_backups
        self.service = None
        self.folder_id = None

    def _default_credentials_path(self) -> Path:
        """Get default credentials path"""
        return Path.home() / '.config' / 'templedb' / 'gdrive_credentials.json'

    def _default_token_path(self) -> Path:
        """Get default token path"""
        return Path.home() / '.config' / 'templedb' / 'gdrive_token.json'

    def authenticate(self) -> bool:
        """
        Authenticate with Google Drive API.

        Returns:
            True if authentication successful, False otherwise
        """
        creds = None

        # Load existing token
        if self.token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)
                logger.debug(f"Loaded credentials from {self.token_path}")
            except Exception as e:
                logger.warning(f"Failed to load credentials: {e}")

        # Refresh or get new credentials
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    logger.info("Refreshed expired credentials")
                except Exception as e:
                    logger.error(f"Failed to refresh credentials: {e}")
                    creds = None

            if not creds:
                if not self.credentials_path.exists():
                    logger.error(f"Credentials file not found: {self.credentials_path}")
                    logger.error("See documentation for setup instructions")
                    return False

                try:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self.credentials_path), SCOPES
                    )
                    creds = flow.run_local_server(port=0)
                    logger.info("Obtained new credentials via OAuth2 flow")
                except Exception as e:
                    logger.error(f"Failed to authenticate: {e}")
                    return False

            # Save credentials
            try:
                self.token_path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.token_path, 'w') as token:
                    token.write(creds.to_json())
                logger.debug(f"Saved credentials to {self.token_path}")
            except Exception as e:
                logger.warning(f"Failed to save credentials: {e}")

        # Build service
        try:
            self.service = build('drive', 'v3', credentials=creds)
            logger.info("Successfully authenticated with Google Drive")
            return True
        except Exception as e:
            logger.error(f"Failed to build Google Drive service: {e}")
            return False

    def _get_or_create_folder(self) -> Optional[str]:
        """
        Get or create backup folder in Google Drive.

        Returns:
            Folder ID or None on error
        """
        if self.folder_id:
            return self.folder_id

        try:
            # Search for existing folder
            query = f"name='{self.folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name)'
            ).execute()

            files = results.get('files', [])

            if files:
                self.folder_id = files[0]['id']
                logger.info(f"Found existing folder: {self.folder_name} (ID: {self.folder_id})")
                return self.folder_id

            # Create new folder
            folder_metadata = {
                'name': self.folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = self.service.files().create(
                body=folder_metadata,
                fields='id'
            ).execute()

            self.folder_id = folder.get('id')
            logger.info(f"Created folder: {self.folder_name} (ID: {self.folder_id})")
            return self.folder_id

        except HttpError as e:
            logger.error(f"Failed to get/create folder: {e}")
            return None

    def create_local_backup(self, db_path: Path, backup_dir: Path = DEFAULT_BACKUP_DIR) -> Optional[Path]:
        """
        Create local database backup.

        Args:
            db_path: Path to database file
            backup_dir: Directory to store backup

        Returns:
            Path to backup file or None on error
        """
        if not db_path.exists():
            logger.error(f"Database not found: {db_path}")
            return None

        # Create backup directory
        backup_dir.mkdir(parents=True, exist_ok=True)

        # Generate backup filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        backup_filename = f"templedb_backup_{timestamp}.sqlite"
        backup_path = backup_dir / backup_filename

        try:
            # Use SQLite backup API for online backup
            logger.info(f"Creating local backup: {backup_path}")

            source = sqlite3.connect(str(db_path))
            dest = sqlite3.connect(str(backup_path))

            with dest:
                source.backup(dest)

            source.close()
            dest.close()

            # Get file size
            size_mb = backup_path.stat().st_size / (1024 * 1024)
            logger.info(f"Backup created successfully ({size_mb:.2f} MB)")

            return backup_path

        except Exception as e:
            logger.error(f"Failed to create backup: {e}", exc_info=True)
            if backup_path.exists():
                backup_path.unlink()
            return None

    def upload_to_gdrive(self, file_path: Path) -> Optional[str]:
        """
        Upload file to Google Drive.

        Args:
            file_path: Path to file to upload

        Returns:
            File ID on Google Drive or None on error
        """
        if not self.service:
            logger.error("Not authenticated with Google Drive")
            return None

        folder_id = self._get_or_create_folder()
        if not folder_id:
            return None

        try:
            file_metadata = {
                'name': file_path.name,
                'parents': [folder_id]
            }

            media = MediaFileUpload(
                str(file_path),
                mimetype='application/x-sqlite3',
                resumable=True
            )

            logger.info(f"Uploading {file_path.name} to Google Drive...")

            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, size, createdTime'
            ).execute()

            file_id = file.get('id')
            size_mb = int(file.get('size', 0)) / (1024 * 1024)

            logger.info(f"Upload successful: {file.get('name')} ({size_mb:.2f} MB, ID: {file_id})")

            return file_id

        except HttpError as e:
            logger.error(f"Failed to upload file: {e}")
            return None

    def list_backups(self) -> List[Dict[str, Any]]:
        """
        List all backups in Google Drive folder.

        Returns:
            List of backup file metadata
        """
        if not self.service:
            logger.error("Not authenticated with Google Drive")
            return []

        folder_id = self._get_or_create_folder()
        if not folder_id:
            return []

        try:
            query = f"'{folder_id}' in parents and trashed=false"
            results = self.service.files().list(
                q=query,
                spaces='drive',
                fields='files(id, name, size, createdTime, modifiedTime)',
                orderBy='createdTime desc'
            ).execute()

            files = results.get('files', [])
            logger.debug(f"Found {len(files)} backups in Google Drive")

            return files

        except HttpError as e:
            logger.error(f"Failed to list backups: {e}")
            return []

    def delete_backup(self, file_id: str) -> bool:
        """
        Delete a backup from Google Drive.

        Args:
            file_id: Google Drive file ID

        Returns:
            True if successful, False otherwise
        """
        if not self.service:
            logger.error("Not authenticated with Google Drive")
            return False

        try:
            self.service.files().delete(fileId=file_id).execute()
            logger.info(f"Deleted backup: {file_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to delete backup: {e}")
            return False

    def cleanup_old_backups(self) -> int:
        """
        Clean up old backups based on retention policy.

        Returns:
            Number of backups deleted
        """
        backups = self.list_backups()
        if not backups:
            return 0

        deleted_count = 0
        cutoff_date = datetime.now() - timedelta(days=self.retention_days)

        # Sort by creation time (oldest first)
        backups_sorted = sorted(backups, key=lambda x: x['createdTime'])

        for backup in backups_sorted:
            # Parse creation time
            created_time = datetime.fromisoformat(backup['createdTime'].replace('Z', '+00:00'))

            # Delete if too old or exceeds max count
            should_delete = (
                created_time < cutoff_date or
                (len(backups) - deleted_count) > self.max_backups
            )

            if should_delete:
                logger.info(f"Deleting old backup: {backup['name']} (created: {backup['createdTime']})")
                if self.delete_backup(backup['id']):
                    deleted_count += 1

        if deleted_count > 0:
            logger.info(f"Cleaned up {deleted_count} old backup(s)")

        return deleted_count

    def backup(
        self,
        db_path: Path,
        cleanup: bool = True,
        keep_local: bool = False
    ) -> bool:
        """
        Perform full backup to Google Drive.

        Args:
            db_path: Path to database file
            cleanup: Whether to cleanup old backups
            keep_local: Whether to keep local backup file

        Returns:
            True if successful, False otherwise
        """
        # Authenticate
        if not self.service:
            if not self.authenticate():
                return False

        # Create local backup
        backup_path = self.create_local_backup(db_path)
        if not backup_path:
            return False

        try:
            # Upload to Google Drive
            file_id = self.upload_to_gdrive(backup_path)
            if not file_id:
                return False

            # Cleanup old backups
            if cleanup:
                self.cleanup_old_backups()

            logger.info("Backup completed successfully")
            return True

        finally:
            # Remove local backup unless requested to keep
            if not keep_local and backup_path.exists():
                try:
                    backup_path.unlink()
                    logger.debug(f"Removed local backup: {backup_path}")
                except Exception as e:
                    logger.warning(f"Failed to remove local backup: {e}")

    def download_backup(self, file_id: str, destination: Path) -> bool:
        """
        Download a backup from Google Drive.

        Args:
            file_id: Google Drive file ID
            destination: Local path to save file

        Returns:
            True if successful, False otherwise
        """
        if not self.service:
            logger.error("Not authenticated with Google Drive")
            return False

        try:
            request = self.service.files().get_media(fileId=file_id)

            logger.info(f"Downloading backup to {destination}...")

            destination.parent.mkdir(parents=True, exist_ok=True)

            with open(destination, 'wb') as f:
                from googleapiclient.http import MediaIoBaseDownload
                downloader = MediaIoBaseDownload(f, request)

                done = False
                while not done:
                    status, done = downloader.next_chunk()
                    if status:
                        logger.debug(f"Download progress: {int(status.progress() * 100)}%")

            size_mb = destination.stat().st_size / (1024 * 1024)
            logger.info(f"Download complete ({size_mb:.2f} MB)")

            return True

        except HttpError as e:
            logger.error(f"Failed to download backup: {e}")
            return False


def main():
    """CLI interface for Google Drive backup"""
    import argparse

    parser = argparse.ArgumentParser(description='TempleDB Google Drive Backup')
    parser.add_argument('command', choices=['backup', 'list', 'download', 'cleanup', 'test'],
                        help='Command to execute')
    parser.add_argument('--db-path', type=Path,
                        default=Path.home() / '.local' / 'share' / 'templedb' / 'templedb.sqlite',
                        help='Path to database file')
    parser.add_argument('--file-id', help='Google Drive file ID (for download)')
    parser.add_argument('--output', type=Path, help='Output path (for download)')
    parser.add_argument('--keep-local', action='store_true',
                        help='Keep local backup file')
    parser.add_argument('--no-cleanup', action='store_true',
                        help='Skip cleanup of old backups')

    args = parser.parse_args()

    gdrive = GDriveBackup()

    if args.command == 'test':
        if gdrive.authenticate():
            print("✓ Authentication successful")
            print(f"✓ Using folder: {gdrive.folder_name}")
            return 0
        else:
            print("✗ Authentication failed")
            return 1

    elif args.command == 'backup':
        if gdrive.backup(args.db_path, cleanup=not args.no_cleanup, keep_local=args.keep_local):
            print("✓ Backup completed successfully")
            return 0
        else:
            print("✗ Backup failed")
            return 1

    elif args.command == 'list':
        if not gdrive.authenticate():
            return 1

        backups = gdrive.list_backups()
        if not backups:
            print("No backups found")
            return 0

        print(f"Found {len(backups)} backup(s):\n")
        for backup in backups:
            size_mb = int(backup.get('size', 0)) / (1024 * 1024)
            created = backup.get('createdTime', 'unknown')
            print(f"  {backup['name']}")
            print(f"    ID: {backup['id']}")
            print(f"    Size: {size_mb:.2f} MB")
            print(f"    Created: {created}")
            print()

        return 0

    elif args.command == 'download':
        if not args.file_id:
            print("Error: --file-id required for download")
            return 1

        if not args.output:
            args.output = Path(f"templedb_restored_{int(time.time())}.sqlite")

        if not gdrive.authenticate():
            return 1

        if gdrive.download_backup(args.file_id, args.output):
            print(f"✓ Downloaded to {args.output}")
            return 0
        else:
            print("✗ Download failed")
            return 1

    elif args.command == 'cleanup':
        if not gdrive.authenticate():
            return 1

        count = gdrive.cleanup_old_backups()
        print(f"✓ Cleaned up {count} old backup(s)")
        return 0


if __name__ == '__main__':
    sys.exit(main())
