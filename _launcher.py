#!/usr/bin/env python3
"""TempleDB launcher — bundled inside the nix package's site-packages.

Invoked by bin/templedb (see flake.nix). Purpose: when TEMPLEDB_DEV_MODE=1
and a materialized checkout exists at
~/.config/templedb/checkouts/templedb/src, prepend that path to sys.path
so `cli` itself and all submodules resolve from the checkout — no per-user
PYTHONPATH setup required.

When TEMPLEDB_DEV_MODE is unset (default), this file behaves identically
to `python -m cli`: reproducibility is unchanged for anyone who isn't
actively editing templedb.

Design: reports/2026-08-16-nix-profile-staleness-design.html (phase 2).
"""
import os
import sys
from pathlib import Path


def _apply_dev_mode() -> None:
    if not os.environ.get("TEMPLEDB_DEV_MODE"):
        return
    checkout = Path.home() / ".config" / "templedb" / "checkouts" / "templedb" / "src"
    if checkout.exists() and (checkout / "cli").exists():
        checkout_str = str(checkout)
        if checkout_str not in sys.path:
            sys.path.insert(0, checkout_str)
    # If dev mode was requested but no checkout exists, cli/__init__.py's
    # module-load-time check will print the warning. Don't duplicate here.


_apply_dev_mode()

from cli import main  # noqa: E402  — imports must follow sys.path setup

if __name__ == "__main__":
    main()
