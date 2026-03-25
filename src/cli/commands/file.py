#!/usr/bin/env python3
"""
File management commands for TempleDB
"""
import sys
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from repositories import ProjectRepository, FileRepository
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class FileCommands(Command):
    """File command handlers"""

    def __init__(self):
        """Initialize with service context"""
        super().__init__()
        from services.context import ServiceContext
        self.ctx = ServiceContext()
        self.project_repo = self.ctx.project_repo
        self.file_repo = FileRepository()

    def show(self, args) -> int:
        """Show file content from TempleDB"""
        try:
            # Get project
            project = self.project_repo.get_project(args.project)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            # Get file content
            file_record = self.file_repo.get_file_by_path(project['id'], args.file_path)
            if not file_record:
                logger.error(f"File '{args.file_path}' not found in project '{args.project}'")
                return 1

            # Read and display content
            content = self._read_file_content(project, file_record)
            if content is None:
                logger.error(f"Could not read file content")
                return 1

            print(content, end='')
            return 0

        except Exception as e:
            logger.error(f"Failed to show file: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def edit(self, args) -> int:
        """Edit file from TempleDB in $EDITOR"""
        try:
            # Get project
            project = self.project_repo.get_project(args.project)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            # Get file content
            file_record = self.file_repo.get_file_by_path(project['id'], args.file_path)
            if not file_record:
                logger.error(f"File '{args.file_path}' not found in project '{args.project}'")
                return 1

            # Get full path to actual file
            repo_path = project.get('repo_url', '').replace('file://', '')
            if not repo_path:
                logger.error(f"Project path not set for '{args.project}'")
                return 1

            full_path = Path(repo_path) / args.file_path

            if not full_path.exists():
                logger.error(f"File does not exist on filesystem: {full_path}")
                return 1

            # Open in editor
            editor = os.environ.get('EDITOR', 'vi')
            try:
                subprocess.run([editor, str(full_path)], check=True)
                print(f"✓ Edited {args.file_path}")
                return 0
            except subprocess.CalledProcessError as e:
                logger.error(f"Editor exited with error: {e}")
                return 1

        except Exception as e:
            logger.error(f"Failed to edit file: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def checkout(self, args) -> int:
        """Checkout file from TempleDB to working directory or specified path"""
        try:
            # Get project
            project = self.project_repo.get_project(args.project)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            # Get file content
            file_record = self.file_repo.get_file_by_path(project['id'], args.file_path)
            if not file_record:
                logger.error(f"File '{args.file_path}' not found in project '{args.project}'")
                return 1

            # Determine target path
            if hasattr(args, 'output') and args.output:
                target_path = Path(args.output)
            else:
                repo_path = project.get('repo_url', '').replace('file://', '')
                if not repo_path:
                    logger.error(f"Project path not set for '{args.project}'")
                    return 1
                target_path = Path(repo_path) / args.file_path

            # Create parent directories if needed
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Read content
            content = self._read_file_content(project, file_record)
            if content is None:
                logger.error(f"Could not read file content")
                return 1

            # Write to target
            target_path.write_text(content)
            print(f"✓ Checked out {args.file_path} to {target_path}")
            return 0

        except Exception as e:
            logger.error(f"Failed to checkout file: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def cat(self, args) -> int:
        """Alias for show command"""
        return self.show(args)

    def get(self, args) -> int:
        """Get file content as string (alias for show, more explicit for programmatic use)"""
        return self.show(args)

    def set(self, args) -> int:
        """Set file content from string (stdin or --content)"""
        try:
            # Get project
            project = self.project_repo.get_project(args.project)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            # Get content from stdin or --content
            if hasattr(args, 'content') and args.content:
                content = args.content
            else:
                # Read from stdin
                import sys
                content = sys.stdin.read()

            if not content:
                logger.error("No content provided (use --content or pipe to stdin)")
                return 1

            # Determine target path
            repo_path = project.get('repo_url', '').replace('file://', '')
            if not repo_path:
                logger.error(f"Project path not set for '{args.project}'")
                return 1

            target_path = Path(repo_path) / args.file_path

            # Create parent directories if needed
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Write content
            target_path.write_text(content)

            # If --stage flag, stage the file
            if hasattr(args, 'stage') and args.stage:
                from services.context import ServiceContext
                ctx = ServiceContext()
                ctx.get_vcs_service().stage_files(
                    project_slug=args.project,
                    file_patterns=[args.file_path],
                    stage_all=False
                )
                print(f"✓ Set and staged {args.file_path}")
            else:
                print(f"✓ Set {args.file_path}")

            return 0

        except Exception as e:
            logger.error(f"Failed to set file: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def _read_file_content(self, project: dict, file_record: dict) -> Optional[str]:
        """Read file content from filesystem"""
        try:
            repo_path = project.get('repo_url', '').replace('file://', '')
            if not repo_path:
                return None

            file_path = Path(repo_path) / file_record['file_path']
            if not file_path.exists():
                return None

            return file_path.read_text()

        except Exception as e:
            logger.debug(f"Error reading file content: {e}")
            return None


def register(cli):
    """Register file commands with CLI"""
    cmd = FileCommands()

    # Create file command with subparsers
    file_parser = cli.subparsers.add_parser(
        'file',
        help='File management commands'
    )
    file_subparsers = file_parser.add_subparsers(dest='file_command', required=True)

    # file show
    show_parser = file_subparsers.add_parser(
        'show',
        help='Show file content'
    )
    show_parser.add_argument('project', help='Project name or slug')
    show_parser.add_argument('file_path', help='Path to file within project')
    cli.commands['file.show'] = cmd.show

    # file edit
    edit_parser = file_subparsers.add_parser(
        'edit',
        help='Edit file in $EDITOR'
    )
    edit_parser.add_argument('project', help='Project name or slug')
    edit_parser.add_argument('file_path', help='Path to file within project')
    cli.commands['file.edit'] = cmd.edit

    # file checkout
    checkout_parser = file_subparsers.add_parser(
        'checkout',
        help='Checkout file to working directory or specified path'
    )
    checkout_parser.add_argument('project', help='Project name or slug')
    checkout_parser.add_argument('file_path', help='Path to file within project')
    checkout_parser.add_argument('-o', '--output', help='Output path (default: project working directory)')
    cli.commands['file.checkout'] = cmd.checkout

    # file cat (alias for show)
    cat_parser = file_subparsers.add_parser(
        'cat',
        help='Show file content (alias for show)'
    )
    cat_parser.add_argument('project', help='Project name or slug')
    cat_parser.add_argument('file_path', help='Path to file within project')
    cli.commands['file.cat'] = cmd.cat

    # file get (programmatic alias for show)
    get_parser = file_subparsers.add_parser(
        'get',
        help='Get file content as string (for programmatic use)'
    )
    get_parser.add_argument('project', help='Project name or slug')
    get_parser.add_argument('file_path', help='Path to file within project')
    cli.commands['file.get'] = cmd.get

    # file set (set content from string)
    set_parser = file_subparsers.add_parser(
        'set',
        help='Set file content from string (stdin or --content)'
    )
    set_parser.add_argument('project', help='Project name or slug')
    set_parser.add_argument('file_path', help='Path to file within project')
    set_parser.add_argument('-c', '--content', help='Content to write (otherwise reads from stdin)')
    set_parser.add_argument('-s', '--stage', action='store_true', help='Stage file after writing')
    cli.commands['file.set'] = cmd.set
