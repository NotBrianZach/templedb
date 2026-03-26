#!/usr/bin/env python3
"""
Checkout Command - Extract project files from database to filesystem
"""

import os
import sys
from pathlib import Path
from typing import Dict, List

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from repositories import ProjectRepository, FileRepository, CheckoutRepository
from logger import get_logger

logger = get_logger(__name__)


class CheckoutCommand:
    """Handles checkout operations - extracting projects from DB to filesystem"""

    def __init__(self):
        super().__init__()
        """Initialize with repositories"""
        self.project_repo = ProjectRepository()
        self.file_repo = FileRepository()
        self.checkout_repo = CheckoutRepository()

    def checkout(self, args) -> int:
        """Checkout project from database to filesystem

        Args:
            args: Namespace with project_slug and target_dir

        Returns:
            0 on success, 1 on error
        """
        project_slug = args.project_slug
        target_dir = Path(args.target_dir).resolve()

        logger.info(f"Checking out project: {project_slug}")
        logger.info(f"Target directory: {target_dir}")

        try:
            # Get project
            project = self.project_repo.get_by_slug(project_slug)
            if not project:
                logger.error(f"Project '{project_slug}' not found")
                return 1

            # Check if target directory exists and is not empty
            if target_dir.exists() and any(target_dir.iterdir()):
                if not args.force:
                    logger.error(f"Target directory is not empty: {target_dir}")
                    logger.error("Use --force to overwrite")
                    return 1
                else:
                    logger.warning("Overwriting existing directory")

            # Create target directory
            target_dir.mkdir(parents=True, exist_ok=True)

            # Get all current files with their content
            logger.info("Loading files from database...")
            files = self.file_repo.get_files_for_project(project['id'], include_content=True)

            if not files:
                logger.warning("No files found in project")
                return 0

            # Write files to filesystem
            logger.info(f"Writing {len(files)} files to filesystem...")
            files_written = 0
            total_bytes = 0

            for file in files:
                file_path = target_dir / file['file_path']

                # Create parent directories
                file_path.parent.mkdir(parents=True, exist_ok=True)

                # Write content
                try:
                    if file['content_type'] == 'text':
                        file_path.write_text(file['content_text'], encoding=file['encoding'] or 'utf-8')
                    else:
                        file_path.write_bytes(file['content_blob'])

                    files_written += 1
                    total_bytes += file['file_size_bytes']

                except Exception as e:
                    logger.warning(f"Failed to write {file['file_path']}: {e}")

            # Record checkout in database and snapshot versions
            with self.checkout_repo.transaction():
                # Insert or update checkout record
                checkout_id = self.checkout_repo.create_or_update(
                    project_id=project['id'],
                    checkout_path=str(target_dir),
                    branch_name='main'
                )

                # Clear old snapshots for this checkout
                self.checkout_repo.clear_snapshots(checkout_id)

                # Record snapshot of file versions
                for file in files:
                    # Get current version for this file
                    version = file.get('version', 1)
                    self.checkout_repo.record_snapshot(
                        checkout_id=checkout_id,
                        file_id=file['file_id'],
                        content_hash=file['content_hash'],
                        version=version
                    )

            # Save sync cache for hash-based change detection
            from sync import SyncManager, make_readonly
            try:
                sync_mgr = SyncManager(project_slug)
                hashes = sync_mgr.compute_checkout_hashes()
                sync_mgr.save_sync_cache(hashes)
                logger.debug(f"Saved {len(hashes)} file hashes to sync cache")

                # Make checkout read-only by default (unless --writable)
                if not (hasattr(args, 'writable') and args.writable):
                    make_readonly(target_dir)
                    logger.info("Checkout is read-only")
                else:
                    logger.info("Checkout is writable")
            except Exception as e:
                logger.warning(f"Could not set up sync cache or permissions: {e}")

            # Summary
            logger.info("Checkout complete!")
            print(f"   Files written: {files_written}")
            print(f"   Total size: {total_bytes:,} bytes ({total_bytes/1024/1024:.2f} MB)")
            print(f"   Location: {target_dir}")

            # Print mode info
            if hasattr(args, 'writable') and args.writable:
                print(f"   Mode: writable")
            else:
                print(f"   Mode: read-only")
                print(f"\n💡 To edit files:")
                print(f"   templedb vcs edit {project_slug}")

            return 0

        except Exception as e:
            logger.error(f"Checkout failed: {e}", exc_info=True)
            return 1


    def list_checkouts(self, args) -> int:
        """List all active checkouts for a project

        Args:
            args: Namespace with optional project_slug

        Returns:
            0 on success, 1 on error
        """
        try:
            if hasattr(args, 'project_slug') and args.project_slug:
                # List checkouts for specific project
                project = self.project_repo.get_by_slug(args.project_slug)
                if not project:
                    logger.error(f"Project '{args.project_slug}' not found")
                    return 1

                checkouts = self.checkout_repo.get_all_for_project(project['id'])

                print(f"\n📦 Checkouts for project: {args.project_slug}")
            else:
                # List all checkouts
                checkouts = self.checkout_repo.get_all()

                print(f"\n📦 All checkouts")

            if not checkouts:
                print("   No checkouts found")
                return 0

            print(f"\nID  | Project        | Path                      | Branch | Active | Last Sync")
            print("-" * 100)

            for co in checkouts:
                project_slug = co.get('project_slug', args.project_slug if hasattr(args, 'project_slug') else '?')
                active = "✓" if co['is_active'] else "✗"
                last_sync = co['last_sync_at'] if co['last_sync_at'] else "never"

                # Check if path still exists
                path_exists = Path(co['checkout_path']).exists()
                path_marker = "" if path_exists else " [MISSING]"

                print(f"{co['id']:<3} | {project_slug:<14} | {co['checkout_path']:<25}{path_marker} | {co['branch_name']:<6} | {active:<6} | {last_sync}")

            print()
            return 0

        except Exception as e:
            logger.error(f"Error listing checkouts: {e}", exc_info=True)
            return 1

    def cleanup_checkouts(self, args) -> int:
        """Remove stale checkouts (where directory no longer exists)

        Args:
            args: Namespace with optional project_slug and force flag

        Returns:
            0 on success, 1 on error
        """
        try:
            if hasattr(args, 'project_slug') and args.project_slug:
                # Cleanup for specific project
                project = self.project_repo.get_by_slug(args.project_slug)
                if not project:
                    logger.error(f"Project '{args.project_slug}' not found")
                    return 1

                logger.info(f"Cleaning up stale checkouts for: {args.project_slug}")
                stale_checkouts = self.checkout_repo.find_stale_checkouts(project['id'])
            else:
                # Cleanup all projects
                logger.info("Cleaning up stale checkouts for all projects")
                stale_checkouts = self.checkout_repo.find_stale_checkouts()

            if not stale_checkouts:
                print("   No stale checkouts found")
                return 0

            print(f"   Found {len(stale_checkouts)} stale checkout(s):")
            for co in stale_checkouts:
                print(f"      - {co['checkout_path']}")

            # Confirm deletion unless --force
            if not (hasattr(args, 'force') and args.force):
                response = input(f"\nRemove {len(stale_checkouts)} stale checkout(s)? (yes/no): ")
                if response.lower() != 'yes':
                    print("Cancelled")
                    return 0

            # Delete stale checkouts (CASCADE will remove snapshots)
            removed = 0
            for co in stale_checkouts:
                self.checkout_repo.delete(co['id'])
                removed += 1
                logger.info(f"Removed: {co['checkout_path']}")

            logger.info(f"Removed {removed} stale checkout(s)")
            return 0

        except Exception as e:
            logger.error(f"Error cleaning up checkouts: {e}", exc_info=True)
            return 1

    def status(self, args) -> int:
        """Show status of a checkout

        Shows:
        - Behind by N commits
        - Uncommitted changes
        - Last sync time
        """
        project_slug = args.project_slug
        checkout_path = Path(args.checkout_path).resolve()

        try:
            # Get project
            project = self.project_repo.get_by_slug(project_slug)
            if not project:
                logger.error(f"Project '{project_slug}' not found")
                return 1

            # Get checkout record
            checkout = self.checkout_repo.get_by_path(project['id'], str(checkout_path))

            if not checkout:
                logger.error(f"No checkout record found for {checkout_path}")
                logger.info(f"Run: templedb project checkout {project_slug} {checkout_path}")
                return 1

            print(f"📂 Checkout: {checkout_path}")
            print(f"   Project: {project_slug}")
            print(f"   Last sync: {checkout['last_sync_at']}")
            print()

            # Get snapshot versions
            snapshots = self.checkout_repo.execute("""
                SELECT COUNT(*) as count
                FROM checkout_snapshots
                WHERE checkout_id = ?
            """, (checkout['id'],))

            if snapshots:
                snapshot_count = snapshots[0]['count']
                print(f"   Tracked files: {snapshot_count}")

            # Check for uncommitted changes (files modified since checkout)
            from importer.content import ContentStore
            from importer.scanner import FileScanner

            scanner = FileScanner(checkout_path)
            scanned_files = scanner.scan_directory()

            modified_files = []
            added_files = []
            deleted_files = []

            # Get snapshots for comparison
            snapshots_dict = {}
            snapshot_rows = self.checkout_repo.execute("""
                SELECT
                    cs.file_id,
                    cs.content_hash,
                    cs.version,
                    pf.file_path
                FROM checkout_snapshots cs
                JOIN project_files pf ON cs.file_id = pf.id
                WHERE cs.checkout_id = ?
            """, (checkout['id'],))

            for row in snapshot_rows:
                snapshots_dict[row['file_path']] = row

            # Check scanned files
            for scanned_file in scanned_files:
                rel_path = str(scanned_file.relative_path)
                file_path = checkout_path / rel_path

                # Read current content
                content = ContentStore.read_file_content(file_path)
                if not content:
                    continue

                if rel_path not in snapshots_dict:
                    added_files.append(rel_path)
                else:
                    snapshot = snapshots_dict[rel_path]
                    if content.hash_sha256 != snapshot['content_hash']:
                        modified_files.append({
                            'path': rel_path,
                            'old_version': snapshot['version']
                        })

                    # Mark as seen
                    snapshots_dict.pop(rel_path)

            # Remaining in snapshots were deleted
            deleted_files = list(snapshots_dict.keys())

            # Display changes
            if added_files or modified_files or deleted_files:
                print(f"\n📝 Uncommitted changes:")

                if added_files:
                    print(f"\n   Added ({len(added_files)}):")
                    for path in added_files[:10]:
                        print(f"      + {path}")
                    if len(added_files) > 10:
                        print(f"      ... and {len(added_files) - 10} more")

                if modified_files:
                    print(f"\n   Modified ({len(modified_files)}):")
                    for item in modified_files[:10]:
                        print(f"      ~ {item['path']}")
                    if len(modified_files) > 10:
                        print(f"      ... and {len(modified_files) - 10} more")

                if deleted_files:
                    print(f"\n   Deleted ({len(deleted_files)}):")
                    for path in deleted_files[:10]:
                        print(f"      - {path}")
                    if len(deleted_files) > 10:
                        print(f"      ... and {len(deleted_files) - 10} more")

                print(f"\n💡 To commit: templedb project commit {project_slug} {checkout_path} -m 'message'")
            else:
                print(f"\n✅ No uncommitted changes")

            # Check if behind database
            from repositories import VCSRepository
            vcs_repo = VCSRepository()

            # Get latest commit in database
            latest_commit = vcs_repo.query_one("""
                SELECT id, commit_hash, commit_message, commit_timestamp
                FROM vcs_commits
                WHERE project_id = ?
                ORDER BY id DESC
                LIMIT 1
            """, (project['id'],))

            if latest_commit:
                # Check if checkout is at this version
                # (Simple check - could be improved with proper version tracking)
                print(f"\n📍 Latest database commit:")
                print(f"   {latest_commit['commit_hash'][:8]}: {latest_commit['commit_message'][:50]}")
                print(f"   {latest_commit['commit_timestamp']}")

            return 0

        except Exception as e:
            logger.error(f"Status check failed: {e}", exc_info=True)
            return 1

    def pull(self, args) -> int:
        """Pull latest changes from database to checkout

        Updates checkout with latest database version, merging with local changes
        """
        project_slug = args.project_slug
        checkout_path = Path(args.checkout_path).resolve()

        try:
            # Get project
            project = self.project_repo.get_by_slug(project_slug)
            if not project:
                logger.error(f"Project '{project_slug}' not found")
                return 1

            # Get checkout record
            checkout = self.checkout_repo.get_by_path(project['id'], str(checkout_path))

            if not checkout:
                logger.error(f"No checkout record found for {checkout_path}")
                return 1

            print(f"📥 Pulling latest changes to {checkout_path}...")

            # Get latest database files
            db_files = self.file_repo.get_files_for_project(project['id'], include_content=True)

            # Get checkout snapshots
            snapshots = {}
            snapshot_rows = self.checkout_repo.execute("""
                SELECT
                    cs.file_id,
                    cs.content_hash,
                    cs.version,
                    pf.file_path
                FROM checkout_snapshots cs
                JOIN project_files pf ON cs.file_id = pf.id
                WHERE cs.checkout_id = ?
            """, (checkout['id'],))

            for row in snapshot_rows:
                snapshots[row['file_path']] = row

            updated_count = 0
            conflict_count = 0

            # Update files
            for db_file in db_files:
                file_path = checkout_path / db_file['file_path']
                snapshot = snapshots.get(db_file['file_path'])

                # File new in database
                if not snapshot:
                    if not file_path.exists():
                        # Add file
                        file_path.parent.mkdir(parents=True, exist_ok=True)

                        if db_file['content_type'] == 'text':
                            file_path.write_text(db_file['content_text'])
                        else:
                            file_path.write_bytes(db_file['content_blob'])

                        print(f"   + Added: {db_file['file_path']}")
                        updated_count += 1
                    else:
                        print(f"   ⚠️  Conflict: {db_file['file_path']} (exists locally, not in snapshot)")
                        conflict_count += 1

                # File changed in database
                elif snapshot['content_hash'] != db_file['content_hash']:
                    # Check if also changed locally
                    from importer.content import ContentStore

                    local_content = ContentStore.read_file_content(file_path)

                    if local_content and local_content.hash_sha256 != snapshot['content_hash']:
                        # Both changed - conflict
                        print(f"   ⚠️  Conflict: {db_file['file_path']} (changed both locally and in database)")
                        conflict_count += 1
                    else:
                        # Only changed in database - safe to update
                        if db_file['content_type'] == 'text':
                            file_path.write_text(db_file['content_text'])
                        else:
                            file_path.write_bytes(db_file['content_blob'])

                        print(f"   ~ Updated: {db_file['file_path']}")
                        updated_count += 1

                        # Update snapshot
                        self.checkout_repo.record_snapshot(
                            checkout_id=checkout['id'],
                            file_id=db_file['file_id'],
                            content_hash=db_file['content_hash'],
                            version=db_file.get('version', 1)
                        )

            # Update checkout sync time
            self.checkout_repo.update_sync_time(checkout['id'])

            print(f"\n✅ Pull complete:")
            print(f"   Updated: {updated_count} files")

            if conflict_count > 0:
                print(f"   ⚠️  Conflicts: {conflict_count} files")
                print(f"\n💡 Resolve conflicts manually or use --force to overwrite")

            return 0

        except Exception as e:
            logger.error(f"Pull failed: {e}", exc_info=True)
            return 1

    def diff(self, args) -> int:
        """Show diff between checkout and database"""
        project_slug = args.project_slug
        checkout_path = Path(args.checkout_path).resolve()
        file_pattern = getattr(args, 'file', None)

        try:
            # Get project
            project = self.project_repo.get_by_slug(project_slug)
            if not project:
                logger.error(f"Project '{project_slug}' not found")
                return 1

            # Get checkout record
            checkout = self.checkout_repo.get_by_path(project['id'], str(checkout_path))

            if not checkout:
                logger.error(f"No checkout record found for {checkout_path}")
                return 1

            # Get database files
            db_files = self.file_repo.get_files_for_project(project['id'], include_content=True)
            db_by_path = {f['file_path']: f for f in db_files}

            # Get checkout snapshots
            snapshots = {}
            snapshot_rows = self.checkout_repo.execute("""
                SELECT
                    cs.file_id,
                    cs.content_hash,
                    pf.file_path
                FROM checkout_snapshots cs
                JOIN project_files pf ON cs.file_id = pf.id
                WHERE cs.checkout_id = ?
            """, (checkout['id'],))

            for row in snapshot_rows:
                snapshots[row['file_path']] = row

            # Find modified files
            from importer.content import ContentStore
            import difflib

            for file_path_str, snapshot in snapshots.items():
                # Filter by pattern if provided
                if file_pattern and file_pattern not in file_path_str:
                    continue

                file_path = checkout_path / file_path_str

                if not file_path.exists():
                    continue

                # Read local content
                local_content = ContentStore.read_file_content(file_path)
                if not local_content:
                    continue

                # Check if modified
                if local_content.hash_sha256 != snapshot['content_hash']:
                    # Get database version
                    db_file = db_by_path.get(file_path_str)
                    if not db_file:
                        continue

                    print(f"\n{'='*60}")
                    print(f"File: {file_path_str}")
                    print(f"{'='*60}")

                    # Show diff
                    if db_file['content_type'] == 'text' and local_content.content_type == 'text':
                        db_lines = db_file['content_text'].splitlines(keepends=True)
                        local_lines = local_content.content_text.splitlines(keepends=True)

                        diff = difflib.unified_diff(
                            db_lines,
                            local_lines,
                            fromfile=f"{file_path_str} (database)",
                            tofile=f"{file_path_str} (checkout)",
                            lineterm=''
                        )

                        for line in diff:
                            if line.startswith('+'):
                                print(f"\033[32m{line}\033[0m")  # Green
                            elif line.startswith('-'):
                                print(f"\033[31m{line}\033[0m")  # Red
                            elif line.startswith('@'):
                                print(f"\033[36m{line}\033[0m")  # Cyan
                            else:
                                print(line)
                    else:
                        print(f"   Binary file changed")
                        print(f"   Database: {len(db_file.get('content_blob', b''))} bytes")
                        print(f"   Checkout: {local_content.file_size} bytes")

            return 0

        except Exception as e:
            logger.error(f"Diff failed: {e}", exc_info=True)
            return 1


def main():
    """CLI entry point for testing"""
    import argparse

    parser = argparse.ArgumentParser(description='Checkout project from TempleDB')
    parser.add_argument('project_slug', help='Project slug')
    parser.add_argument('target_dir', help='Target directory for checkout')
    parser.add_argument('--force', '-f', action='store_true', help='Overwrite existing directory')

    args = parser.parse_args()

    cmd = CheckoutCommand()
    return cmd.checkout(args)


if __name__ == '__main__':
    sys.exit(main())
