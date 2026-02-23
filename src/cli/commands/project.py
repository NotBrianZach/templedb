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
from db_utils import query_one, query_all, execute, get_connection
from cli.core import Command
from cli.commands.checkout import CheckoutCommand
from cli.commands.commit import CommitCommand


class ProjectCommands(Command):
    """Project management command handlers"""

    def import_project(self, args) -> int:
        """Import a project from filesystem into database"""
        project_path = Path(args.path).resolve()

        if not project_path.exists():
            print(f"Error: Path does not exist: {project_path}", file=sys.stderr)
            return 1

        if not project_path.is_dir():
            print(f"Error: Path is not a directory: {project_path}", file=sys.stderr)
            return 1

        # Determine slug
        slug = args.slug if args.slug else project_path.name

        # Check if project exists, create if not
        project = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))

        if not project:
            # Create project
            print(f"Creating new project: {slug}")
            execute("""
                INSERT INTO projects (slug, name, repo_url, git_branch, status)
                VALUES (?, ?, ?, 'main', 'active')
            """, (slug, slug, str(project_path)))
            print(f"✓ Created project '{slug}'")
        else:
            print(f"Updating existing project: {slug}")

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
            print(f"✗ Import failed: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    def list_projects(self, args) -> int:
        """List all projects"""
        projects = query_all("""
            SELECT
                p.slug,
                p.name,
                COUNT(pf.id) as file_count,
                SUM(pf.lines_of_code) as total_lines
            FROM projects p
            LEFT JOIN project_files pf ON p.id = pf.project_id
            GROUP BY p.id
            ORDER BY p.slug
        """)

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
        project = self.get_project_or_exit(args.slug)

        print(f"\nProject: {project['slug']}")
        print(f"Name: {project['name']}")
        print(f"Repository: {project.get('repo_url', 'N/A')}")
        print(f"Branch: {project.get('git_branch', 'N/A')}")

        # Get file statistics
        stats = query_one("""
            SELECT
                COUNT(*) as file_count,
                SUM(lines_of_code) as total_lines,
                COUNT(DISTINCT file_type_id) as file_types
            FROM project_files
            WHERE project_id = ?
        """, (project['id'],))

        if stats:
            print(f"\nFiles: {stats['file_count']}")
            print(f"Lines of code: {stats['total_lines']:,}")
            print(f"File types: {stats['file_types']}")

        # Get VCS info
        vcs_info = query_one("""
            SELECT
                COUNT(DISTINCT vb.id) as branch_count,
                COUNT(DISTINCT vc.id) as commit_count
            FROM vcs_branches vb
            LEFT JOIN vcs_commits vc ON vb.id = vc.branch_id
            WHERE vb.project_id = ?
        """, (project['id'],))

        if vcs_info and vcs_info['branch_count'] > 0:
            print(f"\nVCS Branches: {vcs_info['branch_count']}")
            print(f"VCS Commits: {vcs_info['commit_count']}")

        print()
        return 0

    def sync_project(self, args) -> int:
        """Re-import project from filesystem"""
        project = self.get_project_or_exit(args.slug)

        repo_path = project.get('repo_url')
        if not repo_path or not Path(repo_path).exists():
            print(f"Error: Project path not found: {repo_path}", file=sys.stderr)
            return 1

        print(f"Syncing {args.slug} from {repo_path}...")

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
            print(f"✗ Sync failed: {e}", file=sys.stderr)
            return 1

    def remove_project(self, args) -> int:
        """Remove a project from database"""
        project = self.get_project_or_exit(args.slug)

        if not args.force:
            response = input(f"Remove project '{args.slug}' and all its data? (yes/no): ")
            if response.lower() != 'yes':
                print("Cancelled")
                return 0

        # Delete project (cascade will handle related records)
        execute("DELETE FROM projects WHERE id = ?", (project['id'],))
        print(f"✓ Removed project: {args.slug}")
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
    cli.commands['project.commit'] = commit_cmd.commit
