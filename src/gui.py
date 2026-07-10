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

@app.get("/projects", response_class=HTMLResponse)
def projects_list():
    rows_data = query_all("""
        SELECT p.slug, p.name, p.repo_url, p.updated_at,
               (SELECT COUNT(*) FROM project_files WHERE project_id = p.id) AS files,
               (SELECT COALESCE(SUM(lines_of_code),0) FROM project_files WHERE project_id = p.id) AS loc,
               (SELECT checkout_path FROM checkouts c WHERE c.project_id = p.id AND c.is_active=1 ORDER BY last_sync_at DESC LIMIT 1) AS checkout_path,
               (SELECT MAX(last_sync_at) FROM checkouts c WHERE c.project_id = p.id AND c.is_active=1) AS last_synced,
               (SELECT vc.commit_hash FROM vcs_commits vc WHERE vc.project_id = p.id ORDER BY vc.commit_timestamp DESC LIMIT 1) AS last_commit_hash,
               (SELECT vc.commit_message FROM vcs_commits vc WHERE vc.project_id = p.id ORDER BY vc.commit_timestamp DESC LIMIT 1) AS last_commit_msg,
               (SELECT vc.commit_timestamp FROM vcs_commits vc WHERE vc.project_id = p.id ORDER BY vc.commit_timestamp DESC LIMIT 1) AS last_commit_at,
               (SELECT backed_up_at FROM backup_history ORDER BY backed_up_at DESC LIMIT 1) AS last_backed_up,
               (SELECT provider FROM backup_history ORDER BY backed_up_at DESC LIMIT 1) AS last_backup_provider
        FROM projects p ORDER BY slug
    """)
    rows = [
        [
            f'<a href="/projects/{html.escape(r["slug"])}">{html.escape(r["slug"])}</a>',
            html.escape(r["name"] or ""),
            f'{r["files"]:,}',
            f'{r["loc"]:,}',
            html.escape(r["repo_url"] or ""),
            html.escape((r["updated_at"] or "")[:10]),
            (
                f'{html.escape((r["last_synced"] or "")[:10])} <span class="muted">{html.escape(r["checkout_path"] or "")}</span>'
                if r["last_synced"] else
                (f'<span class="muted">{html.escape(r["checkout_path"])}</span>' if r["checkout_path"] else '<span class="muted">—</span>')
            ),
            (
                f'<a href="/vcs/{html.escape(r["slug"])}/commits/{html.escape(r["last_commit_hash"])}" title="{html.escape((r["last_commit_msg"] or "")[:80])}">'
                f'{html.escape(r["last_commit_hash"][:8])} '
                f'<span class="muted">{html.escape((r["last_commit_at"] or "")[:10])}</span></a>'
            ) if r["last_commit_hash"] else '<span class="muted">—</span>',
            (
                f'{html.escape((r["last_backed_up"] or "")[:10])} <span class="muted">{html.escape(r["last_backup_provider"] or "")}</span>'
            ) if r["last_backed_up"] else '<span class="muted">—</span>',
            f'<form style="display:inline" hx-post="/projects/{html.escape(r["slug"])}/sync" hx-target="#sync-result-{html.escape(r["slug"])}" hx-swap="innerHTML">'
            f'<button type="submit" style="padding:0.15rem 0.4rem;font-size:0.75rem">Sync</button></form>'
            f'<span id="sync-result-{html.escape(r["slug"])}"></span>',
        ]
        for r in rows_data
    ]

    # Backup history table
    backups = query_all("""
        SELECT backed_up_at, provider, backup_path, size_bytes
        FROM backup_history ORDER BY backed_up_at DESC LIMIT 10
    """) if _backup_history_exists() else []
    backup_rows = [
        [
            html.escape((r["backed_up_at"] or "")[:16]),
            html.escape(r["provider"] or ""),
            f'<span class="muted" style="font-size:0.75rem">{html.escape(r["backup_path"] or "")}</span>',
            f'{r["size_bytes"] // 1024 // 1024} MB' if r["size_bytes"] else "—",
        ]
        for r in backups
    ]
    backup_section = f"""
<hr class="sep">
<h3>Backup History</h3>
<div class="row">
  <form hx-post="/backup/local" hx-target="#backup-result" hx-swap="innerHTML">
    <button type="submit">Backup Now (local)</button>
  </form>
  <form hx-post="/backup/gcs" hx-target="#backup-result" hx-swap="innerHTML">
    <button type="submit">Backup to GCS</button>
  </form>
  <span id="backup-result"></span>
</div>
{_table(["Time", "Provider", "Path", "Size"], backup_rows, "No backups recorded yet.")}
"""

    import_form = """
<hr class="sep">
<h3>Import Project</h3>
<form hx-post="/projects/import" hx-target="#import-result" hx-swap="innerHTML">
  <div class="row">
    <div class="form-group" style="flex:1">
      <label>Path</label>
      <input type="text" name="path" class="full" placeholder="/path/to/project" required>
    </div>
    <div class="form-group" style="width:160px">
      <label>Slug (optional)</label>
      <input type="text" name="slug" placeholder="auto-detect">
    </div>
    <div style="padding-top:1.4rem">
      <button type="submit" class="primary">Import</button>
    </div>
  </div>
</form>
<div id="import-result"></div>
"""

    sync_all_btn = """
<div class="row" style="margin-bottom:0.5rem">
  <form hx-post="/projects/sync-all" hx-target="#sync-all-result" hx-swap="innerHTML">
    <button type="submit">Sync All Projects</button>
    <span class="help-tip" style="position:relative">?<span class="tip">Re-imports project files from checkout dirs into the database. Only needed if you edited files in ~/.config/templedb/checkouts/ directly. Not needed if you use the FUSE mount ({FUSE_MOUNT_PATH}/) — FUSE writes go straight to the DB.</span></span>
  </form>
  <span id="sync-all-result" class="muted"></span>
</div>
"""

    body = f"""
<h2>Projects</h2>
{sync_all_btn}
{_search_bar("projects-tbl", "Filter projects…")}
{_table(["Slug", "Name", "Files", "LOC", "Location", "Updated", "Synced", "Latest Commit", "Last Backup", ""], rows, "No projects found.", "projects-tbl")}
{backup_section}
{import_form}
"""
    return _base("Projects", body, "projects")


def _backup_history_exists() -> bool:
    try:
        query_one("SELECT 1 FROM backup_history LIMIT 1")
        return True
    except Exception:
        return False


@app.post("/projects/import", response_class=HTMLResponse)
def projects_import(path: str = Form(...), slug: str = Form("")):
    cmd = ["project", "import", path]
    if slug.strip():
        cmd += ["--slug", slug.strip()]
    rc, out, err = _run(*cmd)
    msg = out or err or "Done"
    return HTMLResponse(_msg(msg, ok=rc == 0))


@app.post("/projects/{slug}/sync", response_class=HTMLResponse)
def project_sync(slug: str):
    rc, out, err = _run("project", "sync", slug)
    text = (out or err or "Done").split("\n")[0][:80]
    ok_cls = "color:#4a9a6a" if rc == 0 else "color:#e94560"
    return HTMLResponse(f' <span style="{ok_cls};font-size:0.75rem">{html.escape(text)}</span>')


@app.post("/projects/sync-all", response_class=HTMLResponse)
def projects_sync_all():
    import os
    projects = query_all("SELECT slug, repo_url FROM projects WHERE repo_url IS NOT NULL AND repo_url != ''")
    results = []
    for p in projects:
        if not os.path.isdir(p["repo_url"]):
            results.append(f'{p["slug"]}: skipped (path missing)')
            continue
        rc, out, err = _run("project", "sync", p["slug"])
        status = "ok" if rc == 0 else "failed"
        results.append(f'{p["slug"]}: {status}')
    summary = ", ".join(results)
    return HTMLResponse(f'<span class="muted" style="font-size:0.8rem">{html.escape(summary)}</span>')


@app.post("/backup/local", response_class=HTMLResponse)
def backup_local():
    rc, out, err = _run("storage", "backup", "local")
    return HTMLResponse(_msg(out or err or "Done", ok=rc == 0))


@app.post("/backup/gcs", response_class=HTMLResponse)
def backup_gcs():
    rc, out, err = _run("storage", "backup", "gcs")
    return HTMLResponse(_msg(out or err or "Done", ok=rc == 0))


@app.post("/nixos/generate-all", response_class=HTMLResponse)
def nixos_generate_all():
    rc, out, err = _run("nixos", "generate-all")
    return HTMLResponse(_msg(out or err or "Generated", ok=rc == 0))


@app.post("/nixos/host-clone", response_class=HTMLResponse)
def nixos_host_clone(source: str = Form(...), target: str = Form(...)):
    rc, out, err = _run("nixos", "host", "clone", source, target)
    return HTMLResponse(_msg(out or err or f"Cloned {source} → {target}", ok=rc == 0))


@app.post("/nixos/dotfiles-apply", response_class=HTMLResponse)
def nixos_dotfiles_apply():
    rc, out, err = _run("nixos", "dotfiles-apply", "--force")
    return HTMLResponse(_msg(out or err or "Applied", ok=rc == 0))


@app.post("/db/migrate", response_class=HTMLResponse)
def db_migrate():
    rc, out, err = _run("db", "migrate")
    return HTMLResponse(_msg(out or err or "Done", ok=rc == 0))


# ── CRUD: system_config ───────────────────────────────────────────────────────

@app.post("/config/set", response_class=HTMLResponse)
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


@app.post("/config/delete", response_class=HTMLResponse)
def config_delete(key: str = Form(...)):
    """Delete a system_config key."""
    from db_utils import execute
    execute("DELETE FROM system_config WHERE key = ?", (key,))
    return HTMLResponse(_msg(f"Deleted {key}", ok=True))


# ── CRUD: environment variables ──────────────────────────────────────────────

@app.post("/env/set", response_class=HTMLResponse)
def env_var_set(project: str = Form(...), var_name: str = Form(...), var_value: str = Form(...)):
    """Set an environment variable."""
    rc, out, err = _run("env", "set", project, var_name, var_value)
    return HTMLResponse(_msg(out or err or f"Set {var_name}", ok=rc == 0))


@app.post("/env/delete", response_class=HTMLResponse)
def env_var_delete(project: str = Form(...), var_name: str = Form(...)):
    """Delete an environment variable."""
    rc, out, err = _run("env", "rm", project, var_name)
    return HTMLResponse(_msg(out or err or f"Deleted {var_name}", ok=rc == 0))


# ── CRUD: dotfiles ───────────────────────────────────────────────────────────

@app.post("/dotfiles/add", response_class=HTMLResponse)
def dotfiles_add(project: str = Form(...), source: str = Form(...), target: str = Form(...)):
    """Add a dotfile mapping."""
    rc, out, err = _run("nixos", "dotfiles-add", project, source, target)
    return HTMLResponse(_msg(out or err or f"Added {source}", ok=rc == 0))


@app.post("/dotfiles/remove", response_class=HTMLResponse)
def dotfiles_remove(project: str = Form(...), source: str = Form(...)):
    """Remove a dotfile mapping."""
    rc, out, err = _run("nixos", "dotfiles-remove", project, source)
    return HTMLResponse(_msg(out or err or f"Removed {source}", ok=rc == 0))


# ── CRUD: project settings ──────────────────────────────────────────────────

@app.post("/projects/{slug}/set-type", response_class=HTMLResponse)
def project_set_type(slug: str, project_type: str = Form(...)):
    """Set project type."""
    rc, out, err = _run("nixos", "set-type", slug, project_type)
    return HTMLResponse(_msg(out or err or f"Set type to {project_type}", ok=rc == 0))


@app.post("/mount/toggle", response_class=HTMLResponse)
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


@app.get("/projects/{slug}", response_class=HTMLResponse)
def project_detail(slug: str, q: str = Query(default=""), tab: str = Query(default="files")):
    proj = query_one("SELECT id, name FROM projects WHERE slug = ?", (slug,))
    if not proj:
        return _base("Not found", f'<p class="muted">Project "{html.escape(slug)}" not found.</p>', "projects")

    s = html.escape(slug)
    tabs_html = f"""
<div class="tabs">
  <a href="/projects/{s}" class="tab{"active" if tab == "files" else ""}">Files</a>
  <a href="/projects/{s}?tab=vars" class="tab{"active" if tab == "vars" else ""}">Vars</a>
  <a href="/projects/{s}?tab=docs" class="tab{"active" if tab == "docs" else ""}">Docs</a>
</div>"""

    if tab == "vars":
        tab_content = _project_vars_tab(slug)
    elif tab == "docs":
        tab_content = _project_docs_tab(slug)
    else:
        tab_content = f"""
<div class="row">
  <input id="search-input" type="text" name="q" value="{html.escape(q)}"
    placeholder="Search files…"
    hx-get="/projects/{s}/search"
    hx-target="#file-list"
    hx-trigger="keyup changed delay:250ms"
    hx-include="[name='q']"
  >
</div>
<div id="file-list">
{_file_rows(slug, q)}
</div>"""

    body = f"""
<h2><a href="/projects">Projects</a> / {s}</h2>
{tabs_html}
{tab_content}
"""
    return _base(slug, body, "projects")


@app.get("/projects/{slug}/search", response_class=HTMLResponse)
def project_files_search(slug: str, q: str = Query(default="")):
    return HTMLResponse(_file_rows(slug, q))


def _resolve_template_refs(template: str, project_id: int, env_prefix: str) -> str:
    """Render ${VAR} in a template as linked badges, resolving values from project vars."""
    # Build a lookup: key → row for all vars in this project
    proj_vars = query_all(
        "SELECT var_name, var_value, is_secret FROM environment_variables WHERE scope_type='project' AND scope_id=?",
        (project_id,)
    )
    lookup: dict = {}
    for v in proj_vars:
        name = v["var_name"] or ""
        # index by full name and bare key (after last colon)
        lookup[name] = v
        if ":" in name:
            lookup[name.rsplit(":", 1)[1]] = v

    def replace(m):
        ref = m.group(1)
        # Try env-scoped lookup first, then bare key
        candidates = [f"{env_prefix}:{ref}", ref]
        row = next((lookup[k] for k in candidates if k in lookup), None)
        if row:
            if row["is_secret"]:
                tip = "secret"
                color = "#e94560"
            else:
                val = row["var_value"] or ""
                tip = val[:80] + ("…" if len(val) > 80 else "")
                color = "#f0a030"
            ref_esc = html.escape(ref)
            tip_esc = html.escape(tip)
            return (
                f'<span title="{tip_esc}" style="display:inline-block;background:#2a1a08;'
                f'border:1px solid {color};color:{color};padding:0 0.3rem;border-radius:3px;'
                f'font-size:0.8rem;cursor:default">${{{ref_esc}}}</span>'
            )
        # Not found locally — might be in secrets, link to secrets page
        ref_esc = html.escape(ref)
        slug_for_link = query_one("SELECT slug FROM projects WHERE id=?", (project_id,))
        slug_esc = html.escape(slug_for_link["slug"] if slug_for_link else "")
        return (
            f'<a href="/secrets/{slug_esc}/default" title="May be in secrets" '
            f'style="display:inline-block;background:#2a0a1a;border:1px solid #e94560;'
            f'color:#e94560;padding:0 0.3rem;border-radius:3px;font-size:0.8rem">${{{ref_esc}}}</a>'
        )

    return re.sub(r'\$\{([^}]+)\}', replace, html.escape(template))


def _project_vars_tab(slug: str) -> str:
    proj = query_one("SELECT id FROM projects WHERE slug=?", (slug,))
    if not proj:
        return '<p class="muted">Project not found.</p>'
    project_id = proj["id"]

    rows = query_all("""
        SELECT id, var_name, var_value, value_type, template, is_secret, updated_at
        FROM environment_variables
        WHERE scope_type='project' AND scope_id=?
        ORDER BY var_name
    """, (project_id,))

    if not rows:
        return '<p class="muted">No vars for this project.</p>'

    # Parse name → (env_prefix, key)
    def parse(name):
        if ":" in name:
            idx = name.rfind(":")
            return name[:idx], name[idx + 1:]
        return "", name

    by_env: dict = defaultdict(list)
    for r in rows:
        ep, key = parse(r["var_name"] or "")
        by_env[ep].append({**dict(r), "env_prefix": ep, "key": key})

    s = html.escape(slug)
    sections = ""
    for ep in sorted(by_env.keys()):
        env_rows = by_env[ep]
        label = ep if ep else "(no env)"
        badge = (
            f'<span class="badge blue">{html.escape(label)}</span>'
            if ep else
            f'<span class="muted">{html.escape(label)}</span>'
        )

        # Build table rows
        tr_list = []
        for r in env_rows:
            if r["is_secret"]:
                val_cell = '<span class="muted">••••••</span> <span class="badge">secret</span>'
            elif r["value_type"] == "compound" and r["template"]:
                val_cell = f'<span style="font-size:0.82rem;word-break:break-all">{_resolve_template_refs(r["template"], project_id, ep)}</span>'
            else:
                val = r["var_value"] or ""
                val_cell = (
                    f'<span title="{html.escape(val)}" style="word-break:break-all">'
                    f'{html.escape(val[:80])}{"<span class=muted>…</span>" if len(val) > 80 else ""}</span>'
                )
            type_cls = " blue" if r["value_type"] != "static" else ""
            tr_list.append([
                f'<code>{html.escape(r["key"])}</code>',
                val_cell,
                f'<span class="badge{type_cls}">{html.escape(r["value_type"])}</span>',
                html.escape((r["updated_at"] or "")[:10]),
            ])

        # dotenv block for this env group
        dotenv_lines = []
        for r in env_rows:
            if r["is_secret"]:
                continue
            val = r["var_value"] or ""
            # Basic shell quoting: wrap in single quotes, escape inner single quotes
            safe_val = val.replace("'", "'\\''")
            dotenv_lines.append(f"{r['key']}='{safe_val}'")
        dotenv_text = "\n".join(dotenv_lines)
        copy_id = f"dotenv-{html.escape(ep or 'none')}"
        dotenv_block = ""
        if dotenv_lines:
            dotenv_block = f"""
<details style="margin-top:0.5rem">
  <summary style="cursor:pointer;color:#606080;font-size:0.78rem">📋 Copy as .env ({len(dotenv_lines)} vars)</summary>
  <div style="position:relative;margin-top:0.4rem">
    <button onclick="navigator.clipboard.writeText(document.getElementById('{copy_id}').innerText).then(()=>this.textContent='Copied!').catch(()=>{{}})" style="position:absolute;top:0.4rem;right:0.4rem;font-size:0.75rem">Copy</button>
    <pre id="{copy_id}" style="max-height:200px;overflow-y:auto;padding-right:4rem">{html.escape(dotenv_text)}</pre>
  </div>
</details>"""

        sections += f"""
<div style="margin-bottom:1.5rem">
  <div style="margin-bottom:0.4rem">{badge}</div>
  {_table(["Key", "Value", "Type", "Updated"], tr_list)}
  {dotenv_block}
</div>"""

    return sections


def _project_docs_tab(slug: str) -> str:
    proj = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
    if not proj:
        return '<p class="muted">Project not found.</p>'
    project_id = proj["id"]

    # Prefer readme_files (rich metadata) if available
    readme_docs = query_all("""
        SELECT rf.id, rf.title, rf.file_path, rf.category, rf.word_count,
               rf.section_count, rf.has_toc, rf.description, rf.last_scanned_at
        FROM readme_files rf
        WHERE rf.project_id = ?
        ORDER BY rf.category NULLS LAST, rf.title
    """, (project_id,))

    if readme_docs:
        # Fetch sections and topics
        doc_ids = [r["id"] for r in readme_docs]
        placeholders = ",".join("?" * len(doc_ids))
        sections_rows = query_all(
            f"SELECT readme_id, heading, level, anchor, line_number FROM readme_sections "
            f"WHERE readme_id IN ({placeholders}) ORDER BY readme_id, line_number",
            doc_ids,
        )
        topics_rows = query_all(
            f"SELECT readme_id, topic, relevance FROM readme_topics "
            f"WHERE readme_id IN ({placeholders}) ORDER BY readme_id, relevance DESC",
            doc_ids,
        )
        sections_by_doc: dict = defaultdict(list)
        for s in sections_rows:
            sections_by_doc[s["readme_id"]].append(s)
        topics_by_doc: dict = defaultdict(list)
        for t in topics_rows:
            topics_by_doc[t["readme_id"]].append(t)

        by_cat: dict = defaultdict(list)
        for r in readme_docs:
            by_cat[r["category"] or "uncategorized"].append(r)

        html_out = ""
        for cat in sorted(by_cat.keys()):
            docs = by_cat[cat]
            cat_label = cat.replace("-", " ").title()
            rows = []
            for r in docs:
                doc_secs = sections_by_doc.get(r["id"], [])
                doc_topics = topics_by_doc.get(r["id"], [])
                topic_badges = " ".join(
                    f'<span class="badge blue" style="font-size:0.68rem">{html.escape(t["topic"])}</span>'
                    for t in doc_topics[:4]
                )
                toc = '<span class="badge green" style="font-size:0.68rem">TOC</span>' if r["has_toc"] else ""
                title = r["title"] or r["file_path"] or ""
                title_cell = (
                    _file_link(slug, r["file_path"], title)
                    if r["file_path"] else html.escape(title)
                )
                desc = r["description"] or ""
                if desc:
                    title_cell += f'<br><span class="muted" style="font-size:0.75rem">{html.escape(desc[:100])}</span>'

                sec_detail = ""
                if doc_secs:
                    sec_trs = []
                    for sec in doc_secs:
                        indent = "&nbsp;" * (sec["level"] - 1) * 3
                        sec_trs.append([
                            f'<span class="muted" style="font-size:0.72rem">H{sec["level"]}</span>',
                            f'{indent}{html.escape(sec["heading"])}',
                            f'<span class="muted">{sec["line_number"]}</span>',
                        ])
                    sec_detail = (
                        f'<details><summary style="cursor:pointer;color:#606080;font-size:0.75rem">'
                        f'{len(doc_secs)} section{"s" if len(doc_secs) != 1 else ""}'
                        f'</summary><div style="margin-top:0.25rem">{_table(["Lvl","Heading","Line"], sec_trs)}</div></details>'
                    )

                rows.append([
                    title_cell,
                    f'{r["word_count"] or 0:,}',
                    sec_detail or f'<span class="muted">{r["section_count"] or 0}</span>',
                    f'{toc} {topic_badges}'.strip(),
                    html.escape((r["last_scanned_at"] or "")[:10]),
                ])
            html_out += (
                f'<div class="fsec" style="margin-top:1.25rem">'
                f'<h4 style="margin:0 0 0.4rem;color:#888">{html.escape(cat_label)}'
                f' <span style="font-weight:normal;font-size:0.8rem">({len(docs)})</span></h4>'
                f'{_table(["Title","Words","Sections","Topics","Scanned"], rows)}'
                f'</div>'
            )
        bar = _search_bar("proj-docs-wrap", "Filter docs…")
        return f'{bar}<div id="proj-docs-wrap">{html_out}</div>'

    # Fallback: project_files filtered to markdown
    md_files = query_all("""
        SELECT pf.file_path, pf.file_name, pf.description, pf.lines_of_code, pf.last_modified
        FROM project_files pf
        WHERE pf.project_id = ?
          AND (pf.file_path LIKE '%.md' OR pf.file_path LIKE '%.markdown'
               OR pf.file_path LIKE '%.rst' OR pf.file_path LIKE '%.txt')
        ORDER BY pf.file_path
    """, (project_id,))

    if not md_files:
        return '<p class="muted">No markdown docs found for this project.</p>'

    rows = []
    for f in md_files:
        name_cell = _file_link(slug, f["file_path"])
        desc = html.escape(f["description"] or "")
        if desc:
            name_cell += f'<br><span class="muted" style="font-size:0.75rem">{desc[:100]}</span>'
        rows.append([
            name_cell,
            f'<span class="muted">{f["lines_of_code"] or "—"}</span>',
            html.escape((f["last_modified"] or "")[:10]),
        ])

    bar = _search_bar("proj-docs-tbl", "Filter docs…")
    return f'{bar}{_table(["File", "Lines", "Modified"], rows, table_id="proj-docs-tbl")}'


def _file_rows(slug: str, q: str) -> str:
    if q:
        data = query_all("""
            SELECT file_path, type_name, lines_of_code
            FROM files_with_types_view
            WHERE project_slug = ? AND file_path LIKE ?
            ORDER BY file_path LIMIT 500
        """, (slug, f"%{q}%"))
    else:
        data = query_all("""
            SELECT file_path, type_name, lines_of_code
            FROM files_with_types_view
            WHERE project_slug = ?
            ORDER BY file_path LIMIT 500
        """, (slug,))

    rows = [
        [
            f'<a href="/projects/{html.escape(slug)}/file?path={html.escape(r["file_path"])}">{html.escape(r["file_path"])}</a>',
            html.escape(r["type_name"] or ""),
            f'{r["lines_of_code"] or 0:,}',
        ]
        for r in data
    ]
    count = f'<p class="muted" style="margin-bottom:0.5rem">{len(data)} file{"s" if len(data) != 1 else ""}</p>'
    return count + _table(["Path", "Type", "LOC"], rows, "No files found.")


@app.get("/projects/{slug}/file", response_class=HTMLResponse)
def project_file_view(slug: str, path: str = Query(...)):
    row = query_one("""
        SELECT cb.content_text
        FROM file_contents fc
        JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
        JOIN project_files pf ON fc.file_id = pf.id
        JOIN projects p ON pf.project_id = p.id
        WHERE p.slug = ? AND pf.file_path = ? AND fc.is_current = 1
    """, (slug, path))

    if row and row["content_text"]:
        lines = row["content_text"].split("\n")
        truncated = len(lines) > 1000
        content = html.escape("\n".join(lines[:1000]))
        note = '<p class="muted" style="margin-top:0.5rem">… truncated at 1000 lines</p>' if truncated else ""
    else:
        content = "(binary or empty file)"
        note = ""

    body = f"""
<h2>
  <a href="/projects">Projects</a> /
  <a href="/projects/{html.escape(slug)}">{html.escape(slug)}</a> /
  {html.escape(path)}
</h2>
<pre>{content}</pre>{note}
"""
    return _base(path, body, "projects")


# ── VCS ───────────────────────────────────────────────────────────────────────

@app.get("/vcs", response_class=HTMLResponse)
def vcs_index():
    projects = query_all("SELECT slug, name FROM projects ORDER BY slug")
    rows = [
        [
            f'<a href="/vcs/{html.escape(r["slug"])}">{html.escape(r["slug"])}</a>',
            html.escape(r["name"] or ""),
        ]
        for r in projects
    ]
    body = f"<h2>VCS — Select Project</h2>{_search_bar('vcs-list','Filter projects…')}{_table(['Slug', 'Name'], rows, 'No projects.', 'vcs-list')}"
    return _base("VCS", body, "vcs")


