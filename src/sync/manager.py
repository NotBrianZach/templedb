"""
Sync manager for checkout/database synchronization

Provides hash-based three-way merge detection similar to Git.
"""
import hashlib
import os
import socket
from pathlib import Path
from typing import Optional, Dict, List, Set
from db_utils import get_connection
from logger import get_logger

logger = get_logger(__name__)


class SyncManager:
    """
    Manages synchronization between database and filesystem checkouts

    Uses content hashes to detect changes and conflicts (three-way merge):
    - Cached hash: State at checkout/last sync time
    - DB hash: Current state in database
    - Disk hash: Current state on filesystem

    Change detection:
    - DB changed, disk same → Export from DB
    - Disk changed, DB same → Import to DB
    - Both changed → Conflict! Ask user
    """

    def __init__(self, project_slug: str):
        self.project_slug = project_slug
        self.db = get_connection()

        # Get project
        project = self.db.execute(
            "SELECT id, slug FROM projects WHERE slug = ?",
            [project_slug]
        ).fetchone()

        if not project:
            raise ValueError(f"Project not found: {project_slug}")

        self.project_id = project['id']

    def compute_file_hash(self, file_path: Path) -> str:
        """Compute SHA256 hash of file content"""
        if not file_path.exists():
            return ""

        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def get_checkout_path(self) -> Path:
        """Get checkout path for this project"""
        from repositories.checkout_repository import CheckoutRepository
        checkout_repo = CheckoutRepository()
        checkout = checkout_repo.get_active_for_project(self.project_id)
        if not checkout:
            raise ValueError(f"No active checkout found for project {self.project_slug}")
        return Path(checkout['checkout_path'])

    def save_sync_cache(self, file_hashes: Dict[str, str]) -> None:
        """
        Save file hashes to sync cache

        Args:
            file_hashes: Dict of {file_path: sha256_hash}
        """
        # Clear existing cache for this project
        self.db.execute(
            "DELETE FROM sync_cache WHERE project_id = ?",
            [self.project_id]
        )

        # Insert new cache entries
        for file_path, content_hash in file_hashes.items():
            self.db.execute("""
                INSERT INTO sync_cache (project_id, file_path, content_hash, file_size)
                VALUES (?, ?, ?, ?)
            """, [
                self.project_id,
                file_path,
                content_hash,
                0  # TODO: track file size
            ])

        self.db.commit()
        logger.debug(f"Saved {len(file_hashes)} hashes to sync cache")

    def load_sync_cache(self) -> Dict[str, str]:
        """
        Load file hashes from sync cache

        Returns:
            Dict of {file_path: sha256_hash}
        """
        rows = self.db.execute("""
            SELECT file_path, content_hash
            FROM sync_cache
            WHERE project_id = ?
        """, [self.project_id]).fetchall()

        return {row['file_path']: row['content_hash'] for row in rows}

    def compute_checkout_hashes(self, checkout_path: Optional[Path] = None) -> Dict[str, str]:
        """
        Compute current hashes of all files in checkout

        Args:
            checkout_path: Optional checkout path to use (defaults to getting from repository)

        Returns:
            Dict of {file_path: sha256_hash}
        """
        if checkout_path is None:
            checkout_path = self.get_checkout_path()

        if not checkout_path.exists():
            return {}

        hashes = {}

        for root, dirs, files in os.walk(checkout_path):
            # Skip hidden directories
            dirs[:] = [d for d in dirs if not d.startswith('.')]

            for filename in files:
                if filename.startswith('.'):
                    continue

                file_path = Path(root) / filename
                relative_path = file_path.relative_to(checkout_path)

                hashes[str(relative_path)] = self.compute_file_hash(file_path)

        return hashes

    def get_db_file_hashes(self) -> Dict[str, str]:
        """
        Get current file hashes from database

        Returns:
            Dict of {file_path: sha256_hash}
        """
        rows = self.db.execute("""
            SELECT pf.file_path, fc.content_hash
            FROM project_files pf
            JOIN file_contents fc ON fc.file_id = pf.id
            WHERE pf.project_id = ?
        """, [self.project_id]).fetchall()

        return {row['file_path']: row['content_hash'] for row in rows}

    def detect_changes(self) -> Dict[str, List[str]]:
        """
        Detect changes using three-way comparison

        Returns:
            {
                'db_changes': [file_path, ...],     # Changed in DB since last sync
                'disk_changes': [file_path, ...],   # Changed on disk since last sync
                'conflicts': [file_path, ...],      # Changed in both
                'deleted_from_db': [file_path, ...],
                'deleted_from_disk': [file_path, ...],
                'added_to_db': [file_path, ...],
                'added_to_disk': [file_path, ...]
            }
        """
        cached_hashes = self.load_sync_cache()
        db_hashes = self.get_db_file_hashes()
        disk_hashes = self.compute_checkout_hashes()

        all_paths = set(cached_hashes.keys()) | set(db_hashes.keys()) | set(disk_hashes.keys())

        changes = {
            'db_changes': [],
            'disk_changes': [],
            'conflicts': [],
            'deleted_from_db': [],
            'deleted_from_disk': [],
            'added_to_db': [],
            'added_to_disk': []
        }

        for path in all_paths:
            cached = cached_hashes.get(path)
            db = db_hashes.get(path)
            disk = disk_hashes.get(path)

            # File added
            if cached is None:
                if db and disk:
                    if db == disk:
                        continue  # Both added with same content
                    else:
                        changes['conflicts'].append(path)
                elif db:
                    changes['added_to_db'].append(path)
                elif disk:
                    changes['added_to_disk'].append(path)
                continue

            # File deleted
            if db is None and disk is None:
                continue  # Deleted from both, no action

            if db is None:
                changes['deleted_from_db'].append(path)
                continue

            if disk is None:
                changes['deleted_from_disk'].append(path)
                continue

            # File changed
            db_changed = (db != cached)
            disk_changed = (disk != cached)

            if db_changed and disk_changed:
                # Changed in both - conflict!
                if db != disk:  # Unless they changed to the same thing
                    changes['conflicts'].append(path)
            elif db_changed:
                changes['db_changes'].append(path)
            elif disk_changed:
                changes['disk_changes'].append(path)

        return changes

    def get_edit_session(self) -> Optional[dict]:
        """Get active edit session for this project"""
        row = self.db.execute("""
            SELECT id, started_at, hostname, pid, reason
            FROM edit_sessions
            WHERE project_id = ?
        """, [self.project_id]).fetchone()

        if row:
            return dict(row)
        return None

    def start_edit_session(self, reason: Optional[str] = None) -> int:
        """
        Start edit session (make checkout writable)

        Returns:
            session_id
        """
        # Check if session already exists
        existing = self.get_edit_session()
        if existing:
            logger.warning(f"Edit session already active (started {existing['started_at']})")
            return existing['id']

        # Create new session
        cursor = self.db.execute("""
            INSERT INTO edit_sessions (project_id, hostname, pid, reason)
            VALUES (?, ?, ?, ?)
        """, [
            self.project_id,
            socket.gethostname(),
            os.getpid(),
            reason
        ])

        self.db.commit()
        session_id = cursor.lastrowid

        logger.info(f"Started edit session {session_id} for {self.project_slug}")
        return session_id

    def end_edit_session(self) -> None:
        """End edit session (make checkout read-only)"""
        self.db.execute(
            "DELETE FROM edit_sessions WHERE project_id = ?",
            [self.project_id]
        )
        self.db.commit()

        logger.info(f"Ended edit session for {self.project_slug}")

    def cleanup_stale_sessions(self) -> int:
        """
        Cleanup stale edit sessions (>24 hours old or dead process)

        Returns:
            Number of sessions cleaned up
        """
        # Get stale sessions
        stale = self.db.execute("""
            SELECT id, project_id, pid, hostname
            FROM stale_edit_sessions
        """).fetchall()

        count = 0
        for session in stale:
            # Check if process still running (only if on same host)
            if session['hostname'] == socket.gethostname():
                try:
                    os.kill(session['pid'], 0)  # Signal 0 just checks if process exists
                    logger.debug(f"Session {session['id']} process still running, keeping it")
                    continue
                except (OSError, ProcessLookupError):
                    logger.info(f"Session {session['id']} process {session['pid']} is dead, cleaning up")

            # Delete stale session
            self.db.execute("DELETE FROM edit_sessions WHERE id = ?", [session['id']])
            count += 1

        if count > 0:
            self.db.commit()
            logger.info(f"Cleaned up {count} stale edit sessions")

        return count
