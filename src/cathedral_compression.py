#!/usr/bin/env python3
"""
Cathedral Compression - Compress and decompress .cathedral packages

Supports:
- tar.gz (gzip) - Universal compatibility
- tar.zst (zstd) - Better compression ratio, faster
- Uncompressed (directory) - Original format
"""

import tarfile
import logging
from pathlib import Path
from typing import Optional, Literal

logger = logging.getLogger('cathedral.compression')

# Try to import zstandard for better compression
try:
    import zstandard as zstd
    ZSTD_AVAILABLE = True
except ImportError:
    ZSTD_AVAILABLE = False
    logger.debug("zstandard not available, using gzip only")

CompressionType = Literal['zstd', 'gzip', 'none']


def detect_compression(package_path: Path) -> CompressionType:
    """
    Detect compression type of a package

    Args:
        package_path: Path to package file or directory

    Returns:
        'zstd', 'gzip', or 'none'
    """
    if package_path.is_dir():
        return 'none'

    name = package_path.name.lower()

    if name.endswith('.tar.zst') or name.endswith('.cathedral.zst'):
        return 'zstd'
    elif name.endswith('.tar.gz') or name.endswith('.cathedral.gz'):
        return 'gzip'
    elif name.endswith('.tar'):
        return 'gzip'  # Treat as gzip (can be uncompressed tar too)

    return 'none'


def compress_package(
    package_dir: Path,
    output_path: Path,
    compression: CompressionType = 'zstd',
    level: Optional[int] = None
) -> Path:
    """
    Compress a .cathedral package directory into an archive

    Args:
        package_dir: Path to .cathedral directory
        output_path: Output file path (without extension)
        compression: Compression type ('zstd', 'gzip', or 'none')
        level: Compression level (None = default)

    Returns:
        Path to compressed archive

    Raises:
        ValueError: If compression type not supported
        FileNotFoundError: If package_dir doesn't exist
    """
    if not package_dir.exists():
        raise FileNotFoundError(f"Package directory not found: {package_dir}")

    if not package_dir.is_dir():
        raise ValueError(f"Package must be a directory: {package_dir}")

    if compression == 'none':
        logger.info("No compression requested, package remains as directory")
        return package_dir

    # Determine output filename and mode
    if compression == 'zstd':
        if not ZSTD_AVAILABLE:
            logger.warning("zstandard not available, falling back to gzip")
            compression = 'gzip'
        else:
            output_file = output_path.with_suffix('.cathedral.tar.zst')
            return _compress_zstd(package_dir, output_file, level)

    if compression == 'gzip':
        output_file = output_path.with_suffix('.cathedral.tar.gz')
        return _compress_gzip(package_dir, output_file, level)

    raise ValueError(f"Unknown compression type: {compression}")


def _compress_gzip(package_dir: Path, output_file: Path, level: Optional[int]) -> Path:
    """Compress using gzip"""
    if level is None:
        level = 6  # Default gzip level

    logger.info(f"Compressing with gzip (level {level})...")

    with tarfile.open(output_file, 'w:gz', compresslevel=level) as tar:
        tar.add(package_dir, arcname=package_dir.name)

    original_size = sum(f.stat().st_size for f in package_dir.rglob('*') if f.is_file())
    compressed_size = output_file.stat().st_size
    ratio = (1 - compressed_size / original_size) * 100

    logger.info(f"✓ Compressed: {original_size / 1024 / 1024:.2f} MB → {compressed_size / 1024 / 1024:.2f} MB ({ratio:.1f}% reduction)")

    return output_file


def _compress_zstd(package_dir: Path, output_file: Path, level: Optional[int]) -> Path:
    """Compress using zstandard"""
    if level is None:
        level = 3  # Default zstd level (faster than gzip at same ratio)

    logger.info(f"Compressing with zstd (level {level})...")

    # Create uncompressed tar first
    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.tar', delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # Create tar archive
        with tarfile.open(tmp_path, 'w') as tar:
            tar.add(package_dir, arcname=package_dir.name)

        # Compress with zstd
        cctx = zstd.ZstdCompressor(level=level)
        with open(tmp_path, 'rb') as f_in:
            with open(output_file, 'wb') as f_out:
                cctx.copy_stream(f_in, f_out)

    finally:
        tmp_path.unlink(missing_ok=True)

    original_size = sum(f.stat().st_size for f in package_dir.rglob('*') if f.is_file())
    compressed_size = output_file.stat().st_size
    ratio = (1 - compressed_size / original_size) * 100

    logger.info(f"✓ Compressed: {original_size / 1024 / 1024:.2f} MB → {compressed_size / 1024 / 1024:.2f} MB ({ratio:.1f}% reduction)")

    return output_file