@app.get("/vcs/{slug}", response_class=HTMLResponse)
def vcs_project(slug: str):
    commits = query_all("""
        SELECT SUBSTR(commit_hash,1,8) AS short, branch_name, author, commit_message, commit_timestamp, commit_hash
        FROM vcs_commit_history_view
        WHERE project_slug = ?
        ORDER BY commit_timestamp DESC LIMIT 50
    """, (slug,))

    rows = [
        [
            f'<a href="/vcs/{html.escape(slug)}/commits/{r["commit_hash"]}">'
            f'<code>{html.escape(r["short"])}</code></a>',
            f'<span class="badge blue">{html.escape(r["branch_name"] or "")}</span>',
            html.escape(r["author"] or ""),
            html.escape((r["commit_message"] or "")[:72]),
            html.escape((r["commit_timestamp"] or "")[:10]),
        ]
        for r in commits
    ]

    actions = f"""
<div class="row">
  <a href="/vcs/{html.escape(slug)}/staging" class="btn">Staging Area</a>
  <a href="/vcs/{html.escape(slug)}/branches" class="btn">Branches</a>
</div>
"""
    body = f"""
<h2><a href="/vcs">VCS</a> / {html.escape(slug)}</h2>
{actions}
<h3>Recent Commits</h3>
{_search_bar("commits-tbl", "Filter by hash / author / message…", "360px")}
{_table(["Hash", "Branch", "Author", "Message", "Date"], rows, "No commits yet.", "commits-tbl")}
"""
    return _base(f"VCS: {slug}", body, "vcs")


@app.get("/vcs/{slug}/commits/{commit_hash}", response_class=HTMLResponse)
def vcs_commit_detail(slug: str, commit_hash: str):
    commit = query_one("""
        SELECT commit_hash, branch_name, author, commit_message, commit_timestamp
        FROM vcs_commit_history_view
        WHERE project_slug = ? AND commit_hash LIKE ?
        LIMIT 1
    """, (slug, f"{commit_hash}%"))

    if not commit:
        return _base("Not found", f'<p class="muted">Commit {html.escape(commit_hash)} not found.</p>', "vcs")

    files = query_all("""
        SELECT pf.file_path, fs.change_type
        FROM vcs_file_states fs
        JOIN project_files pf ON fs.file_id = pf.id
        WHERE fs.commit_id = (SELECT id FROM vcs_commits WHERE commit_hash LIKE ? LIMIT 1)
        ORDER BY pf.file_path
    """, (f"{commit_hash}%",))

    icons = {"added": "✦", "modified": "✎", "deleted": "✗"}
    file_rows = [
        [icons.get(r["change_type"], "?"), html.escape(r["file_path"]), html.escape(r["change_type"] or "")]
        for r in files
    ]

    # Generate diffs from vcs_file_states content
    import difflib
    diff_parts = []
    if files:
        commit_id = query_one(
            "SELECT id FROM vcs_commits WHERE commit_hash LIKE ? LIMIT 1",
            (f"{commit_hash}%",)
        )
        parent = query_one(
            "SELECT parent_commit_id FROM vcs_commit_parents WHERE commit_id = ? LIMIT 1",
            (commit_id["id"],)
        ) if commit_id else None

        for f in files:
            fp = f["file_path"]
            # Get this commit's content
            fs = query_one(
                """SELECT content_text FROM vcs_file_states
                   WHERE commit_id = ? AND file_id = (
                     SELECT id FROM project_files WHERE project_id = (
                       SELECT id FROM projects WHERE slug = ?
                     ) AND file_path = ? LIMIT 1
                   )""",
                (commit_id["id"], slug, fp)
            ) if commit_id else None

            new_text = (fs["content_text"] or "") if fs else ""

            if not new_text:
                continue

            # Get parent commit's content
            old_text = ""
            if parent:
                pfs = query_one(
                    """SELECT content_text FROM vcs_file_states
                       WHERE commit_id = ? AND file_id = (
                         SELECT id FROM project_files WHERE project_id = (
                           SELECT id FROM projects WHERE slug = ?
                         ) AND file_path = ? LIMIT 1
                       )""",
                    (parent["parent_commit_id"], slug, fp)
                )
                old_text = (pfs["content_text"] or "") if pfs else ""

            change = f["change_type"]
            if change == "added":
                old_lines, new_lines = [], new_text.splitlines(keepends=True)
            elif change == "deleted":
                old_lines, new_lines = new_text.splitlines(keepends=True), []
            else:
                old_lines = old_text.splitlines(keepends=True)
                new_lines = new_text.splitlines(keepends=True)

            udiff = difflib.unified_diff(old_lines, new_lines, fromfile=f"a/{fp}", tofile=f"b/{fp}", lineterm="")
            udiff_str = "\n".join(udiff)
            if udiff_str:
                diff_parts.append(udiff_str)

    if diff_parts:
        diff_html = f'<pre>{_colorize_diff(chr(10).join(diff_parts))}</pre>'
    elif not files:
        diff_html = '<p class="muted">No file change data recorded for this commit.</p>'
    else:
        diff_html = '<p class="muted">No diff content available (file snapshots not stored for this commit).</p>'

    body = f"""
<h2><a href="/vcs">VCS</a> / <a href="/vcs/{html.escape(slug)}">{html.escape(slug)}</a> / {html.escape(commit_hash[:8])}</h2>
<table style="margin-bottom:1rem">
  <tr><td class="muted" style="width:80px">Hash</td><td><code>{html.escape(commit["commit_hash"][:16])}</code></td></tr>
  <tr><td class="muted">Branch</td><td><span class="badge blue">{html.escape(commit["branch_name"] or "")}</span></td></tr>
  <tr><td class="muted">Author</td><td>{html.escape(commit["author"] or "")}</td></tr>
  <tr><td class="muted">Date</td><td>{html.escape(commit["commit_timestamp"] or "")}</td></tr>
  <tr><td class="muted">Message</td><td>{html.escape(commit["commit_message"] or "")}</td></tr>
</table>
<h3>Changed Files ({len(files)})</h3>
{_table(["", "Path", "State"], file_rows, "No files.")}
<h3>Diff</h3>
{diff_html}
"""
    return _base(commit_hash[:8], body, "vcs")


@app.get("/vcs/{slug}/branches", response_class=HTMLResponse)
def vcs_branches(slug: str):
    branches = query_all("""
        SELECT branch_name, is_default, total_commits, last_commit_time
        FROM vcs_branch_summary_view
        WHERE project_slug = ?
        ORDER BY is_default DESC, branch_name
    """, (slug,))

    rows = [
        [
            html.escape(r["branch_name"]),
            '<span class="badge green">default</span>' if r["is_default"] else "",
            str(r["total_commits"] or 0),
            html.escape((r["last_commit_time"] or "")[:10]),
        ]
        for r in branches
    ]

    body = f"""
<h2><a href="/vcs">VCS</a> / <a href="/vcs/{html.escape(slug)}">{html.escape(slug)}</a> / Branches</h2>
{_table(["Branch", "Default", "Commits", "Last Commit"], rows, "No branches.")}
"""
    return _base(f"Branches: {slug}", body, "vcs")


@app.get("/vcs/{slug}/staging", response_class=HTMLResponse)
def vcs_staging(slug: str, msg: str = Query(default="")):
    rc, status_out, status_err = _run("vcs", "status", slug, "--refresh")

    msg_html = ""
    if msg:
        ok = not msg.startswith("Error")
        msg_html = _msg(msg, ok=ok)

    commit_form = f"""
<hr class="sep">
<h3>Create Commit</h3>
<form hx-post="/vcs/{html.escape(slug)}/commit" hx-target="#commit-result" hx-swap="innerHTML">
  <div class="form-group">
    <label>Message</label>
    <input type="text" name="message" class="full" placeholder="Commit message" required>
  </div>
  <div class="form-group">
    <label>Author (optional)</label>
    <input type="text" name="author" class="full" placeholder="Name (auto-detect from git config)">
  </div>
  <div class="row">
    <button type="submit" class="primary">Commit Staged</button>
    <button type="submit" name="stage_all" value="1" class="success">Stage All &amp; Commit</button>
  </div>
</form>
<div id="commit-result">{msg_html}</div>
"""

    stage_actions = f"""
<div class="row" style="margin-bottom:0.5rem">
  <form hx-post="/vcs/{html.escape(slug)}/staging/add-all" hx-target="#staging-area" hx-swap="outerHTML">
    <button type="submit">Stage All</button>
  </form>
  <form hx-post="/vcs/{html.escape(slug)}/staging/reset-all" hx-target="#staging-area" hx-swap="outerHTML">
    <button type="submit">Unstage All</button>
  </form>
</div>
"""

    staging_html = _staging_area(slug)

    body = f"""
<h2><a href="/vcs">VCS</a> / <a href="/vcs/{html.escape(slug)}">{html.escape(slug)}</a> / Staging</h2>
{stage_actions}
<div id="staging-area">
{staging_html}
</div>
{commit_form}
"""
    return _base(f"Staging: {slug}", body, "vcs")


def _staging_area(slug: str) -> str:
    proj = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
    if not proj:
        return '<p class="muted">Project not found.</p>'

    branch = query_one("""
        SELECT COALESCE(p.active_branch_id, vb.id) as id FROM projects p LEFT JOIN vcs_branches vb ON vb.project_id = p.id AND vb.is_default = 1 WHERE p.id = ?
    """, (proj["id"],))
    if not branch:
        return '<p class="muted">No branch found.</p>'

    staged = query_all("""
        SELECT pf.file_path, ws.state, ws.file_id
        FROM vcs_working_state ws
        JOIN project_files pf ON ws.file_id = pf.id
        WHERE ws.project_id = ? AND ws.branch_id = ? AND ws.staged = 1
        ORDER BY pf.file_path
    """, (proj["id"], branch["id"]))

    unstaged = query_all("""
        SELECT pf.file_path, ws.state, ws.file_id
        FROM vcs_working_state ws
        JOIN project_files pf ON ws.file_id = pf.id
        WHERE ws.project_id = ? AND ws.branch_id = ? AND ws.staged = 0 AND ws.state != 'unmodified'
        ORDER BY pf.file_path
    """, (proj["id"], branch["id"]))

    icons = {"added": "✦", "modified": "✎", "deleted": "✗"}

    def _staged_rows():
        rows = []
        for r in staged:
            unstage_btn = (
                f'<form style="display:inline" hx-post="/vcs/{html.escape(slug)}/staging/unstage/{r["file_id"]}"'
                f' hx-target="#staging-area" hx-swap="outerHTML">'
                f'<button type="submit" style="padding:0.15rem 0.4rem;font-size:0.75rem">Unstage</button></form>'
            )
            rows.append([icons.get(r["state"], "?"), html.escape(r["file_path"]), html.escape(r["state"]), unstage_btn])
        return rows

    def _unstaged_rows():
        rows = []
        for r in unstaged:
            stage_btn = (
                f'<form style="display:inline" hx-post="/vcs/{html.escape(slug)}/staging/stage/{r["file_id"]}"'
                f' hx-target="#staging-area" hx-swap="outerHTML">'
                f'<button type="submit" style="padding:0.15rem 0.4rem;font-size:0.75rem">Stage</button></form>'
            )
            rows.append([icons.get(r["state"], "?"), html.escape(r["file_path"]), html.escape(r["state"]), stage_btn])
        return rows

    staged_table = _table(["", "Path", "State", ""], _staged_rows(), "Nothing staged.")
    unstaged_table = _table(["", "Path", "State", ""], _unstaged_rows(), "No changes.")

    return f"""
<h3>Staged ({len(staged)})</h3>
{staged_table}
<h3>Unstaged ({len(unstaged)})</h3>
{unstaged_table}
"""


@app.post("/vcs/{slug}/staging/stage/{file_id}", response_class=HTMLResponse)
def vcs_stage_file(slug: str, file_id: int):
    proj = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
    branch = query_one("SELECT COALESCE(p.active_branch_id, vb.id) as id FROM projects p LEFT JOIN vcs_branches vb ON vb.project_id = p.id AND vb.is_default = 1 WHERE p.id = ?", (proj["id"],))
    from db_utils import execute
    execute("UPDATE vcs_working_state SET staged = 1 WHERE file_id = ? AND project_id = ? AND branch_id = ?",
            (file_id, proj["id"], branch["id"]))
    return HTMLResponse(_staging_area(slug))


@app.post("/vcs/{slug}/staging/unstage/{file_id}", response_class=HTMLResponse)
def vcs_unstage_file(slug: str, file_id: int):
    proj = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
    branch = query_one("SELECT COALESCE(p.active_branch_id, vb.id) as id FROM projects p LEFT JOIN vcs_branches vb ON vb.project_id = p.id AND vb.is_default = 1 WHERE p.id = ?", (proj["id"],))
    from db_utils import execute
    execute("UPDATE vcs_working_state SET staged = 0 WHERE file_id = ? AND project_id = ? AND branch_id = ?",
            (file_id, proj["id"], branch["id"]))
    return HTMLResponse(_staging_area(slug))


@app.post("/vcs/{slug}/staging/add-all", response_class=HTMLResponse)
def vcs_stage_all(slug: str):
    _run("vcs", "add", "-p", slug, "--all")
    return HTMLResponse(_staging_area(slug))


@app.post("/vcs/{slug}/staging/reset-all", response_class=HTMLResponse)
def vcs_unstage_all(slug: str):
    _run("vcs", "reset", "-p", slug, "--all")
    return HTMLResponse(_staging_area(slug))


@app.post("/vcs/{slug}/commit", response_class=HTMLResponse)
def vcs_commit(slug: str, message: str = Form(...), author: str = Form(""), stage_all: str = Form("")):
    if stage_all:
        _run("vcs", "add", "-p", slug, "--all")
    cmd = ["vcs", "commit", "-p", slug, "-m", message]
    if author.strip():
        cmd += ["-a", author.strip()]
    rc, out, err = _run(*cmd)
    text = out or err or "Done"
    return HTMLResponse(_msg(text, ok=rc == 0))


# ── Secrets ───────────────────────────────────────────────────────────────────

@app.get("/secrets", response_class=HTMLResponse)
def secrets_list():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/env")


@app.get("/secrets/{slug}/{profile}", response_class=HTMLResponse)
def secret_detail(slug: str, profile: str):
    rc, out, err = _run("secret", "export", slug, "--profile", profile, "--format", "json")

    if rc == 0 and out:
        try:
            data = json.loads(out)
            keys = sorted(data.keys())
            rows = [[html.escape(k), '<span class="muted">••••••</span>'] for k in keys]
            table = _table(["Key", "Value"], rows, "No keys.")
            note = '<p class="muted" style="margin-top:0.5rem">Values hidden. Use CLI to view: <code>templedb env secret export ' + html.escape(slug) + '</code></p>'
            content = table + note
        except Exception:
            content = f'<pre>{html.escape(out)}</pre>'
    else:
        content = _msg(err or "Failed to load secret.", ok=False)

    body = f"""
<h2><a href="/secrets">Secrets</a> / {html.escape(slug)} / {html.escape(profile)}</h2>
{content}
"""
    return _base(f"Secret: {slug}", body, "secrets")


# ── Vars ──────────────────────────────────────────────────────────────────────

@app.get("/vars", response_class=HTMLResponse)
def vars_list(project: str = Query(""), env: str = Query(""), host: str = Query("")):
    rows = query_all("""
        SELECT ev.id, ev.scope_type, ev.scope_id,
               p.slug,
               ev.var_name, ev.var_value, ev.value_type, ev.template,
               ev.is_secret, ev.description, ev.updated_at,
               ev.hostname
        FROM environment_variables ev
        LEFT JOIN projects p ON p.id = ev.scope_id AND ev.scope_type = 'project'
        ORDER BY ev.hostname, p.slug NULLS LAST, ev.var_name
    """)

    def parse_name(var_name):
        name = var_name or ""
        if ":" in name:
            idx = name.rfind(":")
            return name[:idx], name[idx + 1:]
        return "", name

    parsed = [{**dict(r), **dict(zip(("env_prefix", "key"), parse_name(r["var_name"])))} for r in rows]

    # Collect unique values for dropdowns before filtering
    all_slugs = sorted({r["slug"] for r in parsed if r["slug"]})
    all_env_prefixes = sorted({r["env_prefix"] for r in parsed if r["env_prefix"]})
    all_hosts = sorted({r["hostname"] or "(untagged)" for r in parsed})

    if host:
        filter_host = None if host == "(untagged)" else host
        parsed = [r for r in parsed if (r["hostname"] or "(untagged)") == (host or "(untagged)")]
    if project:
        parsed = [r for r in parsed if (r["slug"] or "") == project]
    if env:
        parsed = [r for r in parsed if r["env_prefix"] == env]

    # Filter dropdowns
    def _select(name, options, current, placeholder):
        opts = f'<option value="">{placeholder}</option>'
        for val in options:
            sel = ' selected' if val == current else ''
            opts += f'<option value="{html.escape(val)}"{sel}>{html.escape(val)}</option>'
        style = 'style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;padding:0.3rem 0.5rem;border-radius:4px;font-family:monospace;font-size:0.85rem"'
        return f'<select name="{name}" onchange="this.form.submit()" {style}>{opts}</select>'

    filter_bar = f"""
<form method="get" action="/vars" class="row" style="margin-bottom:1rem">
  {_select("host", all_hosts, host, "All hosts")}
  {_select("project", all_slugs, project, "All projects")}
  {_select("env", all_env_prefixes, env, "All envs")}
  <span class="muted">{len(parsed)} var{"s" if len(parsed) != 1 else ""}</span>
</form>
{_search_bar("vars-content", "Fuzzy filter by key or value…", "340px")}
"""

    def _render_value(r):
        if r["is_secret"]:
            return '<span class="muted">••••••</span> <span class="badge">secret</span>'
        if r["value_type"] == "compound" and r["template"]:
            return f'<span style="font-size:0.78rem;word-break:break-all">{_highlight_template(r["template"])}</span>'
        val = r["var_value"] or ""
        if len(val) > 72:
            return f'<span title="{html.escape(val)}" style="word-break:break-all">{html.escape(val[:72])}<span class="muted">…</span></span>'
        return f'<span style="word-break:break-all">{html.escape(val)}</span>'

    def _type_badge(vtype):
        cls = " blue" if vtype != "static" else ""
        return f'<span class="badge{cls}">{html.escape(vtype)}</span>'

    def _host_badge(hostname):
        import socket
        h = hostname or "(untagged)"
        is_local = h == socket.gethostname()
        color = "#4a9a6a" if is_local else "#7a7a9a"
        return f'<span style="font-size:0.72rem;color:{color}">{html.escape(h)}</span>'

    def _make_table(var_rows):
        trs = [
            [f'<code>{html.escape(r["key"])}</code>', _render_value(r), _type_badge(r["value_type"]),
             _host_badge(r.get("hostname")), html.escape((r["updated_at"] or "")[:10])]
            for r in var_rows
        ]
        return _table(["Key", "Value", "Type", "Host", "Updated"], trs)

    by_project = defaultdict(list)
    for r in parsed:
        by_project[r["slug"] or "__global__"].append(r)

    sections_html = ""

    if "__global__" in by_project:
        global_rows = by_project["__global__"]
        trs = []
        for r in global_rows:
            key_cell = f'<code>{html.escape(r["key"])}</code>'
            if r["env_prefix"]:
                key_cell += f' <span class="muted" style="font-size:0.75rem">[{html.escape(r["env_prefix"])}]</span>'
            trs.append([key_cell, _render_value(r), _type_badge(r["value_type"]),
                        _host_badge(r.get("hostname")), html.escape((r["updated_at"] or "")[:10])])
        sections_html += f'<div class="fsec"><h3>Global</h3>{_table(["Key", "Value", "Type", "Host", "Updated"], trs)}</div>'

    for slug in sorted(k for k in by_project if k != "__global__"):
        proj_rows = by_project[slug]
        by_env = defaultdict(list)
        for r in proj_rows:
            by_env[r["env_prefix"]].append(r)

        proj_html = ""
        for ep in sorted(by_env.keys()):
            label = ep if ep else "(no env)"
            badge = (
                f'<span class="badge blue">{html.escape(label)}</span>'
                if ep else
                f'<span class="muted" style="font-size:0.8rem">{html.escape(label)}</span>'
            )
            proj_html += f'<div class="fsec" style="margin:0.75rem 0 0.4rem">{badge}{_make_table(by_env[ep])}</div>'

        link = f'<a href="/projects/{html.escape(slug)}">{html.escape(slug)}</a>'
        sections_html += f'<div class="fsec"><h3 style="margin-top:1.75rem">{link}</h3>{proj_html}</div>'

    body = f'<h2>Vars</h2>{filter_bar}<div id="vars-content">{sections_html}</div>'
    return _base("Vars", body, "vars")


@app.get("/vars", response_class=HTMLResponse)
def vars_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/env")


# ── Env (unified vars + secrets) ──────────────────────────────────────────────

@app.get("/env", response_class=HTMLResponse)
def env_list(project: str = Query(""), env: str = Query(""), kind: str = Query("")):
    # ── Gather environment_variables ──────────────────────────────────────────
    ev_rows = query_all("""
        SELECT ev.id, ev.scope_type, ev.scope_id, p.slug,
               ev.var_name, ev.var_value, ev.value_type, ev.template,
               ev.is_secret, ev.description, ev.updated_at
        FROM environment_variables ev
        LEFT JOIN projects p ON p.id = ev.scope_id AND ev.scope_type = 'project'
    """)

    def parse_name(name):
        name = name or ""
        if ":" in name:
            idx = name.rfind(":")
            return name[:idx], name[idx + 1:]
        return "", name

    unified = []
    for r in ev_rows:
        ep, key = parse_name(r["var_name"])
        vtype = "secret" if r["is_secret"] else r["value_type"]
        unified.append({
            "source": "var", "slug": r["slug"], "env_prefix": ep, "key": key,
            "value": r["var_value"], "value_type": vtype,
            "template": r["template"], "is_secret": bool(r["is_secret"]),
            "profile": None, "updated_at": r["updated_at"],
            "scope_type": r["scope_type"], "scope_id": r["scope_id"],
        })

    # ── Gather secret_blobs (encrypted — key name only) ───────────────────────
    sb_rows = query_all("""
        SELECT p.slug, psb.profile, sb.secret_name, sb.updated_at
        FROM project_secret_blobs psb
        JOIN projects p ON psb.project_id = p.id
        JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
    """)
    # Deduplicate: same project+secret_name may appear in multiple profiles
    seen_secrets: set = set()
    for r in sb_rows:
        dedup_key = (r["slug"], r["secret_name"])
        if dedup_key in seen_secrets:
            continue
        seen_secrets.add(dedup_key)
        unified.append({
            "source": "secret", "slug": r["slug"], "env_prefix": "",
            "key": r["secret_name"], "value": None, "value_type": "secret",
            "template": None, "is_secret": True,
            "profile": r["profile"], "updated_at": r["updated_at"],
            "scope_type": "project", "scope_id": None,
        })

    unified.sort(key=lambda r: (r["slug"] or "", r["env_prefix"], r["key"]))

    # ── Collect dropdown options BEFORE filtering ─────────────────────────────
    all_slugs = sorted({r["slug"] for r in unified if r["slug"]})
    all_envs = sorted({r["env_prefix"] for r in unified if r["env_prefix"]})

    # ── Apply filters ─────────────────────────────────────────────────────────
    if project:
        unified = [r for r in unified if (r["slug"] or "") == project]
    if env:
        unified = [r for r in unified if r["env_prefix"] == env]
    if kind:
        unified = [r for r in unified if r["value_type"] == kind]

    # ── Filter dropdowns ──────────────────────────────────────────────────────
    def _sel(name, options, cur, placeholder):
        opts = f'<option value="">{placeholder}</option>'
        for v in options:
            sel = " selected" if v == cur else ""
            opts += f'<option value="{html.escape(v)}"{sel}>{html.escape(v)}</option>'
        style = ('style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;'
                 'padding:0.3rem 0.5rem;border-radius:4px;font-family:monospace;font-size:0.85rem"')
        return f'<select name="{name}" onchange="this.form.submit()" {style}>{opts}</select>'

    kind_opts = [("", "All types"), ("static", "static"), ("compound", "compound"), ("secret", "secret")]
    kind_sel_html = '<select name="kind" onchange="this.form.submit()" style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;padding:0.3rem 0.5rem;border-radius:4px;font-family:monospace;font-size:0.85rem">'
    for v, label in kind_opts:
        sel = " selected" if v == kind else ""
        kind_sel_html += f'<option value="{v}"{sel}>{label}</option>'
    kind_sel_html += "</select>"

    n = len(unified)
    filter_bar = f"""
<form method="get" action="/env" class="row" style="margin-bottom:1rem">
  {_sel("project", all_slugs, project, "All projects")}
  {_sel("env", all_envs, env, "All envs")}
  {kind_sel_html}
  <span class="muted">{n} entr{"ies" if n != 1 else "y"}</span>
</form>
{_search_bar("env-content", "Fuzzy filter by key, value, or project…", "360px")}
"""

    # ── Value cell renderer ───────────────────────────────────────────────────
    def _val_cell(r):
        if r["source"] == "secret":
            return '<span class="muted" style="font-size:0.8rem">[age-encrypted]</span>'
        if r["is_secret"]:
            return '<span class="muted">••••••</span>'
        if r["value_type"] == "compound" and r["template"]:
            # Inline resolution: look up ${REF} in same project vars
            proj_id = r["scope_id"]
            if proj_id:
                proj_vars = query_all(
                    "SELECT var_name, var_value, is_secret FROM environment_variables WHERE scope_type='project' AND scope_id=?",
                    (proj_id,)
                )
            else:
                proj_vars = []
            lkp = {v["var_name"]: v for v in proj_vars}
            for v in proj_vars:
                n2 = v["var_name"] or ""
                if ":" in n2:
                    lkp[n2.rsplit(":", 1)[1]] = v

            def _ref(m):
                ref = m.group(1)
                row2 = lkp.get(f"{r['env_prefix']}:{ref}") or lkp.get(ref)
                if row2:
                    col = "#e94560" if row2["is_secret"] else "#f0a030"
                    tip = "secret" if row2["is_secret"] else html.escape((row2["var_value"] or "")[:60])
                    return (f'<span title="{tip}" style="background:#1a1000;border:1px solid {col};'
                            f'color:{col};padding:0 0.25rem;border-radius:3px;font-size:0.78rem">'
                            f'${{{html.escape(ref)}}}</span>')
                return (f'<span style="background:#1a0a1a;border:1px solid #606080;color:#a0a0c0;'
                        f'padding:0 0.25rem;border-radius:3px;font-size:0.78rem">'
                        f'${{{html.escape(ref)}}}</span>')

            rendered = re.sub(r'\$\{([^}]+)\}', _ref, html.escape(r["template"]))
            return f'<span style="font-size:0.8rem;word-break:break-all">{rendered}</span>'
        val = r["value"] or ""
        if len(val) > 72:
            return f'<span title="{html.escape(val)}" style="word-break:break-all">{html.escape(val[:72])}<span class="muted">…</span></span>'
        return f'<span style="word-break:break-all">{html.escape(val)}</span>'

    TYPE_BADGE = {
        "static":   '<span class="badge">static</span>',
        "compound": '<span class="badge blue">compound</span>',
        "secret":   '<span class="badge red">secret</span>',
    }

    # ── Group by project → env_prefix ────────────────────────────────────────
    by_project: dict = defaultdict(list)
    for r in unified:
        by_project[r["slug"] or "__global__"].append(r)

    sections_html = ""

    def _render_section(rows, group_key):
        trs = []
        for r in rows:
            src_badge = (' <span class="muted" style="font-size:0.72rem">blob</span>'
                         if r["source"] == "secret" else "")
            trs.append([
                f'<code>{html.escape(r["key"])}</code>{src_badge}',
                _val_cell(r),
                TYPE_BADGE.get(r["value_type"], f'<span class="badge">{html.escape(r["value_type"])}</span>'),
                html.escape((r["updated_at"] or "")[:10]),
            ])
        return _table(["Key", "Value", "Type", "Updated"], trs)

    def _dotenv_block(rows, group_key):
        lines = []
        for r in rows:
            if r["source"] == "secret" or r["is_secret"]:
                continue
            val = r["value"] or ""
            lines.append(f"{r['key']}='{val.replace(chr(39), chr(39)+chr(92)+chr(39)+chr(39))}'")
        if not lines:
            return ""
        cid = f"dotenv-{html.escape(group_key)}"
        return (f'<details style="margin-top:0.4rem"><summary style="cursor:pointer;color:#606080;font-size:0.78rem">'
                f'📋 Copy as .env ({len(lines)} vars)</summary>'
                f'<div style="position:relative;margin-top:0.3rem">'
                f'<button onclick="navigator.clipboard.writeText(document.getElementById(\'{cid}\').innerText)'
                f'.then(()=>this.textContent=\'Copied!\').catch(()=>{{}})" '
                f'style="position:absolute;top:0.4rem;right:0.4rem;font-size:0.75rem">Copy</button>'
                f'<pre id="{cid}" style="max-height:180px;overflow-y:auto;padding-right:4rem">'
                f'{html.escape(chr(10).join(lines))}</pre></div></details>')

    if "__global__" in by_project:
        g_rows = by_project["__global__"]
        by_env: dict = defaultdict(list)
        for r in g_rows:
            by_env[r["env_prefix"]].append(r)
        inner = ""
        for ep in sorted(by_env.keys()):
            lbl = ep if ep else "(global)"
            badge = f'<span class="badge blue">{html.escape(lbl)}</span>' if ep else f'<span class="muted">{html.escape(lbl)}</span>'
            inner += f'<div class="fsec" style="margin:0.6rem 0 0.3rem">{badge}{_render_section(by_env[ep], f"g-{ep}")}{_dotenv_block(by_env[ep], f"g-{ep}")}</div>'
        sections_html += f'<div class="fsec"><h3>Global</h3>{inner}</div>'

    for sl in sorted(k for k in by_project if k != "__global__"):
        proj_rows = by_project[sl]
        by_env2: dict = defaultdict(list)
        for r in proj_rows:
            by_env2[r["env_prefix"]].append(r)
        proj_inner = ""
        for ep in sorted(by_env2.keys()):
            lbl = ep if ep else "(no env)"
            badge = f'<span class="badge blue">{html.escape(lbl)}</span>' if ep else f'<span class="muted">{html.escape(lbl)}</span>'
            proj_inner += f'<div class="fsec" style="margin:0.6rem 0 0.3rem">{badge}{_render_section(by_env2[ep], f"{sl}-{ep}")}{_dotenv_block(by_env2[ep], f"{sl}-{ep}")}</div>'
        link = f'<a href="/projects/{html.escape(sl)}">{html.escape(sl)}</a>'
        sections_html += f'<div class="fsec"><h3 style="margin-top:1.5rem">{link}</h3>{proj_inner}</div>'

    cli_help = """
<details style="margin-top:1rem;border:1px solid #1e1e3a;border-radius:6px;padding:0.75rem">
<summary style="cursor:pointer;color:#808098;font-size:0.8rem">CLI commands for env vars &amp; secrets</summary>
<div style="margin-top:0.5rem">
<pre style="font-size:0.75rem">templedb env set &lt;project&gt; &lt;KEY&gt; &lt;value&gt;      # set env var
templedb env list &lt;project&gt;                    # list env vars
templedb env export &lt;project&gt; --format dotenv  # export as .env
templedb env secret set &lt;project&gt; &lt;KEY&gt;       # set encrypted secret (prompts)
templedb env secret list                        # list all secrets
templedb env secret get &lt;project&gt; &lt;KEY&gt;       # decrypt &amp; show
templedb env secret export &lt;project&gt; --format dotenv  # export decrypted</pre>
</div>
</details>
"""
    body = f'<h2>Env</h2>{filter_bar}<div id="env-content">{sections_html}</div>{cli_help}'
    return _base("Env", body, "env")


