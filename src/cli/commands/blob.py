#!/usr/bin/env python3
"""
Blob storage management commands
"""
import sys
import os
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Tuple

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from db_utils import DB_PATH
from repositories import BaseRepository
from cli.core import Command
from logger import get_logger
import config
from importer.content import ContentStore, ZSTD_AVAILABLE

logger = get_logger(__name__)


class BlobCommands(Command):
    """Blob storage command handlers"""

    def __init__(self):
        super().__init__()
        self.repo = BaseRepository()
        self.store = ContentStore()

    def status(self, args) -> int:
        """
        Show blob storage statistics

        Usage: ./templedb blob status [project]
        """
        project_filter = args.project if hasattr(args, 'project') and args.project else None

        print("📊 Blob Storage Status")
        print("=" * 70)

        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()

            # Overall statistics
            if project_filter:
                query = """
                SELECT
                    cb.storage_location,
                    COUNT(*) as blob_count,
                    SUM(cb.file_size_bytes) as total_bytes,
                    SUM(CASE WHEN cb.compression IS NOT NULL THEN 1 ELSE 0 END) as compressed_count
                FROM content_blobs cb
                JOIN file_contents fc ON cb.hash_sha256 = fc.content_hash
                JOIN project_files pf ON fc.file_id = pf.id
                JOIN projects p ON pf.project_id = p.id
                WHERE p.slug = ?
                GROUP BY cb.storage_location
                """
                cursor.execute(query, (project_filter,))
            else:
                cursor.execute("SELECT * FROM blob_storage_stats")

            stats = cursor.fetchall()

            if not stats:
                print(f"\n❌ No blobs found" + (f" for project '{project_filter}'" if project_filter else ""))
                conn.close()
                return 1

            # Display statistics by storage location
            total_blobs = 0
            total_size = 0

            for row in stats:
                storage_location = row[0]
                blob_count = row[1]
                size_bytes = row[2] or 0
                compressed_count = row[6] if len(row) > 6 else row[3]

                total_blobs += blob_count
                total_size += size_bytes

                size_mb = size_bytes / 1024 / 1024
                avg_size_mb = size_mb / blob_count if blob_count > 0 else 0

                icon = "💾" if storage_location == "inline" else "📁" if storage_location == "external" else "☁️"

                print(f"\n{icon} {storage_location.upper()} Storage:")
                print(f"  Files: {blob_count:,}")
                print(f"  Total Size: {size_mb:.2f} MB")
                print(f"  Average Size: {avg_size_mb:.2f} MB")
                if compressed_count > 0:
                    print(f"  Compressed: {compressed_count:,} files")

            # Total summary
            print(f"\n{'─' * 70}")
            print(f"Total: {total_blobs:,} blobs, {total_size / 1024 / 1024:.2f} MB")

            # Database size
            db_size = Path(DB_PATH).stat().st_size
            print(f"Database: {db_size / 1024 / 1024:.2f} MB")

            # Blob directory size
            blob_dir = Path(config.BLOB_STORAGE_DIR)
            if blob_dir.exists():
                blob_dir_size = sum(f.stat().st_size for f in blob_dir.rglob('*') if f.is_file())
                print(f"Blob Directory: {blob_dir_size / 1024 / 1024:.2f} MB")

            # Migratable blobs
            cursor.execute("SELECT COUNT(*), SUM(file_size_bytes) FROM migratable_inline_blobs")
            migratable_count, migratable_size = cursor.fetchone()
            if migratable_count and migratable_count > 0:
                print(f"\n💡 {migratable_count:,} large inline blobs could be migrated to external storage")
                print(f"   Total size: {(migratable_size or 0) / 1024 / 1024:.2f} MB")
                print(f"   Run: ./templedb blob migrate --to-external")

            # Compression info
            if not ZSTD_AVAILABLE:
                print(f"\n⚠️  zstandard library not available - compression disabled")
                print(f"   Install: pip install zstandard")

            conn.close()
            return 0

        except Exception as e:
            logger.error(f"Error retrieving blob status: {e}")
            print(f"❌ Error: {e}")
            return 1

    def verify(self, args) -> int:
        """
        Verify blob integrity

        Usage: ./templedb blob verify [project] [--fix]
        """
        project_filter = args.project if hasattr(args, 'project') and args.project else None
        fix = args.fix if hasattr(args, 'fix') and args.fix else False

        print("🔍 Verifying Blob Integrity")
        print("=" * 70)

        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()

            # Get external blobs to verify
            if project_filter:
                query = """
                SELECT DISTINCT cb.hash_sha256, cb.external_path, cb.file_size_bytes
                FROM content_blobs cb
                JOIN file_contents fc ON cb.hash_sha256 = fc.content_hash
                JOIN project_files pf ON fc.file_id = pf.id
                JOIN projects p ON pf.project_id = p.id
                WHERE cb.storage_location = 'external'
                  AND p.slug = ?
                """
                cursor.execute(query, (project_filter,))
            else:
                query = """
                SELECT hash_sha256, external_path, file_size_bytes
                FROM content_blobs
                WHERE storage_location = 'external'
                """
                cursor.execute(query)

            blobs = cursor.fetchall()

            if not blobs:
                print("\n✅ No external blobs to verify")
                conn.close()
                return 0

            print(f"\nVerifying {len(blobs)} external blobs...")

            verified = 0
            missing = 0
            corrupted = 0
            errors = []

            for content_hash, external_path, file_size in blobs:
                is_valid, error = self.store.verify_blob(content_hash, external_path)

                if is_valid:
                    verified += 1
                    if args.verbose if hasattr(args, 'verbose') else False:
                        print(f"  ✓ {content_hash[:16]}...")
                elif "not found" in error.lower():
                    missing += 1
                    errors.append((content_hash, external_path, error))
                    print(f"  ❌ MISSING: {content_hash[:16]}... - {external_path}")
                else:
                    corrupted += 1
                    errors.append((content_hash, external_path, error))
                    print(f"  ⚠️  CORRUPT: {content_hash[:16]}... - {error}")

            # Summary
            print(f"\n{'─' * 70}")
            print(f"✅ Verified: {verified}")
            if missing > 0:
                print(f"❌ Missing: {missing}")
            if corrupted > 0:
                print(f"⚠️  Corrupted: {corrupted}")

            if errors and not fix:
                print(f"\n💡 To attempt recovery, run with --fix flag")

            conn.close()
            return 0 if (missing == 0 and corrupted == 0) else 1

        except Exception as e:
            logger.error(f"Error verifying blobs: {e}")
            print(f"❌ Error: {e}")
            return 1

    def list(self, args) -> int:
        """
        List large blobs

        Usage: ./templedb blob list [--min-size SIZE] [--storage-location LOC] [project]
        """
        project_filter = args.project if hasattr(args, 'project') and args.project else None
        min_size = args.min_size if hasattr(args, 'min_size') and args.min_size else 10 * 1024 * 1024  # 10MB default
        storage_location = args.storage_location if hasattr(args, 'storage_location') and args.storage_location else None

        print(f"📋 Large Blobs (>{min_size / 1024 / 1024:.0f}MB)")
        print("=" * 70)

        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()

            # Build query
            conditions = []
            params = []

            # Add size filter
            conditions.append("file_size_bytes >= ?")
            params.append(min_size)

            if storage_location:
                conditions.append("storage_location = ?")
                params.append(storage_location)

            where_clause = " AND ".join(conditions)

            if project_filter:
                query = f"""
                SELECT DISTINCT
                    cb.hash_sha256,
                    cb.file_size_bytes,
                    cb.storage_location,
                    cb.compression,
                    cb.content_type,
                    GROUP_CONCAT(pf.file_path, ', ') as paths
                FROM content_blobs cb
                JOIN file_contents fc ON cb.hash_sha256 = fc.content_hash
                JOIN project_files pf ON fc.file_id = pf.id
                JOIN projects p ON pf.project_id = p.id
                WHERE cb.{where_clause}
                  AND p.slug = ?
                GROUP BY cb.hash_sha256
                ORDER BY cb.file_size_bytes DESC
                """
                params.append(project_filter)
            else:
                query = f"""
                SELECT
                    hash_sha256,
                    file_size_bytes,
                    storage_location,
                    compression,
                    content_type,
                    NULL as paths
                FROM content_blobs
                WHERE {where_clause}
                ORDER BY file_size_bytes DESC
                """

            cursor.execute(query, params)
            blobs = cursor.fetchall()

            if not blobs:
                print("\n❌ No blobs found matching criteria")
                conn.close()
                return 0

            # Display blobs
            for i, (hash_sha256, size, location, compression, content_type, paths) in enumerate(blobs, 1):
                size_mb = size / 1024 / 1024
                comp_str = f" ({compression})" if compression else ""
                icon = "💾" if location == "inline" else "📁"

                print(f"\n{i}. {icon} {hash_sha256[:16]}...{comp_str}")
                print(f"   Size: {size_mb:.2f} MB | Type: {content_type} | Location: {location}")
                if paths:
                    # Show first few paths
                    path_list = paths.split(', ')
                    shown_paths = path_list[:3]
                    for path in shown_paths:
                        print(f"   📄 {path}")
                    if len(path_list) > 3:
                        print(f"   ... and {len(path_list) - 3} more")

            print(f"\n{'─' * 70}")
            print(f"Total: {len(blobs)} blobs")

            conn.close()
            return 0

        except Exception as e:
            logger.error(f"Error listing blobs: {e}")
            print(f"❌ Error: {e}")
            return 1

    def migrate(self, args) -> int:
        """
        Migrate blobs between storage locations

        Usage:
          ./templedb blob migrate --to-external [--min-size SIZE] [project]
          ./templedb blob migrate --to-inline [--max-size SIZE] [project]
        """
        to_external = args.to_external if hasattr(args, 'to_external') and args.to_external else False
        to_inline = args.to_inline if hasattr(args, 'to_inline') and args.to_inline else False

        if not to_external and not to_inline:
            print("❌ Error: Must specify --to-external or --to-inline")
            return 1

        if to_external and to_inline:
            print("❌ Error: Cannot specify both --to-external and --to-inline")
            return 1

        print("🔄 Blob Migration")
        print("=" * 70)
        print("\n⚠️  This feature will be implemented in Phase 2")
        print("   For now, new large files automatically use external storage")
        return 1


