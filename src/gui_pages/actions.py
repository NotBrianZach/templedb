"""TempleDB GUI — Actions pages."""
import html
import json
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse

from db_utils import execute, query_all, query_one
from gui_helpers import (
    _base, _table, _search_bar, _file_link, _msg, _status_badge, _run, CSS,
    TEMPLEDB,
)

router = APIRouter()

@router.post("/backup/local", response_class=HTMLResponse)
def backup_local():
    rc, out, err = _run("storage", "backup", "local")
    return HTMLResponse(_msg(out or err or "Done", ok=rc == 0))



@router.post("/backup/gcs", response_class=HTMLResponse)
def backup_gcs():
    rc, out, err = _run("storage", "backup", "gcs")
    return HTMLResponse(_msg(out or err or "Done", ok=rc == 0))



@router.post("/db/migrate", response_class=HTMLResponse)
def db_migrate():
    rc, out, err = _run("db", "migrate")
    return HTMLResponse(_msg(out or err or "Done", ok=rc == 0))


# ── woofs offline sync (manual only) ─────────────────────────────────────────
#
# Both directions are deliberately button-driven. The 10-minute
# woofs-snapshot-sync.timer that used to push automatically is off; see
# services.woofs-snapshot-sync.autoSync in system_config.
#
# These run the project's own node scripts rather than going through
# systemd, for two reasons: starting a system unit from the GUI would need
# root or a polkit rule, and the unit's projectDir points at
# ~/.local/share/templedb/fhs-deployments/woofs_projects/working, which is
# only refreshed by a deploy and does not yet carry pullClientNotes.mjs.
# The canonical checkout is kept current by `templedb publish`.
WOOFS_CHECKOUT = Path.home() / ".config" / "templedb" / "checkouts" / "woofs_projects"


def _woofs_sync(script: str, *extra: str) -> tuple[int, str, str]:
    """Run a woofs sync script with the project's env loaded from TempleDB.

    The env is sourced in-process via `var export --secrets`, so DATABASE_URL
    never appears in this process's argv — the same reason var set grew
    --value-stdin. Only the script's own stdout is surfaced; it prints
    counts, not values.
    """
    path = WOOFS_CHECKOUT / "src" / "scripts" / script
    if not path.exists():
        return 1, "", (
            f"{script} not found at {path}. Run "
            "`templedb publish run woofs_projects` to materialise it."
        )
    # </dev/null on the export, and DEVNULL for the whole pipeline, are both
    # load-bearing: `var export --secrets` writes "Decrypt using <file>?
    # [Y/n]" to stderr and READS STDIN, treating an empty read as yes. Given
    # a stdin that stays open it blocks forever — a direct run of this exact
    # command without the redirect hung until it was killed at 5 minutes,
    # where the redirected version finishes in 5 seconds. It appeared to work
    # under uvicorn only because that stdin happened to hit EOF. Same trap the
    # woofs-snapshot-sync envRenderer has to dodge.
    cmd = (
        'set -a; eval "$(' + TEMPLEDB + " var export woofs_projects "
        '--target staging --format shell --secrets </dev/null 2>/dev/null)"; set +a; '
        "exec node " + str(path) + (" " + " ".join(extra) if extra else "")
    )
    r = subprocess.run(
        ["bash", "-c", cmd],
        cwd=str(WOOFS_CHECKOUT),
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=600,
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def _sync_response(rc: int, out: str, err: str) -> HTMLResponse:
    """Render both streams, never one or the other.

    These scripts log progress to stdout and die to stderr, so `out or err`
    shows a run that got four lines in and then failed as if it had
    succeeded — which is exactly how a malformed schedules/2026.json looked
    like a clean push. stderr is shown whenever it is non-empty, and a
    non-zero exit is stated outright rather than left to the badge colour.
    """
    parts = []
    if out:
        parts.append(html.escape(out))
    if err:
        parts.append(("--- stderr ---\n" if out else "") + html.escape(err))
    if rc != 0:
        parts.append(f"--- exited {rc} ---")
    body = "\n".join(parts) or "Done"
    return HTMLResponse(_msg(f"<pre>{body}</pre>", ok=rc == 0))


@router.post("/woofs/sync/push", response_class=HTMLResponse)
def woofs_sync_push():
    """local clientNotes.json + schedules -> Supabase."""
    return _sync_response(*_woofs_sync("syncClientNotes.mjs"))


@router.post("/woofs/sync/pull/preview", response_class=HTMLResponse)
def woofs_sync_pull_preview():
    """Supabase -> clientNotes.json, reporting only. Writes nothing."""
    return _sync_response(*_woofs_sync("pullClientNotes.mjs"))


@router.post("/woofs/sync/pull/apply", response_class=HTMLResponse)
def woofs_sync_pull_apply():
    """Supabase -> clientNotes.json for real. Gap-fill only; takes a .bak."""
    return _sync_response(*_woofs_sync("pullClientNotes.mjs", "--write"))


# ── CRUD: system_config ───────────────────────────────────────────────────────


@router.post("/config/set", response_class=HTMLResponse)
def config_set(key: str = Form(...), value: str = Form(...), hostname: str = Form("")):
    """Set a system_config key (hostname-aware)."""
    import socket
    from db_utils import execute, query_all
    host = hostname or ""
    # Auto-detect host from key pattern: nixos.host.<hostname> or <hostname>.* prefix
    if not host:
        if key.startswith("nixos.host."):
            host = key.split(".")[2]
        else:
            # Check known hosts from existing nixos.host.* entries
            known = {r["key"].split(".")[2] for r in query_all(
                "SELECT key FROM system_config WHERE key LIKE 'nixos.host.%'"
            )}
            for h in known:
                if key.startswith(h + "."):
                    host = h
                    break
    if not host:
        host = socket.gethostname()
    execute(
        "INSERT OR REPLACE INTO system_config (key, value, hostname, updated_at) "
        "VALUES (?, ?, ?, datetime('now'))", (key, value, host)
    )
    return HTMLResponse(_msg(f"Set {key} ({host})", ok=True))



@router.post("/config/delete", response_class=HTMLResponse)
def config_delete(key: str = Form(...)):
    """Delete a system_config key."""
    from db_utils import execute
    execute("DELETE FROM system_config WHERE key = ?", (key,))
    return HTMLResponse(_msg(f"Deleted {key}", ok=True))


# ── CRUD: environment variables ──────────────────────────────────────────────


@router.post("/dotfiles/add", response_class=HTMLResponse)
def dotfiles_add(project: str = Form(...), source: str = Form(...), target: str = Form(...)):
    """Add a dotfile mapping."""
    rc, out, err = _run("nixos", "dotfiles-add", project, source, target)
    return HTMLResponse(_msg(out or err or f"Added {source}", ok=rc == 0))



@router.post("/dotfiles/remove", response_class=HTMLResponse)
def dotfiles_remove(project: str = Form(...), source: str = Form(...)):
    """Remove a dotfile mapping."""
    rc, out, err = _run("nixos", "dotfiles-remove", project, source)
    return HTMLResponse(_msg(out or err or f"Removed {source}", ok=rc == 0))


# ── CRUD: project settings ──────────────────────────────────────────────────
