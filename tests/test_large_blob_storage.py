#!/usr/bin/env python3
"""
Unit tests for large blob storage (Phase 1)

Tests the new external blob storage functionality:
- Inline storage for small files (<10MB)
- External storage for large files (>10MB)
- Hash calculation and verification
- Blob retrieval and integrity checking
"""

import unittest
import tempfile
import shutil
import os
from pathlib import Path
import sys

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from importer.content import ContentStore, BlobMetadata, BINARY_EXTENSIONS
import config


class TestBlobStorageBasics(unittest.TestCase):
    """Test basic blob storage functionality"""

    def setUp(self):
        """Create temporary directories for testing"""
        self.test_dir = tempfile.mkdtemp()
        self.blob_dir = Path(self.test_dir) / "blobs"
        self.store = ContentStore(blob_dir=self.blob_dir)

    def tearDown(self):
        """Clean up test directories"""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_small_text_file_inline_storage(self):
        """Small text files should be stored inline"""
        # Create a small text file (1KB)
        test_file = Path(self.test_dir) / "small.txt"
        content = "Hello World\n" * 100  # ~1.2KB
        test_file.write_text(content)

        # Store the file
        metadata = self.store.store_content(test_file)

        # Verify
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.storage_location, 'inline')
        self.assertEqual(metadata.content_type, 'text')
        self.assertEqual(metadata.content_text, content)
        self.assertEqual(metadata.file_size, len(content.encode('utf-8')))
        self.assertIsNotNone(metadata.content_hash)
        self.assertEqual(len(metadata.content_hash), 64)  # SHA-256 hex length
        self.assertIsNone(metadata.external_path)
        self.assertEqual(metadata.line_count, 100)

    def test_small_binary_file_inline_storage(self):
        """Small binary files should be stored inline"""
        # Create a small binary file (1KB)
        test_file = Path(self.test_dir) / "small.png"
        content = b'\x89PNG\r\n\x1a\n' + b'\x00' * 1000
        test_file.write_bytes(content)

        # Store the file
        metadata = self.store.store_content(test_file)

        # Verify
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.storage_location, 'inline')
        self.assertEqual(metadata.content_type, 'binary')
        self.assertEqual(metadata.content_blob, content)
        self.assertEqual(metadata.file_size, len(content))
        self.assertIsNotNone(metadata.content_hash)
        self.assertIsNone(metadata.external_path)

    def test_large_file_external_storage(self):
        """Large files should be stored externally"""
        # Create a large file (15MB > 10MB threshold)
        # Use .zip extension which is in BINARY_EXTENSIONS
        test_file = Path(self.test_dir) / "large.zip"
        content = b'X' * (15 * 1024 * 1024)
        test_file.write_bytes(content)

        # Store the file
        metadata = self.store.store_content(test_file)

        # Verify
        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.storage_location, 'external')
        self.assertEqual(metadata.content_type, 'binary')
        self.assertEqual(metadata.file_size, 15 * 1024 * 1024)
        self.assertIsNotNone(metadata.content_hash)
        self.assertIsNotNone(metadata.external_path)
        self.assertIsNone(metadata.content_blob)  # Not stored inline
        self.assertIsNone(metadata.content_text)

        # Verify external file exists
        blob_path = self.blob_dir / metadata.external_path
        self.assertTrue(blob_path.exists())
        self.assertEqual(blob_path.stat().st_size, 15 * 1024 * 1024)

    def test_external_path_format(self):
        """External path should use git-style sharding (first 2 chars)"""
        # Create a large file
        test_file = Path(self.test_dir) / "large.txt"
        content = "A" * (11 * 1024 * 1024)  # 11MB
        test_file.write_text(content)

        # Store the file
        metadata = self.store.store_content(test_file)

        # Verify path format: "ab/abc123..."
        self.assertIsNotNone(metadata.external_path)
        parts = metadata.external_path.split('/')
        self.assertEqual(len(parts), 2)
        self.assertEqual(len(parts[0]), 2)  # First 2 chars
        self.assertEqual(parts[0], metadata.content_hash[:2])
        self.assertEqual(parts[1], metadata.content_hash)

    def test_file_too_large(self):
        """Files exceeding max size should return None"""
        # Create a file larger than BLOB_MAX_SIZE
        # For testing, we'll mock the config value
        original_max = config.BLOB_MAX_SIZE
        config.BLOB_MAX_SIZE = 1 * 1024 * 1024  # 1MB for testing

        try:
            test_file = Path(self.test_dir) / "toolarge.bin"
            content = b'X' * (2 * 1024 * 1024)  # 2MB
            test_file.write_bytes(content)

            # Store should return None
            metadata = self.store.store_content(test_file)
            self.assertIsNone(metadata)
        finally:
            config.BLOB_MAX_SIZE = original_max

    def test_hash_calculation_consistency(self):
        """Hash should be consistent for same content"""
        content = b"Test content for hashing"

        hash1 = ContentStore.calculate_hash(content)
        hash2 = ContentStore.calculate_hash(content)

        self.assertEqual(hash1, hash2)
        self.assertEqual(len(hash1), 64)  # SHA-256 hex

    def test_streaming_hash_matches_regular(self):
        """Streaming hash should match regular hash"""
        test_file = Path(self.test_dir) / "test.txt"
        content = "Test content\n" * 1000
        test_file.write_text(content)

        content_bytes = content.encode('utf-8')
        regular_hash = ContentStore.calculate_hash(content_bytes)
        streaming_hash = ContentStore.calculate_hash_streaming(test_file)

        self.assertEqual(regular_hash, streaming_hash)


