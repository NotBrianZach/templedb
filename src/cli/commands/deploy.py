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
import db_utils


class DeployCommands(Command):
    """Deployment command handlers"""

    def deploy(self, args) -> int:
        """Deploy project from TempleDB"""
        try:
            from cathedral_export import export_project

            project_slug = args.slug
            target = args.target if hasattr(args, 'target') and args.target else 'production'
            dry_run = args.dry_run if hasattr(args, 'dry_run') and args.dry_run else False

            # Verify project exists
            project = self.get_project_or_exit(project_slug)

            print(f"🚀 Deploying {project_slug} to {target}...")

            if dry_run:
                print("📋 DRY RUN - No actual deployment will occur\n")

            # Step 1: Export cathedral package to temp directory
            export_dir = Path(f"/tmp/templedb_deploy_{project_slug}")
            export_dir.mkdir(parents=True, exist_ok=True)

            print("📦 Exporting project from TempleDB...")
            success = export_project(
                slug=project_slug,
                output_dir=export_dir,
                compress=False,
                include_files=True,
                include_vcs=True,
                include_environments=True
            )

            if not success:
                print("✗ Export failed", file=sys.stderr)
                return 1

            cathedral_dir = export_dir / f"{project_slug}.cathedral"

            if not cathedral_dir.exists():
                print(f"✗ Cathedral directory not found: {cathedral_dir}", file=sys.stderr)
                return 1

            print(f"✓ Exported to {cathedral_dir}\n")

            # Step 2: Reconstruct project from cathedral files
            work_dir = export_dir / "working"
            work_dir.mkdir(exist_ok=True)

            print("🔧 Reconstructing project from cathedral package...")
            self._reconstruct_project(cathedral_dir, work_dir)
            print(f"✓ Project reconstructed to {work_dir}\n")

            # Step 3: Check for deployment configuration
            config_manager = DeploymentConfigManager(db_utils)
            config = config_manager.get_config(project['id'])

            if config.groups:
                # Use orchestrated deployment
                print("📋 Found deployment configuration - using orchestrator\n")

                orchestrator = DeploymentOrchestrator(
                    project=project,
                    target_name=target,
                    config=config,
                    db_utils=db_utils,
                    work_dir=work_dir
                )

                # Get optional flags
                validate_env = not (hasattr(args, 'skip_validation') and args.skip_validation)
                skip_groups = args.skip_group if hasattr(args, 'skip_group') and args.skip_group else None

                # Execute deployment
                result = orchestrator.deploy(
                    dry_run=dry_run,
                    validate_env=validate_env,
                    skip_groups=skip_groups
                )

                return 0 if result.success else 1

            else:
                # Fallback to deploy.sh script (backwards compatibility)
                deploy_script = work_dir / "deploy.sh"

                if deploy_script.exists():
                    print(f"🔨 Found deployment script: {deploy_script.name}")

                    if dry_run:
                        print(f"   Would execute: bash {deploy_script}")
                        print("\n✓ Dry run complete - no actual deployment performed")
                        return 0

                    print("   Executing deployment script...\n")
                    print("=" * 60)

                    # Run the deployment script
                    result = subprocess.run(
                        ["bash", str(deploy_script)],
                        cwd=work_dir,
                        env={**subprocess.os.environ, "DEPLOYMENT_TARGET": target}
                    )

                    print("=" * 60)

                    if result.returncode == 0:
                        print("\n✅ Deployment complete!")
                        return 0
                    else:
                        print(f"\n✗ Deployment failed with exit code {result.returncode}", file=sys.stderr)
                        return result.returncode
                else:
                    print("⚠️  No deployment configuration or deploy.sh found")
                    print("\n📝 To enable automated deployment:")
                    print(f"   Option 1 - Use deployment config (recommended):")
                    print(f"      ./templedb deploy init {project_slug}")
                    print(f"   Option 2 - Use deploy.sh script:")
                    print(f"      1. Create a deploy.sh script in {project_slug}")
                    print(f"      2. Re-import: ./templedb project sync {project_slug}")

                    if not dry_run:
                        print(f"\n💡 Deployment files available at: {work_dir}")
                        print("   You can manually deploy from this location")

                    return 0

        except Exception as e:
            print(f"✗ Deployment failed: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

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

    def status(self, args) -> int:
        """Show deployment status for project"""
        try:
            project_slug = args.slug
            project = self.get_project_or_exit(project_slug)

            print(f"\n📊 Deployment Status: {project_slug}\n")

            # Check for deployment targets
            targets = self.query_all("""
                SELECT target_name, target_type, provider, host
                FROM deployment_targets
                WHERE project_id = ?
                ORDER BY target_name
            """, (project['id'],))

            if targets:
                print("🎯 Deployment Targets:")
                for target in targets:
                    print(f"   • {target['target_name']} ({target['target_type']})")
                    print(f"     Provider: {target['provider'] or 'unknown'}")
                    if target['host']:
                        print(f"     Host: {target['host']}")
                print()
            else:
                print("⚠️  No deployment targets configured")
                print("   Use: ./templedb target add <project> <target_name> ...\n")

            # Check for deployment script
            deploy_files = self.query_all("""
                SELECT file_path
                FROM files_with_types_view
                WHERE project_slug = ? AND file_path LIKE '%deploy%'
                ORDER BY file_path
            """, (project_slug,))

            if deploy_files:
                print("📜 Deployment Scripts:")
                for file in deploy_files:
                    print(f"   • {file['file_path']}")
                print()
            else:
                print("⚠️  No deployment scripts found\n")

            # Check for migrations
            result = self.query_one("""
                SELECT COUNT(*) as count
                FROM files_with_types_view
                WHERE project_slug = ? AND type_name = 'sql_migration'
            """, (project_slug,))

            migration_count = result['count'] if result else 0
            print(f"🗄️  Database Migrations: {migration_count}")

            # Check for edge functions
            result = self.query_one("""
                SELECT COUNT(*) as count
                FROM files_with_types_view
                WHERE project_slug = ? AND file_path LIKE '%/functions/%index.ts'
            """, (project_slug,))

            function_count = result['count'] if result else 0
            print(f"⚡ Edge Functions: {function_count}")

            # Check for service files
            result = self.query_one("""
                SELECT COUNT(*) as count
                FROM files_with_types_view
                WHERE project_slug = ? AND file_path LIKE '%.service'
            """, (project_slug,))

            service_count = result['count'] if result else 0
            print(f"🔧 Services: {service_count}")

            print()
            return 0

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
    run_parser.add_argument('--skip-group', action='append', help='Skip specific deployment group(s)')
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
