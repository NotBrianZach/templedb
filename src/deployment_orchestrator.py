#!/usr/bin/env python3
"""
Deployment Orchestrator

Executes deployment groups in order with pre/post hooks, migration tracking,
and error handling.
"""
import subprocess
import time
import fnmatch
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field

from deployment_config import DeploymentConfig, DeploymentGroup
from migration_tracker import MigrationTracker, Migration
from deployment_instructions import DeploymentInstructionsGenerator
from deployment_tracker import DeploymentTracker


@dataclass
class GroupResult:
    """Result of deploying a single group"""
    group_name: str
    success: bool
    duration_ms: int
    files_deployed: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None
    # Distinguish deployment vs hook failures
    deployment_success: bool = True  # Core deployment (migrations/builds) succeeded
    pre_hook_success: bool = True    # Pre-deploy hooks succeeded
    post_hook_success: bool = True   # Post-deploy hooks succeeded
    post_hook_errors: List[str] = field(default_factory=list)  # Post-hook error details

    @property
    def has_warnings(self) -> bool:
        """Check if deployment succeeded with warnings (e.g., post-hook failures)"""
        return self.deployment_success and not self.post_hook_success

    @property
    def is_partial_success(self) -> bool:
        """Check if core deployment succeeded but hooks failed"""
        return self.deployment_success and (not self.pre_hook_success or not self.post_hook_success)


@dataclass
class DeploymentResult:
    """Overall deployment result"""
    success: bool
    duration_ms: int
    group_results: List[GroupResult] = field(default_factory=list)
    error_message: Optional[str] = None

    @property
    def failed_groups(self) -> List[GroupResult]:
        """Get list of failed groups"""
        return [r for r in self.group_results if not r.success and not r.skipped]

    @property
    def successful_groups(self) -> List[GroupResult]:
        """Get list of successful groups"""
        return [r for r in self.group_results if r.success]