class TestBlobRetrieval(unittest.TestCase):
    """Test blob retrieval and verification"""

    def setUp(self):
        """Create temporary directories for testing"""
        self.test_dir = tempfile.mkdtemp()
        self.blob_dir = Path(self.test_dir) / "blobs"
        self.store = ContentStore(blob_dir=self.blob_dir)

    def tearDown(self):
        """Clean up test directories"""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_retrieve_external_blob(self):
        """Can retrieve content from external storage"""
        # Create and store a large file
        test_file = Path(self.test_dir) / "large.txt"
        original_content = "Test line\n" * (1024 * 1024)  # ~10MB
        test_file.write_text(original_content)

        metadata = self.store.store_content(test_file)
        self.assertEqual(metadata.storage_location, 'external')

        # Retrieve the content
        retrieved_content = self.store.retrieve_content(
            metadata.content_hash,
            'external',
            metadata.external_path
        )

        # Verify
        self.assertIsNotNone(retrieved_content)
        self.assertEqual(retrieved_content.decode('utf-8'), original_content)

    def test_retrieve_missing_blob(self):
        """Retrieving missing blob should return None"""
        result = self.store.retrieve_content(
            "abc123",
            'external',
            'ab/abc123'
        )
        self.assertIsNone(result)

    def test_retrieve_inline_raises_error(self):
        """Trying to retrieve inline content should raise error"""
        with self.assertRaises(ValueError):
            self.store.retrieve_content("abc123", 'inline', None)

    def test_verify_blob_integrity(self):
        """Blob verification should detect integrity"""
        # Create and store a file
        test_file = Path(self.test_dir) / "large.bin"
        content = b'X' * (15 * 1024 * 1024)
        test_file.write_bytes(content)

        metadata = self.store.store_content(test_file)

        # Verify integrity
        is_valid, error = self.store.verify_blob(
            metadata.content_hash,
            metadata.external_path
        )

        self.assertTrue(is_valid)
        self.assertIsNone(error)

    def test_verify_blob_corruption(self):
        """Blob verification should detect corruption"""
        # Create and store a file
        test_file = Path(self.test_dir) / "large.bin"
        content = b'X' * (15 * 1024 * 1024)
        test_file.write_bytes(content)

        metadata = self.store.store_content(test_file)

        # Corrupt the blob
        blob_path = self.blob_dir / metadata.external_path
        with open(blob_path, 'r+b') as f:
            f.seek(100)
            f.write(b'CORRUPTED')

        # Verify should detect corruption
        is_valid, error = self.store.verify_blob(
            metadata.content_hash,
            metadata.external_path
        )

        self.assertFalse(is_valid)
        self.assertIn("Hash mismatch", error)

    def test_verify_missing_blob(self):
        """Blob verification should detect missing files"""
        is_valid, error = self.store.verify_blob(
            "abc123",
            "ab/abc123"
        )

        self.assertFalse(is_valid)
        self.assertIn("not found", error)


class TestBinaryFileDetection(unittest.TestCase):
    """Test binary file type detection"""

    def test_binary_extensions_detected(self):
        """Known binary extensions should be detected"""
        binary_files = [
            "image.png", "photo.jpg", "icon.gif",
            "archive.zip", "data.tar.gz",
            "program.exe", "library.dll", "module.so",
            "font.woff", "music.mp3", "video.mp4",
            "database.sqlite"
        ]

        for filename in binary_files:
            path = Path(filename)
            self.assertTrue(
                ContentStore.is_binary_file(path),
                f"{filename} should be detected as binary"
            )

    def test_text_extensions_not_binary(self):
        """Text extensions should not be detected as binary"""
        text_files = [
            "file.txt", "code.py", "script.js",
            "style.css", "page.html", "data.json",
            "config.yaml", "readme.md"
        ]

        for filename in text_files:
            path = Path(filename)
            self.assertFalse(
                ContentStore.is_binary_file(path),
                f"{filename} should not be detected as binary"
            )


