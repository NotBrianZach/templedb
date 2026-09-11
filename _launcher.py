#!/usr/bin/env python3
"""TempleDB launcher — bundled inside the nix package's site-packages.

Invoked by bin/templedb (see flake.nix). Decides whether to load
templedb source from the writable checkout at
~/.config/templedb/checkouts/templedb/src or from the frozen nix
package that ships this launcher.

Decision matrix (checked in order):

  1. TEMPLEDB_DEV_MODE explicitly set:
       truthy value  → prefer checkout
       falsy value   → force frozen nix
     (Explicit env always wins.)

  2. Long-running service invocation (`templedb gui`,
     `templedb ai mcp serve`, `templedb ai agent serve`) AND a
     checkout exists → prefer checkout.
     Rationale: these processes stay alive for hours/days. The
     frozen-nix default meant a `file set` on gui.py wouldn't reach
     the running GUI until the operator restarted it AND remembered
     TEMPLEDB_DEV_MODE=1. That "must remember" is where the bug
     lives.

  3. Otherwise (short-lived CLI) → frozen nix. Reproducibility is
     preserved for scripts, and A' preflight inside cli/__init__.py
     already handles per-invocation drift when dev-mode IS on.

If dev-mode was requested but no checkout exists, the warning is
handled by cli/__init__.py's module-load-time check (avoid duplicate
messages).

Design: reports/2026-08-16-nix-profile-staleness-design.html (phase 2)
plus the 2026-09-11 polarity flip for long-running services.
"""
import os
import sys
from pathlib import Path

_CHECKOUT = Path.home() / ".config" / "templedb" / "checkouts" / "templedb" / "src"

_LONG_RUNNING_MARKERS = [
    ("gui",),                   # templedb gui
    ("ai", "mcp", "serve"),     # templedb ai mcp serve
    ("ai", "agent", "serve"),   # templedb ai agent serve
]


def _is_long_running_service(argv):
    """Contiguous-subsequence match of argv[1:] against known markers.
    Positional-only match ignores flags like --port=8420."""
    args = [a for a in argv[1:] if not a.startswith("-")]
    for marker in _LONG_RUNNING_MARKERS:
        for i in range(len(args) - len(marker) + 1):
            if tuple(args[i:i + len(marker)]) == marker:
                return True
    return False


def _dev_mode_enabled():
    """Resolve effective dev-mode following the decision matrix above."""
    env = os.environ.get("TEMPLEDB_DEV_MODE")
    if env is not None:
        return env.lower() not in ("", "0", "false", "no", "off")
    if _is_long_running_service(sys.argv):
        return _CHECKOUT.exists() and (_CHECKOUT / "cli").exists()
    return False


def _apply_dev_mode() -> None:
    if not _dev_mode_enabled():
        return
    if _CHECKOUT.exists() and (_CHECKOUT / "cli").exists():
        checkout_str = str(_CHECKOUT)
        if checkout_str not in sys.path:
            sys.path.insert(0, checkout_str)
    # No warning here on missing checkout — cli/__init__.py handles it
    # so we don't emit twice.


_apply_dev_mode()

from cli import main  # noqa: E402  — imports must follow sys.path setup

if __name__ == "__main__":
    main()
