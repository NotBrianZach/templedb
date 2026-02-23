#!/usr/bin/env python3
"""
TempleDB CLI Core - Unified argparse-based command routing
Replaces the dual CLI system (main.py + templedb_cli.py)
"""
import argparse
import sys
from typing import Callable, Dict, Any, Optional
from pathlib import Path


class TempleDBCLI:
    """
    Unified CLI for TempleDB using argparse.

    Provides consistent command routing, help generation, and error handling
    across all TempleDB commands.
    """

    def __init__(self):
        self.parser = argparse.ArgumentParser(
            prog="templedb",
            description="TempleDB - Database-native project management",
            epilog="Use 'templedb <command> --help' for command-specific help"
        )
        self.parser.add_argument('--version', action='version', version='TempleDB 0.7.0')
        self.subparsers = self.parser.add_subparsers(dest="command", required=True)

        # Command registry: maps command names to handler functions
        self.commands: Dict[str, Callable] = {}

    def register_command(
        self,
        name: str,
        handler: Callable,
        help_text: str = "",
        **parser_kwargs
    ) -> argparse.ArgumentParser:
        """
        Register a command with its handler function.

        Args:
            name: Command name (e.g., 'project', 'vcs')
            handler: Function to call when command is invoked
            help_text: Help text for the command
            **parser_kwargs: Additional arguments for add_parser()

        Returns:
            Subparser for this command (to add arguments)
        """
        self.commands[name] = handler
        return self.subparsers.add_parser(
            name,
            help=help_text,
            **parser_kwargs
        )

    def register_subcommand(
        self,
        parent: str,
        name: str,
        handler: Callable,
        help_text: str = ""
    ) -> argparse.ArgumentParser:
        """
        Register a subcommand (e.g., 'project import', 'vcs commit').

        Args:
            parent: Parent command name
            name: Subcommand name
            handler: Function to call
            help_text: Help text

        Returns:
            Subparser for adding arguments
        """
        # Get or create parent subparsers
        if parent not in self.commands:
            parent_parser = self.register_command(parent, None, help_text=f"{parent} commands")
            subparsers = parent_parser.add_subparsers(dest=f"{parent}_subcommand", required=True)
        else:
            # Parent exists, get its subparsers
            parent_parser = next(
                (action for action in self.subparsers._actions
                 if hasattr(action, 'dest') and action.dest == parent),
                None
            )
            if parent_parser:
                subparsers = parent_parser.add_subparsers(dest=f"{parent}_subcommand")
            else:
                raise ValueError(f"Parent command '{parent}' not properly registered")

        # Register the subcommand handler
        command_key = f"{parent}.{name}"
        self.commands[command_key] = handler

        return subparsers.add_parser(name, help=help_text)

    def execute(self, argv: Optional[list] = None) -> int:
        """
        Parse arguments and execute the appropriate command.

        Args:
            argv: Command-line arguments (default: sys.argv[1:])

        Returns:
            Exit code (0 for success, non-zero for error)
        """
        try:
            args = self.parser.parse_args(argv)

            # Determine which command to run
            if '.' in args.command:
                # Direct subcommand
                handler = self.commands.get(args.command)
            else:
                # Check for subcommand in args
                subcommand_attr = f"{args.command}_subcommand"
                if hasattr(args, subcommand_attr):
                    subcommand = getattr(args, subcommand_attr)
                    handler = self.commands.get(f"{args.command}.{subcommand}")
                else:
                    handler = self.commands.get(args.command)

            if handler is None:
                self.parser.error(f"No handler registered for command: {args.command}")
                return 1

            # Execute the command
            result = handler(args)

            # Return exit code (0 if None)
            return result if result is not None else 0

        except KeyboardInterrupt:
            print("\nInterrupted", file=sys.stderr)
            return 130
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            if '--debug' in (argv or sys.argv):
                import traceback
                traceback.print_exc()
            return 1


class Command:
    """
    Base class for command handlers.

    Provides common functionality like database access, formatting, etc.
    """

    def __init__(self):
        # Import here to avoid circular imports
        sys.path.insert(0, str(Path(__file__).parent.parent))
        from db_utils import (
            get_connection,
            query_one,
            query_all,
            execute,
            DB_PATH
        )
        self.get_connection = get_connection
        self.query_one = query_one
        self.query_all = query_all
        self.execute = execute
        self.db_path = DB_PATH

    def format_table(self, rows: list, columns: list, title: Optional[str] = None) -> str:
        """
        Format rows as ASCII table.

        Args:
            rows: List of dicts with row data
            columns: List of column names to display
            title: Optional title for the table

        Returns:
            Formatted table string
        """
        if not rows:
            return ""

        # Calculate column widths
        widths = {col: len(col) for col in columns}
        for row in rows:
            for col in columns:
                value = str(row.get(col, ''))
                widths[col] = max(widths[col], len(value))

        # Build output
        lines = []

        if title:
            lines.append(f"\n{title}\n")

        # Header
        header = ' '.join(f"{col:<{widths[col]}}" for col in columns)
        lines.append(header)
        lines.append('-' * len(header))

        # Rows
        for row in rows:
            line = ' '.join(f"{str(row.get(col, '')):<{widths[col]}}" for col in columns)
            lines.append(line)

        lines.append('')  # Empty line at end
        return '\n'.join(lines)

    def get_project_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        """Get project by slug"""
        return self.query_one("SELECT * FROM projects WHERE slug = ?", (slug,))

    def get_project_or_exit(self, slug: str) -> Dict[str, Any]:
        """Get project by slug or exit with error"""
        project = self.get_project_by_slug(slug)
        if not project:
            print(f"Error: Project '{slug}' not found", file=sys.stderr)
            sys.exit(1)
        return project


# Global CLI instance
cli = TempleDBCLI()
