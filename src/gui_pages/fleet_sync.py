"""TempleDB GUI — Fleet Sync pages."""
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
from db_utils import execute, query_all, query_one

router = APIRouter()

from gui_helpers import _base, _msg, _run, _search_bar, _status_badge, _table
_base = _base
_table = _table
_search_bar = _search_bar
_msg = _msg
_status_badge = _status_badge
_run = _run


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
        push_btn = ('' if is_local else
            f'<button hx-post="/fleet-sync/push/{h["name"]}" '
            f'hx-target="#sync-{h["name"]}" hx-swap="innerHTML" '
            f'hx-confirm="Push DB to {h["name"]}?" '
            f'style="background:#1a3a1a;border:1px solid #2a4a2a;color:#8f8;'
            f'padding:2px 8px;border-radius:3px;cursor:pointer;font-family:monospace;font-size:0.78rem">'
            f'Push</button>')
        pull_btn = ('' if is_local else
            f'<button hx-post="/fleet-sync/pull/{h["name"]}" '
            f'hx-target="#sync-{h["name"]}" hx-swap="innerHTML" '
            f'hx-confirm="Pull DB from {h["name"]}? This will replace your local DB." '
            f'style="background:#1a1a3a;border:1px solid #2a2a4a;color:#88f;'
            f'padding:2px 8px;border-radius:3px;cursor:pointer;font-family:monospace;font-size:0.78rem">'
            f'Pull</button>')
        sync_btn = '<span class="muted">local</span>' if is_local else f'{push_btn} {pull_btn}'
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

    # Reconcile summary (mig 095): last run per machine, drift/error rate
    recon_rows_data = query_all("""
        SELECT machine_name,
               MAX(ran_at) AS last_run,
               (SELECT status FROM reconcile_runs r2
                 WHERE r2.machine_name = r.machine_name
                 ORDER BY r2.ran_at DESC LIMIT 1) AS last_status,
               SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) AS ok_ct,
               SUM(CASE WHEN status='drift' THEN 1 ELSE 0 END) AS drift_ct,
               SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS err_ct,
               SUM(CASE WHEN status='unreachable' THEN 1 ELSE 0 END) AS unr_ct
          FROM reconcile_runs r
         GROUP BY machine_name
         ORDER BY machine_name
    """)
    recon_rows = []
    for r in recon_rows_data:
        st = r["last_status"] or "?"
        col = ("#4a9a6a" if st == "ok"
               else "#e94560" if st == "drift"
               else "#e0c060")
        recon_rows.append([
            f'<strong>{html.escape(r["machine_name"])}</strong>',
            f'<span style="color:{col}">{st}</span>',
            f'<span class="muted">{html.escape((r["last_run"] or "")[:19])}</span>',
            f'{r["ok_ct"]}',
            (f'<span style="color:#e94560">{r["drift_ct"]}</span>'
             if r["drift_ct"] else '0'),
            (f'<span style="color:#e0c060">{r["err_ct"]}</span>'
             if r["err_ct"] else '0'),
            (f'<span style="color:#e0c060">{r["unr_ct"]}</span>'
             if r["unr_ct"] else '0'),
        ])
    recon_table = _table(
        ["Machine", "Last Status", "Last Run", "OK", "Drift", "Error",
         "Unreachable"],
        recon_rows, "No reconcile runs yet — `templedb reconcile machine all`",
        "fleet-sync-recon")

    # sync_scope entity distribution (mig 099): what would sync vs. stay local
    scope_rows_data = query_all("""
        SELECT sync_scope, COUNT(*) AS n
          FROM entities
         WHERE sync_scope IS NOT NULL
         GROUP BY sync_scope
         ORDER BY n DESC
    """)
    scope_rows = []
    for r in scope_rows_data:
        col = ("#4a9a6a" if r["sync_scope"] == "fleet"
               else "#e0c060" if r["sync_scope"] == "machine-local"
               else "#606080")
        scope_rows.append([
            f'<span style="color:{col}">{html.escape(r["sync_scope"])}</span>',
            f'<strong>{r["n"]:,}</strong>',
        ])
    scope_table = _table(
        ["Sync Scope", "Entity Count"],
        scope_rows, "No entities with sync_scope tagged",
        "fleet-sync-scope")

    body = f"""
<h2>Fleet Sync Dashboard</h2>
<p class="muted" style="margin-bottom:1rem">
  Compare TempleDB database state across machines. Probe checks latest commits via SSH.
  Push sends local DB to remote. Pull downloads remote DB (with conflict detection).
</p>
<h3>This Machine (Local Reference)</h3>
{ref_table}

<h3 style="margin-top:2rem">Reconcile Health</h3>
<p class="muted" style="margin-bottom:0.5rem">
  Passive drift detection — <code>templedb reconcile machine all</code> runs
  daily via systemd timer. Shows accumulated OK/drift/error/unreachable counts
  per machine plus last outcome.
</p>
{recon_table}

<h3 style="margin-top:2rem">Sync Scope Distribution</h3>
<p class="muted" style="margin-bottom:0.5rem">
  What CRSql would sync (fleet) vs. what stays local (machine-local).
  Per <code>_SYNC_SCOPES</code> in <code>src/cli/commands/entity.py</code>.
</p>
{scope_table}

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



@router.post("/fleet-sync/pull/{machine_name}", response_class=HTMLResponse)
def fleet_sync_pull(machine_name: str):
    """Pull the DB from a remote machine — checkpoint, download, conflict check."""
    import sqlite3 as _sqlite3
    import tempfile
    import shutil
    from db_utils import wal_checkpoint, safe_copy_db, DB_PATH

    hosts = _fleet_sync_get_hosts()
    host_info = next((h for h in hosts if h["name"] == machine_name), None)
    if not host_info or not host_info["host"]:
        return HTMLResponse(_msg("Unknown machine or no IP", ok=False))
    if host_info["host"] == "localhost":
        return HTMLResponse(_msg("Cannot pull from localhost", ok=False))

    user = host_info.get("user", "zach")
    host = host_info["host"]
    remote_db = f"{user}@{host}:~/.local/share/templedb/templedb.sqlite"

    try:
        # 1. Checkpoint local WAL first
        wal_checkpoint()

        # 2. Download remote DB to temp file
        tmp = tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False, prefix='templedb_pull_')
        tmp.close()
        r = subprocess.run(
            ["scp", "-o", "ConnectTimeout=10", remote_db, tmp.name],
            capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            os.unlink(tmp.name)
            return HTMLResponse(_msg(f"SCP failed: {r.stderr.strip()}", ok=False))

        # 3. Checkpoint the downloaded DB too
        conn_remote = _sqlite3.connect(tmp.name)
        conn_remote.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn_remote.close()

        # 4. Conflict detection — compare VCS commit heads
        conn_local = _sqlite3.connect(str(DB_PATH))
        conn_remote = _sqlite3.connect(tmp.name)
        conn_local.row_factory = _sqlite3.Row
        conn_remote.row_factory = _sqlite3.Row

        local_heads = {
            r["slug"]: r["hash"]
            for r in conn_local.execute(
                "SELECT p.slug, substr(c.commit_hash, 1, 8) as hash "
                "FROM projects p LEFT JOIN vcs_branches b ON p.active_branch_id = b.id "
                "LEFT JOIN vcs_commits c ON b.head_commit_id = c.id "
                "WHERE p.slug IS NOT NULL"
            ).fetchall()
        }

        try:
            remote_heads = {
                r["slug"]: r["hash"]
                for r in conn_remote.execute(
                    "SELECT p.slug, substr(c.commit_hash, 1, 8) as hash "
                    "FROM projects p LEFT JOIN vcs_branches b ON p.active_branch_id = b.id "
                    "LEFT JOIN vcs_commits c ON b.head_commit_id = c.id "
                    "WHERE p.slug IS NOT NULL"
                ).fetchall()
            }
        except Exception:
            remote_heads = {}

        conn_local.close()
        conn_remote.close()

        # 5. Check for divergence
        diverged = []
        for slug in set(local_heads) | set(remote_heads):
            lh = local_heads.get(slug, "—")
            rh = remote_heads.get(slug, "—")
            if lh != rh and lh != "—" and rh != "—":
                diverged.append(f"{slug}: local={lh} remote={rh}")

        if diverged:
            os.unlink(tmp.name)
            detail = "<br>".join(diverged)
            return HTMLResponse(_msg(
                f"Conflict: {len(diverged)} project(s) diverged between local and {machine_name}.<br>"
                f"{detail}<br><br>"
                f"Resolve by pushing your changes first, or force pull with care.",
                ok=False))

        # 6. No conflicts — safe to replace
        backup_path = str(DB_PATH) + f".pre-pull-{machine_name}"
        safe_copy_db(str(DB_PATH), backup_path)
        shutil.copy2(tmp.name, str(DB_PATH))
        os.unlink(tmp.name)

        return HTMLResponse(_msg(
            f"DB pulled from {machine_name}. Backup at {backup_path}", ok=True))

    except subprocess.TimeoutExpired:
        return HTMLResponse(_msg("SCP timed out", ok=False))
    except Exception as e:
        return HTMLResponse(_msg(f"Error: {e}", ok=False))





# ── Helpers (moved from gui_pages/systemd.py in a2763ce5+1) ──

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

