#!/usr/bin/env python3
"""
Migrate existing checkouts to read-only mode with sync cache

This script:
1. Finds all existing checkouts
2. Computes file hashes and saves to sync cache
3. Makes checkouts read-only
4. Cleans up any stale edit sessions
"""
import sys
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

# Import after path setup
from db_utils import get_connection
from sync import SyncManager, make_readonly
from repositories.project_repository import ProjectRepository
from repositories.checkout_repository import CheckoutRepository
from logger import get_logger

logger = get_logger(__name__)


def migrate_checkouts():
    """Migrate all existing checkouts to read-only mode"""
    checkout_repo = CheckoutRepository()
    project_repo = ProjectRepository()

    # Get all checkouts
    checkouts = checkout_repo.get_all()

    if not checkouts:
        print("No checkouts found")
        return

    print(f"Found {len(checkouts)} checkout(s) to migrate\n")

    migrated = 0
    skipped = 0
    failed = 0

    for checkout in checkouts:
        checkout_path = Path(checkout['checkout_path'])
        project_slug = checkout['project_slug']

        # Get project to verify it exists
        project = project_repo.get_by_slug(project_slug)
        if not project:
            logger.warning(f"Project not found for checkout: {checkout_path}")
            skipped += 1
            continue

        print(f"Migrating: {project_slug}")
        print(f"  Path: {checkout_path}")

        # Check if path exists
        if not checkout_path.exists():
            logger.warning(f"  Checkout path does not exist, skipping")
            skipped += 1
            continue

        try:
            # Initialize sync manager
            sync_mgr = SyncManager(project_slug)

            # Compute and save file hashes
            print(f"  Computing file hashes...")
            hashes = sync_mgr.compute_checkout_hashes(checkout_path)
            sync_mgr.save_sync_cache(hashes)
            print(f"  ✓ Saved {len(hashes)} file hashes to sync cache")

            # Make read-only
            print(f"  Making read-only...")
            make_readonly(checkout_path)
            print(f"  ✓ Checkout is now read-only")

            migrated += 1
            print()

        except Exception as e:
            logger.error(f"  Failed to migrate: {e}")
            failed += 1
            print()

    # Clean up stale edit sessions
    print("Cleaning up stale edit sessions...")
    cleanup_count = 0
    for project in project_repo.get_all():
        try:
            sync_mgr = SyncManager(project['slug'])
            count = sync_mgr.cleanup_stale_sessions()
            cleanup_count += count
        except Exception as e:
            logger.debug(f"Could not cleanup sessions for {project['slug']}: {e}")

    if cleanup_count > 0:
        print(f"✓ Cleaned up {cleanup_count} stale edit session(s)")

    # Summary
    print()
    print("Migration complete!")
    print(f"  Migrated: {migrated}")
    print(f"  Skipped: {skipped}")
    print(f"  Failed: {failed}")
    print()
    print("All checkouts are now read-only.")
    print("To edit a project, use: templedb vcs edit <project>")


if __name__ == '__main__':
    migrate_checkouts()
