#!/usr/bin/env python3
"""
Service Context - Dependency Injection Container

Provides centralized access to all services and repositories, eliminating
duplicate initialization across command classes.
"""
from pathlib import Path
from typing import Optional
from repositories import ProjectRepository, FileRepository, BaseRepository
from logger import get_logger

logger = get_logger(__name__)


class ServiceContext:
    """
    Centralized dependency injection container for services and repositories.

    Usage:
        ctx = ServiceContext()
        project_service = ctx.get_project_service()
        project = project_service.get_by_slug('my-project')
    """

    def __init__(self):
        """Initialize context with lazy-loaded dependencies"""
        self._project_repo: Optional[ProjectRepository] = None
        self._file_repo: Optional[FileRepository] = None
        self._base_repo: Optional[BaseRepository] = None
        self._script_dir: Optional[Path] = None

        # Service cache
        self._project_service = None
        self._deployment_service = None
        self._vcs_service = None
        self._environment_service = None

    @property
    def script_dir(self) -> Path:
        """Get the script directory (project root)"""
        if self._script_dir is None:
            self._script_dir = Path(__file__).parent.parent.parent.resolve()
        return self._script_dir

    # Repository accessors (lazy-loaded)
    @property
    def project_repo(self) -> ProjectRepository:
        """Get ProjectRepository instance"""
        if self._project_repo is None:
            self._project_repo = ProjectRepository()
        return self._project_repo

    @property
    def file_repo(self) -> FileRepository:
        """Get FileRepository instance"""
        if self._file_repo is None:
            self._file_repo = FileRepository()
        return self._file_repo

    @property
    def base_repo(self) -> BaseRepository:
        """Get BaseRepository instance for custom queries"""
        if self._base_repo is None:
            self._base_repo = BaseRepository()
        return self._base_repo

    # Service accessors (lazy-loaded, singleton within context)
    def get_project_service(self):
        """Get ProjectService instance"""
        if self._project_service is None:
            from services.project_service import ProjectService
            self._project_service = ProjectService(self)
        return self._project_service

    def get_deployment_service(self):
        """Get DeploymentService instance"""
        if self._deployment_service is None:
            from services.deployment_service import DeploymentService
            self._deployment_service = DeploymentService(self)
        return self._deployment_service

    def get_vcs_service(self):
        """Get VCSService instance"""
        if self._vcs_service is None:
            from services.vcs_service import VCSService
            self._vcs_service = VCSService(self)
        return self._vcs_service

    def get_environment_service(self):
        """Get EnvironmentService instance"""
        if self._environment_service is None:
            from services.environment_service import EnvironmentService
            self._environment_service = EnvironmentService(self)
        return self._environment_service

    def dispose(self):
        """Clean up resources (for testing)"""
        self._project_repo = None
        self._file_repo = None
        self._base_repo = None
        self._project_service = None
        self._deployment_service = None
        self._vcs_service = None
        self._environment_service = None
