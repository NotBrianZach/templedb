"""
Safe file query API that enforces project_id filtering.

This module provides a query API that ENFORCES the requirement that all
file queries must include project_id or project_slug filters. This prevents
cross-project data corruption and incorrect query results.

Key Principle:
    File paths are NOT globally unique - they're only unique within a project.
    Therefore, all file queries MUST filter by project.

See: QUERY_BEST_PRACTICES.md for detailed documentation.

Usage:
    >>> from safe_file_queries import SafeFileQueries
    >>> queries = SafeFileQueries()
    >>>
    >>> # ✅ SAFE - Always requires project context
    >>> file = queries.get_file_by_path(project_id=1, file_path="README.md")
    >>> content = queries.get_file_content(project_id=1, file_path="src/app.ts")
    >>>
    >>> # ❌ UNSAFE - Won't compile (missing required project_id parameter)
    >>> # file = queries.get_file_by_path(file_path="README.md")  # TypeError!
"""

from typing import Optional, List, Dict, Any, Union
from pathlib import Path
import re

from repositories.base import BaseRepository
from repositories.project_repository import ProjectRepository
from logger import get_logger

logger = get_logger(__name__)


class QueryValidationError(Exception):
    """Raised when a query violates safety constraints."""
    pass


class SafeFileQueries(BaseRepository):
    """
    Safe API for querying files that enforces project_id filtering.

    All methods require either project_id or project_slug to prevent
    accidental cross-project queries.
    """

    def __init__(self):
        super().__init__()
        self._project_repo = ProjectRepository()

    def _resolve_project_id(self, project_id: Optional[int] = None,
                           project_slug: Optional[str] = None) -> int:
        """
        Resolve project_id from either project_id or project_slug.

        Args:
            project_id: Direct project ID
            project_slug: Project slug to resolve to ID

        Returns:
            Project ID

        Raises:
            ValueError: If neither or both parameters provided
            QueryValidationError: If project doesn't exist
        """
        if project_id is None and project_slug is None:
            raise ValueError(
                "Either project_id or project_slug must be provided. "
                "File paths are NOT globally unique - they must be scoped to a project."
            )

        if project_id is not None and project_slug is not None:
            raise ValueError("Provide either project_id OR project_slug, not both")

        if project_slug is not None:
            project = self._project_repo.get_project_by_slug(project_slug)
            if not project:
                raise QueryValidationError(f"Project not found: {project_slug}")
            return project['id']

        return project_id

    # ==========================================================================
    # SAFE FILE QUERY METHODS
    # ==========================================================================

    def get_file_by_path(self, file_path: str,
                        project_id: Optional[int] = None,
                        project_slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get a file by its path within a specific project.

        Args:
            file_path: Relative file path (e.g., 'src/app.ts', 'README.md')
            project_id: Project ID (provide this OR project_slug)
            project_slug: Project slug (provide this OR project_id)

        Returns:
            File metadata dictionary or None if not found

        Example:
            >>> queries = SafeFileQueries()
            >>> file = queries.get_file_by_path('README.md', project_id=1)
            >>> file = queries.get_file_by_path('src/app.ts', project_slug='my-project')
        """
        proj_id = self._resolve_project_id(project_id, project_slug)

        logger.debug(f"Getting file {file_path} for project {proj_id}")
        return self.query_one("""
            SELECT
                pf.id,
                pf.project_id,
                pf.file_path,
                pf.file_name,
                pf.file_type_id,
                pf.component_name,
                pf.lines_of_code,
                pf.status,
                pf.last_modified,
                ft.type_name,
                ft.category as file_category
            FROM project_files pf
            JOIN file_types ft ON pf.file_type_id = ft.id
            WHERE pf.project_id = ? AND pf.file_path = ?
        """, (proj_id, file_path))

    def get_file_content(self, file_path: str,
                        project_id: Optional[int] = None,
                        project_slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get the current content of a file in a specific project.

        Args:
            file_path: Relative file path
            project_id: Project ID (provide this OR project_slug)
            project_slug: Project slug (provide this OR project_id)

        Returns:
            Dictionary with content_text, content_blob, content_type, etc.

        Example:
            >>> queries = SafeFileQueries()
            >>> content = queries.get_file_content('src/app.ts', project_id=1)
            >>> print(content['content_text'])
        """
        proj_id = self._resolve_project_id(project_id, project_slug)

        logger.debug(f"Getting content for {file_path} in project {proj_id}")
        return self.query_one("""
            SELECT
                pf.file_path,
                cb.content_text,
                cb.content_blob,
                cb.content_type,
                cb.encoding,
                cb.file_size_bytes,
                cb.hash_sha256,
                fc.version,
                fc.line_count
            FROM project_files pf
            JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
            JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
            WHERE pf.project_id = ? AND pf.file_path = ?
        """, (proj_id, file_path))

    def list_files(self,
                   project_id: Optional[int] = None,
                   project_slug: Optional[str] = None,
                   file_type: Optional[str] = None,
                   status: str = 'active',
                   pattern: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List files in a specific project with optional filters.

        Args:
            project_id: Project ID (provide this OR project_slug)
            project_slug: Project slug (provide this OR project_id)
            file_type: Filter by file type (e.g., 'typescript', 'sql_table')
            status: Filter by status (default: 'active')
            pattern: SQL GLOB pattern for file_path (e.g., 'src/**/*.ts')

        Returns:
            List of file metadata dictionaries

        Example:
            >>> queries = SafeFileQueries()
            >>> # All TypeScript files
            >>> files = queries.list_files(project_id=1, file_type='typescript')
            >>> # Files matching pattern
            >>> files = queries.list_files(project_id=1, pattern='src/**/*.ts')
        """
        proj_id = self._resolve_project_id(project_id, project_slug)

        sql = """
            SELECT
                pf.id,
                pf.file_path,
                pf.file_name,
                pf.component_name,
                pf.lines_of_code,
                pf.status,
                pf.last_modified,
                ft.type_name,
                ft.category as file_category
            FROM project_files pf
            JOIN file_types ft ON pf.file_type_id = ft.id
            WHERE pf.project_id = ?
        """
        params = [proj_id]

        if file_type:
            sql += " AND ft.type_name = ?"
            params.append(file_type)

        if status:
            sql += " AND pf.status = ?"
            params.append(status)

        if pattern:
            sql += " AND pf.file_path GLOB ?"
            params.append(pattern)

        sql += " ORDER BY pf.file_path"

        logger.debug(f"Listing files for project {proj_id} with filters: "
                    f"type={file_type}, status={status}, pattern={pattern}")
        return self.query_all(sql, tuple(params))

    def get_file_versions(self, file_path: str,
                         project_id: Optional[int] = None,
                         project_slug: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get version history for a file in a specific project.

        Args:
            file_path: Relative file path
            project_id: Project ID (provide this OR project_slug)
            project_slug: Project slug (provide this OR project_id)

        Returns:
            List of version dictionaries ordered by version number (newest first)

        Example:
            >>> queries = SafeFileQueries()
            >>> versions = queries.get_file_versions('README.md', project_id=1)
            >>> for v in versions:
            ...     print(f"Version {v['version']}: {v['created_at']}")
        """
        proj_id = self._resolve_project_id(project_id, project_slug)

        logger.debug(f"Getting version history for {file_path} in project {proj_id}")
        return self.query_all("""
            SELECT
                fc.version,
                fc.content_hash,
                fc.file_size_bytes,
                fc.line_count,
                fc.created_at,
                fc.is_current
            FROM project_files pf
            JOIN file_contents fc ON fc.file_id = pf.id
            WHERE pf.project_id = ? AND pf.file_path = ?
            ORDER BY fc.version DESC
        """, (proj_id, file_path))

    def search_file_content(self, search_term: str,
                           project_id: Optional[int] = None,
                           project_slug: Optional[str] = None,
                           file_type: Optional[str] = None,
                           case_sensitive: bool = False) -> List[Dict[str, Any]]:
        """
        Search file contents within a specific project.

        Args:
            search_term: Text to search for
            project_id: Project ID (provide this OR project_slug)
            project_slug: Project slug (provide this OR project_id)
            file_type: Optional file type filter
            case_sensitive: Whether search is case-sensitive (default: False)

        Returns:
            List of files containing the search term

        Example:
            >>> queries = SafeFileQueries()
            >>> files = queries.search_file_content('TODO', project_id=1)
            >>> files = queries.search_file_content('import React',
            ...                                     project_slug='my-app',
            ...                                     file_type='typescript')
        """
        proj_id = self._resolve_project_id(project_id, project_slug)

        sql = """
            SELECT
                pf.file_path,
                pf.file_name,
                ft.type_name,
                cb.content_text
            FROM project_files pf
            JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
            JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
            JOIN file_types ft ON pf.file_type_id = ft.id
            WHERE pf.project_id = ?
              AND cb.content_text IS NOT NULL
        """
        params = [proj_id]

        if case_sensitive:
            sql += " AND cb.content_text LIKE ?"
            params.append(f"%{search_term}%")
        else:
            sql += " AND LOWER(cb.content_text) LIKE LOWER(?)"
            params.append(f"%{search_term}%")

        if file_type:
            sql += " AND ft.type_name = ?"
            params.append(file_type)

        sql += " ORDER BY pf.file_path"

        logger.debug(f"Searching for '{search_term}' in project {proj_id}")
        return self.query_all(sql, tuple(params))

    # ==========================================================================
    # QUERY VALIDATION
    # ==========================================================================

    @staticmethod
    def validate_file_query(sql: str) -> None:
        """
        Validate that a SQL query follows safe file querying practices.

        Checks that queries involving project_files include project_id filters.

        Args:
            sql: SQL query string to validate

        Raises:
            QueryValidationError: If query appears unsafe

        Example:
            >>> SafeFileQueries.validate_file_query(
            ...     "SELECT * FROM project_files WHERE project_id = 1"
            ... )  # OK
            >>>
            >>> SafeFileQueries.validate_file_query(
            ...     "SELECT * FROM project_files WHERE file_path = 'README.md'"
            ... )  # Raises QueryValidationError!
        """
        # Normalize whitespace
        sql_normalized = ' '.join(sql.lower().split())

        # Check if query involves project_files
        if 'project_files' not in sql_normalized:
            return  # Not a file query, validation not needed

        # Check if it's a view that includes project_slug
        safe_views = [
            'files_with_types_view',
            'current_file_contents_view',
            'file_version_history_view',
        ]

        if any(view in sql_normalized for view in safe_views):
            # Using a safe view - check for project_slug filter
            if 'project_slug' in sql_normalized:
                return  # Safe view with project_slug filter

        # Check for project_id filter in WHERE clause
        # Look for patterns like: WHERE ... project_id = ? ...
        if re.search(r'where\s+.*\bproject_id\s*=', sql_normalized):
            return  # Has project_id filter

        # Check for JOIN with projects table (sometimes used for filtering)
        if 'join projects' in sql_normalized and 'projects.id' in sql_normalized:
            return  # Likely filtering via JOIN

        # Query appears unsafe
        raise QueryValidationError(
            "Query involves project_files but doesn't filter by project_id or project_slug. "
            "File paths are NOT globally unique - they must be scoped to a project.\n"
            f"Unsafe query: {sql[:200]}\n"
            "See: QUERY_BEST_PRACTICES.md"
        )

    # ==========================================================================
    # STATISTICS & UTILITIES
    # ==========================================================================

    def get_file_stats(self, project_id: Optional[int] = None,
                       project_slug: Optional[str] = None) -> Dict[str, Any]:
        """
        Get statistics about files in a project.

        Args:
            project_id: Project ID (provide this OR project_slug)
            project_slug: Project slug (provide this OR project_id)

        Returns:
            Dictionary with file counts, total lines, etc.

        Example:
            >>> queries = SafeFileQueries()
            >>> stats = queries.get_file_stats(project_id=1)
            >>> print(f"Total files: {stats['total_files']}")
            >>> print(f"Total lines: {stats['total_lines']}")
        """
        proj_id = self._resolve_project_id(project_id, project_slug)

        result = self.query_one("""
            SELECT
                COUNT(*) as total_files,
                SUM(lines_of_code) as total_lines,
                COUNT(DISTINCT file_type_id) as file_types_count
            FROM project_files
            WHERE project_id = ?
        """, (proj_id,))

        return result or {
            'total_files': 0,
            'total_lines': 0,
            'file_types_count': 0
        }
