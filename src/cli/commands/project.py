#!/usr/bin/env python3
"""
Project management commands
"""
import sys
import os
import subprocess
from pathlib import Path
from typing import Optional

# Import will be resolved at runtime
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from cli.commands.checkout import CheckoutCommand
from cli.commands.commit import CommitCommand
from repositories import ProjectRepository, FileRepository
from project_context import ProjectContext, get_project_context
from logger import get_logger

logger = get_logger(__name__)


class ProjectCommands(Command):
    """Project management command handlers"""

    def __init__(self):
        super().__init__()
        """Initialize with service context"""
        from services.context import ServiceContext
        self.ctx = ServiceContext()
        self.service = self.ctx.get_project_service()

        # Keep repositories for backward compatibility with methods not yet refactored
        self.project_repo = self.ctx.project_repo
        self.file_repo = self.ctx.file_repo

    def init_project(self, args) -> int:
        """Initialize current directory as a TempleDB project"""
        from error_handler import ValidationError

        project_path = Path(os.getcwd()).resolve()

        try:
            result = self.service.init_project(
                project_path=project_path,
                slug=args.slug,
                name=args.name
            )

            print(f"✅ Initialized TempleDB project: {result['slug']}")
            print(f"   Project root: {result['root']}")
            print(f"   .templedb marker created")
            print()
            print("Next steps:")
            print(f"   templedb sync      # Scan and import files")
            print(f"   templedb status    # Show current project status")

            return 0

        except ValidationError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"{e.solution}")
            return 1
        except Exception as e:
            logger.error(f"Failed to initialize project: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def import_project(self, args) -> int:
        """Import a project from filesystem into database"""
        from error_handler import ValidationError

        try:
            project_path = Path(args.path).resolve()
            dry_run = hasattr(args, 'dry_run') and args.dry_run

            stats = self.service.import_project(
                project_path=project_path,
                slug=args.slug,
                dry_run=dry_run
            )

            print(f"\n📈 Import Statistics:")
            print(f"   Files scanned: {stats.total_files_scanned}")
            print(f"   Files imported: {stats.files_imported}")
            print(f"   Content stored: {stats.content_stored}")
            print(f"   Versions created: {stats.versions_created}")
            print(f"   SQL objects: {stats.sql_objects_found}")

            return 0

        except ValidationError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"{e.solution}")
            return 1
        except Exception as e:
            logger.error(f"Import failed: {e}", exc_info=True)
            return 1

    def list_projects(self, args) -> int:
        """List all projects"""
        projects = self.service.get_all()

        if not projects:
            print("No projects found")
            return 0

        # Format as table
        print(self.format_table(
            projects,
            ['slug', 'name', 'file_count', 'total_lines'],
            title="Projects"
        ))
        return 0

    def show_project(self, args) -> int:
        """Show detailed project information"""
        from error_handler import ResourceNotFoundError

        try:
            project = self.service.get_by_slug(args.slug, required=True)

            print(f"\nProject: {project['slug']}")
            print(f"Name: {project['name']}")
            print(f"Repository: {project.get('repo_url', 'N/A')}")
            print(f"Branch: {project.get('git_branch', 'N/A')}")

            # Get file statistics
            stats = self.service.get_statistics(project['id'])

            if stats:
                print(f"\nFiles: {stats['file_count']}")
                print(f"Lines of code: {stats['total_lines']:,}")
                print(f"File types: {stats['file_types']}")

            # Get VCS info
            vcs_info = self.service.get_vcs_info(project['id'])

            if vcs_info and vcs_info['branch_count'] > 0:
                print(f"\nVCS Branches: {vcs_info['branch_count']}")
                print(f"VCS Commits: {vcs_info['commit_count']}")

            print()
            return 0

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"{e.solution}")
            return 1

    def sync_project(self, args) -> int:
        """Re-import project from filesystem"""
        # If no slug provided, try CWD-based discovery
        if hasattr(args, 'slug') and args.slug:
            slug = args.slug
            project = self.project_repo.get_by_slug(slug)
            if not project:
                logger.error(f"Project '{slug}' not found")
                return 1

            repo_path = project.get('repo_url')
            if not repo_path or not Path(repo_path).exists():
                logger.error(f"Project path not found: {repo_path}")
                return 1
        else:
            # CWD-based discovery
            ctx = get_project_context(required=True)
            slug = ctx.slug
            repo_path = str(ctx.root)
            logger.info(f"Discovered project from CWD: {slug}")

        logger.info(f"Syncing {slug} from {repo_path}...")

        # Use Python importer
        try:
            from importer import ProjectImporter

            importer = ProjectImporter(slug, repo_path, dry_run=False)
            stats = importer.import_files()

            print(f"\n📈 Import Statistics:")
            print(f"   Files scanned: {stats.total_files_scanned}")
            print(f"   Files imported: {stats.files_imported}")
            print(f"   Content stored: {stats.content_stored}")
            print(f"   Versions created: {stats.versions_created}")
            print(f"   SQL objects: {stats.sql_objects_found}")

            return 0
        except Exception as e:
            logger.error(f"Sync failed: {e}", exc_info=True)
            return 1

    def remove_project(self, args) -> int:
        """Remove a project from database"""
        from error_handler import ResourceNotFoundError

        try:
            # Verify project exists
            project = self.service.get_by_slug(args.slug, required=True)

            if not args.force:
                response = input(f"Remove project '{args.slug}' and all its data? (yes/no): ")
                if response.lower() != 'yes':
                    print("Cancelled")
                    return 0

            # Delete project via service
            self.service.delete_project(args.slug)
            logger.info(f"Removed project: {args.slug}")
            return 0

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"{e.solution}")
            return 1

    def generate_envrc(self, args) -> int:
        """Generate .envrc file for a project"""
        project = self.project_repo.get_by_slug(args.slug)
        if not project:
            logger.error(f"Project '{args.slug}' not found")
            return 1

        repo_url = project.get('repo_url')
        if not repo_url:
            logger.error(f"Project '{args.slug}' has no repo_url set")
            return 1

        project_path = Path(repo_url)
        if not project_path.exists():
            logger.error(f"Project path does not exist: {project_path}")
            return 1

        envrc_path = project_path / ".envrc"

        if envrc_path.exists() and not args.force:
            logger.info(f"✓ .envrc already exists at {envrc_path}")
            logger.info("  Use --force to overwrite")
            return 0

        # Standard .envrc content that calls templedb direnv
        # Use absolute path to templedb for reliability
        import os
        templedb_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', 'templedb'))
        envrc_content = f'eval "$({templedb_path} direnv)"\n'

        envrc_path.write_text(envrc_content)
        logger.info(f"✅ Generated .envrc at {envrc_path}")
        return 0


