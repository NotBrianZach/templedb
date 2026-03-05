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

    def diff(self, args) -> int:
        """Show diff between current .envrc and what would be generated"""
        try:
            from pathlib import Path
            import tempfile
            import subprocess

            cwd = Path.cwd()
            envrc_path = cwd / ".envrc"

            if not envrc_path.exists():
                print("No .envrc file exists yet")
                print("Run 'templedb direnv --write' to create one")
                return 1

            # Generate new content to temp file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.envrc', delete=False) as tmp:
                tmp_path = Path(tmp.name)

            try:
                # Generate to temp file
                from main import cmd_direnv
                conn = self.get_connection()
                try:
                    # Redirect stdout to temp file
                    import sys
                    old_stdout = sys.stdout
                    with open(tmp_path, 'w') as f:
                        sys.stdout = f
                        cmd_direnv(
                            conn,
                            args.slug,
                            args.profile,
                            args.load_nix,
                            None, None,
                            getattr(args, 'environment', 'default'),
                            False,  # Don't write
                            True,   # auto_reload
                            False   # Don't validate for diff
                        )
                    sys.stdout = old_stdout
                finally:
                    conn.close()

                # Show diff
                result = subprocess.run(
                    ['diff', '-u', str(envrc_path), str(tmp_path)],
                    capture_output=True,
                    text=True
                )

                if result.returncode == 0:
                    print("✓ .envrc is up-to-date (no changes)")
                    return 0
                else:
                    print(result.stdout)
                    return 0

            finally:
                tmp_path.unlink()

        except Exception as e:
            logger.error(f"diff failed: {e}", exc_info=True)
            return 1

    def verify(self, args) -> int:
        """Verify .envrc matches TempleDB state"""
        try:
            from pathlib import Path
            cwd = Path.cwd()
            envrc_path = cwd / ".envrc"

            if not envrc_path.exists():
                print("✗ No .envrc file found")
                print("  Run 'templedb direnv --write' to create one")
                return 1

            # Read current file
            current_content = envrc_path.read_text()

            # Generate expected content
            from main import cmd_direnv
            import io
            import sys

            conn = self.get_connection()
            try:
                old_stdout = sys.stdout
                sys.stdout = buffer = io.StringIO()
                cmd_direnv(
                    conn,
                    args.slug,
                    args.profile,
                    args.load_nix,
                    None, None,
                    getattr(args, 'environment', 'default'),
                    False,
                    True,
                    False
                )
                sys.stdout = old_stdout
                expected_content = buffer.getvalue()
            finally:
                conn.close()

            # Compare (ignoring whitespace differences)
            if current_content.strip() == expected_content.strip():
                print("✓ .envrc is valid and up-to-date")
                return 0
            else:
                print("⚠️  .envrc differs from TempleDB state")
                print("   Run 'templedb direnv diff' to see changes")
                print("   Run 'templedb direnv --write' to update")
                return 1

        except Exception as e:
            logger.error(f"verify failed: {e}", exc_info=True)
            return 1

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


def register(cli):
    """Register direnv command with CLI"""
    cmd = DirenvCommand()

    # Create direnv command group
    direnv_parser = cli.register_command('direnv', None, help_text='Direnv integration and .envrc management')
    subparsers = direnv_parser.add_subparsers(dest='direnv_subcommand')

    # Generate subcommand (default behavior)
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
    cli.commands['direnv.generate'] = cmd.generate
    cli.commands['direnv.gen'] = cmd.generate

    # Diff subcommand
    diff_parser = subparsers.add_parser('diff', help='Show diff between current .envrc and TempleDB state')
    diff_parser.add_argument('slug', nargs='?', help='Project slug (auto-detected)')
    diff_parser.add_argument('--profile', default='default', help='Secret profile')
    diff_parser.add_argument('--environment', '--env', default='default', help='Environment name')
    diff_parser.add_argument('--no-nix', dest='load_nix', action='store_false', default=True)
    cli.commands['direnv.diff'] = cmd.diff

    # Verify subcommand
    verify_parser = subparsers.add_parser('verify', help='Verify .envrc matches TempleDB state')
    verify_parser.add_argument('slug', nargs='?', help='Project slug (auto-detected)')
    verify_parser.add_argument('--profile', default='default', help='Secret profile')
    verify_parser.add_argument('--environment', '--env', default='default', help='Environment name')
    verify_parser.add_argument('--no-nix', dest='load_nix', action='store_false', default=True)
    cli.commands['direnv.verify'] = cmd.verify