# ── Nix ───────────────────────────────────────────────────────────────────────

def _parse_flake_inputs(nodes: dict) -> list:
    """Extract meaningful input entries from flake.lock nodes dict."""
    import time
    now = time.time()
    result = []
    for name, node in nodes.items():
        if name == "root":
            continue
        locked = node.get("locked", {})
        rev = locked.get("rev", "")
        if not rev:
            continue  # skip alias nodes with no direct lock
        last_mod = locked.get("lastModified", 0)
        age_days = int((now - last_mod) / 86400) if last_mod else None
        owner = locked.get("owner", "")
        repo = locked.get("repo", "")
        ref = node.get("original", {}).get("ref", "")
        result.append({
            "name": name,
            "owner": owner,
            "repo": repo,
            "ref": ref,
            "rev": rev,
            "age_days": age_days,
        })
    return sorted(result, key=lambda r: r["name"])


def _flake_inputs_html(inputs: list, stale_days: int = 90) -> str:
    if not inputs:
        return '<p class="muted">No locked inputs.</p>'
    rows = []
    for r in inputs:
        age = r["age_days"]
        if age is None:
            age_cell = '<span class="muted">—</span>'
        elif age < 30:
            age_cell = f'<span style="color:#4a9a6a">{age}d</span>'
        elif age < stale_days:
            age_cell = f'<span style="color:#c8a040">{age}d</span>'
        else:
            age_cell = f'<span style="color:#e94560">{age}d ⚠</span>'

        origin = html.escape(f'{r["owner"]}/{r["repo"]}' if r["owner"] else r["name"])
        ref_cell = f' <span class="muted">({html.escape(r["ref"])})</span>' if r["ref"] else ""
        rows.append([
            f'<code>{html.escape(r["name"])}</code>',
            f'{origin}{ref_cell}',
            f'<code>{html.escape(r["rev"][:8])}</code>',
            age_cell,
        ])
    return _table(["Input", "Source", "Rev", "Age"], rows)


@app.get("/nix", response_class=HTMLResponse)
def nix_list():
    # ── Flake Configs (stored flake.nix text) ──────────────────────────────────
    configs = query_all("""
        SELECT nc.id, p.slug, nc.profile, nc.nix_text, nc.flake_text,
               nc.flake_lock, nc.build_command, nc.shell_command, nc.updated_at
        FROM nix_configs nc JOIN projects p ON nc.project_id = p.id
        ORDER BY p.slug
    """)

    config_sections = ""
    for c in configs:
        has_flake = bool(c["flake_text"] and c["flake_text"].strip())
        has_nix = bool(c["nix_text"] and c["nix_text"].strip() and c["nix_text"].strip() != "# nix config")

        # Parse lock inputs
        inputs_html = ""
        if c["flake_lock"]:
            try:
                lock = json.loads(c["flake_lock"])
                inputs = _parse_flake_inputs(lock.get("nodes", {}))
                stale = sum(1 for i in inputs if i["age_days"] is not None and i["age_days"] >= 90)
                stale_badge = f' <span style="color:#e94560">({stale} stale)</span>' if stale else ""
                inputs_html = f'<details style="margin:0.75rem 0"><summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">🔒 Lock inputs ({len(inputs)}){stale_badge}</summary><div style="margin-top:0.5rem">{_flake_inputs_html(inputs)}</div></details>'
            except Exception:
                inputs_html = '<p class="muted">Could not parse flake.lock</p>'

        flake_viewer = ""
        if has_flake:
            escaped = html.escape(c["flake_text"])
            flake_viewer = f'<details style="margin:0.75rem 0"><summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">📄 flake.nix</summary><pre style="margin-top:0.5rem;max-height:400px;overflow-y:auto">{escaped}</pre></details>'

        nix_viewer = ""
        if has_nix:
            escaped = html.escape(c["nix_text"])
            nix_viewer = f'<details style="margin:0.75rem 0"><summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">📄 shell.nix / default.nix</summary><pre style="margin-top:0.5rem;max-height:300px;overflow-y:auto">{escaped}</pre></details>'

        proj_link = f'<a href="/projects/{html.escape(c["slug"])}">{html.escape(c["slug"])}</a>'
        cmds = f'<code class="muted" style="font-size:0.78rem">{html.escape(c["build_command"] or "")}</code>'

        config_sections += f"""
<div style="border:1px solid #1e1e3a;border-radius:6px;padding:1rem;margin-bottom:1rem">
  <div class="row" style="margin-bottom:0.5rem">
    <strong>{proj_link}</strong>
    <span class="badge">{html.escape(c["profile"])}</span>
    {cmds}
    <span class="muted" style="margin-left:auto;font-size:0.78rem">{html.escape((c["updated_at"] or "")[:10])}</span>
  </div>
  {inputs_html}{flake_viewer}{nix_viewer}
</div>"""

    # ── Tracked Flakes (nix_flake_metadata) ────────────────────────────────────
    meta_rows = query_all("""
        SELECT nfm.id, p.slug, nfm.flake_inputs, nfm.nixpkgs_commit,
               nfm.packages, nfm.apps, nfm.devShells, nfm.nixosModules,
               nfm.homeManagerModules, nfm.last_build_check, nfm.last_build_succeeded,
               nfm.updated_at
        FROM nix_flake_metadata nfm JOIN projects p ON nfm.project_id = p.id
        ORDER BY p.slug
    """)

    def _output_badges(row):
        badges = []
        for field, label, color in [
            ("packages", "pkg", ""), ("apps", "app", " blue"),
            ("devShells", "shell", " green"), ("nixosModules", "nixos", ""),
            ("homeManagerModules", "hm", ""),
        ]:
            try:
                items = json.loads(row[field] or "[]")
                if items:
                    badges.append(f'<span class="badge{color}" title="{html.escape(str(items))}">{html.escape(label)}:{len(items)}</span>')
            except Exception:
                pass
        return " ".join(badges) or '<span class="muted">—</span>'

    meta_table_rows = []
    for r in meta_rows:
        stale_count = 0
        if r["flake_inputs"]:
            try:
                nodes = json.loads(r["flake_inputs"])
                inputs = _parse_flake_inputs(nodes)
                stale_count = sum(1 for i in inputs if i["age_days"] is not None and i["age_days"] >= 90)
            except Exception:
                pass
        stale_cell = f'<span style="color:#e94560">{stale_count} stale</span>' if stale_count else '<span style="color:#4a9a6a">fresh</span>'
        nixpkgs = html.escape((r["nixpkgs_commit"] or "")[:8])
        build_ok = r["last_build_succeeded"]
        build_cell = (
            '<span style="color:#4a9a6a">✓</span>' if build_ok == 1 else
            '<span style="color:#e94560">✗</span>' if build_ok == 0 else
            '<span class="muted">—</span>'
        )
        meta_table_rows.append([
            f'<a href="/projects/{html.escape(r["slug"])}">{html.escape(r["slug"])}</a>',
            f'<code>{nixpkgs}</code>' if nixpkgs else '<span class="muted">—</span>',
            _output_badges(r),
            stale_cell,
            build_cell,
            html.escape((r["updated_at"] or "")[:10]),
        ])

    # ── Managed Packages ───────────────────────────────────────────────────────
    pkgs = query_all("""
        SELECT nmp.id, p.slug, nmp.package_name, nmp.package_type, nmp.install_scope,
               nmp.flake_uri, nmp.version, nmp.enabled, nmp.notes
        FROM nixos_managed_packages nmp JOIN projects p ON nmp.project_id = p.id
        ORDER BY p.slug, nmp.package_name
    """)

    pkg_rows = []
    for r in pkgs:
        toggle_btn = (
            f'<button hx-post="/nix/packages/{r["id"]}/toggle" hx-target="closest tr" hx-swap="outerHTML" '
            f'style="padding:0.15rem 0.5rem;font-size:0.75rem" class="{"success" if r["enabled"] else ""}">'
            f'{"on" if r["enabled"] else "off"}</button>'
        )
        pkg_rows.append([
            f'<a href="/projects/{html.escape(r["slug"])}">{html.escape(r["slug"])}</a>',
            f'<code>{html.escape(r["package_name"])}</code>',
            f'<span class="badge">{html.escape(r["package_type"])}</span>',
            html.escape(r["install_scope"] or ""),
            f'<span class="muted" style="font-size:0.78rem">{html.escape(r["flake_uri"] or "")}</span>',
            toggle_btn,
        ])

    # ── Dev Environments ───────────────────────────────────────────────────────
    envs = query_all("""
        SELECT ne.id, p.slug, ne.env_name, ne.base_packages, ne.is_active, ne.description
        FROM nix_environments ne JOIN projects p ON ne.project_id = p.id
        ORDER BY p.slug, ne.env_name
    """)

    env_rows = []
    for r in envs:
        try:
            pkgs_list = json.loads(r["base_packages"] or "[]")
            pkgs_cell = ", ".join(html.escape(p) for p in pkgs_list[:6])
            if len(pkgs_list) > 6:
                pkgs_cell += f' <span class="muted">+{len(pkgs_list)-6}</span>'
        except Exception:
            pkgs_cell = '<span class="muted">—</span>'
        active_badge = '<span class="badge green">active</span>' if r["is_active"] else '<span class="muted">inactive</span>'
        env_rows.append([
            f'<a href="/projects/{html.escape(r["slug"])}">{html.escape(r["slug"])}</a>',
            f'<code>{html.escape(r["env_name"])}</code>',
            pkgs_cell,
            active_badge,
        ])

    # ── NixOS Pipeline Status ────────────────────────────────────────────────
    pipeline_html = ""
    try:
        nixos_slugs = query_all(
            "SELECT slug FROM projects WHERE project_type = 'nixos-config' ORDER BY slug"
        )
        if nixos_slugs:
            for ns in nixos_slugs:
                slug = ns["slug"]
                gen_row = query_one(
                    "SELECT value FROM system_config WHERE key = 'nixos.last_generated_at'"
                )
                last_gen = gen_row["value"] if gen_row else None

                proj_row = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
                last_rebuild = None
                if proj_row:
                    rb_row = query_one(
                        "SELECT deployed_at FROM system_deployments "
                        "WHERE project_id = ? AND exit_code = 0 "
                        "ORDER BY deployed_at DESC LIMIT 1",
                        (proj_row["id"],)
                    )
                    if rb_row:
                        last_rebuild = rb_row["deployed_at"]

                # Migration check
                mig_ok = True
                try:
                    from migrator import Migrator
                    from db_utils import DB_PATH
                    m = Migrator(DB_PATH)
                    mig_pending = sum(1 for s in m.status() if not s["applied"])
                    mig_ok = mig_pending == 0
                except Exception:
                    mig_pending = -1

                if last_gen is None:
                    live_st = '<span style="color:#808098">never generated</span>'
                elif last_rebuild is None:
                    live_st = '<span style="color:#e9a045">never rebuilt</span>'
                elif last_gen > last_rebuild:
                    live_st = '<span style="color:#e9a045">rebuild needed</span>'
                else:
                    live_st = '<span style="color:#4a9a6a">up to date</span>'

                mig_st = (
                    '<span style="color:#4a9a6a">OK</span>' if mig_ok
                    else f'<span style="color:#e94560">{mig_pending} pending</span>'
                )

                pipeline_html += f"""
<div style="border:1px solid #1e1e3a;border-radius:6px;padding:1rem;margin-bottom:1rem">
  <strong><a href="/projects/{html.escape(slug)}">{html.escape(slug)}</a></strong>
  <span class="badge">nixos-config</span>
  <table style="margin-top:0.5rem">
    <tr><td style="width:140px;color:#808098">Migrations</td><td>{mig_st}</td></tr>
    <tr><td style="color:#808098">Last generate</td><td>{html.escape((last_gen or 'never')[:16])}</td></tr>
    <tr><td style="color:#808098">Last rebuild</td><td>{html.escape((last_rebuild or 'never')[:16])}</td></tr>
    <tr><td style="color:#808098">Live system</td><td>{live_st}</td></tr>
  </table>
</div>"""
    except Exception:
        pass

    # ── Host Management ───────────────────────────────────────────────────────
    hosts_section = ""
    try:
        host_rows = query_all(
            "SELECT key, value FROM system_config WHERE key LIKE 'nixos.host.%' ORDER BY key"
        )
        active_row = query_one("SELECT value FROM system_config WHERE key = 'nixos.flake_output'")
        active_host = active_row["value"] if active_row else None

        if host_rows:
            h_rows = []
            for h in host_rows:
                hostname = h["key"].replace("nixos.host.", "")
                override_count = query_one(
                    "SELECT COUNT(*) as n FROM system_config WHERE key LIKE ?",
                    (f"{hostname}.%",)
                )
                count = override_count["n"] if override_count else 0
                active = '<span class="badge green">active</span>' if hostname == active_host else ""
                h_rows.append([
                    f'<strong>{html.escape(hostname)}</strong> {active}',
                    html.escape(h["value"]),
                    str(count),
                    f'<a href="/nix/host/{html.escape(hostname)}" style="font-size:0.78rem">view</a>',
                ])

            # Host select dropdown for project selector
            host_opts = "".join(
                f'<option value="{html.escape(h["key"].replace("nixos.host.", ""))}">'
                f'{html.escape(h["key"].replace("nixos.host.", ""))}</option>'
                for h in host_rows
            )

            hosts_section = f"""
<h3 style="margin-top:1.5rem">Hosts ({len(host_rows)})
  <span class="help-tip" style="position:relative">?<span class="tip">NixOS host configurations. Each host can have overrides (GPU, boot, network). Clone a host to create a similar config for a new machine.</span></span>
</h3>
{_table(["Host", "Config File", "Overrides", ""], h_rows)}
<details style="margin-top:0.5rem">
<summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">+ Clone host to new machine</summary>
<form hx-post="/nixos/host-clone" hx-swap="outerHTML" style="margin-top:0.5rem;display:flex;gap:0.5rem;align-items:center">
  <label style="font-size:0.8rem;color:#808098">From:</label>
  <select name="source" style="font-size:0.85rem;padding:0.25rem;background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;border-radius:4px">{host_opts}</select>
  <label style="font-size:0.8rem;color:#808098">To:</label>
  <input type="text" name="target" placeholder="new-hostname" style="width:150px" required>
  <button type="submit" class="sm primary">Clone</button>
</form>
</details>
"""
    except Exception:
        pass

    # ── Dotfiles ──────────────────────────────────────────────────────────────
    dotfiles_section = ""
    try:
        df_row = query_one("SELECT value FROM system_config WHERE key = 'nixos.dotfiles'")
        if df_row and df_row["value"]:
            manifest = json.loads(df_row["value"])
            if manifest:
                checkouts_dir = Path.home() / ".config" / "templedb" / "checkouts"
                df_rows = []
                for entry in manifest:
                    source_abs = checkouts_dir / entry["project"] / entry["source"]
                    target = Path(entry["target"]).expanduser()

                    if target.is_symlink() and target.resolve() == source_abs.resolve():
                        st = '<span style="color:#4a9a6a">linked</span>'
                    elif target.exists():
                        st = '<span style="color:#e9a045">conflict</span>'
                    elif not source_abs.exists():
                        st = '<span style="color:#e94560">no source</span>'
                    else:
                        st = '<span class="muted">not linked</span>'

                    df_rows.append([
                        f'<code>{html.escape(entry["source"])}</code>',
                        f'<span class="badge">{html.escape(entry["project"])}</span>',
                        f'<code class="muted" style="font-size:0.78rem">{html.escape(entry["target"])}</code>',
                        st,
                    ])
                dotfiles_section = f"""
<h3 style="margin-top:1.5rem">Dotfiles ({len(manifest)})</h3>
{_table(["Source", "Project", "Target", "Status"], df_rows)}
<p class="muted" style="font-size:0.8rem">Apply: <code>templedb nixos dotfiles-apply [--force]</code></p>
"""
    except Exception:
        pass

    body = f"""
<h2>Nix</h2>

{"<h3>NixOS Pipeline</h3>" + pipeline_html if pipeline_html else ""}
{hosts_section}

<h3 style="margin-top:1.5rem">Flake Configs</h3>
{config_sections or '<p class="muted">No flake configs stored.</p>'}
<h3 style="margin-top:1.5rem">Tracked Flakes</h3>
{_search_bar("nix-flakes-tbl", "Filter by project or input…")}
{_table(["Project", "nixpkgs", "Outputs", "Inputs", "Build", "Updated"], meta_table_rows, "No tracked flake metadata.", "nix-flakes-tbl")}
<h3 style="margin-top:1.5rem">Managed Packages</h3>
{_search_bar("nix-pkgs-tbl", "Filter by project or package…")}
{_table(["Project", "Package", "Type", "Scope", "Flake URI", "Enabled"], pkg_rows, "No managed packages.", "nix-pkgs-tbl")}
{dotfiles_section}
<h3 style="margin-top:1.5rem">Dev Environments</h3>
{_search_bar("nix-envs-tbl", "Filter by project or env…")}
{_table(["Project", "Env", "Base Packages", "Status"], env_rows, "No dev environments.", "nix-envs-tbl")}
"""
    return _base("Nix", body, "nix")


@app.post("/nix/packages/{pkg_id}/toggle", response_class=HTMLResponse)
def nix_package_toggle(pkg_id: int):
    row = query_one("SELECT * FROM nixos_managed_packages WHERE id = ?", (pkg_id,))
    if not row:
        return HTMLResponse('<tr><td colspan="6" class="muted">Not found</td></tr>')
    new_val = 0 if row["enabled"] else 1
    execute("UPDATE nixos_managed_packages SET enabled = ?, updated_at = datetime('now') WHERE id = ?", (new_val, pkg_id))
    proj = query_one("SELECT slug FROM projects WHERE id = ?", (row["project_id"],))
    slug = proj["slug"] if proj else ""
    toggle_btn = (
        f'<button hx-post="/nix/packages/{pkg_id}/toggle" hx-target="closest tr" hx-swap="outerHTML" '
        f'style="padding:0.15rem 0.5rem;font-size:0.75rem" class="{"success" if new_val else ""}">'
        f'{"on" if new_val else "off"}</button>'
    )
    return HTMLResponse(f"""<tr>
<td><a href="/projects/{html.escape(slug)}">{html.escape(slug)}</a></td>
<td><code>{html.escape(row["package_name"])}</code></td>
<td><span class="badge">{html.escape(row["package_type"])}</span></td>
<td>{html.escape(row["install_scope"] or "")}</td>
<td><span class="muted" style="font-size:0.78rem">{html.escape(row["flake_uri"] or "")}</span></td>
<td>{toggle_btn}</td>
</tr>""")


# ── Nix Host Detail ───────────────────────────────────────────────────────────

@app.get("/nix/host/{hostname}", response_class=HTMLResponse)
def nix_host_detail(hostname: str):
    """Detail view for a NixOS host — config keys, overrides, and services."""
    host_row = query_one(
        "SELECT key, value FROM system_config WHERE key = ?",
        (f"nixos.host.{hostname}",)
    )
    if not host_row:
        return _base("Host Not Found",
                      f'<p class="muted">No host config found for <strong>{html.escape(hostname)}</strong></p>', "nix")

    config_file = host_row["value"]

    # Host-scoped overrides (hostname.key = value)
    overrides = query_all(
        "SELECT key, value FROM system_config WHERE key LIKE ? ORDER BY key",
        (f"{hostname}.%",)
    )
    override_rows = [
        [f'<code>{html.escape(o["key"])}</code>',
         f'<span class="muted" style="font-size:0.78rem">{html.escape((o["value"] or "")[:120])}</span>']
        for o in overrides
    ]
    override_table = _table(["Key", "Value"], override_rows, "No host-specific overrides.")

    # Global NixOS config keys that apply to this host
    global_keys = query_all(
        """SELECT key, value FROM system_config
           WHERE key LIKE 'nixos.%' AND key NOT LIKE 'nixos.host.%'
           ORDER BY key""",
    )
    # Group by prefix
    groups = defaultdict(list)
    for k in global_keys:
        parts = k["key"].split(".", 2)
        prefix = parts[1] if len(parts) > 1 else "other"
        groups[prefix].append(k)

    config_sections = ""
    for prefix in sorted(groups.keys()):
        items = groups[prefix]
        rows = [
            [f'<code style="font-size:0.78rem">{html.escape(i["key"])}</code>',
             f'<span class="muted" style="font-size:0.78rem">{html.escape((i["value"] or "")[:100])}</span>']
            for i in items[:30]  # cap display
        ]
        more = f' <span class="muted">... +{len(items)-30} more</span>' if len(items) > 30 else ""
        config_sections += f"""
<details style="margin-bottom:0.5rem">
  <summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">
    nixos.{html.escape(prefix)}.* <span class="badge">{len(items)}</span>{more}
  </summary>
  <div style="margin-top:0.3rem">{_table(["Key", "Value"], rows)}</div>
</details>"""

    # Services configured for this host
    services = query_all(
        """SELECT key, value FROM system_config
           WHERE (key LIKE 'nixos.service.%' OR key LIKE 'nixos.attr.services.%')
           ORDER BY key"""
    )
    svc_rows = []
    for s in services:
        name = s["key"].replace("nixos.service.user.", "").replace("nixos.service.", "").replace("nixos.attr.services.", "").replace(".enable", "")
        svc_rows.append([
            f'<code>{html.escape(name)}</code>',
            f'<code class="muted" style="font-size:0.78rem">{html.escape(s["key"])}</code>',
            f'<span class="muted">{html.escape((s["value"] or "")[:60])}</span>',
        ])
    svc_table = _table(["Service", "Config Key", "Value"], svc_rows, "No services configured.") if svc_rows else ""

    body = f"""
<h2><a href="/nix" style="color:#808098">Nix</a> / {html.escape(hostname)}</h2>
<p class="muted" style="margin-bottom:1rem">Config file: <code>{html.escape(config_file)}</code></p>

<h3>Host Overrides ({len(overrides)})</h3>
{override_table}

<h3 style="margin-top:1.5rem">NixOS Config ({len(global_keys)} keys)</h3>
{config_sections}

<h3 style="margin-top:1.5rem">Configured Services</h3>
{svc_table}

<div style="margin-top:1.5rem;display:flex;gap:0.5rem">
  <a href="/systemd?scope=system" class="btn" style="font-size:0.78rem">View System Units</a>
  <a href="/systemd?scope=user" class="btn" style="font-size:0.78rem">View User Units</a>
  <button hx-post="/nixos/generate-all" hx-swap="outerHTML" style="font-size:0.78rem">Generate NixOS Config</button>
</div>
"""
    return _base(f"Host: {hostname}", body, "nix")


# ── Deploy ────────────────────────────────────────────────────────────────────

def _status_badge(status: str) -> str:
    colors = {"success": " green", "failed": " red", "pass": " green", "fail": " red"}
    cls = colors.get((status or "").lower(), "")
    return f'<span class="badge{cls}">{html.escape(status or "—")}</span>'


