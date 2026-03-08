"""
Centralized error handling for TempleDB CLI commands.

This module provides user-friendly error messages and consistent error handling
across all CLI commands.
"""

import sqlite3
import logging
from typing import Optional, Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)


class TempleDBError(RuntimeError):
    """Base exception for all TempleDB application errors."""
    pass


class ValidationError(TempleDBError):
    """Raised when input validation fails."""
    pass


class ResourceNotFoundError(TempleDBError):
    """Raised when a requested resource doesn't exist."""
    pass


class ConfigurationError(TempleDBError):
    """Raised when configuration is invalid or missing."""
    pass


class DeploymentError(TempleDBError):
    """Raised when deployment operations fail."""
    pass


class DatabaseError(TempleDBError):
    """Raised when database operations fail."""
    pass


class ErrorHandler:
    """Centralized error handling for CLI commands."""

    @staticmethod
    def format_error(problem: str, context: Optional[str] = None,
                    solution: Optional[str] = None) -> str:
        """
        Format a user-friendly error message.

        Args:
            problem: What went wrong
            context: Additional context about the error
            solution: How to fix it

        Returns:
            Formatted error message
        """
        parts = [f"Error: {problem}"]
        if context:
            parts.append(f"  Context: {context}")
        if solution:
            parts.append(f"  Fix: {solution}")
        return "\n".join(parts)

    @staticmethod
    def handle_command_error(e: Exception, command: str,
                           context: Optional[Dict[str, Any]] = None) -> int:
        """
        Convert any exception to user-friendly message and return appropriate exit code.

        Args:
            e: The exception that was raised
            command: Name of the command that failed
            context: Additional context about the operation (e.g., {"slug": "myproject"})

        Returns:
            Exit code (0=success, 1=expected error, 2=application error)
        """
        context = context or {}

        # Handle SQLite integrity errors (constraint violations)
        if isinstance(e, sqlite3.IntegrityError):
            error_msg = str(e).lower()

            if "unique constraint failed: projects.slug" in error_msg:
                slug = context.get('slug', 'unknown')
                logger.error(f"Project slug '{slug}' already exists")
                logger.info("Use 'templedb project list' to see existing projects")
                logger.info("Or use 'templedb project import' to import into existing project")
                return 1

            elif "unique constraint failed" in error_msg:
                logger.error(f"Duplicate entry: {e}")
                logger.info("This record already exists in the database")
                return 1

            elif "foreign key constraint failed" in error_msg:
                logger.error("Cannot complete operation: referenced record doesn't exist")
                logger.info("Check that all referenced projects/files exist first")
                return 1

            elif "not null constraint failed" in error_msg:
                logger.error(f"Missing required field: {e}")
                logger.info("All required fields must be provided")
                return 1

            else:
                logger.error(f"Database constraint violation: {e}")
                return 1

        # Handle SQLite operational errors (schema, connection issues)
        elif isinstance(e, sqlite3.OperationalError):
            error_msg = str(e).lower()

            if "no such table" in error_msg:
                logger.error("Database schema is missing or outdated")
                logger.info("Try: templedb init (to initialize database)")
                logger.info("Or check that you're in a TempleDB project directory")
                return 1

            elif "no such column" in error_msg:
                logger.error("Database schema is outdated")
                logger.info("Your database schema needs to be updated")
                logger.info("This may require running migrations or reinitializing")
                return 1

            elif "database is locked" in error_msg:
                logger.error("Database is locked by another process")
                logger.info("Wait for other operations to complete or check for stale locks")
                return 1

            elif "unable to open database file" in error_msg:
                logger.error("Cannot access database file")
                logger.info("Check file permissions and that the path is correct")
                return 1

            else:
                logger.error(f"Database operation failed: {e}")
                logger.debug("Full error details:", exc_info=True)
                return 1

        # Handle SQLite programming errors (SQL syntax issues)
        elif isinstance(e, sqlite3.ProgrammingError):
            logger.error(f"Database programming error: {e}")
            logger.debug("This is likely a bug. Full traceback:", exc_info=True)
            logger.info("Please report this issue at https://github.com/anthropics/templedb/issues")
            return 2

        # Handle SQLite database errors (generic)
        elif isinstance(e, sqlite3.DatabaseError):
            logger.error(f"Database error: {e}")
            logger.debug("Full error details:", exc_info=True)
            return 1

        # Handle file not found errors
        elif isinstance(e, FileNotFoundError):
            file_path = context.get('file_path') or str(e)
            logger.error(f"File not found: {file_path}")

            # Provide context-specific guidance
            if 'script' in file_path or '.sh' in file_path:
                logger.info("Check that the script exists and has execute permissions")
                logger.info("Try: ls -la /path/to/script")
            else:
                logger.info("Check that the path is correct and the file exists")
            return 1

        # Handle permission errors
        elif isinstance(e, PermissionError):
            file_path = context.get('file_path') or str(e)
            logger.error(f"Permission denied: {file_path}")
            logger.info("Check file/directory permissions")
            logger.info("You may need to run: chmod +x <file> or change ownership")
            return 1

        # Handle application-specific errors
        elif isinstance(e, ValidationError):
            logger.error(f"Validation error: {e}")
            return 1

        elif isinstance(e, ResourceNotFoundError):
            logger.error(f"Resource not found: {e}")
            return 1

        elif isinstance(e, ConfigurationError):
            logger.error(f"Configuration error: {e}")
            return 1

        elif isinstance(e, DeploymentError):
            logger.error(f"Deployment failed: {e}")
            logger.debug("Full error details:", exc_info=True)
            return 1

        elif isinstance(e, DatabaseError):
            logger.error(f"Database error: {e}")
            logger.debug("Full error details:", exc_info=True)
            return 1

        elif isinstance(e, TempleDBError):
            logger.error(str(e))
            return 2

        # Handle unexpected errors
        else:
            logger.error(f"Unexpected error in '{command}': {e}")
            logger.debug("Full traceback:", exc_info=True)
            logger.info("If this error persists, please report it at:")
            logger.info("https://github.com/anthropics/templedb/issues")
            return 1

    @staticmethod
    def log_non_critical_error(operation: str, error: Exception) -> None:
        """
        Log a non-critical error that doesn't stop the main operation.

        Use this for best-effort operations like audit logging, metrics, etc.

        Args:
            operation: Name of the operation that failed
            error: The exception that occurred
        """
        logger.warning(f"{operation} failed (non-critical): {error}")
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(f"{operation} failure traceback:", exc_info=True)
