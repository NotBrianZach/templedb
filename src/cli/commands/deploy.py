#!/usr/bin/env python3
"""
Deployment management commands for TempleDB
"""
import sys
import subprocess
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

    def list_deployed(self, args) -> int:
        """List all deployed projects with their paths"""
        try:
            from pathlib import Path
            import os
            from datetime import datetime

            deploy_base = Path("/tmp")
            deployed_projects = []

            # Find all deployed project directories
            for item in deploy_base.glob("templedb_deploy_*"):
                if item.is_dir():
                    working_dir = item / "working"
                    if working_dir.exists():
                        # Extract project slug from directory name
                        project_slug = item.name.replace("templedb_deploy_", "")

                        # Get modification time
                        mtime = working_dir.stat().st_mtime
                        modified = datetime.fromtimestamp(mtime)

                        # Check if .envrc exists
                        has_envrc = (working_dir / ".envrc").exists()

                        deployed_projects.append({
                            'slug': project_slug,
                            'path': str(working_dir),
                            'modified': modified,
                            'has_envrc': has_envrc
                        })

            if not deployed_projects:
                print("No deployed projects found in /tmp/")
                print("\nDeploy a project with:")
                print("  ./templedb deploy run <project>")
                return 0

            # Sort by modification time (most recent first)
            deployed_projects.sort(key=lambda x: x['modified'], reverse=True)

            print(f"\n📦 Deployed Projects ({len(deployed_projects)}):\n")

            for proj in deployed_projects:
                envrc_indicator = "✓" if proj['has_envrc'] else "✗"
                age = self._format_time_ago(proj['modified'])

                print(f"  {envrc_indicator} {proj['slug']}")
                print(f"     Path: {proj['path']}")
                print(f"     Updated: {age}")
                print()

            print("💡 Tips:")
            print(f"   Jump to project:  cd $(./templedb deploy path <project>)")
            print(f"   Or use tdb:       cd $(tdb deploy path <project>)")
            print()

            return 0

        except Exception as e:
            print(f"✗ Failed to list deployed projects: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    def get_deployed_path(self, args) -> int:
        """Get the path to a deployed project"""
        try:
            from pathlib import Path

            project_slug = args.slug
            deploy_dir = Path(f"/tmp/templedb_deploy_{project_slug}")
            working_dir = deploy_dir / "working"

            if not working_dir.exists():
                print(f"✗ No deployment found for '{project_slug}'", file=sys.stderr)
                print(f"\nDeploy with: ./templedb deploy run {project_slug}", file=sys.stderr)
                return 1

            # Just print the path (for scripting/piping)
            print(working_dir)
            return 0

        except Exception as e:
            print(f"✗ Failed to get deployment path: {e}", file=sys.stderr)
            return 1

    def _format_time_ago(self, dt: datetime) -> str:
        """Format datetime as human-readable time ago"""
        from datetime import datetime

        now = datetime.now()
        diff = now - dt

        seconds = diff.total_seconds()

        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        else:
            days = int(seconds / 86400)
            return f"{days} day{'s' if days != 1 else ''} ago"

    def nixos_install(self, args) -> int:
        """Install project as NixOS/home-manager package"""
        try:
            project_slug = args.slug
            project = self.get_project_or_exit(project_slug)

            system_config_slug = args.system_config if hasattr(args, 'system_config') else 'system_config'
            dry_run = hasattr(args, 'dry_run') and args.dry_run

            print(f"\n📦 Installing {project_slug} to NixOS config\n")

            # 1. Verify project has a flake
            project_path = Path(project['repo_url'])
            flake_path = project_path / 'flake.nix'

            if not flake_path.exists():
                print(f"❌ Project {project_slug} doesn't have a flake.nix")
                print(f"\n💡 Create a flake for this project first:")
                print(f"   cd {project_path}")
                print(f"   nix flake init")
                return 1

            # 2. Get system_config project
            system_config = self.query_one("""
                SELECT id, slug, repo_url FROM projects WHERE slug = ?
            """, (system_config_slug,))

            if not system_config:
                print(f"❌ System config project '{system_config_slug}' not found")
                print(f"\n💡 Import your system config:")
                print(f"   ./templedb project import ~/.config/templedb/checkouts/system_config")
                return 1

            system_config_path = Path(system_config['repo_url'])
            system_flake = system_config_path / 'flake.nix'
            system_home = system_config_path / 'home.nix'

            if not system_flake.exists():
                print(f"❌ System config doesn't have flake.nix at {system_flake}")
                return 1

            print(f"✅ Found flake.nix in {project_slug}")
            print(f"✅ Found system config at {system_config_path}")
            print()

            if dry_run:
                print("🔍 DRY RUN - Would make these changes:\n")
                print(f"1. Add to {system_flake}:")
                print(f"   inputs.{project_slug}.url = \"path:{project_path}\"")
                print()
                print(f"2. Add to {system_home}:")
                print(f"   {project_slug}.packages.${{pkgs.system}}.default")
                print()
                print("3. Commit changes to git")
                print("4. Run: nixos-rebuild switch with home-manager")
                print()
                return 0

            # 3. Update flake.nix inputs
            print(f"📝 Updating {system_flake}...")
            with open(system_flake, 'r') as f:
                flake_content = f.read()

            # Check if already exists
            if f'{project_slug}.url' in flake_content:
                print(f"⚠️  {project_slug} already in flake.nix inputs")
            else:
                # Add input after last input (before closing brace of inputs)
                # Find the inputs section and add before the closing };
                inputs_match = re.search(r'(inputs = \{.*?)(  \};)', flake_content, re.DOTALL)
                if inputs_match:
                    before_close = inputs_match.group(1)
                    close_brace = inputs_match.group(2)

                    # Add new input
                    new_input = f'\n    # {project["name"] or project_slug}\n    {project_slug}.url = "path:{project_path}";\n'
                    updated_inputs = before_close + new_input + '\n' + close_brace
                    flake_content = flake_content.replace(inputs_match.group(0), updated_inputs)

                    # Also need to add to outputs parameters
                    outputs_match = re.search(r'outputs = \{ ([^}]+) \}@inputs:', flake_content)
                    if outputs_match:
                        params = outputs_match.group(1)
                        if project_slug not in params:
                            # Add to parameters
                            new_params = params.rstrip() + f', {project_slug}'
                            flake_content = flake_content.replace(
                                f'outputs = {{ {params} }}@inputs:',
                                f'outputs = {{ {new_params} }}@inputs:'
                            )

                    # Also add to extraSpecialArgs
                    special_args_match = re.search(r'extraSpecialArgs = \{ inherit ([^}]+) \};', flake_content)
                    if special_args_match:
                        args_list = special_args_match.group(1)
                        if project_slug not in args_list:
                            new_args = args_list.rstrip() + f' {project_slug}'
                            flake_content = flake_content.replace(
                                f'extraSpecialArgs = {{ inherit {args_list} }};',
                                f'extraSpecialArgs = {{ inherit {new_args} }};'
                            )

                    with open(system_flake, 'w') as f:
                        f.write(flake_content)
                    print(f"✅ Added {project_slug} to flake inputs")
                else:
                    print(f"⚠️  Could not parse flake.nix inputs section")
                    return 1

            # 4. Update home.nix
            print(f"📝 Updating {system_home}...")
            with open(system_home, 'r') as f:
                home_content = f.read()

            # Check if already in home.nix arguments
            # Look for the pattern more robustly
            args_pattern = r'\{ ([^}]+) \}:'
            args_match = re.search(args_pattern, home_content)
            if args_match:
                current_args = args_match.group(1)
                # Check if project_slug already in arguments (as whole word)
                if not re.search(rf'\b{project_slug}\b', current_args):
                    # Add to function arguments (insert before ...)
                    new_args = current_args.replace(', ...', f', {project_slug}, ...')
                    home_content = home_content.replace(
                        f'{{ {current_args} }}:',
                        f'{{ {new_args} }}:'
                    )

            # Check if already in packages
            package_ref = f'{project_slug}.packages.${{pkgs.system}}.default'
            if package_ref not in home_content:
                # Add to home.packages
                packages_match = re.search(r'(home\.packages = with pkgs; \[)', home_content)
                if packages_match:
                    # Add comment and package after the opening bracket
                    insert_pos = home_content.find('[', packages_match.start()) + 1
                    new_package = f'\n    # {project["name"] or project_slug}\n    {package_ref}\n'
                    home_content = home_content[:insert_pos] + new_package + home_content[insert_pos:]

                    with open(system_home, 'w') as f:
                        f.write(home_content)
                    print(f"✅ Added {project_slug} to home.packages")
                else:
                    print(f"⚠️  Could not find home.packages in home.nix")
            else:
                print(f"⚠️  {project_slug} already in home.packages")

            # 5. Commit changes
            print(f"\n📦 Committing changes...")
            subprocess.run(['git', '-C', str(system_config_path), 'add', 'flake.nix', 'home.nix'], check=True)
            commit_msg = f"Add {project_slug} to NixOS installation\n\n🤖 Generated with TempleDB"
            subprocess.run(['git', '-C', str(system_config_path), 'commit', '-m', commit_msg], check=True)
            print(f"✅ Changes committed")

            # 6. Rebuild system
            print(f"\n🚀 Deploying to NixOS with home-manager...")
            print(f"   (You may be prompted for sudo password and confirmation)")
            print()

            from services.system_service import SystemService
            service = SystemService()
            result = service.switch_system(system_config_slug, with_home_manager=True)

            if result['success']:
                print(f"\n✅ {project_slug} installed successfully!")
                print(f"\n📍 Verify installation:")
                print(f"   which {project_slug}")
                print(f"   {project_slug} --help")
                return 0
            else:
                print(f"\n❌ Deployment failed")
                print(f"   Error: {result.get('stderr', 'Unknown error')}")
                return 1

        except Exception as e:
            print(f"✗ Failed to install to NixOS: {e}", file=sys.stderr)
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
    cli.commands['deploy.nixos-install'] = deploy_handler.nixos_install
