"""
Config link repository for managing configuration file symlinks.
"""

from typing import Optional, List, Dict, Any
from pathlib import Path
import os

from .base import BaseRepository
from logger import get_logger

logger = get_logger(__name__)


class ConfigLinkRepository(BaseRepository):
    """
    Repository for config link-related database operations.

    Provides a clean interface for:
    - Creating and managing config checkouts
    - Recording symlink mappings
    - Listing active config links
    - Verifying link status
    - Cleaning up broken links
    """

    # ========== Config Checkouts ==========

    def create_checkout(self, project_id: int, checkout_dir: str) -> int:
        """
        Create a config checkout record.

        Args:
            project_id: Project ID
            checkout_dir: Directory where project will be checked out

        Returns:
            Checkout ID
        """
        logger.info(f"Creating config checkout for project {project_id} at {checkout_dir}")

        result = self.execute("""
            INSERT INTO config_checkouts
            (project_id, checkout_dir, created_at, updated_at)
            VALUES (?, ?, datetime('now'), datetime('now'))
        """, (project_id, checkout_dir))

        checkout_id = result if isinstance(result, int) else result
        logger.debug(f"Config checkout ID: {checkout_id}")
        return checkout_id

    def get_checkout_by_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        """
        Get config checkout for a project.

        Args:
            project_id: Project ID

        Returns:
            Checkout dictionary or None
        """
        return self.query_one("""
            SELECT id, project_id, checkout_dir, created_at, updated_at
            FROM config_checkouts
            WHERE project_id = ?
        """, (project_id,))

    def get_checkout_by_dir(self, checkout_dir: str) -> Optional[Dict[str, Any]]:
        """
        Get config checkout by directory path.

        Args:
            checkout_dir: Checkout directory path

        Returns:
            Checkout dictionary or None
        """
        return self.query_one("""
            SELECT id, project_id, checkout_dir, created_at, updated_at
            FROM config_checkouts
            WHERE checkout_dir = ?
        """, (checkout_dir,))

    def get_all_checkouts(self) -> List[Dict[str, Any]]:
        """
        Get all config checkouts with project information.

        Returns:
            List of checkout dictionaries
        """
        logger.debug("Getting all config checkouts")
        return self.query_all("""
            SELECT
                c.id,
                c.project_id,
                p.slug AS project_slug,
                p.name AS project_name,
                c.checkout_dir,
                c.created_at,
                c.updated_at
            FROM config_checkouts c
            JOIN projects p ON c.project_id = p.id
            ORDER BY c.created_at DESC
        """)

    def update_checkout_time(self, checkout_id: int) -> None:
        """
        Update the updated_at timestamp for a checkout.

        Args:
            checkout_id: Checkout ID
        """
        logger.debug(f"Updating time for config checkout {checkout_id}")
        self.execute("""
            UPDATE config_checkouts
            SET updated_at = datetime('now')
            WHERE id = ?
        """, (checkout_id,))

    def delete_checkout(self, checkout_id: int) -> None:
        """
        Delete a config checkout (CASCADE removes links).

        Args:
            checkout_id: Checkout ID
        """
        logger.info(f"Deleting config checkout {checkout_id}")
        self.execute("DELETE FROM config_checkouts WHERE id = ?", (checkout_id,))

    # ========== Config Links ==========

    def create_link(
        self,
        checkout_id: int,
        source_path: str,
        source_absolute: str,
        target_path: str,
        link_type: str = 'file',
        backup_path: Optional[str] = None
    ) -> int:
        """
        Create a config link record.

        Args:
            checkout_id: Checkout ID
            source_path: Relative path in checkout
            source_absolute: Absolute path in checkout
            target_path: Absolute path of symlink
            link_type: 'file' or 'directory'
            backup_path: Path to backup of original file (if existed)

        Returns:
            Link ID
        """
        logger.info(f"Creating config link: {target_path} -> {source_absolute}")

        result = self.execute("""
            INSERT INTO config_links
            (checkout_id, source_path, source_absolute, target_path,
             status, link_type, backup_path, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'active', ?, ?, datetime('now'), datetime('now'))
        """, (checkout_id, source_path, source_absolute, target_path, link_type, backup_path))

        link_id = result if isinstance(result, int) else result
        logger.debug(f"Config link ID: {link_id}")
        return link_id

    def get_link_by_id(self, link_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a config link by ID.

        Args:
            link_id: Link ID

        Returns:
            Link dictionary or None
        """
        return self.query_one("""
            SELECT id, checkout_id, source_path, source_absolute,
                   target_path, status, link_type, backup_path,
                   created_at, updated_at
            FROM config_links
            WHERE id = ?
        """, (link_id,))

    def get_link_by_target(self, target_path: str) -> Optional[Dict[str, Any]]:
        """
        Get a config link by target path.

        Args:
            target_path: Target symlink path

        Returns:
            Link dictionary or None
        """
        return self.query_one("""
            SELECT id, checkout_id, source_path, source_absolute,
                   target_path, status, link_type, backup_path,
                   created_at, updated_at
            FROM config_links
            WHERE target_path = ?
        """, (target_path,))

    def get_links_for_checkout(self, checkout_id: int) -> List[Dict[str, Any]]:
        """
        Get all links for a checkout.

        Args:
            checkout_id: Checkout ID

        Returns:
            List of link dictionaries
        """
        logger.debug(f"Getting links for checkout {checkout_id}")
        return self.query_all("""
            SELECT id, checkout_id, source_path, source_absolute,
                   target_path, status, link_type, backup_path,
                   created_at, updated_at
            FROM config_links
            WHERE checkout_id = ?
            ORDER BY target_path
        """, (checkout_id,))

    def get_all_links(self) -> List[Dict[str, Any]]:
        """
        Get all config links with checkout and project information.

        Returns:
            List of link dictionaries
        """
        logger.debug("Getting all config links")
        return self.query_all("""
            SELECT
                l.id,
                l.checkout_id,
                p.slug AS project_slug,
                p.name AS project_name,
                l.source_path,
                l.source_absolute,
                l.target_path,
                l.status,
                l.link_type,
                l.backup_path,
                l.created_at,
                l.updated_at
            FROM config_links l
            JOIN config_checkouts c ON l.checkout_id = c.id
            JOIN projects p ON c.project_id = p.id
            ORDER BY p.slug, l.target_path
        """)

    def update_link_status(self, link_id: int, status: str) -> None:
        """
        Update the status of a config link.

        Args:
            link_id: Link ID
            status: New status ('active', 'broken', 'removed')
        """
        logger.debug(f"Updating status for link {link_id} to {status}")
        self.execute("""
            UPDATE config_links
            SET status = ?, updated_at = datetime('now')
            WHERE id = ?
        """, (status, link_id))

    def delete_link(self, link_id: int) -> None:
        """
        Delete a config link record.

        Args:
            link_id: Link ID
        """
        logger.info(f"Deleting config link {link_id}")
        self.execute("DELETE FROM config_links WHERE id = ?", (link_id,))

    def delete_links_for_checkout(self, checkout_id: int) -> None:
        """
        Delete all links for a checkout.

        Args:
            checkout_id: Checkout ID
        """
        logger.info(f"Deleting all links for checkout {checkout_id}")
        self.execute("DELETE FROM config_links WHERE checkout_id = ?", (checkout_id,))

    # ========== Status Checking ==========

    def verify_links(self, checkout_id: Optional[int] = None) -> Dict[str, List[Dict[str, Any]]]:
        """
        Verify the status of config links.

        Args:
            checkout_id: Optional checkout ID to filter by

        Returns:
            Dictionary with 'active', 'broken', and 'missing' lists
        """
        if checkout_id:
            links = self.get_links_for_checkout(checkout_id)
        else:
            links = self.get_all_links()

        result = {
            'active': [],
            'broken': [],
            'missing': []
        }

        for link in links:
            target = Path(link['target_path'])
            source = Path(link['source_absolute'])

            if not target.exists():
                result['missing'].append(link)
            elif not target.is_symlink():
                result['broken'].append(link)
            elif not target.resolve() == source:
                result['broken'].append(link)
            else:
                result['active'].append(link)

        logger.debug(f"Link verification: {len(result['active'])} active, "
                    f"{len(result['broken'])} broken, {len(result['missing'])} missing")
        return result
