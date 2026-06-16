#!/usr/bin/env python3
"""
File content storage with versioning and hashing
Supports both inline (database) and external (filesystem) storage
"""
import hashlib
import os
import shutil
from pathlib import Path
from typing import Optional, Set, Tuple
from dataclasses import dataclass

# Import config
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

# Optional compression support
try:
    import zstandard as zstd
    ZSTD_AVAILABLE = True
except ImportError:
    ZSTD_AVAILABLE = False

# Compressed file extensions (already compressed, don't compress again)
COMPRESSED_EXTENSIONS = {
    '.zip', '.gz', '.bz2', '.xz', '.zst', '.7z', '.rar',
    '.jpg', '.jpeg', '.png', '.gif', '.webp',
    '.mp3', '.mp4', '.avi', '.mov', '.mkv', '.flac',
    '.woff', '.woff2', '.ttf', '.eot'
}


# Binary file extensions
BINARY_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg',
    '.pdf', '.zip', '.tar', '.gz', '.bz2', '.xz',
    '.exe', '.dll', '.so', '.dylib',
    '.woff', '.woff2', '.ttf', '.eot',
    '.mp3', '.mp4', '.avi', '.mov',
    '.db', '.sqlite', '.sqlite3'
}

MAX_FILE_SIZE = config.BLOB_MAX_SIZE  # Configurable max size


@dataclass
class FileContent:
    """Represents file content with metadata (inline storage)"""
    content_type: str  # 'text' or 'binary'
    content_text: Optional[str] = None
    content_blob: Optional[bytes] = None
    encoding: Optional[str] = None
    file_size: int = 0
    line_count: Optional[int] = None
    hash_sha256: str = ''


@dataclass
class BlobMetadata:
    """Metadata for blob storage (inline or external)"""
    storage_location: str  # 'inline', 'external', 'remote'
    content_hash: str  # SHA-256 hash
    content_type: str  # 'text' or 'binary'
    file_size: int  # Size in bytes

    # For inline storage
    content_text: Optional[str] = None
    content_blob: Optional[bytes] = None
    encoding: Optional[str] = None
    line_count: Optional[int] = None

    # For external storage
    external_path: Optional[str] = None  # Relative path to blob file
    compression: Optional[str] = None  # 'zstd', 'gzip', or None
    chunk_count: int = 1

    # For remote storage (future)
    remote_url: Optional[str] = None


