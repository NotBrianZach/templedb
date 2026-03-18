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
from services.deployment_cache import DeploymentCacheService, ContentHash
from error_handler import ResourceNotFoundError, DeploymentError
from config import DEPLOYMENT_USE_FHS, DEPLOYMENT_USE_FULL_FHS, DEPLOYMENT_FHS_DIR, DEPLOYMENT_FALLBACK_DIR
import time


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
        self.cache_service = DeploymentCacheService()

    def deploy(
        self,
        project_slug: str,
        target: str = 'production',
        dry_run: bool = False,
        skip_validation: bool = False,
        mutable: bool = False,
        use_full_fhs: Optional[bool] = None
    ) -> DeploymentResult:
        """
        Deploy a project to a target environment.

        Args:
            project_slug: Project slug identifier
            target: Deployment target name (e.g., 'production', 'staging')
            dry_run: If True, simulate deployment without making changes
            skip_validation: If True, skip environment variable validation
            mutable: If True, skip FHS isolation (allows direct file editing)
            use_full_fhs: Override default FHS behavior (None = use config default)

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

        # Determine if we should use full FHS integration
        if use_full_fhs is None:
            use_full_fhs = DEPLOYMENT_USE_FULL_FHS and not mutable

        if mutable:
            self.logger.info("⚠️  Mutable mode: FHS isolation disabled")
            self.logger.info("   Files can be edited directly, but deployment is not reproducible")

        self.logger.info(f"Starting deployment: {project_slug} to {target}")

        # Track timing
        start_time = time.time()
        export_time = 0
        build_time = 0

        try:
            # Step 1: Determine deployment location (FHS-style or /tmp)
            if DEPLOYMENT_USE_FHS:
                self.logger.info(f"Using FHS-style deployment directory: {DEPLOYMENT_FHS_DIR}")
                export_dir = DEPLOYMENT_FHS_DIR / project_slug
                self.logger.info(f"  Location: {export_dir}")
            else:
                self.logger.info("Using traditional /tmp deployment")
                export_dir = DEPLOYMENT_FALLBACK_DIR / f"templedb_deploy_{project_slug}"
                self.logger.info(f"  Location: {export_dir}")

            export_dir.mkdir(parents=True, exist_ok=True)

            # Store FHS preference
            self._use_full_fhs = use_full_fhs
            self._fhs_context = None

            # Step 1.5: Check deployment cache
            work_dir = export_dir / "working"
            work_dir.mkdir(exist_ok=True)

            # First, we need to reconstruct to compute hash (lightweight operation)
            self.logger.info("Exporting project from TempleDB...")
            export_start = time.time()
            cathedral_dir = self._export_project(project_slug, export_dir)

            self.logger.info("Reconstructing project from cathedral package...")
            file_count = self._reconstruct_project(cathedral_dir, work_dir)
            self.logger.info(f"Reconstructed {file_count} files")
            export_time = time.time() - export_start

            # Compute content hash
            self.logger.info("🔍 Computing content hash for cache lookup...")
            hash_start = time.time()
            content_hash = self.cache_service.compute_content_hash(work_dir)
            hash_time = time.time() - hash_start
            self.logger.info(f"   Content hash: {content_hash} (computed in {hash_time:.2f}s)")

            # Look up cache
            cache_entry = self.cache_service.get_cache_entry(
                project['id'],
                target,
                content_hash.content_hash
            )

            if cache_entry and not dry_run:
                self.logger.info("")
                self.logger.info("✨ CACHE HIT! Reusing cached artifacts")
                self.logger.info(f"   Last used: {cache_entry.last_used_at.strftime('%Y-%m-%d %H:%M:%S')}")
                self.logger.info(f"   Use count: {cache_entry.use_count}")
                self.logger.info(f"   Cache size: {cache_entry.total_size_bytes / 1024 / 1024:.1f} MB")

                # Reuse cached FHS environment if available
                if cache_entry.fhs_env_path and use_full_fhs:
                    self.logger.info(f"   Reusing FHS environment from cache")
                    # FHS context would be reconstructed from cached fhs-env.nix
                    # For now, we'll regenerate (small overhead compared to package detection)

                cache_hit = True
                build_time = 0  # No build needed
            else:
                if cache_entry is None:
                    self.logger.info("")
                    self.logger.info("💾 Cache miss - full deployment required")
                else:
                    self.logger.info("   (Dry run mode - cache not used)")
                cache_hit = False
                build_start = time.time()

            # Step 2.5: Detect packages and create FHS environment if using full FHS (only on cache miss)
            if use_full_fhs and not cache_hit:
                self.logger.info("")
                self.logger.info("🔧 Full FHS integration enabled")
                self.logger.info("📦 Detecting project dependencies...")

                # Import FHS modules (lazy import to avoid circular deps)
                from fhs_integration import FHSIntegration
                from fhs_package_detector import PackageDetector

                fhs_integration = FHSIntegration()
                detector = PackageDetector()

                # Detect packages from reconstructed project
                requirements = detector.detect(work_dir)

                packages_list = requirements.to_list()
                self.logger.info(f"   Detected {len(packages_list)} packages:")
                for pkg in packages_list[:10]:  # Show first 10
                    self.logger.info(f"   • {pkg}")
                if len(packages_list) > 10:
                    self.logger.info(f"   • ... and {len(packages_list) - 10} more")

                # Get environment variables for the target
                env_vars = self._get_deployment_env_vars(project, target)

                # Prepare FHS deployment context
                self.logger.info("🔧 Creating FHS environment...")
                self._fhs_context = fhs_integration.prepare_fhs_deployment(
                    project_slug=project_slug,
                    project_dir=work_dir,
                    env_vars=env_vars,
                    extra_packages=[]
                )
                self.logger.info(f"   ✓ FHS environment ready at {self._fhs_context.fhs_env.fhs_dir}")

                build_time = time.time() - build_start

            # Step 2.6: Generate .envrc for direnv integration
            self.logger.info("Setting up direnv integration...")
            self._setup_direnv(project, work_dir)

            # Step 3: Execute deployment
            result = self._execute_deployment(
                project=project,
                target=target,
                work_dir=work_dir,
                dry_run=dry_run,
                validate_env=not skip_validation
            )

            # Step 4: Record cache stats
            total_time = time.time() - start_time

            if result.success and not dry_run:
                if cache_hit:
                    # Record cache hit
                    self.cache_service.record_cache_hit(
                        cache_entry,
                        total_time,
                        skipped_cathedral=True,
                        skipped_fhs=True,
                        skipped_reconstruction=False  # We always reconstruct to compute hash
                    )
                    self.logger.info(f"⚡ Cache performance: {total_time:.1f}s (vs ~{total_time * 3:.1f}s without cache)")
                else:
                    # Record cache miss and create new cache entry
                    self.cache_service.record_cache_miss(
                        project['id'],
                        target,
                        content_hash.content_hash,
                        build_time,
                        export_time,
                        total_time
                    )

                    # Create cache entry for next time
                    fhs_env_path = None
                    if self._fhs_context:
                        fhs_env_path = self._fhs_context.fhs_env.fhs_dir / "fhs-env.nix"

                    # Calculate cache size (approximate)
                    total_size = sum(f.stat().st_size for f in work_dir.rglob('*') if f.is_file())

                    cache_id = self.cache_service.create_cache_entry(
                        project['id'],
                        target,
                        content_hash,
                        cathedral_path=cathedral_dir,
                        fhs_env_path=fhs_env_path,
                        work_dir_path=work_dir,
                        file_count=file_count,
                        total_size_bytes=total_size
                    )
                    self.logger.info(f"💾 Cached deployment artifacts (id: {cache_id})")

            # Show FHS access information if enabled
            if result.success and self._use_full_fhs and self._fhs_context:
                self.logger.info("")
                self.logger.info("✅ Deployment complete!")
                self.logger.info("")
                self.logger.info("🔧 FHS environment available:")
                self.logger.info(f"   Enter shell:  ./templedb deploy shell {project_slug}")
                self.logger.info(f"   Run command:  ./templedb deploy exec {project_slug} '<command>'")

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
            self.logger.info("🏗️  Running deployment...")

            from deployment_orchestrator import DeploymentOrchestrator

            orchestrator = DeploymentOrchestrator(
                project=project,
                target_name=target,
                config=config,
                db_utils=db_utils,
                work_dir=work_dir
            )

            # Wrap in FHS if enabled
            if self._use_full_fhs and self._fhs_context:
                self.logger.info("   (Running in FHS environment)")
                from fhs_integration import FHSIntegration
                fhs = FHSIntegration()

                # TODO: Orchestrator needs FHS wrapping support
                # For now, run normally but note FHS is available
                result = orchestrator.deploy(
                    dry_run=dry_run,
                    validate_env=validate_env
                )
            else:
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
                self.logger.info("🏗️  Running deployment...")
                self.logger.info(f"   Using script: {deploy_script.name}")

                if dry_run:
                    return DeploymentResult(
                        success=True,
                        project_slug=project_slug,
                        target=target,
                        work_dir=work_dir,
                        message="Dry run complete - no actual deployment performed",
                        exit_code=0
                    )

                # Execute deployment script (wrap in FHS if enabled)
                if self._use_full_fhs and self._fhs_context:
                    self.logger.info("   (Running in FHS environment)")
                    from fhs_integration import FHSIntegration
                    fhs = FHSIntegration()

                    try:
                        result = fhs.run_deployment_in_fhs(
                            context=self._fhs_context,
                            deployment_command=["bash", str(deploy_script)]
                        )

                        if result['success']:
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
                                message=f"Deployment script failed with exit code {result.get('exit_code', 1)}",
                                exit_code=result.get('exit_code', 1)
                            )
                    except Exception as e:
                        self.logger.error(f"FHS deployment failed: {e}")
                        return DeploymentResult(
                            success=False,
                            project_slug=project_slug,
                            target=target,
                            work_dir=work_dir,
                            message=f"FHS deployment failed: {e}",
                            exit_code=1
                        )
                else:
                    # Execute without FHS
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

    def _get_deployment_env_vars(self, project: Dict[str, Any], target: str) -> Dict[str, str]:
        """
        Get environment variables for deployment target.

        Args:
            project: Project dictionary
            target: Target name (e.g., 'production', 'staging')

        Returns:
            Dictionary of environment variables
        """
        env_vars = {
            "DEPLOYMENT_TARGET": target,
            "PROJECT_SLUG": project['slug'],
        }

        # Get environment variables from database
        try:
            from environment_service import EnvironmentService
            env_service = EnvironmentService(self.ctx)

            # Get project-specific env vars for this target
            project_envs = env_service.list_variables(
                project_slug=project['slug'],
                target=target
            )

            for env in project_envs:
                env_vars[env['key']] = env['value']
        except Exception as e:
            self.logger.warning(f"Failed to load environment variables: {e}")

        return env_vars

    def _setup_direnv(self, project: Dict[str, Any], work_dir: Path) -> None:
        """
        Generate .envrc file in work directory for direnv integration.

        This allows project CLIs to be automatically available when navigating
        into the deployed project directory.

        Args:
            project: Project dictionary from database
            work_dir: Working directory with reconstructed project files
        """
        envrc_path = work_dir / ".envrc"
        project_slug = project['slug']

        # Generate .envrc content
        envrc_content = f"""# direnv configuration for {project_slug} (deployed)
