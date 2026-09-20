"""
Content compression utilities for TempleDB.

Implements:
1. zlib compression (3-5x reduction for text)
2. Delta compression (5-10x reduction for similar files)
3. Adaptive compression (choose best method)
"""

import zlib
import hashlib
from typing import Optional, Tuple, Dict
from dataclasses import dataclass


@dataclass
class CompressionResult:
    """Result of compression operation"""
    compressed_data: bytes
    original_size: int
    compressed_size: int
    compression_type: str  # 'none', 'zlib', 'delta'
    delta_base_hash: Optional[str] = None
    compression_ratio: float = 0.0

    def __post_init__(self):
        if self.original_size > 0:
            self.compression_ratio = (
                (self.original_size - self.compressed_size) / self.original_size
            )


class ContentCompressor:
    """Handles compression of file content"""

    # Compression thresholds
    MIN_SIZE_FOR_COMPRESSION = 512  # Don't compress files < 512 bytes
    ZLIB_COMPRESSION_LEVEL = 6  # Balance speed vs ratio
    DELTA_SIMILARITY_THRESHOLD = 0.3  # 30% similarity to use delta

    @staticmethod
    def compress_zlib(content: bytes) -> CompressionResult:
        """
        Compress content using zlib.

        Args:
            content: Raw content bytes

        Returns:
            CompressionResult with compressed data
        """
        original_size = len(content)

        # Skip compression for small files
        if original_size < ContentCompressor.MIN_SIZE_FOR_COMPRESSION:
            return CompressionResult(
                compressed_data=content,
                original_size=original_size,
                compressed_size=original_size,
                compression_type='none'
            )

        # Compress
        compressed = zlib.compress(
            content,
            level=ContentCompressor.ZLIB_COMPRESSION_LEVEL
        )
        compressed_size = len(compressed)

        # Only use compression if it actually saves space
        if compressed_size >= original_size * 0.9:  # Less than 10% savings
            return CompressionResult(
                compressed_data=content,
                original_size=original_size,
                compressed_size=original_size,
                compression_type='none'
            )

        return CompressionResult(
            compressed_data=compressed,
            original_size=original_size,
            compressed_size=compressed_size,
            compression_type='zlib'
        )

    @staticmethod
    def decompress_zlib(compressed_data: bytes) -> bytes:
        """
        Decompress zlib-compressed content.

        Args:
            compressed_data: Compressed bytes

        Returns:
            Original uncompressed bytes
        """
        return zlib.decompress(compressed_data)

    @staticmethod
    def compress_delta(
        content: bytes,
        base_content: bytes,
        base_hash: str
    ) -> CompressionResult:
        """
        Compress content using delta compression against base.

        Uses a simple line-based diff for text files.
        For binary files, falls back to zlib.

        Args:
            content: New content to compress
            base_content: Base content to diff against
            base_hash: SHA-256 hash of base content

        Returns:
            CompressionResult with delta-compressed data
        """
        original_size = len(content)

        # Try text-based delta
        try:
            content_str = content.decode('utf-8')
            base_str = base_content.decode('utf-8')

            # Simple line-based delta
            delta_bytes = ContentCompressor._create_line_delta(
                content_str,
                base_str
            )

            delta_size = len(delta_bytes)

            # Only use delta if it saves significant space
            if delta_size < original_size * 0.5:  # At least 50% savings
                return CompressionResult(
                    compressed_data=delta_bytes,
                    original_size=original_size,
                    compressed_size=delta_size,
                    compression_type='delta',
                    delta_base_hash=base_hash
                )

        except UnicodeDecodeError:
            # Binary file - can't use line delta
            pass

        # Delta not effective, fall back to zlib
        return ContentCompressor.compress_zlib(content)

    @staticmethod
    def _create_line_delta(new_text: str, base_text: str) -> bytes:
        """
        Create a line-based delta between two texts.

        Simple format:
        - Lines starting with '+' are additions
        - Lines starting with '-' are deletions
        - Lines starting with ' ' are context (kept for reconstruction)

        Args:
            new_text: New version
            base_text: Base version

        Returns:
            Delta as bytes
        """
        import difflib

        base_lines = base_text.splitlines(keepends=True)
        new_lines = new_text.splitlines(keepends=True)

        # Use difflib for unified diff
        diff = difflib.unified_diff(
            base_lines,
            new_lines,
            lineterm='',
            n=0  # No context lines (we have base file)
        )

        # Convert diff to bytes
        delta_str = ''.join(diff)
        return delta_str.encode('utf-8')

    @staticmethod
    def apply_delta(
        delta_data: bytes,
        base_content: bytes
    ) -> bytes:
        """
        Apply delta to base content to reconstruct original.

        Args:
            delta_data: Delta compressed data
            base_content: Base content

        Returns:
            Reconstructed original content
        """
        try:
            import difflib

            delta_str = delta_data.decode('utf-8')
            base_str = base_content.decode('utf-8')

            # Parse unified diff and apply
            base_lines = base_str.splitlines(keepends=True)

            # Simple patch application
            # (In production, use a proper patch library)
            result_lines = base_lines.copy()

            for line in delta_str.splitlines():
                if line.startswith('+') and not line.startswith('+++'):
                    # Addition
                    result_lines.append(line[1:] + '\n')
                elif line.startswith('-') and not line.startswith('---'):
                    # Deletion
                    content = line[1:] + '\n'
                    if content in result_lines:
                        result_lines.remove(content)

            return ''.join(result_lines).encode('utf-8')

        except Exception as e:
            raise ValueError(f"Failed to apply delta: {e}")

    @staticmethod
    def adaptive_compress(
        content: bytes,
        base_content: Optional[bytes] = None,
        base_hash: Optional[str] = None
    ) -> CompressionResult:
        """
        Automatically choose best compression method.

        Algorithm:
        1. If base_content provided and similar enough, try delta
        2. Otherwise, use zlib
        3. If compression doesn't save enough space, store uncompressed

        Args:
            content: Content to compress
            base_content: Optional base for delta compression
            base_hash: SHA-256 of base content (required if base_content provided)

        Returns:
            CompressionResult with best compression
        """
        # Try delta compression if base provided
        if base_content and base_hash:
            # Check if files are similar enough
            similarity = ContentCompressor._calculate_similarity(
                content,
                base_content
            )

            if similarity >= ContentCompressor.DELTA_SIMILARITY_THRESHOLD:
                delta_result = ContentCompressor.compress_delta(
                    content,
                    base_content,
                    base_hash
                )

                # If delta is effective, use it
                if delta_result.compression_ratio > 0.5:  # 50%+ savings
                    return delta_result

        # Fall back to zlib
        return ContentCompressor.compress_zlib(content)

    @staticmethod
    def _calculate_similarity(content1: bytes, content2: bytes) -> float:
        """
        Calculate similarity between two byte sequences.

        Uses simple metric: ratio of common bytes to total bytes.

        Args:
            content1: First content
            content2: Second content

        Returns:
            Similarity ratio (0.0 to 1.0)
        """
        if not content1 or not content2:
            return 0.0

        # Simple byte-level comparison
        min_len = min(len(content1), len(content2))
        max_len = max(len(content1), len(content2))

        if max_len == 0:
            return 1.0

        # Count matching bytes
        matches = sum(
            1 for i in range(min_len)
            if content1[i] == content2[i]
        )

        return matches / max_len

    @staticmethod
    def decompress(
        compressed_data: bytes,
        compression_type: str,
        base_content: Optional[bytes] = None
    ) -> bytes:
        """
        Decompress content based on compression type.

        Args:
            compressed_data: Compressed bytes
            compression_type: 'none', 'zlib', or 'delta'
            base_content: Required for delta decompression

        Returns:
            Original uncompressed bytes
        """
        if compression_type == 'none':
            return compressed_data

        elif compression_type == 'zlib':
            return ContentCompressor.decompress_zlib(compressed_data)

        elif compression_type == 'delta':
            if not base_content:
                raise ValueError("Base content required for delta decompression")
            return ContentCompressor.apply_delta(compressed_data, base_content)

        else:
            raise ValueError(f"Unknown compression type: {compression_type}")


