#!/usr/bin/env python3
"""
File management commands for TempleDB

These commands read/write directly from the TempleDB database,
bypassing the FUSE mount. Use these when the FUSE mount is down
or for programmatic access.
"""
import sys
import os
import subprocess
import tempfile
import hashlib
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from repositories import ProjectRepository, FileRepository
from cli.core import Command
from cli.fuzzy_matcher import fuzzy_match_project, fuzzy_match_file
from logger import get_logger

logger = get_logger(__name__)


class FileCommands(Command):
    """File command handlers — all reads/writes go through the DB, not the filesystem."""

    def __init__(self):
        """Initialize with service context"""
        super().__init__()
        from services.context import ServiceContext
        self.ctx = ServiceContext()
        self.project_repo = self.ctx.project_repo
        self.file_repo = FileRepository()

    def show(self, args) -> int:
        """Show file content from TempleDB database"""
        try:
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            file_record = fuzzy_match_file(project['id'], args.file_path, show_matched=True)
            if not file_record:
                logger.error(f"File '{args.file_path}' not found in project '{args.project}'")
                return 1

            content = self._read_content_from_db(file_record)
            if content is None:
                logger.error(f"Could not read file content from database")
                return 1

            print(content, end='')
            return 0

        except Exception as e:
            logger.error(f"Failed to show file: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def edit(self, args) -> int:
        """Edit file — reads from DB, writes back to DB"""
        try:
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            file_record = fuzzy_match_file(project['id'], args.file_path, show_matched=True)
            if not file_record:
                logger.error(f"File '{args.file_path}' not found in project '{args.project}'")
                return 1

            content = self._read_content_from_db(file_record)
            if content is None:
                logger.error(f"Could not read file content from database")
                return 1

            # Write to temp file for editing
            suffix = Path(file_record['file_path']).suffix or '.txt'
            with tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False) as tf:
                tf.write(content)
                tmp_path = tf.name

            try:
                editor = os.environ.get('EDITOR', 'vi')
                subprocess.run([editor, tmp_path], check=True)

                # Read back and write to DB if changed
                new_content = Path(tmp_path).read_text()
                if new_content != content:
                    self._write_content_to_db(project['id'], args.project,
                                              file_record['file_path'], new_content)
                    print(f"✓ Edited and saved {file_record['file_path']} to database")
                else:
                    print(f"No changes made to {file_record['file_path']}")
                return 0
            except subprocess.CalledProcessError as e:
                logger.error(f"Editor exited with error: {e}")
                return 1
            finally:
                os.unlink(tmp_path)

        except Exception as e:
            logger.error(f"Failed to edit file: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def checkout(self, args) -> int:
        """Checkout file from TempleDB database to a local path"""
        try:
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

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

            # Read content from DB
            content = self._read_content_from_db(file_record)
            if content is None:
                logger.error(f"Could not read file content from database")
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
        """Set file content directly in the database"""
        try:
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            # Get content from --content flag or stdin
            if hasattr(args, 'content') and args.content:
                content = args.content
            else:
                content = sys.stdin.read()

            if not content:
                logger.error("No content provided (use --content or pipe to stdin)")
                return 1

            self._write_content_to_db(project['id'], args.project, args.file_path, content)

            # If --stage flag, stage the file
            if hasattr(args, 'stage') and args.stage:
                self.ctx.get_vcs_service().stage_files(
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

    def ls(self, args) -> int:
        """List files in a project from the database"""
        try:
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            files = self.file_repo.get_files_for_project(project['id'])
            if not files:
                print(f"No files found in project '{args.project}'")
                return 0

            # Filter by path prefix if provided
            prefix = getattr(args, 'path', None)

            for f in files:
                fp = f['file_path']
                if prefix and not fp.startswith(prefix):
                    continue
                if getattr(args, 'long', False):
                    size = f.get('lines_of_code', 0) or 0
                    print(f"{size:>6} loc  {fp}")
                else:
                    print(fp)

            return 0

        except Exception as e:
            logger.error(f"Failed to list files: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def _read_content_from_db(self, file_record: dict) -> Optional[str]:
        """Read file content directly from the TempleDB database (content_blobs)."""
        try:
            file_id = file_record.get('file_id') or file_record.get('id')
            if not file_id:
                return None

            content_row = self.file_repo.get_file_content(file_id)
            if not content_row:
                return None

            if content_row.get('content_text') is not None:
                return content_row['content_text']
            elif content_row.get('content_blob') is not None:
                # Try to decode binary content
                try:
                    return bytes(content_row['content_blob']).decode('utf-8')
                except UnicodeDecodeError:
                    logger.error("File contains binary content, cannot display as text")
                    return None
            return ""

        except Exception as e:
            logger.debug(f"Error reading content from DB: {e}")
            return None

    def _write_content_to_db(self, project_id: int, project_slug: str,
                             file_path: str, content: str):
        """Write file content directly to the TempleDB database."""
        from repositories.base import BaseRepository
        base = BaseRepository()

        content_bytes = content.encode('utf-8')
        content_hash = hashlib.sha256(content_bytes).hexdigest()
        line_count = content.count('\n') + 1 if content else 0

        # Upsert content blob
        base.execute("""
            INSERT OR IGNORE INTO content_blobs
            (hash_sha256, content_text, content_blob, content_type, encoding,
             file_size_bytes, reference_count)
            VALUES (?, ?, NULL, 'text', 'utf-8', ?, 1)
        """, (content_hash, content, len(content_bytes)))

        # Check if file exists
        file_record = self.file_repo.get_file_by_path(project_id, file_path)
        if file_record:
            file_id = file_record.get('id') or file_record.get('file_id')
            # Update file_contents
            base.execute("""
                INSERT INTO file_contents (file_id, content_hash, file_size_bytes, line_count, is_current)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(file_id, is_current) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    file_size_bytes = excluded.file_size_bytes,
                    line_count = excluded.line_count,
                    updated_at = datetime('now')
            """, (file_id, content_hash, len(content_bytes), line_count))
        else:
            # Create new file
            file_name = file_path.rsplit("/", 1)[-1]
            ext = Path(file_path).suffix.lstrip(".").lower()
            ext_to_type = {
                "py": "python_script", "js": "javascript", "ts": "typescript",
                "nix": "nix", "sql": "sql_file", "sh": "shell_script",
                "md": "markdown", "json": "json", "yaml": "yaml", "yml": "yaml",
                "toml": "toml", "html": "html", "css": "css", "txt": "text_file",
            }
            type_name = ext_to_type.get(ext)
            ft_row = None
            if type_name:
                ft_row = base.query_one(
                    "SELECT id FROM file_types WHERE type_name = ? LIMIT 1", (type_name,))
            if not ft_row:
                ft_row = base.query_one("SELECT id FROM file_types LIMIT 1")
            file_type_id = ft_row['id'] if ft_row else 1

            cursor = base.execute("""
                INSERT INTO project_files (project_id, file_type_id, file_path, file_name,
                                           status, lines_of_code, last_modified)
                VALUES (?, ?, ?, ?, 'active', ?, datetime('now'))
            """, (project_id, file_type_id, file_path, file_name, line_count))
            file_id = cursor.lastrowid

            base.execute("""
                INSERT INTO file_contents (file_id, content_hash, file_size_bytes, line_count, is_current)
                VALUES (?, ?, ?, ?, 1)
            """, (file_id, content_hash, len(content_bytes), line_count))

        # Auto-stage
        try:
            branch = base.query_one(
                "SELECT active_branch_id as id FROM projects WHERE id = ? AND active_branch_id IS NOT NULL",
                (project_id,))
            if not branch:
                branch = base.query_one(
                    "SELECT id FROM vcs_branches WHERE project_id = ? AND is_default = 1 LIMIT 1",
                    (project_id,))
            if branch:
                change_state = "modified" if file_record else "added"
                base.execute("""
                    INSERT INTO vcs_working_state (project_id, branch_id, file_id, state, staged, last_modified)
                    VALUES (?, ?, ?, ?, 1, datetime('now'))
                    ON CONFLICT (project_id, branch_id, file_id)
                    DO UPDATE SET state = excluded.state, staged = 1, last_modified = datetime('now')
                """, (project_id, branch['id'], file_id, change_state))
        except Exception as e:
            logger.debug(f"Auto-stage failed (non-fatal): {e}")


def register(cli):
    """Register file commands with CLI"""
    cmd = FileCommands()

    # Create file command with subparsers
    file_parser = cli.subparsers.add_parser(
        'file',
        help='File management commands'
    )
    file_subparsers = file_parser.add_subparsers(dest='file_subcommand', required=True)

    # file show
    show_parser = file_subparsers.add_parser(
        'show',
        help='Show file content'
    )
    show_parser.add_argument('project', help='Project name or pattern')
    show_parser.add_argument('file_path', help='File path or pattern (fuzzy matching enabled)')
    cli.commands['file.show'] = cmd.show

    # file edit
    edit_parser = file_subparsers.add_parser(
        'edit',
        help='Edit file in $EDITOR'
    )
    edit_parser.add_argument('project', help='Project name or pattern')
    edit_parser.add_argument('file_path', help='File path or pattern (fuzzy matching enabled)')
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
    cat_parser.add_argument('project', help='Project name or pattern')
    cat_parser.add_argument('file_path', help='File path or pattern (fuzzy matching enabled)')
    cli.commands['file.cat'] = cmd.cat

    # file get (programmatic alias for show)
    get_parser = file_subparsers.add_parser(
        'get',
        help='Get file content as string (for programmatic use)'
    )
    get_parser.add_argument('project', help='Project name or pattern')
    get_parser.add_argument('file_path', help='File path or pattern (fuzzy matching enabled)')
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

    # file ls (list files)
    ls_parser = file_subparsers.add_parser(
        'ls',
        help='List files in a project'
    )
    ls_parser.add_argument('project', help='Project name or pattern')
    ls_parser.add_argument('path', nargs='?', help='Optional path prefix to filter by')
    ls_parser.add_argument('-l', '--long', action='store_true', help='Show detailed info (lines of code)')
    cli.commands['file.ls'] = cmd.ls
