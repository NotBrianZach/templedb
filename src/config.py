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

# Logging Configuration
LOG_LEVEL = os.environ.get('TEMPLEDB_LOG_LEVEL', 'INFO')
LOG_FILE = os.path.join(DB_DIR, "templedb.log")
LOG_TO_FILE = os.environ.get('TEMPLEDB_LOG_TO_FILE', 'false').lower() in ('true', '1', 'yes')

# Initialize logging system on import
# This ensures all modules get the configured logger
from . import logger as _logger
_logger.setup_logging(
    level=LOG_LEVEL,
    log_file=Path(LOG_FILE) if LOG_TO_FILE else None,
    verbose=False
)
