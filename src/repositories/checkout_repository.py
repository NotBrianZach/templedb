"""
Checkout repository for managing workspace checkouts.
"""

from typing import Optional, List, Dict, Any
from pathlib import Path

from .base import BaseRepository
from logger import get_logger

logger = get_logger(__name__)


class CheckoutRepository(BaseRepository):
    """
    Repository for checkout-related database operations.

    Provides a clean interface for:
    - Creating and managing checkouts
    - Recording checkout snapshots
    - Listing active checkouts
    - Cleaning up stale checkouts
    """

    def create_or_update(self, project_id: int, checkout_path: str, branch_name: str = 'main') -> int:
        """
        Create or update a checkout record.

        Args:
            project_id: Project ID
            checkout_path: Filesystem path where project was checked out
            branch_name: Branch name (default: 'main')

        Returns:
            Checkout ID
        """
        logger.info(f"Creating/updating checkout for project {project_id} at {checkout_path}")

        checkout_id = self.execute("""
            INSERT OR REPLACE INTO checkouts
            (project_id, checkout_path, branch_name, checkout_at, is_active)
            VALUES (?, ?, ?, datetime('now'), 1)
        """, (project_id, checkout_path, branch_name))

        logger.debug(f"Checkout ID: {checkout_id}")
        return checkout_id

    def get_by_path(self, project_id: int, checkout_path: str) -> Optional[Dict[str, Any]]:
        """
        Get a checkout by project and path.

        Args:
            project_id: Project ID
            checkout_path: Checkout path

        Returns:
            Checkout dictionary or None
        """
        return self.query_one("""
            SELECT id, project_id, checkout_path, branch_name, checkout_at, last_sync_at, is_active
            FROM checkouts
            WHERE project_id = ? AND checkout_path = ?
        """, (project_id, checkout_path))

    def get_all_for_project(self, project_id: int) -> List[Dict[str, Any]]:
        """
        Get all checkouts for a project.

        Args:
            project_id: Project ID

        Returns:
            List of checkout dictionaries
        """
        logger.debug(f"Getting all checkouts for project {project_id}")
        return self.query_all("""
            SELECT
                id,
                checkout_path,
                branch_name,
                checkout_at,
                last_sync_at,
                is_active
            FROM checkouts
            WHERE project_id = ?
            ORDER BY checkout_at DESC
        """, (project_id,))

    def get_all(self) -> List[Dict[str, Any]]:
        """
        Get all checkouts across all projects.

        Returns:
            List of checkout dictionaries with project information
        """
        logger.debug("Getting all checkouts")
        return self.query_all("""
            SELECT
                c.id,
                p.slug AS project_slug,
                c.checkout_path,
                c.branch_name,
                c.checkout_at,
                c.last_sync_at,
                c.is_active
            FROM checkouts c
            JOIN projects p ON c.project_id = p.id
            ORDER BY c.checkout_at DESC
        """)

    def update_sync_time(self, checkout_id: int) -> None:
        """
        Update the last_sync_at timestamp for a checkout.

        Args:
            checkout_id: Checkout ID
        """
        logger.debug(f"Updating sync time for checkout {checkout_id}")
        self.execute("""
            UPDATE checkouts
            SET last_sync_at = datetime('now')
            WHERE id = ?
        """, (checkout_id,))

    def record_snapshot(self, checkout_id: int, file_id: int, content_hash: str, version: int) -> None:
        """
        Record a snapshot of a file at checkout time.

        Args:
            checkout_id: Checkout ID
            file_id: File ID
            content_hash: Content hash at checkout
            version: Version number at checkout
        """
        logger.debug(f"Recording snapshot for checkout {checkout_id}, file {file_id}")
        self.execute("""
            INSERT OR REPLACE INTO checkout_snapshots
            (checkout_id, file_id, content_hash, version, checked_out_at)
            VALUES (?, ?, ?, ?, datetime('now'))
        """, (checkout_id, file_id, content_hash, version), commit=False)

    def clear_snapshots(self, checkout_id: int) -> None:
        """
        Clear all snapshots for a checkout.

        Args:
            checkout_id: Checkout ID
        """
        logger.debug(f"Clearing snapshots for checkout {checkout_id}")
        self.execute("""
            DELETE FROM checkout_snapshots
            WHERE checkout_id = ?
        """, (checkout_id,), commit=False)

    def get_snapshot(self, checkout_id: int, file_id: int) -> Optional[Dict[str, Any]]:
        """
        Get the snapshot for a specific file in a checkout.

        Args:
            checkout_id: Checkout ID
            file_id: File ID

        Returns:
            Snapshot dictionary or None
        """
        return self.query_one("""
            SELECT version, content_hash, checked_out_at
            FROM checkout_snapshots
            WHERE checkout_id = ? AND file_id = ?
        """, (checkout_id, file_id))

    def delete(self, checkout_id: int) -> None:
        """
        Delete a checkout record (CASCADE removes snapshots).

        Args:
            checkout_id: Checkout ID
        """
        logger.info(f"Deleting checkout {checkout_id}")
        self.execute("DELETE FROM checkouts WHERE id = ?", (checkout_id,))

    def find_stale_checkouts(self, project_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Find checkouts where the directory no longer exists.

        Args:
            project_id: Optional project ID to filter by

        Returns:
            List of stale checkout dictionaries
        """
        if project_id:
            checkouts = self.query_all(
                "SELECT id, checkout_path FROM checkouts WHERE project_id = ?",
                (project_id,)
            )
        else:
            checkouts = self.query_all("SELECT id, checkout_path FROM checkouts")

        stale = []
        for checkout in checkouts:
            if not Path(checkout['checkout_path']).exists():
                stale.append(checkout)

        logger.debug(f"Found {len(stale)} stale checkouts")
        return stale