@app.get("/deploy", response_class=HTMLResponse)
def deploy_list():
    # ── Deployment Scripts ─────────────────────────────────────────────────────
    scripts = query_all("""
        SELECT ds.id, ds.project_slug, ds.script_path, ds.description, ds.enabled, ds.updated_at
        FROM deployment_scripts ds ORDER BY ds.project_slug
    """)
    script_rows = []
    for s in scripts:
        toggle = (
            f'<button hx-post="/deploy/scripts/{s["id"]}/toggle" hx-target="closest tr" hx-swap="outerHTML" '
            f'style="padding:0.15rem 0.5rem;font-size:0.75rem" class="{"success" if s["enabled"] else ""}">'
            f'{"on" if s["enabled"] else "off"}</button>'
        )
        script_rows.append([
            f'<a href="/projects/{html.escape(s["project_slug"])}">{html.escape(s["project_slug"])}</a>',
            _file_link(s["project_slug"], s["script_path"]),
            html.escape(s["description"] or ""),
            toggle,
            html.escape((s["updated_at"] or "")[:10]),
        ])

    # ── Deployment Targets ─────────────────────────────────────────────────────
    targets = query_all("""
        SELECT dt.id, p.slug, dt.target_name, dt.target_type, dt.host,
               dt.provider, dt.requires_vpn, dt.access_url
        FROM deployment_targets dt JOIN projects p ON dt.project_id = p.id
        ORDER BY p.slug, dt.target_name
    """)
    target_rows = []
    for t in targets:
        url_cell = (
            f'<a href="{html.escape(t["access_url"])}" target="_blank" style="font-size:0.78rem">'
            f'{html.escape(t["access_url"][:48])}</a>'
            if t["access_url"] else '<span class="muted">—</span>'
        )
        vpn = '<span class="badge" style="color:#c8a040">VPN</span>' if t["requires_vpn"] else ""
        target_rows.append([
            f'<a href="/projects/{html.escape(t["slug"])}">{html.escape(t["slug"])}</a>',
            f'<strong>{html.escape(t["target_name"])}</strong>',
            f'<span class="badge">{html.escape(t["target_type"] or "")}</span>',
            html.escape(t["host"] or ""),
            html.escape(t["provider"] or ""),
            url_cell,
            vpn,
        ])

    # ── Deployment History ─────────────────────────────────────────────────────
    history = query_all("""
        SELECT dh.id, p.slug, dh.target_name, dh.deployment_type, dh.status,
               dh.started_at, dh.completed_at, dh.duration_ms,
               dh.deployed_by, dh.deployment_method, dh.error_message,
               SUBSTR(dh.commit_hash, 1, 8) AS short_hash,
               dh.branch_name, dh.triggered_by
        FROM deployment_history dh JOIN projects p ON dh.project_id = p.id
        ORDER BY dh.started_at DESC LIMIT 25
    """)

    hist_rows = []
    for d in history:
        dur = f'{d["duration_ms"] // 1000}s' if d["duration_ms"] else "—"
        checks = query_all(
            "SELECT check_name, check_type, status, response_time_ms, error_message FROM deployment_health_checks WHERE deployment_id=? ORDER BY id",
            (d["id"],)
        )
        checks_html = ""
        if checks:
            check_rows = [
                [html.escape(c["check_name"]), html.escape(c["check_type"]), _status_badge(c["status"]),
                 f'{c["response_time_ms"]}ms' if c["response_time_ms"] else "—",
                 html.escape(c["error_message"] or "")]
                for c in checks
            ]
            checks_html = (
                f'<details style="margin-top:0.3rem"><summary style="cursor:pointer;font-size:0.75rem;color:#606080">'
                f'health checks ({len(checks)})</summary><div style="margin-top:0.3rem">'
                f'{_table(["Check", "Type", "Status", "ms", "Error"], check_rows)}</div></details>'
            )
        err_cell = html.escape((d["error_message"] or "")[:60])
        if d["error_message"] and len(d["error_message"]) > 60:
            err_cell = f'<span title="{html.escape(d["error_message"])}">{err_cell}…</span>'

        detail_cell = f'{err_cell}{checks_html}'
        # Triggered-by badge
        triggered = d.get("triggered_by") or "manual"
        trigger_badge = ""
        if triggered == "auto-commit":
            trigger_badge = '<span class="badge green" style="font-size:0.68rem">auto</span> '
        elif triggered == "rollback":
            trigger_badge = '<span class="badge" style="font-size:0.68rem;color:#e9a040">rollback</span> '
        # Branch
        branch_html = ""
        if d.get("branch_name"):
            branch_html = f'<span class="badge blue" style="font-size:0.68rem">{html.escape(d["branch_name"])}</span> '
        commit_cell = f'{branch_html}{trigger_badge}<code class="muted" style="font-size:0.75rem">{html.escape(d["short_hash"] or "")}</code>'

        hist_rows.append([
            f'<a href="/projects/{html.escape(d["slug"])}">{html.escape(d["slug"])}</a>',
            html.escape(d["target_name"] or ""),
            _status_badge(d["status"]),
            commit_cell,
            html.escape(d["deployed_by"] or ""),
            html.escape((d["started_at"] or "")[:16]),
            html.escape(dur),
            detail_cell,
        ])

    # ── NixOS System Switches ──────────────────────────────────────────────────
    sys_deps = query_all("""
        SELECT sd.id, p.slug, sd.deployed_at, sd.command, sd.exit_code,
               sd.is_active, sd.checkout_path, sd.output
        FROM system_deployments sd JOIN projects p ON sd.project_id = p.id
        ORDER BY sd.deployed_at DESC LIMIT 15
    """)
    nixos_rows = []
    for sd in sys_deps:
        ok = sd["exit_code"] == 0
        status_cell = '<span style="color:#4a9a6a">✓ ok</span>' if ok else f'<span style="color:#e94560">✗ exit {sd["exit_code"]}</span>'
        active_badge = '<span class="badge green">active</span>' if sd["is_active"] else ""
        out_lines = (sd["output"] or "").strip().split("\n")
        last_line = html.escape(out_lines[-1][:80]) if out_lines else ""
        output_block = (
            f'<details style="margin-top:0.2rem"><summary style="cursor:pointer;font-size:0.75rem;color:#606080">'
            f'build output ({len(out_lines)} lines)</summary>'
            f'<pre style="max-height:200px;overflow-y:auto;font-size:0.75rem;margin-top:0.3rem">{html.escape((sd["output"] or "")[-3000:])}</pre></details>'
        ) if sd["output"] else ""
        nixos_rows.append([
            f'<a href="/projects/{html.escape(sd["slug"])}">{html.escape(sd["slug"])}</a>',
            html.escape((sd["deployed_at"] or "")[:16]),
            f'<code>{html.escape(sd["command"] or "")}</code>',
            f'{status_cell} {active_badge}',
            f'<span class="muted" style="font-size:0.78rem">{last_line}</span>{output_block}',
        ])

    # ── NixOS Service Definitions ──────────────────────────────────────────────
    services = query_all("""
        SELECT nsm.id, p.slug, nsm.service_name, nsm.service_description,
               nsm.systemd_service_name, nsm.systemd_after, nsm.opens_ports,
               nsm.state_directory_path, nsm.dynamic_user, nsm.private_tmp
        FROM nix_service_metadata nsm JOIN projects p ON nsm.project_id = p.id
        ORDER BY p.slug, nsm.service_name
    """)
    svc_rows = []
    for s in services:
        after = ""
        try:
            after_list = json.loads(s["systemd_after"] or "[]")
            after = ", ".join(after_list[:3])
        except Exception:
            pass
        flags = []
        if s["dynamic_user"]: flags.append("dynamic-user")
        if s["private_tmp"]: flags.append("private-tmp")
        flag_html = " ".join(f'<span class="badge">{f}</span>' for f in flags) or '<span class="muted">—</span>'
        svc_rows.append([
            f'<a href="/projects/{html.escape(s["slug"])}">{html.escape(s["slug"])}</a>',
            f'<code>{html.escape(s["service_name"])}</code>',
            f'<code class="muted" style="font-size:0.78rem">{html.escape(s["systemd_service_name"] or "")}</code>',
            html.escape(s["service_description"] or ""),
            html.escape(after),
            flag_html,
        ])

    # ── Local Services (fleet) ───────────────────────────────────────────────
    local_svcs = query_all("""
        SELECT nls.id, p.slug, nls.service_name, nls.service_type,
               nls.port_mapping, nls.status, nls.description,
               nls.health_check_url, nls.last_started_at, nls.failure_reason,
               nls.nix_package
        FROM fleet_local_services nls
        JOIN fleet_networks nn ON nls.network_id = nn.id
        JOIN projects p ON nn.project_id = p.id
        ORDER BY p.slug, nls.start_order
    """)
    local_rows = []
    for s in local_svcs:
        status_colors = {"running": " green", "failed": " red", "stopped": "", "new": ""}
        cls = status_colors.get(s["status"] or "", "")
        health_cell = (
            f'<a href="{html.escape(s["health_check_url"])}" target="_blank" class="muted" style="font-size:0.75rem">'
            f'{html.escape(s["health_check_url"])}</a>'
            if s["health_check_url"] else '<span class="muted">—</span>'
        )
        fail_note = ""
        if s["failure_reason"]:
            fail_note = f'<div class="muted" style="font-size:0.75rem;margin-top:0.2rem" title="{html.escape(s["failure_reason"])}">{html.escape(s["failure_reason"][:60])}…</div>'
        local_rows.append([
            f'<a href="/projects/{html.escape(s["slug"])}">{html.escape(s["slug"])}</a>',
            f'<code>{html.escape(s["service_name"])}</code>',
            f'<span class="badge{cls}">{html.escape(s["status"] or "unknown")}</span>',
            html.escape(s["port_mapping"] or ""),
            f'<code class="muted" style="font-size:0.75rem">{html.escape(s["nix_package"] or "")}</code>',
            health_cell,
            f'{html.escape((s["last_started_at"] or "")[:10])}{fail_note}',
        ])

    # ── Auto-Deploy Triggers ──────────────────────────────────────────────────
    triggers = query_all("""
        SELECT dt.id, p.slug, dt.branch_pattern, dt.target_name, dt.enabled,
               dt.auto_rollback, dt.require_health_check, dt.updated_at
        FROM deployment_triggers dt JOIN projects p ON dt.project_id = p.id
        ORDER BY p.slug, dt.branch_pattern
    """)
    trigger_rows = []
    for t in triggers:
        toggle = (
            f'<button hx-post="/deploy/triggers/{t["id"]}/toggle" hx-target="closest tr" hx-swap="outerHTML" '
            f'style="padding:0.15rem 0.5rem;font-size:0.75rem" class="{"success" if t["enabled"] else ""}">'
            f'{"on" if t["enabled"] else "off"}</button>'
        )
        flags = []
        if t["auto_rollback"]: flags.append("auto-rollback")
        if t["require_health_check"]: flags.append("health-check")
        flag_html = " ".join(f'<span class="badge">{f}</span>' for f in flags) or ""
        trigger_rows.append([
            f'<a href="/projects/{html.escape(t["slug"])}">{html.escape(t["slug"])}</a>',
            f'<code>{html.escape(t["branch_pattern"])}</code>',
            f'<strong>{html.escape(t["target_name"])}</strong>',
            toggle,
            flag_html,
        ])

    # ── Notifications ──────────────────────────────────────────────────────────
    notifications = query_all("""
        SELECT dn.id, dn.event, dn.notification_type, dn.config, dn.enabled,
               p.slug as project_slug
        FROM deployment_notifications dn
        LEFT JOIN projects p ON dn.project_id = p.id
        ORDER BY dn.event
    """)
    notif_rows = []
    for n in notifications:
        try:
            config = json.loads(n["config"])
            dest = config.get("url") or config.get("command", "")
        except Exception:
            dest = n["config"]
        scope = html.escape(n["project_slug"] or "global")
        notif_rows.append([
            f'<code>{html.escape(n["event"])}</code>',
            f'<span class="badge">{html.escape(n["notification_type"])}</span>',
            f'<span class="muted" style="font-size:0.78rem">{html.escape(str(dest)[:60])}</span>',
            scope,
            '<span style="color:#4a9a6a">on</span>' if n["enabled"] else '<span class="muted">off</span>',
        ])

    # ── Deployment Cache Stats ─────────────────────────────────────────────────
    cache_stats = query_all("""
        SELECT p.slug, dc.target, dc.content_hash, dc.use_count, dc.last_used_at,
               SUBSTR(dc.files_hash, 1, 8) AS short_files,
               SUBSTR(dc.deps_hash, 1, 8) AS short_deps
        FROM deployment_cache dc
        JOIN projects p ON dc.project_id = p.id
        ORDER BY dc.last_used_at DESC LIMIT 20
    """)
    cache_rows = []
    for c in cache_stats:
        cache_rows.append([
            f'<a href="/projects/{html.escape(c["slug"])}">{html.escape(c["slug"])}</a>',
            html.escape(c["target"] or ""),
            f'<code class="muted" style="font-size:0.72rem">{html.escape((c["content_hash"] or "")[:12])}</code>',
            f'<code class="muted" style="font-size:0.72rem">{html.escape(c["short_files"] or "")}</code>',
            str(c["use_count"] or 0),
            html.escape((c["last_used_at"] or "")[:16]),
        ])

    # ── Fleet Networks & Machines ────────────────────────────────────────────
    fleet_networks = query_all("""
        SELECT n.id, n.network_name, n.network_uuid, n.is_active,
               p.slug AS project_slug, n.flake_uri, n.config_file_path,
               COUNT(DISTINCT m.id) AS machine_count,
               COUNT(DISTINCT CASE WHEN m.deployment_status = 'deployed' THEN m.id END) AS deployed_count,
               MAX(d.started_at) AS last_deploy_at
        FROM fleet_networks n
        JOIN projects p ON n.project_id = p.id
        LEFT JOIN fleet_machines m ON n.id = m.network_id
        LEFT JOIN fleet_deployments d ON n.id = d.network_id
        WHERE n.is_active = 1
        GROUP BY n.id
        ORDER BY n.network_name
    """)
    fleet_net_rows = []
    for fn in fleet_networks:
        deploy_ratio = f'{fn["deployed_count"]}/{fn["machine_count"]}'
        last = html.escape((fn["last_deploy_at"] or "never")[:16])
        fleet_net_rows.append([
            f'<a href="/projects/{html.escape(fn["project_slug"])}">{html.escape(fn["project_slug"])}</a>',
            f'<strong>{html.escape(fn["network_name"])}</strong>',
            f'<code class="muted" style="font-size:0.72rem">{html.escape(fn["network_uuid"][:8])}</code>',
            deploy_ratio,
            last,
            f'<code class="muted" style="font-size:0.72rem">{html.escape(fn["flake_uri"] or fn["config_file_path"] or "")}</code>',
        ])

    fleet_machines = query_all("""
        SELECT m.id, m.machine_name, m.target_host, m.target_user, m.target_port,
               m.deployment_status, m.health_status, m.nixos_version,
               m.last_deployed_at, m.machine_config,
               n.network_name, p.slug AS project_slug
        FROM fleet_machines m
        JOIN fleet_networks n ON m.network_id = n.id
        JOIN projects p ON n.project_id = p.id
        WHERE n.is_active = 1
        ORDER BY n.network_name, m.machine_name
    """)
    fleet_machine_rows = []
    for fm in fleet_machines:
        status_cls = {"deployed": " green", "failed": " red", "new": "", "deploying": ""}
        health_cls = {"healthy": " green", "unhealthy": " red", "unreachable": " red", "reverting": " red"}
        try:
            config = json.loads(fm["machine_config"] or "{}")
        except Exception:
            config = {}
        tags = config.get("tags", [])
        tag_html = " ".join(f'<span class="badge">{html.escape(t)}</span>' for t in tags) if tags else ""
        watchdog_html = ""
        if fm["health_status"] == "reverting":
            watchdog_html = ' <span class="badge" style="color:#c8a040">watchdog</span>'

        fleet_machine_rows.append([
            html.escape(fm["network_name"]),
            f'<strong>{html.escape(fm["machine_name"])}</strong>',
            f'{html.escape(fm["target_user"] or "root")}@{html.escape(fm["target_host"] or "?")}',
            f'<span class="{status_cls.get(fm["deployment_status"] or "", "")}">'
            f'{html.escape(fm["deployment_status"] or "new")}</span>{watchdog_html}',
            f'<span class="{health_cls.get(fm["health_status"] or "", "")}">'
            f'{html.escape(fm["health_status"] or "unknown")}</span>',
            html.escape(fm["nixos_version"] or "—"),
            tag_html,
            html.escape((fm["last_deployed_at"] or "never")[:16]),
        ])

    fleet_deploys = query_all("""
        SELECT d.deployment_uuid, d.operation, d.status,
               d.started_at, d.duration_seconds, d.triggered_by,
               n.network_name, p.slug AS project_slug,
               COUNT(md.id) AS total_machines,
               COUNT(CASE WHEN md.status = 'success' THEN 1 END) AS ok_machines
        FROM fleet_deployments d
        JOIN fleet_networks n ON d.network_id = n.id
        JOIN projects p ON n.project_id = p.id
        LEFT JOIN fleet_machine_deployments md ON d.id = md.deployment_id
        GROUP BY d.id
        ORDER BY d.started_at DESC LIMIT 20
    """)
    fleet_deploy_rows = []
    for fd in fleet_deploys:
        dur = f'{fd["duration_seconds"]}s' if fd["duration_seconds"] else "running"
        ratio = f'{fd["ok_machines"]}/{fd["total_machines"]}'
        fleet_deploy_rows.append([
            html.escape(fd["network_name"]),
            f'<span class="badge">{html.escape(fd["operation"])}</span>',
            _status_badge(fd["status"]),
            ratio,
            html.escape(fd["triggered_by"] or "user"),
            html.escape((fd["started_at"] or "")[:16]),
            dur,
        ])

    # ── Assemble ───────────────────────────────────────────────────────────────
    history_summary = query_all("""
        SELECT status, COUNT(*) as n FROM deployment_history GROUP BY status ORDER BY n DESC
    """)
    summary_html = " ".join(f'{_status_badge(r["status"])} <span class="muted">{r["n"]}</span>' for r in history_summary)

    # Count auto-deploys
    auto_count = query_one("SELECT COUNT(*) as n FROM deployment_history WHERE triggered_by = 'auto-commit'")
    auto_html = f' <span class="badge">auto: {auto_count["n"]}</span>' if auto_count and auto_count["n"] else ""

    body = f"""
<h2>Deploy</h2>

<h3>Auto-Deploy Triggers</h3>
<p class="muted" style="font-size:0.8rem;margin-bottom:0.5rem">Commits to matching branches auto-deploy to the target. Manage with <code>templedb deploy trigger add/list/remove</code></p>
{_table(["Project", "Branch", "Target", "Enabled", "Flags"], trigger_rows, "No triggers. Add one: templedb deploy trigger add &lt;project&gt; main production", "deploy-triggers-tbl")}

<h3 style="margin-top:1.5rem">Notifications</h3>
<p class="muted" style="font-size:0.8rem;margin-bottom:0.5rem">Webhook and command hooks for deploy events. Manage with <code>templedb deploy notify add/list/remove</code></p>
{_table(["Event", "Type", "Destination", "Scope", "Enabled"], notif_rows, "No notifications configured.", "deploy-notif-tbl")}

<h3 style="margin-top:1.5rem">Scripts</h3>
{_search_bar("deploy-scripts-tbl", "Filter scripts...")}
{_table(["Project", "Path", "Description", "Enabled", "Updated"], script_rows, "No deployment scripts.", "deploy-scripts-tbl")}

<h3 style="margin-top:1.5rem">Targets</h3>
{_search_bar("deploy-targets-tbl", "Filter by project or target...")}
{_table(["Project", "Target", "Type", "Host", "Provider", "URL", ""], target_rows, "No targets.", "deploy-targets-tbl")}

<h3 style="margin-top:1.5rem">History <span style="font-weight:normal;font-size:0.85rem">{summary_html}{auto_html}</span></h3>
{_search_bar("deploy-hist-tbl", "Filter by project / target / status / commit...", "360px")}
{_table(["Project", "Target", "Status", "Commit", "By", "Started", "Dur", "Details"], hist_rows, "No history.", "deploy-hist-tbl")}

<h3 style="margin-top:1.5rem">Cache <span class="muted" style="font-weight:normal;font-size:0.85rem">(content-addressable)</span></h3>
{_table(["Project", "Target", "Content Hash", "Files Hash", "Hits", "Last Used"], cache_rows, "No cached deployments.", "deploy-cache-tbl")}

<h3 style="margin-top:1.5rem">Fleet Networks</h3>
<p class="muted" style="font-size:0.8rem;margin-bottom:0.5rem">Multi-machine NixOS deployment with magic rollback. Manage with <code>templedb deploy fleet network/machine/deploy</code></p>
{_table(["Project", "Network", "UUID", "Deployed", "Last Deploy", "Flake/Config"], fleet_net_rows, 'No fleet networks. Create one: <code>templedb deploy fleet network create &lt;project&gt; &lt;name&gt; --flake-uri &lt;uri&gt;</code>', "fleet-net-tbl")}

<h3 style="margin-top:1.5rem">Fleet Machines</h3>
<p class="muted" style="font-size:0.8rem;margin-bottom:0.5rem">Tag machines for targeted deploys: <code>--on web</code>, <code>--on austin</code>. Magic rollback auto-reverts if SSH fails after activation.</p>
{_search_bar("fleet-machine-tbl", "Filter by network, machine, host, or tag...")}
{_table(["Network", "Machine", "Host", "Status", "Health", "NixOS", "Tags", "Last Deploy"], fleet_machine_rows, "No machines. Add one: <code>templedb deploy fleet machine add &lt;project&gt; &lt;network&gt; &lt;name&gt; --host &lt;ip&gt;</code>", "fleet-machine-tbl")}

<h3 style="margin-top:1.5rem">Fleet Deploy History</h3>
{_table(["Network", "Operation", "Status", "Machines", "By", "Started", "Duration"], fleet_deploy_rows, "No fleet deployments yet.", "fleet-deploy-tbl")}

<h3 style="margin-top:1.5rem">NixOS Switches</h3>
{_search_bar("nixos-switches-tbl", "Filter by project or date...")}
{_table(["Project", "Date", "Command", "Result", "Output"], nixos_rows, "No system deployments.", "nixos-switches-tbl")}

<h3 style="margin-top:1.5rem">NixOS Service Definitions</h3>
{_search_bar("nix-svc-tbl", "Filter services...")}
{_table(["Project", "Service", "Unit", "Description", "After", "Flags"], svc_rows, "No service definitions.", "nix-svc-tbl")}

<h3 style="margin-top:1.5rem">Local Services</h3>
{_search_bar("local-svcs-tbl", "Filter by project or service...")}
{_table(["Project", "Service", "Status", "Ports", "Package", "Health URL", "Last Started"], local_rows, "No local services.", "local-svcs-tbl")}
"""
    return _base("Deploy", body, "deploy")


@app.post("/deploy/triggers/{trigger_id}/toggle", response_class=HTMLResponse)
def deploy_trigger_toggle(trigger_id: int):
    row = query_one("SELECT dt.*, p.slug FROM deployment_triggers dt JOIN projects p ON dt.project_id = p.id WHERE dt.id=?", (trigger_id,))
    if not row:
        return HTMLResponse('<tr><td colspan="5" class="muted">Not found</td></tr>')
    new_val = 0 if row["enabled"] else 1
    execute("UPDATE deployment_triggers SET enabled=?, updated_at=datetime('now') WHERE id=?", (new_val, trigger_id))
    toggle = (
        f'<button hx-post="/deploy/triggers/{trigger_id}/toggle" hx-target="closest tr" hx-swap="outerHTML" '
        f'style="padding:0.15rem 0.5rem;font-size:0.75rem" class="{"success" if new_val else ""}">'
        f'{"on" if new_val else "off"}</button>'
    )
    flags = []
    if row["auto_rollback"]: flags.append("auto-rollback")
    if row["require_health_check"]: flags.append("health-check")
    flag_html = " ".join(f'<span class="badge">{f}</span>' for f in flags) or ""
    return HTMLResponse(f"""<tr>
<td><a href="/projects/{html.escape(row['slug'])}">{html.escape(row['slug'])}</a></td>
<td><code>{html.escape(row['branch_pattern'])}</code></td>
<td><strong>{html.escape(row['target_name'])}</strong></td>
<td>{toggle}</td>
<td>{flag_html}</td>
</tr>""")


@app.post("/deploy/scripts/{script_id}/toggle", response_class=HTMLResponse)
def deploy_script_toggle(script_id: int):
    row = query_one("SELECT * FROM deployment_scripts WHERE id=?", (script_id,))
    if not row:
        return HTMLResponse('<tr><td colspan="5" class="muted">Not found</td></tr>')
    new_val = 0 if row["enabled"] else 1
    execute("UPDATE deployment_scripts SET enabled=?, updated_at=datetime('now') WHERE id=?", (new_val, script_id))
    toggle = (
        f'<button hx-post="/deploy/scripts/{script_id}/toggle" hx-target="closest tr" hx-swap="outerHTML" '
        f'style="padding:0.15rem 0.5rem;font-size:0.75rem" class="{"success" if new_val else ""}">'
        f'{"on" if new_val else "off"}</button>'
    )
    return HTMLResponse(f"""<tr>
<td><a href="/projects/{html.escape(row['project_slug'])}">{html.escape(row['project_slug'])}</a></td>
<td><code style="font-size:0.78rem;word-break:break-all">{html.escape(row['script_path'])}</code></td>
<td>{html.escape(row['description'] or '')}</td>
<td>{toggle}</td>
<td>{html.escape((row['updated_at'] or '')[:10])}</td>
</tr>""")


# ── Audit ─────────────────────────────────────────────────────────────────────