class TestEdgeCases(unittest.TestCase):
    """Test edge cases and error handling"""

    def setUp(self):
        """Create temporary directories for testing"""
        self.test_dir = tempfile.mkdtemp()
        self.blob_dir = Path(self.test_dir) / "blobs"
        self.store = ContentStore(blob_dir=self.blob_dir)

    def tearDown(self):
        """Clean up test directories"""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_empty_file(self):
        """Empty files should be handled correctly"""
        test_file = Path(self.test_dir) / "empty.txt"
        test_file.write_text("")

        metadata = self.store.store_content(test_file)

        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.storage_location, 'inline')
        self.assertEqual(metadata.file_size, 0)
        self.assertEqual(metadata.line_count, 0)

    def test_nonexistent_file(self):
        """Non-existent files should return None"""
        test_file = Path(self.test_dir) / "nonexistent.txt"

        metadata = self.store.store_content(test_file)
        self.assertIsNone(metadata)

    def test_unicode_text_file(self):
        """Unicode text files should be handled correctly"""
        test_file = Path(self.test_dir) / "unicode.txt"
        content = "Hello 世界 🌍\n" * 100
        test_file.write_text(content, encoding='utf-8')

        metadata = self.store.store_content(test_file)

        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.storage_location, 'inline')
        self.assertEqual(metadata.content_type, 'text')
        self.assertEqual(metadata.content_text, content)
        self.assertEqual(metadata.encoding, 'utf-8')

    def test_text_file_with_no_extension(self):
        """Text files without extension should be handled"""
        test_file = Path(self.test_dir) / "README"
        content = "This is a readme file\n"
        test_file.write_text(content)

        metadata = self.store.store_content(test_file)

        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.content_type, 'text')

    def test_binary_data_in_text_extension(self):
        """Binary data with text extension should fallback to binary"""
        test_file = Path(self.test_dir) / "fake.txt"
        # Write invalid UTF-8 bytes
        test_file.write_bytes(b'\x89\xFF\xFE\x00\x01\x02')

        metadata = self.store.store_content(test_file)

        self.assertIsNotNone(metadata)
        self.assertEqual(metadata.storage_location, 'inline')
        self.assertEqual(metadata.content_type, 'binary')
        self.assertIsNone(metadata.content_text)
        self.assertIsNotNone(metadata.content_blob)


class TestBackwardsCompatibility(unittest.TestCase):
    """Test backwards compatibility with legacy read_file_content()"""

    def setUp(self):
        """Create temporary directories for testing"""
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test directories"""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_legacy_method_still_works(self):
        """Legacy read_file_content() should still work for small files"""
        test_file = Path(self.test_dir) / "small.txt"
        content = "Hello World\n" * 100
        test_file.write_text(content)

        # Use legacy method
        file_content = ContentStore.read_file_content(test_file)

        self.assertIsNotNone(file_content)
        self.assertEqual(file_content.content_type, 'text')
        self.assertEqual(file_content.content_text, content)
        self.assertIsNotNone(file_content.hash_sha256)

    def test_legacy_method_skips_large_files(self):
        """Legacy method should skip files larger than threshold"""
        test_file = Path(self.test_dir) / "large.txt"
        # Create file larger than inline threshold
        content = "X" * (config.BLOB_INLINE_THRESHOLD + 1000)
        test_file.write_text(content)

        # Legacy method should return None
        file_content = ContentStore.read_file_content(test_file)
        self.assertIsNone(file_content)


class TestContentDeduplication(unittest.TestCase):
    """Test that content deduplication still works with external storage"""

    def setUp(self):
        """Create temporary directories for testing"""
        self.test_dir = tempfile.mkdtemp()
        self.blob_dir = Path(self.test_dir) / "blobs"
        self.store = ContentStore(blob_dir=self.blob_dir)

    def tearDown(self):
        """Clean up test directories"""
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_same_content_same_hash(self):
        """Identical content should produce same hash"""
        # Create two files with identical content
        file1 = Path(self.test_dir) / "file1.txt"
        file2 = Path(self.test_dir) / "file2.txt"

        content = "Identical content\n" * (1024 * 1024)  # ~17MB
        file1.write_text(content)
        file2.write_text(content)

        # Store both files
        metadata1 = self.store.store_content(file1)
        metadata2 = self.store.store_content(file2)

        # Verify same hash
        self.assertEqual(metadata1.content_hash, metadata2.content_hash)
        self.assertEqual(metadata1.external_path, metadata2.external_path)

        # Verify only one blob file exists
        blob_path = self.blob_dir / metadata1.external_path
        self.assertTrue(blob_path.exists())

        # The second store operation would have created a hard link or copy
        # to the same location (overwriting is fine since content is identical)


def run_tests():
    """Run all tests"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestBlobStorageBasics))
    suite.addTests(loader.loadTestsFromTestCase(TestBlobRetrieval))
    suite.addTests(loader.loadTestsFromTestCase(TestBinaryFileDetection))
    suite.addTests(loader.loadTestsFromTestCase(TestEdgeCases))
    suite.addTests(loader.loadTestsFromTestCase(TestBackwardsCompatibility))
    suite.addTests(loader.loadTestsFromTestCase(TestContentDeduplication))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
