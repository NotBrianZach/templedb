#!/usr/bin/env python3
"""
Deployment history and health check commands
"""
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class DeployHistoryCommands(Command):
    """Deployment history command handlers"""

    def __init__(self):
        super().__init__()
        from services.context import ServiceContext
        from services.deployment_tracking_service import DeploymentTrackingService
        self.ctx = ServiceContext()
        self.tracking_service = DeploymentTrackingService()

    def history(self, args) -> int:
        """Show deployment history"""
        try:
            project_slug = args.slug
            target = args.target if hasattr(args, 'target') and args.target else None
            limit = args.limit if hasattr(args, 'limit') and args.limit else 10

            deployments = self.tracking_service.get_deployment_history(
                project_slug=project_slug,
                target=target,
                limit=limit
            )

            if not deployments:
                print(f"No deployments found for {project_slug}")
                if target:
                    print(f"(filtered by target: {target})")
                return 0

            # Display deployment history
            print(f"\n📜 Deployment History: {project_slug}")
            if target:
                print(f"   Target: {target}")
            print(f"   Showing last {len(deployments)} deployments\n")

            for deployment in deployments:
                # Status indicator
                status_icon = {
                    'success': '✅',
                    'failed': '❌',
                    'in_progress': '🔄',
                    'rolled_back': '⏪'
                }.get(deployment.status, '❓')

                # Format timestamp
                deployed_at = deployment.deployed_at
                if isinstance(deployed_at, str):
                    try:
                        dt = datetime.fromisoformat(deployed_at.replace('Z', '+00:00'))
                        deployed_at = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        pass

                print(f"{status_icon} Deployment #{deployment.id}")
                print(f"   Target:    {deployment.target}")
                print(f"   Status:    {deployment.status}")
                print(f"   Deployed:  {deployed_at}")

                if deployment.duration_seconds:
                    print(f"   Duration:  {deployment.duration_seconds:.2f}s")

                if deployment.deployment_hash:
                    print(f"   Hash:      {deployment.deployment_hash[:12]}...")

                if deployment.notes:
                    print(f"   Notes:     {deployment.notes}")

                # Get health checks
                health_checks = self.tracking_service.get_health_checks(deployment.id)
                if health_checks:
                    print(f"   Health Checks:")
                    for check in health_checks:
                        check_icon = {
                            'pass': '✅',
                            'fail': '❌',
                            'skip': '⏭️',
                            'timeout': '⏱️'
                        }.get(check['status'], '❓')
                        print(f"      {check_icon} {check['check_name']}: {check['status']}")
                        if check.get('response_time_ms'):
                            print(f"         ({check['response_time_ms']}ms)")

                print()

            return 0

        except Exception as e:
            logger.error(f"Failed to get deployment history: {e}")
            import traceback
            traceback.print_exc()
            return 1

    def stats(self, args) -> int:
        """Show deployment statistics"""
        try:
            project_slug = args.slug

            stats = self.tracking_service.get_deployment_stats(project_slug)

            if not stats:
                print(f"No deployment statistics found for {project_slug}")
                return 0

            print(f"\n📊 Deployment Statistics: {project_slug}\n")

            for stat in stats:
                success_rate = (stat['successful_deployments'] / stat['total_deployments'] * 100) if stat['total_deployments'] > 0 else 0

                print(f"Target: {stat['target']}")
                print(f"  Total deployments:      {stat['total_deployments']}")
                print(f"  Successful:             {stat['successful_deployments']}")
                print(f"  Failed:                 {stat['failed_deployments']}")
                print(f"  Success rate:           {success_rate:.1f}%")

                if stat['avg_duration_seconds']:
                    print(f"  Avg duration:           {stat['avg_duration_seconds']:.2f}s")

                if stat['last_deployed_at']:
                    print(f"  Last deployment:        {stat['last_deployed_at']}")

                print()

            return 0

        except Exception as e:
            logger.error(f"Failed to get deployment statistics: {e}")
            import traceback
            traceback.print_exc()
            return 1

    def health_check(self, args) -> int:
        """Run health checks on deployed project"""
        try:
            project_slug = args.slug
            target = args.target if hasattr(args, 'target') and args.target else 'production'

            # Get latest deployment for this target
            deployments = self.tracking_service.get_deployment_history(
                project_slug=project_slug,
                target=target,
                limit=1
            )

            if not deployments:
                print(f"No deployments found for {project_slug} ({target})")
                return 1

            deployment = deployments[0]
            print(f"\n🏥 Running health checks for {project_slug} ({target})")
            print(f"   Deployment #{deployment.id} from {deployment.deployed_at}\n")

            # Get project to access environment variables
            project = self.ctx.project_repo.get_by_slug(project_slug)
            if not project:
                print(f"Project not found: {project_slug}")
                return 1

            # Get environment variables for health check URLs
            env_vars = self.ctx.base_repo.query_all("""
                SELECT var_name, var_value
                FROM environment_variables
                WHERE scope_type = 'project'
                  AND scope_id = ?
                  AND (var_name LIKE ? OR var_name NOT LIKE '%:%')
            """, (project['id'], f"{target}:%"))

            env_dict = {}
            for row in env_vars:
                var_name = row['var_name']
                if ':' in var_name:
                    _, actual_name = var_name.split(':', 1)
                else:
                    actual_name = var_name
                env_dict[actual_name] = row['var_value']

            # Run HTTP health checks
            checks_run = 0

            # Check SUPABASE_URL if available
            if 'SUPABASE_URL' in env_dict:
                url = env_dict['SUPABASE_URL']
                print(f"Checking Supabase API...")
                result = self.tracking_service.run_http_health_check(
                    deployment_id=deployment.id,
                    check_name="Supabase API",
                    url=url
                )
                status_icon = '✅' if result.status == 'pass' else '❌'
                print(f"  {status_icon} {result.status.upper()}", end='')
                if result.response_time_ms:
                    print(f" ({result.response_time_ms}ms)", end='')
                if result.error_message:
                    print(f" - {result.error_message}", end='')
                print()
                checks_run += 1

            # Check DATABASE_URL if available
            if 'DATABASE_URL' in env_dict:
                print(f"Checking database connectivity...")
                result = self.tracking_service.run_database_health_check(
                    deployment_id=deployment.id,
                    check_name="Database",
                    database_url=env_dict['DATABASE_URL']
                )
                status_icon = '✅' if result.status == 'pass' else '❌'
                print(f"  {status_icon} {result.status.upper()}", end='')
                if result.response_time_ms:
                    print(f" ({result.response_time_ms}ms)", end='')
                if result.error_message:
                    print(f" - {result.error_message}", end='')
                print()
                checks_run += 1

            # Check PUBLIC_URL if available
            if 'PUBLIC_URL' in env_dict:
                url = env_dict['PUBLIC_URL']
                print(f"Checking public URL...")
                result = self.tracking_service.run_http_health_check(
                    deployment_id=deployment.id,
                    check_name="Public URL",
                    url=url
                )
                status_icon = '✅' if result.status == 'pass' else '❌'
                print(f"  {status_icon} {result.status.upper()}", end='')
                if result.response_time_ms:
                    print(f" ({result.response_time_ms}ms)", end='')
                if result.error_message:
                    print(f" - {result.error_message}", end='')
                print()
                checks_run += 1

            if checks_run == 0:
                print("No health check endpoints configured")
                print("Set SUPABASE_URL, DATABASE_URL, or PUBLIC_URL to enable health checks")

            print()
            return 0

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            import traceback
            traceback.print_exc()
            return 1


def register(cli):
    """Register deployment history commands

    Note: These are registered as subcommands under 'deploy' in deploy.py
    This function is called after deploy.register() to add history commands.
    """
    # Commands are registered in deploy.py register() function
    # This is just a placeholder for future expansion
    pass
