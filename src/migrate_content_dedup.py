#!/usr/bin/env python3
"""
Content Deduplication Migration
Phase 1 of TempleDB Philosophy Implementation

This migration:
1. Creates content_blobs table (content-addressable storage)
2. Deduplicates content by SHA-256 hash
3. Updates file_contents to reference blobs
4. Reduces storage by ~75%

Safety:
- Creates full database backup before migration
- Keeps old table as file_contents_backup
- Verifies data integrity after migration
- Can be rolled back if needed
"""

import os
import sys
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

DB_PATH = os.path.expanduser("~/.local/share/templedb/templedb.sqlite")
MIGRATION_SQL = Path(__file__).parent.parent / "migrations" / "001_content_deduplication.sql"


def backup_database():
    """Create timestamped backup of database"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{DB_PATH}.backup_{timestamp}"

    print(f"📦 Creating backup: {backup_path}")
    shutil.copy2(DB_PATH, backup_path)

    # Verify backup
    backup_size = os.path.getsize(backup_path)
    original_size = os.path.getsize(DB_PATH)

    if backup_size != original_size:
        raise Exception(f"Backup verification failed! Sizes don't match.")

    print(f"✓ Backup created successfully ({backup_size:,} bytes)")
    return backup_path


def get_pre_migration_stats(conn):
    """Get statistics before migration"""
    cursor = conn.cursor()

    stats = {}

    # Total file_contents records
    cursor.execute("SELECT COUNT(*) FROM file_contents")
    stats['total_records'] = cursor.fetchone()[0]

    # Unique hashes (column is content_hash, not hash_sha256)
    cursor.execute("SELECT COUNT(DISTINCT content_hash) FROM file_contents")
    stats['unique_hashes'] = cursor.fetchone()[0]

    # Total size
    cursor.execute("SELECT SUM(file_size_bytes) FROM file_contents")
    stats['total_bytes'] = cursor.fetchone()[0] or 0

    # Duplicates
    stats['duplicates'] = stats['total_records'] - stats['unique_hashes']
    stats['dedup_percent'] = round(100.0 * stats['duplicates'] / stats['total_records'], 2) if stats['total_records'] > 0 else 0

    return stats


def run_migration(conn):
    """Execute migration SQL"""
    print("\n🔄 Running migration...")

    # Read migration SQL
    with open(MIGRATION_SQL, 'r') as f:
        migration_sql = f.read()

    cursor = conn.cursor()

    try:
        # Use executescript which handles multiple statements correctly
        print("  Executing migration SQL...")
        cursor.executescript(migration_sql)
        conn.commit()
        print("✓ Migration completed successfully")
    except sqlite3.Error as e:
        print(f"✗ Error during migration: {e}")
        raise


def verify_migration(conn):
    """Verify migration was successful"""
    print("\n🔍 Verifying migration...")

    cursor = conn.cursor()

    # Check tables exist
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('content_blobs', 'file_contents', 'file_contents_backup')")
    tables = {row[0] for row in cursor.fetchall()}

    required_tables = {'content_blobs', 'file_contents', 'file_contents_backup'}
    if not required_tables.issubset(tables):
        missing = required_tables - tables
        raise Exception(f"Migration verification failed! Missing tables: {missing}")

    # Check record counts match
    cursor.execute("SELECT COUNT(*) FROM file_contents")
    new_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM file_contents_backup")
    old_count = cursor.fetchone()[0]

    if new_count != old_count:
        raise Exception(f"Record count mismatch! Old: {old_count}, New: {new_count}")

    # Check all file_ids preserved
    cursor.execute("SELECT COUNT(DISTINCT file_id) FROM file_contents")
    new_files = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT file_id) FROM file_contents_backup")
    old_files = cursor.fetchone()[0]

    if new_files != old_files:
        raise Exception(f"File ID count mismatch! Old: {old_files}, New: {new_files}")

    # Check content_blobs has expected deduplication
    cursor.execute("SELECT COUNT(*) FROM content_blobs")
    blob_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(DISTINCT content_hash) FROM file_contents_backup")
    expected_blobs = cursor.fetchone()[0]

    if blob_count != expected_blobs:
        raise Exception(f"Blob count mismatch! Expected: {expected_blobs}, Got: {blob_count}")

    print("✓ Migration verified successfully")


def get_post_migration_stats(conn):
    """Get statistics after migration"""
    cursor = conn.cursor()

    stats = {}

    # Total file_contents records
    cursor.execute("SELECT COUNT(*) FROM file_contents")
    stats['total_records'] = cursor.fetchone()[0]

    # Total content_blobs
    cursor.execute("SELECT COUNT(*) FROM content_blobs")
    stats['unique_blobs'] = cursor.fetchone()[0]

    # New total size (blobs only, deduplicated)
    cursor.execute("SELECT SUM(file_size_bytes) FROM content_blobs")
    stats['blob_bytes'] = cursor.fetchone()[0] or 0

    # Old total size
    cursor.execute("SELECT SUM(file_size_bytes) FROM file_contents_backup")
    stats['old_bytes'] = cursor.fetchone()[0] or 0

    # Savings
    stats['bytes_saved'] = stats['old_bytes'] - stats['blob_bytes']
    stats['percent_saved'] = round(100.0 * stats['bytes_saved'] / stats['old_bytes'], 2) if stats['old_bytes'] > 0 else 0

    return stats


def print_stats_comparison(pre, post):
    """Print before/after statistics"""
    print("\n" + "="*70)
    print("📊 MIGRATION RESULTS")
    print("="*70)

    print("\nBEFORE:")
    print(f"  Total records: {pre['total_records']:,}")
    print(f"  Unique hashes: {pre['unique_hashes']:,}")
    print(f"  Duplicates: {pre['duplicates']:,} ({pre['dedup_percent']}%)")
    print(f"  Total size: {pre['total_bytes']:,} bytes ({pre['total_bytes']/1024/1024:.2f} MB)")

    print("\nAFTER:")
    print(f"  Total records: {post['total_records']:,}")
    print(f"  Unique blobs: {post['unique_blobs']:,}")
    print(f"  Blob storage: {post['blob_bytes']:,} bytes ({post['blob_bytes']/1024/1024:.2f} MB)")

    print("\nSAVINGS:")
    print(f"  Space saved: {post['bytes_saved']:,} bytes ({post['bytes_saved']/1024/1024:.2f} MB)")
    print(f"  Reduction: {post['percent_saved']}%")
    print(f"  Records eliminated: {post['total_records'] - post['unique_blobs']:,}")

    print("\n" + "="*70)


def main():
    """Run content deduplication migration"""
    print("="*70)
    print("TempleDB Content Deduplication Migration")
    print("Phase 1: Eliminate Duplication, Implement Normalization")
    print("="*70)

    # Check database exists
    if not os.path.exists(DB_PATH):
        print(f"✗ Database not found: {DB_PATH}")
        sys.exit(1)

    # Check migration SQL exists
    if not os.path.exists(MIGRATION_SQL):
        print(f"✗ Migration SQL not found: {MIGRATION_SQL}")
        sys.exit(1)

    try:
        # Step 1: Backup
        backup_path = backup_database()

        # Step 2: Connect to database
        print(f"\n🔌 Connecting to database...")
        conn = sqlite3.connect(DB_PATH)
        conn.execute("PRAGMA foreign_keys = ON")

        # Step 3: Get pre-migration stats
        print("\n📈 Gathering pre-migration statistics...")
        pre_stats = get_pre_migration_stats(conn)

        # Step 4: Run migration
        run_migration(conn)

        # Step 5: Verify migration
        verify_migration(conn)

        # Step 6: Get post-migration stats
        print("\n📉 Gathering post-migration statistics...")
        post_stats = get_post_migration_stats(conn)

        # Step 7: Print results
        print_stats_comparison(pre_stats, post_stats)

        # Step 8: Cleanup (optional - keep backup for safety)
        print(f"\n✓ Migration completed successfully!")
        print(f"\nBackup retained at: {backup_path}")
        print(f"Old table retained as: file_contents_backup")
        print(f"\nTo rollback:")
        print(f"  1. Restore from backup: cp {backup_path} {DB_PATH}")
        print(f"  2. Or use SQL: DROP TABLE file_contents; ALTER TABLE file_contents_backup RENAME TO file_contents;")

        conn.close()

    except Exception as e:
        print(f"\n✗ Migration failed: {e}")
        print(f"\nDatabase backup available at: {backup_path}")
        print(f"To restore: cp {backup_path} {DB_PATH}")
        sys.exit(1)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Content deduplication migration")
    parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompt')
    args = parser.parse_args()

    # Confirmation prompt
    print("\nThis migration will:")
    print("  1. Create a backup of your database")
    print("  2. Deduplicate file content (eliminate ~75% duplication)")
    print("  3. Create new content_blobs table")
    print("  4. Update file_contents to reference blobs")
    print("  5. Keep old table as backup")

    if not args.yes:
        try:
            response = input("\nProceed with migration? [y/N]: ").strip().lower()
            if response != 'y':
                print("Migration cancelled.")
                sys.exit(0)
        except EOFError:
            print("\nNo input detected. Use --yes flag to skip prompt.")
            sys.exit(1)

    main()