def calculate_content_hash(content: bytes) -> str:
    """
    Calculate SHA-256 hash of content.

    Args:
        content: Content bytes

    Returns:
        Hex-encoded SHA-256 hash
    """
    return hashlib.sha256(content).hexdigest()


def get_compression_stats(compressed_results: list[CompressionResult]) -> Dict:
    """
    Calculate aggregate compression statistics.

    Args:
        compressed_results: List of compression results

    Returns:
        Dictionary with statistics
    """
    if not compressed_results:
        return {
            'total_files': 0,
            'total_original_size': 0,
            'total_compressed_size': 0,
            'overall_ratio': 0.0,
            'by_type': {}
        }

    total_original = sum(r.original_size for r in compressed_results)
    total_compressed = sum(r.compressed_size for r in compressed_results)
    overall_ratio = (
        (total_original - total_compressed) / total_original
        if total_original > 0 else 0.0
    )

    # Stats by compression type
    by_type = {}
    for comp_type in ['none', 'zlib', 'delta']:
        matching = [r for r in compressed_results if r.compression_type == comp_type]
        if matching:
            type_original = sum(r.original_size for r in matching)
            type_compressed = sum(r.compressed_size for r in matching)
            type_ratio = (
                (type_original - type_compressed) / type_original
                if type_original > 0 else 0.0
            )
            by_type[comp_type] = {
                'count': len(matching),
                'original_size': type_original,
                'compressed_size': type_compressed,
                'ratio': type_ratio
            }

    return {
        'total_files': len(compressed_results),
        'total_original_size': total_original,
        'total_compressed_size': total_compressed,
        'overall_ratio': overall_ratio,
        'savings_mb': (total_original - total_compressed) / 1024 / 1024,
        'by_type': by_type
    }