@app.get("/audit", response_class=HTMLResponse)
def audit_list(project: str = Query(""), action: str = Query(""), limit: int = Query(200)):
    all_actions = query_all("SELECT DISTINCT action FROM audit_log ORDER BY action")
    all_projects = query_all("SELECT DISTINCT project_slug FROM audit_log WHERE project_slug IS NOT NULL ORDER BY project_slug")

    params: list = []
    wheres: list = []
    if project:
        wheres.append("project_slug = ?")
        params.append(project)
    if action:
        wheres.append("action = ?")
        params.append(action)
    where_sql = ("WHERE " + " AND ".join(wheres)) if wheres else ""

    rows = query_all(
        f"SELECT id, ts, actor, action, project_slug, profile, details FROM audit_log {where_sql} ORDER BY id DESC LIMIT ?",
        tuple(params) + (limit,)
    )

    total = (query_one(f"SELECT COUNT(*) AS n FROM audit_log {where_sql}", tuple(params)) or {}).get("n", 0)

    def _sel(name, options_rows, key, cur, placeholder):
        opts = f'<option value="">{placeholder}</option>'
        for r in options_rows:
            v = r[key]
            sel = " selected" if v == cur else ""
            opts += f'<option value="{html.escape(v or "")}"{sel}>{html.escape(v or "")}</option>'
        style = ('style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;'
                 'padding:0.3rem 0.5rem;border-radius:4px;font-family:monospace;font-size:0.85rem"')
        return f'<select name="{name}" onchange="this.form.submit()" {style}>{opts}</select>'

    limit_opts = ""
    for v in [50, 200, 500, 1000]:
        sel = " selected" if v == limit else ""
        limit_opts += f'<option value="{v}"{sel}>{v}</option>'
    limit_sel = (f'<select name="limit" onchange="this.form.submit()" style="background:#13131f;border:1px solid #2a2a4a;'
                 f'color:#d0d0e8;padding:0.3rem 0.5rem;border-radius:4px;font-family:monospace;font-size:0.85rem">'
                 f'{limit_opts}</select>')

    filter_bar = f"""
<form method="get" action="/audit" class="row" style="margin-bottom:1rem">
  {_sel("project", all_projects, "project_slug", project, "All projects")}
  {_sel("action", all_actions, "action", action, "All actions")}
  {limit_sel}
  <span class="muted">showing {len(rows)} of {total}</span>
</form>
{_search_bar("audit-tbl", "Filter by actor, action, project…", "320px")}
"""

    ACTION_COLORS = {
        "get-secret": "#c87030", "set-secret": "#e94560", "delete-secret": "#e94560",
        "deploy": "#4a9a6a", "commit": "#4a8acc", "sync": "#4a8acc",
    }

    tbl_rows = []
    for r in rows:
        color = ACTION_COLORS.get(r["action"] or "", "#808098")
        action_cell = f'<span style="color:{color};font-size:0.82rem">{html.escape(r["action"] or "")}</span>'
        proj_cell = (f'<a href="/projects/{html.escape(r["project_slug"])}">{html.escape(r["project_slug"])}</a>'
                     if r["project_slug"] else '<span class="muted">—</span>')
        details = r["details"] or ""
        if details and details != "{}":
            try:
                d = json.loads(details)
                details = ", ".join(f"{k}={v}" for k, v in list(d.items())[:3])
            except Exception:
                pass
        tbl_rows.append([
            html.escape((r["ts"] or "")[:16]),
            html.escape(r["actor"] or ""),
            action_cell,
            proj_cell,
            html.escape(r["profile"] or ""),
            f'<span class="muted" style="font-size:0.78rem">{html.escape(str(details)[:60])}</span>',
        ])

    body = f"""
<h2>Audit Log</h2>
{filter_bar}
{_table(["Time", "Actor", "Action", "Project", "Profile/Key", "Details"], tbl_rows, "No audit entries.", "audit-tbl")}
"""
    return _base("Audit", body, "audit")


# ── Domains ────────────────────────────────────────────────────────────────────

@app.get("/domains", response_class=HTMLResponse)
def domains_list():
    domains = query_all("""
        SELECT pd.id, p.slug, pd.domain, pd.registrar, pd.status,
               pd.primary_domain, pd.created_at, pd.updated_at
        FROM project_domains pd JOIN projects p ON pd.project_id = p.id
        ORDER BY p.slug, pd.domain
    """)

    dns = query_all("""
        SELECT dr.*, pd.domain AS domain_name, p.slug
        FROM dns_records dr
        JOIN project_domains pd ON dr.domain_id = pd.id
        JOIN projects p ON pd.project_id = p.id
        ORDER BY p.slug, pd.domain, dr.record_type
    """)

    dns_by_domain: dict = defaultdict(list)
    for r in dns:
        dns_by_domain[r["domain_id"]].append(r)

    domain_rows = []
    for d in domains:
        status_color = {"active": " green", "pending": "", "expired": " red"}.get(d["status"] or "", "")
        primary = '<span class="badge green">primary</span>' if d["primary_domain"] else ""
        dns_records = dns_by_domain.get(d["id"], [])
        dns_summary = f'{len(dns_records)} record{"s" if len(dns_records) != 1 else ""}'
        dns_detail = ""
        if dns_records:
            dns_trs = [
                [f'<span class="badge">{html.escape(r["record_type"])}</span>',
                 html.escape(r["name"] or ""),
                 f'<code style="font-size:0.78rem">{html.escape(r["value"] or "")}</code>',
                 html.escape(r["target_name"] or ""),
                 f'<span class="muted">{r["ttl"]}s</span>']
                for r in dns_records
            ]
            dns_detail = (f'<details style="margin-top:0.2rem"><summary style="cursor:pointer;'
                          f'color:#606080;font-size:0.75rem">{dns_summary}</summary>'
                          f'<div style="margin-top:0.3rem">{_table(["Type","Name","Value","Target","TTL"], dns_trs)}</div></details>')
        domain_rows.append([
            f'<a href="/projects/{html.escape(d["slug"])}">{html.escape(d["slug"])}</a>',
            f'<strong>{html.escape(d["domain"])}</strong> {primary}',
            f'<span class="badge{status_color}">{html.escape(d["status"] or "unknown")}</span>',
            html.escape(d["registrar"] or ""),
            html.escape((d["updated_at"] or "")[:10]),
            dns_detail,
        ])

    body = f"""
<h2>Domains</h2>
{_search_bar("domains-tbl", "Filter by project or domain…")}
{_table(["Project", "Domain", "Status", "Registrar", "Updated", "DNS"], domain_rows, "No domains.", "domains-tbl")}
"""
    return _base("Domains", body, "domains")


# ── Docs ──────────────────────────────────────────────────────────────────────

CLI_REFERENCE = """
<details open style="margin-bottom:1.5rem;border:1px solid #1e1e3a;border-radius:6px;padding:1rem">
<summary style="cursor:pointer;color:#e94560;font-weight:bold;font-size:0.9rem">CLI Quick Reference</summary>
<div style="margin-top:0.75rem;display:grid;grid-template-columns:1fr 1fr 1fr;gap:1.5rem;font-size:0.8rem">

<div>
<h3>Getting Started</h3>
<pre style="font-size:0.75rem">templedb bootstrap                        # new machine setup
templedb bootstrap --from-backup &lt;path&gt;   # restore from backup
templedb bootstrap --from-gcs &lt;bucket&gt;    # restore from GCS
templedb bootstrap --username &lt;user&gt;      # set identity
templedb bootstrap --hostname &lt;host&gt;      # set NixOS hostname
templedb tutorial                          # interactive guides
templedb status                            # system overview</pre>

<h3 style="margin-top:1rem">Projects</h3>
<pre style="font-size:0.75rem">templedb project import &lt;path&gt; [--slug x]  # import project
templedb project list                      # list all projects
templedb project show &lt;slug&gt;              # project details
templedb project checkout &lt;slug&gt; &lt;dir&gt;    # checkout to filesystem
templedb project sync &lt;slug&gt;              # re-scan from disk</pre>

<h3 style="margin-top:1rem">Version Control</h3>
<pre style="font-size:0.75rem">templedb vcs status &lt;proj&gt; --refresh       # detect changes
templedb vcs add -p &lt;proj&gt; --all          # stage all
templedb vcs commit -p &lt;proj&gt; -m "msg"    # commit
templedb vcs log &lt;proj&gt;                   # history
templedb vcs log &lt;proj&gt; --branch feat     # log for branch
templedb vcs diff &lt;proj&gt;                  # show changes
templedb vcs branch &lt;proj&gt;                # list branches
templedb vcs branch &lt;proj&gt; feat           # create branch
templedb vcs branch &lt;proj&gt; -d feat        # delete branch
templedb vcs switch &lt;proj&gt; feat           # switch branch
templedb vcs merge &lt;proj&gt; feat            # merge into current
templedb vcs merge &lt;proj&gt; feat --squash  # squash into 1 commit
templedb git-export &lt;proj&gt; --remote &lt;url&gt; # export to git</pre>
</div>

<div>
<h3>NixOS</h3>
<pre style="font-size:0.75rem">templedb nixos status                      # pipeline state
templedb nixos doctor                      # diagnose problems
templedb nixos import-config               # import config to DB
templedb nixos generate-all                # generate everything
templedb nixos generate &lt;slug&gt;            # generate modules only
templedb nixos rebuild &lt;slug&gt;             # nixos-rebuild switch
templedb nixos config-set &lt;key&gt; &lt;val&gt;    # set config value
templedb nixos config-list                 # list all config</pre>

<h3 style="margin-top:1rem">Dotfiles</h3>
<pre style="font-size:0.75rem">templedb nixos dotfiles-list               # show all mappings
templedb nixos dotfiles-add &lt;p&gt; &lt;s&gt; &lt;t&gt;  # add mapping
templedb nixos dotfiles-remove &lt;p&gt; &lt;s&gt;   # remove mapping
templedb nixos dotfiles-apply [--force]    # create symlinks</pre>

<h3 style="margin-top:1rem">FUSE Filesystem</h3>
<pre style="font-size:0.75rem">templedb mount [~/temple]                  # mount DB as filesystem
templedb mount -r                          # read-only mount
templedb unmount [~/temple]                # unmount
templedb mount-status                      # check mount state</pre>
</div>

<div>
<h3>Secrets &amp; Environment</h3>
<pre style="font-size:0.75rem">templedb env secret list                   # list secrets
templedb env secret set &lt;proj&gt; &lt;key&gt;      # set secret
templedb env secret export &lt;proj&gt;         # export as dotenv
templedb env set &lt;proj&gt; &lt;key&gt; &lt;val&gt;      # set env var
templedb env list &lt;proj&gt;                  # list env vars
templedb env key list                      # list encryption keys</pre>

<h3 style="margin-top:1rem">Deployment</h3>
<pre style="font-size:0.75rem">templedb deploy run &lt;proj&gt;                # deploy project
templedb deploy list                       # list deployments
templedb deploy history &lt;proj&gt;            # deployment history
templedb deploy shell &lt;proj&gt;              # enter deploy shell
templedb deploy rollback &lt;proj&gt;           # rollback deploy</pre>

<h3 style="margin-top:1rem">Database &amp; Backup</h3>
<pre style="font-size:0.75rem">templedb admin db status                    # migration status
templedb admin db migrate                   # apply migrations
templedb admin db integrity                 # integrity check
templedb storage backup local               # local backup
templedb storage backup gcs                 # backup to GCS
templedb storage backup restore &lt;path&gt;     # restore from backup</pre>

<h3 style="margin-top:1rem">Publishing</h3>
<pre style="font-size:0.75rem">templedb publish run &lt;proj&gt; -m "msg"       # commit + push to mirrors
templedb publish build &lt;proj&gt;              # nix build from git daemon
templedb publish mirror-add &lt;p&gt; github &lt;url&gt;
templedb publish mirror-list               # show all mirrors</pre>

<h3 style="margin-top:1rem">Sync &amp; Network</h3>
<pre style="font-size:0.75rem">templedb sync init                         # init cr-sqlite CRDTs
templedb sync sync &lt;peer&gt;                 # bidirectional sync
templedb sync network setup                # configure Tailscale
templedb sync network sync-all             # sync all peers</pre>
</div>

</div>
</details>
"""


@app.get("/docs", response_class=HTMLResponse)
def docs_list(project: str = Query(""), category: str = Query("")):
    readme_files = query_all("""
        SELECT rf.id, p.slug, rf.title, rf.file_path, rf.category, rf.scope,
               rf.word_count, rf.section_count, rf.has_toc, rf.last_scanned_at,
               rf.description
        FROM readme_files rf JOIN projects p ON rf.project_id = p.id
        ORDER BY p.slug, rf.category NULLS LAST, rf.title
    """)

    topics_rows = query_all("""
        SELECT rt.readme_id, rt.topic, rt.relevance
        FROM readme_topics rt
        ORDER BY rt.readme_id, rt.relevance DESC
    """)
    topics_by_doc: dict = defaultdict(list)
    for t in topics_rows:
        topics_by_doc[t["readme_id"]].append(t)  # t["relevance"] is the score

    sections_rows = query_all("""
        SELECT rs.readme_id, rs.heading, rs.level, rs.anchor, rs.line_number
        FROM readme_sections rs ORDER BY rs.readme_id, rs.line_number
    """)
    sections_by_doc: dict = defaultdict(list)
    for s in sections_rows:
        sections_by_doc[s["readme_id"]].append(s)

    # Collect filter options — include ALL projects, not just those with READMEs
    readme_projects = sorted({r["slug"] for r in readme_files})
    all_projects_rows = query_all("SELECT slug FROM projects ORDER BY slug")
    all_projects = sorted({r["slug"] for r in all_projects_rows})
    all_categories = sorted({r["category"] or "uncategorized" for r in readme_files})

    # Filter
    filtered = readme_files
    if project:
        filtered = [r for r in filtered if r["slug"] == project]
    if category:
        cat_match = None if category == "uncategorized" else category
        filtered = [r for r in filtered if (r["category"] or None) == cat_match]

    # Group by category
    by_category: dict = defaultdict(list)
    for r in filtered:
        by_category[r["category"] or "uncategorized"].append(r)

    # Filter dropdowns
    proj_opts = '<option value="">All projects</option>' + "".join(
        f'<option value="{html.escape(p)}" {"selected" if p == project else ""}>{html.escape(p)}</option>'
        for p in all_projects
    )
    cat_opts = '<option value="">All categories</option>' + "".join(
        f'<option value="{html.escape(c)}" {"selected" if c == category else ""}>{html.escape(c)}</option>'
        for c in all_categories
    )

    sections_html = ""
    for cat in sorted(by_category.keys()):
        docs = by_category[cat]
        cat_label = cat.title() if cat != "uncategorized" else "Uncategorized"
        rows = []
        for r in docs:
            doc_topics = topics_by_doc.get(r["id"], [])
            doc_sections = sections_by_doc.get(r["id"], [])
            topic_badges = " ".join(
                f'<span class="badge blue" style="font-size:0.68rem">{html.escape(t["topic"])}</span>'
                for t in doc_topics[:5]
            )
            toc_badge = '<span class="badge green" style="font-size:0.68rem">TOC</span>' if r["has_toc"] else ""
            scope_badge = (
                f'<span class="badge" style="font-size:0.68rem">{html.escape(r["scope"])}</span>'
                if r["scope"] else ""
            )
            title_cell = (
                f'<strong>{_file_link(r["slug"], r["file_path"], r["title"] or r["file_path"])}</strong>'
                if r["file_path"] else f'<strong>{html.escape(r["title"] or "")}</strong>'
            )
            desc = html.escape(r["description"] or "")
            desc_cell = f'<span class="muted" style="font-size:0.8rem">{desc}</span>' if desc else ""

            # Sections expander
            sec_detail = ""
            if doc_sections:
                sec_trs = []
                for s in doc_sections:
                    indent = "&nbsp;" * (s["level"] - 1) * 3
                    anchor_link = (
                        f'<a href="/projects/{html.escape(r["slug"])}/file?path={html.escape(r["file_path"] or "")}#{html.escape(s["anchor"] or "")}" '
                        f'style="font-size:0.78rem">{indent}{html.escape(s["heading"])}</a>'
                        if r["file_path"] else f'{indent}{html.escape(s["heading"])}'
                    )
                    sec_trs.append([
                        f'<span class="muted" style="font-size:0.75rem">H{s["level"]}</span>',
                        anchor_link,
                        f'<span class="muted">{s["line_number"]}</span>',
                    ])
                sec_inner = _table(["Lvl", "Heading", "Line"], sec_trs)
                sec_detail = (
                    f'<details style="margin-top:0.15rem">'
                    f'<summary style="cursor:pointer;color:#606080;font-size:0.75rem">'
                    f'{len(doc_sections)} section{"s" if len(doc_sections) != 1 else ""}</summary>'
                    f'<div style="margin-top:0.3rem">{sec_inner}</div></details>'
                )

            rows.append([
                title_cell + (f'<br>{desc_cell}' if desc_cell else ""),
                f'{r["slug"]}',
                f'{r["word_count"] or 0:,}',
                sec_detail or f'<span class="muted">{r["section_count"] or 0}</span>',
                f'{toc_badge} {scope_badge}'.strip(),
                topic_badges,
                html.escape((r["last_scanned_at"] or "")[:10]),
            ])

        section_table = _table(
            ["Title", "Project", "Words", "Sections", "Flags", "Topics", "Scanned"],
            rows,
        )
        sections_html += (
            f'<div class="fsec" style="margin-top:1.5rem">'
            f'<h3>{html.escape(cat_label)} <span class="muted" style="font-weight:normal;font-size:0.85rem">({len(docs)})</span></h3>'
            f'{section_table}</div>'
        )

    total = len(filtered)

    # ── File Tree Browser ─────────────────────────────────────────────────
    file_tree_html = ""
    browse_slug = project or "system_config"
    try:
        browse_proj = query_one("SELECT id, slug FROM projects WHERE slug = ?", (browse_slug,))
        if browse_proj:
            doc_files = query_all("""
                SELECT pf.file_path, cb.file_size_bytes
                FROM project_files pf
                JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
                JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
                WHERE pf.project_id = ? AND pf.status = 'active'
                AND (pf.file_path LIKE '%.md' OR pf.file_path LIKE '%.nix'
                     OR pf.file_path LIKE '%.json' OR pf.file_path LIKE '%.yaml'
                     OR pf.file_path LIKE '%.yml' OR pf.file_path LIKE '%.toml'
                     OR pf.file_path LIKE '%.sh' OR pf.file_path LIKE '%.py'
                     OR pf.file_path LIKE '%.ts' OR pf.file_path LIKE '%.js'
                     OR pf.file_path LIKE '%.txt' OR pf.file_path LIKE '%.sql'
                     OR pf.file_path LIKE '%.hs' OR pf.file_path LIKE '%.css'
                     OR pf.file_path LIKE '%.html' OR pf.file_path LIKE '%.envrc')
                ORDER BY pf.file_path
            """, (browse_proj["id"],))

            if doc_files:
                # Build tree structure
                tree = {}
                for f in doc_files:
                    parts = f["file_path"].split("/")
                    node = tree
                    for i, p in enumerate(parts[:-1]):
                        node = node.setdefault(p, {})
                    node[parts[-1]] = f

                def _render_tree(node, prefix="", depth=0):
                    result = ""
                    indent = "&nbsp;" * depth * 3
                    for name in sorted(node.keys()):
                        val = node[name]
                        if isinstance(val, dict) and "file_path" not in val:
                            # Directory
                            result += f'<div style="margin:0.1rem 0">{indent}<span style="color:#808098">📁</span> <strong style="font-size:0.82rem;color:#a0a0c0">{html.escape(name)}/</strong></div>'
                            result += _render_tree(val, prefix + name + "/", depth + 1)
                        else:
                            # File
                            fp = val["file_path"]
                            size = val["file_size_bytes"]
                            size_str = f"{size:,}" if size < 10000 else f"{size/1024:.0f}K"
                            ext = name.rsplit(".", 1)[-1] if "." in name else ""
                            icon = {"md": "📄", "nix": "❄", "json": "📋", "py": "🐍", "sh": "⚡", "ts": "📘", "js": "📘", "sql": "🗄"}.get(ext, "📄")
                            result += (
                                f'<div style="margin:0.1rem 0">{indent}{icon} '
                                f'<a href="/projects/{html.escape(browse_slug)}/file?path={html.escape(fp)}" '
                                f'style="font-size:0.82rem">{html.escape(name)}</a> '
                                f'<span class="muted" style="font-size:0.7rem">{size_str}</span></div>'
                            )
                    return result

                tree_rendered = _render_tree(tree)
                file_tree_html = f"""
<div style="border:1px solid #1e1e3a;border-radius:6px;padding:1rem;margin-bottom:1.5rem;max-height:500px;overflow-y:auto">
  <h3 style="margin-bottom:0.5rem">{html.escape(browse_slug)} File Browser
    <span class="help-tip" style="position:relative">?<span class="tip">Browse project files. Click any file to view its contents. Shows text files (.nix, .md, .json, .py, .sh, etc.).</span></span>
  </h3>
  {tree_rendered}
</div>
"""
    except Exception:
        pass

    # ── Project selector for file browser ─────────────────────────────────
    all_proj_opts = "".join(
        f'<option value="{html.escape(s)}"{" selected" if s == browse_slug else ""}>{html.escape(s)}</option>'
        for s in all_projects
    )

    body = f"""
<h2>Docs</h2>

<div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-bottom:1rem;align-items:center">
  <form method="get" style="display:flex;gap:0.5rem;align-items:center">
    <label style="font-size:0.85rem;color:#808098">Browse project:</label>
    <select name="project" onchange="this.form.submit()" style="font-size:0.85rem;padding:0.3rem;background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;border-radius:4px">{all_proj_opts}</select>
    <select name="category" onchange="this.form.submit()" style="font-size:0.85rem;padding:0.3rem;background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;border-radius:4px">{cat_opts}</select>
    {"" if not (project or category) else '<a href="/docs" style="font-size:0.8rem">clear</a>'}
  </form>
</div>

{file_tree_html}

<h3>Project Documentation ({total})</h3>
{_search_bar("docs-content", "Filter docs…")}
<div id="docs-content">{sections_html or '<p class="muted">No docs found.</p>'}</div>

{CLI_REFERENCE}

<h3 style="margin-top:1.5rem">Quick Config Links</h3>
{_project_config_links()}
"""
    return _base("Docs", body, "docs")


def _project_config_links() -> str:
    """Generate quick links to key config files across projects."""
    config_patterns = [
        ("NixOS", ["flake.nix", "home.nix", "configuration.nix"]),
        ("Project", ["package.json", "Cargo.toml", "flake.nix", "shell.nix", "default.nix"]),
        ("Docs", ["README.md", "CHANGELOG.md", "CLAUDE.md", "AGENTS.md"]),
        ("CI/Deploy", [".github/workflows/test.yml", "deploy.sh", "Dockerfile"]),
    ]

    projects = query_all("SELECT slug FROM projects ORDER BY slug")
    if not projects:
        return '<p class="muted">No projects.</p>'

    rows = []
    for proj in projects:
        slug = proj["slug"]
        # Find which config files exist for this project
        files = query_all(
            "SELECT file_path FROM project_files WHERE project_id = "
            "(SELECT id FROM projects WHERE slug = ?) AND status = 'active' "
            "AND (file_path IN (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "OR file_path LIKE '%README%' OR file_path LIKE '%CLAUDE%')"
            "ORDER BY file_path LIMIT 10",
            (slug, "flake.nix", "home.nix", "configuration.nix",
             "package.json", "Cargo.toml", "shell.nix", "default.nix",
             "README.md", "CHANGELOG.md", "AGENTS.md", "Dockerfile")
        )
        if files:
            links = " ".join(
                f'<a href="/projects/{html.escape(slug)}/file?path={html.escape(f["file_path"])}" '
                f'style="font-size:0.75rem">{html.escape(f["file_path"].split("/")[-1])}</a>'
                for f in files
            )
            rows.append([
                f'<a href="/projects/{html.escape(slug)}">{html.escape(slug)}</a>',
                links,
            ])

    if not rows:
        return '<p class="muted">No config files found.</p>'

    return _table(["Project", "Config Files"], rows)


# ── Code Intelligence ─────────────────────────────────────────────────────────

@app.get("/code", response_class=HTMLResponse)
def code_redirect(project: str = Query(""), kind: str = Query("")):
    from fastapi.responses import RedirectResponse
    params = ["view=symbols"]
    if project: params.append(f"project={project}")
    if kind: params.append(f"kind={kind}")
    return RedirectResponse(f"/graph?{'&'.join(params)}")


def _code_symbols_html(project: str = "", kind: str = ""):
    symbols = query_all("""
        SELECT cs.id, p.slug, cs.symbol_name, cs.symbol_type,
               pf.file_path, cs.start_line, cs.end_line,
               cs.cyclomatic_complexity, cs.num_dependents, cs.docstring
        FROM code_symbols cs
        JOIN projects p ON cs.project_id = p.id
        LEFT JOIN project_files pf ON cs.file_id = pf.id
        ORDER BY p.slug, cs.symbol_type, cs.symbol_name
    """)

    deps = query_all("""
        SELECT cd.caller_symbol_id, cd.called_symbol_id,
               cd.dependency_type, cd.confidence_score,
               cs1.symbol_name AS caller_name, cs1.symbol_type AS caller_type,
               cs2.symbol_name AS called_name, cs2.symbol_type AS called_type,
               p1.slug AS caller_project
        FROM code_symbol_dependencies cd
        JOIN code_symbols cs1 ON cd.caller_symbol_id = cs1.id
        JOIN code_symbols cs2 ON cd.called_symbol_id = cs2.id
        JOIN projects p1 ON cs1.project_id = p1.id
        ORDER BY p1.slug, cs1.symbol_name
    """)

    clusters = query_all("""
        SELECT cc.id, p.slug, cc.cluster_name, cc.cluster_type,
               cc.cohesion_score, cc.description
        FROM code_clusters cc JOIN projects p ON cc.project_id = p.id
        ORDER BY p.slug, cc.cohesion_score DESC NULLS LAST
    """)

    all_projects = sorted({s["slug"] for s in symbols} | {c["slug"] for c in clusters})
    all_kinds = sorted({s["symbol_type"] for s in symbols if s["symbol_type"]})

    # Filter
    filtered_syms = symbols
    if project:
        filtered_syms = [s for s in filtered_syms if s["slug"] == project]
    if kind:
        filtered_syms = [s for s in filtered_syms if s["symbol_type"] == kind]

    filtered_clusters = clusters
    if project:
        filtered_clusters = [c for c in filtered_clusters if c["slug"] == project]

    filtered_deps = deps
    if project:
        filtered_deps = [d for d in filtered_deps if d["caller_project"] == project]

    # Filter dropdowns
    proj_opts = '<option value="">All projects</option>' + "".join(
        f'<option value="{html.escape(p)}" {"selected" if p == project else ""}>{html.escape(p)}</option>'
        for p in all_projects
    )
    kind_opts = '<option value="">All types</option>' + "".join(
        f'<option value="{html.escape(k)}" {"selected" if k == kind else ""}>{html.escape(k)}</option>'
        for k in all_kinds
    )

    # ── Symbols table ─────────────────────────────────────────────────────────
    TYPE_COLORS = {"function": "", "method": "blue", "class": "green"}
    sym_rows = []
    for s in filtered_syms:
        color = TYPE_COLORS.get(s["symbol_type"] or "", "")
        badge_style = f' style="background:#3a4a3a;color:#8fbf8f"' if color == "green" else ""
        type_badge = f'<span class="badge{" " + color if color else ""}"{badge_style}>{html.escape(s["symbol_type"] or "")}</span>'
        lines = ""
        if s["start_line"] and s["end_line"]:
            lines = f'{s["start_line"]}–{s["end_line"]}'
        elif s["start_line"]:
            lines = str(s["start_line"])
        complexity = s["cyclomatic_complexity"]
        complexity_cell = (
            f'<span style="color:{"#d44" if (complexity or 0) > 10 else "#c8a040" if (complexity or 0) > 5 else "inherit"}">{complexity}</span>'
            if complexity else '<span class="muted">—</span>'
        )
        dependents = s["num_dependents"] or 0
        dep_cell = (
            f'<strong style="color:#6a9fbf">{dependents}</strong>' if dependents > 0
            else '<span class="muted">0</span>'
        )
        file_cell = _file_link(s["slug"], s["file_path"]) if s["file_path"] else '<span class="muted">—</span>'
        docstring = s["docstring"] or ""
        name_cell = f'<strong style="font-family:monospace">{html.escape(s["symbol_name"])}</strong>'
        if docstring:
            short_doc = html.escape(docstring[:80] + ("…" if len(docstring) > 80 else ""))
            name_cell += f'<br><span class="muted" style="font-size:0.75rem;font-family:sans-serif">{short_doc}</span>'
        sym_rows.append([
            name_cell,
            type_badge,
            f'<a href="/projects/{html.escape(s["slug"])}">{html.escape(s["slug"])}</a>',
            file_cell,
            f'<span class="muted">{lines}</span>',
            complexity_cell,
            dep_cell,
        ])

    symbols_section = f"""
<div style="margin-bottom:2rem">
  <h3>Symbols <span class="muted" style="font-weight:normal;font-size:0.85rem">({len(filtered_syms)})</span></h3>
  {_search_bar("sym-tbl", "Filter symbols…")}
  {_table(["Name", "Type", "Project", "File", "Lines", "Complexity", "Dependents"], sym_rows, "No symbols.", "sym-tbl")}
</div>"""

    # ── Call graph / dependencies ─────────────────────────────────────────────
    dep_rows = []
    for d in filtered_deps[:200]:  # cap at 200 rows
        dep_type_badge = f'<span class="badge" style="font-size:0.72rem">{html.escape(d["dependency_type"] or "call")}</span>'
        conf = d["confidence_score"]
        conf_cell = f'{conf:.2f}' if conf is not None else '<span class="muted">—</span>'
        dep_rows.append([
            f'<span style="font-family:monospace">{html.escape(d["caller_name"])}</span>',
            f'<span class="muted">→</span>',
            f'<span style="font-family:monospace">{html.escape(d["called_name"])}</span>',
            dep_type_badge,
            conf_cell,
        ])

    deps_section = f"""
<div style="margin-bottom:2rem">
  <h3>Call Graph <span class="muted" style="font-weight:normal;font-size:0.85rem">({len(filtered_deps)} edges)</span></h3>
  {_search_bar("dep-tbl", "Filter calls…")}
  {_table(["Caller", "", "Callee", "Type", "Confidence"], dep_rows, "No dependency edges.", "dep-tbl")}
</div>"""

    # ── Clusters ─────────────────────────────────────────────────────────────
    cluster_rows = []
    for c in filtered_clusters:
        cohesion = c["cohesion_score"]
        cohesion_cell = (
            f'<span style="color:{"#6abf6a" if (cohesion or 0) > 0.7 else "#c8a040" if (cohesion or 0) > 0.4 else "#d44"}">{cohesion:.2f}</span>'
            if cohesion is not None else '<span class="muted">—</span>'
        )
        cluster_rows.append([
            f'<strong>{html.escape(c["cluster_name"])}</strong>',
            f'<a href="/projects/{html.escape(c["slug"])}">{html.escape(c["slug"])}</a>',
            f'<span class="badge">{html.escape(c["cluster_type"] or "")}</span>',
            cohesion_cell,
            html.escape(c["description"] or ""),
        ])

    clusters_section = f"""
<div style="margin-bottom:2rem">
  <h3>Clusters <span class="muted" style="font-weight:normal;font-size:0.85rem">({len(filtered_clusters)})</span></h3>
  {_search_bar("cluster-tbl", "Filter clusters…")}
  {_table(["Name", "Project", "Type", "Cohesion", "Description"], cluster_rows, "No clusters.", "cluster-tbl")}
</div>"""

    return f"""
<div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-bottom:1.25rem;align-items:center">
  <form method="get" action="/graph" style="display:flex;gap:0.5rem;align-items:center">
    <input type="hidden" name="view" value="symbols">
    <select name="project" onchange="this.form.submit()" style="font-size:0.85rem;padding:0.3rem">{proj_opts}</select>
    <select name="kind" onchange="this.form.submit()" style="font-size:0.85rem;padding:0.3rem">{kind_opts}</select>
    {"" if not (project or kind) else '<a href="/graph?view=symbols" style="font-size:0.8rem">clear</a>'}
  </form>
</div>
{symbols_section}
{deps_section}
{clusters_section}
"""


