#!/usr/bin/env python3
"""
Version control commands
"""
import sys
import hashlib
import time
import difflib
from pathlib import Path
from typing import Optional, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from repositories import ProjectRepository, VCSRepository
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class VCSCommands(Command):
    """VCS command handlers"""

    def __init__(self):
        """Initialize with repositories"""
        super().__init__()  # Initialize base Command class
        self.project_repo = ProjectRepository()
        self.vcs_repo = VCSRepository()

    def _get_author(self) -> str:
        """Get author name from git config or default"""
        import subprocess
        try:
            result = subprocess.run(
                ['git', 'config', 'user.name'],
                capture_output=True,
                text=True,
                timeout=5
            )
            author = result.stdout.strip()
            if author:
                return author
        except Exception:
            pass
        return "unknown"

    def _refresh_working_state(self, project: dict):
        """Refresh VCS working state by detecting changes"""
        from importer import WorkingStateDetector

        repo_url = project.get('repo_url')
        if not repo_url:
            print("   Error: Project path not set", file=sys.stderr)
            return

        detector = WorkingStateDetector(project['slug'], repo_url)
        detector.detect_changes()

    def add(self, args) -> int:
        """Stage files for commit"""
        project = self.get_project_or_exit(args.project)

        # Get default branch
        branches = self.vcs_repo.get_branches(project['id'])
        branch = next((b for b in branches if b.get('is_default')), None)

        if not branch:
            logger.error("No default branch found")
            return 1

        # Handle --all flag
        if hasattr(args, 'all') and args.all:
            # Stage all changes
            self.vcs_repo.execute("""
                UPDATE vcs_working_state
                SET staged = 1
                WHERE project_id = ? AND branch_id = ? AND state != 'unmodified'
            """, (project['id'], branch['id']))

            # Count affected rows
            staged_count = self.vcs_repo.query_one("""
                SELECT COUNT(*) as count FROM vcs_working_state
                WHERE project_id = ? AND branch_id = ? AND staged = 1
            """, (project['id'], branch['id']))

            print(f"✓ Staged {staged_count['count']} file(s)")
            return 0

        # Handle specific files
        if hasattr(args, 'files') and args.files:
            for file_pattern in args.files:
                # Find matching files in working state
                files = self.vcs_repo.query_all("""
                    SELECT ws.id, pf.file_path
                    FROM vcs_working_state ws
                    JOIN project_files pf ON ws.file_id = pf.id
                    WHERE ws.project_id = ? AND ws.branch_id = ?
                    AND pf.file_path LIKE ?
                """, (project['id'], branch['id'], f"%{file_pattern}%"))

                if not files:
                    print(f"   No matching files for: {file_pattern}")
                    continue

                # Stage matching files
                for file in files:
                    self.vcs_repo.execute("""
                        UPDATE vcs_working_state
                        SET staged = 1
                        WHERE id = ?
                    """, (file['id'],))
                    print(f"   ✓ Staged: {file['file_path']}")

            return 0

        logger.error("Specify --all or provide file patterns")
        return 1

    def reset(self, args) -> int:
        """Unstage files"""
        project = self.get_project_or_exit(args.project)

        # Get default branch
        branches = self.vcs_repo.get_branches(project['id'])
        branch = next((b for b in branches if b.get('is_default')), None)

        if not branch:
            logger.error("No default branch found")
            return 1

        # Handle --all flag
        if hasattr(args, 'all') and args.all:
            # Unstage all changes
            self.vcs_repo.execute("""
                UPDATE vcs_working_state
                SET staged = 0
                WHERE project_id = ? AND branch_id = ? AND staged = 1
            """, (project['id'], branch['id']))

            # Count affected rows
            unstaged_count = self.vcs_repo.query_one("""
                SELECT COUNT(*) as count FROM vcs_working_state
                WHERE project_id = ? AND branch_id = ? AND state != 'unmodified'
            """, (project['id'], branch['id']))

            print(f"✓ Unstaged {unstaged_count['count']} file(s)")
            return 0

        # Handle specific files
        if hasattr(args, 'files') and args.files:
            for file_pattern in args.files:
                # Find matching files in working state
                files = self.vcs_repo.query_all("""
                    SELECT ws.id, pf.file_path
                    FROM vcs_working_state ws
                    JOIN project_files pf ON ws.file_id = pf.id
                    WHERE ws.project_id = ? AND ws.branch_id = ?
                    AND ws.staged = 1
                    AND pf.file_path LIKE ?
                """, (project['id'], branch['id'], f"%{file_pattern}%"))

                if not files:
                    print(f"   No staged files matching: {file_pattern}")
                    continue

                # Unstage matching files
                for file in files:
                    self.vcs_repo.execute("""
                        UPDATE vcs_working_state
                        SET staged = 0
                        WHERE id = ?
                    """, (file['id'],))
                    print(f"   ✓ Unstaged: {file['file_path']}")

            return 0

        logger.error("Specify --all or provide file patterns")
        return 1

    def commit(self, args) -> int:
        """Create VCS commit"""
        project = self.get_project_or_exit(args.project)

        # Get branch
        if args.branch:
            branches = self.vcs_repo.get_branches(project['id'])
            branch = next((b for b in branches if b['branch_name'] == args.branch), None)
        else:
            branches = self.vcs_repo.get_branches(project['id'])
            branch = next((b for b in branches if b.get('is_default')), None)

        if not branch:
            logger.error("Branch not found")
            return 1

        # Get staged files with content info
        staged = self.vcs_repo.query_all("""
            SELECT ws.*, fc.content_text, fc.file_size_bytes, fc.line_count
            FROM vcs_working_state ws
            LEFT JOIN file_contents fc ON ws.file_id = fc.file_id
            WHERE ws.project_id = ? AND ws.branch_id = ? AND ws.staged = 1
        """, (project['id'], branch['id']))

        if not staged:
            print("No changes staged for commit")
            return 1

        # Get author
        author = args.author or self._get_author()

        # Generate commit hash
        hash_input = f"{project['slug']}:{branch['branch_name']}:{args.message}:{time.time()}"
        commit_hash = hashlib.sha256(hash_input.encode()).hexdigest()[:16].upper()

        # Create commit
        commit_id = self.vcs_repo.create_commit(
            project_id=project['id'],
            branch_id=branch['id'],
            commit_hash=commit_hash,
            author=author,
            message=args.message
        )

        # Create file states
        for file in staged:
            # Use placeholder values for deleted files
            content_hash = file['content_hash'] or 'DELETED'
            file_size = file.get('file_size_bytes', 0) or 0
            line_count = file.get('line_count')
            content_text = file.get('content_text')

            self.vcs_repo.execute("""
                INSERT INTO vcs_file_states (
                    commit_id, file_id, content_text,
                    content_hash, file_size, line_count, change_type
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (commit_id, file['file_id'], content_text,
                  content_hash, file_size, line_count, file['state']), commit=False)

        # Handle deleted files - remove from project_files and working_state
        deleted_files = [f for f in staged if f['state'] == 'deleted']
        if deleted_files:
            for file in deleted_files:
                self.vcs_repo.execute("DELETE FROM project_files WHERE id = ?", (file['file_id'],), commit=False)
                self.vcs_repo.execute("""
                    DELETE FROM vcs_working_state
                    WHERE file_id = ? AND project_id = ? AND branch_id = ?
                """, (file['file_id'], project['id'], branch['id']), commit=False)

        # Clear staging for remaining files
        self.vcs_repo.execute("""
            UPDATE vcs_working_state
            SET staged = 0, state = 'unmodified'
            WHERE project_id = ? AND branch_id = ? AND staged = 1
        """, (project['id'], branch['id']))

        print(f"✓ Created commit {commit_hash}")
        print(f"  Project: {project['slug']}")
        print(f"  Branch: {branch['branch_name']}")
        print(f"  Author: {author}")
        print(f"  Files: {len(staged)}")
        print(f"  Message: {args.message}")
        return 0

    def status(self, args) -> int:
        """Show working directory status"""
        project = self.get_project_or_exit(args.project)

        # Auto-detect changes if requested or if working state is empty
        if hasattr(args, 'refresh') and args.refresh:
            self._refresh_working_state(project)
        else:
            # Check if working state is populated
            existing = self.vcs_repo.query_one("""
                SELECT COUNT(*) as count FROM vcs_working_state
                WHERE project_id = ?
            """, (project['id'],))

            if not existing or existing['count'] == 0:
                print("🔄 Detecting changes (first time)...")
                self._refresh_working_state(project)

        # Get current branch
        branches = self.vcs_repo.get_branches(project['id'])
        branch = next((b for b in branches if b.get('is_default')), None)

        if branch:
            print(f"On branch: {branch['branch_name']}")

        # Get changes
        changes = self.vcs_repo.query_all("""
            SELECT pf.file_path, ws.state, ws.staged
            FROM vcs_working_state ws
            JOIN project_files pf ON ws.file_id = pf.id
            WHERE ws.project_id = ? AND ws.state != 'unmodified'
            ORDER BY ws.staged DESC, pf.file_path
        """, (project['id'],))

        if not changes:
            print("No changes")
            return 0

        # Staged changes
        staged = [c for c in changes if c['staged']]
        if staged:
            print("\nChanges to be committed:")
            for change in staged:
                state_symbol = {'modified': '📝', 'added': '✨', 'deleted': '🗑️'}.get(change['state'], '❓')
                print(f"  {state_symbol} {change['state']:<10} {change['file_path']}")

        # Unstaged changes
        unstaged = [c for c in changes if not c['staged']]
        if unstaged:
            print("\nChanges not staged for commit:")
            for change in unstaged:
                state_symbol = {'modified': '📝', 'added': '✨', 'deleted': '🗑️'}.get(change['state'], '❓')
                print(f"  {state_symbol} {change['state']:<10} {change['file_path']}")

        print()
        return 0

    def log(self, args) -> int:
        """Show commit history"""
        project = self.get_project_or_exit(args.project)
        limit = args.n if hasattr(args, 'n') and args.n else 10

        # Use VCSRepository's get_commit_history method
        commits = self.vcs_repo.get_commit_history(project['id'], branch_name=None, limit=limit)

        if not commits:
            print("No commits found")
            return 0

        print(f"\nCommit log for {project['slug']}\n")
        for commit in commits:
            print(f"commit {commit['commit_hash']}")
            print(f"Branch: {commit.get('branch_name', 'N/A')}")
            print(f"Author: {commit['author']}")
            print(f"Date:   {commit['commit_timestamp']}")
            print(f"\n    {commit['commit_message']}\n")

        return 0

    def branch(self, args) -> int:
        """List or create branches"""
        project = self.get_project_or_exit(args.project)

        if hasattr(args, 'name') and args.name:
            # Create new branch - get default branch as parent
            branches = self.vcs_repo.get_branches(project['id'])
            parent = next((b for b in branches if b.get('is_default')), None)

            if not parent:
                logger.error("No default branch found")
                return 1

            self.vcs_repo.execute("""
                INSERT INTO vcs_branches (project_id, branch_name, parent_branch_id)
                VALUES (?, ?, ?)
            """, (project['id'], args.name, parent['id']))

            print(f"✓ Created branch: {args.name}")
            return 0
        else:
            # List branches - use query to get summary view data
            branches = self.vcs_repo.query_all("""
                SELECT branch_name, total_commits, last_author, last_message
                FROM vcs_branch_summary_view
                WHERE project_slug = ?
                ORDER BY branch_name
            """, (project['slug'],))

            if not branches:
                print("No branches found")
                return 0

            print(self.format_table(
                branches,
                ['branch_name', 'total_commits', 'last_message'],
                title=f"Branches for {project['slug']}"
            ))
            return 0

    def diff(self, args) -> int:
        """Show diff between file versions"""
        project = self.get_project_or_exit(args.project)

        # Handle --staged flag (show staged changes)
        if hasattr(args, 'staged') and args.staged:
            return self._diff_staged(project, args)

        # Get file
        file_row = self.vcs_repo.query_one("""
            SELECT id, file_path FROM project_files
            WHERE project_id = ? AND file_path LIKE ?
        """, (project['id'], f"%{args.file}%"))

        if not file_row:
            print(f"Error: File not found: {args.file}", file=sys.stderr)
            return 1

        # Determine versions to compare
        if args.commit1 and args.commit2:
            # Compare specific commits
            content1, label1 = self._get_content_at_commit(
                file_row['id'], args.commit1, project['id']
            )
            content2, label2 = self._get_content_at_commit(
                file_row['id'], args.commit2, project['id']
            )
        elif args.commit1:
            # Compare commit to current
            content1, label1 = self._get_content_at_commit(
                file_row['id'], args.commit1, project['id']
            )
            content2, label2 = self._get_current_content(file_row['id'])
            label2 = "current"
        else:
            # Compare previous version to current
            versions = self.vcs_repo.query_all("""
                SELECT fc.version, fc.content_hash, fc.updated_at
                FROM file_contents fc
                WHERE fc.file_id = ?
                ORDER BY fc.version DESC
                LIMIT 2
            """, (file_row['id'],))

            if len(versions) < 2:
                print("Only one version exists, no diff available")
                return 0

            # Current version
            content2, _ = self._get_content_by_hash(versions[0]['content_hash'])
            label2 = f"version {versions[0]['version']} (current)"

            # Previous version
            content1, _ = self._get_content_by_hash(versions[1]['content_hash'])
            label1 = f"version {versions[1]['version']}"

        if content1 is None:
            print(f"Error: Could not retrieve old version", file=sys.stderr)
            return 1

        if content2 is None:
            print(f"Error: Could not retrieve new version", file=sys.stderr)
            return 1

        # Generate and display diff
        self._display_diff(
            content1, content2,
            f"{file_row['file_path']} ({label1})",
            f"{file_row['file_path']} ({label2})",
            unified=not args.side_by_side if hasattr(args, 'side_by_side') else True,
            color=not args.no_color if hasattr(args, 'no_color') else True
        )

        return 0

    def _get_content_by_hash(self, content_hash: str) -> Tuple[Optional[str], Optional[str]]:
        """Get content from content_blobs by hash"""
        blob = self.vcs_repo.query_one("""
            SELECT content_text, content_type FROM content_blobs
            WHERE hash_sha256 = ?
        """, (content_hash,))

        if not blob:
            return None, None

        if blob['content_type'] != 'text':
            return None, "binary"

        return blob['content_text'], "text"

    def _get_current_content(self, file_id: int) -> Tuple[Optional[str], str]:
        """Get current file content"""
        current = self.vcs_repo.query_one("""
            SELECT fc.content_hash
            FROM file_contents fc
            WHERE fc.file_id = ? AND fc.is_current = 1
        """, (file_id,))

        if not current:
            return None, "not found"

        content, content_type = self._get_content_by_hash(current['content_hash'])
        return content, content_type or "current"

    def _get_content_at_commit(
        self, file_id: int, commit_ref: str, project_id: int
    ) -> Tuple[Optional[str], str]:
        """Get file content at a specific commit"""
        # Find commit by hash prefix or full hash
        commit = self.vcs_repo.query_one("""
            SELECT id, commit_hash FROM vcs_commits
            WHERE project_id = ? AND (
                commit_hash = ? OR commit_hash LIKE ?
            )
        """, (project_id, commit_ref, f"{commit_ref}%"))

        if not commit:
            return None, f"commit {commit_ref} not found"

        # Get file state at that commit
        file_state = self.vcs_repo.query_one("""
            SELECT content_text, change_type FROM vcs_file_states
            WHERE commit_id = ? AND file_id = ?
        """, (commit['id'], file_id))

        if not file_state:
            return None, f"file not in commit {commit['commit_hash'][:8]}"

        if file_state['change_type'] == 'deleted':
            return "", f"deleted in {commit['commit_hash'][:8]}"

        return file_state['content_text'], commit['commit_hash'][:8]

    def _display_diff(
        self, old_content: str, new_content: str,
        old_label: str, new_label: str,
        unified: bool = True, color: bool = True
    ) -> None:
        """Display diff with optional color"""
        old_lines = old_content.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)

        if unified:
            diff_lines = list(difflib.unified_diff(
                old_lines, new_lines,
                fromfile=old_label,
                tofile=new_label,
                lineterm=''
            ))

            if not diff_lines:
                print("No differences")
                return

            for line in diff_lines:
                if color:
                    print(self._colorize_diff_line(line))
                else:
                    print(line)
        else:
            # Side-by-side diff (context diff)
            diff_lines = list(difflib.context_diff(
                old_lines, new_lines,
                fromfile=old_label,
                tofile=new_label,
                lineterm=''
            ))

            if not diff_lines:
                print("No differences")
                return

            for line in diff_lines:
                if color:
                    print(self._colorize_diff_line(line))
                else:
                    print(line)

    def _colorize_diff_line(self, line: str) -> str:
        """Add color to diff output"""
        # ANSI color codes
        RED = '\033[31m'
        GREEN = '\033[32m'
        CYAN = '\033[36m'
        RESET = '\033[0m'

        if line.startswith('---') or line.startswith('+++'):
            return f"{CYAN}{line}{RESET}"
        elif line.startswith('-'):
            return f"{RED}{line}{RESET}"
        elif line.startswith('+'):
            return f"{GREEN}{line}{RESET}"
        elif line.startswith('@@'):
            return f"{CYAN}{line}{RESET}"
        else:
            return line

    def _diff_staged(self, project: dict, args) -> int:
        """Show diff of staged changes"""
        # Get default branch
        branches = self.vcs_repo.get_branches(project['id'])
        branch = next((b for b in branches if b.get('is_default')), None)

        if not branch:
            logger.error("No default branch found")
            return 1

        # Get all staged files
        staged_files = self.vcs_repo.query_all("""
            SELECT
                ws.file_id,
                ws.state,
                ws.content_hash as staged_hash,
                pf.file_path,
                fc.content_hash as current_hash
            FROM vcs_working_state ws
            JOIN project_files pf ON ws.file_id = pf.id
            LEFT JOIN file_contents fc ON fc.file_id = ws.file_id AND fc.is_current = 1
            WHERE ws.project_id = ? AND ws.branch_id = ? AND ws.staged = 1
            ORDER BY pf.file_path
        """, (project['id'], branch['id']))

        if not staged_files:
            print("No staged changes")
            return 0

        print(f"Staged changes for {project['slug']}:\n")

        for file in staged_files:
            print(f"{'='*70}")
            print(f"File: {file['file_path']}")
            print(f"State: {file['state']}")
            print(f"{'='*70}\n")

            if file['state'] == 'added':
                # Show new file content
                content, _ = self._get_content_by_hash(file['staged_hash'] or file['current_hash'])
                if content:
                    print("+++ New file")
                    for line in content.splitlines():
                        print(f"+{line}")
                print()

            elif file['state'] == 'deleted':
                # Show deleted file (would need to get from last commit)
                print("--- File deleted")
                print()

            elif file['state'] == 'modified':
                # Show diff between committed and staged version
                # Get last committed version
                last_commit = self.vcs_repo.query_one("""
                    SELECT vfs.content_text
                    FROM vcs_file_states vfs
                    JOIN vcs_commits vc ON vfs.commit_id = vc.id
                    WHERE vfs.file_id = ? AND vc.branch_id = ?
                    ORDER BY vc.commit_timestamp DESC
                    LIMIT 1
                """, (file['file_id'], branch['id']))

                old_content = last_commit['content_text'] if last_commit else ""
                new_content, _ = self._get_content_by_hash(file['current_hash'])

                if new_content:
                    self._display_diff(
                        old_content or "",
                        new_content,
                        f"{file['file_path']} (committed)",
                        f"{file['file_path']} (staged)",
                        unified=not args.side_by_side if hasattr(args, 'side_by_side') else True,
                        color=not args.no_color if hasattr(args, 'no_color') else True
                    )
                print()

        return 0

    def show(self, args) -> int:
        """Show commit details"""
        project = self.get_project_or_exit(args.project)

        # Find commit
        commit = self.vcs_repo.query_one("""
            SELECT
                c.id,
                c.commit_hash,
                c.author,
                c.commit_message,
                c.commit_timestamp,
                b.branch_name
            FROM vcs_commits c
            JOIN vcs_branches b ON c.branch_id = b.id
            WHERE c.project_id = ? AND (
                c.commit_hash = ? OR c.commit_hash LIKE ?
            )
        """, (project['id'], args.commit, f"{args.commit}%"))

        if not commit:
            print(f"Error: Commit not found: {args.commit}", file=sys.stderr)
            return 1

        # Print commit info
        print(f"commit {commit['commit_hash']}")
        print(f"Branch: {commit['branch_name']}")
        print(f"Author: {commit['author']}")
        print(f"Date:   {commit['commit_timestamp']}")
        print()
        print(f"    {commit['commit_message']}")
        print()

        # Get changed files
        file_states = self.vcs_repo.query_all("""
            SELECT
                pf.file_path,
                vfs.change_type,
                vfs.file_size,
                vfs.line_count
            FROM vcs_file_states vfs
            JOIN project_files pf ON vfs.file_id = pf.id
            WHERE vfs.commit_id = ?
            ORDER BY pf.file_path
        """, (commit['id'],))

        if file_states:
            print(f"Changed files ({len(file_states)}):")
            for fs in file_states:
                change_symbol = {
                    'added': '✨',
                    'modified': '📝',
                    'deleted': '🗑️',
                    'renamed': '📋'
                }.get(fs['change_type'], '❓')

                size_info = f"({fs['line_count']} lines)" if fs['line_count'] else f"({fs['file_size']} bytes)"
                print(f"  {change_symbol} {fs['change_type']:<10} {fs['file_path']} {size_info}")

        return 0



def register(cli):
    """Register VCS commands"""
    cmd = VCSCommands()

    vcs_parser = cli.register_command('vcs', None, help_text='Version control')
    subparsers = vcs_parser.add_subparsers(dest='vcs_subcommand', required=True)

    # vcs add
    add_parser = subparsers.add_parser('add', help='Stage files for commit')
    add_parser.add_argument('-p', '--project', required=True, help='Project slug')
    add_parser.add_argument('-a', '--all', action='store_true', help='Stage all changes')
    add_parser.add_argument('files', nargs='*', help='File patterns to stage')
    cli.commands['vcs.add'] = cmd.add

    # vcs reset
    reset_parser = subparsers.add_parser('reset', help='Unstage files')
    reset_parser.add_argument('-p', '--project', required=True, help='Project slug')
    reset_parser.add_argument('-a', '--all', action='store_true', help='Unstage all changes')
    reset_parser.add_argument('files', nargs='*', help='File patterns to unstage')
    cli.commands['vcs.reset'] = cmd.reset

    # vcs commit
    commit_parser = subparsers.add_parser('commit', help='Create commit')
    commit_parser.add_argument('-m', '--message', required=True, help='Commit message')
    commit_parser.add_argument('-p', '--project', required=True, help='Project slug')
    commit_parser.add_argument('-b', '--branch', help='Branch name')
    commit_parser.add_argument('-a', '--author', help='Author name')
    cli.commands['vcs.commit'] = cmd.commit

    # vcs status
    status_parser = subparsers.add_parser('status', help='Show working directory status')
    status_parser.add_argument('project', help='Project slug')
    status_parser.add_argument('--refresh', '-r', action='store_true', help='Refresh working state')
    cli.commands['vcs.status'] = cmd.status

    # vcs log
    log_parser = subparsers.add_parser('log', help='Show commit history')
    log_parser.add_argument('project', help='Project slug')
    log_parser.add_argument('-n', type=int, help='Number of commits to show')
    cli.commands['vcs.log'] = cmd.log

    # vcs branch
    branch_parser = subparsers.add_parser('branch', help='List or create branches')
    branch_parser.add_argument('project', help='Project slug')
    branch_parser.add_argument('name', nargs='?', help='New branch name')
    cli.commands['vcs.branch'] = cmd.branch

    # vcs diff
    diff_parser = subparsers.add_parser('diff', help='Show diff between file versions')
    diff_parser.add_argument('project', help='Project slug')
    diff_parser.add_argument('file', nargs='?', help='File path or pattern (not required with --staged)')
    diff_parser.add_argument('commit1', nargs='?', help='First commit hash (optional)')
    diff_parser.add_argument('commit2', nargs='?', help='Second commit hash (optional)')
    diff_parser.add_argument('--staged', action='store_true', help='Show diff of staged changes')
    diff_parser.add_argument('--side-by-side', '-s', action='store_true', help='Side-by-side diff')
    diff_parser.add_argument('--no-color', action='store_true', help='Disable color output')
    cli.commands['vcs.diff'] = cmd.diff

    # vcs show
    show_parser = subparsers.add_parser('show', help='Show commit details')
    show_parser.add_argument('project', help='Project slug')
    show_parser.add_argument('commit', help='Commit hash or prefix')
    cli.commands['vcs.show'] = cmd.show
