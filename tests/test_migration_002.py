#!/usr/bin/env python3
"""
Integration test for migration 002 - Large Blob Support

Verifies that migration 002 was applied correctly and
the database schema is ready for external blob storage.
"""

import unittest
import sqlite3
import os
from pathlib import Path


class TestMigration002(unittest.TestCase):
    """Test migration 002 database changes"""

    @classmethod
    def setUpClass(cls):
        """Connect to the database"""
        db_path = os.path.expanduser("~/.local/share/templedb/templedb.sqlite")
        if not os.path.exists(db_path):
            raise unittest.SkipTest("Database not found, skipping migration test")
        cls.conn = sqlite3.connect(db_path)
        cls.cursor = cls.conn.cursor()

    @classmethod
    def tearDownClass(cls):
        """Close database connection"""
        cls.conn.close()

    def test_new_columns_exist(self):
        """Migration 002 should add new columns to content_blobs"""
        self.cursor.execute("PRAGMA table_info(content_blobs)")
        columns = {row[1]: row[2] for row in self.cursor.fetchall()}

        # Check new columns exist
        self.assertIn('storage_location', columns)
        self.assertIn('external_path', columns)
        self.assertIn('chunk_count', columns)
        self.assertIn('compression', columns)
        self.assertIn('remote_url', columns)
        self.assertIn('fetch_count', columns)
        self.assertIn('last_fetched_at', columns)

    def test_all_existing_blobs_inline(self):
        """All existing blobs should be marked as 'inline'"""
        self.cursor.execute("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN storage_location = 'inline' THEN 1 ELSE 0 END) as inline_count
            FROM content_blobs
        """)
        total, inline_count = self.cursor.fetchone()

        if total > 0:
            self.assertEqual(total, inline_count,
                           "All existing blobs should be 'inline'")

    def test_indexes_created(self):
        """Migration 002 should create performance indexes"""
        self.cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name LIKE '%blob%'
        """)
        indexes = [row[0] for row in self.cursor.fetchall()]

        # Check expected indexes exist
        expected_indexes = [
            'idx_content_blobs_storage_location',
            'idx_content_blobs_size',
            'idx_content_blobs_external_path',
            'idx_content_blobs_fetch_count'
        ]

        for index_name in expected_indexes:
            self.assertIn(index_name, indexes,
                         f"Index {index_name} should exist")

    def test_views_created(self):
        """Migration 002 should create statistics views"""
        self.cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='view' AND name LIKE '%blob%'
        """)
        views = [row[0] for row in self.cursor.fetchall()]

        # Check expected views exist
        expected_views = [
            'blob_storage_stats',
            'external_blobs_view',
            'migratable_inline_blobs'
        ]

        for view_name in expected_views:
            self.assertIn(view_name, views,
                         f"View {view_name} should exist")

    def test_blob_storage_stats_view_works(self):
        """blob_storage_stats view should return valid data"""
        self.cursor.execute("SELECT * FROM blob_storage_stats")
        rows = self.cursor.fetchall()

        # Should have at least one row (for 'inline' storage)
        self.assertGreater(len(rows), 0)

        # Check columns are present
        self.cursor.execute("PRAGMA table_info(blob_storage_stats)")
        columns = [row[1] for row in self.cursor.fetchall()]

        expected_columns = [
            'storage_location', 'blob_count', 'total_size_bytes',
            'avg_size_bytes', 'min_size_bytes', 'max_size_bytes',
            'compressed_count'
        ]

        for col in expected_columns:
            self.assertIn(col, columns)

    def test_no_existing_external_blobs(self):
        """Fresh migration should have no external blobs"""
        self.cursor.execute("""
            SELECT COUNT(*) FROM content_blobs
            WHERE storage_location = 'external'
        """)
        count = self.cursor.fetchone()[0]
        self.assertEqual(count, 0, "Should have no external blobs after migration")

    def test_storage_location_constraint(self):
        """storage_location should enforce valid values"""
        # Try to insert invalid storage_location
        with self.assertRaises(sqlite3.IntegrityError):
            self.cursor.execute("""
                INSERT INTO content_blobs (
                    hash_sha256, storage_location, content_type, file_size_bytes
                )
                VALUES ('testinvalidlocation', 'invalid', 'text', 100)
            """)
            self.conn.commit()

        # Rollback the failed transaction
        self.conn.rollback()

    def test_compression_constraint(self):
        """compression should enforce valid values"""
        # Try to insert invalid compression
        with self.assertRaises(sqlite3.IntegrityError):
            self.cursor.execute("""
                INSERT INTO content_blobs (
                    hash_sha256, storage_location, content_type,
                    file_size_bytes, compression
                )
                VALUES ('testinvalidcompression', 'inline', 'text', 100, 'invalid')
            """)
            self.conn.commit()

        # Rollback the failed transaction
        self.conn.rollback()


def run_tests():
    """Run migration tests"""
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestMigration002)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == '__main__':
    import sys
    success = run_tests()
    sys.exit(0 if success else 1)
