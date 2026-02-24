"""
Google Drive backup provider for TempleDB
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

try:
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
    from googleapiclient.errors import HttpError
    GDRIVE_AVAILABLE = True
except ImportError:
    GDRIVE_AVAILABLE = False

from src.backup.base import CloudBackupProvider
from src.logger import get_logger

logger = get_logger(__name__)

# Google Drive API scopes
SCOPES = ['https://www.googleapis.com/auth/drive.file']


class GDriveBackupProvider(CloudBackupProvider):
    """Google Drive backup provider"""

    def __init__(
        self,
        credentials_path: Optional[Path] = None,
        token_path: Optional[Path] = None,
        folder_name: str = 'TempleDB Backups',
        **kwargs
    ):
        """
        Initialize Google Drive backup provider.

        Args:
            credentials_path: Path to OAuth2 credentials.json
            token_path: Path to store authentication token
            folder_name: Name of folder in Google Drive
            **kwargs: Base class arguments (retention_days, max_backups)
        """
        super().__init__(**kwargs)

        self.credentials_path = credentials_path or self._default_credentials_path()
        self.token_path = token_path or self._default_token_path()
        self.folder_name = folder_name
        self.service = None
        self.folder_id = None

    def _default_credentials_path(self) -> Path:
        """Get default credentials path"""
        return Path.home() / '.config' / 'templedb' / 'gdrive_credentials.json'

    def _default_token_path(self) -> Path:
        """Get default token path"""
        return Path.home() / '.config' / 'templedb' / 'gdrive_token.json'

    def authenticate(self) -> bool:
        """Authenticate with Google Drive API"""
        if self.authenticated and self.service:
            return True

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
                    logger.error("Run: templedb backup setup gdrive")
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
            self.authenticated = True
            logger.info("Successfully authenticated with Google Drive")
            return True
        except Exception as e:
            logger.error(f"Failed to build Google Drive service: {e}")
            return False

    def _get_or_create_folder(self) -> Optional[str]:
        """Get or create backup folder in Google Drive"""
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
                logger.info(f"Using existing folder: {self.folder_name}")
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
            logger.info(f"Created folder: {self.folder_name}")
            return self.folder_id

        except HttpError as e:
            logger.error(f"Failed to get/create folder: {e}")
            return None

    def upload_file(self, file_path: Path, remote_name: Optional[str] = None) -> Optional[str]:
        """Upload file to Google Drive"""
        if not self.authenticated:
            if not self.authenticate():
                return None

        folder_id = self._get_or_create_folder()
        if not folder_id:
            return None

        remote_name = remote_name or file_path.name

        try:
            file_metadata = {
                'name': remote_name,
                'parents': [folder_id]
            }

            media = MediaFileUpload(
                str(file_path),
                mimetype='application/x-sqlite3',
                resumable=True
            )

            logger.info(f"Uploading {remote_name} to Google Drive...")

            file = self.service.files().create(
                body=file_metadata,
                media_body=media,
                fields='id, name, size, createdTime'
            ).execute()

            file_id = file.get('id')
            size_mb = int(file.get('size', 0)) / (1024 * 1024)

            logger.info(f"Upload successful: {file.get('name')} ({size_mb:.2f} MB)")

            return file_id

        except HttpError as e:
            logger.error(f"Failed to upload file: {e}")
            return None

    def download_file(self, remote_id: str, destination: Path) -> bool:
        """Download file from Google Drive"""
        if not self.authenticated:
            if not self.authenticate():
                return False

        try:
            request = self.service.files().get_media(fileId=remote_id)

            logger.info(f"Downloading backup to {destination}...")

            destination.parent.mkdir(parents=True, exist_ok=True)

            with open(destination, 'wb') as f:
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

    def list_backups(self) -> List[Dict[str, Any]]:
        """List all backups in Google Drive folder"""
        if not self.authenticated:
            if not self.authenticate():
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

            # Convert to standard format
            backups = []
            for file in files:
                backups.append({
                    'id': file['id'],
                    'name': file['name'],
                    'size': int(file.get('size', 0)),
                    'created': file['createdTime'],
                    'modified': file.get('modifiedTime'),
                })

            return backups

        except HttpError as e:
            logger.error(f"Failed to list backups: {e}")
            return []

    def delete_backup(self, remote_id: str) -> bool:
        """Delete backup from Google Drive"""
        if not self.authenticated:
            if not self.authenticate():
                return False

        try:
            self.service.files().delete(fileId=remote_id).execute()
            logger.info(f"Deleted backup: {remote_id}")
            return True
        except HttpError as e:
            logger.error(f"Failed to delete backup: {e}")
            return False

    @classmethod
    def get_provider_name(cls) -> str:
        return "Google Drive"

    @classmethod
    def get_required_config(cls) -> List[str]:
        return []  # Optional: credentials_path, token_path, folder_name

    @classmethod
    def is_available(cls) -> bool:
        return GDRIVE_AVAILABLE