# ── Status ────────────────────────────────────────────────────────────────────

# ── Graph ─────────────────────────────────────────────────────────────────────

@app.get("/graph", response_class=HTMLResponse)
def graph_page(q: str = Query(""), view: str = Query("overview"), project: str = Query(""), kind: str = Query("")):

    search_result = ""
    if q:
        from knowledge_graph import search_everywhere
        results = search_everywhere(q, limit=30)
        total = sum(len(v) for v in results.values())

        sections = ""
        for category, items in results.items():
            rows = []
            for item in items:
                if category == "projects":
                    rows.append([
                        f'<a href="/projects/{html.escape(item["slug"])}">{html.escape(item["slug"])}</a>',
                        html.escape(item.get("project_type", "")),
                        html.escape(item.get("name", "") or ""),
                    ])
                elif category == "files":
                    rows.append([
                        f'<a href="/projects/{html.escape(item["slug"])}">{html.escape(item["slug"])}</a>',
                        _file_link(item["slug"], item["file_path"]),
                    ])
                elif category == "env_vars":
                    val = "****" if item.get("is_secret") else html.escape((item.get("var_value", "") or "")[:50])
                    rows.append([
                        html.escape(item.get("slug", "") or ""),
                        f'<code>{html.escape(item["var_name"])}</code>',
                        val,
                    ])
                elif category == "secrets":
                    rows.append([
                        html.escape(item["slug"]),
                        f'<code>{html.escape(item["secret_name"])}</code>',
                        f'<span class="badge">{html.escape(item.get("profile", ""))}</span>',
                    ])
                elif category == "config":
                    rows.append([
                        f'<code style="font-size:0.78rem">{html.escape(item["key"])}</code>',
                        f'<span class="muted" style="font-size:0.78rem">{html.escape(item["value"][:80])}</span>',
                    ])
                elif category == "commits":
                    rows.append([
                        f'<a href="/vcs/{html.escape(item["slug"])}">{html.escape(item["slug"])}</a>',
                        f'<code>{html.escape(item["commit_hash"][:8])}</code>',
                        html.escape((item.get("commit_message", "") or "")[:60]),
                        f'<span class="muted">{html.escape(item.get("commit_timestamp", "")[:10])}</span>',
                    ])
                elif category == "symbols":
                    rows.append([
                        html.escape(item["slug"]),
                        f'<code>{html.escape(item.get("symbol_name", ""))}</code>',
                        f'<span class="badge">{html.escape(item["symbol_type"])}</span>',
                        f'<span class="muted">{html.escape(item.get("file_path", ""))}</span>',
                    ])

            if rows:
                headers = {
                    "projects": ["Project", "Type", "Name"],
                    "files": ["Project", "Path"],
                    "env_vars": ["Project", "Variable", "Value"],
                    "secrets": ["Project", "Secret", "Profile"],
                    "config": ["Key", "Value"],
                    "commits": ["Project", "Hash", "Message", "Date"],
                    "symbols": ["Project", "Symbol", "Type", "File"],
                }.get(category, ["Data"])
                cat_label = category.replace("_", " ").title()
                sections += f'<h3 style="margin-top:1rem">{cat_label} ({len(items)})</h3>'
                sections += _table(headers, rows)

        search_result = f"""
<div style="border:1px solid #1e1e3a;border-radius:6px;padding:1rem;margin-bottom:1.5rem">
  <h3>Results for "{html.escape(q)}" ({total} matches)</h3>
  {sections if sections else '<p class="muted">No results found.</p>'}
</div>"""

    # Overview tab
    overview_html = ""
    if view == "overview":
        from knowledge_graph import cross_project_analysis
        analysis = cross_project_analysis()

        # Project table
        proj_rows = []
        for p in analysis["projects"]:
            proj_rows.append([
                f'<a href="/projects/{html.escape(p["slug"])}">{html.escape(p["slug"])}</a>',
                f'<span class="badge">{html.escape(p.get("project_type", "") or "")}</span>',
                str(p["file_count"]),
                str(p["commit_count"]),
                str(p["env_var_count"]),
                str(p["secret_count"]),
            ])
        proj_table = _table(
            ["Project", "Type", "Files", "Commits", "Vars", "Secrets"],
            proj_rows, table_id="graph-projects"
        )

        # Shared secrets
        shared_sec = ""
        if analysis["shared_secrets"]:
            sec_rows = [[
                f'<code>{html.escape(s["secret_name"])}</code>',
                html.escape(s["projects"]),
                str(s["project_count"]),
            ] for s in analysis["shared_secrets"]]
            shared_sec = f"""
<h3 style="margin-top:1.5rem">Shared Secrets
  <span class="help-tip" style="position:relative">?<span class="tip">Secrets used by multiple projects. These are cross-project dependencies.</span></span>
</h3>
{_table(["Secret", "Projects", "Count"], sec_rows)}"""

        # Shared vars
        shared_vars = ""
        if analysis["shared_vars"]:
            var_rows = [[
                f'<code>{html.escape(v["var_name"])}</code>',
                html.escape(v["projects"]),
                str(v["project_count"]),
            ] for v in analysis["shared_vars"]]
            shared_vars = f"""
<h3 style="margin-top:1.5rem">Shared Env Vars</h3>
{_table(["Variable", "Projects", "Count"], var_rows)}"""

        # Recent activity
        recent = ""
        if analysis["recent_activity"]:
            act_rows = [[
                f'<a href="/vcs/{html.escape(r["slug"])}">{html.escape(r["slug"])}</a>',
                f'<code>{html.escape(r["commit_hash"][:8])}</code>',
                html.escape((r.get("commit_message", "") or "")[:60]),
                f'<span class="muted">{html.escape(r.get("commit_timestamp", "")[:10])}</span>',
            ] for r in analysis["recent_activity"]]
            recent = f"""
<h3 style="margin-top:1.5rem">Recent Activity</h3>
{_table(["Project", "Hash", "Message", "Date"], act_rows)}"""

        overview_html = f"""
<h3>Projects ({len(analysis["projects"])})
  <span class="help-tip" style="position:relative">?<span class="tip">All projects with their file, commit, variable, and secret counts. Click a project for its dependency graph.</span></span>
</h3>
{_search_bar("graph-projects", "Filter projects...")}
{proj_table}
{shared_sec}
{shared_vars}
{recent}
"""

    # FUSE mount status section
    fuse_html = ""
    try:
        fuse_mounts = []
        with open("/proc/mounts") as fm:
            for line in fm:
                if "fuse" in line.lower() and "temple" in line.lower():
                    fuse_mounts.append(line.split()[1])

        mount_status = (
            f'<span style="color:#4a9a6a">Mounted at {", ".join(fuse_mounts)}</span>'
            if fuse_mounts
            else '<span class="muted">Not mounted</span>'
        )

        fuse_html = f"""
<div style="border:1px solid #1e1e3a;border-radius:6px;padding:1rem;margin-bottom:1.5rem">
  <h3>FUSE Mount
    <span class="help-tip" style="position:relative">?<span class="tip">Mount the TempleDB database as a real filesystem. Projects appear as directories, files are read from/written to the DB. Writes auto-stage for VCS commit. No sync needed — edits go straight to the DB.</span></span>
  </h3>
  <p style="margin:0.5rem 0">Status: {mount_status}</p>
  <div style="display:flex;gap:0.5rem;margin-top:0.5rem">
    <button hx-post="/mount/toggle" hx-swap="outerHTML" class="sm">{'Unmount' if fuse_mounts else 'Mount {FUSE_MOUNT_PATH}'}</button>
  </div>
  <p class="muted" style="font-size:0.78rem;margin-top:0.5rem">
    {'Access files at: <code>' + fuse_mounts[0] + '/&lt;project&gt;/</code>' if fuse_mounts else
     'After mounting, access files at <code>{FUSE_MOUNT_PATH}/&lt;project&gt;/</code>. Writes auto-stage in VCS.'}
  </p>
</div>
"""
    except Exception:
        pass

    # ── View tabs ────────────────────────────────────────────────────────────
    view_tabs = "".join(
        f'<a href="/graph?view={k}" class="tab{"active" if view == k else ""}">{label}</a>'
        for k, label in [("overview", "Overview"), ("symbols", "Code Intelligence")]
    )

    # ── Symbols view ──────────────────────────────────────────────────────────
    symbols_html = ""
    if view == "symbols":
        symbols_html = _code_symbols_html(project=project, kind=kind)

    body = f"""
<h2>Graph
  <span class="help-tip" style="position:relative">?<span class="tip">Knowledge graph: explore relationships across projects, secrets, env vars, deployments, and code. Use the search bar to find anything.</span></span>
</h2>

<form method="get" action="/graph" style="margin-bottom:1rem;display:flex;gap:0.5rem;align-items:center">
  <input type="text" name="q" value="{html.escape(q)}" placeholder="Search everything: projects, files, secrets, commits, symbols..."
    style="flex:1;max-width:600px" autocomplete="off">
  <button type="submit" class="primary">Search</button>
  <input type="hidden" name="view" value="{html.escape(view)}">
</form>

{search_result}
<div class="tabs">{view_tabs}</div>
{fuse_html}
{overview_html if view == "overview" else ""}
{symbols_html}
"""
    return _base("Graph", body, "graph")


@app.get("/graph/{slug}", response_class=HTMLResponse)
def graph_project(slug: str):
    """Project dependency graph detail view."""
    from knowledge_graph import project_dependencies, changes_since_deploy

    deps = project_dependencies(slug)
    if "error" in deps:
        return _base("Not Found", f'<p class="muted">{html.escape(deps["error"])}</p>', "graph")

    proj = deps["project"]
    changes = changes_since_deploy(slug)

    # File types
    ft_rows = [[html.escape(ft["type_name"]), str(ft["count"])] for ft in deps["file_types"]]
    ft_table = _table(["Type", "Count"], ft_rows, "No files.") if ft_rows else ""

    # Env vars
    ev_rows = []
    for ev in deps["env_vars"]:
        val = "****" if ev["is_secret"] else html.escape((ev["var_value"] or "")[:50])
        ev_rows.append([f'<code>{html.escape(ev["var_name"])}</code>', val])
    ev_table = _table(["Variable", "Value"], ev_rows, "No env vars.")

    # Secrets
    sec_rows = [[f'<code>{html.escape(s["secret_name"])}</code>',
                  f'<span class="badge">{html.escape(s["profile"])}</span>'] for s in deps["secrets"]]
    sec_table = _table(["Secret", "Profile"], sec_rows, "No secrets.")

    # Flake inputs
    fi_html = ""
    if deps["flake_inputs"]:
        fi_rows = [[f'<code>{html.escape(fi["key"].replace("nixos.flake.input.", ""))}</code>',
                     f'<span class="muted" style="font-size:0.78rem">{html.escape(fi["value"])}</span>']
                    for fi in deps["flake_inputs"]]
        fi_html = f'<h3 style="margin-top:1rem">Flake Inputs</h3>{_table(["Input", "URL"], fi_rows)}'

    # Symbols
    sym_html = ""
    if deps["symbols"]:
        sym_rows = [[f'<code>{html.escape(s.get("symbol_name", ""))}</code>',
                      f'<span class="badge">{html.escape(s["symbol_type"])}</span>',
                      f'<span class="muted" style="font-size:0.78rem">{html.escape(s["file_path"])}</span>']
                     for s in deps["symbols"][:20]]
        sym_html = f'<h3 style="margin-top:1rem">Code Symbols ({len(deps["symbols"])})</h3>{_table(["Symbol", "Type", "File"], sym_rows)}'

    # Deploy info
    d = deps.get("deploys", {})
    deploy_html = ""
    if d.get("total"):
        deploy_html = f"""
<h3 style="margin-top:1rem">Deployments</h3>
<table>
<tr><td style="width:150px">Total</td><td>{d.get('total', 0)}</td></tr>
<tr><td>Successful</td><td>{d.get('successful', 0)}</td></tr>
<tr><td>Last deploy</td><td>{html.escape(str(d.get('last_deploy', 'never')))}</td></tr>
</table>"""

    # Changes since deploy
    changes_html = ""
    if not changes.get("error"):
        commits = changes.get("commits_since", [])
        uncommitted = changes.get("uncommitted_changes", [])
        if commits or uncommitted:
            c_rows = [[f'<code>{html.escape(c["commit_hash"][:8])}</code>',
                        html.escape((c.get("commit_message", "") or "")[:60]),
                        f'<span class="muted">{html.escape(c.get("commit_timestamp", "")[:10])}</span>']
                       for c in commits[:10]]
            u_rows = [[html.escape(u["file_path"]),
                        f'<span class="badge">{html.escape(u["state"])}</span>',
                        "staged" if u.get("staged") else ""]
                       for u in uncommitted]
            changes_html = f'<h3 style="margin-top:1rem">Changes Since Last Deploy</h3>'
            if c_rows:
                changes_html += f'<p class="muted" style="margin-bottom:0.5rem">{len(commits)} commit(s)</p>'
                changes_html += _table(["Hash", "Message", "Date"], c_rows)
            if u_rows:
                changes_html += f'<p class="muted" style="margin-bottom:0.5rem">{len(uncommitted)} uncommitted</p>'
                changes_html += _table(["File", "State", "Staged"], u_rows)

    body = f"""
<h2><a href="/graph" style="color:#808098">Graph</a> / {html.escape(slug)}</h2>
<div style="margin-bottom:1rem">
  <span class="badge">{html.escape(proj.get('project_type', '') or 'regular')}</span>
  <span class="muted" style="margin-left:0.5rem">{html.escape(proj.get('repo_url', '') or '')}</span>
</div>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:1.5rem">
<div>
  <h3>File Types</h3>
  {ft_table}
  <h3 style="margin-top:1rem">Env Vars ({len(deps['env_vars'])})</h3>
  {ev_table}
  <h3 style="margin-top:1rem">Secrets ({len(deps['secrets'])})</h3>
  {sec_table}
</div>
<div>
  {fi_html}
  {sym_html}
  {deploy_html}
  {changes_html}
</div>
</div>
"""
    return _base(f"Graph: {slug}", body, "graph")


# ── Schema Browser ────────────────────────────────────────────────────────────

@app.get("/schema-browser", response_class=HTMLResponse)
def schema_browser(table: str = Query(""), q: str = Query("")):
    conn = query_one.__self__ if hasattr(query_one, '__self__') else None
    # Get fresh connection for schema queries
    import sqlite3 as _sqlite3
    from db_utils import DB_PATH
    db = _sqlite3.connect(DB_PATH)
    db.row_factory = _sqlite3.Row

    # Get all tables with row counts
    tables_raw = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()

    table_info = []
    for t in tables_raw:
        name = t["name"]
        try:
            count = db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            cols = db.execute(f'PRAGMA table_info("{name}")').fetchall()
            table_info.append({"name": name, "rows": count, "cols": len(cols)})
        except Exception:
            table_info.append({"name": name, "rows": -1, "cols": 0})

    # Get views
    views_raw = db.execute(
        "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"
    ).fetchall()

    # Sidebar: table list
    sidebar_rows = []
    for t in table_info:
        active = ' style="color:#e94560;font-weight:bold"' if t["name"] == table else ""
        row_badge = f'<span class="muted" style="font-size:0.7rem">{t["rows"]}</span>' if t["rows"] >= 0 else ""
        sidebar_rows.append(
            f'<a href="/schema-browser?table={html.escape(t["name"])}" '
            f'style="display:block;padding:0.15rem 0.4rem;color:#808098;text-decoration:none;font-size:0.78rem;border-radius:3px'
            f'{";background:#1a1a30;color:#e94560" if t["name"] == table else ""}">'
            f'{html.escape(t["name"])} {row_badge}</a>'
        )

    # Detail panel
    detail_html = ""
    if table:
        # Column info
        cols = db.execute(f'PRAGMA table_info("{table}")').fetchall()
        col_rows = []
        for c in cols:
            pk = '<span class="badge green">PK</span>' if c["pk"] else ""
            nn = '<span class="badge">NOT NULL</span>' if c["notnull"] else ""
            dflt = f'<span class="muted">{html.escape(str(c["dflt_value"]))}</span>' if c["dflt_value"] else ""
            col_rows.append([
                f'<code>{html.escape(c["name"])}</code>',
                f'<span class="badge blue">{html.escape(c["type"] or "ANY")}</span>',
                f'{pk} {nn}'.strip(),
                dflt,
            ])
        col_table = _table(["Column", "Type", "Constraints", "Default"], col_rows)

        # Indexes
        indexes = db.execute(f'PRAGMA index_list("{table}")').fetchall()
        idx_rows = []
        for idx in indexes:
            idx_cols = db.execute(f'PRAGMA index_info("{idx["name"]}")').fetchall()
            col_names = ", ".join(c["name"] for c in idx_cols)
            unique = '<span class="badge green">UNIQUE</span>' if idx["unique"] else ""
            idx_rows.append([
                f'<code style="font-size:0.75rem">{html.escape(idx["name"])}</code>',
                col_names,
                unique,
            ])
        idx_table = _table(["Index", "Columns", "Unique"], idx_rows, "No indexes.") if idx_rows else ""

        # Foreign keys
        fks = db.execute(f'PRAGMA foreign_key_list("{table}")').fetchall()
        fk_rows = []
        for fk in fks:
            fk_rows.append([
                f'<code>{html.escape(fk["from"])}</code>',
                f'<a href="/schema-browser?table={html.escape(fk["table"])}">{html.escape(fk["table"])}</a>',
                f'<code>{html.escape(fk["to"])}</code>',
                html.escape(fk["on_delete"] or ""),
            ])
        fk_table = _table(["Column", "References", "Foreign Column", "On Delete"], fk_rows, "No foreign keys.") if fk_rows else ""

        # Sample data
        try:
            row_count = db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            sample = db.execute(f'SELECT * FROM "{table}" LIMIT 20').fetchall()
            if sample:
                headers = [desc[0] for desc in db.execute(f'SELECT * FROM "{table}" LIMIT 0').description]
                data_rows = []
                for row in sample:
                    cells = []
                    for h in headers:
                        val = row[h]
                        if val is None:
                            cells.append('<span class="muted">NULL</span>')
                        elif isinstance(val, bytes):
                            cells.append(f'<span class="muted">[{len(val)} bytes]</span>')
                        else:
                            s = html.escape(str(val))
                            cells.append(s[:80] + ("..." if len(s) > 80 else ""))
                    data_rows.append(cells)
                sample_table = f'<p class="muted" style="margin-bottom:0.5rem">{row_count} total rows (showing first 20)</p>'
                sample_table += _table(headers, data_rows, table_id="sample-data")
            else:
                sample_table = '<p class="muted">Table is empty.</p>'
        except Exception as e:
            sample_table = f'<p class="muted">Could not query: {html.escape(str(e))}</p>'

        # SQL to create
        create_sql = db.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        create_block = ""
        if create_sql and create_sql[0]:
            create_block = f'<details style="margin-top:1rem"><summary style="cursor:pointer;color:#808098;font-size:0.8rem">CREATE TABLE SQL</summary><pre style="margin-top:0.5rem;font-size:0.75rem">{html.escape(create_sql[0])}</pre></details>'

        detail_html = f"""
<h3>{html.escape(table)}
  <span class="badge">{row_count} rows</span>
  <span class="badge blue">{len(cols)} columns</span>
</h3>

<h3 style="margin-top:1rem">Columns</h3>
{col_table}

{"<h3 style='margin-top:1rem'>Indexes</h3>" + idx_table if idx_table else ""}
{"<h3 style='margin-top:1rem'>Foreign Keys</h3>" + fk_table if fk_table else ""}

<h3 style="margin-top:1rem">Data</h3>
{_search_bar("sample-data", "Filter rows...")}
{sample_table}

{create_block}
"""
    else:
        # Overview: show all tables grouped by prefix
        groups = {}
        for t in table_info:
            prefix = t["name"].split("_")[0] if "_" in t["name"] else t["name"]
            groups.setdefault(prefix, []).append(t)

        overview_rows = []
        for t in sorted(table_info, key=lambda x: -x["rows"]):
            overview_rows.append([
                f'<a href="/schema-browser?table={html.escape(t["name"])}">{html.escape(t["name"])}</a>',
                f'{t["rows"]:,}' if t["rows"] >= 0 else "?",
                str(t["cols"]),
            ])

        detail_html = f"""
<h3>Tables ({len(table_info)})
  <span class="help-tip" style="position:relative">?<span class="tip">Click a table to see its columns, indexes, foreign keys, and sample data. Tables sorted by row count.</span></span>
</h3>
{_search_bar("schema-overview", "Filter tables...")}
{_table(["Table", "Rows", "Columns"], overview_rows, table_id="schema-overview")}

<h3 style="margin-top:1.5rem">Views ({len(views_raw)})</h3>
<div style="display:flex;flex-wrap:wrap;gap:0.3rem">
{"".join(f'<span class="badge" style="font-size:0.72rem">{html.escape(v["name"])}</span>' for v in views_raw)}
</div>
"""

    db.close()

    body = f"""
<h2>Schema Browser</h2>
<div style="display:flex;gap:1.5rem">
  <div style="width:220px;max-height:80vh;overflow-y:auto;border-right:1px solid #1e1e3a;padding-right:1rem;flex-shrink:0">
    <input type="search" placeholder="Filter tables..." oninput="
      var q=this.value.toLowerCase();
      this.parentElement.querySelectorAll('a').forEach(function(a){{
        a.style.display=a.textContent.toLowerCase().includes(q)?'':'none';
      }});
    " style="width:100%;margin-bottom:0.5rem;background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;padding:0.25rem 0.4rem;border-radius:4px;font-family:monospace;font-size:0.78rem" autocomplete="off">
    {"".join(sidebar_rows)}
  </div>
  <div style="flex:1;overflow:auto">
    {detail_html}
  </div>
</div>
"""
    return _base("Schema Browser", body, "schema-browser")


# ── Settings ──────────────────────────────────────────────────────────────────

@app.get("/settings", response_class=HTMLResponse)
def settings_redirect(q: str = Query(""), host: str = Query("")):
    from fastapi.responses import RedirectResponse
    params = []
    if q: params.append(f"q={q}")
    if host: params.append(f"host={host}")
    qs = "?" + "&".join(params) if params else ""
    return RedirectResponse(f"/system{qs}")


@app.get("/status", response_class=HTMLResponse)
def status_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/system")


