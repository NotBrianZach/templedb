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

    @staticmethod
    def _comparable(content: str):
        """Lines of an .envrc with the volatile header line removed.

        `# Generated: <wall clock>` changes on every call, so comparing
        it answers "was this generated in the same second" rather than
        "is this up to date". Dropped here so both sides of the
        comparison and the rendered diff agree on what counts.
        """
        return [
            line + '\n'
            for line in content.strip().splitlines()
            if not line.startswith('# Generated:')
        ]

    def diff(self, args) -> int:
        """Show diff between current .envrc and what would be generated.

        Absorbed `env direnv verify`, which asked the same question and
        differed only in what it did with the answer: verify printed a
        verdict and exited 1 on a difference, diff rendered the hunks
        and exited 0 either way. That is one comparison with two front
        ends, so the verdict is now `--exit-code`, following git's
        convention that a diff is not an error unless you ask for it.

        The comparison keeps `verify`'s `.strip()` tolerance -- the
        generator does not commit to a trailing newline, and reporting
        drift over one is the false positive that makes a checker
        useless in a hook -- and adds one the old command needed and
        did not have: the `# Generated:` line is excluded.

        That line carries a wall-clock timestamp, so a `.envrc` written
        by `generate --write` stopped matching the generator one second
        later. `verify` therefore answered "differs from TempleDB
        state" for every project unconditionally, including one whose
        file had just been generated from the same data -- a checker
        that cannot pass. Excluding the one volatile line is what makes
        `--exit-code` mean something. Everything else the header
        carries (project, profile, environment) is real state and still
        compared.

        The rendered hunks come from the same normalized comparison, so
        output and exit status cannot disagree.
        """
        try:
            from pathlib import Path
            import difflib
            import io
            import sys

            cwd = Path.cwd()
            envrc_path = cwd / ".envrc"

            if not envrc_path.exists():
                print("No .envrc file exists yet")
                print("Run 'templedb env direnv --write' to create one")
                return 1

            current_content = envrc_path.read_text()

            from direnv_generator import cmd_direnv
            conn = self.get_connection()
            try:
                old_stdout = sys.stdout
                try:
                    sys.stdout = buffer = io.StringIO()
                    cmd_direnv(
                        conn,
                        args.slug,
                        args.profile,
                        args.load_nix,
                        None, None,
                        getattr(args, 'environment', 'default'),
                        False,  # Don't write
                        True,   # auto_reload
                        False   # Don't validate for a comparison
                    )
                finally:
                    sys.stdout = old_stdout
                expected_content = buffer.getvalue()
            finally:
                conn.close()

            current_lines = self._comparable(current_content)
            expected_lines = self._comparable(expected_content)

            if current_lines == expected_lines:
                print("✓ .envrc is up-to-date (no changes)")
                return 0

            sys.stdout.writelines(difflib.unified_diff(
                current_lines,
                expected_lines,
                fromfile=str(envrc_path),
                tofile='(generated)',
            ))

            if getattr(args, 'exit_code', False):
                return 1
            return 0

        except Exception as e:
            logger.error(f"diff failed: {e}", exc_info=True)
            return 1

    def generate(self, args) -> int:
        """Generate direnv-compatible output for a project"""
        try:
            # Import the direnv generator
            from direnv_generator import cmd_direnv

            # Get connection using the base class method
            conn = self.get_connection()

            try:
                cmd_direnv(
                    conn,
                    args.slug,
                    args.profile,
                    args.load_nix,
                    getattr(args, 'branch', None),
                    getattr(args, 'ref', None),
                    getattr(args, 'environment', 'default'),
                    getattr(args, 'write', False),
                    getattr(args, 'auto_reload', True),
                    getattr(args, 'validate', True)
                )
                return 0
            finally:
                conn.close()
        except Exception as e:
            logger.error(f"direnv failed: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
            return 1


def register_subcommands(parent_subparsers, cli, prefix='env'):
    """Register direnv commands as subcommands under a parent (e.g., env direnv generate)."""
    cmd = DirenvCommand()

    direnv_parser = parent_subparsers.add_parser('direnv', help='Direnv integration and .envrc management')
    direnv_parser.add_argument('--profile', default='default',
                               help='Secret profile (default/staging/production, auto-detected from git branch)')
    direnv_parser.add_argument('--environment', '--env', default='default',
                               help='Environment for env_vars (default/development/production)')
    direnv_parser.add_argument('--no-nix', dest='load_nix', action='store_false', default=True,
                               help="Don't emit 'use nix' directive")
    direnv_parser.add_argument('--branch', help='Override git branch detection')
    direnv_parser.add_argument('--ref', help='Override git ref/commit detection')
    direnv_parser.add_argument('--write', '-w', action='store_true',
                               help='Write output to .envrc file (instead of stdout)')
    direnv_parser.add_argument('--no-auto-reload', dest='auto_reload', action='store_false', default=True,
                               help="Don't add watch_file directive for auto-reload")
    direnv_parser.add_argument('--no-validate', dest='validate', action='store_false', default=True,
                               help='Skip validation of generated .envrc')

    subparsers = direnv_parser.add_subparsers(dest='direnv_subcommand')
    direnv_parser.set_defaults(slug=None)
    cli.commands[f'{prefix}.direnv'] = cmd.generate

    gen_parser = subparsers.add_parser('generate', help='Generate .envrc (default if no subcommand)', aliases=['gen'])
    gen_parser.add_argument('slug', nargs='?', help='Project slug (auto-detected from .templedb/ or cwd)')
    gen_parser.add_argument('--profile', default='default',
                           help='Secret profile (default/staging/production, auto-detected from git branch)')
    gen_parser.add_argument('--environment', '--env', default='default',
                           help='Environment for env_vars (default/development/production)')
    gen_parser.add_argument('--no-nix', dest='load_nix', action='store_false', default=True,
                           help="Don't emit 'use nix' directive")
    gen_parser.add_argument('--branch', help='Override git branch detection')
    gen_parser.add_argument('--ref', help='Override git ref/commit detection')
    gen_parser.add_argument('--write', '-w', action='store_true',
                           help='Write output to .envrc file (instead of stdout)')
    gen_parser.add_argument('--no-auto-reload', dest='auto_reload', action='store_false', default=True,
                           help="Don't add watch_file directive for auto-reload")
    gen_parser.add_argument('--no-validate', dest='validate', action='store_false', default=True,
                           help='Skip validation of generated .envrc')
    cli.commands[f'{prefix}.direnv.generate'] = cmd.generate
    cli.commands[f'{prefix}.direnv.gen'] = cmd.generate

    diff_parser = subparsers.add_parser(
        'diff',
        help='Show diff between current .envrc and TempleDB state '
             '(--exit-code to fail on drift; absorbed `verify`)')
    diff_parser.add_argument('slug', nargs='?', help='Project slug (auto-detected)')
    diff_parser.add_argument('--profile', default='default', help='Secret profile')
    diff_parser.add_argument('--environment', '--env', default='default', help='Environment name')
    diff_parser.add_argument('--no-nix', dest='load_nix', action='store_false', default=True)
    diff_parser.add_argument('--exit-code', action='store_true',
                             help='Exit 1 when .envrc differs (was `direnv verify`)')
    cli.commands[f'{prefix}.direnv.diff'] = cmd.diff