class DeploymentOrchestrator:
    """Orchestrates multi-component deployments"""

    def __init__(
        self,
        project: Dict[str, Any],
        target_name: str,
        config: DeploymentConfig,
        db_utils,
        work_dir: Path
    ):
        """
        Initialize orchestrator

        Args:
            project: Project dict from database
            target_name: Deployment target (production, staging, etc.)
            config: Deployment configuration
            db_utils: Database utilities module
            work_dir: Working directory with reconstructed project files
        """
        self.project = project
        self.target_name = target_name
        self.config = config
        self.db_utils = db_utils
        self.work_dir = work_dir
        self.migration_tracker = MigrationTracker(db_utils)
        self.deployment_tracker = DeploymentTracker(db_utils)
        self.env_vars = {}
        self.target_info = None
        self.current_deployment_id = None

    def load_target_info(self) -> None:
        """Load deployment target information including connection strings"""
        import os
        import re

        # Get target info from database
        target_rows = self.db_utils.query_all("""
            SELECT target_name, target_type, provider, host, connection_string, access_url
            FROM deployment_targets
            WHERE project_id = ? AND target_name = ?
        """, (self.project['id'], self.target_name))

        if target_rows:
            self.target_info = dict(target_rows[0])

            # Process connection_string if present
            if self.target_info.get('connection_string'):
                conn_str = self.target_info['connection_string']

                # Resolve environment variable references like ${VAR_NAME}
                def resolve_env_var(match):
                    var_name = match.group(1)
                    return os.environ.get(var_name, match.group(0))

                conn_str = re.sub(r'\$\{([^}]+)\}', resolve_env_var, conn_str)
                conn_str = re.sub(r'\$([A-Z_][A-Z0-9_]*)', lambda m: os.environ.get(m.group(1), m.group(0)), conn_str)

                # Make DATABASE_URL available as env var
                self.env_vars['DATABASE_URL'] = conn_str

    def load_environment_variables(self) -> None:
        """Load environment variables for this project/target"""
        rows = self.db_utils.query_all("""
            SELECT var_name, var_value
            FROM environment_variables
            WHERE scope_type = 'project'
              AND scope_id = ?
        """, (self.project['id'],))

        for row in rows:
            var_name = row['var_name']
            var_value = row['var_value']

            # Parse target from var_name (target:varname format)
            if ':' in var_name:
                target, actual_name = var_name.split(':', 1)
                # Only load vars for this target or default
                if target == self.target_name or target == 'default':
                    self.env_vars[actual_name] = var_value
            else:
                self.env_vars[var_name] = var_value

    def validate_environment(self) -> List[str]:
        """Validate all required environment variables are set"""
        missing = []
        required_vars = self.config.get_all_required_env_vars()

        for var_name in required_vars:
            if var_name not in self.env_vars:
                missing.append(var_name)

        return missing

    def get_matching_files(self, file_patterns: List[str]) -> List[Path]:
        """Get files matching glob patterns"""
        matching_files = []

        for pattern in file_patterns:
            # Use glob to find matching files
            for file_path in self.work_dir.rglob('*'):
                if file_path.is_file():
                    rel_path = str(file_path.relative_to(self.work_dir))
                    if fnmatch.fnmatch(rel_path, pattern):
                        matching_files.append(file_path)

        return sorted(set(matching_files))

    def run_hook(
        self,
        hook_command: str,
        dry_run: bool = False,
        timeout: int = 30,
        retry_attempts: int = 1,
        retry_delay: int = 5
    ) -> bool:
        """
        Run a pre/post deploy hook with retry logic

        Args:
            hook_command: Shell command to execute
            dry_run: If True, just print what would be done
            timeout: Command timeout in seconds
            retry_attempts: Number of retry attempts (1 = no retries)
            retry_delay: Seconds to wait between retries
        """
        if dry_run:
            print(f"      [DRY RUN] Would run: {hook_command}")
            return True

        for attempt in range(retry_attempts):
            try:
                # Substitute environment variables
                cmd = hook_command
                for var_name, var_value in self.env_vars.items():
                    cmd = cmd.replace(f"${var_name}", var_value)
                    cmd = cmd.replace(f"${{{var_name}}}", var_value)

                result = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=self.work_dir,
                    env={**subprocess.os.environ, **self.env_vars},
                    capture_output=True,
                    text=True,
                    timeout=timeout
                )

                if result.returncode != 0:
                    if attempt < retry_attempts - 1:
                        print(f"      ⚠️  Hook failed (attempt {attempt+1}/{retry_attempts}), retrying in {retry_delay}s...")
                        if result.stderr:
                            print(f"        Error: {result.stderr[:200]}")
                        time.sleep(retry_delay)
                        continue
                    else:
                        print(f"      ✗ Hook failed after {retry_attempts} attempts: {hook_command}")
                        if result.stderr:
                            print(f"        {result.stderr[:200]}")
                        return False

                if result.stdout:
                    # Show first line of output
                    first_line = result.stdout.strip().split('\n')[0]
                    print(f"      ✓ {first_line[:80]}")
                else:
                    print(f"      ✓ Hook completed")

                return True  # Success, exit retry loop

            except subprocess.TimeoutExpired:
                if attempt < retry_attempts - 1:
                    print(f"      ⚠️  Hook timed out (attempt {attempt+1}/{retry_attempts}), retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"      ✗ Hook timed out after {retry_attempts} attempts: {hook_command}")
                    return False
            except Exception as e:
                if attempt < retry_attempts - 1:
                    print(f"      ⚠️  Hook error (attempt {attempt+1}/{retry_attempts}): {e}, retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                    continue
                else:
                    print(f"      ✗ Hook error after {retry_attempts} attempts: {e}")
                    return False

        return False  # Should not reach here

    def deploy_migration_group(
        self,
        group: DeploymentGroup,
        dry_run: bool = False
    ) -> GroupResult:
        """Deploy migration group with tracking"""
        start_time = time.time()

        # Get pending migrations
        pending = self.migration_tracker.get_pending_migrations(
            self.project['id'],
            self.target_name
        )

        if not pending:
            return GroupResult(
                group_name=group.name,
                success=True,
                duration_ms=0,
                skipped=True,
                skip_reason="No pending migrations"
            )

        print(f"   Found {len(pending)} pending migrations")

        deployed_files = []

        for migration in pending:
            migration_file = self.work_dir / migration.file_path

            if not migration_file.exists():
                print(f"      ✗ Migration file not found: {migration.file_path}")
                continue

            if dry_run:
                print(f"      [DRY RUN] Would apply: {migration.file_path}")
                deployed_files.append(migration.file_path)
                continue

            # Apply migration
            print(f"      Applying: {migration.file_path}")
            apply_start = time.time()

            try:
                # Substitute environment variables in command
                deploy_cmd = group.deploy_command
                for var_name, var_value in self.env_vars.items():
                    deploy_cmd = deploy_cmd.replace(f"${var_name}", var_value)
                    deploy_cmd = deploy_cmd.replace(f"${{{var_name}}}", var_value)

                # Substitute {file} placeholder
                deploy_cmd = deploy_cmd.replace("{file}", str(migration_file))

                result = subprocess.run(
                    deploy_cmd,
                    shell=True,
                    cwd=self.work_dir,
                    env={**subprocess.os.environ, **self.env_vars},
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 minute timeout for migrations
                )

                apply_duration = int((time.time() - apply_start) * 1000)

                if result.returncode == 0:
                    # Record success
                    self.migration_tracker.record_migration_success(
                        self.project['id'],
                        self.target_name,
                        migration.file_path,
                        migration.checksum,
                        apply_duration,
                        applied_by='templedb-deploy'
                    )
                    print(f"      ✓ Applied in {apply_duration}ms")
                    deployed_files.append(migration.file_path)
                else:
                    # Record failure
                    error_msg = result.stderr[:500] if result.stderr else "Unknown error"
                    self.migration_tracker.record_migration_failure(
                        self.project['id'],
                        self.target_name,
                        migration.file_path,
                        migration.checksum,
                        error_msg,
                        apply_duration,
                        applied_by='templedb-deploy'
                    )
                    print(f"      ✗ Failed: {error_msg[:100]}")

                    duration_ms = int((time.time() - start_time) * 1000)
                    return GroupResult(
                        group_name=group.name,
                        success=False,
                        duration_ms=duration_ms,
                        files_deployed=deployed_files,
                        error_message=f"Migration failed: {migration.file_path}"
                    )

            except subprocess.TimeoutExpired:
                print(f"      ✗ Migration timed out")
                self.migration_tracker.record_migration_failure(
                    self.project['id'],
                    self.target_name,
                    migration.file_path,
                    migration.checksum,
                    "Migration timed out after 5 minutes",
                    300000,
                    applied_by='templedb-deploy'
                )

                duration_ms = int((time.time() - start_time) * 1000)
                return GroupResult(
                    group_name=group.name,
                    success=False,
                    duration_ms=duration_ms,
                    files_deployed=deployed_files,
                    error_message=f"Migration timed out: {migration.file_path}"
                )

            except Exception as e:
                print(f"      ✗ Error: {e}")
                duration_ms = int((time.time() - start_time) * 1000)
                return GroupResult(
                    group_name=group.name,
                    success=False,
                    duration_ms=duration_ms,
                    files_deployed=deployed_files,
                    error_message=str(e)
                )

        duration_ms = int((time.time() - start_time) * 1000)
        return GroupResult(
            group_name=group.name,
            success=True,
            duration_ms=duration_ms,
            files_deployed=deployed_files
        )

    def deploy_build_group(
        self,
        group: DeploymentGroup,
        dry_run: bool = False
    ) -> GroupResult:
        """Deploy build group (npm build, etc.)"""
        start_time = time.time()

        if dry_run:
            print(f"   [DRY RUN] Would run build: {group.build_command}")
            return GroupResult(
                group_name=group.name,
                success=True,
                duration_ms=0,
                skipped=True,
                skip_reason="Dry run"
            )

        try:
            # Run test command first if present
            if group.test_command:
                print(f"   Running tests: {group.test_command}")
                result = subprocess.run(
                    group.test_command,
                    shell=True,
                    cwd=self.work_dir,
                    env={**subprocess.os.environ, **self.env_vars},
                    capture_output=True,
                    text=True,
                    timeout=300
                )

                if result.returncode != 0:
                    print(f"   ✗ Tests failed")
                    if result.stderr:
                        print(f"     {result.stderr[:200]}")
                    duration_ms = int((time.time() - start_time) * 1000)
                    return GroupResult(
                        group_name=group.name,
                        success=False,
                        duration_ms=duration_ms,
                        error_message="Tests failed"
                    )

                print(f"   ✓ Tests passed")

            # Run build command
            if group.build_command:
                print(f"   Running build: {group.build_command}")
                result = subprocess.run(
                    group.build_command,
                    shell=True,
                    cwd=self.work_dir,
                    env={**subprocess.os.environ, **self.env_vars},
                    capture_output=True,
                    text=True,
                    timeout=600  # 10 minute timeout for builds
                )

                if result.returncode != 0:
                    print(f"   ✗ Build failed")
                    if result.stderr:
                        print(f"     {result.stderr[:200]}")
                    duration_ms = int((time.time() - start_time) * 1000)
                    return GroupResult(
                        group_name=group.name,
                        success=False,
                        duration_ms=duration_ms,
                        error_message="Build failed"
                    )

                print(f"   ✓ Build succeeded")

            duration_ms = int((time.time() - start_time) * 1000)
            return GroupResult(
                group_name=group.name,
                success=True,
                duration_ms=duration_ms
            )

        except subprocess.TimeoutExpired:
            print(f"   ✗ Build timed out")
            duration_ms = int((time.time() - start_time) * 1000)
            return GroupResult(
                group_name=group.name,
                success=False,
                duration_ms=duration_ms,
                error_message="Build timed out"
            )
        except Exception as e:
            print(f"   ✗ Build error: {e}")
            duration_ms = int((time.time() - start_time) * 1000)
            return GroupResult(
                group_name=group.name,
                success=False,
                duration_ms=duration_ms,
                error_message=str(e)
            )

    def _generate_deploy_instructions(self) -> None:
        """Generate DEPLOY_INSTRUCTIONS.md after successful deployment"""
        try:
            generator = DeploymentInstructionsGenerator(
                work_dir=self.work_dir,
                project=self.project,
                target_name=self.target_name
            )

            # Validate before writing
            validation = generator.validate()

            # Write with validation report
            output_path = generator.write_to_file(validate=True)
            print(f"📝 Generated deployment instructions: {output_path}")

            # Show validation summary
            if validation.errors:
                print(f"   ⚠️  {len(validation.errors)} validation error(s) found")
            if validation.warnings:
                print(f"   ⚠️  {len(validation.warnings)} validation warning(s) found")
            if validation.valid:
                print(f"   ✓ Validation passed")

        except Exception as e:
            # Don't fail deployment if instruction generation fails
            print(f"⚠️  Could not generate deployment instructions: {e}")

    def deploy_group(
        self,
        group: DeploymentGroup,
        dry_run: bool = False
    ) -> GroupResult:
        """Deploy a single deployment group"""
        print(f"\n🔧 [{group.order}] Deploying: {group.name}")

        start_time = time.time()

        # Run pre-deploy hooks with retry logic
        pre_hook_success = True
        if group.pre_deploy:
            print(f"   Running pre-deploy hooks...")
            for hook in group.pre_deploy:
                if not self.run_hook(
                    hook,
                    dry_run,
                    timeout=group.hook_timeout,
                    retry_attempts=group.retry_attempts,
                    retry_delay=group.retry_delay
                ):
                    pre_hook_success = False
                    duration_ms = int((time.time() - start_time) * 1000)
                    return GroupResult(
                        group_name=group.name,
                        success=False,
                        duration_ms=duration_ms,
                        error_message=f"Pre-deploy hook failed: {hook}",
                        deployment_success=False,
                        pre_hook_success=False,
                        post_hook_success=True
                    )

        # Handle migration groups specially
        if group.name.lower() in ['migrations', 'database_migrations', 'migration']:
            result = self.deploy_migration_group(group, dry_run)
        elif group.build_command:
            result = self.deploy_build_group(group, dry_run)
        else:
            # Generic file deployment
            result = GroupResult(
                group_name=group.name,
                success=True,
                duration_ms=0,
                skipped=True,
                skip_reason="No deployment logic for this group type yet",
                deployment_success=True,
                pre_hook_success=pre_hook_success,
                post_hook_success=True
            )

        # Run post-deploy hooks if deployment succeeded
        # Post-hook failures don't fail the deployment, just create warnings
        post_hook_success = True
        post_hook_errors = []
        if result.deployment_success and group.post_deploy:
            print(f"   Running post-deploy hooks...")
            for hook in group.post_deploy:
                if not self.run_hook(
                    hook,
                    dry_run,
                    timeout=group.hook_timeout,
                    retry_attempts=group.retry_attempts,
                    retry_delay=group.retry_delay
                ):
                    post_hook_success = False
                    post_hook_errors.append(f"Post-deploy hook failed: {hook}")
                    print(f"      ⚠️  Warning: Post-deploy hook failed but deployment continues")

        # Update result with post-hook status
        result.post_hook_success = post_hook_success
        result.post_hook_errors = post_hook_errors

        # Overall success requires both deployment and post-hooks to succeed
        # But we distinguish between deployment success and hook success
        if not post_hook_success:
            result.success = False
            result.error_message = "; ".join(post_hook_errors) if post_hook_errors else "Post-deploy hooks failed"

        if result.success and not result.skipped:
            print(f"   ✅ Completed in {result.duration_ms}ms")
        elif result.has_warnings:
            print(f"   ⚠️  Deployed with warnings in {result.duration_ms}ms")
            print(f"       Deployment succeeded but post-hooks failed")
        elif result.skipped:
            print(f"   ⏭️  Skipped: {result.skip_reason}")

        return result

    def deploy(
        self,
        dry_run: bool = False,
        validate_env: bool = True,
        skip_groups: Optional[List[str]] = None
    ) -> DeploymentResult:
        """Execute full deployment"""
        start_time = time.time()

        print(f"\n🚀 Deploying {self.project['slug']} to {self.target_name}")
        if dry_run:
            print("📋 DRY RUN - No actual changes will be made\n")

        # Start deployment tracking (not in dry run)
        if not dry_run:
            # Get latest commit for tracking
            from repositories import VCSRepository
            vcs_repo = VCSRepository()
            latest_commit = vcs_repo.query_one("""
                SELECT commit_hash FROM vcs_commits
                WHERE project_id = ? ORDER BY id DESC LIMIT 1
            """, (self.project['id'],))

            commit_hash = latest_commit['commit_hash'] if latest_commit else None

            self.current_deployment_id = self.deployment_tracker.start_deployment(
                project_id=self.project['id'],
                target_name=self.target_name,
                deployment_type='deploy',
                commit_hash=commit_hash
            )

        # Load target info (connection strings, etc.)
        self.load_target_info()

        # Load environment variables
        self.load_environment_variables()

        # Validate environment if requested
        if validate_env:
            missing_vars = self.validate_environment()
            if missing_vars:
                error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
                print(f"\n✗ {error_msg}")
                print(f"\n💡 Set them with: ./templedb env set {self.project['slug']} VAR_NAME value --target {self.target_name}")
                return DeploymentResult(
                    success=False,
                    duration_ms=0,
                    error_message=error_msg
                )

        # Deploy groups in order
        group_results = []
        sorted_groups = sorted(self.config.groups, key=lambda g: g.order)

        for group in sorted_groups:
            # Skip if requested
            if skip_groups and group.name in skip_groups:
                print(f"\n⏭️  Skipping: {group.name} (user requested)")
                continue

            result = self.deploy_group(group, dry_run)
            group_results.append(result)

            # Stop on failure unless continue_on_failure is set
            if not result.success and not result.skipped and not group.continue_on_failure:
                print(f"\n✗ Deployment failed at group: {group.name}")
                print(f"   Error: {result.error_message}")
                duration_ms = int((time.time() - start_time) * 1000)
                return DeploymentResult(
                    success=False,
                    duration_ms=duration_ms,
                    group_results=group_results,
                    error_message=f"Failed at group: {group.name}"
                )

        duration_ms = int((time.time() - start_time) * 1000)

        # Check if all succeeded
        all_success = all(r.success or r.skipped for r in group_results)

        if all_success:
            print(f"\n✅ Deployment complete! ({duration_ms / 1000:.1f}s total)")

            # Generate deployment instructions after successful deployment
            if not dry_run:
                self._generate_deploy_instructions()
        else:
            print(f"\n⚠️  Deployment completed with errors ({duration_ms / 1000:.1f}s total)")

        # Complete deployment tracking (not in dry run)
        if not dry_run and self.current_deployment_id:
            # Collect deployed groups and files
            groups_deployed = [r.group_name for r in group_results if r.success and not r.skipped]
            files_deployed = []
            for r in group_results:
                if r.files_deployed:
                    files_deployed.extend(r.files_deployed)

            # Create deployment snapshot
            deployment_snapshot = {
                'groups': [r.__dict__ for r in group_results],
                'environment_vars': list(self.env_vars.keys()),
                'target_info': {
                    'name': self.target_name,
                    'groups_count': len(self.config.groups)
                }
            }

            # Get error message if failed
            error_message = None
            if not all_success:
                failed_groups = [r for r in group_results if not r.success and not r.skipped]
                if failed_groups:
                    error_message = failed_groups[0].error_message

            # Complete deployment record
            self.deployment_tracker.complete_deployment(
                deployment_id=self.current_deployment_id,
                success=all_success,
                duration_ms=duration_ms,
                groups_deployed=groups_deployed,
                files_deployed=files_deployed,
                error_message=error_message,
                deployment_snapshot=deployment_snapshot
            )

        return DeploymentResult(
            success=all_success,
            duration_ms=duration_ms,
            group_results=group_results
        )

    def rollback(
        self,
        to_commit_hash: str,
        dry_run: bool = False,
        validate_env: bool = True
    ) -> DeploymentResult:
        """
        Rollback deployment to a specific commit

        Args:
            to_commit_hash: Commit hash to rollback to
            dry_run: If True, show what would be done
            validate_env: If True, validate environment variables

        Returns:
            DeploymentResult with rollback status
        """
        start_time = time.time()

        print(f"\n⏪ Rolling back {self.project['slug']} to commit {to_commit_hash[:8]}...")
        if dry_run:
            print("📋 DRY RUN - No actual changes will be made\n")

        # Start rollback deployment tracking
        if not dry_run:
            self.current_deployment_id = self.deployment_tracker.start_deployment(
                project_id=self.project['id'],
                target_name=self.target_name,
                deployment_type='rollback',
                commit_hash=to_commit_hash
            )

        # Export the specific commit from database
        print("📦 Exporting target commit from TempleDB...")

        from cathedral_export import CathedralExporter
        from repositories import VCSRepository

        # Verify commit exists
        vcs_repo = VCSRepository()
        commit = vcs_repo.query_one("""
            SELECT * FROM vcs_commits
            WHERE project_id = ? AND commit_hash = ?
        """, (self.project['id'], to_commit_hash))

        if not commit:
            error_msg = f"Commit {to_commit_hash} not found in database"
            print(f"✗ {error_msg}")

            if not dry_run and self.current_deployment_id:
                self.deployment_tracker.complete_deployment(
                    deployment_id=self.current_deployment_id,
                    success=False,
                    duration_ms=int((time.time() - start_time) * 1000),
                    error_message=error_msg
                )

            return DeploymentResult(
                success=False,
                duration_ms=int((time.time() - start_time) * 1000),
                error_message=error_msg
            )

        # Export cathedral package at specific commit
        export_dir = Path(f"/tmp/templedb_rollback_{self.project['slug']}")
        export_dir.mkdir(parents=True, exist_ok=True)

        exporter = CathedralExporter()
        # Note: This would need enhancement to export at specific commit
        # For now, exporting current state
        print(f"⚠️  Full commit-based rollback not yet implemented")
        print(f"   Exporting current database state instead...")

        # TODO: Implement commit-specific export in CathedralExporter
        # This requires filtering files/content based on commit state

        from cathedral_export import export_project
        success = export_project(
            slug=self.project['slug'],
            output_dir=export_dir,
            compress=False,
            include_files=True,
            include_vcs=False,
            include_environments=True
        )

        if not success:
            error_msg = "Failed to export project for rollback"
            print(f"✗ {error_msg}")

            if not dry_run and self.current_deployment_id:
                self.deployment_tracker.complete_deployment(
                    deployment_id=self.current_deployment_id,
                    success=False,
                    duration_ms=int((time.time() - start_time) * 1000),
                    error_message=error_msg
                )

            return DeploymentResult(
                success=False,
                duration_ms=int((time.time() - start_time) * 1000),
                error_message=error_msg
            )

        cathedral_dir = export_dir / f"{self.project['slug']}.cathedral"
        print(f"✓ Exported to {cathedral_dir}\n")

        # Reconstruct to working directory
        work_dir = export_dir / "working"
        work_dir.mkdir(exist_ok=True)

        print("🔧 Reconstructing project...")
        self._reconstruct_project(cathedral_dir, work_dir)
        print(f"✓ Reconstructed to {work_dir}\n")

        # Update work_dir for deployment
        original_work_dir = self.work_dir
        self.work_dir = work_dir

        # Load environment and validate
        self.load_environment_variables()

        if validate_env:
            missing_vars = self.validate_environment()
            if missing_vars:
                error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
                print(f"\n✗ {error_msg}")

                if not dry_run and self.current_deployment_id:
                    self.deployment_tracker.complete_deployment(
                        deployment_id=self.current_deployment_id,
                        success=False,
                        duration_ms=int((time.time() - start_time) * 1000),
                        error_message=error_msg
                    )

                return DeploymentResult(
                    success=False,
                    duration_ms=int((time.time() - start_time) * 1000),
                    error_message=error_msg
                )

        # Deploy using normal deployment flow
        print("🚀 Deploying rollback version...\n")

        group_results = []
        sorted_groups = sorted(self.config.groups, key=lambda g: g.order)

        for group in sorted_groups:
            result = self.deploy_group(group, dry_run)
            group_results.append(result)

            if not result.success and not result.skipped and not group.continue_on_failure:
                print(f"\n✗ Rollback failed at group: {group.name}")
                print(f"   Error: {result.error_message}")

                duration_ms = int((time.time() - start_time) * 1000)

                if not dry_run and self.current_deployment_id:
                    self.deployment_tracker.complete_deployment(
                        deployment_id=self.current_deployment_id,
                        success=False,
                        duration_ms=duration_ms,
                        group_results=[r.__dict__ for r in group_results],
                        error_message=f"Failed at group: {group.name}"
                    )

                return DeploymentResult(
                    success=False,
                    duration_ms=duration_ms,
                    group_results=group_results,
                    error_message=f"Failed at group: {group.name}"
                )

        duration_ms = int((time.time() - start_time) * 1000)
        all_success = all(r.success or r.skipped for r in group_results)

        if all_success:
            print(f"\n✅ Rollback complete! ({duration_ms / 1000:.1f}s total)")
        else:
            print(f"\n⚠️  Rollback completed with errors ({duration_ms / 1000:.1f}s total)")

        # Complete rollback deployment tracking
        if not dry_run and self.current_deployment_id:
            groups_deployed = [r.group_name for r in group_results if r.success and not r.skipped]
            files_deployed = []
            for r in group_results:
                if r.files_deployed:
                    files_deployed.extend(r.files_deployed)

            deployment_snapshot = {
                'rollback_to_commit': to_commit_hash,
                'groups': [r.__dict__ for r in group_results]
            }

            error_message = None
            if not all_success:
                failed_groups = [r for r in group_results if not r.success and not r.skipped]
                if failed_groups:
                    error_message = failed_groups[0].error_message

            self.deployment_tracker.complete_deployment(
                deployment_id=self.current_deployment_id,
                success=all_success,
                duration_ms=duration_ms,
                groups_deployed=groups_deployed,
                files_deployed=files_deployed,
                error_message=error_message,
                deployment_snapshot=deployment_snapshot
            )

        # Restore original work_dir
        self.work_dir = original_work_dir

        return DeploymentResult(
            success=all_success,
            duration_ms=duration_ms,
            group_results=group_results
        )

    def _reconstruct_project(self, cathedral_dir: Path, work_dir: Path) -> None:
        """Reconstruct project structure from cathedral package"""
        import json

        files_dir = cathedral_dir / "files"

        if not files_dir.exists():
            raise ValueError(f"Files directory not found: {files_dir}")

        # Process all file JSON metadata
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
            import shutil
            shutil.copy2(blob_file, target_file)

            file_count += 1

        print(f"   Reconstructed {file_count} files")
