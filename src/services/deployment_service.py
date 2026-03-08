#!/usr/bin/env python3
"""
Deployment Service - Business logic for deployment operations

Handles project deployment including cathedral export, reconstruction,
and orchestration of deployment workflows.
"""
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass
import subprocess
import json
import shutil

from services.base import BaseService
from error_handler import ResourceNotFoundError, DeploymentError


@dataclass
class DeploymentResult:
    """Result of a deployment operation"""
    success: bool
    project_slug: str
    target: str
    work_dir: Path
    message: str
    exit_code: int = 0


class DeploymentService(BaseService):
    """
    Service layer for deployment operations.

    Orchestrates the full deployment workflow:
    1. Export project from TempleDB (cathedral package)
    2. Reconstruct project filesystem
    3. Execute deployment (via orchestrator or deploy.sh)
    """

    def __init__(self, context):
        super().__init__()
        self.ctx = context
        self.project_repo = context.project_repo
        self.script_dir = context.script_dir

    def deploy(
        self,
        project_slug: str,
        target: str = 'production',
        dry_run: bool = False,
        skip_validation: bool = False
    ) -> DeploymentResult:
        """
        Deploy a project to a target environment.

        Args:
            project_slug: Project slug identifier
            target: Deployment target name (e.g., 'production', 'staging')
            dry_run: If True, simulate deployment without making changes
            skip_validation: If True, skip environment variable validation

        Returns:
            DeploymentResult with deployment status

        Raises:
            ResourceNotFoundError: If project doesn't exist
            DeploymentError: If deployment fails
        """
        # Verify project exists
        project = self.project_repo.get_by_slug(project_slug)
        if not project:
            raise ResourceNotFoundError(
                f"Project '{project_slug}' not found",
                solution="Run 'templedb project list' to see available projects"
            )

        self.logger.info(f"Starting deployment: {project_slug} to {target}")

        try:
            # Step 1: Export cathedral package
            export_dir = Path(f"/tmp/templedb_deploy_{project_slug}")
            export_dir.mkdir(parents=True, exist_ok=True)

            self.logger.info("Exporting project from TempleDB...")
            cathedral_dir = self._export_project(project_slug, export_dir)

            # Step 2: Reconstruct project
            work_dir = export_dir / "working"
            work_dir.mkdir(exist_ok=True)

            self.logger.info("Reconstructing project from cathedral package...")
            file_count = self._reconstruct_project(cathedral_dir, work_dir)
            self.logger.info(f"Reconstructed {file_count} files")

            # Step 3: Execute deployment
            result = self._execute_deployment(
                project=project,
                target=target,
                work_dir=work_dir,
                dry_run=dry_run,
                validate_env=not skip_validation
            )

            return result

        except Exception as e:
            self.logger.error(f"Deployment failed: {e}", exc_info=True)
            raise DeploymentError(
                f"Deployment failed for {project_slug}",
                solution="Check logs for detailed error information"
            ) from e

    def _export_project(self, project_slug: str, export_dir: Path) -> Path:
        """
        Export project as cathedral package.

        Returns:
            Path to cathedral directory
        """
        from cathedral_export import export_project

        success = export_project(
            slug=project_slug,
            output_dir=export_dir,
            compress=False,
            include_files=True,
            include_vcs=True,
            include_environments=True
        )

        if not success:
            raise DeploymentError(
                "Export failed",
                solution="Check project exists and has files to export"
            )

        cathedral_dir = export_dir / f"{project_slug}.cathedral"

        if not cathedral_dir.exists():
            raise DeploymentError(
                f"Cathedral directory not found: {cathedral_dir}",
                solution="Export may have failed silently - check logs"
            )

        return cathedral_dir

    def _reconstruct_project(self, cathedral_dir: Path, work_dir: Path) -> int:
        """
        Reconstruct project structure from cathedral package.

        Returns:
            Number of files reconstructed
        """
        files_dir = cathedral_dir / "files"

        if not files_dir.exists():
            raise DeploymentError(
                f"Files directory not found: {files_dir}",
                solution="Cathedral package may be corrupted"
            )

        file_count = 0
        for file_json in sorted(files_dir.glob("*.json")):
            if file_json.name == "manifest.json":
                continue

            # Read metadata
            with open(file_json, 'r') as f:
                metadata = json.load(f)

            file_path = metadata.get('file_path')
            if not file_path:
                continue

            # Check for corresponding blob
            blob_file = file_json.with_suffix('.blob')
            if not blob_file.exists():
                continue

            # Create target path
            target_file = work_dir / file_path
            target_file.parent.mkdir(parents=True, exist_ok=True)

            # Copy blob to target location
            shutil.copy2(blob_file, target_file)
            file_count += 1

        return file_count

    def _execute_deployment(
        self,
        project: Dict[str, Any],
        target: str,
        work_dir: Path,
        dry_run: bool,
        validate_env: bool
    ) -> DeploymentResult:
        """
        Execute deployment using orchestrator or deploy.sh.

        Returns:
            DeploymentResult
        """
        project_slug = project['slug']

        # Check for deployment configuration
        import db_utils
        from deployment_config import DeploymentConfigManager

        config_manager = DeploymentConfigManager(db_utils)
        config = config_manager.get_config(project['id'])

        if config.groups:
            # Use orchestrated deployment
            self.logger.info("Using deployment orchestrator")

            from deployment_orchestrator import DeploymentOrchestrator

            orchestrator = DeploymentOrchestrator(
                project=project,
                target_name=target,
                config=config,
                db_utils=db_utils,
                work_dir=work_dir
            )

            result = orchestrator.deploy(
                dry_run=dry_run,
                validate_env=validate_env
            )

            return DeploymentResult(
                success=result.success,
                project_slug=project_slug,
                target=target,
                work_dir=work_dir,
                message=result.summary if hasattr(result, 'summary') else "Deployment completed",
                exit_code=0 if result.success else 1
            )

        else:
            # Fallback to deploy.sh script
            deploy_script = work_dir / "deploy.sh"

            if deploy_script.exists():
                self.logger.info(f"Using deployment script: {deploy_script.name}")

                if dry_run:
                    return DeploymentResult(
                        success=True,
                        project_slug=project_slug,
                        target=target,
                        work_dir=work_dir,
                        message="Dry run complete - no actual deployment performed",
                        exit_code=0
                    )

                # Execute deployment script
                result = subprocess.run(
                    ["bash", str(deploy_script)],
                    cwd=work_dir,
                    env={**subprocess.os.environ, "DEPLOYMENT_TARGET": target}
                )

                if result.returncode == 0:
                    return DeploymentResult(
                        success=True,
                        project_slug=project_slug,
                        target=target,
                        work_dir=work_dir,
                        message="Deployment complete",
                        exit_code=0
                    )
                else:
                    return DeploymentResult(
                        success=False,
                        project_slug=project_slug,
                        target=target,
                        work_dir=work_dir,
                        message=f"Deployment script failed with exit code {result.returncode}",
                        exit_code=result.returncode
                    )
            else:
                # No deployment method configured
                return DeploymentResult(
                    success=True,  # Not a failure, just no deployment configured
                    project_slug=project_slug,
                    target=target,
                    work_dir=work_dir,
                    message="No deployment configuration found - files prepared for manual deployment",
                    exit_code=0
                )

    def get_deployment_status(self, project_slug: str) -> Dict[str, Any]:
        """
        Get deployment status information for a project.

        Args:
            project_slug: Project slug

        Returns:
            Dictionary with deployment targets, scripts, migrations

        Raises:
            ResourceNotFoundError: If project not found
        """
        project = self.project_repo.get_by_slug(project_slug)
        if not project:
            raise ResourceNotFoundError(
                f"Project '{project_slug}' not found",
                solution="Run 'templedb project list' to see available projects"
            )

        # Get deployment targets
        targets = self.ctx.base_repo.query_all("""
            SELECT target_name, target_type, provider, host
            FROM deployment_targets
            WHERE project_id = ?
            ORDER BY target_name
        """, (project['id'],))

        # Get deployment scripts
        deploy_files = self.ctx.base_repo.query_all("""
            SELECT file_path
            FROM files_with_types_view
            WHERE project_slug = ? AND file_path LIKE '%deploy%'
            ORDER BY file_path
        """, (project_slug,))

        # Get migration count
        result = self.ctx.base_repo.query_one("""
            SELECT COUNT(*) as count
            FROM files_with_types_view
            WHERE project_slug = ? AND type_name = 'sql_migration'
        """, (project_slug,))

        migration_count = result['count'] if result else 0

        return {
            'project_slug': project_slug,
            'targets': targets,
            'deploy_scripts': [f['file_path'] for f in deploy_files],
            'migration_count': migration_count
        }