def decompress_package(archive_path: Path, output_dir: Path) -> Path:
    """
    Decompress a .cathedral archive

    Args:
        archive_path: Path to compressed archive
        output_dir: Directory to extract to

    Returns:
        Path to extracted .cathedral directory

    Raises:
        ValueError: If compression type not supported
        FileNotFoundError: If archive doesn't exist
    """
    if not archive_path.exists():
        raise FileNotFoundError(f"Archive not found: {archive_path}")

    compression = detect_compression(archive_path)

    if compression == 'none':
        logger.info("Package is already uncompressed")
        return archive_path

    logger.info(f"Decompressing {compression} archive...")

    if compression == 'zstd':
        return _decompress_zstd(archive_path, output_dir)
    elif compression == 'gzip':
        return _decompress_gzip(archive_path, output_dir)

    raise ValueError(f"Unknown compression type: {compression}")


def _decompress_gzip(archive_path: Path, output_dir: Path) -> Path:
    """Decompress gzip archive"""
    output_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(archive_path, 'r:gz') as tar:
        # Extract all members
        tar.extractall(output_dir)

        # Get the extracted directory name (should be first member)
        members = tar.getmembers()
        if members:
            first_member = members[0].name.split('/')[0]
            extracted_dir = output_dir / first_member
            logger.info(f"✓ Decompressed to: {extracted_dir}")
            return extracted_dir

    raise ValueError("Archive appears to be empty")


def _decompress_zstd(archive_path: Path, output_dir: Path) -> Path:
    """Decompress zstandard archive"""
    if not ZSTD_AVAILABLE:
        raise ImportError("zstandard module required for .tar.zst decompression")

    output_dir.mkdir(parents=True, exist_ok=True)

    import tempfile
    with tempfile.NamedTemporaryFile(suffix='.tar', delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        # Decompress with zstd
        dctx = zstd.ZstdDecompressor()
        with open(archive_path, 'rb') as f_in:
            with open(tmp_path, 'wb') as f_out:
                dctx.copy_stream(f_in, f_out)

        # Extract tar
        with tarfile.open(tmp_path, 'r') as tar:
            tar.extractall(output_dir)

            members = tar.getmembers()
            if members:
                first_member = members[0].name.split('/')[0]
                extracted_dir = output_dir / first_member
                logger.info(f"✓ Decompressed to: {extracted_dir}")
                return extracted_dir

    finally:
        tmp_path.unlink(missing_ok=True)

    raise ValueError("Archive appears to be empty")


def get_compression_info(package_path: Path) -> dict:
    """
    Get information about package compression

    Returns:
        dict with keys: compression, size, size_mb, is_compressed
    """
    compression = detect_compression(package_path)

    if compression == 'none':
        # Directory - calculate total size
        if package_path.is_dir():
            size = sum(f.stat().st_size for f in package_path.rglob('*') if f.is_file())
        else:
            size = 0
    else:
        # Compressed file
        size = package_path.stat().st_size

    return {
        'compression': compression,
        'size': size,
        'size_mb': size / 1024 / 1024,
        'is_compressed': compression != 'none'
    }


# Convenience functions for CLI
def auto_compress(package_dir: Path, prefer_zstd: bool = True, level: Optional[int] = None) -> Path:
    """
    Automatically compress package with best available compression

    Args:
        package_dir: Path to .cathedral directory
        prefer_zstd: Prefer zstd if available (default: True)
        level: Compression level (None = default, gzip: 1-9, zstd: 1-22)

    Returns:
        Path to compressed archive
    """
    # Determine compression type
    if prefer_zstd and ZSTD_AVAILABLE:
        compression = 'zstd'
    else:
        compression = 'gzip'

    # Output path (remove .cathedral suffix, will be added by compress_package)
    output_path = package_dir.parent / package_dir.stem

    return compress_package(package_dir, output_path, compression, level=level)


def auto_decompress(package_path: Path) -> Path:
    """
    Automatically decompress package if compressed, otherwise return as-is

    Args:
        package_path: Path to package (compressed or uncompressed)

    Returns:
        Path to uncompressed .cathedral directory
    """
    compression = detect_compression(package_path)

    if compression == 'none':
        return package_path

    # Decompress to same directory as archive
    output_dir = package_path.parent
    return decompress_package(package_path, output_dir)
