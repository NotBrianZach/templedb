"""TempleDB GUI — Fleet Sync pages."""
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


@router.get("/fleet-sync", response_class=HTMLResponse)
def fleet_sync_page():
    """Fleet Sync Dashboard — visualize DB sync state across machines."""
    hosts = _fleet_sync_get_hosts()
    sync_projects = ["system_config", "templedb"]

    # Local commit reference
    local_heads = {}
    for slug in sync_projects:
        head = query_one("""
            SELECT c.commit_hash, c.commit_message, c.commit_timestamp
            FROM vcs_commits c
            JOIN vcs_branches b ON c.id = b.head_commit_id
            JOIN projects p ON b.project_id = p.id
            WHERE p.slug = ? AND b.branch_name = 'main'
        """, (slug,))
        if head:
            local_heads[slug] = head

    ref_rows = []
    for slug in sync_projects:
        head = local_heads.get(slug)
        if head:
            ref_rows.append([
                f'<strong>{html.escape(slug)}</strong>',
                f'<code>{html.escape(head["commit_hash"][:12])}</code>',
                html.escape((head["commit_message"] or "")[:60]),
                f'<span class="muted">{html.escape((head["commit_timestamp"] or "")[:19])}</span>',
            ])

    ref_table = _table(["Project", "Latest Commit", "Message", "Date"], ref_rows,
                       "No projects with commits", "fleet-sync-refs")

    # Machine rows with probe/sync buttons
    machine_rows = []
    for h in hosts:
        name = html.escape(h["name"])
        ip = html.escape(h["host"] or "—")
        probe_btn = (
            f'<button hx-post="/fleet-sync/probe/{h["name"]}" '
            f'hx-target="#probe-{h["name"]}" hx-swap="innerHTML" '
            f'style="background:#1a1a3a;border:1px solid #2a2a4a;color:#d0d0e8;'
            f'padding:2px 8px;border-radius:3px;cursor:pointer;font-family:monospace;font-size:0.78rem">'
            f'Probe</button>')
        is_local = h["host"] == "localhost"
        sync_btn = ('<span class="muted">local</span>' if is_local else
            f'<button hx-post="/fleet-sync/push/{h["name"]}" '
            f'hx-target="#sync-{h["name"]}" hx-swap="innerHTML" '
            f'hx-confirm="Push DB to {h["name"]}?" '
            f'style="background:#1a3a1a;border:1px solid #2a4a2a;color:#8f8;'
            f'padding:2px 8px;border-radius:3px;cursor:pointer;font-family:monospace;font-size:0.78rem">'
            f'Sync DB</button>')
        machine_rows.append([
            f'<strong>{name}</strong>', ip,
            f'{probe_btn} {sync_btn}',
            f'<span id="probe-{h["name"]}" class="muted">click Probe</span>',
            f'<span id="sync-{h["name"]}"></span>',
        ])

    machine_table = _table(
        ["Machine", "IP", "Actions", "Status", "Sync Result"],
        machine_rows, "No hosts found in system_config flake.nix", "fleet-sync-machines")

    probe_all = (
        '<button hx-post="/fleet-sync/probe-all" '
        'hx-target="#probe-all-results" hx-swap="innerHTML" '
        'style="background:#1a1a3a;border:1px solid #3a3a5a;color:#d0d0e8;'
        'padding:4px 12px;border-radius:4px;cursor:pointer;font-family:monospace;'
        'font-size:0.85rem;margin-bottom:1rem">Probe All Machines</button>')

    body = f"""
<h2>Fleet Sync Dashboard</h2>
<p class="muted" style="margin-bottom:1rem">
  Compare TempleDB database state across machines. Probe checks latest commits via SSH.
  Sync pushes the local DB (with WAL checkpoint) to remote machines.
</p>
<h3>This Machine (Local Reference)</h3>
{ref_table}
<h3 style="margin-top:2rem">Machines</h3>
{probe_all}
<div id="probe-all-results"></div>
{_search_bar("fleet-sync-machines", "Filter machines...")}
{machine_table}
"""
    return _base("Fleet Sync", body, "fleet-sync")


@router.post("/fleet-sync/probe/{machine_name}", response_class=HTMLResponse)
def fleet_sync_probe(machine_name: str):
    """Probe a single machine's sync state."""
    hosts = _fleet_sync_get_hosts()
    host_info = next((h for h in hosts if h["name"] == machine_name), None)
    if not host_info:
        return HTMLResponse('<span style="color:#e94560">Unknown machine</span>')
    result = _fleet_sync_probe(host_info, ["system_config", "templedb"])
    return HTMLResponse(_fleet_sync_format_probe(result, ["system_config", "templedb"]))


@router.post("/fleet-sync/probe-all", response_class=HTMLResponse)
def fleet_sync_probe_all():
    """Probe all machines in parallel."""
    import concurrent.futures
    hosts = _fleet_sync_get_hosts()
    sync_projects = ["system_config", "templedb"]

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fleet_sync_probe, h, sync_projects): h["name"] for h in hosts}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as e:
                results[name] = {"name": name, "error": str(e), "ssh": False, "projects": {}}

    # OOB swaps to update each machine's probe span
    oob = []
    summary_parts = []
    for h in hosts:
        r = results.get(h["name"], {})
        probe_html = _fleet_sync_format_probe(r, sync_projects)
        oob.append(f'<span id="probe-{html.escape(h["name"])}" hx-swap-oob="innerHTML">{probe_html}</span>')
        if r.get("error"):
            summary_parts.append(f'<strong>{html.escape(h["name"])}</strong>: <span style="color:#e94560">{html.escape(r["error"])}</span>')
        elif r.get("ssh"):
            summary_parts.append(f'<strong>{html.escape(h["name"])}</strong>: <span style="color:#4a9a6a">OK</span>')
        else:
            summary_parts.append(f'<strong>{html.escape(h["name"])}</strong>: <span class="muted">?</span>')

    return HTMLResponse(
        f'<p>{"&nbsp; | &nbsp;".join(summary_parts)}</p>' + "".join(oob))


@router.post("/fleet-sync/push/{machine_name}", response_class=HTMLResponse)
def fleet_sync_push(machine_name: str):
    """Checkpoint WAL and SCP the DB to a remote machine."""
    import sqlite3 as _sqlite3
    hosts = _fleet_sync_get_hosts()
    host_info = next((h for h in hosts if h["name"] == machine_name), None)
    if not host_info or not host_info["host"]:
        return HTMLResponse(_msg("Unknown machine or no IP", ok=False))
    if host_info["host"] == "localhost":
        return HTMLResponse(_msg("Cannot push to localhost", ok=False))

    user = host_info.get("user", "zach")
    host = host_info["host"]
    db_path = Path.home() / ".local" / "share" / "templedb" / "templedb.sqlite"

    try:
        conn = _sqlite3.connect(str(db_path))
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()

        r = subprocess.run(
            ["scp", "-o", "ConnectTimeout=10", str(db_path), f"{user}@{host}:~/.local/share/templedb/templedb.sqlite"],
            capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return HTMLResponse(_msg(f"SCP failed: {r.stderr.strip()}", ok=False))
        return HTMLResponse(_msg(f"DB synced to {machine_name}", ok=True))

    except subprocess.TimeoutExpired:
        return HTMLResponse(_msg("SCP timed out", ok=False))
    except Exception as e:
        return HTMLResponse(_msg(f"Error: {e}", ok=False))


# ── Tests Dashboard ──────────────────────────────────────────────────────────


# ── Split page modules ──
from gui_pages.tests import router as tests_router
app.include_router(tests_router)

