#!/usr/bin/env python3
"""
Project Service - Business logic for project operations

Handles project lifecycle operations including creation, importing,
validation, and project discovery.
"""
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from services.base import BaseService
from error_handler import ResourceNotFoundError, ValidationError


@dataclass
class ImportStats:
    """Statistics from a project import operation"""
    total_files_scanned: int = 0
    files_imported: int = 0
    content_stored: int = 0
    versions_created: int = 0
    sql_objects_found: int = 0


class ProjectService(BaseService):
    """
    Service layer for project operations.

    Separates business logic from CLI presentation and provides
    reusable methods for project management.
    """

    def __init__(self, context):
        super().__init__()
        self.ctx = context
        self.project_repo = context.project_repo
        self.file_repo = context.file_repo

    def get_by_slug(self, slug: str, required: bool = False) -> Optional[Dict[str, Any]]:
        """
        Get project by slug.

        Args:
            slug: Project slug identifier
            required: If True, raises ResourceNotFoundError if not found

        Returns:
            Project dictionary or None

        Raises:
            ResourceNotFoundError: If required=True and project not found
        """
        project = self.project_repo.get_by_slug(slug)

        if not project and required:
            raise ResourceNotFoundError(
                f"Project '{slug}' not found",
                solution="Run 'templedb project list' to see available projects"
            )

        return project

    def get_all(self) -> List[Dict[str, Any]]:
        """Get all projects"""
        return self.project_repo.get_all()

    def get_statistics(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Get file statistics for a project"""
        return self.project_repo.get_statistics(project_id)

    def get_vcs_info(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Get VCS information for a project"""
        return self.project_repo.get_vcs_info(project_id)

    def create_project(
        self,
        slug: str,
        name: Optional[str] = None,
        repo_url: Optional[str] = None,
        git_branch: str = 'main'
    ) -> int:
        """
        Create a new project in the database.

        Args:
            slug: Unique project identifier
            name: Human-readable project name
            repo_url: Git repository URL or filesystem path
            git_branch: Default git branch

        Returns:
            Project ID

        Raises:
            ValidationError: If slug is invalid or already exists
        """
        self._validate_required(slug, 'slug')
        self._validate_slug(slug)

        # Check if project already exists
        existing = self.project_repo.get_by_slug(slug)
        if existing:
            raise ValidationError(
                f"Project with slug '{slug}' already exists",
                solution="Use a different slug or 'templedb project show <slug>' to view existing project"
            )

        project_id = self.project_repo.create(
            slug=slug,
            name=name or slug,
            repo_url=repo_url,
            git_branch=git_branch
        )

        self.logger.info(f"Created project '{slug}' with ID {project_id}")
        return project_id

    def init_project(
        self,
        project_path: Path,
        slug: Optional[str] = None,
        name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Initialize a directory as a TempleDB project.

        Creates project database entry and .templedb marker file.

        Args:
            project_path: Absolute path to project directory
            slug: Project slug (defaults to directory name)
            name: Project name (defaults to slug)

        Returns:
            Dictionary with project_id, slug, root

        Raises:
            ValidationError: If already a project or slug exists
        """
        project_path = project_path.resolve()

        # Import here to avoid circular dependency
        from project_context import ProjectContext

        # Check if already in a project
        existing_ctx = ProjectContext.discover(project_path)
        if existing_ctx:
            raise ValidationError(
                f"Already in a TempleDB project: {existing_ctx.slug}",
                solution=f"Project root: {existing_ctx.root}"
            )

        # Determine slug
        final_slug = slug if slug else project_path.name
        self._validate_slug(final_slug)

        # Create project
        project_id = self.create_project(
            slug=final_slug,
            name=name or final_slug,
            repo_url=str(project_path),
            git_branch='main'
        )

        # Create .templedb marker
        ProjectContext.create_marker(
            project_root=project_path,
            slug=final_slug,
            project_id=project_id
        )

        self.logger.info(f"Initialized project '{final_slug}' at {project_path}")

        return {
            'project_id': project_id,
            'slug': final_slug,
            'root': project_path
        }

    def import_project(
        self,
        project_path: Path,
        slug: Optional[str] = None,
        dry_run: bool = False
    ) -> ImportStats:
        """
        Import a project from filesystem into database.

        Creates project if it doesn't exist, updates .templedb marker,
        and scans/imports all files.

        Args:
            project_path: Path to project directory
            slug: Project slug (defaults to directory name)
            dry_run: If True, don't make changes

        Returns:
            ImportStats with import statistics

        Raises:
            ValidationError: If path doesn't exist or isn't a directory
        """
        project_path = project_path.resolve()

        if not project_path.exists():
            raise ValidationError(
                f"Path does not exist: {project_path}",
                solution="Check the path and try again"
            )

        if not project_path.is_dir():
            raise ValidationError(
                f"Path is not a directory: {project_path}",
                solution="Provide a directory path"
            )

        # Determine slug
        final_slug = slug if slug else project_path.name
        self._validate_slug(final_slug)

        # Check if project exists, create if not
        project = self.project_repo.get_by_slug(final_slug)
        from project_context import ProjectContext

        if not project:
            self.logger.info(f"Creating new project: {final_slug}")
            project_id = self.create_project(
                slug=final_slug,
                name=final_slug,
                repo_url=str(project_path),
                git_branch='main'
            )

            # Create .templedb marker
            ProjectContext.create_marker(
                project_root=project_path,
                slug=final_slug,
                project_id=project_id
            )
        else:
            self.logger.info(f"Updating existing project: {final_slug}")
            project_id = project['id']

            # Create .templedb marker if it doesn't exist
            marker_dir = project_path / ".templedb"
            if not marker_dir.exists():
                ProjectContext.create_marker(
                    project_root=project_path,
                    slug=final_slug,
                    project_id=project_id
                )
                self.logger.info("Added .templedb marker to existing project")

        # Import files using ProjectImporter
        from importer import ProjectImporter

        importer = ProjectImporter(final_slug, str(project_path), dry_run=dry_run)
        stats = importer.import_files()

        self.logger.info(
            f"Import completed: {stats.files_imported} files, "
            f"{stats.content_stored} content stored"
        )

        return stats

    def sync_project(self, slug: str, repo_path: Optional[str] = None) -> ImportStats:
        """
        Re-import/sync project from filesystem.

        Args:
            slug: Project slug
            repo_path: Optional path override (uses project's repo_url if None)

        Returns:
            ImportStats with sync statistics

        Raises:
            ResourceNotFoundError: If project not found
            ValidationError: If repo path invalid
        """
        project = self.get_by_slug(slug, required=True)

        # Determine path
        if repo_path is None:
            repo_path = project.get('repo_url')
            if not repo_path:
                raise ValidationError(
                    f"Project '{slug}' has no repo_url set",
                    solution="Provide a path explicitly or update project repo_url"
                )

        path = Path(repo_path)
        if not path.exists():
            raise ValidationError(
                f"Project path not found: {path}",
                solution="Check the path and try again"
            )

        self.logger.info(f"Syncing {slug} from {repo_path}")

        # Use ProjectImporter
        from importer import ProjectImporter

        importer = ProjectImporter(slug, str(path), dry_run=False)
        stats = importer.import_files()

        self.logger.info(f"Sync completed for {slug}")
        return stats

    def delete_project(self, slug: str) -> None:
        """
        Delete a project and all related data.

        Args:
            slug: Project slug

        Raises:
            ResourceNotFoundError: If project not found
        """
        project = self.get_by_slug(slug, required=True)
        project_id = project['id']

        self.project_repo.delete(project_id)
        self.logger.info(f"Deleted project: {slug}")

    def generate_envrc(
        self,
        slug: str,
        force: bool = False
    ) -> Path:
        """
        Generate .envrc file for a project.

        Args:
            slug: Project slug
            force: If True, overwrite existing .envrc

        Returns:
            Path to generated .envrc file

        Raises:
            ResourceNotFoundError: If project not found
            ValidationError: If project has no repo_url or path doesn't exist
        """
        project = self.get_by_slug(slug, required=True)

        repo_url = project.get('repo_url')
        if not repo_url:
            raise ValidationError(
                f"Project '{slug}' has no repo_url set",
                solution="Update project with a valid repo_url"
            )

        project_path = Path(repo_url)
        if not project_path.exists():
            raise ValidationError(
                f"Project path does not exist: {project_path}",
                solution="Check the path and update project if needed"
            )

        envrc_path = project_path / ".envrc"

        if envrc_path.exists() and not force:
            self.logger.info(f".envrc already exists at {envrc_path}")
            return envrc_path

        # Generate .envrc content
        import os
        templedb_path = os.path.abspath(
            os.path.join(self.ctx.script_dir, 'templedb')
        )
        envrc_content = f'eval "$({templedb_path} direnv)"\n'

        envrc_path.write_text(envrc_content)
        self.logger.info(f"Generated .envrc at {envrc_path}")

        return envrc_path
