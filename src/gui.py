#!/usr/bin/env python3
"""
TempleDB Web GUI — FastAPI + HTMX
"""
import html
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db_utils import execute, query_all, query_one
from config import FUSE_MOUNT_PATH

from fastapi import FastAPI, Form, Query
from fastapi.responses import HTMLResponse

app = FastAPI(title="TempleDB", docs_url="/api-docs", redoc_url="/api-redoc")

def _find_templedb() -> str:
    """Find the templedb binary — works in both dev and nix-installed contexts."""
    import shutil
    # 1. Check if templedb is on PATH (nix-installed)
    on_path = shutil.which("templedb")
    if on_path:
        return on_path
    # 2. Check relative to this file (dev mode: src/gui.py -> ../templedb)
    dev_path = Path(__file__).parent.parent / "templedb"
    if dev_path.exists():
        return str(dev_path)
    # 3. Fallback: use python -m cli
    return sys.executable + " -m cli"

TEMPLEDB = _find_templedb()


# ── CLI helpers ───────────────────────────────────────────────────────────────

def _run(*args: str) -> tuple[int, str, str]:
    cmd = TEMPLEDB
    if " -m " in cmd:
        # python3 -m cli form: split into list
        parts = cmd.split() + list(args)
    else:
        parts = [cmd] + list(args)
    r = subprocess.run(parts, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


# ── HTML helpers ──────────────────────────────────────────────────────────────

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: monospace; background: #0f0f1a; color: #d0d0e8; display: flex; min-height: 100vh; font-size: 14px; }
nav { width: 180px; background: #13131f; padding: 1.2rem 1rem; border-right: 1px solid #1e1e3a; flex-shrink: 0; display: flex; flex-direction: column; gap: 0.2rem; }
nav h1 { color: #e94560; font-size: 1.1rem; margin-bottom: 1.2rem; letter-spacing: 0.05em; }
nav a { color: #808098; text-decoration: none; padding: 0.35rem 0.5rem; border-radius: 4px; display: block; }
nav a:hover { background: #1e1e3a; color: #d0d0e8; }
nav a.active { background: #1a1a30; color: #e94560; }
nav a kbd { float: right; font-size: 0.65rem; color: #606080; background: #0a0a14; padding: 0 3px; border-radius: 2px; margin-left: 0.4rem; line-height: 1.6; }
nav a:hover kbd { color: #808098; }
kbd.keyhint { font-size: 0.65rem; color: #606080; background: #0a0a14; padding: 1px 4px; border-radius: 2px; margin-left: 0.5rem; font-family: monospace; }
main { flex: 1; padding: 1.5rem 2rem; overflow: auto; }
h2 { color: #e94560; font-size: 1rem; margin-bottom: 1rem; text-transform: uppercase; letter-spacing: 0.08em; }
h3 { color: #a0a0c0; font-size: 0.9rem; margin-bottom: 0.6rem; }
table { width: 100%; border-collapse: collapse; margin-bottom: 1rem; }
.tabs { display: flex; gap: 0; margin-bottom: 1.5rem; border-bottom: 1px solid #1e1e3a; }
.tab { padding: 0.4rem 0.9rem; color: #606080; text-decoration: none; font-size: 0.85rem; border-bottom: 2px solid transparent; margin-bottom: -1px; }
.tab:hover { color: #d0d0e8; }
.tab.active { color: #e94560; border-bottom-color: #e94560; }
th { text-align: left; padding: 0.4rem 0.6rem; background: #13131f; color: #606080; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; border-bottom: 1px solid #1e1e3a; }
th:hover { color: #a0a0c0; }
th[data-sort="asc"] span { color: #e94560 !important; }
th[data-sort="desc"] span { color: #e94560 !important; }
td { padding: 0.35rem 0.6rem; border-bottom: 1px solid #1a1a2e; font-size: 0.85rem; }
tr:hover td { background: #16162a; }
a { color: #4a9eff; text-decoration: none; }
a:hover { color: #80c0ff; }
input[type=text], textarea { background: #13131f; border: 1px solid #2a2a4a; color: #d0d0e8; padding: 0.35rem 0.6rem; border-radius: 4px; font-family: monospace; font-size: 0.85rem; }
input[type=text]:focus, textarea:focus { outline: none; border-color: #4a9eff; }
input[type=text].full, textarea.full { width: 100%; }
button, .btn { background: #1e1e3a; border: 1px solid #2a2a4a; color: #d0d0e8; padding: 0.35rem 0.75rem; border-radius: 4px; cursor: pointer; font-family: monospace; font-size: 0.85rem; }
button:hover, .btn:hover { background: #282848; }
button.primary { background: #e94560; border-color: #e94560; color: #fff; }
button.primary:hover { background: #c73550; }
button.success { background: #2a6a3a; border-color: #2a6a3a; }
button.success:hover { background: #336a44; }
.badge { display: inline-block; background: #1e1e3a; padding: 0.1rem 0.4rem; border-radius: 3px; font-size: 0.75rem; color: #808098; }
.badge.green { background: #1a3a22; color: #4a9a6a; }
.badge.blue { background: #1a2a4a; color: #4a8acc; }
.badge.red { background: #3a1a1a; color: #e94560; }
pre { background: #0a0a14; border: 1px solid #1e1e3a; padding: 1rem; border-radius: 4px; overflow-x: auto; font-size: 0.8rem; line-height: 1.5; white-space: pre; }
.diff-add { color: #4a9a6a; }
.diff-del { color: #e94560; }
.diff-hunk { color: #808098; }
.form-group { margin-bottom: 0.75rem; }
label { display: block; color: #808098; font-size: 0.8rem; margin-bottom: 0.25rem; }
.row { display: flex; gap: 0.5rem; align-items: center; margin-bottom: 1rem; flex-wrap: wrap; }
.msg { padding: 0.5rem 0.75rem; border-radius: 4px; margin-bottom: 0.75rem; font-size: 0.85rem; }
.msg.ok { background: #1a3a22; border: 1px solid #2a6a3a; color: #4a9a6a; }
.msg.err { background: #3a1a22; border: 1px solid #e94560; color: #e94560; }
.muted { color: #606080; font-size: 0.8rem; }
.stat { display: inline-block; background: #13131f; border: 1px solid #1e1e3a; border-radius: 6px; padding: 0.75rem 1.25rem; margin: 0 0.5rem 0.5rem 0; }
.stat .val { font-size: 1.5rem; color: #e94560; }
.stat .key { font-size: 0.75rem; color: #606080; text-transform: uppercase; letter-spacing: 0.05em; margin-top: 0.2rem; }
.sep { border: none; border-top: 1px solid #1e1e3a; margin: 1rem 0; }
#search-input { width: 320px; }
.help-tip { display: inline-block; width: 16px; height: 16px; border-radius: 50%; background: #1e1e3a; color: #808098; text-align: center; font-size: 11px; line-height: 16px; cursor: help; margin-left: 4px; border: 1px solid #2a2a4a; }
.help-tip:hover { background: #282848; color: #d0d0e8; }
.help-tip .tip { display: none; position: absolute; background: #1a1a30; border: 1px solid #2a2a4a; padding: 0.5rem; border-radius: 4px; font-size: 0.78rem; color: #d0d0e8; max-width: 300px; z-index: 100; white-space: normal; margin-top: 4px; }
.help-tip:hover .tip { display: block; }
.inline-edit { background: none; border: none; border-bottom: 1px dashed #2a2a4a; color: #d0d0e8; font-family: monospace; font-size: 0.85rem; padding: 0.1rem 0.3rem; cursor: text; width: 100%; }
.inline-edit:focus { outline: none; border-bottom-color: #4a9eff; background: #13131f; }
.inline-edit:hover { border-bottom-color: #4a9eff; }
button.sm { padding: 0.15rem 0.4rem; font-size: 0.72rem; }
button.danger { background: #3a1a1a; border-color: #e94560; color: #e94560; }
button.danger:hover { background: #4a2222; }
#global-search { position: fixed; top: 0; left: 180px; right: 0; background: #0f0f1a; border-bottom: 1px solid #1e1e3a; padding: 0.5rem 2rem; z-index: 50; display: none; }
#global-search.active { display: flex; align-items: center; gap: 0.75rem; }
"""


def _base(title: str, body: str, active: str = "") -> HTMLResponse:
    nav = "\n".join(
        f'<a href="{href}" class="{"active" if active == k else ""}">'
        f'{label}'
        f'{f"""<kbd style="float:right;font-size:0.65rem;color:#606080;background:#0a0a14;padding:0 3px;border-radius:2px;margin-left:0.4rem">{key}</kbd>""" if key else ""}'
        f'</a>'
        for k, href, label, key in [
            ("dashboard", "/",         "Dashboard",  ""),
            ("projects", "/projects",  "Projects",   ", p"),
            ("vcs",      "/vcs",       "VCS",        ", s"),
            ("env",      "/env",       "Env",        ", v"),
            ("nix",      "/nix",       "Nix",        ", N"),
            ("deploy",   "/deploy",    "Deploy",     ", D"),
            ("audit",    "/audit",     "Audit",      ", L"),
            ("domains",  "/domains",   "Domains",    ", O"),
            ("docs",     "/docs",      "Docs",       ", k"),
            ("code",     "/code",      "Code",       ", C"),
            ("graph",    "/graph",     "Graph",      ", g"),
            ("schema-browser", "/schema-browser", "Schema", ", Q"),
            ("settings", "/settings",  "Settings",   ", S"),
            ("status",   "/status",    "Status",     ", i"),
            ("systemd",  "/systemd",   "Systemd",    ", u"),
            ("fleet-sync", "/fleet-sync", "Fleet Sync", ", F"),
            ("tests", "/tests",        "Tests",      ", t"),
        ]
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)} — TempleDB</title>
<script src="https://unpkg.com/htmx.org@1.9.10"></script>
<style>{CSS}</style>
<script>
function tFilter(id,q){{
  q=q.toLowerCase().trim();
  var c=document.getElementById(id);
  if(!c)return;
  c.querySelectorAll('tbody tr').forEach(function(r){{
    r.style.display=(!q||r.textContent.toLowerCase().includes(q))?'':'none';
  }});
  c.querySelectorAll('.fsec').forEach(function(s){{
    var rows=s.querySelectorAll('tbody tr');
    if(!rows.length)return;
    s.style.display=Array.from(rows).some(function(r){{return r.style.display!=='none';}})?'':'none';
  }});
}}
function fuzzyMatch(t,q){{
  t=t.toLowerCase();q=q.toLowerCase();var qi=0;
  for(var i=0;i<t.length&&qi<q.length;i++){{if(t[i]===q[qi])qi++;}}
  return qi===q.length;
}}
function gSearch(q){{
  q=q.trim();
  document.querySelectorAll('table tbody tr').forEach(function(r){{
    if(!q){{r.style.display='';return;}}
    r.style.display=fuzzyMatch(r.textContent,q)?'':'none';
  }});
}}
function sortTable(th){{
  var table=th.closest('table');
  if(!table)return;
  var tbody=table.querySelector('tbody');
  if(!tbody)return;
  var idx=Array.from(th.parentElement.children).indexOf(th);
  var rows=Array.from(tbody.querySelectorAll('tr'));
  var asc=th.dataset.sort!=='asc';
  th.parentElement.querySelectorAll('th').forEach(function(h){{h.dataset.sort='';h.style.color='';}});
  th.dataset.sort=asc?'asc':'desc';
  th.style.color='#e94560';
  rows.sort(function(a,b){{
    var av=a.children[idx]?a.children[idx].textContent.trim():'';
    var bv=b.children[idx]?b.children[idx].textContent.trim():'';
    var an=parseFloat(av.replace(/,/g,''));
    var bn=parseFloat(bv.replace(/,/g,''));
    if(!isNaN(an)&&!isNaN(bn))return asc?an-bn:bn-an;
    return asc?av.localeCompare(bv):bv.localeCompare(av);
  }});
  rows.forEach(function(r){{tbody.appendChild(r);}});
}}
document.addEventListener('keydown',function(e){{
  if(e.key==='/'&&!e.target.matches('input,textarea')){{
    e.preventDefault();
    var s=document.getElementById('gsearch');
    if(s){{s.parentElement.classList.add('active');s.focus();}}
  }}
  if(e.key==='Escape'){{
    var s=document.getElementById('gsearch');
    if(s){{s.parentElement.classList.remove('active');s.value='';gSearch('');}}
  }}
}});
</script>
</head>
<body>
<nav>
  <h1>TempleDB</h1>
  {nav}
  <div style="margin-top:auto;padding-top:1rem;border-top:1px solid #1e1e3a">
    <span class="muted" style="font-size:0.7rem">/ search &middot; Emacs: SPC ,</span>
  </div>
</nav>
<div id="global-search">
  <span style="color:#808098;font-size:0.85rem">Search:</span>
  <input id="gsearch" type="search" placeholder="Fuzzy search across all tables..." oninput="gSearch(this.value)"
    style="flex:1;max-width:500px;background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;padding:0.35rem 0.6rem;border-radius:4px;font-family:monospace;font-size:0.85rem"
    autocomplete="off">
  <span class="muted" style="font-size:0.75rem">Esc to close</span>
</div>
<main>
{body}
</main>
</body>
</html>"""
    return HTMLResponse(page)


def _table(headers: list[str], rows: list[list[str]], empty: str = "No results.", table_id: str = "") -> str:
    if not rows:
        return f'<p class="muted">{html.escape(empty)}</p>'
    ths = "".join(
        f'<th onclick="sortTable(this)" style="cursor:pointer;user-select:none" title="Click to sort">{html.escape(h)} <span style="font-size:0.65rem;color:#404060">⇅</span></th>'
        for h in headers
    )
    trs = ""
    for row in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in row)
        trs += f"<tr>{tds}</tr>"
    id_attr = f' id="{html.escape(table_id)}"' if table_id else ""
    return f"<table{id_attr}><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>"


def _search_bar(container_id: str, placeholder: str = "Filter…", width: str = "280px") -> str:
    return (
        f'<input type="search" placeholder="{html.escape(placeholder)}" '
        f'oninput="tFilter(\'{container_id}\',this.value)" '
        f'style="width:{width};margin-bottom:0.75rem;background:#13131f;border:1px solid #2a2a4a;'
        f'color:#d0d0e8;padding:0.35rem 0.6rem;border-radius:4px;font-family:monospace;font-size:0.85rem" '
        f'autocomplete="off">'
    )


def _file_link(slug: str, path: str, label: str = "") -> str:
    """Render a clickable file path linking to the file viewer."""
    escaped_slug = html.escape(slug)
    from urllib.parse import quote
    escaped_path = html.escape(path)
    encoded_path = quote(path, safe="")
    display = html.escape(label or path)
    return (
        f'<a href="/projects/{escaped_slug}/file?path={encoded_path}" '
        f'style="font-family:monospace;font-size:0.78rem;word-break:break-all">{display}</a>'
    )


def _msg(text: str, ok: bool = True) -> str:
    cls = "ok" if ok else "err"
    return f'<div class="msg {cls}">{html.escape(text)}</div>'


def _colorize_diff(diff: str) -> str:
    out = []
    for line in diff.split("\n"):
        esc = html.escape(line)
        if line.startswith("+++") or line.startswith("---"):
            out.append(f'<span class="muted">{esc}</span>')
        elif line.startswith("+"):
            out.append(f'<span class="diff-add">{esc}</span>')
        elif line.startswith("-"):
            out.append(f'<span class="diff-del">{esc}</span>')
        elif line.startswith("@@"):
            out.append(f'<span class="diff-hunk">{esc}</span>')
        else:
            out.append(esc)
    return "\n".join(out)


def _highlight_template(template: str) -> str:
    """Highlight ${VAR} references in compound var templates."""
    def replace(m):
        name = html.escape(m.group(1))
        return f'<span style="color:#f0a030;font-weight:bold">${{{name}}}</span>'
    return re.sub(r'\$\{([^}]+)\}', replace, html.escape(template))


# ── Root ──────────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
def root():
    # ── Stats ──────────────────────────────────────────────────────────────────
    project_count = (query_one("SELECT COUNT(*) AS n FROM projects") or {}).get("n", 0)
    file_count = (query_one("SELECT COUNT(*) AS n FROM project_files") or {}).get("n", 0)
    commit_count = (query_one("SELECT COUNT(*) AS n FROM vcs_commits") or {}).get("n", 0)
    loc = (query_one("SELECT COALESCE(SUM(lines_of_code),0) AS n FROM project_files") or {}).get("n", 0)

    try:
        from config import default_db_path
        db_path = default_db_path()
        db_size_mb = os.path.getsize(db_path) / 1024 / 1024
        db_size_str = f'{db_size_mb:.1f} MB'
    except Exception:
        db_size_str = "?"

    stats_html = "".join(
        f'<div class="stat"><div class="val">{v}</div><div class="key">{k}</div></div>'
        for v, k in [
            (project_count, "Projects"),
            (f"{file_count:,}", "Files"),
            (f"{commit_count:,}", "Commits"),
            (f"{loc:,}", "Lines of Code"),
            (db_size_str, "Database"),
        ]
    )

    # ── Recent commits ─────────────────────────────────────────────────────────
    recent_commits = query_all("""
        SELECT p.slug, vc.commit_hash, vc.commit_message, vc.commit_timestamp, vc.author
        FROM vcs_commits vc JOIN projects p ON vc.project_id = p.id
        ORDER BY vc.commit_timestamp DESC LIMIT 8
    """)
    commit_rows = []
    for c in recent_commits:
        commit_rows.append([
            f'<a href="/projects/{html.escape(c["slug"])}">{html.escape(c["slug"])}</a>',
            f'<a href="/vcs/{html.escape(c["slug"])}/commits/{html.escape(c["commit_hash"])}">'
            f'<code>{html.escape(c["commit_hash"][:8])}</code></a>',
            html.escape((c["commit_message"] or "").split("\n")[0][:72]),
            html.escape(c["author"] or ""),
            html.escape((c["commit_timestamp"] or "")[:16]),
        ])

    # ── Recent deploys ─────────────────────────────────────────────────────────
    recent_deploys = query_all("""
        SELECT p.slug, dh.target_name, dh.status, dh.started_at, dh.duration_ms,
               SUBSTR(dh.commit_hash, 1, 8) AS short_hash, dh.error_message
        FROM deployment_history dh JOIN projects p ON dh.project_id = p.id
        ORDER BY dh.started_at DESC LIMIT 6
    """)
    deploy_rows = []
    for d in recent_deploys:
        dur = f'{d["duration_ms"] // 1000}s' if d["duration_ms"] else ""
        deploy_rows.append([
            f'<a href="/projects/{html.escape(d["slug"])}">{html.escape(d["slug"])}</a>',
            html.escape(d["target_name"] or ""),
            _status_badge(d["status"]),
            f'<code class="muted">{html.escape(d["short_hash"] or "")}</code>',
            html.escape((d["started_at"] or "")[:16]),
            dur,
        ])

    # ── Fleet health ───────────────────────────────────────────────────────────
    fleet_machines = query_all("""
        SELECT m.machine_name, m.target_host, m.deployment_status, m.health_status,
               n.network_name
        FROM fleet_machines m
        JOIN fleet_networks n ON m.network_id = n.id
        WHERE n.is_active = 1
        ORDER BY n.network_name, m.machine_name
    """)
    fleet_html = ""
    if fleet_machines:
        fleet_items = []
        for fm in fleet_machines:
            h = fm["health_status"] or "unknown"
            s = fm["deployment_status"] or "new"
            color = "#4a9a6a" if h == "healthy" else "#e94560" if h in ("unhealthy", "unreachable") else "#808098"
            fleet_items.append(
                f'<div style="display:inline-block;background:#13131f;border:1px solid #1e1e3a;'
                f'border-radius:4px;padding:0.4rem 0.7rem;margin:0.2rem">'
                f'<span style="color:{color};font-size:0.9rem">{"●" if h == "healthy" else "○"}</span> '
                f'<strong>{html.escape(fm["machine_name"])}</strong> '
                f'<span class="muted" style="font-size:0.75rem">{html.escape(fm["target_host"] or "")}</span>'
                f'</div>'
            )
        fleet_html = f"""
<h3 style="margin-top:1.5rem">Fleet <a href="/deploy" class="muted" style="font-size:0.75rem">view all</a></h3>
<div style="display:flex;flex-wrap:wrap;gap:0.2rem">{"".join(fleet_items)}</div>
"""

    # ── Alerts ─────────────────────────────────────────────────────────────────
    alerts = []
    failed_deploys = query_one(
        "SELECT COUNT(*) AS n FROM deployment_history WHERE status = 'failed' AND started_at > datetime('now', '-7 days')"
    )
    if failed_deploys and failed_deploys["n"]:
        alerts.append(f'{failed_deploys["n"]} failed deploy(s) in last 7 days')

    unhealthy = [m for m in fleet_machines if m["health_status"] in ("unhealthy", "unreachable")]
    if unhealthy:
        names = ", ".join(m["machine_name"] for m in unhealthy[:3])
        alerts.append(f'Fleet machines need attention: {names}')

    last_backup = query_one("SELECT backed_up_at FROM backup_history ORDER BY backed_up_at DESC LIMIT 1") if _backup_history_exists() else None
    if not last_backup:
        alerts.append("No backups recorded")

    try:
        from migrator import Migrator
        from db_utils import DB_PATH
        m = Migrator(DB_PATH)
        pending = sum(1 for s in m.status() if not s["applied"])
        if pending:
            alerts.append(f'{pending} pending DB migration(s)')
    except Exception:
        pass

    fuse_mounted = False
    try:
        with open("/proc/mounts") as fm:
            for line in fm:
                if "fuse" in line.lower() and "temple" in line.lower():
                    fuse_mounted = True
                    break
    except Exception:
        pass
    if not fuse_mounted:
        alerts.append("FUSE mount is down ({FUSE_MOUNT_PATH})")

    alerts_html = ""
    if alerts:
        items = "".join(
            f'<div style="background:#3a1a22;border:1px solid #4a2a32;border-radius:4px;'
            f'padding:0.4rem 0.75rem;margin-bottom:0.3rem;font-size:0.85rem;color:#e94560">{html.escape(a)}</div>'
            for a in alerts
        )
        alerts_html = f'<div style="margin-bottom:1rem">{items}</div>'

    # ── Quick Actions ──────────────────────────────────────────────────────────
    quick_actions = """
<div style="display:flex;gap:0.5rem;margin-bottom:1.5rem;flex-wrap:wrap">
  <button hx-post="/backup/gcs" hx-swap="outerHTML" style="font-size:0.78rem">Backup to GCS</button>
  <button hx-post="/mount/toggle" hx-swap="outerHTML" style="font-size:0.78rem">Toggle FUSE Mount</button>
  <button hx-post="/projects/sync-all" hx-target="#dash-sync-result" hx-swap="innerHTML" style="font-size:0.78rem">Sync All</button>
  <button hx-post="/db/migrate" hx-swap="outerHTML" style="font-size:0.78rem">Run Migrations</button>
  <span id="dash-sync-result" class="muted"></span>
</div>
"""

    # ── Navigation Guide ───────────────────────────────────────────────────────
    nav_guide = """
<h3 style="margin-top:1.5rem">About TempleDB</h3>
<div style="color:#a0a0c0;font-size:0.85rem;line-height:1.7;margin-bottom:1.2rem;max-width:700px">
<p style="margin-bottom:0.6rem">
Terry Davis built an entire operating system alone because he believed a single
mind could hold a whole cathedral. TempleDB carries that conviction forward:
one SQLite file <em>is</em> the project &mdash; source, history, secrets, config,
deployments, domains, documentation, and the knowledge graph that connects them.
Not scattered across <code>.git/</code>, <code>.env</code>, CI YAML, and a dozen SaaS dashboards.
One artifact. One truth.
</p>
<p style="margin-bottom:0.6rem">
The FUSE mount at <code>{FUSE_MOUNT_PATH}/</code> projects the database back into the
filesystem so legacy tools still work, but the filesystem is the shadow on the
cave wall &mdash; the database is the reality. Writes through the mount go
straight to SQLite with ACID guarantees. Version control is native:
commits are rows, branches are foreign keys, merges are transactions.
</p>
<p>
Every tab below is a different <em>view</em> into the same data. Projects are
the central entity; everything else &mdash; commits, deploys, secrets, nix
configs, domains &mdash; hangs off them. The system is designed so that
a single <code>templedb.sqlite</code> backup is a complete, portable snapshot
of your entire digital life as a developer.
</p>
</div>
<div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(280px, 1fr));gap:0.5rem">
  <a href="/projects" style="display:block;background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.65rem 0.85rem;text-decoration:none">
    <strong style="color:#e94560">Projects</strong><kbd class="keyhint">SPC , p</kbd>
    <div class="muted" style="margin-top:0.2rem">Every git repo you've imported. Files, LOC, sync status, backups. The central entity everything else hangs off of.</div>
  </a>
  <a href="/vcs" style="display:block;background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.65rem 0.85rem;text-decoration:none">
    <strong style="color:#e94560">VCS</strong><kbd class="keyhint">SPC , s</kbd>
    <div class="muted" style="margin-top:0.2rem">Database-native version control. Commits, branches, staging, diffs. Replaces git with ACID-guaranteed history stored in SQLite.</div>
  </a>
  <a href="/env" style="display:block;background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.65rem 0.85rem;text-decoration:none">
    <strong style="color:#e94560">Env</strong><kbd class="keyhint">SPC , v</kbd>
    <div class="muted" style="margin-top:0.2rem">Environment variables and secrets across projects and profiles. Templated values, secret masking, scoped to project or global.</div>
  </a>
  <a href="/nix" style="display:block;background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.65rem 0.85rem;text-decoration:none">
    <strong style="color:#e94560">Nix</strong><kbd class="keyhint">SPC , N</kbd>
    <div class="muted" style="margin-top:0.2rem">NixOS configuration stored in the DB. Flake configs, host-specific options, packages, and the system config that gets materialized into your flake.</div>
  </a>
  <a href="/deploy" style="display:block;background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.65rem 0.85rem;text-decoration:none">
    <strong style="color:#e94560">Deploy</strong><kbd class="keyhint">SPC , D</kbd>
    <div class="muted" style="margin-top:0.2rem">Deployment engine. Auto-deploy triggers, fleet NixOS rollouts with magic rollback, deploy history, health checks, and caching.</div>
  </a>
  <a href="/audit" style="display:block;background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.65rem 0.85rem;text-decoration:none">
    <strong style="color:#e94560">Audit</strong><kbd class="keyhint">SPC , L</kbd>
    <div class="muted" style="margin-top:0.2rem">Every action TempleDB takes gets logged. Filter by project or action type. The immutable record of what happened and when.</div>
  </a>
  <a href="/domains" style="display:block;background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.65rem 0.85rem;text-decoration:none">
    <strong style="color:#e94560">Domains</strong><kbd class="keyhint">SPC , O</kbd>
    <div class="muted" style="margin-top:0.2rem">Domain names, DNS records, SSL certs, and registrar info. Track which project owns which domain.</div>
  </a>
  <a href="/docs" style="display:block;background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.65rem 0.85rem;text-decoration:none">
    <strong style="color:#e94560">Docs</strong><kbd class="keyhint">SPC , k</kbd>
    <div class="muted" style="margin-top:0.2rem">READMEs and documentation files across all projects. Scanned, categorized, and searchable by topic.</div>
  </a>
  <a href="/code" style="display:block;background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.65rem 0.85rem;text-decoration:none">
    <strong style="color:#e94560">Code</strong><kbd class="keyhint">SPC , C</kbd>
    <div class="muted" style="margin-top:0.2rem">Extracted code symbols &mdash; functions, classes, methods. Complexity analysis, dependency tracking, and cross-project call graphs.</div>
  </a>
  <a href="/graph" style="display:block;background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.65rem 0.85rem;text-decoration:none">
    <strong style="color:#e94560">Graph</strong><kbd class="keyhint">SPC , g</kbd>
    <div class="muted" style="margin-top:0.2rem">The knowledge graph. Cross-project search, dependency visualization, and relationship mapping. How everything connects.</div>
  </a>
  <a href="/schema-browser" style="display:block;background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.65rem 0.85rem;text-decoration:none">
    <strong style="color:#e94560">Schema</strong><kbd class="keyhint">SPC , Q</kbd>
    <div class="muted" style="margin-top:0.2rem">Browse the TempleDB schema itself. Every table, column, index, and trigger in the SQLite database.</div>
  </a>
  <a href="/settings" style="display:block;background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.65rem 0.85rem;text-decoration:none">
    <strong style="color:#e94560">Settings</strong><kbd class="keyhint">SPC , S</kbd>
    <div class="muted" style="margin-top:0.2rem">System configuration. Host-specific NixOS attrs, dotfile links, config checkouts, and TempleDB's own settings.</div>
  </a>
  <a href="/status" style="display:block;background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.65rem 0.85rem;text-decoration:none">
    <strong style="color:#e94560">Status</strong><kbd class="keyhint">SPC , i</kbd>
    <div class="muted" style="margin-top:0.2rem">System health. DB stats, migration status, FUSE mount, bootstrap readiness, daemon status, and active services.</div>
  </a>
  <a href="/systemd" style="display:block;background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.65rem 0.85rem;text-decoration:none">
    <strong style="color:#e94560">Systemd</strong><kbd class="keyhint">SPC , u</kbd>
    <div class="muted" style="margin-top:0.2rem">Live systemd unit monitor. View user and system services, filter by state, read logs. Your machine at a glance.</div>
  </a>
</div>
"""

    body = f"""
<h2>TempleDB</h2>
<p style="color:#606080;font-size:0.8rem;margin-bottom:1rem;font-style:italic">In Honor of Terry Davis</p>
{alerts_html}
{stats_html}
{quick_actions}

<h3 style="margin-top:1rem">Recent Commits</h3>
{_table(["Project", "Hash", "Message", "Author", "Time"], commit_rows, "No commits yet.")}

<h3 style="margin-top:1rem">Recent Deploys <a href="/deploy" class="muted" style="font-size:0.75rem">view all</a></h3>
{_table(["Project", "Target", "Status", "Commit", "Started", "Dur"], deploy_rows, "No deployments yet.")}

{fleet_html}

<h3 style="margin-top:1.5rem">Emacs Keybindings <span class="muted" style="font-size:0.75rem">SPC , opens dispatch</span></h3>
<div style="display:grid;grid-template-columns:repeat(auto-fill, minmax(320px, 1fr));gap:0.6rem;font-size:0.8rem;margin-bottom:1.2rem">
  <div style="background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.6rem 0.8rem">
    <strong style="color:#e94560">Claude Code & AI</strong>
    <div class="muted" style="margin-top:0.3rem;line-height:1.8">
      <kbd class="keyhint">SPC , ,</kbd> Launch Claude Code &nbsp;
      <kbd class="keyhint">SPC , a</kbd> Vibe start &nbsp;
      <kbd class="keyhint">SPC , A</kbd> Vibe stop &amp; commit
    </div>
  </div>
  <div style="background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.6rem 0.8rem">
    <strong style="color:#e94560">VCS</strong>
    <div class="muted" style="margin-top:0.3rem;line-height:1.8">
      <kbd class="keyhint">SPC , s</kbd> Status &nbsp;
      <kbd class="keyhint">SPC , c</kbd> Commit &nbsp;
      <kbd class="keyhint">SPC , l</kbd> Log &nbsp;
      <kbd class="keyhint">SPC , b</kbd> Branch &nbsp;
      <kbd class="keyhint">SPC , d</kbd> Diff &nbsp;
      <kbd class="keyhint">SPC , m</kbd> Merge
    </div>
  </div>
  <div style="background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.6rem 0.8rem">
    <strong style="color:#e94560">Projects</strong>
    <div class="muted" style="margin-top:0.3rem;line-height:1.8">
      <kbd class="keyhint">SPC , p</kbd> List &nbsp;
      <kbd class="keyhint">SPC , P</kbd> Switch &nbsp;
      <kbd class="keyhint">SPC , I</kbd> Import &nbsp;
      <kbd class="keyhint">SPC , y</kbd> Sync &nbsp;
      <kbd class="keyhint">SPC , Y</kbd> Sync all &nbsp;
      <kbd class="keyhint">SPC , o</kbd> Layout
    </div>
  </div>
  <div style="background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.6rem 0.8rem">
    <strong style="color:#e94560">Operations</strong>
    <div class="muted" style="margin-top:0.3rem;line-height:1.8">
      <kbd class="keyhint">SPC , D</kbd> Deploy &nbsp;
      <kbd class="keyhint">SPC , f</kbd> Fleet &nbsp;
      <kbd class="keyhint">SPC , t</kbd> Tests &nbsp;
      <kbd class="keyhint">SPC , /</kbd> Search &nbsp;
      <kbd class="keyhint">SPC , B</kbd> Backup &nbsp;
      <kbd class="keyhint">SPC , x</kbd> Migrate
    </div>
  </div>
  <div style="background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.6rem 0.8rem">
    <strong style="color:#e94560">NixOS &amp; Config</strong>
    <div class="muted" style="margin-top:0.3rem;line-height:1.8">
      <kbd class="keyhint">SPC , N</kbd> Nix menu &nbsp;
      <kbd class="keyhint">SPC , S</kbd> Settings &nbsp;
      <kbd class="keyhint">SPC , M</kbd> FUSE mount &nbsp;
      <kbd class="keyhint">SPC , v</kbd> Variables
    </div>
  </div>
  <div style="background:#13131f;border:1px solid #1e1e3a;border-radius:4px;padding:0.6rem 0.8rem">
    <strong style="color:#e94560">Browse</strong>
    <div class="muted" style="margin-top:0.3rem;line-height:1.8">
      <kbd class="keyhint">SPC , Q</kbd> Schema &nbsp;
      <kbd class="keyhint">SPC , C</kbd> Code &nbsp;
      <kbd class="keyhint">SPC , g</kbd> Graph &nbsp;
      <kbd class="keyhint">SPC , L</kbd> Audit &nbsp;
      <kbd class="keyhint">SPC , k</kbd> Docs &nbsp;
      <kbd class="keyhint">SPC , q</kbd> SQL
    </div>
  </div>
</div>

{nav_guide}
"""
    return _base("Dashboard", body, "dashboard")


# ── Projects ──────────────────────────────────────────────────────────────────


from gui_pages.settings import router as settings_router
app.include_router(settings_router)
from gui_pages.projects import router as projects_router
app.include_router(projects_router)
from gui_pages.actions import router as actions_router
app.include_router(actions_router)
