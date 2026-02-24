"""
Centralized logging configuration for TempleDB.

This module sets up a unified logging system with:
- Configurable log levels (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- Console output with colored formatting
- Optional file logging
- Structured log format with timestamps
"""

import logging
import os
import sys
from pathlib import Path
from typing import Optional


class ColoredFormatter(logging.Formatter):
    """Custom formatter with color support for console output."""

    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m'        # Reset
    }

    def __init__(self, fmt: Optional[str] = None, use_color: bool = True):
        super().__init__(fmt)
        self.use_color = use_color and sys.stdout.isatty()

    def format(self, record: logging.LogRecord) -> str:
        if self.use_color:
            levelname = record.levelname
            if levelname in self.COLORS:
                record.levelname = f"{self.COLORS[levelname]}{levelname}{self.COLORS['RESET']}"
        return super().format(record)


def setup_logging(
    level: Optional[str] = None,
    log_file: Optional[Path] = None,
    verbose: bool = False
) -> logging.Logger:
    """
    Configure logging for TempleDB.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
               If None, reads from TEMPLEDB_LOG_LEVEL env var or defaults to INFO.
        log_file: Optional path to log file. If provided, logs will be written to file.
        verbose: If True, sets level to DEBUG regardless of other settings.

    Returns:
        Configured root logger instance.

    Example:
        >>> logger = setup_logging(verbose=True)
        >>> logger.debug("Debug message")
        >>> logger.info("Info message")
        >>> logger.warning("Warning message")
    """
    # Determine log level
    if verbose:
        log_level = logging.DEBUG
    elif level:
        log_level = getattr(logging, level.upper(), logging.INFO)
    else:
        env_level = os.getenv('TEMPLEDB_LOG_LEVEL', 'INFO').upper()
        log_level = getattr(logging, env_level, logging.INFO)

    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    # Console handler with colored output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)

    console_format = '%(levelname)-8s %(message)s'
    if log_level == logging.DEBUG:
        console_format = '%(asctime)s [%(levelname)-8s] %(name)s:%(lineno)d - %(message)s'

    console_formatter = ColoredFormatter(console_format)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.DEBUG)  # Always log everything to file

        file_format = '%(asctime)s [%(levelname)-8s] %(name)s:%(lineno)d - %(message)s'
        file_formatter = logging.Formatter(file_format)
        file_handler.setFormatter(file_formatter)
        root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance for a specific module.

    Args:
        name: Logger name, typically __name__ from the calling module.

    Returns:
        Logger instance configured with the module name.

    Example:
        >>> logger = get_logger(__name__)
        >>> logger.info("Module initialized")
    """
    return logging.getLogger(name)


# Convenience functions for quick migration from print()
def info(msg: str) -> None:
    """Log info message (replaces print for informational output)."""
    logging.getLogger('templedb').info(msg)


def debug(msg: str) -> None:
    """Log debug message (replaces print for detailed diagnostics)."""
    logging.getLogger('templedb').debug(msg)


def warning(msg: str) -> None:
    """Log warning message (replaces print for warnings)."""
    logging.getLogger('templedb').warning(msg)


def error(msg: str) -> None:
    """Log error message (replaces print for errors)."""
    logging.getLogger('templedb').error(msg)


# Example usage patterns for migration:
#
# OLD: print("Processing project...")
# NEW: logger.info("Processing project...")
#
# OLD: print(f"Debug: value={value}")
# NEW: logger.debug(f"Debug: value={value}")
#
# OLD: print(f"⚠️  Warning: {issue}")
# NEW: logger.warning(f"Warning: {issue}")
#
# OLD: print(f"Error: {error}")
# NEW: logger.error(f"Error: {error}")
