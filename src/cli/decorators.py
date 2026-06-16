#!/usr/bin/env python3
"""
CLI Command Decorators

Provides decorators for consistent error handling and behavior across commands.
"""
from functools import wraps
from typing import Callable
from logger import get_logger

logger = get_logger(__name__)


def safe_command(command_name: str = None):
    """
    Decorator for command methods that provides consistent error handling.

    Catches typed exceptions (ValidationError, ResourceNotFoundError, etc.)
    and presents them to the user in a friendly way.

    Usage:
        @safe_command("project_init")
        def init_project(self, args) -> int:
            # No try-catch needed
            result = self.service.init_project(...)
            print(f"Success: {result}")
            return 0

    Args:
        command_name: Optional command name for logging (defaults to function name)

    Returns:
        Decorated function that catches and handles exceptions
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> int:
            cmd_name = command_name or func.__name__
            # args[1] is the argparse Namespace when called as self.method(args)
            ns = args[1] if len(args) > 1 else None

            try:
                return func(*args, **kwargs)

            except ImportError:
                raise

            except Exception as e:
                from error_handler import (
                    TempleDBError,
                    ResourceNotFoundError,
                    ValidationError,
                    DeploymentError
                )

                solution = getattr(e, 'solution', None)

                if isinstance(e, ResourceNotFoundError):
                    _safe_emit_error(ns, "NOT_FOUND", str(e), solution)
                    return 1

                if isinstance(e, ValidationError):
                    _safe_emit_error(ns, "VALIDATION_ERROR", str(e), solution)
                    return 1

                if isinstance(e, DeploymentError):
                    _safe_emit_error(ns, "DEPLOYMENT_ERROR", str(e), solution)
                    return 1

                if isinstance(e, TempleDBError):
                    _safe_emit_error(ns, "TEMPLEDB_ERROR", f"{cmd_name} failed: {e}", solution)
                    return 1

                _safe_emit_error(ns, "INTERNAL_ERROR", f"{cmd_name} failed: {e}", solution)
                logger.debug("Full error details:", exc_info=True)
                return 1

        return wrapper
    return decorator


def _safe_emit_error(ns, code: str, message: str, solution=None) -> None:
    """Emit error as JSON or log it, depending on --json flag."""
    try:
        import argparse
        from cli.json_output import emit_error
        if ns is not None and isinstance(ns, argparse.Namespace):
            emit_error(ns, code, message, solution=solution)
            return
    except Exception:
        pass
    logger.error(message)
    if solution:
        logger.info(f"Hint: {solution}")


def require_project(func: Callable) -> Callable:
    """
    Decorator that ensures a project exists before running the command.

    Usage:
        @require_project
        def deploy(self, args) -> int:
            # args.project is guaranteed to exist
            ...

    Expects:
        - Command class has self.service with get_project() method
        - args has a 'project' attribute with project slug
    """
    @wraps(func)
    def wrapper(self, args, *extra_args, **kwargs) -> int:
        from error_handler import ResourceNotFoundError

        project_slug = getattr(args, 'project', None) or getattr(args, 'slug', None)

        if not project_slug:
            logger.error("No project specified")
            return 1

        try:
            # Validate project exists
            if hasattr(self, 'service'):
                if hasattr(self.service, 'get_project'):
                    self.service.get_project(project_slug)
                elif hasattr(self.service, 'get_by_slug'):
                    self.service.get_by_slug(project_slug, required=True)

            # Call original function
            return func(self, args, *extra_args, **kwargs)

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

    return wrapper


def log_command(func: Callable) -> Callable:
    """
    Decorator that logs command execution for audit trail.

    Usage:
        @log_command
        def deploy(self, args) -> int:
            ...

    Logs:
        - Command start
        - Command completion
        - Exit code
    """
    @wraps(func)
    def wrapper(*args, **kwargs) -> int:
        command_name = func.__name__
        logger.debug(f"Command started: {command_name}")

        result = func(*args, **kwargs)

        logger.debug(f"Command completed: {command_name} (exit code: {result})")
        return result

    return wrapper


def with_confirmation(message: str = "Are you sure?"):
    """
    Decorator that requires user confirmation before executing.

    Usage:
        @with_confirmation("Delete project and all data?")
        def remove_project(self, args) -> int:
            ...

    Args:
        message: Confirmation message to display

    Respects:
        - args.force: Skip confirmation if True
        - args.yes: Skip confirmation if True
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(self, args, *extra_args, **kwargs) -> int:
            # Check for force flags
            force = getattr(args, 'force', False) or getattr(args, 'yes', False)

            if not force:
                response = input(f"{message} (yes/no): ")
                if response.lower() != 'yes':
                    print("Cancelled")
                    return 0

            return func(self, args, *extra_args, **kwargs)

        return wrapper
    return decorator
