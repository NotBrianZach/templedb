#!/usr/bin/env python3
"""
Project management commands
"""
import sys
import subprocess
from pathlib import Path
from typing import Optional

# Import will be resolved at runtime
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from cli.commands.checkout import CheckoutCommand
from cli.commands.commit import CommitCommand
from repositories import ProjectRepository, FileRepository
from logger import get_logger

logger = get_logger(__name__)


class ProjectCommands(Command):
    """Project management command handlers"""

    def __init__(self):
        super().__init__()
        """Initialize with repositories"""
        self.project_repo = ProjectRepository()
        self.file_repo = FileRepository()

    def import_project(self, args) -> int:
        """Import a project from filesystem into database"""
        project_path = Path(args.path).resolve()

        if not project_path.exists():
            logger.error(f"Path does not exist: {project_path}")
            return 1

        if not project_path.is_dir():
            logger.error(f"Path is not a directory: {project_path}")
            return 1

        # Determine slug
        slug = args.slug if args.slug else project_path.name

        # Check if project exists, create if not
        project = self.project_repo.get_by_slug(slug)

        if not project:
            # Create project
            logger.info(f"Creating new project: {slug}")
            self.project_repo.create(
                slug=slug,
                name=slug,
                repo_url=str(project_path),
                git_branch='main'
            )
            logger.info(f"Created project '{slug}'")
        else:
            logger.info(f"Updating existing project: {slug}")

        # Use Python importer
        try:
            from importer import ProjectImporter

            dry_run = hasattr(args, 'dry_run') and args.dry_run
            importer = ProjectImporter(slug, str(project_path), dry_run=dry_run)
            stats = importer.import_files()

            print(f"\n📈 Import Statistics:")
            print(f"   Files scanned: {stats.total_files_scanned}")
            print(f"   Files imported: {stats.files_imported}")
            print(f"   Content stored: {stats.content_stored}")
            print(f"   Versions created: {stats.versions_created}")
            print(f"   SQL objects: {stats.sql_objects_found}")

            return 0
        except Exception as e:
            logger.error(f"Import failed: {e}", exc_info=True)
            return 1

    def list_projects(self, args) -> int:
        """List all projects"""
        projects = self.project_repo.get_all()

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
        project = self.project_repo.get_by_slug(args.slug)
        if not project:
            logger.error(f"Project '{args.slug}' not found")
            return 1

        print(f"\nProject: {project['slug']}")
        print(f"Name: {project['name']}")
        print(f"Repository: {project.get('repo_url', 'N/A')}")
        print(f"Branch: {project.get('git_branch', 'N/A')}")

        # Get file statistics
        stats = self.project_repo.get_statistics(project['id'])

        if stats:
            print(f"\nFiles: {stats['file_count']}")
            print(f"Lines of code: {stats['total_lines']:,}")
            print(f"File types: {stats['file_types']}")

        # Get VCS info
        vcs_info = self.project_repo.get_vcs_info(project['id'])

        if vcs_info and vcs_info['branch_count'] > 0:
            print(f"\nVCS Branches: {vcs_info['branch_count']}")
            print(f"VCS Commits: {vcs_info['commit_count']}")

        print()
        return 0

    def sync_project(self, args) -> int:
        """Re-import project from filesystem"""
        project = self.project_repo.get_by_slug(args.slug)
        if not project:
            logger.error(f"Project '{args.slug}' not found")
            return 1

        repo_path = project.get('repo_url')
        if not repo_path or not Path(repo_path).exists():
            logger.error(f"Project path not found: {repo_path}")
            return 1

        logger.info(f"Syncing {args.slug} from {repo_path}...")

        # Use Python importer
        try:
            from importer import ProjectImporter

            importer = ProjectImporter(args.slug, repo_path, dry_run=False)
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
        project = self.project_repo.get_by_slug(args.slug)
        if not project:
            logger.error(f"Project '{args.slug}' not found")
            return 1

        if not args.force:
            response = input(f"Remove project '{args.slug}' and all its data? (yes/no): ")
            if response.lower() != 'yes':
                print("Cancelled")
                return 0

        # Delete project (cascade will handle related records)
        self.project_repo.delete(project['id'])
        logger.info(f"Removed project: {args.slug}")
        return 0

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
    sync_parser.add_argument('slug', help='Project slug')
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
