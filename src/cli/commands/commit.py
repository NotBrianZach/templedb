#!/usr/bin/env python3
"""
Commit Command - Commit filesystem changes back to database
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from repositories import ProjectRepository, FileRepository, CheckoutRepository, VCSRepository
from importer.content import ContentStore, FileContent
from importer.scanner import FileScanner
from logger import get_logger

logger = get_logger(__name__)


@dataclass
class FileChange:
    """Represents a change to a file"""
    change_type: str  # 'added', 'modified', 'deleted'
    file_path: str
    file_id: Optional[int] = None
    old_hash: Optional[str] = None
    content: Optional[FileContent] = None


class CommitCommand:
    """Handles commit operations - committing workspace changes to database"""

    def __init__(self):
        super().__init__()
        self.scanner = None
        self.content_store = ContentStore()
        self.project_repo = ProjectRepository()
        self.file_repo = FileRepository()
        self.checkout_repo = CheckoutRepository()
        self.vcs_repo = VCSRepository()

    def commit(self, args) -> int:
        """Commit workspace changes back to database

        Args:
            args: Namespace with project_slug, workspace_dir, and message

        Returns:
            0 on success, 1 on error
        """
        project_slug = args.project_slug
        workspace_dir = Path(args.workspace_dir).resolve()
        message = args.message

        logger.info(f"Committing changes for project: {project_slug}")
        logger.info(f"Workspace directory: {workspace_dir}")

        try:
            # Verify workspace exists
            if not workspace_dir.exists():
                logger.error(f"Workspace directory does not exist: {workspace_dir}")
                return 1

            # Get project
            project = self.project_repo.get_by_slug(project_slug)
            if not project:
                logger.error(f"Project '{project_slug}' not found")
                return 1

            # Initialize scanner for this workspace
            self.scanner = FileScanner(workspace_dir)

            # Scan workspace for changes
            logger.info("Scanning workspace for changes...")
            changes = self._scan_changes(project['id'], workspace_dir)

            # Check if there are any changes
            total_changes = len(changes['added']) + len(changes['modified']) + len(changes['deleted'])

            if total_changes == 0:
                logger.info("No changes to commit")
                return 0

            # Display changes
            print(f"\n📊 Changes detected:")
            if changes['added']:
                print(f"   Added: {len(changes['added'])} files")
                for change in changes['added'][:5]:  # Show first 5
                    print(f"      + {change.file_path}")
                if len(changes['added']) > 5:
                    print(f"      ... and {len(changes['added']) - 5} more")

            if changes['modified']:
                print(f"   Modified: {len(changes['modified'])} files")
                for change in changes['modified'][:5]:
                    print(f"      ~ {change.file_path}")
                if len(changes['modified']) > 5:
                    print(f"      ... and {len(changes['modified']) - 5} more")

            if changes['deleted']:
                print(f"   Deleted: {len(changes['deleted'])} files")
                for change in changes['deleted'][:5]:
                    print(f"      - {change.file_path}")
                if len(changes['deleted']) > 5:
                    print(f"      ... and {len(changes['deleted']) - 5} more")

            # Check for conflicts before committing (unless --force)
            conflicts = []
            force = getattr(args, 'force', False)

            if not force and changes['modified']:
                logger.info("Checking for conflicts...")
                conflicts = self._detect_conflicts(project['id'], workspace_dir, changes['modified'])

            if conflicts:
                logger.warning(f"CONFLICTS DETECTED: {len(conflicts)} file(s)")
                for conflict in conflicts:
                    print(f"   {conflict['file_path']}")
                    print(f"      Your version: {conflict['your_version']}")
                    print(f"      Current version: {conflict['current_version']}")
                    if conflict['changed_by']:
                        print(f"      Changed by: {conflict['changed_by']} at {conflict['changed_at']}")

                # Determine resolution strategy
                strategy = getattr(args, 'strategy', None)
                if not strategy:
                    strategy = self._prompt_resolution_strategy()

                if strategy == 'abort':
                    logger.info("Commit aborted by user")
                    print(f"\nTo resolve:")
                    print(f"  1. Checkout fresh copy: templedb project checkout {project_slug} /tmp/{project_slug}-fresh")
                    print(f"  2. Manually merge your changes from {workspace_dir}")
                    print(f"  3. Commit again")
                    return 1
                elif strategy == 'force':
                    logger.warning(f"Forcing commit - will overwrite {len(conflicts)} conflicting file(s)")
                    force = True  # Proceed with force
                else:
                    logger.error(f"Strategy '{strategy}' not yet implemented")
                    return 1

            # Commit changes (atomic transaction)
            logger.info("Committing changes to database...")

            with self.vcs_repo.transaction():
                # Get or create 'main' branch
                branch_id = self.vcs_repo.get_or_create_branch(project['id'], 'main')

                # Generate commit hash (simple timestamp-based for now)
                import hashlib
                import time
                commit_hash = hashlib.sha256(f"{project['id']}-{message}-{time.time()}".encode()).hexdigest()[:40]

                # Create commit record
                author = os.getenv('USER', 'unknown')
                commit_id = self.vcs_repo.create_commit(
                    project_id=project['id'],
                    branch_id=branch_id,
                    commit_hash=commit_hash,
                    author=author,
                    message=message
                )

                # Process changes
                files_processed = 0

                # Added files
                for change in changes['added']:
                    self._commit_added_file(project['id'], commit_id, change)
                    files_processed += 1

                # Modified files
                for change in changes['modified']:
                    self._commit_modified_file(project['id'], commit_id, change)
                    files_processed += 1

                # Deleted files
                for change in changes['deleted']:
                    self._commit_deleted_file(project['id'], commit_id, change)
                    files_processed += 1

                # Get checkout
                checkout = self.checkout_repo.get_by_path(project['id'], str(workspace_dir))

                if checkout:
                    # Update checkout timestamp
                    self.checkout_repo.update_sync_time(checkout['id'])

                    # CRITICAL: Update checkout snapshots with new versions
                    # This prevents false conflicts on next commit

                    # Update snapshots for added files
                    for change in changes['added']:
                        # Get current version for the file
                        version_info = self.vcs_repo.get_current_file_version(change.file_id)
                        version = version_info['version'] if version_info else 1
                        self.checkout_repo.record_snapshot(
                            checkout_id=checkout['id'],
                            file_id=change.file_id,
                            content_hash=change.content.hash_sha256,
                            version=version
                        )

                    # Update snapshots for modified files
                    for change in changes['modified']:
                        version_info = self.vcs_repo.get_current_file_version(change.file_id)
                        version = version_info['version'] if version_info else 1
                        self.checkout_repo.record_snapshot(
                            checkout_id=checkout['id'],
                            file_id=change.file_id,
                            content_hash=change.content.hash_sha256,
                            version=version
                        )

                    # Remove snapshots for deleted files
                    for change in changes['deleted']:
                        self.checkout_repo.execute(
                            "DELETE FROM checkout_snapshots WHERE checkout_id = ? AND file_id = ?",
                            (checkout['id'], change.file_id),
                            commit=False
                        )

            # Success
            logger.info("Commit complete!")
            print(f"   Commit ID: {commit_id}")
            print(f"   Files changed: {files_processed}")
            print(f"   Message: {message}")

            return 0

        except Exception as e:
            logger.error(f"Commit failed: {e}", exc_info=True)
            return 1

    def _scan_changes(self, project_id: int, workspace_dir: Path) -> Dict[str, List[FileChange]]:
        """Scan workspace and detect changes"""
        changes = {'added': [], 'modified': [], 'deleted': []}

        # Get current database state
        db_files = self.file_repo.get_files_for_project(project_id, include_content=False)

        # Convert to dict keyed by path with expected structure
        db_by_path = {}
        for f in db_files:
            db_by_path[f['file_path']] = {
                'id': f['file_id'],
                'file_path': f['file_path'],
                'content_hash': f['content_hash'],
                'file_type_id': f.get('file_type_id')
            }

        # Scan filesystem (use scanner to get trackable files)
        scanned_files = self.scanner.scan_directory()

        for scanned_file in scanned_files:
            rel_path = str(scanned_file.relative_path)

            # Read content and compute hash
            file_path = workspace_dir / rel_path
            content = ContentStore.read_file_content(file_path)

            if not content:
                continue

            if rel_path not in db_by_path:
                # New file
                changes['added'].append(FileChange(
                    change_type='added',
                    file_path=rel_path,
                    content=content
                ))
            else:
                # Check if modified
                db_file = db_by_path[rel_path]
                if db_file['content_hash'] != content.hash_sha256:
                    changes['modified'].append(FileChange(
                        change_type='modified',
                        file_path=rel_path,
                        file_id=db_file['id'],
                        old_hash=db_file['content_hash'],
                        content=content
                    ))

                # Mark as seen
                db_by_path.pop(rel_path)

        # Remaining files in db_by_path were deleted
        for path, file_info in db_by_path.items():
            changes['deleted'].append(FileChange(
                change_type='deleted',
                file_path=path,
                file_id=file_info['id'],
                old_hash=file_info['content_hash']
            ))

        return changes

    def _commit_added_file(self, project_id: int, commit_id: int, change: FileChange):
        """Commit an added file"""
        # Determine file type
        file_type_id = self._get_file_type_id(change.file_path)

        # Create project_files entry
        file_name = Path(change.file_path).name
        component_name = Path(change.file_path).stem

        file_id = self.file_repo.execute("""
            INSERT INTO project_files
            (project_id, file_path, file_name, file_type_id, component_name)
            VALUES (?, ?, ?, ?, ?)
        """, (project_id, change.file_path, file_name, file_type_id, component_name), commit=False)

        # Store content blob (INSERT OR IGNORE for deduplication)
        if change.content.content_type == 'text':
            self.file_repo.execute("""
                INSERT OR IGNORE INTO content_blobs
                (hash_sha256, content_text, content_blob, content_type, encoding, file_size_bytes)
                VALUES (?, ?, NULL, ?, ?, ?)
            """, (
                change.content.hash_sha256,
                change.content.content_text,
                change.content.content_type,
                change.content.encoding,
                change.content.file_size
            ), commit=False)
        else:
            self.file_repo.execute("""
                INSERT OR IGNORE INTO content_blobs
                (hash_sha256, content_text, content_blob, content_type, encoding, file_size_bytes)
                VALUES (?, NULL, ?, ?, ?, ?)
            """, (
                change.content.hash_sha256,
                change.content.content_blob,
                change.content.content_type,
                change.content.encoding,
                change.content.file_size
            ), commit=False)

        # Create file_contents reference
        self.file_repo.execute("""
            INSERT INTO file_contents
            (file_id, content_hash, file_size_bytes, line_count, is_current)
            VALUES (?, ?, ?, ?, 1)
        """, (
            file_id,
            change.content.hash_sha256,
            change.content.file_size,
            change.content.line_count
        ), commit=False)

        # Record in commit_files
        self.vcs_repo.record_file_change(
            commit_id=commit_id,
            file_id=file_id,
            change_type='added',
            old_hash=None,
            new_hash=change.content.hash_sha256,
            new_path=change.file_path
        )

        # Store file_id in change for later snapshot update
        change.file_id = file_id

    def _commit_modified_file(self, project_id: int, commit_id: int, change: FileChange):
        """Commit a modified file"""
        # Store new content blob (INSERT OR IGNORE for deduplication)
        if change.content.content_type == 'text':
            self.file_repo.execute("""
                INSERT OR IGNORE INTO content_blobs
                (hash_sha256, content_text, content_blob, content_type, encoding, file_size_bytes)
                VALUES (?, ?, NULL, ?, ?, ?)
            """, (
                change.content.hash_sha256,
                change.content.content_text,
                change.content.content_type,
                change.content.encoding,
                change.content.file_size
            ), commit=False)
        else:
            self.file_repo.execute("""
                INSERT OR IGNORE INTO content_blobs
                (hash_sha256, content_text, content_blob, content_type, encoding, file_size_bytes)
                VALUES (?, NULL, ?, ?, ?, ?)
            """, (
                change.content.hash_sha256,
                change.content.content_blob,
                change.content.content_type,
                change.content.encoding,
                change.content.file_size
            ), commit=False)

        # Update file_contents reference with version increment
        self.file_repo.execute("""
            UPDATE file_contents
            SET content_hash = ?,
                file_size_bytes = ?,
                line_count = ?,
                version = version + 1,
                updated_at = datetime('now')
            WHERE file_id = ? AND is_current = 1
        """, (
            change.content.hash_sha256,
            change.content.file_size,
            change.content.line_count,
            change.file_id
        ), commit=False)

        # Record in commit_files
        self.vcs_repo.record_file_change(
            commit_id=commit_id,
            file_id=change.file_id,
            change_type='modified',
            old_hash=change.old_hash,
            new_hash=change.content.hash_sha256,
            new_path=change.file_path
        )

    def _commit_deleted_file(self, project_id: int, commit_id: int, change: FileChange):
        """Commit a deleted file"""
        # Mark file_contents as not current
        self.file_repo.execute("""
            UPDATE file_contents
            SET is_current = 0, updated_at = datetime('now')
            WHERE file_id = ?
        """, (change.file_id,), commit=False)

        # Record in commit_files
        self.vcs_repo.record_file_change(
            commit_id=commit_id,
            file_id=change.file_id,
            change_type='deleted',
            old_hash=change.old_hash,
            new_hash=None,
            old_path=change.file_path
        )

    def _get_file_type_id(self, file_path: str) -> Optional[int]:
        """Get file type ID for a file path"""
        extension = Path(file_path).suffix.lstrip('.')

        # Map common extensions
        extension_map = {
            'py': 'python',
            'js': 'javascript',
            'ts': 'typescript',
            'sql': 'sql',
            'md': 'markdown',
            'txt': 'text',
            'json': 'json',
            'yaml': 'yaml',
            'yml': 'yaml',
            'toml': 'toml',
            'sh': 'shell',
            'bash': 'shell',
            'nix': 'nix',
        }

        type_name = extension_map.get(extension, 'unknown')

        # Get type ID
        file_type = self.file_repo.query_one("SELECT id FROM file_types WHERE type_name = ?", (type_name,))
        return file_type['id'] if file_type else None

    def _detect_conflicts(self, project_id: int, workspace_dir: Path, modified_files: List[FileChange]) -> List[Dict]:
        """Detect version conflicts for modified files"""
        conflicts = []

        # Get checkout info
        checkout = self.checkout_repo.get_by_path(project_id, str(workspace_dir))

        if not checkout:
            # No checkout record, can't detect conflicts
            return []

        for change in modified_files:
            # Get current version in database (still need raw query for join with commits)
            current = self.file_repo.query_one("""
                SELECT
                    fc.version,
                    fc.content_hash,
                    c.author,
                    c.commit_timestamp
                FROM file_contents fc
                LEFT JOIN commit_files cf ON cf.file_id = fc.file_id AND cf.new_content_hash = fc.content_hash
                LEFT JOIN vcs_commits c ON c.id = cf.commit_id
                WHERE fc.file_id = ? AND fc.is_current = 1
            """, (change.file_id,))

            # Get version at checkout
            snapshot = self.checkout_repo.get_snapshot(checkout['id'], change.file_id)

            if snapshot and current:
                # Check for version mismatch
                if current['version'] != snapshot['version']:
                    conflicts.append({
                        'file_path': change.file_path,
                        'file_id': change.file_id,
                        'your_version': snapshot['version'],
                        'current_version': current['version'],
                        'changed_by': current.get('author'),
                        'changed_at': current.get('commit_timestamp')
                    })

        return conflicts

    def _prompt_resolution_strategy(self) -> str:
        """Prompt user for conflict resolution strategy"""
        print(f"\nHow would you like to resolve?")
        print(f"  [a] Abort commit (recommended)")
        print(f"  [f] Force commit (overwrite other changes)")
        print(f"  [r] Attempt auto-rebase (not yet implemented)")

        while True:
            try:
                choice = input("Choice: ").strip().lower()
                if choice in ['a', 'abort']:
                    return 'abort'
                elif choice in ['f', 'force']:
                    return 'force'
                elif choice in ['r', 'rebase']:
                    return 'rebase'
                else:
                    print("Invalid choice. Please enter 'a', 'f', or 'r'")
            except (EOFError, KeyboardInterrupt):
                print("\nAborted")
                return 'abort'


def main():
    """CLI entry point for testing"""
    import argparse

    parser = argparse.ArgumentParser(description='Commit workspace changes to TempleDB')
    parser.add_argument('project_slug', help='Project slug')
    parser.add_argument('workspace_dir', help='Workspace directory')
    parser.add_argument('-m', '--message', required=True, help='Commit message')

    args = parser.parse_args()

    cmd = CommitCommand()
    return cmd.commit(args)


if __name__ == '__main__':
    sys.exit(main())
