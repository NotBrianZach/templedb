#!/usr/bin/env python3
"""
TempleDB Configuration - Single Source of Truth
All configuration values defined in one place
"""

import os
from pathlib import Path

# Database - handle sudo properly
def _get_db_path():
    """Get database path, using real user's home when run with sudo"""
    if 'TEMPLEDB_PATH' in os.environ:
        return os.environ['TEMPLEDB_PATH']

    # When run with sudo, use SUDO_USER's home
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        return f'/home/{sudo_user}/.local/share/templedb/templedb.sqlite'
    else:
        return os.path.expanduser("~/.local/share/templedb/templedb.sqlite")

DB_PATH = _get_db_path()
DB_DIR = Path(DB_PATH).parent

# Ensure database directory exists.
#
# Guarded on the directory already existing, because os.makedirs walks
# UP: given a leaf it cannot stat, it recurses to the parent and tries
# to create that instead. Inside a systemd sandbox that is fatal at
# import time. woofs-sync.service runs with ProtectHome=true plus a
# BindReadOnlyPaths remount of just the templedb directory, so the DB
# and its directory are both present and readable while /home/zach is
# not -- and this line died with
#
#   PermissionError: [Errno 13] Permission denied: '/home/zach'
#
# before argparse ever ran. The service reported "Failed to load
# DATABASE_URL from TempleDB", which sent three people looking for a
# missing secret that was there the whole time.
#
# Creation failure is tolerated rather than raised: a read-only or
# sandboxed DB directory is a legitimate way to run, and a genuinely
# unusable path still produces a precise error when the connection is
# opened. Dying here only costs us `--help`.
def _ensure_dir(path):
    """mkdir -p that never raises at import time.

    os.makedirs walks UP: given a leaf it cannot stat, it recurses to
    the parent and tries to create that instead. Checking is_dir()
    first means an existing-but-unstattable directory is left alone
    rather than triggering that climb.
    """
    try:
        if not Path(path).is_dir():
            os.makedirs(path, exist_ok=True)
    except OSError:
        pass


_ensure_dir(DB_DIR)

# Directories
NIX_ENV_DIR = DB_DIR / "nix-envs"
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
BLOB_STORAGE_DIR = DB_DIR / "blobs"
BLOB_CACHE_DIR = DB_DIR / "blob-cache"

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

# Ensure blob directories exist (same import-time guard as DB_DIR --
# these sit under DB_DIR, so a sandbox that blocks one blocks all three)
_ensure_dir(BLOB_STORAGE_DIR)
_ensure_dir(BLOB_CACHE_DIR)

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
