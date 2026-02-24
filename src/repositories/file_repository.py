"""
File repository for managing project files and content.
"""

from typing import Optional, List, Dict, Any
from pathlib import Path

from .base import BaseRepository
from logger import get_logger

logger = get_logger(__name__)


class FileRepository(BaseRepository):
    """
    Repository for file-related database operations.

    Provides a clean interface for:
    - Getting files for a project
    - Getting file content
    - Managing file versions
    - File statistics
    """

    def get_files_for_project(self, project_id: int, include_content: bool = False) -> List[Dict[str, Any]]:
        """
        Get all current files for a project.

        Args:
            project_id: Project ID
            include_content: Whether to include file content (default: False)

        Returns:
            List of file dictionaries
        """
        logger.debug(f"Getting files for project {project_id} (include_content={include_content})")

        if include_content:
            return self.query_all("""
                SELECT
                    pf.id as file_id,
                    pf.file_path,
                    pf.file_name,
                    pf.lines_of_code,
                    fc.content_hash,
                    fc.version,
                    cb.content_text,
                    cb.content_blob,
                    cb.content_type,
                    cb.encoding,
                    cb.file_size_bytes
                FROM project_files pf
                JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
                JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
                WHERE pf.project_id = ?
                ORDER BY pf.file_path
            """, (project_id,))
        else:
            return self.query_all("""
                SELECT
                    pf.id as file_id,
                    pf.file_path,
                    pf.file_name,
                    pf.lines_of_code,
                    fc.content_hash,
                    fc.version
                FROM project_files pf
                LEFT JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
                WHERE pf.project_id = ?
                ORDER BY pf.file_path
            """, (project_id,))

    def get_file_by_path(self, project_id: int, file_path: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific file by its path within a project.

        Args:
            project_id: Project ID
            file_path: Relative file path

        Returns:
            File dictionary or None if not found
        """
        logger.debug(f"Getting file {file_path} for project {project_id}")
        return self.query_one("""
            SELECT
                pf.id,
                pf.file_path,
                pf.file_name,
                pf.file_type_id,
                pf.lines_of_code,
                fc.content_hash,
                fc.version
            FROM project_files pf
            LEFT JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
            WHERE pf.project_id = ? AND pf.file_path = ?
        """, (project_id, file_path))

    def get_file_content(self, file_id: int) -> Optional[Dict[str, Any]]:
        """
        Get the current content for a file.

        Args:
            file_id: File ID

        Returns:
            Content dictionary with text/blob, encoding, type
        """
        logger.debug(f"Getting content for file {file_id}")
        return self.query_one("""
            SELECT
                cb.hash_sha256,
                cb.content_text,
                cb.content_blob,
                cb.content_type,
                cb.encoding,
                cb.file_size_bytes,
                fc.version,
                fc.line_count
            FROM file_contents fc
            JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
            WHERE fc.file_id = ? AND fc.is_current = 1
        """, (file_id,))

    def get_file_versions(self, file_id: int) -> List[Dict[str, Any]]:
        """
        Get all versions of a file.

        Args:
            file_id: File ID

        Returns:
            List of version dictionaries ordered by version number
        """
        logger.debug(f"Getting version history for file {file_id}")
        return self.query_all("""
            SELECT
                fc.version,
                fc.content_hash,
                fc.file_size_bytes,
                fc.line_count,
                fc.created_at,
                fc.updated_at,
                fc.is_current
            FROM file_contents fc
            WHERE fc.file_id = ?
            ORDER BY fc.version DESC
        """, (file_id,))

    def count_files(self, project_id: int) -> int:
        """
        Count total files in a project.

        Args:
            project_id: Project ID

        Returns:
            Number of files
        """
        result = self.query_one(
            "SELECT COUNT(*) as count FROM project_files WHERE project_id = ?",
            (project_id,)
        )
        return result['count'] if result else 0

    def get_file_types_summary(self, project_id: int) -> List[Dict[str, Any]]:
        """
        Get summary of file types in a project.

        Args:
            project_id: Project ID

        Returns:
            List of dictionaries with type_name, file_count, total_lines
        """
        logger.debug(f"Getting file types summary for project {project_id}")
        return self.query_all("""
            SELECT
                ft.type_name,
                COUNT(pf.id) as file_count,
                SUM(pf.lines_of_code) as total_lines
            FROM project_files pf
            JOIN file_types ft ON pf.file_type_id = ft.id
            WHERE pf.project_id = ?
            GROUP BY ft.type_name
            ORDER BY file_count DESC
        """, (project_id,))