def register(cli):
    """Register project commands with CLI"""
    cmd = ProjectCommands()

    # Create project command group
    project_parser = cli.register_command(
        'project',
        None,  # No handler for parent
        help_text='Project management'
    )
    subparsers = project_parser.add_subparsers(dest='project_subcommand', required=True)

    # project init
    init_parser = subparsers.add_parser('init', help='Initialize current directory as TempleDB project')
    init_parser.add_argument('--slug', help='Project slug (default: directory name)')
    init_parser.add_argument('--name', help='Project name (default: slug)')
    cli.commands['project.init'] = cmd.init_project

    # project import
    import_parser = subparsers.add_parser('import', help='Import project from filesystem')
    import_parser.add_argument('path', help='Path to project directory')
    import_parser.add_argument('--slug', help='Project slug (default: directory name)')
    import_parser.add_argument('--dry-run', action='store_true', help='Dry run (no changes)')
    cli.commands['project.import'] = cmd.import_project

    # project list
    list_parser = subparsers.add_parser('list', help='List all projects', aliases=['ls'])
    cli.commands['project.list'] = cmd.list_projects
    cli.commands['project.ls'] = cmd.list_projects

    # project show
    show_parser = subparsers.add_parser('show', help='Show project details')
    show_parser.add_argument('slug', help='Project slug')
    cli.commands['project.show'] = cmd.show_project

    # project sync
    sync_parser = subparsers.add_parser('sync', help='Re-import project from filesystem')
    sync_parser.add_argument('slug', nargs='?', help='Project slug (optional, uses CWD if omitted)')
    cli.commands['project.sync'] = cmd.sync_project

    # project rm
    rm_parser = subparsers.add_parser('rm', help='Remove project from database')
    rm_parser.add_argument('slug', help='Project slug')
    rm_parser.add_argument('--force', '-f', action='store_true', help='Skip confirmation')
    cli.commands['project.rm'] = cmd.remove_project

    # project generate-envrc
    envrc_parser = subparsers.add_parser('generate-envrc', help='Generate .envrc file for project')
    envrc_parser.add_argument('slug', help='Project slug')
    envrc_parser.add_argument('--force', '-f', action='store_true', help='Overwrite existing .envrc')
    cli.commands['project.generate-envrc'] = cmd.generate_envrc

    # project checkout
    checkout_cmd = CheckoutCommand()
    checkout_parser = subparsers.add_parser('checkout', help='Checkout project to filesystem')
    checkout_parser.add_argument('project_slug', help='Project slug')
    checkout_parser.add_argument('target_dir', help='Target directory for checkout')
    checkout_parser.add_argument('--force', '-f', action='store_true', help='Overwrite existing directory')
    checkout_parser.add_argument('--writable', '-w', action='store_true', help='Make checkout writable (default: read-only)')
    cli.commands['project.checkout'] = checkout_cmd.checkout

    # project checkout-list
    checkout_list_parser = subparsers.add_parser('checkout-list', help='List active checkouts')
    checkout_list_parser.add_argument('project_slug', nargs='?', help='Project slug (optional, lists all if omitted)')
    cli.commands['project.checkout-list'] = checkout_cmd.list_checkouts

    # project checkout-cleanup
    checkout_cleanup_parser = subparsers.add_parser('checkout-cleanup', help='Remove stale checkouts')
    checkout_cleanup_parser.add_argument('project_slug', nargs='?', help='Project slug (optional, cleans all if omitted)')
    checkout_cleanup_parser.add_argument('--force', '-f', action='store_true', help='Skip confirmation')
    cli.commands['project.checkout-cleanup'] = checkout_cmd.cleanup_checkouts

    # project checkout-status
    checkout_status_parser = subparsers.add_parser('checkout-status', help='Show checkout status')
    checkout_status_parser.add_argument('project_slug', help='Project slug')
    checkout_status_parser.add_argument('checkout_path', help='Checkout directory path')
    cli.commands['project.checkout-status'] = checkout_cmd.status

    # project checkout-pull
    checkout_pull_parser = subparsers.add_parser('checkout-pull', help='Pull latest changes to checkout')
    checkout_pull_parser.add_argument('project_slug', help='Project slug')
    checkout_pull_parser.add_argument('checkout_path', help='Checkout directory path')
    cli.commands['project.checkout-pull'] = checkout_cmd.pull

    # project checkout-diff
    checkout_diff_parser = subparsers.add_parser('checkout-diff', help='Show diff between checkout and database')
    checkout_diff_parser.add_argument('project_slug', help='Project slug')
    checkout_diff_parser.add_argument('checkout_path', help='Checkout directory path')
    checkout_diff_parser.add_argument('file', nargs='?', help='File pattern to diff (optional)')
    cli.commands['project.checkout-diff'] = checkout_cmd.diff

    # project commit
    commit_cmd = CommitCommand()
    commit_parser = subparsers.add_parser('commit', help='Commit workspace changes to database')
    commit_parser.add_argument('project_slug', help='Project slug')
    commit_parser.add_argument('workspace_dir', help='Workspace directory')
    commit_parser.add_argument('-m', '--message', required=True, help='Commit message')
    commit_parser.add_argument('--force', '-f', action='store_true', help='Force commit, overwrite conflicts')
    commit_parser.add_argument('--strategy', choices=['abort', 'force', 'rebase'], help='Conflict resolution strategy')

    # Metadata options
    commit_parser.add_argument('--interactive', '-i', action='store_true', help='Interactive mode for rich metadata')
    commit_parser.add_argument('--intent', help='High-level intent/purpose of the commit')
    commit_parser.add_argument('--type', choices=['feature', 'bugfix', 'refactor', 'docs', 'test', 'chore', 'perf', 'style'], help='Type of change')
    commit_parser.add_argument('--scope', help='Scope/area of codebase affected')
    commit_parser.add_argument('--breaking', action='store_true', help='Mark as breaking change')
    commit_parser.add_argument('--impact', choices=['low', 'medium', 'high', 'critical'], help='Impact level')
    commit_parser.add_argument('--ai-assisted', action='store_true', help='Mark as AI-assisted')
    commit_parser.add_argument('--ai-tool', help='AI tool used (e.g., Claude, GPT-4)')
    commit_parser.add_argument('--confidence', choices=['low', 'medium', 'high'], help='Confidence level')
    commit_parser.add_argument('--tags', help='Comma-separated tags')

    cli.commands['project.commit'] = commit_cmd.commit
