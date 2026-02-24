"""
Project repository for managing project data.
"""

from typing import Optional, List, Dict, Any
from pathlib import Path

from .base import BaseRepository
from logger import get_logger

logger = get_logger(__name__)


class ProjectRepository(BaseRepository):
    """
    Repository for project-related database operations.

    Provides a clean interface for:
    - Finding projects by slug or ID
    - Creating and updating projects
    - Deleting projects
    - Getting project statistics
    """

    def get_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """
        Find a project by its slug.

        Args:
            slug: Project slug

        Returns:
            Project dictionary or None if not found

        Example:
            >>> repo = ProjectRepository()
            >>> project = repo.get_by_slug("myproject")
            >>> print(project['name'])
        """
        logger.debug(f"Finding project by slug: {slug}")
        return self.query_one("SELECT * FROM projects WHERE slug = ?", (slug,))

    def get_by_id(self, project_id: int) -> Optional[Dict[str, Any]]:
        """
        Find a project by its ID.

        Args:
            project_id: Project ID

        Returns:
            Project dictionary or None if not found
        """
        logger.debug(f"Finding project by ID: {project_id}")
        return self.query_one("SELECT * FROM projects WHERE id = ?", (project_id,))

    def get_all(self) -> List[Dict[str, Any]]:
        """
        Get all projects with file counts and line counts.

        Returns:
            List of project dictionaries with statistics
        """
        logger.debug("Fetching all projects with statistics")
        return self.query_all("""
            SELECT
                p.id,
                p.slug,
                p.name,
                p.repo_url,
                p.git_branch,
                p.created_at,
                p.updated_at,
                COUNT(pf.id) as file_count,
                SUM(pf.lines_of_code) as total_lines
            FROM projects p
            LEFT JOIN project_files pf ON p.id = pf.project_id
            GROUP BY p.id
            ORDER BY p.slug
        """)

    def create(self, slug: str, name: str = None, repo_url: str = None,
               git_branch: str = 'main') -> int:
        """
        Create a new project.

        Args:
            slug: Unique project slug
            name: Project name (defaults to slug)
            repo_url: Repository URL (optional)
            git_branch: Git branch name (default: 'main')

        Returns:
            Project ID

        Raises:
            Exception: If project with slug already exists
        """
        logger.info(f"Creating project: {slug}")

        # Check if project exists
        existing = self.get_by_slug(slug)
        if existing:
            raise ValueError(f"Project with slug '{slug}' already exists")

        project_id = self.execute("""
            INSERT INTO projects (slug, name, repo_url, git_branch)
            VALUES (?, ?, ?, ?)
        """, (slug, name or slug, repo_url, git_branch))

        logger.info(f"Created project '{slug}' with ID {project_id}")
        return project_id

    def update(self, project_id: int, **kwargs) -> None:
        """
        Update a project's fields.

        Args:
            project_id: Project ID
            **kwargs: Fields to update (name, repo_url, git_branch, status)

        Example:
            >>> repo = ProjectRepository()
            >>> repo.update(1, name="New Name", status="archived")
        """
        if not kwargs:
            logger.warning(f"No fields to update for project {project_id}")
            return

        # Build SET clause
        set_parts = [f"{key} = ?" for key in kwargs.keys()]
        values = list(kwargs.values()) + [project_id]

        sql = f"UPDATE projects SET {', '.join(set_parts)} WHERE id = ?"

        logger.info(f"Updating project {project_id} with fields: {list(kwargs.keys())}")
        self.execute(sql, tuple(values))

    def delete(self, project_id: int) -> None:
        """
        Delete a project.

        Note: CASCADE will delete related records (files, commits, etc.)

        Args:
            project_id: Project ID
        """
        logger.info(f"Deleting project with ID {project_id}")
        self.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        logger.info(f"Deleted project {project_id}")

    def get_statistics(self, project_id: int) -> Optional[Dict[str, Any]]:
        """
        Get detailed statistics for a project.

        Args:
            project_id: Project ID

        Returns:
            Dictionary with file_count, total_lines, file_types
        """
        logger.debug(f"Getting statistics for project {project_id}")
        return self.query_one("""
            SELECT
                COUNT(*) as file_count,
                SUM(lines_of_code) as total_lines,
                COUNT(DISTINCT file_type_id) as file_types
            FROM project_files
            WHERE project_id = ?
        """, (project_id,))

    def get_vcs_info(self, project_id: int) -> Optional[Dict[str, Any]]:
        """
        Get version control statistics for a project.

        Args:
            project_id: Project ID

        Returns:
            Dictionary with branch_count and commit_count
        """
        logger.debug(f"Getting VCS info for project {project_id}")
        return self.query_one("""
            SELECT
                COUNT(DISTINCT vb.id) as branch_count,
                COUNT(DISTINCT vc.id) as commit_count
            FROM vcs_branches vb
            LEFT JOIN vcs_commits vc ON vb.id = vc.branch_id
            WHERE vb.project_id = ?
        """, (project_id,))

    def exists(self, slug: str) -> bool:
        """
        Check if a project exists by slug.

        Args:
            slug: Project slug

        Returns:
            True if project exists, False otherwise
        """
        project = self.get_by_slug(slug)
        return project is not None
