"""
Consolidated Safe Query API for TempleDB

This module provides safe query APIs for all project-scoped tables.
All methods ENFORCE project_id filtering to prevent cross-project data bugs.

Tables with non-globally-unique fields that MUST be scoped to project:
- project_files (file_path)
- deployment_targets (target_name, target_type)
- api_endpoints (endpoint_path, http_method)
- database_migrations (migration_number)
- nix_environments (env_name)
- vcs_branches (branch_name)

Usage:
    >>> from safe_queries import SafeQueries
    >>> queries = SafeQueries()
    >>>
    >>> # Files
    >>> file = queries.files.get_by_path('README.md', project_id=1)
    >>>
    >>> # Deployment targets
    >>> target = queries.targets.get_target('production', project_id=1)
    >>>
    >>> # API endpoints
    >>> endpoint = queries.endpoints.get_endpoint('/api/users', 'GET', project_id=1)
    >>>
    >>> # Environments
    >>> env = queries.environments.get_environment('dev', project_id=1)
"""

from typing import Optional, List, Dict, Any
from repositories.base import BaseRepository
from repositories.project_repository import ProjectRepository
from logger import get_logger

logger = get_logger(__name__)


class QueryValidationError(Exception):
    """Raised when a query violates safety constraints."""
    pass


class _ProjectContextMixin:
    """Mixin for handling project_id/project_slug resolution."""

    def __init__(self):
        self._project_repo = ProjectRepository()

    def _resolve_project_id(self, project_id: Optional[int] = None,
                           project_slug: Optional[str] = None) -> int:
        """
        Resolve project_id from either project_id or project_slug.

        Raises:
            ValueError: If neither or both parameters provided
            QueryValidationError: If project doesn't exist
        """
        if project_id is None and project_slug is None:
            raise ValueError(
                "Either project_id or project_slug must be provided. "
                "Fields are NOT globally unique - they must be scoped to a project."
            )

        if project_id is not None and project_slug is not None:
            raise ValueError("Provide either project_id OR project_slug, not both")

        if project_slug is not None:
            project = self._project_repo.get_project_by_slug(project_slug)
            if not project:
                raise QueryValidationError(f"Project not found: {project_slug}")
            return project['id']

        return project_id


