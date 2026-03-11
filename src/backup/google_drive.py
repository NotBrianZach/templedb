#!/usr/bin/env python3
"""
Google Drive Backup Integration for TempleDB
Handles database backups to Google Drive
"""

import os
import json
import pickle
import datetime
from pathlib import Path
from typing import Optional, List, Dict
from logger import get_logger

logger = get_logger(__name__)


class GoogleDriveBackup:
    """
    Google Drive backup manager for TempleDB

    Uses Google Drive API v3 to upload and manage database backups
    """

    SCOPES = ['https://www.googleapis.com/auth/drive.file']
    BACKUP_FOLDER_NAME = 'TempleDB Backups'

    def __init__(self, credentials_file: Optional[str] = None, token_file: Optional[str] = None):
        """
        Initialize Google Drive backup manager

        Args:
            credentials_file: Path to OAuth2 credentials JSON (from Google Cloud Console)
            token_file: Path to store authentication token
        """
        self.credentials_file = credentials_file or os.path.expanduser('~/.templedb/google_credentials.json')
        self.token_file = token_file or os.path.expanduser('~/.templedb/google_token.pickle')

        self.service = None
        self.backup_folder_id = None

    def authenticate(self) -> bool:
        """
        Authenticate with Google Drive API

        Returns:
            True if authentication successful

        Raises:
            ImportError: If google-auth libraries not installed
            FileNotFoundError: If credentials file not found
        """
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError:
            raise ImportError(
                "Google Drive backup requires google-api-python-client. "
                "Install with: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
            )

        creds = None

        # Check for existing token
        if os.path.exists(self.token_file):
            with open(self.token_file, 'rb') as token:
                creds = pickle.load(token)

        # If no valid credentials, authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                logger.info("Refreshing Google Drive credentials...")
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_file):
                    raise FileNotFoundError(
                        f"Google Drive credentials not found at: {self.credentials_file}\n"
                        f"Download from: https://console.cloud.google.com/apis/credentials"
                    )

                logger.info("Authenticating with Google Drive...")
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, self.SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save credentials
            os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
            with open(self.token_file, 'wb') as token:
                pickle.dump(creds, token)

        # Build service
        self.service = build('drive', 'v3', credentials=creds)
        logger.info("✓ Authenticated with Google Drive")
        return True

    def _get_or_create_backup_folder(self) -> str:
        """
        Get or create the backup folder in Google Drive

        Returns:
            Folder ID
        """
        if self.backup_folder_id:
            return self.backup_folder_id

        # Search for existing folder
        query = f"name='{self.BACKUP_FOLDER_NAME}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
        results = self.service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)'
        ).execute()

        files = results.get('files', [])

        if files:
            self.backup_folder_id = files[0]['id']
            logger.info(f"Found existing backup folder: {self.backup_folder_id}")
        else:
            # Create folder
            folder_metadata = {
                'name': self.BACKUP_FOLDER_NAME,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            folder = self.service.files().create(
                body=folder_metadata,
                fields='id'
            ).execute()
            self.backup_folder_id = folder['id']
            logger.info(f"Created backup folder: {self.backup_folder_id}")

        return self.backup_folder_id

    def upload_backup(self, db_path: str, description: Optional[str] = None) -> Dict:
        """
        Upload database backup to Google Drive

        Args:
            db_path: Path to database file
            description: Optional description for the backup

        Returns:
            Dict with backup info (file_id, name, size, webViewLink)
        """
        if not self.service:
            self.authenticate()

        folder_id = self._get_or_create_backup_folder()

        # Generate backup filename with timestamp
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        backup_name = f"templedb_{timestamp}.sqlite"

        # Prepare metadata
        file_metadata = {
            'name': backup_name,
            'parents': [folder_id],
            'description': description or f"TempleDB backup created at {timestamp}"
        }

        # Upload file
        from googleapiclient.http import MediaFileUpload

        media = MediaFileUpload(db_path, mimetype='application/x-sqlite3', resumable=True)

        logger.info(f"Uploading backup: {backup_name}")
        file = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields='id, name, size, webViewLink, createdTime'
        ).execute()

        logger.info(f"✓ Backup uploaded: {file['name']} ({self._format_size(int(file['size']))})")

        return {
            'file_id': file['id'],
            'name': file['name'],
            'size': int(file['size']),
            'web_link': file.get('webViewLink'),
            'created_time': file.get('createdTime')
        }

    def list_backups(self, limit: int = 10) -> List[Dict]:
        """
        List recent backups from Google Drive

        Args:
            limit: Maximum number of backups to return

        Returns:
            List of backup info dicts
        """
        if not self.service:
            self.authenticate()

        folder_id = self._get_or_create_backup_folder()

        # Query for SQLite files in backup folder
        query = f"'{folder_id}' in parents and trashed=false"
        results = self.service.files().list(
            q=query,
            pageSize=limit,
            orderBy='createdTime desc',
            fields='files(id, name, size, createdTime, webViewLink)'
        ).execute()

        backups = []
        for file in results.get('files', []):
            backups.append({
                'file_id': file['id'],
                'name': file['name'],
                'size': int(file.get('size', 0)),
                'created_time': file.get('createdTime'),
                'web_link': file.get('webViewLink')
            })

        return backups

    def download_backup(self, file_id: str, output_path: str) -> bool:
        """
        Download a backup from Google Drive

        Args:
            file_id: Google Drive file ID
            output_path: Where to save the downloaded file

        Returns:
            True if successful
        """
        if not self.service:
            self.authenticate()

        from googleapiclient.http import MediaIoBaseDownload
        import io

        request = self.service.files().get_media(fileId=file_id)

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with io.FileIO(output_path, 'wb') as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False

            logger.info(f"Downloading backup to {output_path}")

            while not done:
                status, done = downloader.next_chunk()
                if status:
                    progress = int(status.progress() * 100)
                    logger.info(f"Download progress: {progress}%")

        logger.info(f"✓ Backup downloaded: {output_path}")
        return True

    def delete_backup(self, file_id: str) -> bool:
        """
        Delete a backup from Google Drive

        Args:
            file_id: Google Drive file ID

        Returns:
            True if successful
        """
        if not self.service:
            self.authenticate()

        self.service.files().delete(fileId=file_id).execute()
        logger.info(f"✓ Backup deleted: {file_id}")
        return True

    def cleanup_old_backups(self, keep_count: int = 10) -> int:
        """
        Delete old backups, keeping only the most recent N

        Args:
            keep_count: Number of recent backups to keep

        Returns:
            Number of backups deleted
        """
        backups = self.list_backups(limit=1000)  # Get all backups

        if len(backups) <= keep_count:
            logger.info(f"No cleanup needed. {len(backups)} backups (keeping {keep_count})")
            return 0

        # Delete old backups
        to_delete = backups[keep_count:]
        deleted_count = 0

        for backup in to_delete:
            try:
                self.delete_backup(backup['file_id'])
                deleted_count += 1
            except Exception as e:
                logger.error(f"Failed to delete {backup['name']}: {e}")

        logger.info(f"✓ Cleaned up {deleted_count} old backups")
        return deleted_count

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format byte size to human-readable string"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"


def create_backup(db_path: str, description: Optional[str] = None) -> Dict:
    """
    Create and upload a backup to Google Drive

    Args:
        db_path: Path to TempleDB database
        description: Optional backup description

    Returns:
        Backup info dict
    """
    backup_manager = GoogleDriveBackup()
    backup_manager.authenticate()
    return backup_manager.upload_backup(db_path, description)


def list_backups(limit: int = 10) -> List[Dict]:
    """
    List recent backups from Google Drive

    Args:
        limit: Maximum backups to list

    Returns:
        List of backup info dicts
    """
    backup_manager = GoogleDriveBackup()
    backup_manager.authenticate()
    return backup_manager.list_backups(limit)


def restore_backup(file_id: str, output_path: str) -> bool:
    """
    Restore a backup from Google Drive

    Args:
        file_id: Google Drive file ID
        output_path: Where to restore the database

    Returns:
        True if successful
    """
    backup_manager = GoogleDriveBackup()
    backup_manager.authenticate()
    return backup_manager.download_backup(file_id, output_path)
