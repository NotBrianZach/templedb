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

from db_utils import query_one, query_all, execute, transaction
from importer.content import ContentStore, FileContent
from importer.scanner import FileScanner


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
        self.scanner = None
        self.content_store = ContentStore()

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

        print(f"📦 Committing changes for project: {project_slug}")
        print(f"📁 Workspace directory: {workspace_dir}")

        try:
            # Verify workspace exists
            if not workspace_dir.exists():
                print(f"✗ Error: Workspace directory does not exist: {workspace_dir}", file=sys.stderr)
                return 1

            # Get project
            project = query_one("SELECT id, name FROM projects WHERE slug = ?", (project_slug,))
            if not project:
                print(f"✗ Error: Project '{project_slug}' not found", file=sys.stderr)
                return 1

            # Initialize scanner for this workspace
            self.scanner = FileScanner(workspace_dir)

            # Scan workspace for changes
            print(f"\n🔍 Scanning workspace for changes...")
            changes = self._scan_changes(project['id'], workspace_dir)

            # Check if there are any changes
            total_changes = len(changes['added']) + len(changes['modified']) + len(changes['deleted'])

            if total_changes == 0:
                print(f"\n✓ No changes to commit")
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
                print(f"\n🔍 Checking for conflicts...")
                conflicts = self._detect_conflicts(project['id'], workspace_dir, changes['modified'])

            if conflicts:
                print(f"\n⚠️  CONFLICTS DETECTED:")
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
                    print(f"\n✗ Commit aborted")
                    print(f"\nTo resolve:")
                    print(f"  1. Checkout fresh copy: templedb project checkout {project_slug} /tmp/{project_slug}-fresh")
                    print(f"  2. Manually merge your changes from {workspace_dir}")
                    print(f"  3. Commit again")
                    return 1
                elif strategy == 'force':
                    print(f"\n⚠️  Forcing commit - will overwrite {len(conflicts)} conflicting file(s)")
                    force = True  # Proceed with force
                else:
                    print(f"\n✗ Strategy '{strategy}' not yet implemented")
                    return 1

            # Commit changes (atomic transaction)
            print(f"\n💾 Committing changes to database...")

            with transaction():
                # Get or create 'main' branch
                branch = query_one("""
                    SELECT id FROM vcs_branches
                    WHERE project_id = ? AND branch_name = 'main'
                """, (project['id'],))

                if not branch:
                    # Create main branch
                    branch_id = execute("""
                        INSERT INTO vcs_branches
                        (project_id, branch_name, is_default)
                        VALUES (?, 'main', 1)
                    """, (project['id'],), commit=False)
                else:
                    branch_id = branch['id']

                # Generate commit hash (simple timestamp-based for now)
                import hashlib
                import time
                commit_hash = hashlib.sha256(f"{project['id']}-{message}-{time.time()}".encode()).hexdigest()[:40]

                # Create commit record
                author = os.getenv('USER', 'unknown')
                commit_id = execute("""
                    INSERT INTO vcs_commits
                    (project_id, branch_id, commit_hash, author, commit_message, commit_timestamp)
                    VALUES (?, ?, ?, ?, ?, datetime('now'))
                """, (project['id'], branch_id, commit_hash, author, message), commit=False)

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

                # Update checkout timestamp
                execute("""
                    UPDATE checkouts
                    SET last_sync_at = datetime('now')
                    WHERE project_id = ? AND checkout_path = ?
                """, (project['id'], str(workspace_dir)), commit=False)

                # CRITICAL: Update checkout snapshots with new versions
                # This prevents false conflicts on next commit
                checkout = query_one("""
                    SELECT id FROM checkouts
                    WHERE project_id = ? AND checkout_path = ?
                """, (project['id'], str(workspace_dir)))

                if checkout:
                    # Update snapshots for added files
                    for change in changes['added']:
                        execute("""
                            INSERT OR REPLACE INTO checkout_snapshots
                            (checkout_id, file_id, content_hash, version, checked_out_at)
                            VALUES (?, ?, ?, (
                                SELECT version FROM file_contents WHERE file_id = ? AND is_current = 1
                            ), datetime('now'))
                        """, (checkout['id'], change.file_id, change.content.hash_sha256, change.file_id), commit=False)

                    # Update snapshots for modified files
                    for change in changes['modified']:
                        execute("""
                            UPDATE checkout_snapshots
                            SET content_hash = ?,
                                version = (SELECT version FROM file_contents WHERE file_id = ? AND is_current = 1),
                                checked_out_at = datetime('now')
                            WHERE checkout_id = ? AND file_id = ?
                        """, (change.content.hash_sha256, change.file_id, checkout['id'], change.file_id), commit=False)

                    # Remove snapshots for deleted files
                    for change in changes['deleted']:
                        execute("""
                            DELETE FROM checkout_snapshots
                            WHERE checkout_id = ? AND file_id = ?
                        """, (checkout['id'], change.file_id), commit=False)

            # Success
            print(f"\n✅ Commit complete!")
            print(f"   Commit ID: {commit_id}")
            print(f"   Files changed: {files_processed}")
            print(f"   Message: {message}")

            return 0

        except Exception as e:
            print(f"\n✗ Commit failed: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
            return 1

    def _scan_changes(self, project_id: int, workspace_dir: Path) -> Dict[str, List[FileChange]]:
        """Scan workspace and detect changes"""
        changes = {'added': [], 'modified': [], 'deleted': []}

        # Get current database state
        db_files = query_all("""
            SELECT
                pf.id,
                pf.file_path,
                fc.content_hash,
                pf.file_type_id
            FROM project_files pf
            LEFT JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
            WHERE pf.project_id = ?
        """, (project_id,))

        db_by_path = {f['file_path']: f for f in db_files}

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

        file_id = execute("""
            INSERT INTO project_files
            (project_id, file_path, file_name, file_type_id, component_name)
            VALUES (?, ?, ?, ?, ?)
        """, (project_id, change.file_path, file_name, file_type_id, component_name), commit=False)

        # Store content blob (INSERT OR IGNORE for deduplication)
        if change.content.content_type == 'text':
            execute("""
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
            execute("""
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
        execute("""
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
        execute("""
            INSERT INTO commit_files
            (commit_id, file_id, change_type, old_content_hash, new_content_hash, new_file_path)
            VALUES (?, ?, 'added', NULL, ?, ?)
        """, (commit_id, file_id, change.content.hash_sha256, change.file_path), commit=False)

    def _commit_modified_file(self, project_id: int, commit_id: int, change: FileChange):
        """Commit a modified file"""
        # Store new content blob (INSERT OR IGNORE for deduplication)
        if change.content.content_type == 'text':
            execute("""
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
            execute("""
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
        execute("""
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
        execute("""
            INSERT INTO commit_files
            (commit_id, file_id, change_type, old_content_hash, new_content_hash, new_file_path)
            VALUES (?, ?, 'modified', ?, ?, ?)
        """, (commit_id, change.file_id, change.old_hash, change.content.hash_sha256, change.file_path), commit=False)

    def _commit_deleted_file(self, project_id: int, commit_id: int, change: FileChange):
        """Commit a deleted file"""
        # Mark file_contents as not current
        execute("""
            UPDATE file_contents
            SET is_current = 0, updated_at = datetime('now')
            WHERE file_id = ?
        """, (change.file_id,), commit=False)

        # Record in commit_files
        execute("""
            INSERT INTO commit_files
            (commit_id, file_id, change_type, old_content_hash, new_content_hash, old_file_path)
            VALUES (?, ?, 'deleted', ?, NULL, ?)
        """, (commit_id, change.file_id, change.old_hash, change.file_path), commit=False)

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
        file_type = query_one("SELECT id FROM file_types WHERE type_name = ?", (type_name,))
        return file_type['id'] if file_type else None

    def _detect_conflicts(self, project_id: int, workspace_dir: Path, modified_files: List[FileChange]) -> List[Dict]:
        """Detect version conflicts for modified files"""
        conflicts = []

        # Get checkout info
        checkout = query_one("""
            SELECT id FROM checkouts
            WHERE project_id = ? AND checkout_path = ?
        """, (project_id, str(workspace_dir)))

        if not checkout:
            # No checkout record, can't detect conflicts
            return []

        for change in modified_files:
            # Get current version in database
            current = query_one("""
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
            snapshot = query_one("""
                SELECT version, content_hash
                FROM checkout_snapshots
                WHERE checkout_id = ? AND file_id = ?
            """, (checkout['id'], change.file_id))

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
