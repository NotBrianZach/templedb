#!/usr/bin/env python3
"""
Example: Automated Deployment Pipeline

Demonstrates how to use the service layer to create an automated deployment
pipeline that can be triggered by CI/CD or cron jobs.

Usage:
    python3 examples/automated_deployment.py deploy my-project production
    python3 examples/automated_deployment.py status my-project
    python3 examples/automated_deployment.py list-targets my-project

This demonstrates:
- Using DeploymentService programmatically
- Checking deployment status
- Executing deployments
- Error handling for automated workflows
"""
import sys
from pathlib import Path
import json
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from services.context import ServiceContext
from error_handler import ResourceNotFoundError, DeploymentError


def deploy_project(project_slug: str, target: str, dry_run: bool = False):
    """
    Deploy a project to a target environment.

    Args:
        project_slug: Project slug
        target: Target environment (e.g., 'production', 'staging')
        dry_run: If True, simulate deployment

    Returns:
        int: Exit code (0 for success, 1 for failure)
    """
    ctx = ServiceContext()
    service = ctx.get_deployment_service()

    print(f"🚀 Deploying {project_slug} to {target}")
    print(f"   Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"   Dry run: {'Yes' if dry_run else 'No'}")
    print()

    try:
        # Execute deployment
        result = service.deploy(
            project_slug=project_slug,
            target=target,
            dry_run=dry_run,
            skip_validation=False
        )

        if result.success:
            print("✅ Deployment successful!")
            print(f"   Work directory: {result.work_dir}")
            print(f"   Message: {result.message}")

            # Log to file for CI/CD
            log_deployment(project_slug, target, success=True)

            return 0
        else:
            print(f"❌ Deployment failed: {result.message}")
            print(f"   Exit code: {result.exit_code}")

            # Log failure
            log_deployment(project_slug, target, success=False, error=result.message)

            return 1

    except ResourceNotFoundError as e:
        print(f"❌ Error: {e}")
        if e.solution:
            print(f"   💡 {e.solution}")
        log_deployment(project_slug, target, success=False, error=str(e))
        return 1

    except DeploymentError as e:
        print(f"❌ Deployment error: {e}")
        if e.solution:
            print(f"   💡 {e.solution}")
        log_deployment(project_slug, target, success=False, error=str(e))
        return 1

    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        log_deployment(project_slug, target, success=False, error=str(e))
        return 1


def get_deployment_status(project_slug: str):
    """
    Get deployment status for a project.

    Args:
        project_slug: Project slug

    Returns:
        int: Exit code
    """
    ctx = ServiceContext()
    service = ctx.get_deployment_service()

    try:
        status = service.get_deployment_status(project_slug)

        print(f"📊 Deployment Status: {project_slug}")
        print()

        # Targets
        if status['targets']:
            print("🎯 Deployment Targets:")
            for target in status['targets']:
                print(f"   • {target['target_name']} ({target['target_type']})")
                if target['provider']:
                    print(f"     Provider: {target['provider']}")
                if target['host']:
                    print(f"     Host: {target['host']}")
            print()
        else:
            print("⚠️  No deployment targets configured")
            print()

        # Scripts
        if status['deploy_scripts']:
            print("📜 Deployment Scripts:")
            for script in status['deploy_scripts']:
                print(f"   • {script}")
            print()

        # Migrations
        print(f"🗄️  Database Migrations: {status['migration_count']}")
        print()

        return 0

    except ResourceNotFoundError as e:
        print(f"❌ Error: {e}")
        return 1


def list_deployment_targets(project_slug: str):
    """
    List all deployment targets for a project.

    Args:
        project_slug: Project slug

    Returns:
        int: Exit code
    """
    ctx = ServiceContext()
    service = ctx.get_deployment_service()

    try:
        status = service.get_deployment_status(project_slug)

        if not status['targets']:
            print(f"No deployment targets configured for {project_slug}")
            return 0

        print(f"Deployment targets for {project_slug}:")
        print()

        for target in status['targets']:
            print(f"  {target['target_name']}")
            print(f"    Type: {target['target_type']}")
            print(f"    Provider: {target['provider'] or 'N/A'}")
            print(f"    Host: {target['host'] or 'N/A'}")
            print()

        return 0

    except ResourceNotFoundError as e:
        print(f"❌ Error: {e}")
        return 1


def log_deployment(project_slug: str, target: str, success: bool, error: str = None):
    """
    Log deployment to file for CI/CD tracking.

    Args:
        project_slug: Project slug
        target: Target environment
        success: Whether deployment succeeded
        error: Error message if failed
    """
    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'project': project_slug,
        'target': target,
        'success': success,
        'error': error
    }

    # Append to deployment log
    log_file = Path('/tmp/templedb_deployments.log')
    with open(log_file, 'a') as f:
        f.write(json.dumps(log_entry) + '\n')


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Automated deployment pipeline for TempleDB',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Deploy to production
  python3 examples/automated_deployment.py deploy my-project production

  # Dry run deployment
  python3 examples/automated_deployment.py deploy my-project staging --dry-run

  # Check deployment status
  python3 examples/automated_deployment.py status my-project

  # List deployment targets
  python3 examples/automated_deployment.py list-targets my-project

Use in CI/CD:
  # GitLab CI
  deploy:
    script:
      - python3 examples/automated_deployment.py deploy $PROJECT production

  # GitHub Actions
  - name: Deploy
    run: python3 examples/automated_deployment.py deploy ${{ env.PROJECT }} production
        """
    )

    subparsers = parser.add_subparsers(dest='command', required=True)

    # Deploy command
    deploy_parser = subparsers.add_parser('deploy', help='Deploy project')
    deploy_parser.add_argument('project', help='Project slug')
    deploy_parser.add_argument('target', help='Target environment')
    deploy_parser.add_argument('--dry-run', action='store_true', help='Simulate deployment')

    # Status command
    status_parser = subparsers.add_parser('status', help='Show deployment status')
    status_parser.add_argument('project', help='Project slug')

    # List targets command
    targets_parser = subparsers.add_parser('list-targets', help='List deployment targets')
    targets_parser.add_argument('project', help='Project slug')

    args = parser.parse_args()

    # Execute command
    if args.command == 'deploy':
        exit_code = deploy_project(args.project, args.target, dry_run=args.dry_run)
    elif args.command == 'status':
        exit_code = get_deployment_status(args.project)
    elif args.command == 'list-targets':
        exit_code = list_deployment_targets(args.project)
    else:
        print(f"Unknown command: {args.command}", file=sys.stderr)
        exit_code = 1

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
