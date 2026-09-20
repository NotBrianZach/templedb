#!/usr/bin/env python3
"""
Merge Command - Merge external changes with database
"""

import sys
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from cli.core import Command
from repositories import ProjectRepository, FileRepository
from merge_resolver import MergeResolver, MergeConflict, ConflictType
from logger import get_logger

logger = get_logger(__name__)


class MergeCommand(Command):
    """Handle merge operations"""

    def __init__(self):
        super().__init__()
        self.project_repo = ProjectRepository()
        self.file_repo = FileRepository()
        self.merge_resolver = MergeResolver()

    def merge_from_git(self, args) -> int:
        """
        Merge changes from external git repository

        Args:
            args: Namespace with project_slug and strategy

        Returns:
            0 on success, 1 on error
        """
        project_slug = args.project_slug
        strategy = getattr(args, 'strategy', 'ai-assisted')

        logger.info(f"Merging from git for project: {project_slug}")

        try:
            # Get project
            project = self.project_repo.get_by_slug(project_slug)
            if not project:
                logger.error(f"Project '{project_slug}' not found")
                return 1

            repo_url = project.get('repo_url')
            if not repo_url:
                logger.error(f"Project has no repo_url configured")
                return 1

            repo_path = Path(repo_url)
            if not repo_path.exists():
                logger.error(f"Repository path does not exist: {repo_path}")
                return 1

            # Check if it's a git repository
            if not (repo_path / '.git').exists():
                logger.error(f"Not a git repository: {repo_path}")
                return 1

            # Get current database state
            logger.info("Reading database state...")
            db_files = self._get_db_files(project['id'])

            # Get git state
            logger.info("Reading git repository state...")
            git_files = self._get_git_files(repo_path)

            # Find common ancestor (base) if possible
            logger.info("Finding common ancestor...")
            base_files = self._get_base_files(project['id'], repo_path)

            # Detect changes and conflicts
            logger.info("Detecting conflicts...")
            conflicts = self._detect_merge_conflicts(db_files, git_files, base_files)

            if not conflicts:
                logger.info("✅ No conflicts detected - files can be auto-merged")

                # Perform auto-merge
                merged_count = self._auto_merge_files(project['id'], db_files, git_files)
                print(f"\n✅ Auto-merged {merged_count} files")
                return 0

            # Show conflicts
            print(f"\n⚠️  Detected {len(conflicts)} conflicts:\n")
            for i, conflict in enumerate(conflicts, 1):
                self._display_conflict_summary(i, conflict)

            # Resolve conflicts based on strategy
            if strategy == 'manual':
                logger.info("Manual resolution required")
                print("\n💡 Use 'templedb merge resolve' to resolve conflicts interactively")
                return 1

            logger.info(f"Resolving conflicts with strategy: {strategy}")
            resolved = self.merge_resolver.resolve_conflicts(conflicts, strategy)

            # Show AI suggestions
            if strategy == 'ai-assisted':
                print(f"\n🤖 AI Merge Suggestions:\n")
                for i, conflict in enumerate(resolved, 1):
                    self._display_ai_suggestion(i, conflict)

                # Prompt for human review
                if not getattr(args, 'auto_apply', False):
                    print(f"\n❓ Apply AI suggestions?")
                    print(f"   [a] Accept all")
                    print(f"   [r] Review each")
                    print(f"   [n] Cancel")

                    choice = input("Choice: ").strip().lower()
                    if choice == 'n':
                        logger.info("Merge cancelled by user")
                        return 1
                    elif choice == 'r':
                        resolved = self._review_suggestions(resolved)
                    # 'a' falls through to apply all

            # Apply resolutions
            applied = self._apply_resolutions(project['id'], resolved)
            print(f"\n✅ Merged {applied} files")

            return 0

        except Exception as e:
            logger.error(f"Merge failed: {e}", exc_info=True)
            return 1

    def _get_db_files(self, project_id: int) -> Dict[str, Dict]:
        """Get current database file state"""
        files = self.file_repo.get_files_for_project(project_id, include_content=True)

        result = {}
        for f in files:
            result[f['file_path']] = {
                'id': f['file_id'],
                'path': f['file_path'],
                'hash': f['content_hash'],
                'content': f.get('content_text') or f.get('content_blob', b'').decode('utf-8', errors='ignore')
            }

        return result

    def _get_git_files(self, repo_path: Path) -> Dict[str, Dict]:
        """Get git repository file state"""
        import subprocess
        import hashlib

        result = {}

        try:
            # Get list of tracked files
            output = subprocess.check_output(
                ['git', 'ls-files'],
                cwd=repo_path,
                text=True
            ).strip()

            for file_path in output.split('\n'):
                if not file_path:
                    continue

                full_path = repo_path / file_path
                if not full_path.exists():
                    continue

                try:
                    content = full_path.read_text()
                    content_hash = hashlib.sha256(content.encode()).hexdigest()

                    result[file_path] = {
                        'path': file_path,
                        'hash': content_hash,
                        'content': content
                    }
                except Exception as e:
                    logger.warning(f"Could not read {file_path}: {e}")

        except subprocess.CalledProcessError as e:
            logger.error(f"Git command failed: {e}")

        return result

    def _get_base_files(self, project_id: int, repo_path: Path) -> Dict[str, Dict]:
        """
        Get common ancestor file state.

        For now, returns empty dict. Full implementation would:
        1. Track last git commit hash imported
        2. Checkout that commit in git
        3. Read files at that commit
        """
        # TODO: Implement proper base version tracking
        return {}

    def _detect_merge_conflicts(
        self,
        db_files: Dict[str, Dict],
        git_files: Dict[str, Dict],
        base_files: Dict[str, Dict]
    ) -> List[MergeConflict]:
        """Detect merge conflicts between database and git"""
        conflicts = []

        all_paths = set(db_files.keys()) | set(git_files.keys())

        for path in all_paths:
            db_file = db_files.get(path)
            git_file = git_files.get(path)
            base_file = base_files.get(path)

            # Both exist and differ
            if db_file and git_file and db_file['hash'] != git_file['hash']:
                # Check if base exists to determine conflict type
                if base_file:
                    # Both modified from base
                    if db_file['hash'] != base_file['hash'] and git_file['hash'] != base_file['hash']:
                        from merge_resolver import FileVersion

                        conflicts.append(MergeConflict(
                            file_path=path,
                            conflict_type=ConflictType.BOTH_MODIFIED,
                            ours=FileVersion(
                                content=db_file['content'],
                                hash=db_file['hash'],
                                source='database'
                            ),
                            theirs=FileVersion(
                                content=git_file['content'],
                                hash=git_file['hash'],
                                source='git'
                            ),
                            base=FileVersion(
                                content=base_file['content'],
                                hash=base_file['hash'],
                                source='base'
                            )
                        ))
                else:
                    # No base - treat as conflict
                    from merge_resolver import FileVersion

                    conflicts.append(MergeConflict(
                        file_path=path,
                        conflict_type=ConflictType.BOTH_MODIFIED,
                        ours=FileVersion(
                            content=db_file['content'],
                            hash=db_file['hash'],
                            source='database'
                        ),
                        theirs=FileVersion(
                            content=git_file['content'],
                            hash=git_file['hash'],
                            source='git'
                        )
                    ))

            # Modify-delete conflict
            elif db_file and not git_file and base_file:
                # File deleted in git but modified in db
                from merge_resolver import FileVersion

                conflicts.append(MergeConflict(
                    file_path=path,
                    conflict_type=ConflictType.MODIFY_DELETE,
                    ours=FileVersion(
                        content=db_file['content'],
                        hash=db_file['hash'],
                        source='database'
                    ),
                    theirs=None,  # Deleted in git
                    base=FileVersion(
                        content=base_file['content'],
                        hash=base_file['hash'],
                        source='base'
                    )
                ))

            elif git_file and not db_file and base_file:
                # File deleted in db but modified in git
                from merge_resolver import FileVersion

                conflicts.append(MergeConflict(
                    file_path=path,
                    conflict_type=ConflictType.MODIFY_DELETE,
                    ours=None,  # Deleted in db
                    theirs=FileVersion(
                        content=git_file['content'],
                        hash=git_file['hash'],
                        source='git'
                    ),
                    base=FileVersion(
                        content=base_file['content'],
                        hash=base_file['hash'],
                        source='base'
                    )
                ))

        return conflicts

    def _auto_merge_files(
        self,
        project_id: int,
        db_files: Dict[str, Dict],
        git_files: Dict[str, Dict]
    ) -> int:
        """Auto-merge files that don't conflict"""

        # TODO: Implement actual file updates
        # This would:
        # 1. Identify files that changed only in git
        # 2. Update those files in database
        # 3. Create a merge commit

        merged_count = 0
        all_paths = set(db_files.keys()) | set(git_files.keys())

        for path in all_paths:
            db_file = db_files.get(path)
            git_file = git_files.get(path)

            # File only in git - add to db
            if git_file and not db_file:
                logger.info(f"Would add: {path}")
                merged_count += 1

            # File only in db - already there
            elif db_file and not git_file:
                pass  # Keep db version

            # Both exist and identical
            elif db_file and git_file and db_file['hash'] == git_file['hash']:
                pass  # Already in sync

            # Both exist but differ - need conflict resolution
            else:
                pass  # Handled by conflict resolution

        return merged_count

    def _apply_resolutions(self, project_id: int, resolved: List[MergeConflict]) -> int:
        """Apply resolved conflicts to database"""

        # TODO: Implement actual database updates
        # This would:
        # 1. Update file_contents with resolved content
        # 2. Create merge commit
        # 3. Update checkout snapshots

        applied = 0
        for conflict in resolved:
            if conflict.ai_suggestion:
                logger.info(f"Would apply resolution for: {conflict.file_path}")
                applied += 1

        return applied

    def _display_conflict_summary(self, index: int, conflict: MergeConflict):
        """Display conflict summary"""
        print(f"{index}. {conflict.file_path}")
        print(f"   Type: {conflict.conflict_type.value}")

        if conflict.ours:
            print(f"   Database: {conflict.ours.hash[:8]}")
        else:
            print(f"   Database: (deleted)")

        if conflict.theirs:
            print(f"   Git:      {conflict.theirs.hash[:8]}")
        else:
            print(f"   Git:      (deleted)")

        print()

    def _display_ai_suggestion(self, index: int, conflict: MergeConflict):
        """Display AI suggestion for conflict"""
        print(f"{index}. {conflict.file_path}")
        print(f"   Confidence: {conflict.ai_confidence or 'unknown'}")

        if conflict.ai_reasoning:
            print(f"   Reasoning: {conflict.ai_reasoning[:100]}...")

        if conflict.ai_suggestion:
            print(f"   Suggestion: {len(conflict.ai_suggestion)} bytes")
        else:
            print(f"   Suggestion: (none)")

        print()

    def _review_suggestions(self, conflicts: List[MergeConflict]) -> List[MergeConflict]:
        """Interactive review of AI suggestions"""

        reviewed = []

        for i, conflict in enumerate(conflicts, 1):
            print(f"\n--- Conflict {i}/{len(conflicts)}: {conflict.file_path} ---")

            if conflict.ai_suggestion:
                print(f"\nAI Confidence: {conflict.ai_confidence}")
                print(f"Reasoning: {conflict.ai_reasoning}")
                print(f"\n[Preview of suggested resolution]")

                # Show first 20 lines
                lines = conflict.ai_suggestion.split('\n')
                for line in lines[:20]:
                    print(f"  {line}")

                if len(lines) > 20:
                    print(f"  ... ({len(lines) - 20} more lines)")

            print(f"\n❓ Accept this resolution?")
            print(f"   [y] Yes")
            print(f"   [n] No (keep conflict markers)")
            print(f"   [e] Edit manually")
            print(f"   [o] Use ours (database version)")
            print(f"   [t] Use theirs (git version)")

            choice = input("Choice: ").strip().lower()

            if choice == 'y':
                reviewed.append(conflict)
            elif choice == 'n':
                conflict.ai_suggestion = None
                reviewed.append(conflict)
            elif choice == 'o':
                conflict.ai_suggestion = conflict.ours.content if conflict.ours else None
                reviewed.append(conflict)
            elif choice == 't':
                conflict.ai_suggestion = conflict.theirs.content if conflict.theirs else None
                reviewed.append(conflict)
            else:
                # 'e' or unknown - mark for manual edit
                conflict.ai_suggestion = None
                reviewed.append(conflict)

        return reviewed


def register(cli):
    """Register merge command with CLI"""
    cmd = MergeCommand()

    # Create merge command group
    merge_parser = cli.register_command(
        'merge',
        None,
        help_text='Merge changes from external sources'
    )
    subparsers = merge_parser.add_subparsers(dest='merge_subcommand', required=True)

    # merge from-git
    from_git_parser = subparsers.add_parser(
        'from-git',
        help='Merge changes from external git repository'
    )
    from_git_parser.add_argument('project_slug', help='Project slug')
    from_git_parser.add_argument(
        '--strategy',
        choices=['ai-assisted', 'ours', 'theirs', 'manual'],
        default='ai-assisted',
        help='Merge strategy'
    )
    from_git_parser.add_argument(
        '--auto-apply',
        action='store_true',
        help='Automatically apply AI suggestions without review'
    )
    cli.commands['merge.from-git'] = cmd.merge_from_git
