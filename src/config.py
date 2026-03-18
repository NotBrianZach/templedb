#!/usr/bin/env python3
"""
TempleDB Configuration - Single Source of Truth
All configuration values defined in one place
"""

import os
from pathlib import Path

# Database
DB_PATH = os.environ.get(
    'TEMPLEDB_PATH',
    os.path.expanduser("~/.local/share/templedb/templedb.sqlite")
)
DB_DIR = os.path.dirname(DB_PATH)

# Ensure database directory exists
os.makedirs(DB_DIR, exist_ok=True)

# Directories
NIX_ENV_DIR = os.path.join(DB_DIR, "nix-envs")
MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

# Editor
EDITOR = os.environ.get('EDITOR', 'vim')

# Project root (where TempleDB is installed)
PROJECT_ROOT = Path(__file__).parent.parent

# Defaults
DEFAULT_BRANCH = 'master'
DEFAULT_AUTHOR = os.environ.get('USER', 'unknown')

# VCS
VCS_ENABLED = True

# TUI
TUI_THEME = "dark"  # or "light"

# Large Blob Storage Configuration
# Files larger than this threshold are stored externally on filesystem
BLOB_INLINE_THRESHOLD = int(os.environ.get(
    'TEMPLEDB_BLOB_INLINE_THRESHOLD',
    10 * 1024 * 1024  # 10MB default
))

# Maximum file size that can be stored (prevents runaway imports)
BLOB_MAX_SIZE = int(os.environ.get(
    'TEMPLEDB_BLOB_MAX_SIZE',
    1024 * 1024 * 1024  # 1GB default
))

# Chunk size for streaming large files
BLOB_CHUNK_SIZE = int(os.environ.get(
    'TEMPLEDB_BLOB_CHUNK_SIZE',
    50 * 1024 * 1024  # 50MB chunks
))

# Blob storage directories
BLOB_STORAGE_DIR = os.path.join(DB_DIR, "blobs")
BLOB_CACHE_DIR = os.path.join(DB_DIR, "blob-cache")

# Compression settings
BLOB_COMPRESSION_ENABLED = os.environ.get(
    'TEMPLEDB_BLOB_COMPRESSION',
    'true'
).lower() in ('true', '1', 'yes')

BLOB_COMPRESSION_THRESHOLD = int(os.environ.get(
    'TEMPLEDB_BLOB_COMPRESSION_THRESHOLD',
    1 * 1024 * 1024  # Compress blobs >1MB
))

# Lazy fetch (download blobs on-demand)
BLOB_LAZY_FETCH = os.environ.get(
    'TEMPLEDB_BLOB_LAZY_FETCH',
    'false'  # Disabled by default for reliability
).lower() in ('true', '1', 'yes')

# Cache settings (for remote blobs, future use)
BLOB_CACHE_MAX_SIZE = int(os.environ.get(
    'TEMPLEDB_BLOB_CACHE_MAX_SIZE',
    10 * 1024 * 1024 * 1024  # 10GB
))

BLOB_CACHE_EVICTION_POLICY = os.environ.get(
    'TEMPLEDB_BLOB_CACHE_EVICTION_POLICY',
    'lru'  # lru, lfu, fifo
).lower()

# Ensure blob directories exist
os.makedirs(BLOB_STORAGE_DIR, exist_ok=True)
os.makedirs(BLOB_CACHE_DIR, exist_ok=True)

# Logging Configuration
LOG_LEVEL = os.environ.get('TEMPLEDB_LOG_LEVEL', 'INFO')
LOG_FILE = os.path.join(DB_DIR, "templedb.log")
LOG_TO_FILE = os.environ.get('TEMPLEDB_LOG_TO_FILE', 'false').lower() in ('true', '1', 'yes')

# Deployment Configuration
DEPLOYMENT_USE_FHS = os.environ.get('TEMPLEDB_DEPLOYMENT_USE_FHS', 'true').lower() in ('true', '1', 'yes')

# Full FHS integration (default: TRUE - deployments run in isolated FHS environments)
DEPLOYMENT_USE_FULL_FHS = os.environ.get('TEMPLEDB_DEPLOYMENT_USE_FULL_FHS', 'true').lower() in ('true', '1', 'yes')

DEPLOYMENT_FHS_DIR = Path(os.environ.get(
    'TEMPLEDB_DEPLOYMENT_FHS_DIR',
    os.path.join(DB_DIR, "fhs-deployments")
))
DEPLOYMENT_FALLBACK_DIR = Path(os.environ.get(
    'TEMPLEDB_DEPLOYMENT_FALLBACK_DIR',
    "/tmp"
))

# Initialize logging system on import
# This ensures all modules get the configured logger
import logger as _logger
_logger.setup_logging(
    level=LOG_LEVEL,
    log_file=Path(LOG_FILE) if LOG_TO_FILE else None,
    verbose=False
)
