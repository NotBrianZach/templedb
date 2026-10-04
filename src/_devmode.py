#!/usr/bin/env python3
"""Single source of truth for TEMPLEDB_DEV_MODE tree resolution.

Lives at src/_devmode.py so it is importable from both layouts: the nix
install flattens src/ into site-packages (`cp -r src/. "$SITE/"`) next to
_launcher.py, and a dev tree has <tree>/src on sys.path. That matters
because this runs *before* the templedb packages are importable, so it
must not import anything from them.

This logic previously existed in three places — _launcher.py,
cli/__init__.py, and (in spirit) CheckoutRepository.resolve. Two had
already drifted: _launcher.py ordered purely by recency while
cli/__init__.py had learned to prefer `kind='edit'`, so the launcher
chose a different tree than the package thought it had chosen. Since the
launcher runs first and wins, the package's copy was dead code. The
duplication was documented as "a correctness coupling, not a style
problem"; this module is that coupling made literal.
"""
import os
import sys
from pathlib import Path
from typing import List, Optional

__all__ = ["resolve_dev_checkout", "DEFAULT_CHECKOUT"]

# Resolution is cached for the life of the process. _launcher.py resolves
# first to set up sys.path, then cli/__init__.py asks again for the same
# answer; without this they would each open the DB, stat a few hundred
# paths, and print the same skip warnings twice. A sentinel rather than
# None because None is a meaningful result ("no usable tree").
_UNRESOLVED = object()
_cached = _UNRESOLVED

DEFAULT_CHECKOUT = Path.home() / ".config" / "templedb" / "checkouts" / "templedb" / "src"


def _db_path() -> str:
    return os.environ.get("TEMPLEDB_PATH") or str(
        Path.home() / ".local" / "share" / "templedb" / "templedb.sqlite")


def _env_session() -> Optional[str]:
    """This process's declared session NAME, or None.

    Only the name form is useful here: the message's job is to say "that
    tree belongs to someone else", and the owner we have from SQL is a
    name. Resolving TEMPLEDB_SESSION_ID to a name would mean a second
    query on a startup path, to sharpen a diagnostic that is already
    correct without it — an unpinned caller simply gets the neutral
    wording. Deliberately does not create or validate anything.
    """
    return os.environ.get("TEMPLEDB_SESSION", "").strip() or None


def resolve_dev_checkout(warn=True) -> Optional[Path]:
    """Return the src/ dir dev mode should run from, or None if there is none.

    Candidate order mirrors CheckoutRepository.resolve(PURPOSE_EDIT): an
    edit workspace first (dev mode exists to run the code you are
    editing), then the canonical tree. `kind` arrived in migration 113,
    so the ordering degrades to pure recency on a DB that predates it.

    A candidate is rejected if it is missing files the DB lists as active
    under src/. An edit workspace abandoned by another session keeps its
    `checkouts` row and still looks plausible — it has src/cli/ — but
    lacks whatever modules landed after it was last materialized, so
    choosing it fails at import. Observed 2026-09-29: the newest edit
    workspace belonged to a different session and had no
    cli/commands/claims.py, and TEMPLEDB_DEV_MODE=1 died with ImportError
    rather than falling back to a tree that worked.

    The check is existence-only. Hashing a few hundred files on every
    startup is too expensive for a path that runs before argument
    parsing; this catches the failure that actually breaks things (a new
    module absent entirely), while a tree holding stale *contents* of
    every file still passes and merely runs slightly old code.

    TEMPLEDB_DEV_SRC overrides everything, unchecked — if you point it
    somewhere deliberately, that is the answer.
    """
    global _cached
    if _cached is not _UNRESOLVED:
        return _cached

    override = os.environ.get("TEMPLEDB_DEV_SRC")
    if override:
        _cached = Path(override)
        return _cached

    _cached = _resolve_uncached(warn)
    return _cached


def _resolve_uncached(warn: bool) -> Optional[Path]:
    try:
        import sqlite3
        con = sqlite3.connect(f"file:{_db_path()}?mode=ro", uri=True)
        try:
            # kind/session come back so an accepted non-canonical tree
            # can name itself and its owner. Arity matches the legacy
            # query's padding below so the unpack is shape-stable.
            ordered = """SELECT c.checkout_path, c.kind, s.name
                            FROM checkouts c
                            JOIN projects p ON p.id = c.project_id
                       LEFT JOIN vcs_sessions s ON s.id = c.session_id
                           WHERE p.slug = 'templedb' AND c.is_active = 1
                           ORDER BY CASE c.kind WHEN 'edit' THEN 0
                                                WHEN 'canonical' THEN 1
                                                ELSE 2 END,
                                    c.checkout_at DESC"""
            legacy = """SELECT c.checkout_path, NULL AS kind, NULL AS name
                           FROM checkouts c
                          JOIN projects p ON p.id = c.project_id
                         WHERE p.slug = 'templedb' AND c.is_active = 1
                         ORDER BY c.checkout_at DESC"""
            try:
                rows = con.execute(ordered).fetchall()
            except sqlite3.OperationalError:
                rows = con.execute(legacy).fetchall()
            src_files: List[str] = [r[0] for r in con.execute(
                """SELECT pf.file_path FROM project_files pf
                     JOIN projects p ON p.id = pf.project_id
                    WHERE p.slug = 'templedb' AND pf.status = 'active'
                      AND pf.file_path LIKE 'src/%'""").fetchall()]
        finally:
            con.close()

        for (path, kind, owner) in rows:
            candidate = Path(path) / "src"
            if not (candidate / "cli").is_dir():
                continue
            base = candidate.parent      # paths are stored as 'src/...'
            gaps = [f for f in src_files if not (base / f).exists()]
            if gaps:
                if warn:
                    print(f"⚠  skipping dev tree {base} — behind DB by "
                          f"{len(gaps)} file(s) (e.g. {gaps[0]})",
                          file=sys.stderr)
                continue
            # Announce an accepted non-canonical tree. The check above is
            # existence-only by design (hashing every file before argparse
            # is too expensive), so a tree holding stale CONTENTS of a file
            # that exists passes silently and runs old code. On 2026-10-04
            # that cost an hour: dev mode served
            # edit-workspaces/templedb/claude-code-agent-3528, whose
            # project.py was 626 lines against the canonical 629 while its
            # checkout.py was current at 874, so a new parser flag kept
            # being rejected while the feature it sat next to worked. The
            # half-stale tree is the confusing case and nothing named it.
            # Saying which tree was chosen is cheap and turns a silent
            # wrong answer into a visible one.
            if warn and kind != 'canonical':
                whose = f"session '{owner}'" if owner else "no live session"
                mine = _env_session()
                if owner and mine and owner != mine:
                    whose += " — NOT yours"
                print(f"ℹ  dev mode: running {base} ({whose}), not the "
                      f"canonical tree. Only MISSING files are detected, so "
                      f"stale contents here run silently. Override with "
                      f"TEMPLEDB_DEV_SRC=<tree>/src.", file=sys.stderr)
            return candidate
        # Nothing usable. None disables dev mode, rather than silently
        # running whichever stale tree happened to sort first.
        return None
    except Exception:
        # Never let dev-mode resolution break startup.
        return DEFAULT_CHECKOUT if DEFAULT_CHECKOUT.exists() else None
