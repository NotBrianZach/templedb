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

            # Summary
            logger.info("Checkout complete!")
            print(f"   Files written: {files_written}")
            print(f"   Total size: {total_bytes:,} bytes ({total_bytes/1024/1024:.2f} MB)")
            print(f"   Location: {target_dir}")

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
