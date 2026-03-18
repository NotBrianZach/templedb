#!/usr/bin/env python3
"""
Error handling utilities and decorators for TempleDB CLI commands.

This module provides convenient decorators and helper functions to standardize
error handling across all CLI commands.
"""

import sys
import functools
from typing import Callable, Optional, Dict, Any
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from error_handler import (
    ErrorHandler,
    TempleDBError,
    ValidationError,
    ResourceNotFoundError,
    ConfigurationError,
    DeploymentError,
    DatabaseError
)
from logger import get_logger

logger = get_logger(__name__)


def handle_errors(command_name: str):
    """
    Decorator to standardize error handling in CLI command methods.

    Usage:
        @handle_errors("project import")
        def project_import(self, args) -> int:
            # Your command logic here
            # Raise exceptions as needed
            # Return 0 for success
            pass

    The decorator will:
    - Catch all exceptions
    - Log them appropriately
    - Return proper exit codes
    - Provide user-friendly error messages

    Args:
        command_name: Name of the command (for logging/error messages)

    Returns:
        Decorated function that returns int (exit code)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self, args) -> int:
            try:
                return func(self, args)
            except Exception as e:
                # Extract context from args if available
                context = {}
                if hasattr(args, 'project'):
                    context['slug'] = args.project
                if hasattr(args, 'file_path'):
                    context['file_path'] = args.file_path

                # Use centralized error handler
                return ErrorHandler.handle_command_error(e, command_name, context)

        return wrapper
    return decorator


def require_project(func: Callable) -> Callable:
    """
    Decorator to validate that a project exists before executing command.

    Usage:
        @require_project
        def some_command(self, args) -> int:
            # args.project is guaranteed to exist in database
            pass

    Raises:
        ResourceNotFoundError: If project doesn't exist
    """
    @functools.wraps(func)
    def wrapper(self, args) -> int:
        if not hasattr(args, 'project') or not args.project:
            raise ValidationError("Project slug is required")

        # Check if project exists
        project = self.query_one(
            "SELECT id, slug, name FROM projects WHERE slug = ?",
            (args.project,)
        )

        if not project:
            raise ResourceNotFoundError(
                f"Project '{args.project}' not found. "
                f"Use './templedb project list' to see available projects."
            )

        return func(self, args)

    return wrapper


def validate_path_exists(path_arg: str = 'path'):
    """
    Decorator to validate that a file/directory path exists.

    Usage:
        @validate_path_exists('file_path')
        def some_command(self, args) -> int:
            # args.file_path is guaranteed to exist
            pass

    Args:
        path_arg: Name of the argument containing the path (default: 'path')

    Raises:
        ValidationError: If path doesn't exist
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(self, args) -> int:
            path_value = getattr(args, path_arg, None)

            if not path_value:
                raise ValidationError(f"Path argument '{path_arg}' is required")

            path = Path(path_value)
            if not path.exists():
                raise ValidationError(
                    f"Path does not exist: {path}\n"
                    f"Check that the path is correct and accessible."
                )

            return func(self, args)

        return wrapper
    return decorator


def print_error(message: str, context: Optional[str] = None,
                solution: Optional[str] = None) -> None:
    """
    Print a formatted error message to the user.

    Usage:
        print_error(
            "Failed to import project",
            context="Repository URL may be invalid",
            solution="Check the URL and try again"
        )

    Args:
        message: Main error message
        context: Additional context about the error
        solution: Suggested fix for the user
    """
    formatted = ErrorHandler.format_error(message, context, solution)
    print(f"❌ {formatted}")
    logger.error(message)
    if context:
        logger.debug(f"Context: {context}")


def print_warning(message: str) -> None:
    """
    Print a warning message to the user.

    Usage:
        print_warning("Database schema may be outdated")

    Args:
        message: Warning message
    """
    print(f"⚠️  Warning: {message}")
    logger.warning(message)


def print_success(message: str) -> None:
    """
    Print a success message to the user.

    Usage:
        print_success("Project imported successfully")

    Args:
        message: Success message
    """
    print(f"✅ {message}")
    logger.info(message)


def confirm_action(prompt: str, default: bool = False) -> bool:
    """
    Ask user to confirm an action.

    Usage:
        if confirm_action("Delete all projects?", default=False):
            # Proceed with deletion
            pass

    Args:
        prompt: Question to ask the user
        default: Default response if user just presses Enter

    Returns:
        True if user confirms, False otherwise
    """
    suffix = " [Y/n]" if default else " [y/N]"

    try:
        response = input(f"{prompt}{suffix} ").strip().lower()

        if not response:
            return default

        return response in ('y', 'yes')

    except (KeyboardInterrupt, EOFError):
        print()  # New line after ^C
        return False


# Export all error classes for convenience
__all__ = [
    'handle_errors',
    'require_project',
    'validate_path_exists',
    'print_error',
    'print_warning',
    'print_success',
    'confirm_action',
    'TempleDBError',
    'ValidationError',
    'ResourceNotFoundError',
    'ConfigurationError',
    'DeploymentError',
    'DatabaseError',
    'ErrorHandler'
]