@app.get("/system", response_class=HTMLResponse)
def system_page(q: str = Query(""), host: str = Query("")):
    import socket
    current_host = socket.gethostname()

    # ── System Config (grouped by host) ──────────────────────────────────────
    configs = query_all(
        "SELECT key, value, hostname, updated_at FROM system_config ORDER BY hostname, key"
    )

    # Collect unique hostnames for filter
    all_hosts = sorted({c["hostname"] or "(untagged)" for c in configs})

    # Filter by host if specified
    if host:
        filter_host = None if host == "(untagged)" else host
        configs = [c for c in configs if (c["hostname"] or "(untagged)") == (host or "(untagged)")]

    # Group by hostname
    by_host = defaultdict(list)
    for c in configs:
        h = c["hostname"] or "(untagged)"
        by_host[h].append(c)

    # Host filter bar
    host_options = ''.join(
        f'<option value="{html.escape(h)}"{" selected" if h == host else ""}>{html.escape(h)}'
        f'{"  (this machine)" if h == current_host else ""}</option>'
        for h in all_hosts
    )
    host_filter = f"""
<form method="get" action="/system" style="margin-bottom:1rem;display:flex;gap:0.5rem;align-items:center">
  <select name="host" onchange="this.form.submit()"
    style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;padding:0.3rem 0.5rem;border-radius:4px;font-family:monospace;font-size:0.85rem">
    <option value="">All hosts ({len(configs)} keys)</option>
    {host_options}
  </select>
  <span class="muted" style="font-size:0.8rem">Current: <strong>{html.escape(current_host)}</strong></span>
</form>
"""

    # Build grouped config sections
    config_sections_html = ""
    for hostname in sorted(by_host.keys(), key=lambda h: (h != current_host, h)):
        host_configs = by_host[hostname]
        is_current = hostname == current_host
        host_badge = (
            f'<span style="color:{"#4a9a6a" if is_current else "#a0a0c0"};font-weight:600">'
            f'{html.escape(hostname)}</span>'
            f'{"  <span class=\"badge\" style=\"font-size:0.7rem\">this machine</span>" if is_current else ""}'
        )

        config_rows = []
        for c in host_configs:
            key = html.escape(c["key"])
            val = html.escape(c["value"] or "")

            edit_form = (
                f'<form hx-post="/config/set" hx-swap="outerHTML" style="display:inline">'
                f'<input type="hidden" name="key" value="{key}">'
                f'<input type="hidden" name="hostname" value="{html.escape(hostname)}">'
                f'<input type="text" name="value" value="{val}" class="inline-edit" '
                f'style="width:350px" onchange="this.form.requestSubmit()">'
                f'</form>'
            )
            del_btn = (
                f'<form hx-post="/config/delete" hx-swap="outerHTML" hx-confirm="Delete {key}?" style="display:inline">'
                f'<input type="hidden" name="key" value="{key}">'
                f'<button class="sm danger" type="submit">x</button>'
                f'</form>'
            )
            config_rows.append([
                f'<code style="font-size:0.78rem">{key}</code>',
                edit_form,
                html.escape((c["updated_at"] or "")[:10]),
                del_btn,
            ])

        config_table = _table(["Key", "Value", "Updated", ""], config_rows, "No config keys.", f"config-tbl-{hostname}")
        config_sections_html += f"""
<details {"open" if is_current or len(by_host) == 1 else ""} style="margin-bottom:1rem;border:1px solid {"#2a4a3a" if is_current else "#1e1e3a"};border-radius:6px;padding:0.75rem">
  <summary style="cursor:pointer;font-size:0.9rem">{host_badge} <span class="muted">({len(host_configs)} keys)</span></summary>
  <div style="margin-top:0.5rem">
    {_search_bar(f"config-tbl-{hostname}", "Filter keys...", "300px")}
    {config_table}
  </div>
</details>
"""

    # Add config form (with hostname)
    host_opts_for_add = ''.join(
        f'<option value="{html.escape(h)}"{" selected" if h == current_host else ""}>{html.escape(h)}</option>'
        for h in all_hosts if h != "(untagged)"
    )
    add_config = f"""
<details style="margin-top:0.5rem">
<summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">+ Add config key</summary>
<form hx-post="/config/set" hx-swap="outerHTML" style="margin-top:0.5rem;display:flex;gap:0.5rem;align-items:center">
  <select name="hostname" style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;padding:0.3rem 0.5rem;border-radius:4px;font-size:0.85rem">
    {host_opts_for_add}
  </select>
  <input type="text" name="key" placeholder="key.name" style="width:200px" required>
  <input type="text" name="value" placeholder="value" style="width:250px" required>
  <button type="submit" class="sm primary">Add</button>
</form>
</details>
"""

    # ── Dotfiles ──────────────────────────────────────────────────────────────
    dotfiles_html = ""
    try:
        df_row = query_one("SELECT value FROM system_config WHERE key = 'nixos.dotfiles'")
        if df_row and df_row["value"]:
            manifest = json.loads(df_row["value"])
            checkouts_dir = Path.home() / ".config" / "templedb" / "checkouts"
            df_rows = []
            for entry in manifest:
                source_abs = checkouts_dir / entry["project"] / entry["source"]
                target = Path(entry["target"]).expanduser()
                if target.is_symlink() and target.resolve() == source_abs.resolve():
                    st = '<span style="color:#4a9a6a">linked</span>'
                elif target.exists():
                    st = '<span style="color:#e9a045">conflict</span>'
                else:
                    st = '<span class="muted">not linked</span>'

                rm_form = (
                    f'<form hx-post="/dotfiles/remove" hx-swap="outerHTML" style="display:inline">'
                    f'<input type="hidden" name="project" value="{html.escape(entry["project"])}">'
                    f'<input type="hidden" name="source" value="{html.escape(entry["source"])}">'
                    f'<button class="sm danger" type="submit">x</button>'
                    f'</form>'
                )
                df_rows.append([
                    f'<code>{html.escape(entry["source"])}</code>',
                    f'<span class="badge">{html.escape(entry["project"])}</span>',
                    f'<code class="muted" style="font-size:0.78rem">{html.escape(entry["target"])}</code>',
                    st, rm_form,
                ])
            dotfiles_html = _table(["Source", "Project", "Target", "Status", ""], df_rows, "No dotfiles.", "df-tbl")
        else:
            dotfiles_html = '<p class="muted">No dotfiles configured.</p>'
    except Exception:
        dotfiles_html = '<p class="muted">Could not load dotfiles.</p>'

    add_dotfile = """
<details style="margin-top:0.5rem">
<summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">+ Add dotfile mapping</summary>
<form hx-post="/dotfiles/add" hx-swap="outerHTML" style="margin-top:0.5rem;display:flex;gap:0.5rem;align-items:center">
  <input type="text" name="project" placeholder="project slug" style="width:150px" required>
  <input type="text" name="source" placeholder="source (e.g. .spacemacs)" style="width:200px" required>
  <input type="text" name="target" placeholder="target (e.g. ~/.spacemacs)" style="width:200px" required>
  <button type="submit" class="sm primary">Add</button>
</form>
</details>
"""

    # ── Help text ─────────────────────────────────────────────────────────────
    help_html = """
<details style="margin-top:1.5rem;border:1px solid #1e1e3a;border-radius:6px;padding:1rem">
<summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">Help: What do these settings control?</summary>
<div style="margin-top:0.75rem;font-size:0.8rem;color:#a0a0c0;line-height:1.6">
<p><strong>System Config</strong> — key-value pairs that control TempleDB behavior and NixOS generation.</p>
<table style="margin:0.5rem 0">
<tr><td style="width:250px"><code>nixos.username</code></td><td>Your username (used in generated NixOS config)</td></tr>
<tr><td><code>nixos.flake_output</code></td><td>NixOS hostname for <code>nixos-rebuild switch --flake .#&lt;hostname&gt;</code></td></tr>
<tr><td><code>nixos.let.home.homeDir</code></td><td>Home directory path (portable across machines)</td></tr>
<tr><td><code>nixos.dotfiles</code></td><td>JSON manifest of dotfile symlink mappings</td></tr>
<tr><td><code>woofs.*</code></td><td>Woofs deployment service configuration</td></tr>
<tr><td><code>gcs.backup_bucket</code></td><td>GCS bucket name for cloud backups</td></tr>
</table>
<p><strong>Dotfiles</strong> — symlinks from TempleDB checkouts to your home directory. Managed by <code>templedb nixos dotfiles-*</code>.</p>
<p><strong>Actions</strong></p>
<table style="margin:0.5rem 0">
<tr><td style="width:180px"><strong>Sync</strong></td><td>Re-import project files from disk into the database</td></tr>
<tr><td><strong>Mount {FUSE_MOUNT_PATH}</strong></td><td>Mount the database as a FUSE filesystem (read/write, auto-stages changes)</td></tr>
<tr><td><strong>Generate NixOS</strong></td><td>Regenerate all NixOS config from DB: let-bindings, templates, modules, flake inputs</td></tr>
<tr><td><strong>Apply Dotfiles</strong></td><td>Create/update symlinks from checkout files to home directory</td></tr>
<tr><td><strong>Backup to GCS</strong></td><td>Upload database to Google Cloud Storage bucket</td></tr>
</table>
</div>
</details>
"""

    # ── NixOS Host Configs (parsed from nix files) ─────────────────────────────
    nixos_hosts_html = ""
    try:
        sys_proj = query_one("SELECT id FROM projects WHERE slug = 'system_config'")
        if sys_proj:
            sys_pid = sys_proj["id"]
            host_files = query_all("""
                SELECT pf.file_path, cb.content_text
                FROM project_files pf
                JOIN file_contents fc ON fc.file_id = pf.id
                JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
                WHERE pf.project_id = ? AND (
                    pf.file_path LIKE 'hosts/%.nix'
                    OR pf.file_path = 'configuration.nix'
                    OR pf.file_path = 'home.nix'
                )
                ORDER BY pf.file_path
            """, (sys_pid,))

            for hf in host_files:
                fpath = hf["file_path"]
                content = hf["content_text"] or ""
                lines = content.split("\n")

                # Derive host from filename
                if fpath.startswith("hosts/"):
                    file_host = fpath.replace("hosts/", "").replace(".nix", "")
                elif fpath == "configuration.nix":
                    file_host = "(shared)"
                elif fpath == "home.nix":
                    file_host = "(home-manager)"
                else:
                    file_host = fpath

                # Parse packages, services, and key settings
                packages = []
                services = []
                other_settings = []
                in_packages = False
                in_block = None
                brace_depth = 0

                for i, line in enumerate(lines):
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue

                    # Track package blocks
                    if any(kw in stripped for kw in ["systemPackages", "home.packages", "withPackages", "extraPackages"]):
                        in_packages = True
                        continue
                    if in_packages:
                        if "];" in stripped or stripped == "];":
                            in_packages = False
                        elif stripped and not stripped.startswith("(") and not stripped.startswith(")"):
                            pkg = stripped.rstrip(";").strip()
                            if pkg and pkg not in ["with pkgs;", "[", "]"]:
                                packages.append(pkg)
                        continue

                    # Track services
                    if stripped.startswith("services.") and "=" in stripped:
                        services.append(stripped.rstrip(";"))
                    # Track networking, boot, hardware
                    elif any(stripped.startswith(pf) for pf in ["networking.", "boot.", "hardware.", "programs."]):
                        if "=" in stripped:
                            other_settings.append(stripped.rstrip(";"))

                # Build section
                is_current_host = file_host == current_host
                host_color = "#4a9a6a" if is_current_host else "#a0a0c0"

                pkg_html = ""
                if packages:
                    pkg_list = "".join(f"<li><code>{html.escape(p)}</code></li>" for p in sorted(set(packages))[:50])
                    pkg_html = f'<div style="margin:0.5rem 0"><strong style="font-size:0.8rem;color:#a0a0c0">Packages ({len(set(packages))})</strong><ul style="columns:3;font-size:0.78rem;margin:0.3rem 0">{pkg_list}</ul></div>'

                svc_html = ""
                if services:
                    svc_list = "".join(f"<li><code>{html.escape(s[:60])}</code></li>" for s in services[:20])
                    svc_html = f'<div style="margin:0.5rem 0"><strong style="font-size:0.8rem;color:#a0a0c0">Services ({len(services)})</strong><ul style="font-size:0.78rem;margin:0.3rem 0">{svc_list}</ul></div>'

                settings_html = ""
                if other_settings:
                    set_list = "".join(f"<li><code>{html.escape(s[:70])}</code></li>" for s in other_settings[:20])
                    settings_html = f'<div style="margin:0.5rem 0"><strong style="font-size:0.8rem;color:#a0a0c0">Settings ({len(other_settings)})</strong><ul style="font-size:0.78rem;margin:0.3rem 0">{set_list}</ul></div>'

                if packages or services or other_settings:
                    badge = f'{"  <span class=\"badge\" style=\"font-size:0.7rem\">this machine</span>" if is_current_host else ""}'
                    nixos_hosts_html += f"""
<details {"open" if is_current_host else ""} style="margin-bottom:0.75rem;border:1px solid {"#2a4a3a" if is_current_host else "#1e1e3a"};border-radius:6px;padding:0.75rem">
  <summary style="cursor:pointer;font-size:0.9rem">
    <span style="color:{host_color};font-weight:600">{html.escape(file_host)}</span>{badge}
    <span class="muted" style="font-size:0.78rem">— {html.escape(fpath)}</span>
  </summary>
  {pkg_html}{svc_html}{settings_html}
</details>
"""
    except Exception as e:
        nixos_hosts_html = f'<p class="muted">Could not parse NixOS configs: {html.escape(str(e))}</p>'

    # ── Stats (from old Status page) ─────────────────────────────────────────
    project_count = (query_one("SELECT COUNT(*) AS n FROM projects") or {}).get("n", 0)
    file_count = (query_one("SELECT COUNT(*) AS n FROM project_files") or {}).get("n", 0)
    commit_count = (query_one("SELECT COUNT(*) AS n FROM vcs_commits") or {}).get("n", 0)
    loc = (query_one("SELECT COALESCE(SUM(lines_of_code),0) AS n FROM project_files") or {}).get("n", 0)

    try:
        from config import default_db_path
        db_path = default_db_path()
        db_size = os.path.getsize(db_path) / 1024 / 1024
        db_info = f'{db_size:.1f} MB — <span class="muted">{html.escape(str(db_path))}</span>'
    except Exception:
        db_path = None
        db_info = "unknown"

    stats = [
        (project_count, "Projects"),
        (f"{file_count:,}", "Files"),
        (f"{commit_count:,}", "Commits"),
        (f"{loc:,}", "Lines of Code"),
    ]
    stats_html = "".join(
        f'<div class="stat"><div class="val">{v}</div><div class="key">{k}</div></div>'
        for v, k in stats
    )

    # ── Migration status ──────────────────────────────────────────────────────
    migration_html = ""
    try:
        from migrator import Migrator
        from db_utils import DB_PATH
        m = Migrator(DB_PATH)
        mig_status = m.status()
        applied = sum(1 for s in mig_status if s["applied"])
        pending = sum(1 for s in mig_status if not s["applied"])
        total = len(mig_status)

        if pending == 0:
            mig_badge = f'<span class="badge green">all {applied} applied</span>'
        else:
            mig_badge = f'<span class="badge red">{pending} pending</span>'

        mig_rows = []
        for s in mig_status:
            status_cell = (
                f'<span style="color:#4a9a6a">applied</span> <span class="muted">{html.escape((s["applied_at"] or "")[:10])}</span>'
                if s["applied"]
                else '<span style="color:#e94560">pending</span>'
            )
            mig_rows.append([
                f'<code>{html.escape(s["filename"])}</code>',
                status_cell,
                f'<code class="muted" style="font-size:0.72rem">{html.escape(s["file_hash"] or "")}</code>',
            ])

        mig_table = _table(["Migration", "Status", "Hash"], mig_rows)
        migration_html = f"""
<h3 style="margin-top:1.5rem">Database Migrations {mig_badge}</h3>
<details style="margin-top:0.5rem">
  <summary style="cursor:pointer;color:#a0a0c0;font-size:0.85rem">{applied}/{total} migrations applied</summary>
  <div style="margin-top:0.5rem">{mig_table}</div>
</details>
"""
        if pending > 0:
            migration_html += '<p style="margin-top:0.5rem;color:#e94560;font-size:0.85rem">Run <code>templedb admin db migrate</code> to apply pending migrations</p>'
    except Exception as e:
        migration_html = f'<p class="muted" style="margin-top:1rem">Migrations: could not check ({html.escape(str(e))})</p>'

    # ── Bootstrap readiness ───────────────────────────────────────────────────
    bootstrap_html = ""
    try:
        age_paths = [
            Path.home() / ".age" / "key.txt",
            Path.home() / ".config" / "sops" / "age" / "keys.txt",
        ]
        age_ok = any(p.exists() for p in age_paths)
        age_cell = ('<span style="color:#4a9a6a">found</span>' if age_ok
                    else '<span style="color:#e94560">missing</span>')

        checkout_dir = Path.home() / ".config" / "templedb" / "checkouts"
        checkout_count = sum(1 for p in checkout_dir.iterdir() if p.is_dir()) if checkout_dir.exists() else 0

        # FUSE mount status
        fuse_mounts = []
        try:
            with open("/proc/mounts") as fm:
                for line in fm:
                    if "fuse" in line.lower() and "temple" in line.lower():
                        parts = line.split()
                        fuse_mounts.append(parts[1])
        except Exception:
            pass

        fuse_cell = (
            f'<span style="color:#4a9a6a">mounted at {", ".join(fuse_mounts)}</span>'
            if fuse_mounts
            else '<span class="muted">not mounted</span>'
        )

        bootstrap_html = f"""
<h3 style="margin-top:1.5rem">Bootstrap Readiness</h3>
<table>
<tr><td style="width:180px">Age key</td><td>{age_cell}</td></tr>
<tr><td>Project checkouts</td><td>{checkout_count} checked out</td></tr>
<tr><td>FUSE mount</td><td>{fuse_cell}</td></tr>
<tr><td>Database</td><td>{db_info}</td></tr>
</table>
<div style="display:flex;gap:0.5rem;margin-top:0.75rem;flex-wrap:wrap">
  <button hx-post="/mount/toggle" hx-swap="outerHTML" style="font-size:0.78rem">{'Unmount' if fuse_mounts else 'Mount'} {FUSE_MOUNT_PATH}</button>
  <button hx-post="/db/migrate" hx-swap="outerHTML" style="font-size:0.78rem">Run Migrations</button>
  <button hx-post="/nixos/dotfiles-apply" hx-swap="outerHTML" style="font-size:0.78rem">Apply Dotfiles</button>
  <button hx-post="/nixos/generate-all" hx-swap="outerHTML" style="font-size:0.78rem">Generate NixOS</button>
  <button hx-post="/backup/gcs" hx-swap="outerHTML" style="font-size:0.78rem">Backup to GCS</button>
</div>
"""
    except Exception:
        pass

    # ── Daemon Status ─────────────────────────────────────────────────────
    daemon_html = ""
    try:
        import subprocess as _sp

        # Services to check: from DB + known TempleDB services
        service_checks = []

        # User services from DB
        db_user_svcs = query_all(
            "SELECT key FROM system_config WHERE key LIKE 'nixos.service.user.%'"
        )
        for s in db_user_svcs:
            name = s["key"].replace("nixos.service.user.", "")
            service_checks.append(("user", f"{name}.service"))

        # System services from DB
        db_sys_svcs = query_all(
            "SELECT key FROM system_config WHERE key LIKE 'nixos.attr.services.%.enable'"
        )
        for s in db_sys_svcs:
            # nixos.attr.services.pipewire.enable → pipewire
            name = s["key"].replace("nixos.attr.services.", "").replace(".enable", "")
            # Skip nested attrs like pipewire.alsa.enable
            if "." not in name:
                service_checks.append(("system", f"{name}.service"))

        # Always check git-daemon
        service_checks.append(("system", "git-daemon.service"))

        daemon_rows = []
        for scope, svc_name in service_checks:
            try:
                if scope == "user":
                    r = _sp.run(
                        ["systemctl", "--user", "is-active", svc_name],
                        capture_output=True, text=True, timeout=3
                    )
                    status_r = _sp.run(
                        ["systemctl", "--user", "show", svc_name,
                         "--property=ActiveState,SubState,MainPID,MemoryCurrent"],
                        capture_output=True, text=True, timeout=3
                    )
                else:
                    r = _sp.run(
                        ["systemctl", "is-active", svc_name],
                        capture_output=True, text=True, timeout=3
                    )
                    status_r = _sp.run(
                        ["systemctl", "show", svc_name,
                         "--property=ActiveState,SubState,MainPID,MemoryCurrent"],
                        capture_output=True, text=True, timeout=3
                    )

                state = r.stdout.strip()
                props = {}
                if status_r.returncode == 0:
                    for line in status_r.stdout.strip().split("\n"):
                        if "=" in line:
                            k, v = line.split("=", 1)
                            props[k] = v

                if state == "active":
                    state_cell = '<span style="color:#4a9a6a">active</span>'
                elif state == "activating":
                    state_cell = '<span style="color:#e9a045">activating</span>'
                elif state == "failed":
                    state_cell = '<span style="color:#e94560">failed</span>'
                elif state == "inactive":
                    state_cell = '<span class="muted">inactive</span>'
                else:
                    state_cell = f'<span class="muted">{html.escape(state)}</span>'

                pid = props.get("MainPID", "")
                pid_cell = pid if pid and pid != "0" else ""
                mem = props.get("MemoryCurrent", "")
                if mem and mem != "[not set]":
                    try:
                        mem_mb = int(mem) / 1024 / 1024
                        mem_cell = f"{mem_mb:.1f} MB"
                    except Exception:
                        mem_cell = ""
                else:
                    mem_cell = ""

                scope_badge = f'<span class="badge{" blue" if scope == "user" else ""}">{scope}</span>'

                daemon_rows.append([
                    f'<code>{html.escape(svc_name)}</code>',
                    scope_badge,
                    state_cell,
                    pid_cell,
                    f'<span class="muted">{mem_cell}</span>',
                ])
            except Exception:
                daemon_rows.append([
                    f'<code>{html.escape(svc_name)}</code>',
                    f'<span class="badge">{scope}</span>',
                    '<span class="muted">?</span>',
                    "", "",
                ])

        if daemon_rows:
            daemon_html = f"""
<h3 style="margin-top:1.5rem">Daemons
  <span class="help-tip" style="position:relative">?<span class="tip">Systemd services managed by TempleDB NixOS config. User services run as your user, system services run as root.</span></span>
</h3>
{_table(["Service", "Scope", "Status", "PID", "Memory"], daemon_rows)}
"""
    except Exception:
        pass

    # ── Backup History (moved from Projects page) ──────────────────────────────
    backup_html = ""
    try:
        backups = query_all("""
            SELECT backed_up_at, provider, backup_path, size_bytes
            FROM backup_history ORDER BY backed_up_at DESC LIMIT 10
        """) if _backup_history_exists() else []
        backup_rows = [
            [
                html.escape((r["backed_up_at"] or "")[:16]),
                html.escape(r["provider"] or ""),
                f'<span class="muted" style="font-size:0.75rem">{html.escape(r["backup_path"] or "")}</span>',
                f'{r["size_bytes"] // 1024 // 1024} MB' if r["size_bytes"] else "",
            ]
            for r in backups
        ]
        backup_html = f"""
<h3 style="margin-top:1.5rem">Backups</h3>
<div class="row" style="margin-bottom:0.5rem">
  <form hx-post="/backup/local" hx-target="#sys-backup-result" hx-swap="innerHTML">
    <button type="submit" style="font-size:0.78rem">Backup Now (local)</button>
  </form>
  <form hx-post="/backup/gcs" hx-target="#sys-backup-result" hx-swap="innerHTML">
    <button type="submit" style="font-size:0.78rem">Backup to GCS</button>
  </form>
  <span id="sys-backup-result"></span>
</div>
{_table(["Time", "Provider", "Path", "Size"], backup_rows, "No backups recorded yet.")}
"""
    except Exception:
        pass

    # ── Schema Browser link ───────────────────────────────────────────────────
    schema_link = '<p style="margin-top:1rem"><a href="/schema-browser">Schema Browser</a> <span class="muted">— browse all tables, columns, indexes, and sample data</span></p>'

    # ── Assemble merged System page ───────────────────────────────────────────
    body = f"""
<h2>System</h2>
<div style="margin-bottom:1.5rem">{stats_html}</div>
<p class="muted">Database: {db_info}</p>

<div style="display:flex;gap:0.5rem;margin:1rem 0;flex-wrap:wrap">
  <button hx-post="/mount/toggle" hx-swap="outerHTML" style="font-size:0.78rem">Toggle FUSE Mount</button>
  <button hx-post="/db/migrate" hx-swap="outerHTML" style="font-size:0.78rem">Run Migrations</button>
  <button hx-post="/nixos/dotfiles-apply" hx-swap="outerHTML" style="font-size:0.78rem">Apply Dotfiles</button>
  <button hx-post="/nixos/generate-all" hx-swap="outerHTML" style="font-size:0.78rem">Generate NixOS</button>
  <button hx-post="/backup/gcs" hx-swap="outerHTML" style="font-size:0.78rem">Backup to GCS</button>
</div>

{migration_html}
{bootstrap_html}
{daemon_html}

<hr class="sep">

{backup_html}

<hr class="sep">

<h3>System Config
  <span class="help-tip" style="position:relative">?<span class="tip">Key-value pairs stored in system_config table, grouped by host. Edit inline — changes save on blur. Used by NixOS generation, dotfiles, backups.</span></span>
</h3>
{host_filter}
{config_sections_html}
{add_config}

<hr class="sep">

<h3>NixOS Host Configs
  <span class="help-tip" style="position:relative">?<span class="tip">Parsed from configuration.nix, home.nix, and hosts/*.nix in the system_config project. Shows packages, services, and key settings per host.</span></span>
</h3>
{nixos_hosts_html if nixos_hosts_html else '<p class="muted">No NixOS config files found in system_config project.</p>'}

<hr class="sep">

<h3>Dotfiles
  <span class="help-tip" style="position:relative">?<span class="tip">Symlinks from TempleDB project checkouts to your home directory. Apply with: templedb nixos dotfiles-apply</span></span>
</h3>
{dotfiles_html}
{add_dotfile}
<div style="margin-top:0.5rem">
  <button hx-post="/nixos/dotfiles-apply" hx-swap="outerHTML" class="sm">Apply All Dotfiles</button>
</div>

<hr class="sep">

<h3 style="margin-top:1.5rem">Third-Party Services &amp; APIs
  <span class="help-tip" style="position:relative">?<span class="tip">External services TempleDB integrates with. Not all are required — most are optional depending on your workflow.</span></span>
</h3>
<table>
<thead><tr><th>Service</th><th>Used For</th><th>Required?</th><th>Config</th></tr></thead>
<tbody>
<tr><td><strong>SQLite</strong></td><td>Core database</td><td><span class="badge green">core</span></td><td><code>~/.local/share/templedb/templedb.sqlite</code></td></tr>
<tr><td><strong>cr-sqlite</strong></td><td>CRDT sync between machines</td><td><span class="badge">optional</span></td><td><code>templedb sync init</code></td></tr>
<tr><td><strong>Git</strong></td><td>Checkout management, git daemon, git-export</td><td><span class="badge green">core</span></td><td>Built-in</td></tr>
<tr><td><strong>Nix / NixOS</strong></td><td>System config generation, flake inputs</td><td><span class="badge green">core</span></td><td><code>templedb nixos status</code></td></tr>
<tr><td><strong>FUSE</strong></td><td>Mount DB as filesystem at <code>{FUSE_MOUNT_PATH}/</code></td><td><span class="badge blue">recommended</span></td><td><code>templedb mount {FUSE_MOUNT_PATH}</code></td></tr>
<tr><td><strong>SOPS / Age</strong></td><td>Secret encryption</td><td><span class="badge blue">recommended</span></td><td><code>~/.age/key.txt</code></td></tr>
<tr><td><strong>GCS</strong></td><td>Cloud backup</td><td><span class="badge">optional</span></td><td><code>gcs.backup_bucket</code></td></tr>
<tr><td><strong>Tailscale</strong></td><td>Machine-to-machine sync</td><td><span class="badge">optional</span></td><td><code>templedb sync peers</code></td></tr>
<tr><td><strong>GitHub</strong></td><td>Flake inputs, git-export</td><td><span class="badge">optional</span></td><td><code>gh</code> CLI</td></tr>
<tr><td><strong>Cloudflare</strong></td><td>DNS management</td><td><span class="badge">optional</span></td><td><code>CF_API_TOKEN</code></td></tr>
<tr><td><strong>Claude / Anthropic</strong></td><td>AI-assisted coding, MCP server</td><td><span class="badge">optional</span></td><td><code>claude</code> CLI</td></tr>
</tbody>
</table>

{schema_link}

{help_html}
"""
    return _base("System", body, "system")


