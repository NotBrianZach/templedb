#!/usr/bin/env python3
"""Emacs layer dev-mode helpers.

Phase 0 escape hatch for iterating on the Emacs layer without a NixOS
rebuild. Home-manager owns the top-level symlink at
`~/.emacs.d/private/local-layers/templedb`, so a filesystem symlink swap
is fragile. Instead we do the load-path override *inside* Emacs via
`M-x templedb-agent-reload-from-checkout' — same effect from the user's
perspective (edit the checkout, see changes live), no fight with
home-manager. This CLI is a convenience wrapper so you can trigger the
reload from a shell instead of switching to Emacs.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class EmacsCommands(Command):
    """Emacs layer dev-mode commands."""

    def reload(self, args) -> int:
        """Trigger `M-x templedb-agent-reload-from-checkout` via emacsclient.

        Prerequisites: an Emacs server running (`M-x server-start` or
        Emacs launched as a daemon). If neither is running, we print
        the M-x command so the user can run it manually.

        Return code:
          0 — reload triggered successfully
          1 — emacsclient failed (usually: no server running)
          2 — checkout file doesn't exist
        """
        checkout_path = Path.home() / ".config" / "templedb" / "checkouts" / \
            "templedb" / "integrations" / "emacs" / "templedb-agent.el"

        if not checkout_path.exists():
            print(f"❌ Checkout not found at: {checkout_path}")
            print()
            print("Run this first to materialize the writable checkout:")
            print("  templedb project checkout templedb "
                  "~/.config/templedb/checkouts/templedb --writable --force")
            return 2

        # Try emacsclient. Non-blocking (-n) so we don't wait for output;
        # the reload is fire-and-forget.
        try:
            result = subprocess.run(
                ["emacsclient", "-e", "(templedb-agent-reload-from-checkout)"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                # emacsclient returns the elisp result as a string.
                # Success = a non-error string (usually the "reloaded" message).
                out = result.stdout.strip()
                print(f"✓ Reload triggered")
                if out:
                    # Elisp returns strings quoted; strip surrounding quotes.
                    print(f"  {out.strip(chr(34))}")
                return 0
            # emacsclient exited non-zero: usually "no server running"
            stderr = result.stderr.strip()
            print(f"⚠ emacsclient failed: {stderr or '(no output)'}")
            print()
            self._print_manual_instructions(checkout_path)
            return 1
        except FileNotFoundError:
            print("⚠ emacsclient not on PATH")
            print()
            self._print_manual_instructions(checkout_path)
            return 1
        except subprocess.TimeoutExpired:
            print("⚠ emacsclient timed out after 5s")
            print()
            self._print_manual_instructions(checkout_path)
            return 1

    def _print_manual_instructions(self, checkout_path: Path):
        """Fallback: tell the user what to run manually inside Emacs."""
        print("To reload manually, run this inside Emacs:")
        print(f"  M-x templedb-agent-reload-from-checkout")
        print(f"  (or press C-c C-l inside a Temple Agent buffer)")
        print()
        print(f"Checkout path: {checkout_path}")
        print()
        print("To enable emacsclient for future use, either:")
        print("  1. Start the daemon: 'emacs --daemon' or add to .spacemacs:")
        print("     (server-start)")
        print("  2. Add (server-start) to dotspacemacs-user-config in .spacemacs")
