#!/usr/bin/env python3
"""
TUI launcher command
"""
import sys
import subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command


class TUICommands(Command):
    """TUI command handlers"""

    def launch_tui(self, args) -> int:
        """Launch the TempleDB TUI"""
        # Check if textual is installed
        try:
            import textual
        except ImportError:
            print("Error: textual is not installed", file=sys.stderr)
            print("", file=sys.stderr)
            print("Install with:", file=sys.stderr)
            print("  pip install textual", file=sys.stderr)
            print("", file=sys.stderr)
            print("Or with Nix:", file=sys.stderr)
            print("  nix-shell -p python3Packages.textual", file=sys.stderr)
            return 1

        # Launch TUI
        tui_path = Path(__file__).parent.parent.parent / "tui.py"
        try:
            result = subprocess.run([sys.executable, str(tui_path)], check=False)
            return result.returncode
        except KeyboardInterrupt:
            return 0
        except Exception as e:
            print(f"Error launching TUI: {e}", file=sys.stderr)
            return 1


def register(cli):
    """Register TUI commands"""
    cmd = TUICommands()

    tui_parser = cli.register_command('tui', cmd.launch_tui, help_text='Launch interactive terminal UI')
