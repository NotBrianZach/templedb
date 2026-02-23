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
        self.env_vars = {}
        self.target_info = None

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

    def run_hook(self, hook_command: str, dry_run: bool = False) -> bool:
        """Run a pre/post deploy hook"""
        if dry_run:
            print(f"      [DRY RUN] Would run: {hook_command}")
            return True

        try:
            # Substitute environment variables
            for var_name, var_value in self.env_vars.items():
                hook_command = hook_command.replace(f"${var_name}", var_value)
                hook_command = hook_command.replace(f"${{{var_name}}}", var_value)

            result = subprocess.run(
                hook_command,
                shell=True,
                cwd=self.work_dir,
                env={**subprocess.os.environ, **self.env_vars},
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                print(f"      ✗ Hook failed: {hook_command}")
                if result.stderr:
                    print(f"        {result.stderr[:200]}")
                return False

            if result.stdout:
                # Show first line of output
                first_line = result.stdout.strip().split('\n')[0]
                print(f"      ✓ {first_line[:80]}")

            return True

        except subprocess.TimeoutExpired:
            print(f"      ✗ Hook timed out: {hook_command}")
            return False
        except Exception as e:
            print(f"      ✗ Hook error: {e}")
            return False

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

    def deploy_group(
        self,
        group: DeploymentGroup,
        dry_run: bool = False
    ) -> GroupResult:
        """Deploy a single deployment group"""
        print(f"\n🔧 [{group.order}] Deploying: {group.name}")

        start_time = time.time()

        # Run pre-deploy hooks
        if group.pre_deploy:
            print(f"   Running pre-deploy hooks...")
            for hook in group.pre_deploy:
                if not self.run_hook(hook, dry_run):
                    duration_ms = int((time.time() - start_time) * 1000)
                    return GroupResult(
                        group_name=group.name,
                        success=False,
                        duration_ms=duration_ms,
                        error_message=f"Pre-deploy hook failed: {hook}"
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
                skip_reason="No deployment logic for this group type yet"
            )

        # Run post-deploy hooks if successful
        if result.success and group.post_deploy:
            print(f"   Running post-deploy hooks...")
            for hook in group.post_deploy:
                if not self.run_hook(hook, dry_run):
                    result.success = False
                    result.error_message = f"Post-deploy hook failed: {hook}"
                    break

        if result.success and not result.skipped:
            print(f"   ✅ Completed in {result.duration_ms}ms")
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
        else:
            print(f"\n⚠️  Deployment completed with errors ({duration_ms / 1000:.1f}s total)")

        return DeploymentResult(
            success=all_success,
            duration_ms=duration_ms,
            group_results=group_results
        )
