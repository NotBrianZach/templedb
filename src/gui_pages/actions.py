"""TempleDB GUI — Actions pages."""
import html
import json
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse

from db_utils import execute, query_all, query_one
from gui_helpers import _base, _table, _search_bar, _file_link, _msg, _status_badge, CSS

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


@router.post("/mount/toggle", response_class=HTMLResponse)
def mount_toggle():
    # Check if mounted
    try:
        with open("/proc/mounts") as f:
            mounted = any("fuse" in l.lower() and "temple" in l.lower() for l in f)
    except Exception:
        mounted = False

    if mounted:
        rc, out, err = _run("unmount")
        return HTMLResponse(_msg("Unmounted" if rc == 0 else err, ok=rc == 0))
    else:
        # Mount in background (FUSE blocks)
        import subprocess, threading
        def _bg_mount():
            subprocess.run(
                [TEMPLEDB, "mount", str(Path.home() / "temple"), "--foreground"],
                capture_output=True
            )
        t = threading.Thread(target=_bg_mount, daemon=True)
        t.start()
        import time; time.sleep(1)
        return HTMLResponse(_msg("Mounting at {FUSE_MOUNT_PATH}...", ok=True))