# ── Systemd Monitor ──────────────────────────────────────────────────────────

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


@app.get("/systemd", response_class=HTMLResponse)
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


@app.get("/systemd/{unit_name}", response_class=HTMLResponse)
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


@app.post("/systemd/{unit_name}/start", response_class=HTMLResponse)
def systemd_start(unit_name: str, scope: str = "user"):
    cmd = ["systemctl", "start", unit_name]
    if scope == "user":
        cmd.insert(1, "--user")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if r.returncode == 0:
        return HTMLResponse(_msg(f"Started {unit_name}", ok=True))
    return HTMLResponse(_msg(f"Failed: {r.stderr.strip()}", ok=False))


@app.post("/systemd/{unit_name}/stop", response_class=HTMLResponse)
def systemd_stop(unit_name: str, scope: str = "user"):
    cmd = ["systemctl", "stop", unit_name]
    if scope == "user":
        cmd.insert(1, "--user")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    if r.returncode == 0:
        return HTMLResponse(_msg(f"Stopped {unit_name}", ok=True))
    return HTMLResponse(_msg(f"Failed: {r.stderr.strip()}", ok=False))


@app.post("/systemd/{unit_name}/restart", response_class=HTMLResponse)
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


@app.get("/fleet-sync", response_class=HTMLResponse)
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


@app.post("/fleet-sync/probe/{machine_name}", response_class=HTMLResponse)
def fleet_sync_probe(machine_name: str):
    """Probe a single machine's sync state."""
    hosts = _fleet_sync_get_hosts()
    host_info = next((h for h in hosts if h["name"] == machine_name), None)
    if not host_info:
        return HTMLResponse('<span style="color:#e94560">Unknown machine</span>')
    result = _fleet_sync_probe(host_info, ["system_config", "templedb"])
    return HTMLResponse(_fleet_sync_format_probe(result, ["system_config", "templedb"]))


@app.post("/fleet-sync/probe-all", response_class=HTMLResponse)
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


@app.post("/fleet-sync/push/{machine_name}", response_class=HTMLResponse)
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

@app.get("/tests", response_class=HTMLResponse)
def tests_page():
    """Tests Dashboard — run QA tests against projects."""
    from test_runner import detect_project_type, PROJECT_TESTS, STRUCTURE_TESTS

    projects = query_all("SELECT slug, repo_url, name FROM projects ORDER BY slug")

    rows = []
    for p in projects:
        slug = p["slug"]
        checkout = Path.home() / ".config" / "templedb" / "checkouts" / slug
        repo_path = Path(p.get("repo_url") or "") if p.get("repo_url") else None

        # Pick best path
        if repo_path and repo_path.exists() and (
            (repo_path / "src" / "gui.py").exists() or
            (repo_path / "frontend" / "package.json").exists() or
            (repo_path / "package.json").exists() or
            (repo_path / "backend" / "app.py").exists() or
            (repo_path / "app.py").exists()
        ):
            project_path = repo_path
        elif checkout.exists():
            project_path = checkout
        elif repo_path and repo_path.exists():
            project_path = repo_path
        else:
            project_path = None

        if not project_path:
            continue

        ptype = detect_project_type(project_path)
        has_tests = slug in PROJECT_TESTS
        has_struct = slug in STRUCTURE_TESTS

        badges = []
        if has_tests:
            badges.append('<span style="background:#1a3a1a;color:#8f8;padding:1px 6px;border-radius:3px;font-size:0.72rem">server tests</span>')
        if has_struct:
            badges.append('<span style="background:#1a2a3a;color:#8af;padding:1px 6px;border-radius:3px;font-size:0.72rem">structure tests</span>')
        if not badges:
            badges.append('<span style="color:#606080;font-size:0.72rem">auto-detect only</span>')

        run_btn = (
            f'<button hx-post="/tests/run/{slug}" '
            f'hx-target="#test-result-{slug}" hx-swap="innerHTML" '
            f'hx-indicator="#test-spinner-{slug}" '
            f'style="background:#1a1a3a;border:1px solid #2a2a4a;color:#d0d0e8;'
            f'padding:2px 8px;border-radius:3px;cursor:pointer;font-family:monospace;font-size:0.78rem">'
            f'Run Tests</button>'
            f'<span id="test-spinner-{slug}" class="htmx-indicator" style="color:#606080;font-size:0.72rem"> running...</span>'
        )

        rows.append([
            f'<a href="/tests/{html.escape(slug)}" style="color:#d0d0e8"><strong>{html.escape(slug)}</strong></a>',
            html.escape(ptype),
            " ".join(badges),
            run_btn,
            f'<div id="test-result-{slug}" class="muted" style="font-size:0.78rem">—</div>',
        ])

    table = _table(
        ["Project", "Type", "Tests", "Action", "Results"],
        rows, "No testable projects found", "tests-table")

    body = f"""
<h2>Tests Dashboard</h2>
<p class="muted" style="margin-bottom:1rem">
  Run QA tests against TempleDB-managed projects. Structure tests run instantly.
  Server tests start the app and check page loads + endpoints.
</p>

<button hx-post="/tests/run-all" hx-target="#run-all-results" hx-swap="innerHTML"
  hx-indicator="#run-all-spinner"
  style="background:#1a1a3a;border:1px solid #3a3a5a;color:#d0d0e8;
  padding:4px 12px;border-radius:4px;cursor:pointer;font-family:monospace;
  font-size:0.85rem;margin-bottom:1rem">Run All Tests</button>
<span id="run-all-spinner" class="htmx-indicator" style="color:#606080"> running all...</span>
<div id="run-all-results"></div>

{_search_bar("tests-table", "Filter projects...")}
{table}
"""
    return _base("Tests", body, "tests")


@app.post("/tests/run/{slug}", response_class=HTMLResponse)
def tests_run_project(slug: str):
    """Run tests for a single project and return results as HTML."""
    from test_runner import run_tests, detect_project_type, TestResult

    project = query_one("SELECT slug, repo_url FROM projects WHERE slug = ?", (slug,))
    if not project:
        return HTMLResponse(f'<span style="color:#e94560">Project not found</span>')

    # Resolve path
    checkout = Path.home() / ".config" / "templedb" / "checkouts" / slug
    repo_path = Path(project.get("repo_url") or "") if project.get("repo_url") else None

    if repo_path and repo_path.exists() and (
        (repo_path / "src" / "gui.py").exists() or
        (repo_path / "frontend" / "package.json").exists() or
        (repo_path / "package.json").exists() or
        (repo_path / "backend" / "app.py").exists() or
        (repo_path / "app.py").exists()
    ):
        project_path = repo_path
    elif checkout.exists():
        project_path = checkout
    elif repo_path and repo_path.exists():
        project_path = repo_path
    else:
        return HTMLResponse(f'<span style="color:#e94560">No project path found</span>')

    # Capture test output
    import io
    old_stdout = sys.stdout
    sys.stdout = captured = io.StringIO()

    try:
        success = run_tests(slug, project_path, verbose=True)
    except Exception as e:
        sys.stdout = old_stdout
        return HTMLResponse(f'<span style="color:#e94560">Error: {html.escape(str(e))}</span>')
    finally:
        sys.stdout = old_stdout

    output = captured.getvalue()

    # Parse results from output
    lines = output.strip().split("\n")
    result_parts = []
    for line in lines:
        line_clean = re.sub(r'\033\[[0-9;]*m', '', line)  # strip ANSI
        if "PASS" in line_clean:
            test_name = line_clean.replace("PASS", "").strip()
            result_parts.append(f'<div style="color:#4a9a6a;font-size:0.75rem">&#x2713; {html.escape(test_name)}</div>')
        elif "FAIL" in line_clean:
            test_name = line_clean.replace("FAIL", "").strip()
            result_parts.append(f'<div style="color:#e94560;font-size:0.75rem">&#x2717; {html.escape(test_name)}</div>')

    # Summary line
    for line in lines:
        if "Results:" in line:
            line_clean = re.sub(r'\033\[[0-9;]*m', '', line)
            if success:
                summary = f'<div style="color:#4a9a6a;font-weight:bold;margin-top:4px">{html.escape(line_clean.strip())}</div>'
            else:
                summary = f'<div style="color:#e94560;font-weight:bold;margin-top:4px">{html.escape(line_clean.strip())}</div>'
            result_parts.append(summary)
            break

    if not result_parts:
        if success:
            result_parts.append('<div style="color:#4a9a6a">All tests passed</div>')
        else:
            result_parts.append(f'<div style="color:#e94560">Tests failed</div>')

    # Collapsible detail
    detail_id = f"detail-{slug}"
    result_html = (
        f'<details><summary style="cursor:pointer;color:#a0a0c0;font-size:0.78rem">'
        f'{"&#x2713;" if success else "&#x2717;"} '
        f'{result_parts[-1] if result_parts else ""}</summary>'
        f'<div style="margin-top:4px;padding:4px 8px;background:#0a0a15;border-radius:4px">'
        f'{"".join(result_parts[:-1])}'
        f'</div></details>'
    )

    return HTMLResponse(result_html)


@app.post("/tests/run-all", response_class=HTMLResponse)
def tests_run_all():
    """Run tests for all testable projects."""
    from test_runner import PROJECT_TESTS, STRUCTURE_TESTS

    testable = set(list(PROJECT_TESTS.keys()) + list(STRUCTURE_TESTS.keys()))
    results = []

    for slug in sorted(testable):
        # Trigger individual test and collect summary
        r = tests_run_project(slug)
        body = r.body.decode() if hasattr(r, 'body') else str(r)
        results.append(f'<div style="margin-bottom:4px"><strong>{html.escape(slug)}</strong>: {body}</div>')

        # Also update the individual result span via OOB
        results.append(
            f'<div id="test-result-{html.escape(slug)}" hx-swap-oob="innerHTML">{body}</div>'
        )

    return HTMLResponse("".join(results))


@app.get("/tests/{slug}", response_class=HTMLResponse)
def tests_detail(slug: str):
    """Per-project test detail page with editable test definitions."""
    project = query_one("SELECT * FROM projects WHERE slug = ?", (slug,))
    if not project:
        return _base("Not found", f'<p class="muted">Project "{html.escape(slug)}" not found.</p>', "tests")

    pid = project["id"]

    # Load test definitions
    tests = query_all(
        "SELECT * FROM project_tests WHERE project_id = ? ORDER BY test_type, path, file_path", (pid,))

    # Group by type
    page_tests = [t for t in tests if t["test_type"] == "page"]
    post_tests = [t for t in tests if t["test_type"] == "post"]
    struct_file_tests = [t for t in tests if t["test_type"] == "structure_file"]
    struct_dir_tests = [t for t in tests if t["test_type"] == "structure_dir"]

    # Build page tests table
    page_rows = []
    for t in page_tests:
        enabled = '&#x2713;' if t["enabled"] else '&#x2717;'
        toggle_btn = (
            f'<button hx-post="/tests/{slug}/toggle/{t["id"]}" hx-target="#test-row-{t["id"]}" hx-swap="outerHTML" '
            f'style="background:none;border:none;color:#d0d0e8;cursor:pointer;font-size:0.8rem" '
            f'title="Toggle enabled">{"&#x1f7e2;" if t["enabled"] else "&#x26aa;"}</button>')
        delete_btn = (
            f'<button hx-delete="/tests/{slug}/delete/{t["id"]}" hx-target="#test-row-{t["id"]}" hx-swap="outerHTML" '
            f'hx-confirm="Delete this test?" '
            f'style="background:none;border:none;color:#e94560;cursor:pointer;font-size:0.8rem">&#x2717;</button>')
        page_rows.append(f'<tr id="test-row-{t["id"]}"><td><code>{html.escape(t["path"] or "")}</code></td>'
                        f'<td>{html.escape(t["expected_text"] or "")}</td>'
                        f'<td>{html.escape(t["description"] or "")}</td>'
                        f'<td>{toggle_btn} {delete_btn}</td></tr>')

    # Build structure tests table
    struct_rows = []
    for t in struct_file_tests + struct_dir_tests:
        ttype = "file" if t["test_type"] == "structure_file" else "dir"
        toggle_btn = (
            f'<button hx-post="/tests/{slug}/toggle/{t["id"]}" hx-target="#test-row-{t["id"]}" hx-swap="outerHTML" '
            f'style="background:none;border:none;color:#d0d0e8;cursor:pointer;font-size:0.8rem">'
            f'{"&#x1f7e2;" if t["enabled"] else "&#x26aa;"}</button>')
        delete_btn = (
            f'<button hx-delete="/tests/{slug}/delete/{t["id"]}" hx-target="#test-row-{t["id"]}" hx-swap="outerHTML" '
            f'hx-confirm="Delete this test?" '
            f'style="background:none;border:none;color:#e94560;cursor:pointer;font-size:0.8rem">&#x2717;</button>')
        struct_rows.append(f'<tr id="test-row-{t["id"]}"><td>{ttype}</td>'
                          f'<td><code>{html.escape(t["file_path"] or "")}</code></td>'
                          f'<td>{html.escape(t["description"] or "")}</td>'
                          f'<td>{toggle_btn} {delete_btn}</td></tr>')

    # Post tests table
    post_rows = []
    for t in post_tests:
        toggle_btn = (
            f'<button hx-post="/tests/{slug}/toggle/{t["id"]}" hx-target="#test-row-{t["id"]}" hx-swap="outerHTML" '
            f'style="background:none;border:none;color:#d0d0e8;cursor:pointer;font-size:0.8rem">'
            f'{"&#x1f7e2;" if t["enabled"] else "&#x26aa;"}</button>')
        delete_btn = (
            f'<button hx-delete="/tests/{slug}/delete/{t["id"]}" hx-target="#test-row-{t["id"]}" hx-swap="outerHTML" '
            f'hx-confirm="Delete this test?" '
            f'style="background:none;border:none;color:#e94560;cursor:pointer;font-size:0.8rem">&#x2717;</button>')
        post_rows.append(f'<tr id="test-row-{t["id"]}"><td><code>{html.escape(t["path"] or "")}</code></td>'
                        f'<td>{html.escape(t["expected_text"] or "")}</td>'
                        f'<td>{html.escape(t["description"] or "")}</td>'
                        f'<td>{toggle_btn} {delete_btn}</td></tr>')

    # Test history
    history = query_all(
        "SELECT * FROM test_runs WHERE project_id = ? ORDER BY created_at DESC LIMIT 10", (pid,))
    history_rows = []
    for h in history:
        color = "#4a9a6a" if h["failed"] == 0 else "#e94560"
        history_rows.append([
            f'<span style="color:{color}">{h["passed"]}/{h["passed"] + h["failed"]}</span>',
            f'{h.get("duration_ms", 0) or 0}ms',
            f'<span class="muted">{html.escape((h["created_at"] or "")[:19])}</span>',
        ])

    # Add test forms
    input_style = ('style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;'
                   'padding:4px 8px;border-radius:3px;font-family:monospace;font-size:0.8rem;width:250px"')
    btn_style = ('style="background:#1a3a1a;border:1px solid #2a4a2a;color:#8f8;'
                 'padding:4px 10px;border-radius:3px;cursor:pointer;font-family:monospace;font-size:0.8rem"')

    add_page_form = f"""
<form hx-post="/tests/{slug}/add" hx-target="#add-page-result" hx-swap="innerHTML"
  style="display:flex;gap:8px;align-items:center;margin-top:8px">
  <input type="hidden" name="test_type" value="page">
  <input name="path" placeholder="/path" {input_style} style="width:150px">
  <input name="expected_text" placeholder="Expected text" {input_style} style="width:180px">
  <input name="description" placeholder="Description" {input_style} style="width:180px">
  <button type="submit" {btn_style}>+ Add Page Test</button>
  <span id="add-page-result"></span>
</form>"""

    add_post_form = f"""
<form hx-post="/tests/{slug}/add" hx-target="#add-post-result" hx-swap="innerHTML"
  style="display:flex;gap:8px;align-items:center;margin-top:8px">
  <input type="hidden" name="test_type" value="post">
  <input name="path" placeholder="/path" {input_style} style="width:150px">
  <input name="expected_text" placeholder="Expected text" {input_style} style="width:180px">
  <input name="description" placeholder="Description" {input_style} style="width:180px">
  <button type="submit" {btn_style}>+ Add POST Test</button>
  <span id="add-post-result"></span>
</form>"""

    add_struct_form = f"""
<form hx-post="/tests/{slug}/add" hx-target="#add-struct-result" hx-swap="innerHTML"
  style="display:flex;gap:8px;align-items:center;margin-top:8px">
  <select name="test_type" style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;padding:4px;border-radius:3px;font-family:monospace;font-size:0.8rem">
    <option value="structure_file">File</option>
    <option value="structure_dir">Dir</option>
  </select>
  <input name="file_path" placeholder="relative/path" {input_style} style="width:200px">
  <input name="description" placeholder="Description" {input_style} style="width:180px">
  <button type="submit" {btn_style}>+ Add Structure Test</button>
  <span id="add-struct-result"></span>
</form>"""

    # Load test deps
    test_deps = query_all(
        "SELECT * FROM project_test_deps WHERE project_id = ? ORDER BY nix_package", (pid,))
    dep_rows = []
    for d in test_deps:
        resolved = ""
        try:
            from test_runner import _find_nix_binary
            binary = _find_nix_binary(d["nix_package"], d.get("binary_name"))
            resolved = f'<span style="color:#8f8;font-size:0.7rem">{html.escape(str(binary))}</span>' if binary else '<span style="color:#f88;font-size:0.7rem">not found</span>'
        except Exception:
            resolved = '<span style="color:#888;font-size:0.7rem">?</span>'
        enabled_color = "#8f8" if d["enabled"] else "#888"
        dep_rows.append(
            f'<tr id="dep-row-{d["id"]}">'
            f'<td><code>{html.escape(d["nix_package"])}</code></td>'
            f'<td>{html.escape(d.get("env_var") or "")}</td>'
            f'<td>{html.escape(d.get("binary_name") or "")}</td>'
            f'<td>{html.escape(d.get("reason") or "")}</td>'
            f'<td>{resolved}</td>'
            f'<td>'
            f'<button hx-post="/tests/{slug}/dep/toggle/{d["id"]}" hx-target="#dep-row-{d["id"]}" hx-swap="outerHTML" '
            f'style="background:none;border:none;cursor:pointer;color:{enabled_color}">{"●" if d["enabled"] else "○"}</button> '
            f'<button hx-delete="/tests/{slug}/dep/delete/{d["id"]}" hx-target="#dep-row-{d["id"]}" hx-swap="outerHTML" '
            f'style="background:none;border:none;cursor:pointer;color:#f66">✕</button>'
            f'</td></tr>'
        )
    deps_table_html = (
        f'<table><thead><tr><th>Package</th><th>Env Var</th><th>Binary</th><th>Reason</th><th>Resolved</th><th></th></tr></thead>'
        f'<tbody>{"".join(dep_rows)}</tbody></table>' if dep_rows else '<p class="muted">No test dependencies</p>')

    add_dep_form = f"""
<form hx-post="/tests/{slug}/dep/add" hx-target="#add-dep-result" hx-swap="innerHTML"
  style="display:flex;gap:8px;align-items:center;margin-top:8px">
  <input name="nix_package" placeholder="chromium" {input_style} style="width:120px">
  <input name="env_var" placeholder="CHROME_PATH" {input_style} style="width:120px">
  <input name="binary_name" placeholder="chromium" {input_style} style="width:120px">
  <input name="reason" placeholder="Reason" {input_style} style="width:160px">
  <button type="submit" {btn_style}>+ Add Dep</button>
  <span id="add-dep-result"></span>
</form>"""

    # Run button
    run_btn = (
        f'<button hx-post="/tests/run/{slug}" hx-target="#run-result" hx-swap="innerHTML" '
        f'hx-indicator="#run-spinner" '
        f'style="background:#1a1a3a;border:1px solid #3a3a5a;color:#d0d0e8;'
        f'padding:6px 16px;border-radius:4px;cursor:pointer;font-family:monospace;'
        f'font-size:0.85rem;margin-bottom:1rem">Run All Tests</button>'
        f'<span id="run-spinner" class="htmx-indicator" style="color:#606080"> running...</span>'
    )

    page_table_html = (
        f'<table><thead><tr><th>Path</th><th>Expected</th><th>Description</th><th></th></tr></thead>'
        f'<tbody>{"".join(page_rows)}</tbody></table>' if page_rows else '<p class="muted">No page tests</p>')

    post_table_html = (
        f'<table><thead><tr><th>Path</th><th>Expected</th><th>Description</th><th></th></tr></thead>'
        f'<tbody>{"".join(post_rows)}</tbody></table>' if post_rows else '<p class="muted">No POST tests</p>')

    struct_table_html = (
        f'<table><thead><tr><th>Type</th><th>Path</th><th>Description</th><th></th></tr></thead>'
        f'<tbody>{"".join(struct_rows)}</tbody></table>' if struct_rows else '<p class="muted">No structure tests</p>')

    body = f"""
<h2>Tests: {html.escape(slug)}</h2>
<p><a href="/tests" style="color:#606080">&larr; All Projects</a></p>

{run_btn}
<div id="run-result" style="margin-bottom:1.5rem"></div>

<h3>Page Tests ({len(page_tests)})</h3>
{page_table_html}
{add_page_form}

<h3 style="margin-top:1.5rem">POST Tests ({len(post_tests)})</h3>
{post_table_html}
{add_post_form}

<h3 style="margin-top:1.5rem">Structure Tests ({len(struct_file_tests) + len(struct_dir_tests)})</h3>
{struct_table_html}
{add_struct_form}

<h3 style="margin-top:1.5rem">Test Dependencies (Nix Packages)</h3>
{deps_table_html}
{add_dep_form}

<h3 style="margin-top:1.5rem">Run History</h3>
{_table(["Result", "Duration", "Date"], history_rows, "No test runs yet.")}
"""
    return _base(f"Tests: {slug}", body, "tests")


@app.post("/tests/{slug}/add", response_class=HTMLResponse)
def tests_add(slug: str, test_type: str = Form(...), path: str = Form(""),
              expected_text: str = Form(""), description: str = Form(""),
              file_path: str = Form(""), post_data: str = Form("")):
    """Add a new test definition."""
    project = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
    if not project:
        return HTMLResponse(_msg("Project not found", ok=False))

    if test_type in ("page", "post") and not path:
        return HTMLResponse(_msg("Path is required", ok=False))
    if test_type.startswith("structure_") and not file_path:
        return HTMLResponse(_msg("File path is required", ok=False))

    execute("""
        INSERT INTO project_tests (project_id, test_type, path, expected_text, post_data, file_path, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (project["id"], test_type,
          path or None, expected_text or None,
          post_data or None, file_path or None,
          description or None))

    return HTMLResponse(_msg(f"Added {test_type} test", ok=True))


@app.post("/tests/{slug}/toggle/{test_id}", response_class=HTMLResponse)
def tests_toggle(slug: str, test_id: int):
    """Toggle a test definition enabled/disabled."""
    test = query_one("SELECT * FROM project_tests WHERE id = ?", (test_id,))
    if not test:
        return HTMLResponse("")

    new_enabled = 0 if test["enabled"] else 1
    execute("UPDATE project_tests SET enabled = ?, updated_at = datetime('now') WHERE id = ?",
            (new_enabled, test_id))

    # Return updated row
    test = query_one("SELECT * FROM project_tests WHERE id = ?", (test_id,))
    toggle_icon = "&#x1f7e2;" if test["enabled"] else "&#x26aa;"
    toggle_btn = (
        f'<button hx-post="/tests/{slug}/toggle/{test_id}" hx-target="#test-row-{test_id}" hx-swap="outerHTML" '
        f'style="background:none;border:none;color:#d0d0e8;cursor:pointer;font-size:0.8rem">{toggle_icon}</button>')
    delete_btn = (
        f'<button hx-delete="/tests/{slug}/delete/{test_id}" hx-target="#test-row-{test_id}" hx-swap="outerHTML" '
        f'hx-confirm="Delete this test?" '
        f'style="background:none;border:none;color:#e94560;cursor:pointer;font-size:0.8rem">&#x2717;</button>')

    if test["test_type"] in ("page", "post"):
        return HTMLResponse(
            f'<tr id="test-row-{test_id}"><td><code>{html.escape(test["path"] or "")}</code></td>'
            f'<td>{html.escape(test["expected_text"] or "")}</td>'
            f'<td>{html.escape(test["description"] or "")}</td>'
            f'<td>{toggle_btn} {delete_btn}</td></tr>')
    else:
        ttype = "file" if test["test_type"] == "structure_file" else "dir"
        return HTMLResponse(
            f'<tr id="test-row-{test_id}"><td>{ttype}</td>'
            f'<td><code>{html.escape(test["file_path"] or "")}</code></td>'
            f'<td>{html.escape(test["description"] or "")}</td>'
            f'<td>{toggle_btn} {delete_btn}</td></tr>')


@app.delete("/tests/{slug}/delete/{test_id}", response_class=HTMLResponse)
def tests_delete(slug: str, test_id: int):
    """Delete a test definition."""
    execute("DELETE FROM project_tests WHERE id = ?", (test_id,))
    return HTMLResponse("")


@app.post("/tests/{slug}/dep/add", response_class=HTMLResponse)
def tests_dep_add(slug: str, nix_package: str = Form(...), env_var: str = Form(""),
                  binary_name: str = Form(""), reason: str = Form("")):
    """Add a test dependency (nix package)."""
    project = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
    if not project:
        return HTMLResponse(_msg("Project not found", ok=False))
    if not nix_package.strip():
        return HTMLResponse(_msg("Package name required", ok=False))
    execute("""
        INSERT OR IGNORE INTO project_test_deps (project_id, nix_package, env_var, binary_name, reason)
        VALUES (?, ?, ?, ?, ?)
    """, (project["id"], nix_package.strip(), env_var.strip() or None, binary_name.strip() or None, reason.strip() or None))
    return HTMLResponse(_msg(f"Added dep: {nix_package}", ok=True))


@app.post("/tests/{slug}/dep/toggle/{dep_id}", response_class=HTMLResponse)
def tests_dep_toggle(slug: str, dep_id: int):
    """Toggle a test dependency enabled/disabled."""
    dep = query_one("SELECT * FROM project_test_deps WHERE id = ?", (dep_id,))
    if dep:
        execute("UPDATE project_test_deps SET enabled = ? WHERE id = ?", (0 if dep["enabled"] else 1, dep_id))
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/tests/{slug}", status_code=303)


@app.delete("/tests/{slug}/dep/delete/{dep_id}", response_class=HTMLResponse)
def tests_dep_delete(slug: str, dep_id: int):
    """Delete a test dependency."""
    execute("DELETE FROM project_test_deps WHERE id = ?", (dep_id,))
    return HTMLResponse("")
