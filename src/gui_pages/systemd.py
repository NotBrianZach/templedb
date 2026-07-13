"""TempleDB GUI — Systemd pages."""
import html
import json
import os
import subprocess
import sys
import time
import sqlite3 as _sqlite3
from pathlib import Path

from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import execute, query_all, query_one

router = APIRouter()

import gui as _gui
_base = _gui._base
_table = _gui._table
_search_bar = _gui._search_bar
_msg = _gui._msg
_status_badge = _gui._status_badge
_run = _gui._run


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

def _fleet_sync_get_hosts() -> list[dict]:
    """Discover NixOS hosts from system_config flake.nix and known IPs."""
    hosts = []
    checkout = Path.home() / ".config" / "templedb" / "checkouts" / "system_config"
    flake = checkout / "flake.nix"
    if flake.exists():
        content = flake.read_text()
        for m in re.finditer(r'nixosConfigurations\.(\w+)\s*=', content):
            name = m.group(1)
            hosts.append({"name": name, "host": None, "user": "zach", "port": 22})

    # Resolve IPs from fleet_machines
    ip_map = {}
    try:
        machines = query_all("SELECT machine_name, target_host FROM fleet_machines")
        for m in machines:
            ip_map[m["machine_name"]] = m["target_host"]
    except Exception:
        pass

    # Known host fallbacks
    import socket
    hostname = socket.gethostname()
    known = {"zMothership2": "localhost" if hostname == "zMothership2" else "192.168.8.164",
             "zMothership3": "localhost" if hostname == "zMothership3" else "192.168.8.172"}
    for k, v in known.items():
        if k not in ip_map:
            ip_map[k] = v

    for h in hosts:
        h["host"] = ip_map.get(h["name"])
    return hosts


def _fleet_sync_probe(host_info: dict, projects: list[str]) -> dict:
    """SSH into a host and get its DB sync state."""
    import socket
    name = host_info["name"]
    host = host_info["host"]
    user = host_info.get("user", "zach")

    result = {"name": name, "host": host or "unknown", "ssh": False, "projects": {}, "error": None}

    if not host:
        result["error"] = "No IP configured"
        return result

    # Local machine
    if host == "localhost" or name == socket.gethostname():
        result["ssh"] = True
        for slug in projects:
            head = query_one("""
                SELECT c.commit_hash, c.commit_message, c.commit_timestamp
                FROM vcs_commits c
                JOIN vcs_branches b ON c.id = b.head_commit_id
                JOIN projects p ON b.project_id = p.id
                WHERE p.slug = ? AND b.branch_name = 'main'
            """, (slug,))
            if head:
                result["projects"][slug] = {
                    "hash": head["commit_hash"], "message": head["commit_message"], "date": head["commit_timestamp"]}
        return result

    # Remote machine
    try:
        ssh_base = ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no",
                     "-o", "BatchMode=yes", f"{user}@{host}"]

        r = subprocess.run(ssh_base + ["echo ok"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            result["error"] = "SSH failed"
            return result
        result["ssh"] = True

        for slug in projects:
            r = subprocess.run(
                ssh_base + [f"~/templeDB/templedb vcs log {slug} 2>/dev/null | head -5"],
                capture_output=True, text=True, timeout=15)
            if r.returncode == 0:
                for line in r.stdout.strip().split("\n"):
                    if line.startswith("commit "):
                        result["projects"][slug] = {"hash": line.split()[1], "message": "", "date": ""}
                        break

    except subprocess.TimeoutExpired:
        result["error"] = "SSH timeout"
    except Exception as e:
        result["error"] = str(e)
    return result


def _fleet_sync_format_probe(result: dict, sync_projects: list[str]) -> str:
    """Format probe result as HTML."""
    if result.get("error"):
        return f'<span style="color:#e94560">{html.escape(result["error"])}</span>'
    if not result.get("ssh"):
        return '<span class="muted">not probed</span>'

    parts = []
    for slug in sync_projects:
        local_head = query_one("""
            SELECT c.commit_hash FROM vcs_commits c
            JOIN vcs_branches b ON c.id = b.head_commit_id
            JOIN projects p ON b.project_id = p.id
            WHERE p.slug = ? AND b.branch_name = 'main'
        """, (slug,))
        remote = result.get("projects", {}).get(slug, {})
        remote_hash = remote.get("hash", "—")
        local_hash = local_head["commit_hash"] if local_head else "—"

        if remote_hash == "—":
            badge = '<span style="color:#606080">no data</span>'
        elif remote_hash == local_hash:
            badge = '<span style="color:#4a9a6a">&#x2713; in-sync</span>'
        else:
            badge = f'<span style="color:#e9a045">&#x26a0; stale ({html.escape(remote_hash[:8])})</span>'
        parts.append(f'{html.escape(slug)}: {badge}')

    return f'<span style="color:#4a9a6a">SSH &#x2713;</span> | {" | ".join(parts)}'


from gui_pages.fleet_sync import router as fleet_sync_router
app.include_router(fleet_sync_router)

