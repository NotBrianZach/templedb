"""TempleDB GUI — Systemd pages."""
import html
import json
import os
import re
import subprocess
import sys
import time
import sqlite3 as _sqlite3
from pathlib import Path

from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse

sys.path.insert(0, str(Path(__file__).parent.parent))

router = APIRouter()

from gui_helpers import _base, _msg, _run, _search_bar, _status_badge, _table
_base = _base
_table = _table
_search_bar = _search_bar
_msg = _msg
_status_badge = _status_badge
_run = _run


@router.get("/systemd", response_class=HTMLResponse)
def systemd_page(scope: str = "user", filter: str = "", show: str = "all"):
    """Systemd unit monitor — view all units, their status, and logs."""
    is_user = scope == "user"
    units = _systemd_list_units(user=is_user)

    # Filter by state
    if show == "active":
        units = [u for u in units if u["active"] == "active"]
    elif show == "failed":
        units = [u for u in units if u["active"] == "failed"]
    elif show == "inactive":
        units = [u for u in units if u["active"] == "inactive"]

    # Filter by search term
    if filter:
        q = filter.lower()
        units = [u for u in units if q in u["unit"].lower() or q in u.get("description", "").lower()]

    # Scope tabs
    scope_tabs = "".join(
        f'<a href="/systemd?scope={s}&show={html.escape(show)}" class="tab{"  active" if scope == s else ""}">{s.title()}</a>'
        for s in ["user", "system"]
    )

    # State filter tabs
    state_tabs = "".join(
        f'<a href="/systemd?scope={html.escape(scope)}&show={s}" class="tab{" active" if show == s else ""}">{s.title()}</a>'
        for s in ["all", "active", "failed", "inactive"]
    )

    rows = []
    for u in units:
        unit_name = u["unit"]
        state_cell = _systemd_state_cell(u["active"], u["sub"])
        desc = html.escape(u.get("description", ""))
        detail_link = f'<a href="/systemd/{html.escape(unit_name)}?scope={html.escape(scope)}">{html.escape(unit_name)}</a>'
        actions = ""
        if u["active"] == "active":
            actions = (
                f'<button hx-post="/systemd/{html.escape(unit_name)}/restart?scope={html.escape(scope)}" '
                f'hx-swap="outerHTML" style="font-size:0.72rem;padding:0.15rem 0.4rem">restart</button>'
            )
        elif u["active"] in ("inactive", "failed"):
            actions = (
                f'<button hx-post="/systemd/{html.escape(unit_name)}/start?scope={html.escape(scope)}" '
                f'hx-swap="outerHTML" style="font-size:0.72rem;padding:0.15rem 0.4rem">start</button>'
            )
        rows.append([detail_link, f'<span class="muted">{u["load"]}</span>', state_cell,
                     f'<span class="muted" style="font-size:0.78rem">{desc}</span>', actions])

    search = _search_bar("systemd-table", placeholder="Filter units…")
    table = _table(["Unit", "Load", "State", "Description", ""], rows, table_id="systemd-table")

    summary_active = sum(1 for u in units if u["active"] == "active")
    summary_failed = sum(1 for u in units if u["active"] == "failed")
    summary_badge = f'<span class="badge green">{summary_active} active</span>'
    if summary_failed:
        summary_badge += f' <span class="badge red">{summary_failed} failed</span>'

    body = f"""
<h2>Systemd Monitor</h2>
<div class="tabs">{scope_tabs}</div>
<div style="display:flex;gap:1rem;align-items:center;margin-bottom:1rem;flex-wrap:wrap">
  <div class="tabs" style="margin-bottom:0;border-bottom:none">{state_tabs}</div>
  {summary_badge}
  <span class="muted" style="font-size:0.8rem">{len(units)} units</span>
</div>
{search}
{table}
"""
    return _base("Systemd", body, "systemd")


