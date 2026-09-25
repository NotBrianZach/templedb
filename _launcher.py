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


def _resolve_dev_checkout() -> Path:
    """Locate the tree dev mode should run from.

    Kept in sync with cli/__init__.py::_resolve_dev_checkout — duplicated
    rather than imported because this file runs *before* the templedb
    packages are on sys.path, which is the whole reason it exists.

    The hardcoded checkouts/templedb/src is the read-only materialized
    copy, not the edit workspace you actually edit, so dev mode used to
    run different code than the one just changed.
    """
    override = os.environ.get("TEMPLEDB_DEV_SRC")
    if override:
        return Path(override)

    default = Path.home() / ".config" / "templedb" / "checkouts" / "templedb" / "src"
    db_path = os.environ.get("TEMPLEDB_PATH") or str(
        Path.home() / ".local" / "share" / "templedb" / "templedb.sqlite")
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            rows = con.execute(
                """SELECT c.checkout_path FROM checkouts c
                     JOIN projects p ON p.id = c.project_id
                    WHERE p.slug = 'templedb' AND c.is_active = 1
                    ORDER BY c.checkout_at DESC""").fetchall()
        finally:
            con.close()
        for (path,) in rows:
            candidate = Path(path) / "src"
            if (candidate / "cli").is_dir():
                return candidate
    except Exception:
        pass
    return default


def _apply_dev_mode() -> None:
    if not os.environ.get("TEMPLEDB_DEV_MODE"):
        return
    checkout = _resolve_dev_checkout()
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
