#!/usr/bin/env python3
"""
Complete the partially-finished content deduplication migration

The previous migration created content_blobs and file_contents_backup,
but left file_contents empty. This script completes the migration.
"""

import os
import sys
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

DB_PATH = os.path.expanduser("~/.local/share/templedb/templedb.sqlite")


def main():
    print("="*70)
    print("Completing Content Deduplication Migration")
    print("="*70)

    # Backup first
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = f"{DB_PATH}.backup_{timestamp}"
    print(f"\n📦 Creating backup: {backup_path}")
    shutil.copy2(DB_PATH, backup_path)
    print(f"✓ Backup created")

    # Connect
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Check current state
    cursor.execute("SELECT COUNT(*) FROM file_contents")
    current_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM file_contents_backup")
    backup_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM content_blobs")
    blob_count = cursor.fetchone()[0]

    print(f"\n📊 Current State:")
    print(f"  file_contents: {current_count} records")
    print(f"  file_contents_backup: {backup_count} records")
    print(f"  content_blobs: {blob_count} blobs")

    if current_count > 0:
        print("\n✓ file_contents already populated. Migration complete!")
        return

    # Populate file_contents from backup
    print(f"\n🔄 Populating file_contents from backup...")

    cursor.execute("""
        INSERT INTO file_contents (
            id,
            file_id,
            content_hash,
            file_size_bytes,
            line_count,
            is_current,
            created_at,
            updated_at
        )
        SELECT
            id,
            file_id,
            hash_sha256 as content_hash,  -- Map hash_sha256 to content_hash
            file_size_bytes,
            line_count,
            is_current,
            created_at,
            updated_at
        FROM file_contents_backup
    """)

    conn.commit()

    # Verify
    cursor.execute("SELECT COUNT(*) FROM file_contents")
    new_count = cursor.fetchone()[0]

    if new_count != backup_count:
        raise Exception(f"Count mismatch! Expected {backup_count}, got {new_count}")

    # Update reference counts
    print(f"\n📊 Updating reference counts...")
    cursor.execute("""
        UPDATE content_blobs
        SET reference_count = (
            SELECT COUNT(*)
            FROM file_contents
            WHERE content_hash = content_blobs.hash_sha256
        )
    """)
    conn.commit()

    # Get stats
    cursor.execute("SELECT SUM(file_size_bytes) FROM content_blobs")
    blob_size = cursor.fetchone()[0] or 0

    cursor.execute("SELECT SUM(file_size_bytes) FROM file_contents_backup")
    old_size = cursor.fetchone()[0] or 0

    savings = old_size - blob_size
    percent = round(100.0 * savings / old_size, 2) if old_size > 0 else 0

    print(f"\n" + "="*70)
    print("✅ MIGRATION COMPLETE!")
    print("="*70)
    print(f"\nResults:")
    print(f"  Records migrated: {new_count:,}")
    print(f"  Unique blobs: {blob_count:,}")
    print(f"  Duplicates eliminated: {new_count - blob_count:,}")
    print(f"\nStorage:")
    print(f"  Before: {old_size:,} bytes ({old_size/1024/1024:.2f} MB)")
    print(f"  After: {blob_size:,} bytes ({blob_size/1024/1024:.2f} MB)")
    print(f"  Saved: {savings:,} bytes ({savings/1024/1024:.2f} MB)")
    print(f"  Reduction: {percent}%")
    print(f"\nBackup: {backup_path}")
    print("="*70)

    conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)
