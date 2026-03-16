#!/usr/bin/env python3
"""
Blob storage management commands
"""
import sys
import os
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
from cli.error_handling_utils import (
    handle_errors,
    ValidationError,
    print_warning
)

logger = get_logger(__name__)


class BlobCommands(Command):
    """Blob storage command handlers"""

    def __init__(self):
        super().__init__()
        self.repo = BaseRepository()
        self.store = ContentStore()

    @handle_errors("blob status")
    def status(self, args) -> int:
        """
        Show blob storage statistics

        Usage: ./templedb blob status [project]
        """
        project_filter = args.project if hasattr(args, 'project') and args.project else None

        print("📊 Blob Storage Status")
        print("=" * 70)

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
            stats = self.query_all(query, (project_filter,))
        else:
            stats = self.query_all("SELECT * FROM blob_storage_stats")

        if not stats:
            print(f"\n❌ No blobs found" + (f" for project '{project_filter}'" if project_filter else ""))
            return 1

        # Display statistics by storage location
        total_blobs = 0
        total_size = 0

        for row in stats:
            storage_location = row['storage_location']
            blob_count = row['blob_count']
            size_bytes = row['total_size_bytes'] or 0
            compressed_count = row.get('compressed_count', 0)

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
        migratable_result = self.query_one("SELECT COUNT(*) as count, SUM(file_size_bytes) as total_size FROM migratable_inline_blobs")
        if migratable_result and migratable_result['count'] > 0:
            print(f"\n💡 {migratable_result['count']:,} large inline blobs could be migrated to external storage")
            print(f"   Total size: {(migratable_result['total_size'] or 0) / 1024 / 1024:.2f} MB")
            print(f"   Run: ./templedb blob migrate --to-external")

        # Compression info
        if not ZSTD_AVAILABLE:
            print_warning("zstandard library not available - compression disabled")
            print(f"   Install: pip install zstandard")

        return 0

    @handle_errors("blob verify")
    def verify(self, args) -> int:
        """
        Verify blob integrity

        Usage: ./templedb blob verify [project] [--fix]
        """
        project_filter = args.project if hasattr(args, 'project') and args.project else None
        fix = args.fix if hasattr(args, 'fix') and args.fix else False

        print("🔍 Verifying Blob Integrity")
        print("=" * 70)

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
            blobs = self.query_all(query, (project_filter,))
        else:
            query = """
            SELECT hash_sha256, external_path, file_size_bytes
            FROM content_blobs
            WHERE storage_location = 'external'
            """
            blobs = self.query_all(query)

        if not blobs:
            print("\n✅ No external blobs to verify")
            return 0

        print(f"\nVerifying {len(blobs)} external blobs...")

        verified = 0
        missing = 0
        corrupted = 0
        errors = []

        for blob in blobs:
            content_hash = blob['hash_sha256']
            external_path = blob['external_path']
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

        return 0 if (missing == 0 and corrupted == 0) else 1

    @handle_errors("blob list")
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

        blobs = self.query_all(query, tuple(params))

        if not blobs:
            print("\n❌ No blobs found matching criteria")
            return 0

        # Display blobs
        for i, blob in enumerate(blobs, 1):
            hash_sha256 = blob['hash_sha256']
            size = blob['file_size_bytes']
            location = blob['storage_location']
            compression = blob.get('compression')
            content_type = blob.get('content_type', 'unknown')
            paths = blob.get('paths')

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

        return 0

    @handle_errors("blob migrate")
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
            raise ValidationError(
                "Must specify either --to-external or --to-inline\n"
                "Example: ./templedb blob migrate --to-external"
            )

        if to_external and to_inline:
            raise ValidationError(
                "Cannot specify both --to-external and --to-inline\n"
                "Choose one migration direction"
            )

        print("🔄 Blob Migration")
        print("=" * 70)
        print("\n⚠️  This feature will be implemented in Phase 2")
        print("   For now, new large files automatically use external storage")
        return 1


def register(cli):
    """Register blob commands as a single command group"""
    cmd = BlobCommands()

    # Main blob command with subcommands
    blob_parser = cli.register_command('blob', None, help_text='Manage blob storage')
    subparsers = blob_parser.add_subparsers(dest='blob_subcommand', required=True)

    # blob status
    status_parser = subparsers.add_parser('status', help='Show blob storage statistics')
    status_parser.add_argument('project', nargs='?', help='Project slug (optional)')
    cli.commands['blob.status'] = cmd.status

    # blob verify
    verify_parser = subparsers.add_parser('verify', help='Verify blob integrity')
    verify_parser.add_argument('project', nargs='?', help='Project slug (optional)')
    verify_parser.add_argument('--fix', action='store_true', help='Attempt to fix issues')
    verify_parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    cli.commands['blob.verify'] = cmd.verify

    # blob list
    list_parser = subparsers.add_parser('list', help='List large blobs')
    list_parser.add_argument('project', nargs='?', help='Project slug (optional)')
    list_parser.add_argument('--min-size', type=int, help='Minimum size in bytes (default: 10MB)')
    list_parser.add_argument('--storage-location', choices=['inline', 'external', 'remote'],
                           help='Filter by storage location')
    cli.commands['blob.list'] = cmd.list

    # blob migrate
    migrate_parser = subparsers.add_parser('migrate', help='Migrate blobs between storage tiers')
    migrate_parser.add_argument('project', nargs='?', help='Project slug (optional)')
    migrate_parser.add_argument('--to-external', action='store_true', help='Migrate to external storage')
    migrate_parser.add_argument('--to-inline', action='store_true', help='Migrate to inline storage')
    migrate_parser.add_argument('--min-size', type=int, help='Minimum size for migration')
    migrate_parser.add_argument('--max-size', type=int, help='Maximum size for migration')
    migrate_parser.add_argument('--dry-run', action='store_true', help='Show what would be migrated')
    cli.commands['blob.migrate'] = cmd.migrate