class ContentStore:
    """Handles file content reading, hashing, and storage (inline and external)"""

    def __init__(self, blob_dir: Optional[Path] = None):
        """
        Initialize ContentStore

        Args:
            blob_dir: Directory for external blob storage
                     Defaults to config.BLOB_STORAGE_DIR
        """
        self.blob_dir = Path(blob_dir) if blob_dir else Path(config.BLOB_STORAGE_DIR)
        self.blob_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def is_binary_file(file_path: Path) -> bool:
        """Check if file is binary based on extension"""
        return file_path.suffix.lower() in BINARY_EXTENSIONS

    @staticmethod
    def calculate_hash(content: bytes) -> str:
        """Calculate SHA-256 hash of content"""
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def calculate_hash_streaming(file_path: Path) -> str:
        """Calculate SHA-256 hash of file using streaming (for large files)"""
        hasher = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
        return hasher.hexdigest()

    def store_content(self, file_path: Path) -> Optional[BlobMetadata]:
        """
        Store file content, automatically choosing storage strategy

        Returns BlobMetadata with storage location and content info
        Returns None if file is too large or cannot be read
        """
        try:
            file_size = file_path.stat().st_size
        except (OSError, FileNotFoundError):
            return None

        # Size validation
        if file_size > config.BLOB_MAX_SIZE:
            # File too large - skip
            return None

        # Decide storage strategy based on size
        if file_size < config.BLOB_INLINE_THRESHOLD:
            return self._store_inline(file_path, file_size)
        else:
            return self._store_external(file_path, file_size)

    def _store_inline(self, file_path: Path, file_size: int) -> Optional[BlobMetadata]:
        """Store small files inline (in database)"""
        is_binary = self.is_binary_file(file_path)

        try:
            if is_binary:
                # Read as binary
                content_bytes = file_path.read_bytes()
                content_hash = self.calculate_hash(content_bytes)

                return BlobMetadata(
                    storage_location='inline',
                    content_hash=content_hash,
                    content_type='binary',
                    file_size=file_size,
                    content_blob=content_bytes,
                    encoding=None,
                    line_count=None
                )
            else:
                # Try to read as text
                try:
                    content_text = file_path.read_text(encoding='utf-8')
                    content_bytes = content_text.encode('utf-8')
                    content_hash = self.calculate_hash(content_bytes)
                    line_count = len(content_text.splitlines())

                    return BlobMetadata(
                        storage_location='inline',
                        content_hash=content_hash,
                        content_type='text',
                        file_size=file_size,
                        content_text=content_text,
                        encoding='utf-8',
                        line_count=line_count
                    )
                except UnicodeDecodeError:
                    # If UTF-8 fails, treat as binary
                    content_bytes = file_path.read_bytes()
                    content_hash = self.calculate_hash(content_bytes)

                    return BlobMetadata(
                        storage_location='inline',
                        content_hash=content_hash,
                        content_type='binary',
                        file_size=file_size,
                        content_blob=content_bytes,
                        encoding=None,
                        line_count=None
                    )
        except (OSError, MemoryError):
            return None

    def _should_compress(self, file_path: Path, file_size: int) -> bool:
        """
        Determine if file should be compressed

        Returns False if:
        - Compression disabled in config
        - File too small (< compression threshold)
        - File already compressed (known extension)
        - zstd not available
        """
        if not config.BLOB_COMPRESSION_ENABLED:
            return False

        if not ZSTD_AVAILABLE:
            return False

        if file_size < config.BLOB_COMPRESSION_THRESHOLD:
            return False

        # Don't compress already-compressed formats
        if file_path.suffix.lower() in COMPRESSED_EXTENSIONS:
            return False

        return True

    def _compress_file(self, source: Path, dest: Path) -> int:
        """
        Compress file using zstandard

        Returns compressed size in bytes
        """
        if not ZSTD_AVAILABLE:
            raise RuntimeError("zstandard not available")

        cctx = zstd.ZstdCompressor(level=3)  # Level 3 is good balance of speed/ratio

        with open(source, 'rb') as src, open(dest, 'wb') as dst:
            cctx.copy_stream(src, dst)

        return dest.stat().st_size

    def _decompress_file(self, source: Path) -> bytes:
        """Decompress zstandard file"""
        if not ZSTD_AVAILABLE:
            raise RuntimeError("zstandard not available")

        dctx = zstd.ZstdDecompressor()
        with open(source, 'rb') as src:
            return dctx.decompress(src.read())

    def _store_external(self, file_path: Path, file_size: int) -> Optional[BlobMetadata]:
        """Store large files on filesystem"""
        try:
            # Calculate hash using streaming (don't load entire file in memory)
            content_hash = self.calculate_hash_streaming(file_path)

            # Create blob directory using first 2 chars of hash (sharding like git)
            # e.g., hash abc123... → blobs/ab/abc123...
            blob_subdir = self.blob_dir / content_hash[:2]
            blob_subdir.mkdir(exist_ok=True)

            blob_path = blob_subdir / content_hash
            compression = None
            actual_stored_size = file_size

            # Determine if file should be compressed
            if self._should_compress(file_path, file_size):
                try:
                    # Compress to blob storage
                    blob_path = blob_path.with_suffix('.zst')
                    compressed_size = self._compress_file(file_path, blob_path)
                    compression = 'zstd'
                    actual_stored_size = compressed_size
                except Exception:
                    # If compression fails, fall back to uncompressed
                    blob_path = blob_subdir / content_hash
                    compression = None

            if compression is None:
                # Store uncompressed
                # Hard link or copy to blob storage
                # Hard link is preferred (saves space, instant)
                # Fall back to copy if hard link fails (different filesystems)
                try:
                    os.link(file_path, blob_path)
                except OSError:
                    shutil.copy2(file_path, blob_path)
                actual_stored_size = file_size

            # Determine content type
            is_binary = self.is_binary_file(file_path)
            content_type = 'binary' if is_binary else 'text'

            # Count lines for text files (if reasonable size)
            line_count = None
            if not is_binary and file_size < 10 * 1024 * 1024:  # Only for files <10MB
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        line_count = sum(1 for _ in f)
                except (UnicodeDecodeError, OSError):
                    pass

            # Create relative path for storage
            external_path = f"{content_hash[:2]}/{blob_path.name}"

            return BlobMetadata(
                storage_location='external',
                content_hash=content_hash,
                content_type=content_type,
                file_size=file_size,  # Original size, not compressed size
                external_path=external_path,
                compression=compression,
                line_count=line_count
            )

        except (OSError, MemoryError):
            return None

    def retrieve_content(self, content_hash: str, storage_location: str,
                        external_path: Optional[str] = None,
                        compression: Optional[str] = None) -> Optional[bytes]:
        """
        Retrieve blob content from storage

        Args:
            content_hash: SHA-256 hash of content
            storage_location: 'inline', 'external', or 'remote'
            external_path: Path to external blob (if external storage)
            compression: Compression algorithm ('zstd', 'gzip', or None)

        Returns:
            Content as bytes (decompressed if needed), or None if not found
        """
        if storage_location == 'inline':
            # For inline storage, content must be fetched from database
            # This method only handles external storage
            raise ValueError("Cannot retrieve inline content from ContentStore. Query database instead.")

        elif storage_location == 'external':
            if not external_path:
                raise ValueError("external_path required for external storage")

            blob_path = self.blob_dir / external_path

            if not blob_path.exists():
                return None

            try:
                # Handle compression
                if compression == 'zstd':
                    if not ZSTD_AVAILABLE:
                        raise RuntimeError("zstandard library not available for decompression")
                    return self._decompress_file(blob_path)
                elif compression == 'gzip':
                    # Future: gzip support
                    raise NotImplementedError("gzip decompression not yet implemented")
                else:
                    # No compression, return raw bytes
                    return blob_path.read_bytes()
            except (OSError, MemoryError):
                return None

        elif storage_location == 'remote':
            # Future: Fetch from remote storage (S3/GCS)
            raise NotImplementedError("Remote blob storage not yet implemented")

        else:
            raise ValueError(f"Unknown storage location: {storage_location}")

    def verify_blob(self, content_hash: str, external_path: str) -> Tuple[bool, Optional[str]]:
        """
        Verify external blob integrity

        Returns:
            (is_valid, error_message)
        """
        blob_path = self.blob_dir / external_path

        if not blob_path.exists():
            return False, f"Blob file not found: {blob_path}"

        try:
            actual_hash = self.calculate_hash_streaming(blob_path)
            if actual_hash != content_hash:
                return False, f"Hash mismatch: expected {content_hash}, got {actual_hash}"
            return True, None
        except (OSError, MemoryError) as e:
            return False, f"Error reading blob: {e}"

    @staticmethod
    def read_file_content(file_path: Path) -> Optional[FileContent]:
        """
        Legacy method for backwards compatibility
        Read file content and return FileContent object (inline only)

        DEPRECATED: Use store_content() instead for new code
        """
        # Check file size
        file_size = file_path.stat().st_size
        if file_size > config.BLOB_INLINE_THRESHOLD:
            # File too large for inline storage
            return None

        is_binary = ContentStore.is_binary_file(file_path)

        if is_binary:
            # Read as binary
            content_bytes = file_path.read_bytes()
            return FileContent(
                content_type='binary',
                content_blob=content_bytes,
                encoding=None,
                file_size=len(content_bytes),
                line_count=None,
                hash_sha256=ContentStore.calculate_hash(content_bytes)
            )
        else:
            # Try to read as text
            try:
                content_text = file_path.read_text(encoding='utf-8')
                content_bytes = content_text.encode('utf-8')
                line_count = len(content_text.splitlines())

                return FileContent(
                    content_type='text',
                    content_text=content_text,
                    encoding='utf-8',
                    file_size=len(content_bytes),
                    line_count=line_count,
                    hash_sha256=ContentStore.calculate_hash(content_bytes)
                )
            except UnicodeDecodeError:
                # If UTF-8 fails, treat as binary
                content_bytes = file_path.read_bytes()
                return FileContent(
                    content_type='binary',
                    content_blob=content_bytes,
                    encoding=None,
                    file_size=len(content_bytes),
                    line_count=None,
                    hash_sha256=ContentStore.calculate_hash(content_bytes)
                )

    @staticmethod
    def content_changed(hash1: Optional[str], hash2: str) -> bool:
        """Check if content has changed by comparing hashes"""
        return hash1 is None or hash1 != hash2
