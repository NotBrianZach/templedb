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

from db_utils import query_one, query_all, execute, transaction


class CheckoutCommand:
    """Handles checkout operations - extracting projects from DB to filesystem"""

    def checkout(self, args) -> int:
        """Checkout project from database to filesystem

        Args:
            args: Namespace with project_slug and target_dir

        Returns:
            0 on success, 1 on error
        """
        project_slug = args.project_slug
        target_dir = Path(args.target_dir).resolve()

        print(f"📦 Checking out project: {project_slug}")
        print(f"📁 Target directory: {target_dir}")

        try:
            # Get project
            project = query_one("SELECT id, name FROM projects WHERE slug = ?", (project_slug,))
            if not project:
                print(f"✗ Error: Project '{project_slug}' not found", file=sys.stderr)
                return 1

            # Check if target directory exists and is not empty
            if target_dir.exists() and any(target_dir.iterdir()):
                if not args.force:
                    print(f"✗ Error: Target directory is not empty: {target_dir}", file=sys.stderr)
                    print(f"   Use --force to overwrite", file=sys.stderr)
                    return 1
                else:
                    print(f"⚠️  Warning: Overwriting existing directory")

            # Create target directory
            target_dir.mkdir(parents=True, exist_ok=True)

            # Get all current files with their content
            print(f"\n🔍 Loading files from database...")
            files = query_all("""
                SELECT
                    pf.id as file_id,
                    pf.file_path,
                    fc.content_hash,
                    cb.content_text,
                    cb.content_blob,
                    cb.content_type,
                    cb.encoding,
                    cb.file_size_bytes
                FROM project_files pf
                JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
                JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
                WHERE pf.project_id = ?
                ORDER BY pf.file_path
            """, (project['id'],))

            if not files:
                print(f"⚠️  Warning: No files found in project")
                return 0

            # Write files to filesystem
            print(f"📄 Writing {len(files)} files to filesystem...")
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
                    print(f"⚠️  Warning: Failed to write {file['file_path']}: {e}", file=sys.stderr)

            # Record checkout in database and snapshot versions
            with transaction():
                # Insert or update checkout record
                checkout_id = execute("""
                    INSERT OR REPLACE INTO checkouts
                    (project_id, checkout_path, branch_name, checkout_at, is_active)
                    VALUES (?, ?, 'main', datetime('now'), 1)
                """, (project['id'], str(target_dir)), commit=False)

                # Clear old snapshots for this checkout
                execute("""
                    DELETE FROM checkout_snapshots
                    WHERE checkout_id = ?
                """, (checkout_id,), commit=False)

                # Record snapshot of file versions
                for file in files:
                    execute("""
                        INSERT INTO checkout_snapshots
                        (checkout_id, file_id, content_hash, version)
                        VALUES (?, ?, ?, (
                            SELECT version FROM file_contents
                            WHERE file_id = ? AND is_current = 1
                        ))
                    """, (checkout_id, file['file_id'], file['content_hash'], file['file_id']), commit=False)

            # Summary
            print(f"\n✅ Checkout complete!")
            print(f"   Files written: {files_written}")
            print(f"   Total size: {total_bytes:,} bytes ({total_bytes/1024/1024:.2f} MB)")
            print(f"   Location: {target_dir}")

            return 0

        except Exception as e:
            print(f"\n✗ Checkout failed: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
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
                project = query_one("SELECT id, slug, name FROM projects WHERE slug = ?", (args.project_slug,))
                if not project:
                    print(f"✗ Error: Project '{args.project_slug}' not found", file=sys.stderr)
                    return 1

                checkouts = query_all("""
                    SELECT
                        id,
                        checkout_path,
                        branch_name,
                        checkout_at,
                        last_sync_at,
                        is_active
                    FROM checkouts
                    WHERE project_id = ?
                    ORDER BY checkout_at DESC
                """, (project['id'],))

                print(f"\n📦 Checkouts for project: {args.project_slug}")
            else:
                # List all checkouts
                checkouts = query_all("""
                    SELECT
                        c.id,
                        p.slug AS project_slug,
                        c.checkout_path,
                        c.branch_name,
                        c.checkout_at,
                        c.last_sync_at,
                        c.is_active
                    FROM checkouts c
                    JOIN projects p ON c.project_id = p.id
                    ORDER BY c.checkout_at DESC
                """)

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
            print(f"✗ Error listing checkouts: {e}", file=sys.stderr)
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
                project = query_one("SELECT id, slug FROM projects WHERE slug = ?", (args.project_slug,))
                if not project:
                    print(f"✗ Error: Project '{args.project_slug}' not found", file=sys.stderr)
                    return 1

                checkouts = query_all("""
                    SELECT id, checkout_path
                    FROM checkouts
                    WHERE project_id = ?
                """, (project['id'],))

                print(f"\n🧹 Cleaning up stale checkouts for: {args.project_slug}")
            else:
                # Cleanup all projects
                checkouts = query_all("SELECT id, checkout_path FROM checkouts")
                print(f"\n🧹 Cleaning up stale checkouts for all projects")

            stale_checkouts = []
            for co in checkouts:
                if not Path(co['checkout_path']).exists():
                    stale_checkouts.append(co)

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
                execute("DELETE FROM checkouts WHERE id = ?", (co['id'],))
                removed += 1
                print(f"   ✓ Removed: {co['checkout_path']}")

            print(f"\n✅ Removed {removed} stale checkout(s)")
            return 0

        except Exception as e:
            print(f"✗ Error cleaning up checkouts: {e}", file=sys.stderr)
            import traceback
            traceback.print_exc()
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
