#!/usr/bin/env python3
"""
Deployment management commands for TempleDB
"""
import os
import sys
import subprocess
import shutil
import re
from pathlib import Path
from typing import Optional
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from deployment_config import DeploymentConfigManager
from deployment_orchestrator import DeploymentOrchestrator
from logger import get_logger
import db_utils

logger = get_logger(__name__)


from cli.commands.deploy_ops import DeployOpsMixin


class DeployCommands(DeployOpsMixin, Command):
    """Deployment command handlers"""

    def __init__(self):
        super().__init__()
        """Initialize with service context"""
        from services.context import ServiceContext
        self.ctx = ServiceContext()
        self.service = self.ctx.get_deployment_service()

    def _get_available_targets(self, project_slug: str) -> list:
        """Get list of available deployment targets for a project"""
        from services.context import ServiceContext
        ctx = ServiceContext()

        project = ctx.project_repo.get_by_slug(project_slug)
        if not project:
            return []

        # Query environment variables to find target prefixes
        rows = ctx.base_repo.query_all("""
            SELECT DISTINCT
                CASE
                    WHEN var_name LIKE '%:%'
                    THEN substr(var_name, 1, instr(var_name, ':') - 1)
                    ELSE NULL
                END as target
            FROM environment_variables
            WHERE scope_type = 'project' AND scope_id = ?
              AND var_name LIKE '%:%'
        """, (project['id'],))

        targets = [row['target'] for row in rows if row['target']]
        return sorted(set(targets))  # Return unique sorted list

    def deploy(self, args) -> int:
        """Deploy project from TempleDB"""
        from error_handler import ResourceNotFoundError, DeploymentError
        import os

        # Handle --examples flag
        if hasattr(args, 'examples') and args.examples:
            from cli.help_utils import CommandHelp, CommandExamples
            CommandHelp.show_examples('deploy run', CommandExamples.DEPLOY_RUN)
            return 0

        # Check if slug was provided
        if not args.slug:
            print("❌ Error: Project slug is required", file=sys.stderr)
            print("\nUsage: ./templedb deploy run <project> [options]", file=sys.stderr)
            print("       ./templedb deploy run --examples  # Show examples", file=sys.stderr)
            return 1

        try:
            project_slug = args.slug

            # Multi-target deploy
            all_targets = getattr(args, 'all_targets', False)
            targets_csv = getattr(args, 'targets', None)
            if all_targets or targets_csv:
                from services.deployment_pipeline import DeploymentPipelineService
                pipeline = DeploymentPipelineService()
                target_list = targets_csv.split(',') if targets_csv else None
                dry_run = getattr(args, 'dry_run', False)
                results = pipeline.deploy_multi(project_slug, targets=target_list, dry_run=dry_run)
                success_count = sum(1 for r in results if r['success'])
                fail_count = len(results) - success_count
                print(f"\nMulti-target deploy: {success_count} succeeded, {fail_count} failed")
                for r in results:
                    status = "OK" if r['success'] else "FAILED"
                    print(f"  {r['target']}: {status} — {r.get('message', '')}")
                return 0 if fail_count == 0 else 1

            # Check if target was explicitly provided
            target_provided = hasattr(args, 'target') and args.target

            if not target_provided:
                # Get available targets
                available_targets = self._get_available_targets(project_slug)

                if len(available_targets) > 1:
                    # Multiple targets available - show list and exit
                    print(f"📋 Available deployment targets for {project_slug}:\n")
                    for i, t in enumerate(available_targets, 1):
                        print(f"  {i}. {t}")
                    print(f"\n💡 Please specify a target:")
                    print(f"   ./templedb deploy run {project_slug} --target <target>\n")
                    print(f"Example:")
                    print(f"   ./templedb deploy run {project_slug} --target {available_targets[0]}")
                    return 0
                elif len(available_targets) == 1:
                    # Only one target - use it automatically
                    target = available_targets[0]
                    print(f"ℹ️  Auto-selected target: {target} (only available target)\n")
                else:
                    # No targets configured - default to production
                    target = 'production'
                    print(f"⚠️  No deployment targets configured - using default: production\n")
            else:
                target = args.target

            dry_run = args.dry_run if hasattr(args, 'dry_run') and args.dry_run else False
            skip_validation = hasattr(args, 'skip_validation') and args.skip_validation
            mutable = hasattr(args, 'mutable') and args.mutable
            no_fhs = hasattr(args, 'no_fhs') and args.no_fhs
            no_script = hasattr(args, 'no_script') and args.no_script

            # Check for registered deployment script (skip if --no-script flag)
            deploy_script = None
            if not no_script:
                deploy_script = db_utils.query_one(
                    "SELECT * FROM deployment_scripts WHERE project_slug = ? AND enabled = 1",
                    (project_slug,)
                )

            if deploy_script:
                script_path = deploy_script['script_path']

                # Verify script exists
                if not os.path.exists(script_path):
                    print(f"⚠️  Warning: Registered deployment script not found: {script_path}")
                    print(f"   Falling back to standard deployment...")
                else:
                    # Use custom deployment script
                    print(f"📜 Using deployment script: {os.path.basename(script_path)}")
                    if deploy_script['description']:
                        print(f"   {deploy_script['description']}")
                    print()

                    # Build command arguments
                    cmd = [script_path]
                    if dry_run:
                        cmd.append('--dry-run')
                    # Pass target to deployment script
                    cmd.extend(['--target', target])
                    # Pass --only if specified
                    only = getattr(args, 'only', None)
                    if only:
                        cmd.extend(['--only', only])

                    # Wrap in nix develop if project has flake.nix
                    script_dir = os.path.dirname(script_path)
                    flake_path = os.path.join(script_dir, 'flake.nix')
                    if os.path.exists(flake_path) and shutil.which('nix'):
                        cmd = ['nix', 'develop', script_dir, '--command'] + cmd

                    # Run the deployment script and track it
                    import time
                    deploy_start_time = time.time()

                    try:
                        result = subprocess.run(cmd, check=False)
                        deploy_duration = time.time() - deploy_start_time

                        # Record deployment (if not dry run)
                        if not dry_run:
                            try:
                                from services.deployment_tracking_service import DeploymentTrackingService
                                tracking_service = DeploymentTrackingService()

                                # Get project ID
                                project = self.ctx.project_repo.get_by_slug(project_slug)
                                if project:
                                    deployment_id = tracking_service.start_deployment(
                                        project_id=project['id'],
                                        target=target
                                    )

                                    tracking_service.complete_deployment(
                                        deployment_id=deployment_id,
                                        success=(result.returncode == 0),
                                        exit_code=result.returncode,
                                        duration_seconds=deploy_duration,
                                        notes=None if result.returncode == 0 else "Deployment script failed"
                                    )
                            except Exception as e:
                                # Don't fail deployment if tracking fails
                                logger.warning(f"Failed to record deployment: {e}")

                        return result.returncode
                    except Exception as e:
                        print(f"❌ Deployment script execution failed: {e}")
                        print(f"   Falling back to standard deployment...")
                        # Continue with standard deployment on error

            # Show warnings for non-default modes
            if mutable:
                print("⚠️  MUTABLE MODE: Files can be edited directly")
                print("   Note: Deployment will not be isolated or reproducible")
                print()

            if no_fhs:
                print("⚠️  WARNING: FHS isolation disabled (--no-fhs)")
                print("   This uses system packages and may not be reproducible")
                print("   Remove --no-fhs to use FHS (recommended)")
                print()

            print(f"🚀 Deploying {project_slug} to {target}...")

            if dry_run:
                print("📋 DRY RUN - No actual deployment will occur\n")

            # Use service for deployment
            import time
            deploy_start_time = time.time()

            deploy_commit = getattr(args, 'commit', None)
            deploy_branch = getattr(args, 'deploy_branch', None)

            result = self.service.deploy(
                project_slug=project_slug,
                target=target,
                dry_run=dry_run,
                skip_validation=skip_validation,
                mutable=mutable or no_fhs,  # Both disable FHS
                use_full_fhs=not no_fhs if not mutable else False,
                commit_hash=deploy_commit,
                branch_name=deploy_branch,
            )

            deploy_duration = time.time() - deploy_start_time

            # Record deployment (if not dry run)
            if not dry_run:
                try:
                    from services.deployment_tracking_service import DeploymentTrackingService
                    tracking_service = DeploymentTrackingService()

                    # Get project ID
                    project = self.ctx.project_repo.get_by_slug(project_slug)
                    if project:
                        deployment_id = tracking_service.start_deployment(
                            project_id=project['id'],
                            target=target,
                            work_dir=result.work_dir
                        )

                        tracking_service.complete_deployment(
                            deployment_id=deployment_id,
                            success=result.success,
                            exit_code=result.exit_code,
                            duration_seconds=deploy_duration,
                            notes=result.message if not result.success else None
                        )
                except Exception as e:
                    # Don't fail deployment if tracking fails
                    logger.warning(f"Failed to record deployment: {e}")

            # Present results
            if result.success:
                if result.message and 'No deployment configuration' in result.message:
                    # No deployment method configured
                    print("⚠️  No deployment configuration or deploy.sh found")
                    print("\n📝 To enable automated deployment:")
                    print(f"   Option 1 - Use deployment config (recommended):")
                    print(f"      ./templedb deploy init {project_slug}")
                    print(f"   Option 2 - Use deploy.sh script:")
                    print(f"      1. Create a deploy.sh script in {project_slug}")
                    print(f"      2. Re-import: ./templedb project sync {project_slug}")

                    if not dry_run:
                        print(f"\n💡 Deployment files available at: {result.work_dir}")
                        print("   You can manually deploy from this location")
                else:
                    print(f"\n✅ Deployment complete!")
                    if dry_run:
                        print("✓ Dry run complete - no actual deployment performed")

                    # Show FHS info if available
                    from config import DEPLOYMENT_USE_FHS, DEPLOYMENT_FHS_DIR
                    if DEPLOYMENT_USE_FHS:
                        fhs_nix = DEPLOYMENT_FHS_DIR / project_slug / "fhs-env.nix"
                        if fhs_nix.exists():
                            print(f"\n🔧 FHS environment available")
                            print(f"   Enter shell:  ./templedb deploy shell {project_slug}")
                            print(f"   Run command:  ./templedb deploy exec {project_slug} '<command>'")
                        else:
                            print(f"\n📁 Deployed to: {result.work_dir}")
                            print(f"   💡 Deploy with --use-fhs for FHS environment")
                    else:
                        print(f"\n📁 Deployed to: {result.work_dir}")

                    # Show related commands
                    if not dry_run:
                        from cli.help_utils import CommandHelp, RelatedCommands
                        related = [(cmd.replace('<project>', project_slug), desc)
                                   for cmd, desc in RelatedCommands.AFTER_DEPLOY_RUN]
                        CommandHelp.show_related_commands(related)

                return 0
            else:
                logger.error(f"Deployment failed: {result.message}")
                return result.exit_code

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except DeploymentError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except Exception as e:
            logger.error(f"Deployment failed: {e}")
            logger.debug("Full error details:", exc_info=True)
            return 1

    def status(self, args) -> int:
        """Show deployment status for project"""
        from error_handler import ResourceNotFoundError

        try:
            project_slug = args.slug

            print(f"\n📊 Deployment Status: {project_slug}\n")

            # Get status from service
            status = self.service.get_deployment_status(project_slug)

            # Display targets
            if status['targets']:
                print("🎯 Deployment Targets:")
                for target in status['targets']:
                    print(f"   • {target['target_name']} ({target['target_type']})")
                    print(f"     Provider: {target['provider'] or 'unknown'}")
                    if target['host']:
                        print(f"     Host: {target['host']}")
                print()
            else:
                print("⚠️  No deployment targets configured")
                print("   Use: ./templedb deploy targets add <project> <target_name> ...\n")

            # Display deployment scripts
            if status['deploy_scripts']:
                print("📜 Deployment Scripts:")
                for file_path in status['deploy_scripts']:
                    print(f"   • {file_path}")
                print()
            else:
                print("⚠️  No deployment scripts found\n")

            # Display migration count
            print(f"🗄️  Database Migrations: {status['migration_count']}")

            # Additional file counts (kept in command for now)
            result = self.query_one("""
                SELECT COUNT(*) as count
                FROM files_with_types_view
                WHERE project_slug = ? AND file_path LIKE '%/functions/%index.ts'
            """, (project_slug,))

            function_count = result['count'] if result else 0
            print(f"⚡ Edge Functions: {function_count}")

            result = self.query_one("""
                SELECT COUNT(*) as count
                FROM files_with_types_view
                WHERE project_slug = ? AND file_path LIKE '%.service'
            """, (project_slug,))

            service_count = result['count'] if result else 0
            print(f"🔧 Services: {service_count}")

            print()
            return 0

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except Exception as e:
            print(f"✗ Failed to get deployment status: {e}", file=sys.stderr)
            return 1

    def init(self, args) -> int:
        """Initialize deployment configuration for a project"""
        try:
            from deployment_config import create_default_config

            project_slug = args.slug
            project = self.get_project_or_exit(project_slug)

            print(f"\n🏗️  Initializing deployment configuration for {project_slug}...\n")

            # Check if config already exists
            config_manager = DeploymentConfigManager(db_utils)
            existing_config = config_manager.get_config(project['id'])

            if existing_config.groups:
                print(f"⚠️  Deployment configuration already exists")
                print(f"\n💡 To view: ./templedb deploy config {project_slug} --show")
                print(f"💡 To edit: Edit in database or create new config\n")
                return 0

            # Create default config
            default_config = create_default_config()

            # Customize based on project
            print("📋 Creating default deployment configuration...")
            print("\n   Default groups:")
            for group in default_config.groups:
                print(f"      {group.order}. {group.name}")

            # Save config
            config_manager.set_config(project['id'], default_config)

            print(f"\n✅ Deployment configuration initialized!")
            print(f"\n📝 Next steps:")
            print(f"   1. Review config: ./templedb deploy config {project_slug} --show")
            print(f"   2. Set environment variables: ./templedb env set {project_slug} VAR_NAME value")
            print(f"   3. Deploy: ./templedb deploy run {project_slug} --target production --dry-run")

            return 0

        except Exception as e:
            print(f"✗ Failed to initialize deployment config: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    def config_command(self, args) -> int:
        """Manage deployment configuration"""
        try:
            project_slug = args.slug
            project = self.get_project_or_exit(project_slug)

            config_manager = DeploymentConfigManager(db_utils)
            config = config_manager.get_config(project['id'])

            if hasattr(args, 'show') and args.show:
                # Show configuration
                if not config.groups:
                    print(f"\n⚠️  No deployment configuration found for {project_slug}")
                    print(f"\n💡 Initialize with: ./templedb deploy init {project_slug}\n")
                    return 0

                print(f"\n📋 Deployment Configuration: {project_slug}\n")
                print(config.to_json())
                print()

                return 0

            elif hasattr(args, 'validate') and args.validate:
                # Validate configuration
                if not config.groups:
                    print(f"✗ No deployment configuration found", file=sys.stderr)
                    return 1

                errors = config.validate()
                if errors:
                    print(f"✗ Configuration validation failed:\n")
                    for error in errors:
                        print(f"   • {error}")
                    return 1
                else:
                    print(f"✅ Configuration is valid")
                    return 0

            else:
                print(f"Usage: ./templedb deploy config <project> [--show | --validate]")
                return 1

        except Exception as e:
            print(f"✗ Failed to manage deployment config: {e}", file=sys.stderr)
            return 1

    def target(self, args) -> int:
        """Manage deployment targets"""
        try:
            project_slug = args.slug
            project = self.get_project_or_exit(project_slug)

            if hasattr(args, 'set_connection') and args.set_connection:
                # Set connection string for a target
                target_name = args.target
                connection_string = args.connection_string

                # Check if target exists
                existing = self.query_one("""
                    SELECT id FROM deployment_targets
                    WHERE project_id = ? AND target_name = ?
                """, (project['id'], target_name))

                if not existing:
                    print(f"✗ Target '{target_name}' not found for project {project_slug}", file=sys.stderr)
                    print(f"\n💡 Available targets:")
                    targets = self.query_all("""
                        SELECT target_name FROM deployment_targets
                        WHERE project_id = ?
                    """, (project['id'],))
                    for t in targets:
                        print(f"   • {t['target_name']}")
                    return 1

                # Update connection string
                self.execute("""
                    UPDATE deployment_targets
                    SET connection_string = ?, updated_at = datetime('now')
                    WHERE project_id = ? AND target_name = ?
                """, (connection_string, project['id'], target_name))

                print(f"✅ Updated connection string for target '{target_name}'")

                # Show if it contains env var references
                if '${' in connection_string or connection_string.startswith('$'):
                    print(f"📝 Note: Connection string contains environment variable references")
                    print(f"   These will be resolved from the environment at deployment time")

                return 0

            elif hasattr(args, 'show') and args.show:
                # Show target info including connection string
                target_name = args.target if hasattr(args, 'target') else None

                if target_name:
                    # Show specific target
                    target = self.query_one("""
                        SELECT target_name, target_type, provider, host, connection_string, access_url
                        FROM deployment_targets
                        WHERE project_id = ? AND target_name = ?
                    """, (project['id'], target_name))

                    if not target:
                        print(f"✗ Target '{target_name}' not found", file=sys.stderr)
                        return 1

                    print(f"\n🎯 Deployment Target: {target['target_name']}\n")
                    print(f"   Type: {target['target_type']}")
                    print(f"   Provider: {target['provider'] or 'unknown'}")
                    if target['host']:
                        print(f"   Host: {target['host']}")
                    if target['access_url']:
                        print(f"   Access URL: {target['access_url']}")
                    if target['connection_string']:
                        # Mask sensitive parts
                        conn_str = target['connection_string']
                        if '://' in conn_str and '@' in conn_str:
                            # Mask password in connection string
                            parts = conn_str.split('@')
                            before_at = parts[0]
                            if ':' in before_at:
                                protocol_user = before_at.rsplit(':', 1)[0]
                                conn_str = f"{protocol_user}:****@{parts[1]}"
                        print(f"   Connection: {conn_str}")
                    else:
                        print(f"   Connection: (not set)")
                    print()
                else:
                    # Show all targets
                    targets = self.query_all("""
                        SELECT target_name, target_type, provider, host,
                               CASE WHEN connection_string IS NOT NULL THEN 1 ELSE 0 END as has_connection
                        FROM deployment_targets
                        WHERE project_id = ?
                        ORDER BY target_name
                    """, (project['id'],))

                    if not targets:
                        print(f"⚠️  No deployment targets configured for {project_slug}\n")
                        return 0

                    print(f"\n🎯 Deployment Targets for {project_slug}:\n")
                    for target in targets:
                        conn_indicator = "✓" if target['has_connection'] else "✗"
                        print(f"   {conn_indicator} {target['target_name']} ({target['target_type']})")
                        print(f"      Provider: {target['provider'] or 'unknown'}")
                        if target['host']:
                            print(f"      Host: {target['host']}")
                    print()

                return 0

            else:
                print(f"Usage:")
                print(f"  ./templedb deploy target <project> --show [--target <name>]")
                print(f"  ./templedb deploy target <project> --set-connection --target <name> <connection_string>")
                return 1

        except Exception as e:
            print(f"✗ Failed to manage deployment target: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    # history, stats, health_check, rollback, list_deployed, get_deployed_path,
    # shell, exec_command, _format_time_ago, nixos_install
    # are provided by DeployOpsMixin (see deploy_ops.py)


def register(cli):
    """Register deployment commands with CLI"""
    deploy_handler = DeployCommands()

    # Create deploy command group
    deploy_parser = cli.register_command('deploy', None, help_text='Deploy project from TempleDB')
    subparsers = deploy_parser.add_subparsers(dest='deploy_subcommand', required=True)

    # Import deployment backend modules and consolidated subcommands
    from cli.commands import deploy_nix, fleet as fleet_module, deploy_script, deploy_appstore, deploy_steam, deploy_blue_green
    from cli.commands import target as target_module, migration as migration_module

    # deploy run command
    run_parser = subparsers.add_parser('run', help='Deploy project (uses FHS isolation by default)')
    run_parser.add_argument('slug', nargs='?', help='Project slug')
    run_parser.add_argument('--target', default=None, help='Deployment target (shows available targets if not specified)')
    run_parser.add_argument('--dry-run', action='store_true', help='Show what would be deployed without deploying')
    run_parser.add_argument('--skip-validation', action='store_true', help='Skip environment variable validation')
    run_parser.add_argument('--mutable', action='store_true',
                           help='Mutable mode: allow direct file editing (disables FHS isolation)')
    run_parser.add_argument('--no-fhs', action='store_true',
                           help='Disable FHS isolation completely (not recommended, uses system packages)')
    run_parser.add_argument('--no-script', action='store_true',
                           help='Skip custom deployment script and use standard deployment')
    run_parser.add_argument('--only', choices=['frontend', 'functions', 'migrations', 'secrets'],
                           help='Deploy only a specific component (passed through to the deploy script)')
    run_parser.add_argument('--commit', help='Deploy from a specific VCS commit hash')
    run_parser.add_argument('--branch', dest='deploy_branch',
                           help='Deploy from the head of a specific branch')
    run_parser.add_argument('--all-targets', action='store_true',
                           help='Deploy to all configured targets for this project')
    run_parser.add_argument('--targets', help='Comma-separated list of targets to deploy to')
    run_parser.add_argument('--examples', action='store_true', help='Show usage examples')
    cli.commands['deploy.run'] = deploy_handler.deploy

    # deploy status command
    status_parser = subparsers.add_parser('status', help='Show deployment status')
    status_parser.add_argument('slug', help='Project slug')
    cli.commands['deploy.status'] = deploy_handler.status

    # deploy init command
    init_parser = subparsers.add_parser('init', help='Initialize deployment configuration')
    init_parser.add_argument('slug', help='Project slug')
    cli.commands['deploy.init'] = deploy_handler.init

    # deploy config command
    config_parser = subparsers.add_parser('config', help='Manage deployment configuration')
    config_parser.add_argument('slug', help='Project slug')
    config_parser.add_argument('--show', action='store_true', help='Show configuration')
    config_parser.add_argument('--validate', action='store_true', help='Validate configuration')
    cli.commands['deploy.config'] = deploy_handler.config_command

    # deploy target command
    target_parser = subparsers.add_parser('target', help='Manage deployment targets')
    target_parser.add_argument('slug', help='Project slug')
    target_parser.add_argument('--show', action='store_true', help='Show target(s)')
    target_parser.add_argument('--target', help='Target name')
    target_parser.add_argument('--set-connection', action='store_true', help='Set connection string for target')
    target_parser.add_argument('connection_string', nargs='?', help='Connection string (supports ${ENV_VAR} syntax)')
    cli.commands['deploy.target'] = deploy_handler.target

    # deploy history command
    history_parser = subparsers.add_parser('history', help='Show deployment history with timestamps and health checks')
    history_parser.add_argument('slug', help='Project slug')
    history_parser.add_argument('--target', help='Filter by target')
    history_parser.add_argument('--limit', type=int, default=10, help='Number of deployments to show (default: 10)')
    cli.commands['deploy.history'] = deploy_handler.history

    # deploy stats command
    stats_parser = subparsers.add_parser('stats', help='Show deployment statistics')
    stats_parser.add_argument('slug', help='Project slug')
    cli.commands['deploy.stats'] = deploy_handler.stats

    # deploy health-check command
    health_parser = subparsers.add_parser('health-check', help='Run health checks on deployed project')
    health_parser.add_argument('slug', help='Project slug')
    health_parser.add_argument('--target', default='production', help='Deployment target (default: production)')
    cli.commands['deploy.health-check'] = deploy_handler.health_check

    # deploy rollback command
    rollback_parser = subparsers.add_parser('rollback', help='Rollback to previous deployment')
    rollback_parser.add_argument('slug', help='Project slug')
    rollback_parser.add_argument('--target', default='production', help='Deployment target (default: production)')
    rollback_parser.add_argument('--to-id', type=int, help='Deployment ID to rollback to (default: previous successful)')
    rollback_parser.add_argument('--reason', help='Reason for rollback')
    rollback_parser.add_argument('--yes', action='store_true', help='Skip confirmation prompt')
    cli.commands['deploy.rollback'] = deploy_handler.rollback

    # deploy list command
    list_parser = subparsers.add_parser('list', help='List all deployed projects')
    cli.commands['deploy.list'] = deploy_handler.list_deployed

    # deploy path command
    path_parser = subparsers.add_parser('path', help='Get path to deployed project (use with: cd $(tdb deploy path <project>))')
    path_parser.add_argument('slug', help='Project slug')
    cli.commands['deploy.path'] = deploy_handler.get_deployed_path

    # deploy nixos-install command
    nixos_install_parser = subparsers.add_parser('nixos-install', help='Install project as NixOS/home-manager package')
    nixos_install_parser.add_argument('slug', help='Project slug (must have flake.nix)')
    nixos_install_parser.add_argument('--system-config', default='system_config', help='System config project slug (default: system_config)')
    nixos_install_parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    nixos_install_parser.add_argument('--quiet', '-q', action='store_true', help='Hide nix store paths and copying lines from output')
    cli.commands['deploy.nixos-install'] = deploy_handler.nixos_install

    # deploy bootstrap command
    bootstrap_parser = subparsers.add_parser('bootstrap', help='Bootstrap NixOS on this machine from TempleDB database')
    bootstrap_parser.add_argument('--hostname', default=None, help='Hostname for flake target (default: current hostname)')
    bootstrap_parser.add_argument('--system-config', default='system_config', help='System config project slug (default: system_config)')
    bootstrap_parser.add_argument('--quiet', '-q', action='store_true', help='Hide nix store paths from output')
    bootstrap_parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    cli.commands['deploy.bootstrap'] = deploy_handler.bootstrap

    # deploy hardware-config command
    hw_config_parser = subparsers.add_parser('hardware-config', help='Generate and save hardware config for this machine')
    hw_config_parser.add_argument('--hostname', default=None, help='Hostname (default: current hostname)')
    hw_config_parser.add_argument('--system-config', default='system_config', help='System config project slug (default: system_config)')
    hw_config_parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    cli.commands['deploy.hardware-config'] = deploy_handler.hardware_config

    # deploy shell command
    shell_parser = subparsers.add_parser('shell', help='Enter interactive shell in deployment environment (FHS if available)')
    shell_parser.add_argument('slug', help='Project slug')
    cli.commands['deploy.shell'] = deploy_handler.shell

    # deploy exec command
    exec_parser = subparsers.add_parser('exec', help='Execute command in deployment environment')
    exec_parser.add_argument('slug', nargs='?', help='Project slug')
    exec_parser.add_argument('exec_command', nargs='?', metavar='command', help='Command to execute (quote if multiple words)')
    exec_parser.add_argument('--examples', action='store_true', help='Show usage examples')
    cli.commands['deploy.exec'] = deploy_handler.exec_command

    # === Nested deployment backend commands ===

    # deploy nix - Nix closures backend (from deploy-nix)
    deploy_nix.register_under_deploy(subparsers, cli)

    # deploy project - App deployment (Cloudflare Workers, Vercel, etc.)
    from cli.commands import deploy_project
    deploy_project.register_under_deploy(subparsers, cli)

    # deploy fleet - Multi-machine NixOS deployment with magic rollback
    fleet_module.register_under_deploy(subparsers, cli)

    # deploy bg - Blue-green deployment strategy
    deploy_blue_green.register_under_deploy(subparsers, cli)

    # deploy hooks - Custom deployment hooks (renamed from plugin/script)
    deploy_script.register_under_deploy(subparsers, cli)

    # deploy appstore - App store and package manager deployment
    deploy_appstore.register_under_deploy(subparsers, cli)

    # deploy steam - Steam platform deployment
    deploy_steam.register_under_deploy(subparsers, cli)

    # Consolidated: targets and migration management under deploy
    target_module.register_subcommands(subparsers, cli, prefix='deploy')
    migration_module.register_subcommands(subparsers, cli, prefix='deploy')

    # === Pipeline automation commands ===
    from cli.commands.deploy_pipeline import register_pipeline_commands
    register_pipeline_commands(subparsers, cli)
