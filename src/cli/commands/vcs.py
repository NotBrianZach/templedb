#!/usr/bin/env python3
"""
Version control commands
"""
import sys
import hashlib
import time
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from db_utils import query_one, query_all, execute
from cli.core import Command


class VCSCommands(Command):
    """VCS command handlers"""

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

        # Get current branch
        branch = query_one("""
            SELECT id FROM vcs_branches
            WHERE project_id = ? AND is_default = 1
        """, (project['id'],))

        if not branch:
            print("Error: No default branch found", file=sys.stderr)
            return 1

        # Handle --all flag
        if hasattr(args, 'all') and args.all:
            # Stage all changes
            result = execute("""
                UPDATE vcs_working_state
                SET staged = 1
                WHERE project_id = ? AND branch_id = ? AND state != 'unmodified'
            """, (project['id'], branch['id']))

            # Count affected rows
            staged_count = query_one("""
                SELECT COUNT(*) as count FROM vcs_working_state
                WHERE project_id = ? AND branch_id = ? AND staged = 1
            """, (project['id'], branch['id']))

            print(f"✓ Staged {staged_count['count']} file(s)")
            return 0

        # Handle specific files
        if hasattr(args, 'files') and args.files:
            for file_pattern in args.files:
                # Find matching files in working state
                files = query_all("""
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
                    execute("""
                        UPDATE vcs_working_state
                        SET staged = 1
                        WHERE id = ?
                    """, (file['id'],))
                    print(f"   ✓ Staged: {file['file_path']}")

            return 0

        print("Error: Specify --all or provide file patterns", file=sys.stderr)
        return 1

    def commit(self, args) -> int:
        """Create VCS commit"""
        project = self.get_project_or_exit(args.project)

        # Get branch
        if args.branch:
            branch = query_one("""
                SELECT id, branch_name FROM vcs_branches
                WHERE project_id = ? AND branch_name = ?
            """, (project['id'], args.branch))
        else:
            branch = query_one("""
                SELECT id, branch_name FROM vcs_branches
                WHERE project_id = ? AND is_default = 1
            """, (project['id'],))

        if not branch:
            print("Error: Branch not found", file=sys.stderr)
            return 1

        # Get staged files with content info
        staged = query_all("""
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
        commit_id = execute("""
            INSERT INTO vcs_commits (
                project_id, branch_id, commit_hash,
                author, commit_message, commit_timestamp
            )
            VALUES (?, ?, ?, ?, ?, datetime('now'))
        """, (project['id'], branch['id'], commit_hash, author, args.message))

        # Create file states
        for file in staged:
            # Use placeholder values for deleted files
            content_hash = file['content_hash'] or 'DELETED'
            file_size = file.get('file_size_bytes', 0) or 0
            line_count = file.get('line_count')
            content_text = file.get('content_text')

            execute("""
                INSERT INTO vcs_file_states (
                    commit_id, file_id, content_text,
                    content_hash, file_size, line_count, change_type
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (commit_id, file['file_id'], content_text,
                  content_hash, file_size, line_count, file['state']))

        # Handle deleted files - remove from project_files and working_state
        deleted_files = [f for f in staged if f['state'] == 'deleted']
        if deleted_files:
            for file in deleted_files:
                execute("DELETE FROM project_files WHERE id = ?", (file['file_id'],))
                execute("""
                    DELETE FROM vcs_working_state
                    WHERE file_id = ? AND project_id = ? AND branch_id = ?
                """, (file['file_id'], project['id'], branch['id']))

        # Clear staging for remaining files
        execute("""
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
            existing = query_one("""
                SELECT COUNT(*) as count FROM vcs_working_state
                WHERE project_id = ?
            """, (project['id'],))

            if not existing or existing['count'] == 0:
                print("🔄 Detecting changes (first time)...")
                self._refresh_working_state(project)

        # Get current branch
        branch = query_one("""
            SELECT branch_name FROM vcs_branches
            WHERE project_id = ? AND is_default = 1
        """, (project['id'],))

        if branch:
            print(f"On branch: {branch['branch_name']}")

        # Get changes
        changes = query_all("""
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

        commits = query_all("""
            SELECT
                commit_hash, branch_name, author,
                commit_message, commit_timestamp
            FROM vcs_commit_history_view
            WHERE project_slug = ?
            ORDER BY commit_timestamp DESC
            LIMIT ?
        """, (project['slug'], limit))

        if not commits:
            print("No commits found")
            return 0

        print(f"\nCommit log for {project['slug']}\n")
        for commit in commits:
            print(f"commit {commit['commit_hash']}")
            print(f"Branch: {commit['branch_name']}")
            print(f"Author: {commit['author']}")
            print(f"Date:   {commit['commit_timestamp']}")
            print(f"\n    {commit['commit_message']}\n")

        return 0

    def branch(self, args) -> int:
        """List or create branches"""
        project = self.get_project_or_exit(args.project)

        if hasattr(args, 'name') and args.name:
            # Create new branch
            parent = query_one("""
                SELECT id FROM vcs_branches
                WHERE project_id = ? AND is_default = 1
            """, (project['id'],))

            if not parent:
                print("Error: No default branch found", file=sys.stderr)
                return 1

            execute("""
                INSERT INTO vcs_branches (project_id, branch_name, parent_branch_id)
                VALUES (?, ?, ?)
            """, (project['id'], args.name, parent['id']))

            print(f"✓ Created branch: {args.name}")
            return 0
        else:
            # List branches
            branches = query_all("""
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
