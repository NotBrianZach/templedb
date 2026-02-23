#!/usr/bin/env python3
"""
File content storage with versioning and hashing
"""
import hashlib
from pathlib import Path
from typing import Optional, Set
from dataclasses import dataclass


# Binary file extensions
BINARY_EXTENSIONS = {
    '.png', '.jpg', '.jpeg', '.gif', '.bmp', '.ico', '.svg',
    '.pdf', '.zip', '.tar', '.gz', '.bz2', '.xz',
    '.exe', '.dll', '.so', '.dylib',
    '.woff', '.woff2', '.ttf', '.eot',
    '.mp3', '.mp4', '.avi', '.mov',
    '.db', '.sqlite', '.sqlite3'
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB limit


@dataclass
class FileContent:
    """Represents file content with metadata"""
    content_type: str  # 'text' or 'binary'
    content_text: Optional[str] = None
    content_blob: Optional[bytes] = None
    encoding: Optional[str] = None
    file_size: int = 0
    line_count: Optional[int] = None
    hash_sha256: str = ''


class ContentStore:
    """Handles file content reading, hashing, and storage"""

    @staticmethod
    def is_binary_file(file_path: Path) -> bool:
        """Check if file is binary based on extension"""
        return file_path.suffix.lower() in BINARY_EXTENSIONS

    @staticmethod
    def calculate_hash(content: bytes) -> str:
        """Calculate SHA-256 hash of content"""
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def read_file_content(file_path: Path) -> Optional[FileContent]:
        """Read file content and return FileContent object"""
        # Check file size
        file_size = file_path.stat().st_size
        if file_size > MAX_FILE_SIZE:
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