class SafeFileQueries(_ProjectContextMixin, BaseRepository):
    """Safe API for querying files (project_files table)."""

    def get_by_path(self, file_path: str,
                    project_id: Optional[int] = None,
                    project_slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get a file by path within a specific project."""
        proj_id = self._resolve_project_id(project_id, project_slug)
        return self.query_one("""
            SELECT pf.*, ft.type_name, ft.category as file_category
            FROM project_files pf
            JOIN file_types ft ON pf.file_type_id = ft.id
            WHERE pf.project_id = ? AND pf.file_path = ?
        """, (proj_id, file_path))

    def get_content(self, file_path: str,
                    project_id: Optional[int] = None,
                    project_slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get file content within a specific project."""
        proj_id = self._resolve_project_id(project_id, project_slug)
        return self.query_one("""
            SELECT cb.content_text, cb.content_blob, cb.content_type,
                   cb.encoding, cb.file_size_bytes, cb.hash_sha256
            FROM project_files pf
            JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
            JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
            WHERE pf.project_id = ? AND pf.file_path = ?
        """, (proj_id, file_path))

    def list_files(self, project_id: Optional[int] = None,
                   project_slug: Optional[str] = None,
                   pattern: Optional[str] = None) -> List[Dict[str, Any]]:
        """List files in a project with optional GLOB pattern."""
        proj_id = self._resolve_project_id(project_id, project_slug)
        sql = "SELECT * FROM project_files WHERE project_id = ?"
        params = [proj_id]

        if pattern:
            sql += " AND file_path GLOB ?"
            params.append(pattern)

        sql += " ORDER BY file_path"
        return self.query_all(sql, tuple(params))


class SafeDeploymentQueries(_ProjectContextMixin, BaseRepository):
    """Safe API for querying deployment targets."""

    def get_target(self, target_name: str, target_type: str = None,
                   project_id: Optional[int] = None,
                   project_slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get a deployment target by name within a specific project.

        Args:
            target_name: Target name (e.g., 'production', 'staging')
            target_type: Optional target type filter
            project_id: Project ID (provide this OR project_slug)
            project_slug: Project slug (provide this OR project_id)

        Returns:
            Deployment target dictionary or None
        """
        proj_id = self._resolve_project_id(project_id, project_slug)

        if target_type:
            return self.query_one("""
                SELECT * FROM deployment_targets
                WHERE project_id = ? AND target_name = ? AND target_type = ?
            """, (proj_id, target_name, target_type))
        else:
            return self.query_one("""
                SELECT * FROM deployment_targets
                WHERE project_id = ? AND target_name = ?
            """, (proj_id, target_name))

    def list_targets(self, project_id: Optional[int] = None,
                     project_slug: Optional[str] = None,
                     target_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """List deployment targets for a project."""
        proj_id = self._resolve_project_id(project_id, project_slug)

        sql = "SELECT * FROM deployment_targets WHERE project_id = ?"
        params = [proj_id]

        if target_type:
            sql += " AND target_type = ?"
            params.append(target_type)

        sql += " ORDER BY target_name"
        return self.query_all(sql, tuple(params))


class SafeAPIQueries(_ProjectContextMixin, BaseRepository):
    """Safe API for querying API endpoints."""

    def get_endpoint(self, endpoint_path: str, http_method: str,
                     project_id: Optional[int] = None,
                     project_slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get an API endpoint by path and method within a specific project.

        Args:
            endpoint_path: Endpoint path (e.g., '/api/users/:id')
            http_method: HTTP method (e.g., 'GET', 'POST')
            project_id: Project ID (provide this OR project_slug)
            project_slug: Project slug (provide this OR project_id)

        Returns:
            API endpoint dictionary or None
        """
        proj_id = self._resolve_project_id(project_id, project_slug)
        return self.query_one("""
            SELECT * FROM api_endpoints
            WHERE project_id = ? AND endpoint_path = ? AND http_method = ?
        """, (proj_id, endpoint_path, http_method))

    def list_endpoints(self, project_id: Optional[int] = None,
                       project_slug: Optional[str] = None,
                       http_method: Optional[str] = None) -> List[Dict[str, Any]]:
        """List API endpoints for a project."""
        proj_id = self._resolve_project_id(project_id, project_slug)

        sql = "SELECT * FROM api_endpoints WHERE project_id = ?"
        params = [proj_id]

        if http_method:
            sql += " AND http_method = ?"
            params.append(http_method)

        sql += " ORDER BY endpoint_path"
        return self.query_all(sql, tuple(params))


class SafeMigrationQueries(_ProjectContextMixin, BaseRepository):
    """Safe API for querying database migrations."""

    def get_migration(self, migration_number: str,
                      project_id: Optional[int] = None,
                      project_slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get a migration by number within a specific project.

        Args:
            migration_number: Migration number (e.g., '001', '20240115_001')
            project_id: Project ID (provide this OR project_slug)
            project_slug: Project slug (provide this OR project_id)

        Returns:
            Migration dictionary or None
        """
        proj_id = self._resolve_project_id(project_id, project_slug)
        return self.query_one("""
            SELECT * FROM database_migrations
            WHERE project_id = ? AND migration_number = ?
        """, (proj_id, migration_number))

    def list_migrations(self, project_id: Optional[int] = None,
                        project_slug: Optional[str] = None,
                        status: Optional[str] = None) -> List[Dict[str, Any]]:
        """List migrations for a project."""
        proj_id = self._resolve_project_id(project_id, project_slug)

        sql = "SELECT * FROM database_migrations WHERE project_id = ?"
        params = [proj_id]

        if status:
            sql += " AND status = ?"
            params.append(status)

        sql += " ORDER BY migration_number"
        return self.query_all(sql, tuple(params))


class SafeEnvironmentQueries(_ProjectContextMixin, BaseRepository):
    """Safe API for querying Nix environments."""

    def get_environment(self, env_name: str,
                        project_id: Optional[int] = None,
                        project_slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get a Nix environment by name within a specific project.

        Args:
            env_name: Environment name (e.g., 'dev', 'prod')
            project_id: Project ID (provide this OR project_slug)
            project_slug: Project slug (provide this OR project_id)

        Returns:
            Environment dictionary or None
        """
        proj_id = self._resolve_project_id(project_id, project_slug)
        return self.query_one("""
            SELECT * FROM nix_environments
            WHERE project_id = ? AND env_name = ?
        """, (proj_id, env_name))

    def list_environments(self, project_id: Optional[int] = None,
                          project_slug: Optional[str] = None) -> List[Dict[str, Any]]:
        """List Nix environments for a project."""
        proj_id = self._resolve_project_id(project_id, project_slug)
        return self.query_all("""
            SELECT * FROM nix_environments
            WHERE project_id = ?
            ORDER BY env_name
        """, (proj_id,))


class SafeBranchQueries(_ProjectContextMixin, BaseRepository):
    """Safe API for querying VCS branches."""

    def get_branch(self, branch_name: str,
                   project_id: Optional[int] = None,
                   project_slug: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Get a branch by name within a specific project.

        Args:
            branch_name: Branch name (e.g., 'main', 'develop')
            project_id: Project ID (provide this OR project_slug)
            project_slug: Project slug (provide this OR project_id)

        Returns:
            Branch dictionary or None
        """
        proj_id = self._resolve_project_id(project_id, project_slug)
        return self.query_one("""
            SELECT * FROM vcs_branches
            WHERE project_id = ? AND branch_name = ?
        """, (proj_id, branch_name))

    def list_branches(self, project_id: Optional[int] = None,
                      project_slug: Optional[str] = None) -> List[Dict[str, Any]]:
        """List branches for a project."""
        proj_id = self._resolve_project_id(project_id, project_slug)
        return self.query_all("""
            SELECT * FROM vcs_branches
            WHERE project_id = ?
            ORDER BY is_default DESC, branch_name
        """, (proj_id,))


class SafeQueries:
    """
    Consolidated safe query API for all project-scoped tables.

    Provides a single entry point for all safe query operations.

    Usage:
        >>> queries = SafeQueries()
        >>> file = queries.files.get_by_path('README.md', project_id=1)
        >>> target = queries.targets.get_target('production', project_id=1)
        >>> endpoint = queries.endpoints.get_endpoint('/api/users', 'GET', project_id=1)
    """

    def __init__(self):
        self.files = SafeFileQueries()
        self.targets = SafeDeploymentQueries()
        self.endpoints = SafeAPIQueries()
        self.migrations = SafeMigrationQueries()
        self.environments = SafeEnvironmentQueries()
        self.branches = SafeBranchQueries()

    def __repr__(self):
        return (
            "SafeQueries(files, targets, endpoints, migrations, environments, branches)"
        )