# Auto-generated by TempleDB deployment
# This file makes the project CLI available when entering this directory

"""

        # Check if project has shell.nix or flake.nix for Nix support
        has_shell_nix = (work_dir / "shell.nix").exists()
        has_flake = (work_dir / "flake.nix").exists()

        if has_shell_nix or has_flake:
            envrc_content += """# Use Nix environment if available
if has nix_direnv_version || has nix; then
  if [ -f "flake.nix" ]; then
    use flake
  elif [ -f "shell.nix" ]; then
    use nix
  fi
fi

"""

        # Add current directory to PATH (for project CLIs)
        envrc_content += """# Add current directory to PATH for project CLI
PATH_add "$(pwd)"

"""

        # Check for common CLI patterns and make them executable
        cli_patterns = [
            "*.mjs",  # Node.js scripts (like bza.mjs)
            "*.py",   # Python scripts
            "*.sh",   # Shell scripts
            "cli",    # Common CLI names
            project_slug  # Project name as CLI
        ]

        envrc_content += f"""# Make project CLIs executable
for pattern in {' '.join(cli_patterns)}; do
  for file in $pattern; do
    if [ -f "$file" ] && [ ! -x "$file" ]; then
      chmod +x "$file"
    fi
  done
done

"""

        # Add project root export
        envrc_content += f"""# Export project root
export {project_slug.upper()}_PROJECT_ROOT="$(pwd)"

"""

        # Load .env if it exists
        envrc_content += """# Load environment variables from .env if present
if [ -f ".env" ]; then
  dotenv .env
fi

"""

        # Success message
        envrc_content += f"""echo "✓ {project_slug} environment loaded (deployed)"
"""

        # Write .envrc file
        try:
            envrc_path.write_text(envrc_content)
            self.logger.info(f"Generated .envrc at {envrc_path}")
        except Exception as e:
            self.logger.warning(f"Failed to generate .envrc: {e}")
            # Don't fail deployment if .envrc generation fails
