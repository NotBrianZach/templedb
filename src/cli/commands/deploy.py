#!/usr/bin/env python3
"""
Deployment management commands for TempleDB
"""
import sys
import subprocess
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from deployment_config import DeploymentConfigManager
from deployment_orchestrator import DeploymentOrchestrator
from logger import get_logger
import db_utils

logger = get_logger(__name__)


class DeployCommands(Command):
    """Deployment command handlers"""

    def __init__(self):
        super().__init__()
        """Initialize with service context"""
        from services.context import ServiceContext
        self.ctx = ServiceContext()
        self.service = self.ctx.get_deployment_service()

    def deploy(self, args) -> int:
        """Deploy project from TempleDB"""
        from error_handler import ResourceNotFoundError, DeploymentError

        try:
            project_slug = args.slug
            target = args.target if hasattr(args, 'target') and args.target else 'production'
            dry_run = args.dry_run if hasattr(args, 'dry_run') and args.dry_run else False
            skip_validation = hasattr(args, 'skip_validation') and args.skip_validation

            print(f"🚀 Deploying {project_slug} to {target}...")

            if dry_run:
                print("📋 DRY RUN - No actual deployment will occur\n")

            # Use service for deployment
            result = self.service.deploy(
                project_slug=project_slug,
                target=target,
                dry_run=dry_run,
                skip_validation=skip_validation
            )

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
                print("   Use: ./templedb target add <project> <target_name> ...\n")

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

    def history(self, args) -> int:
        """Show deployment history for a project"""
        try:
            project_slug = args.slug
            project = self.get_project_or_exit(project_slug)

            from deployment_tracker import DeploymentTracker
            tracker = DeploymentTracker(db_utils)

            target = args.target if hasattr(args, 'target') and args.target else None
            limit = args.limit if hasattr(args, 'limit') and args.limit else 10

            print(f"\n📜 Deployment History: {project_slug}")
            if target:
                print(f"   Target: {target}")
            print()

            # Get deployment history
            history = tracker.get_deployment_history(
                project_id=project['id'],
                target_name=target,
                limit=limit
            )

            if not history:
                print("   No deployments found")
                return 0

            # Display history
            for record in history:
                status_icon = {
                    'success': '✅',
                    'failed': '❌',
                    'in_progress': '🔄',
                    'rolled_back': '⏪'
                }.get(record.status, '❓')

                print(f"{status_icon} #{record.id} - {record.target_name}")
                print(f"   Status: {record.status}")
                print(f"   Started: {record.started_at}")
                if record.completed_at:
                    print(f"   Duration: {record.duration_ms / 1000:.1f}s")
                if record.commit_hash:
                    print(f"   Commit: {record.commit_hash[:8]}")
                if record.deployed_by:
                    print(f"   By: {record.deployed_by}")
                if record.groups_deployed:
                    print(f"   Groups: {', '.join(record.groups_deployed)}")
                if record.error_message:
                    print(f"   Error: {record.error_message[:100]}")
                print()

            return 0

        except Exception as e:
            print(f"✗ Failed to get deployment history: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    def rollback(self, args) -> int:
        """Rollback to a previous deployment"""
        try:
            project_slug = args.slug
            project = self.get_project_or_exit(project_slug)

            from deployment_tracker import DeploymentTracker
            tracker = DeploymentTracker(db_utils)

            target = args.target if hasattr(args, 'target') and args.target else 'production'
            to_deployment_id = args.to_id if hasattr(args, 'to_id') and args.to_id else None
            reason = args.reason if hasattr(args, 'reason') and args.reason else None

            print(f"\n⏪ Rolling back {project_slug} on {target}...\n")

            # Get current deployment
            current = tracker.get_deployment_history(
                project_id=project['id'],
                target_name=target,
                limit=1,
                status='success'
            )

            if not current:
                print("✗ No successful deployment found to rollback from", file=sys.stderr)
                return 1

            current_deployment = current[0]

            # If no specific target, get last successful before current
            if not to_deployment_id:
                previous = tracker.get_last_successful_deployment(
                    project_id=project['id'],
                    target_name=target,
                    before_deployment_id=current_deployment.id
                )

                if not previous:
                    print("✗ No previous deployment found to rollback to", file=sys.stderr)
                    return 1

                to_deployment_id = previous.id
                print(f"📌 Rolling back from deployment #{current_deployment.id} to #{to_deployment_id}")
            else:
                print(f"📌 Rolling back from deployment #{current_deployment.id} to #{to_deployment_id}")

            # Get target deployment
            target_deployment = None
            all_deployments = tracker.get_deployment_history(
                project_id=project['id'],
                target_name=target,
                limit=100
            )
            for d in all_deployments:
                if d.id == to_deployment_id:
                    target_deployment = d
                    break

            if not target_deployment:
                print(f"✗ Deployment #{to_deployment_id} not found", file=sys.stderr)
                return 1

            if target_deployment.status != 'success':
                print(f"✗ Cannot rollback to deployment with status: {target_deployment.status}", file=sys.stderr)
                return 1

            # Show what will be rolled back
            print(f"\n📋 Rollback Plan:")
            print(f"   Current: Deployment #{current_deployment.id}")
            print(f"            Started: {current_deployment.started_at}")
            if current_deployment.commit_hash:
                print(f"            Commit: {current_deployment.commit_hash[:8]}")
            print()
            print(f"   Target:  Deployment #{target_deployment.id}")
            print(f"            Started: {target_deployment.started_at}")
            if target_deployment.commit_hash:
                print(f"            Commit: {target_deployment.commit_hash[:8]}")
            print()

            # Confirm (unless --yes flag)
            if not (hasattr(args, 'yes') and args.yes):
                response = input("   Proceed with rollback? [y/N]: ")
                if response.lower() not in ['y', 'yes']:
                    print("   Rollback cancelled")
                    return 0

            print("\n🔄 Performing rollback...\n")

            from deployment_orchestrator import DeploymentOrchestrator
            from deployment_config import DeploymentConfigManager

            config_manager = DeploymentConfigManager(db_utils)
            config = config_manager.get_config(project['id'])

            if not config.groups:
                print("✗ No deployment configuration found - cannot rollback", file=sys.stderr)
                return 1

            # Get commit hash to rollback to
            if not target_deployment.commit_hash:
                print("✗ Target deployment has no commit hash - cannot rollback", file=sys.stderr)
                return 1

            # Create orchestrator and execute rollback
            # Note: work_dir will be created by orchestrator.rollback()
            orchestrator = DeploymentOrchestrator(
                project=project,
                target_name=target,
                config=config,
                db_utils=db_utils,
                work_dir=Path("/tmp")  # Placeholder, will be replaced in rollback()
            )

            # Execute rollback
            result = orchestrator.rollback(
                to_commit_hash=target_deployment.commit_hash,
                dry_run=False,
                validate_env=True
            )

            if result.success:
                # Record rollback relationship
                # Get the rollback deployment ID from tracker
                rollback_deployments = tracker.get_deployment_history(
                    project_id=project['id'],
                    target_name=target,
                    limit=1
                )

                if rollback_deployments:
                    rollback_deployment_id = rollback_deployments[0].id
                    tracker.record_rollback(
                        from_deployment_id=current_deployment.id,
                        to_deployment_id=target_deployment.id,
                        rollback_deployment_id=rollback_deployment_id,
                        reason=reason
                    )

                print("\n✅ Rollback completed successfully!")
                return 0
            else:
                print(f"\n✗ Rollback failed: {result.error_message}")
                return 1

            return 0

        except Exception as e:
            print(f"✗ Rollback failed: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1


def register(cli):
    """Register deployment commands with CLI"""
    deploy_handler = DeployCommands()

    # Create deploy command group
    deploy_parser = cli.register_command('deploy', None, help_text='Deploy project from TempleDB')
    subparsers = deploy_parser.add_subparsers(dest='deploy_subcommand', required=True)

    # deploy run command
    run_parser = subparsers.add_parser('run', help='Deploy project')
    run_parser.add_argument('slug', help='Project slug')
    run_parser.add_argument('--target', default='production', help='Deployment target (default: production)')
    run_parser.add_argument('--dry-run', action='store_true', help='Show what would be deployed without deploying')
    run_parser.add_argument('--skip-validation', action='store_true', help='Skip environment variable validation')
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
    history_parser = subparsers.add_parser('history', help='Show deployment history')
    history_parser.add_argument('slug', help='Project slug')
    history_parser.add_argument('--target', help='Filter by target')
    history_parser.add_argument('--limit', type=int, default=10, help='Number of deployments to show (default: 10)')
    cli.commands['deploy.history'] = deploy_handler.history

    # deploy rollback command
    rollback_parser = subparsers.add_parser('rollback', help='Rollback to previous deployment')
    rollback_parser.add_argument('slug', help='Project slug')
    rollback_parser.add_argument('--target', default='production', help='Deployment target (default: production)')
    rollback_parser.add_argument('--to-id', type=int, help='Deployment ID to rollback to (default: previous successful)')
    rollback_parser.add_argument('--reason', help='Reason for rollback')
    rollback_parser.add_argument('--yes', action='store_true', help='Skip confirmation prompt')
    cli.commands['deploy.rollback'] = deploy_handler.rollback