@router.get("/systemd/{unit_name}", response_class=HTMLResponse)
def systemd_unit_detail(unit_name: str, scope: str = "user", log_lines: int = 50):
    """Detail view for a single systemd unit with properties and logs."""
    is_user = scope == "user"
    props = _systemd_unit_props(unit_name, user=is_user)
    logs = _systemd_logs(unit_name, user=is_user, lines=log_lines)

    active = props.get("ActiveState", "unknown")
    sub = props.get("SubState", "unknown")
    state_cell = _systemd_state_cell(active, sub)

    pid = props.get("MainPID", "0")
    pid_cell = pid if pid != "0" else "-"
    mem = props.get("MemoryCurrent", "")
    if mem and mem not in ("[not set]", ""):
        try:
            mem_cell = f"{int(mem) / 1024 / 1024:.1f} MB"
        except Exception:
            mem_cell = "-"
    else:
        mem_cell = "-"
    restarts = props.get("NRestarts", "0")
    started = props.get("ActiveEnterTimestamp", "-")
    stopped = props.get("InactiveEnterTimestamp", "-")
    fragment = props.get("FragmentPath", "-")
    desc = props.get("Description", unit_name)

    # Action buttons
    actions = '<div style="display:flex;gap:0.5rem;margin:1rem 0">'
    if active == "active":
        actions += (
            f'<button hx-post="/systemd/{html.escape(unit_name)}/restart?scope={html.escape(scope)}" '
            f'hx-swap="innerHTML" hx-target="#action-result" class="btn">Restart</button>'
            f'<button hx-post="/systemd/{html.escape(unit_name)}/stop?scope={html.escape(scope)}" '
            f'hx-swap="innerHTML" hx-target="#action-result" class="btn">Stop</button>'
        )
    else:
        actions += (
            f'<button hx-post="/systemd/{html.escape(unit_name)}/start?scope={html.escape(scope)}" '
            f'hx-swap="innerHTML" hx-target="#action-result" class="btn primary">Start</button>'
        )
    actions += '</div><div id="action-result"></div>'

    # Log line selector
    log_opts = "".join(
        f'<a href="/systemd/{html.escape(unit_name)}?scope={html.escape(scope)}&log_lines={n}" '
        f'class="tab{" active" if log_lines == n else ""}">{n}</a>'
        for n in [20, 50, 100, 200]
    )

    escaped_logs = html.escape(logs)

    body = f"""
<h2><a href="/systemd?scope={html.escape(scope)}" style="color:#808098">Systemd</a> / {html.escape(unit_name)}</h2>
<p style="margin-bottom:0.5rem">{html.escape(desc)}</p>

<table style="width:auto;margin-bottom:0.5rem">
<tr><td style="width:120px;color:#808098">State</td><td>{state_cell}</td></tr>
<tr><td style="color:#808098">PID</td><td><code>{html.escape(pid_cell)}</code></td></tr>
<tr><td style="color:#808098">Memory</td><td>{mem_cell}</td></tr>
<tr><td style="color:#808098">Restarts</td><td>{restarts}</td></tr>
<tr><td style="color:#808098">Started</td><td><span class="muted">{html.escape(started)}</span></td></tr>
<tr><td style="color:#808098">Stopped</td><td><span class="muted">{html.escape(stopped)}</span></td></tr>
<tr><td style="color:#808098">Unit file</td><td><code class="muted" style="font-size:0.78rem">{html.escape(fragment)}</code></td></tr>
</table>

{actions}

<h3 style="margin-top:1.5rem">Journal Logs</h3>
<div class="tabs" style="margin-bottom:0.5rem">{log_opts}</div>
<pre style="max-height:500px;overflow:auto;font-size:0.78rem">{escaped_logs}</pre>
"""
    return _base(unit_name, body, "systemd")


@router.post("/systemd/{unit_name}/start", response_class=HTMLResponse)
def systemd_start(unit_name: str, scope: str = "user"):
    cmd = ["systemctl", "start", unit_name]
    if scope == "user":
        cmd.insert(1, "--user")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if r.returncode == 0:
        return HTMLResponse(_msg(f"Started {unit_name}", ok=True))
    return HTMLResponse(_msg(f"Failed: {r.stderr.strip()}", ok=False))


@router.post("/systemd/{unit_name}/stop", response_class=HTMLResponse)
def systemd_stop(unit_name: str, scope: str = "user"):
    cmd = ["systemctl", "stop", unit_name]
    if scope == "user":
        cmd.insert(1, "--user")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if r.returncode == 0:
        return HTMLResponse(_msg(f"Stopped {unit_name}", ok=True))
    return HTMLResponse(_msg(f"Failed: {r.stderr.strip()}", ok=False))


@router.post("/systemd/{unit_name}/restart", response_class=HTMLResponse)
def systemd_restart(unit_name: str, scope: str = "user"):
    cmd = ["systemctl", "restart", unit_name]
    if scope == "user":
        cmd.insert(1, "--user")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if r.returncode == 0:
        return HTMLResponse(_msg(f"Restarted {unit_name}", ok=True))
    return HTMLResponse(_msg(f"Failed: {r.stderr.strip()}", ok=False))


# ── Fleet Sync Dashboard ─────────────────────────────────────────────────────










# ── Helpers (moved from gui_pages/settings.py in a2763ce5+1) ──

def _systemd_list_units(user: bool = False) -> list[dict]:
    """List systemd units with their status."""
    cmd = ["systemctl", "list-units", "--all", "--no-pager", "--no-legend", "--plain"]
    if user:
        cmd.insert(1, "--user")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        units = []
        for line in r.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = line.split(None, 4)
            if len(parts) >= 4:
                units.append({
                    "unit": parts[0],
                    "load": parts[1],
                    "active": parts[2],
                    "sub": parts[3],
                    "description": parts[4] if len(parts) > 4 else "",
                })
        return units
    except Exception:
        return []

def _systemd_unit_props(unit: str, user: bool = False) -> dict:
    """Get properties for a single unit."""
    cmd = ["systemctl", "show", unit,
           "--property=ActiveState,SubState,MainPID,MemoryCurrent,ActiveEnterTimestamp,"
           "InactiveEnterTimestamp,NRestarts,ExecMainStartTimestamp,FragmentPath,Description"]
    if user:
        cmd.insert(1, "--user")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        props = {}
        for line in r.stdout.strip().split("\n"):
            if "=" in line:
                k, v = line.split("=", 1)
                props[k] = v
        return props
    except Exception:
        return {}

def _systemd_logs(unit: str, user: bool = False, lines: int = 50) -> str:
    """Get recent journal logs for a unit."""
    cmd = ["journalctl", "-u", unit, "--no-pager", f"-n{lines}", "--output=short-iso"]
    if user:
        cmd.insert(1, "--user")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except Exception as e:
        return f"Error fetching logs: {e}"

def _systemd_state_cell(active: str, sub: str) -> str:
    """Render colored state badge."""
    if active == "active":
        color = "#4a9a6a"
    elif active == "failed":
        color = "#e94560"
    elif active == "activating" or active == "reloading":
        color = "#e9a045"
    else:
        color = "#808098"
    return f'<span style="color:{color}">{html.escape(active)}</span> <span class="muted">({html.escape(sub)})</span>'

