#!/usr/bin/env python3
"""
Environment Service - Business logic for environment management

Handles Nix environment operations including entering environments,
listing environments, and managing environment configurations.
"""
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from services.base import BaseService
from error_handler import ResourceNotFoundError, ValidationError


@dataclass
class EnvironmentSession:
    """Environment session information"""
    session_id: int
    project_slug: str
    env_name: str
    nix_file: Path


class EnvironmentService(BaseService):
    """
    Service layer for environment operations.

    Manages Nix FHS environments for projects including session tracking,
    environment generation, and environment listing.
    """

    def __init__(self, context):
        super().__init__()
        self.ctx = context
        self.project_repo = context.project_repo
        self.env_repo = context.base_repo

        # Set up nix_env_dir
        from db_utils import DB_PATH
        self.nix_env_dir = Path(DB_PATH).parent / "nix-envs"
        self.nix_env_dir.mkdir(exist_ok=True)

    def get_environment(
        self,
        project_slug: str,
        env_name: str = 'dev'
    ) -> Optional[Dict[str, Any]]:
        """
        Get environment by project and name.

        Args:
            project_slug: Project slug
            env_name: Environment name (default: 'dev')

        Returns:
            Environment dictionary or None

        Raises:
            ResourceNotFoundError: If project not found
        """
        project = self.project_repo.get_by_slug(project_slug)
        if not project:
            raise ResourceNotFoundError(
                f"Project '{project_slug}' not found",
                solution="Run 'templedb project list' to see available projects"
            )

        env = self.env_repo.query_one("""
            SELECT * FROM nix_environments
            WHERE project_id = ? AND env_name = ?
        """, (project['id'], env_name))

        return env

    def list_environments(
        self,
        project_slug: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        List environments.

        Args:
            project_slug: Optional project slug to filter (lists all if None)

        Returns:
            List of environment dictionaries
        """
        if project_slug:
            rows = self.env_repo.query_all("""
                SELECT
                    env_name,
                    description,
                    (LENGTH(base_packages) - LENGTH(REPLACE(base_packages, ',', '')) + 1) as package_count,
                    (SELECT COUNT(*) FROM nix_env_sessions WHERE environment_id = ne.id) as session_count
                FROM nix_environments ne
                WHERE project_id = (SELECT id FROM projects WHERE slug = ?)
                ORDER BY env_name
            """, (project_slug,))
        else:
            rows = self.env_repo.query_all("""
                SELECT
                    p.slug as project_slug,
                    ne.env_name,
                    (LENGTH(ne.base_packages) - LENGTH(REPLACE(ne.base_packages, ',', '')) + 1) as package_count,
                    (SELECT COUNT(*) FROM nix_env_sessions WHERE environment_id = ne.id) as session_count
                FROM nix_environments ne
                JOIN projects p ON ne.project_id = p.id
                ORDER BY p.slug, ne.env_name
            """)

        return rows

    def generate_nix_expression(
        self,
        project_slug: str,
        env_name: str = 'dev'
    ) -> Path:
        """
        Generate Nix expression for environment.

        Args:
            project_slug: Project slug
            env_name: Environment name

        Returns:
            Path to generated Nix file

        Raises:
            ResourceNotFoundError: If project or environment not found
        """
        import subprocess
        import sys

        project = self.project_repo.get_by_slug(project_slug)
        if not project:
            raise ResourceNotFoundError(
                f"Project '{project_slug}' not found",
                solution="Run 'templedb project list' to see available projects"
            )

        env = self.get_environment(project_slug, env_name)
        if not env:
            raise ResourceNotFoundError(
                f"Environment '{env_name}' not found for project '{project_slug}'",
                solution=f"Create environment with: templedb env detect {project_slug}"
            )

        nix_file = self.nix_env_dir / f"{project_slug}-{env_name}.nix"

        # Generate Nix expression using generator script
        result = subprocess.run([
            sys.executable,
            str(self.ctx.script_dir / "src" / "nix_env_generator.py"),
            "generate",
            "-p", project_slug,
            "-e", env_name
        ], capture_output=True, text=True)

        if result.returncode != 0:
            raise ValidationError(
                "Failed to generate Nix expression",
                solution=f"Error: {result.stderr}" if result.stderr else "Check generator logs"
            )

        self.logger.info(f"Generated Nix expression: {nix_file}")
        return nix_file

    def prepare_environment_session(
        self,
        project_slug: str,
        env_name: str = 'dev'
    ) -> EnvironmentSession:
        """
        Prepare environment session (generates Nix file and creates session tracking).

        Args:
            project_slug: Project slug
            env_name: Environment name

        Returns:
            EnvironmentSession with session info

        Raises:
            ResourceNotFoundError: If project or environment not found
        """
        project = self.project_repo.get_by_slug(project_slug)
        if not project:
            raise ResourceNotFoundError(
                f"Project '{project_slug}' not found"
            )

        env = self.get_environment(project_slug, env_name)
        if not env:
            raise ResourceNotFoundError(
                f"Environment '{env_name}' not found for project '{project_slug}'",
                solution=f"List environments with: templedb env list {project_slug}"
            )

        # Generate Nix expression if needed
        nix_file = self.nix_env_dir / f"{project_slug}-{env_name}.nix"
        if not nix_file.exists():
            self.logger.info(f"Generating Nix expression for {project_slug}:{env_name}")
            nix_file = self.generate_nix_expression(project_slug, env_name)

        # Start session tracking
        session_id = self.env_repo.execute("""
            INSERT INTO nix_env_sessions (environment_id, started_at)
            VALUES (?, datetime('now'))
        """, (env['id'],))

        return EnvironmentSession(
            session_id=session_id,
            project_slug=project_slug,
            env_name=env_name,
            nix_file=nix_file
        )

    def end_environment_session(
        self,
        session_id: int,
        exit_code: int = 0
    ) -> None:
        """
        End environment session tracking.

        Args:
            session_id: Session ID
            exit_code: Exit code from shell
        """
        self.env_repo.execute("""
            UPDATE nix_env_sessions
            SET ended_at = datetime('now'), exit_code = ?
            WHERE id = ?
        """, (exit_code, session_id))

        self.logger.info(f"Ended environment session {session_id}")
