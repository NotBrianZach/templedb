"""
Google Cloud Storage (GCS) backup provider for TempleDB
"""

from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime
import sqlite3
import subprocess
import json
import tempfile
import os

try:
    from google.cloud import storage
    from google.oauth2 import service_account
    from google.api_core import exceptions as gcs_exceptions
    GCS_AVAILABLE = True
except ImportError:
    GCS_AVAILABLE = False

from backup.base import CloudBackupProvider
from logger import get_logger

logger = get_logger(__name__)


class GCSBackupProvider(CloudBackupProvider):
    """Google Cloud Storage backup provider"""

    def __init__(
        self,
        bucket_name: str,
        credentials_path: Optional[Path] = None,
        project_id: Optional[str] = None,
        prefix: str = 'templedb-backups/',
        **kwargs
    ):
        """
        Initialize GCS backup provider.

        Args:
            bucket_name: GCS bucket name
            credentials_path: Path to service account JSON key file
            project_id: GCP project ID (optional, can be in credentials)
            prefix: Prefix for backup objects in bucket
            **kwargs: Base class arguments (retention_days, max_backups)
        """
        super().__init__(**kwargs)

        self.bucket_name = bucket_name
        self.credentials_path = credentials_path
        self.project_id = project_id
        self.prefix = prefix.rstrip('/') + '/'
        self.client = None
        self.bucket = None

    def _load_credentials_from_secrets(self) -> Optional[Dict]:
        """
        Load service account credentials from TempleDB secrets.
        Returns credentials dict, or None if not found.
        """
        try:
            db_path = Path.home() / '.local' / 'share' / 'templedb' / 'templedb.sqlite'
            if not db_path.exists():
                return None

            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row

            # Get secret blob from system_config project
            cursor = conn.execute("""
                SELECT sb.secret_blob
                FROM secret_blobs sb
                JOIN projects p ON p.id = sb.project_id
                WHERE p.slug = 'system_config'
                AND sb.profile = 'default'
                AND sb.secret_name = 'gcs_service_account'
            """)

            row = cursor.fetchone()
            conn.close()

            if not row:
                logger.debug("No GCS service account credentials found in TempleDB secrets")
                return None

            # Decrypt using age
            key_file_str = os.environ.get("TEMPLEDB_AGE_KEY_FILE") or \
                          os.environ.get("SOPS_AGE_KEY_FILE")

            if key_file_str:
                key_file = Path(key_file_str)
            else:
                key_file = Path.home() / ".config" / "sops" / "age" / "keys.txt"

            if not key_file.exists():
                logger.warning(f"Age key file not found: {key_file}")
                return None

            proc = subprocess.run(
                ["age", "-d", "-i", str(key_file)],
                input=row['secret_blob'],
                capture_output=True
            )

            if proc.returncode != 0:
                logger.error(f"Failed to decrypt credentials: {proc.stderr.decode('utf-8')}")
                return None

            # Parse JSON
            decrypted_json = proc.stdout.decode('utf-8')

            try:
                creds_data = json.loads(decrypted_json)
                logger.info("Loaded GCS service account credentials from TempleDB secrets")
                return creds_data
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse credentials JSON: {e}")
                return None

        except Exception as e:
            logger.error(f"Failed to load credentials from secrets: {e}")
            return None

    def authenticate(self) -> bool:
        """Authenticate with Google Cloud Storage"""
        if self.authenticated and self.client:
            return True

        credentials = None

        # Try to load from file first
        if self.credentials_path and self.credentials_path.exists():
            try:
                credentials = service_account.Credentials.from_service_account_file(
                    str(self.credentials_path)
                )
                logger.info(f"Loaded GCS credentials from file: {self.credentials_path}")
            except Exception as e:
                logger.error(f"Failed to load credentials from file: {e}")
                return False

        # If no file, try loading from TempleDB secrets
        if not credentials:
            logger.info("Credentials file not found, checking TempleDB secrets...")
            creds_dict = self._load_credentials_from_secrets()

            if creds_dict:
                try:
                    credentials = service_account.Credentials.from_service_account_info(creds_dict)
                    logger.info("Loaded GCS credentials from TempleDB secrets")
                except Exception as e:
                    logger.error(f"Failed to create credentials from secrets: {e}")
                    return False
            else:
                logger.error("GCS credentials not found in file or TempleDB secrets")
                logger.error("Either:")
                logger.error("  1. Place service account JSON key at credentials_path")
                logger.error("  2. Store in TempleDB secrets as 'gcs_service_account'")
                return False

        # Create client
        try:
            project = self.project_id or credentials.project_id
            self.client = storage.Client(credentials=credentials, project=project)
            self.bucket = self.client.bucket(self.bucket_name)

            # Verify bucket exists
            if not self.bucket.exists():
                logger.error(f"Bucket '{self.bucket_name}' does not exist")
                logger.error(f"Create it at: https://console.cloud.google.com/storage/browser")
                return False

            self.authenticated = True
            logger.info(f"Successfully authenticated with GCS bucket: {self.bucket_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to authenticate with GCS: {e}")
            return False

    def upload_file(self, file_path: Path, remote_name: Optional[str] = None) -> Optional[str]:
        """Upload file to GCS bucket"""
        if not self.authenticated:
            if not self.authenticate():
                return None

        remote_name = remote_name or file_path.name
        blob_name = f"{self.prefix}{remote_name}"

        try:
            logger.info(f"Uploading {remote_name} to GCS bucket {self.bucket_name}...")

            blob = self.bucket.blob(blob_name)
            blob.upload_from_filename(str(file_path))

            size_mb = file_path.stat().st_size / (1024 * 1024)
            logger.info(f"Upload successful: {blob_name} ({size_mb:.2f} MB)")

            return blob_name

        except Exception as e:
            logger.error(f"Failed to upload file: {e}")
            return None

    def download_file(self, remote_id: str, destination: Path) -> bool:
        """Download file from GCS bucket"""
        if not self.authenticated:
            if not self.authenticate():
                return False

        try:
            logger.info(f"Downloading {remote_id} from GCS...")

            blob = self.bucket.blob(remote_id)
            destination.parent.mkdir(parents=True, exist_ok=True)
            blob.download_to_filename(str(destination))

            size_mb = destination.stat().st_size / (1024 * 1024)
            logger.info(f"Download complete ({size_mb:.2f} MB)")

            return True

        except Exception as e:
            logger.error(f"Failed to download backup: {e}")
            return False

    def list_backups(self) -> List[Dict[str, Any]]:
        """List all backups in GCS bucket"""
        if not self.authenticated:
            if not self.authenticate():
                return []

        try:
            blobs = self.client.list_blobs(self.bucket_name, prefix=self.prefix)
            backups = []

            for blob in blobs:
                # Skip directory markers
                if blob.name.endswith('/'):
                    continue

                backups.append({
                    'id': blob.name,
                    'name': blob.name.replace(self.prefix, ''),
                    'size': blob.size,
                    'created': blob.time_created.isoformat(),
                    'modified': blob.updated.isoformat() if blob.updated else blob.time_created.isoformat(),
                })

            # Sort by creation time (newest first)
            backups.sort(key=lambda x: x['created'], reverse=True)

            logger.debug(f"Found {len(backups)} backups in GCS bucket")
            return backups

        except Exception as e:
            logger.error(f"Failed to list backups: {e}")
            return []

    def delete_backup(self, remote_id: str) -> bool:
        """Delete backup from GCS bucket"""
        if not self.authenticated:
            if not self.authenticate():
                return False

        try:
            blob = self.bucket.blob(remote_id)
            blob.delete()
            logger.info(f"Deleted backup: {remote_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete backup: {e}")
            return False

    def test_connection(self) -> bool:
        """Test connection to GCS bucket"""
        return self.authenticate()

    @classmethod
    def get_provider_name(cls) -> str:
        return "Google Cloud Storage"

    @classmethod
    def get_required_config(cls) -> List[str]:
        return ['bucket_name']  # Only bucket_name is required

    @classmethod
    def is_available(cls) -> bool:
        return GCS_AVAILABLE
