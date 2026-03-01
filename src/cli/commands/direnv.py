#!/usr/bin/env python3
"""
Direnv integration command
"""
import sys
from pathlib import Path

# Import will be resolved at runtime
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class DirenvCommand(Command):
    """Direnv integration command handlers"""

    def __init__(self):
        super().__init__()

    def generate(self, args) -> int:
        """Generate direnv-compatible output for a project"""
        try:
            # Import the actual implementation from main.py
            from main import cmd_direnv

            # Get connection using the base class method
            conn = self.get_connection()

            try:
                cmd_direnv(
                    conn,
                    args.slug,
                    args.profile,
                    args.load_nix,
                    getattr(args, 'branch', None),
                    getattr(args, 'ref', None)
                )
                return 0
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"direnv failed: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            return 1


def register(cli):
    """Register direnv command with CLI"""
    cmd = DirenvCommand()

    # Create direnv command (top-level, not a subcommand)
    direnv_parser = cli.register_command(
        'direnv',
        cmd.generate,
        help_text='Generate direnv-compatible output'
    )

    direnv_parser.add_argument('slug', nargs='?', help='Project slug (inferred from cwd if omitted)')
    direnv_parser.add_argument('--profile', default='default', help='Secret profile to use')
    direnv_parser.add_argument('--no-nix', dest='load_nix', action='store_false', default=True,
                              help="Don't emit 'use nix' directive")
    direnv_parser.add_argument('--branch', help='Override git branch (auto-detected if not specified)')
    direnv_parser.add_argument('--ref', help='Override git ref/commit (auto-detected if not specified)')