def register(cli):
    """Register blob commands"""
    cmd = BlobCommands()

    # blob status
    status_parser = cli.register_command('blob-status', cmd.status, help_text='Show blob storage statistics')
    status_parser.add_argument('project', nargs='?', help='Project slug (optional)')

    # blob verify
    verify_parser = cli.register_command('blob-verify', cmd.verify, help_text='Verify blob integrity')
    verify_parser.add_argument('project', nargs='?', help='Project slug (optional)')
    verify_parser.add_argument('--fix', action='store_true', help='Attempt to fix issues')
    verify_parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    # blob list
    list_parser = cli.register_command('blob-list', cmd.list, help_text='List large blobs')
    list_parser.add_argument('project', nargs='?', help='Project slug (optional)')
    list_parser.add_argument('--min-size', type=int, help='Minimum size in bytes (default: 10MB)')
    list_parser.add_argument('--storage-location', choices=['inline', 'external', 'remote'],
                           help='Filter by storage location')

    # blob migrate
    migrate_parser = cli.register_command('blob-migrate', cmd.migrate, help_text='Migrate blobs between storage tiers')
    migrate_parser.add_argument('project', nargs='?', help='Project slug (optional)')
    migrate_parser.add_argument('--to-external', action='store_true', help='Migrate to external storage')
    migrate_parser.add_argument('--to-inline', action='store_true', help='Migrate to inline storage')
    migrate_parser.add_argument('--min-size', type=int, help='Minimum size for migration')
    migrate_parser.add_argument('--max-size', type=int, help='Maximum size for migration')
    migrate_parser.add_argument('--dry-run', action='store_true', help='Show what would be migrated')
