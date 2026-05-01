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
from cli.fuzzy_matcher import fuzzy_match_project, fuzzy_match_file
from logger import get_logger

logger = get_logger(__name__)


class VCSCommands(Command):
    """VCS command handlers"""

    def __init__(self):
        """Initialize with service context"""
        super().__init__()  # Initialize base Command class
        from services.context import ServiceContext
        self.ctx = ServiceContext()
        self.service = self.ctx.get_vcs_service()

        # Keep repositories for methods not yet refactored
        self.project_repo = self.ctx.project_repo
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
        from error_handler import ResourceNotFoundError, ValidationError

        try:
            # Fuzzy match project
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            # Determine what to stage
            stage_all = hasattr(args, 'all') and args.all
            file_patterns = args.files if hasattr(args, 'files') and args.files else None

            if not stage_all and not file_patterns:
                logger.error("Specify --all or provide file patterns")
                return 1

            # Fuzzy match file patterns if provided
            if file_patterns and not stage_all:
                resolved_files = []
                for pattern in file_patterns:
                    file_record = fuzzy_match_file(project['id'], pattern, show_matched=True)
                    if file_record:
                        resolved_files.append(file_record['file_path'])
                    else:
                        logger.warning(f"Skipping unmatched pattern: {pattern}")

                if not resolved_files:
                    logger.error("No files matched the patterns")
                    return 1

                file_patterns = resolved_files

            # Stage files via service
            count = self.service.stage_files(
                project_slug=project['slug'],
                file_patterns=file_patterns,
                stage_all=stage_all
            )

            print(f"✓ Staged {count} file(s)")
            return 0

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except ValidationError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except Exception as e:
            logger.error(f"Failed to stage files: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def reset(self, args) -> int:
        """Unstage files"""
        from error_handler import ResourceNotFoundError, ValidationError

        try:
            # Fuzzy match project
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            # Determine what to unstage
            unstage_all = hasattr(args, 'all') and args.all
            file_patterns = args.files if hasattr(args, 'files') and args.files else None

            if not unstage_all and not file_patterns:
                logger.error("Specify --all or provide file patterns")
                return 1

            # Fuzzy match file patterns if provided
            if file_patterns and not unstage_all:
                resolved_files = []
                for pattern in file_patterns:
                    file_record = fuzzy_match_file(project['id'], pattern, show_matched=True)
                    if file_record:
                        resolved_files.append(file_record['file_path'])
                    else:
                        logger.warning(f"Skipping unmatched pattern: {pattern}")

                if not resolved_files:
                    logger.error("No files matched the patterns")
                    return 1

                file_patterns = resolved_files

            # Unstage files via service
            count = self.service.unstage_files(
                project_slug=project['slug'],
                file_patterns=file_patterns,
                unstage_all=unstage_all
            )

            print(f"✓ Unstaged {count} file(s)")
            return 0

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except ValidationError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except Exception as e:
            logger.error(f"Failed to unstage files: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def edit(self, args) -> int:
        """Enter edit mode (make checkout writable)"""
        from sync import SyncManager, make_writable
        from error_handler import ResourceNotFoundError

        try:
            # Fuzzy match project
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            # Initialize sync manager
            sync_mgr = SyncManager(project['slug'])

            # Get checkout path
            checkout_path = sync_mgr.get_checkout_path()
            if not checkout_path.exists():
                logger.error(f"No checkout found for {project['slug']}")
                logger.info(f"💡 Run: templedb project checkout {project['slug']}")
                return 1

            # Check if already in edit mode
            existing_session = sync_mgr.get_edit_session()
            if existing_session:
                logger.warning(f"Already in edit mode (started {existing_session['started_at']})")
                return 0

            # Make writable
            make_writable(checkout_path)

            # Start edit session
            reason = args.reason if hasattr(args, 'reason') and args.reason else None
            sync_mgr.start_edit_session(reason=reason)

            print(f"✓ {project['slug']} is now editable")
            print(f"  Path: {checkout_path}")
            print(f"📝 Files are writable until you commit or discard")
            print()
            print("To save changes:")
            print(f"  templedb vcs commit {project['slug']} -m 'message'")
            print()
            print("To discard changes:")
            print(f"  templedb vcs discard {project['slug']}")

            return 0

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except Exception as e:
            logger.error(f"Failed to enter edit mode: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def discard(self, args) -> int:
        """Discard changes and return to read-only mode"""
        from sync import SyncManager, make_readonly
        from error_handler import ResourceNotFoundError

        try:
            # Fuzzy match project
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            # Initialize sync manager
            sync_mgr = SyncManager(project['slug'])

            # Get checkout path
            checkout_path = sync_mgr.get_checkout_path()
            if not checkout_path.exists():
                logger.error(f"No checkout found for {project['slug']}")
                return 1

            # Check if in edit mode
            edit_session = sync_mgr.get_edit_session()
            if not edit_session:
                logger.warning(f"Not in edit mode")
                return 0

            # Detect changes
            changes = sync_mgr.detect_changes()
            has_changes = (changes['disk_changes'] or
                          changes['added_to_disk'] or
                          changes['deleted_from_disk'])

            if has_changes and not (hasattr(args, 'force') and args.force):
                print("⚠️  You have uncommitted changes:")
                if changes['disk_changes']:
                    print("\nModified files:")
                    for f in changes['disk_changes'][:10]:
                        print(f"  M {f}")
                    if len(changes['disk_changes']) > 10:
                        print(f"  ... and {len(changes['disk_changes']) - 10} more")

                if changes['added_to_disk']:
                    print("\nAdded files:")
                    for f in changes['added_to_disk'][:10]:
                        print(f"  A {f}")
                    if len(changes['added_to_disk']) > 10:
                        print(f"  ... and {len(changes['added_to_disk']) - 10} more")

                if changes['deleted_from_disk']:
                    print("\nDeleted files:")
                    for f in changes['deleted_from_disk'][:10]:
                        print(f"  D {f}")

                print()
                print("These changes will be PERMANENTLY LOST!")
                print()
                print("To discard anyway:")
                print(f"  templedb vcs discard {project['slug']} --force")
                print()
                print("To save changes:")
                print(f"  templedb vcs commit {project['slug']} -m 'message'")
                return 1

            # Re-export from database (discard changes)
            logger.info("Re-exporting from database...")
            from repositories import ProjectRepository
            proj_repo = ProjectRepository()
            proj_repo.checkout_project(project['slug'], force=True)

            # Back to read-only
            make_readonly(checkout_path)

            # End edit session
            sync_mgr.end_edit_session()

            print(f"✓ Discarded all changes")
            print(f"✓ {project['slug']} is now read-only")

            return 0

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except Exception as e:
            logger.error(f"Failed to discard changes: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def commit(self, args) -> int:
        """Create VCS commit"""
        # Fuzzy match project
        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            logger.error(f"Project '{args.project}' not found")
            return 1

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
        # content_text lives in content_blobs (CAS), not file_contents
        staged = self.vcs_repo.query_all("""
            SELECT ws.*, cb.content_text, fc.file_size_bytes, fc.line_count
            FROM vcs_working_state ws
            LEFT JOIN file_contents fc ON ws.file_id = fc.file_id AND fc.is_current = 1
            LEFT JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
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

        # If in edit mode, make read-only and end session
        from sync import SyncManager, make_readonly
        try:
            sync_mgr = SyncManager(project['slug'])
            checkout_path = sync_mgr.get_checkout_path()

            if sync_mgr.get_edit_session():
                # Update sync cache with current state
                hashes = sync_mgr.compute_checkout_hashes()
                sync_mgr.save_sync_cache(hashes)

                # Back to read-only
                if checkout_path.exists():
                    make_readonly(checkout_path)

                # End edit session
                sync_mgr.end_edit_session()

                print(f"✓ Checkout is now read-only")
        except Exception as e:
            logger.debug(f"Could not update read-only status: {e}")

        return 0

    def status(self, args) -> int:
        """Show working directory status"""
        from error_handler import ResourceNotFoundError
        from sync import SyncManager, is_writable

        try:
            # Fuzzy match project
            project = fuzzy_match_project(args.project, show_matched=False)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1

            # Get sync manager to check edit status
            sync_mgr = SyncManager(project['slug'])
            checkout_path = sync_mgr.get_checkout_path()
            edit_session = sync_mgr.get_edit_session()

            # Show checkout mode (read-only vs writable)
            if checkout_path.exists():
                writable = is_writable(checkout_path)
                mode_str = "writable (edit mode)" if writable else "read-only"
                print(f"Checkout: {checkout_path}")
                print(f"Mode: {mode_str}")
                if edit_session:
                    print(f"Edit session started: {edit_session['started_at']}")
                    if edit_session.get('reason'):
                        print(f"Reason: {edit_session['reason']}")
                print()

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

            # Get status from service
            status = self.service.get_status(project['slug'])

            if not status['has_branch']:
                print("No VCS branch initialized")
                print("Use: templedb vcs init <project>")
                return 0

            print(f"On branch: {status['branch']}")

            # Check if any changes
            if not status['staged'] and not status['modified'] and not status['untracked']:
                print("No changes")
                return 0

            # Display staged changes
            if status['staged']:
                print("\nChanges to be committed:")
                for file_path in status['staged']:
                    print(f"  📝 staged      {file_path}")

            # Display modified changes
            if status['modified']:
                print("\nChanges not staged for commit:")
                for file_path in status['modified']:
                    print(f"  📝 modified    {file_path}")

            # Display untracked
            if status['untracked']:
                print("\nUntracked files:")
                for file_path in status['untracked']:
                    print(f"  ❓ untracked   {file_path}")

            print()
            return 0

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except Exception as e:
            logger.error(f"Failed to get status: {e}")
            logger.debug("Full error:", exc_info=True)
            return 1

    def log(self, args) -> int:
        """Show commit history"""
        # Fuzzy match project
        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            logger.error(f"Project '{args.project}' not found")
            return 1
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
        # Fuzzy match project
        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            logger.error(f"Project '{args.project}' not found")
            return 1

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
        # Fuzzy match project
        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            logger.error(f"Project '{args.project}' not found")
            return 1

        # Handle --staged flag (show staged changes)
        if hasattr(args, 'staged') and args.staged:
            return self._diff_staged(project, args)

        # Fuzzy match file
        file_record = fuzzy_match_file(project['id'], args.file, show_matched=True)
        if not file_record:
            logger.error(f"File not found: {args.file}")
            logger.info(f"Use: templedb vcs status {args.project} to see available files")
            return 1

        # Get file row with id
        file_row = self.vcs_repo.query_one("""
            SELECT id, file_path FROM project_files
            WHERE project_id = ? AND file_path = ?
        """, (project['id'], file_record['file_path']))

        if not file_row:
            logger.error(f"File not found: {args.file}")
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
            logger.error("Could not retrieve old version")
            logger.info("The content may have been deleted or corrupted")
            return 1

        if content2 is None:
            logger.error("Could not retrieve new version")
            logger.info("The content may have been deleted or corrupted")
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
        # Fuzzy match project
        project = fuzzy_match_project(args.project, show_matched=False)
        if not project:
            logger.error(f"Project '{args.project}' not found")
            return 1

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
            logger.error(f"Commit not found: {args.commit}")
            logger.info(f"Use: templedb vcs log {args.project} to see available commits")
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

    def import_history(self, args) -> int:
        """Import full git history from repository"""
        project = self.get_project_or_exit(args.project)

        repo_url = project.get('repo_url')
        if not repo_url:
            logger.error(f"Project has no repo_url set")
            return 1

        repo_path = Path(repo_url)
        if not repo_path.exists():
            logger.error(f"Repository path does not exist: {repo_path}")
            return 1

        if not (repo_path / '.git').exists():
            logger.error(f"Not a git repository: {repo_path}")
            return 1

        print(f"📦 Importing git history for {args.project}")
        print(f"   Repository: {repo_path}")

        if args.branch:
            print(f"   Branch: {args.branch}")
        else:
            print(f"   Branches: all")

        print()

        try:
            from importer.git_history import GitHistoryImporter

            importer = GitHistoryImporter(args.project, str(repo_path))
            stats = importer.import_full_history(branch=args.branch)

            print(f"\n✅ Git history import complete!")
            print(f"   Commits imported: {stats['commits_imported']}")
            print(f"   Branches imported: {stats['branches_imported']}")
            print(f"   Tags imported: {stats['tags_imported']}")

            if stats['errors'] > 0:
                print(f"   ⚠️  Errors: {stats['errors']}")

            return 0

        except Exception as e:
            logger.error(f"Git history import failed: {e}", exc_info=True)
            print(f"\n✗ Import failed: {e}", file=sys.stderr)
            return 1

    def export_to_git(self, args) -> int:
        """Export database commits to git repository"""
        project = self.get_project_or_exit(args.project)

        repo_url = project.get('repo_url')
        if not repo_url:
            logger.error(f"Project has no repo_url set")
            return 1

        repo_path = Path(repo_url)
        if not repo_path.exists():
            logger.error(f"Repository path does not exist: {repo_path}")
            return 1

        if not (repo_path / '.git').exists():
            logger.error(f"Not a git repository: {repo_path}")
            return 1

        print(f"📤 Exporting commits from {args.project} to git")
        print(f"   Repository: {repo_path}")
        print(f"   Branch: {args.branch}")

        if args.since:
            print(f"   Since commit: {args.since}")

        print()

        try:
            from exporter.git_export import GitExporter

            exporter = GitExporter(args.project, str(repo_path))
            stats = exporter.export_commits(
                branch_name=args.branch,
                since_commit=args.since
            )

            print(f"\n✅ Git export complete!")
            print(f"   Commits exported: {stats.commits_exported}")
            print(f"   Files written: {stats.files_written}")
            print(f"   Branches updated: {stats.branches_updated}")

            if stats.errors > 0:
                print(f"   ⚠️  Errors: {stats.errors}")

            # Push if requested
            if args.push and stats.commits_exported > 0:
                print(f"\n📡 Pushing to {args.remote}/{args.branch}...")

                if exporter.push_to_remote(
                    remote=args.remote,
                    branch=args.branch,
                    force=args.force
                ):
                    print(f"   ✅ Pushed successfully")
                else:
                    print(f"   ✗ Push failed", file=sys.stderr)
                    return 1

            return 0

        except Exception as e:
            logger.error(f"Git export failed: {e}", exc_info=True)
            print(f"\n✗ Export failed: {e}", file=sys.stderr)
            return 1


def register(cli):
    """Register VCS commands"""
    cmd = VCSCommands()

    vcs_parser = cli.register_command('vcs', None, help_text='Version control')
    subparsers = vcs_parser.add_subparsers(dest='vcs_subcommand', required=True)

    # vcs add
    add_parser = subparsers.add_parser('add', help='Stage files for commit')
    add_parser.add_argument('-p', '--project', required=True, help='Project name or pattern (fuzzy matching enabled)')
    add_parser.add_argument('-a', '--all', action='store_true', help='Stage all changes')
    add_parser.add_argument('files', nargs='*', help='File patterns to stage (fuzzy matching enabled)')
    cli.commands['vcs.add'] = cmd.add

    # vcs reset
    reset_parser = subparsers.add_parser('reset', help='Unstage files')
    reset_parser.add_argument('-p', '--project', required=True, help='Project name or pattern (fuzzy matching enabled)')
    reset_parser.add_argument('-a', '--all', action='store_true', help='Unstage all changes')
    reset_parser.add_argument('files', nargs='*', help='File patterns to unstage (fuzzy matching enabled)')
    cli.commands['vcs.reset'] = cmd.reset

    # vcs edit
    edit_parser = subparsers.add_parser('edit', help='Enter edit mode (make checkout writable)')
    edit_parser.add_argument('project', help='Project name or pattern (fuzzy matching enabled)')
    edit_parser.add_argument('--reason', help='Reason for editing (optional)')
    cli.commands['vcs.edit'] = cmd.edit

    # vcs discard
    discard_parser = subparsers.add_parser('discard', help='Discard changes and return to read-only mode')
    discard_parser.add_argument('project', help='Project name or pattern (fuzzy matching enabled)')
    discard_parser.add_argument('--force', '-f', action='store_true', help='Discard without confirmation')
    cli.commands['vcs.discard'] = cmd.discard

    # vcs commit
    commit_parser = subparsers.add_parser('commit', help='Create commit')
    commit_parser.add_argument('-m', '--message', required=True, help='Commit message')
    commit_parser.add_argument('-p', '--project', required=True, help='Project name or pattern (fuzzy matching enabled)')
    commit_parser.add_argument('-b', '--branch', help='Branch name')
    commit_parser.add_argument('-a', '--author', help='Author name')
    cli.commands['vcs.commit'] = cmd.commit

    # vcs status
    status_parser = subparsers.add_parser('status', help='Show working directory status')
    status_parser.add_argument('project', help='Project name or pattern (fuzzy matching enabled)')
    status_parser.add_argument('--refresh', '-r', action='store_true', help='Refresh working state')
    cli.commands['vcs.status'] = cmd.status

    # vcs log
    log_parser = subparsers.add_parser('log', help='Show commit history')
    log_parser.add_argument('project', help='Project name or pattern (fuzzy matching enabled)')
    log_parser.add_argument('-n', type=int, help='Number of commits to show')
    cli.commands['vcs.log'] = cmd.log

    # vcs branch
    branch_parser = subparsers.add_parser('branch', help='List or create branches')
    branch_parser.add_argument('project', help='Project name or pattern (fuzzy matching enabled)')
    branch_parser.add_argument('name', nargs='?', help='New branch name')
    cli.commands['vcs.branch'] = cmd.branch

    # vcs diff
    diff_parser = subparsers.add_parser('diff', help='Show diff between file versions')
    diff_parser.add_argument('project', help='Project name or pattern (fuzzy matching enabled)')
    diff_parser.add_argument('file', nargs='?', help='File path or pattern (fuzzy matching enabled, not required with --staged)')
    diff_parser.add_argument('commit1', nargs='?', help='First commit hash (optional)')
    diff_parser.add_argument('commit2', nargs='?', help='Second commit hash (optional)')
    diff_parser.add_argument('--staged', action='store_true', help='Show diff of staged changes')
    diff_parser.add_argument('--side-by-side', '-s', action='store_true', help='Side-by-side diff')
    diff_parser.add_argument('--no-color', action='store_true', help='Disable color output')
    cli.commands['vcs.diff'] = cmd.diff

    # vcs show
    show_parser = subparsers.add_parser('show', help='Show commit details')
    show_parser.add_argument('project', help='Project name or pattern (fuzzy matching enabled)')
    show_parser.add_argument('commit', help='Commit hash or prefix')
    cli.commands['vcs.show'] = cmd.show

    # vcs import-history
    import_history_parser = subparsers.add_parser('import-history', help='Import full git history')
    import_history_parser.add_argument('project', help='Project slug')
    import_history_parser.add_argument('--branch', help='Specific branch to import (default: all branches)')
    cli.commands['vcs.import-history'] = cmd.import_history

    # vcs export
    export_parser = subparsers.add_parser('export', help='Export database commits to git')
    export_parser.add_argument('project', help='Project slug')
    export_parser.add_argument('--branch', default='main', help='Branch to export (default: main)')
    export_parser.add_argument('--since', help='Only export commits after this git commit hash')
    export_parser.add_argument('--push', action='store_true', help='Push to remote after export')
    export_parser.add_argument('--remote', default='origin', help='Remote to push to (default: origin)')
    export_parser.add_argument('--force', action='store_true', help='Force push (use with caution)')
    cli.commands['vcs.export'] = cmd.export_to_git
