#!/usr/bin/env python3
"""
TempleDB GUI Helpers — shared HTML generation functions.
Used by all gui_pages/*.py route modules.
"""
import html
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db_utils import execute, query_all, query_one
from config import FUSE_MOUNT_PATH
from fastapi.responses import HTMLResponse

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


def _run(*args: str) -> tuple[int, str, str]:
    cmd = TEMPLEDB
    if " -m " in cmd:
        # python3 -m cli form: split into list
        parts = cmd.split() + list(args)
    else:
        parts = [cmd] + list(args)
    r = subprocess.run(parts, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()



TEMPLEDB = _find_templedb()

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


def _status_badge(status: str) -> str:
    colors = {"success": " green", "failed": " red", "pass": " green", "fail": " red"}
    cls = colors.get((status or "").lower(), "")
    return f'<span class="badge{cls}">{html.escape(status or "—")}</span>'


def _deploy_logic_section() -> str:
    """Build the Prolog-powered deployment logic section."""
    try:
        from services.prolog_engine import DeploymentLogic
        pl_path = Path(__file__).parent / "services" / "deploy_logic.pl"
        if not pl_path.exists():
            return '<div class="muted" style="margin-bottom:1.5rem">deploy_logic.pl not found</div>'
        logic = DeploymentLogic(str(pl_path))

        # Single swipl call: all projects, order, groups, validation
        batch = logic.batch_all()

        projects_info = []
        for p in batch.get("projects", []):
            slug = str(p.get("slug", "")).replace("_", "-")
            ptype = str(p.get("type", "?"))
            # Adapt validation dict to match expected format
            v = {
                "valid": p.get("valid", False),
                "can_deploy": p.get("can_deploy", False),
                "has_cycle": p.get("has_cycle", False),
                "deps": [str(d).replace("_", "-") for d in p.get("deps", [])],
                "targets": [str(t) for t in p.get("targets", [])],
                "required_env": [str(e) for e in p.get("required_env", [])],
                "health_checks": p.get("health_checks", []),
            }
            projects_info.append((slug, ptype, v))

        ordered = [str(s).replace("_", "-") for s in batch.get("deploy_order", [])]
        parallel = [
            [str(s).replace("_", "-") for s in g]
            for g in batch.get("parallel_groups", [])
        ]

        # Build project cards
        cards_html = ""
        for slug, ptype, v in sorted(projects_info, key=lambda x: ordered.index(x[0]) if x[0] in ordered else 99):
            ok = v["valid"] and v["can_deploy"] and not v["has_cycle"]
            status_icon = '<span style="color:#4a9a6a">&#x2713;</span>' if ok else '<span style="color:#e94560">&#x2717;</span>'
            deps_html = ", ".join(f'<code>{html.escape(d)}</code>' for d in v["deps"]) or '<span class="muted">none</span>'
            targets_html = ", ".join(f'<code>{html.escape(t)}</code>' for t in v["targets"]) or '<span class="muted">\u2014</span>'
            env_html = ", ".join(f'<code style="font-size:0.7rem">{html.escape(e)}</code>' for e in v["required_env"]) if v["required_env"] else ""
            health_html = ""
            for hc in v["health_checks"]:
                health_html += f' <a href="{html.escape(hc.get("URL", ""))}" target="_blank" style="font-size:0.72rem" class="muted">{html.escape(hc.get("URL", ""))}</a>'
            cycle_warn = ' <span class="badge" style="color:#e94560">CYCLE</span>' if v["has_cycle"] else ""
            safe_id = slug.replace('-', '_')

            cards_html += f"""
            <div style="background:#13131f;border:1px solid #1e1e3a;border-radius:6px;padding:0.6rem 0.8rem;min-width:220px">
              <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:0.3rem">
                <strong>{status_icon} <a href="/projects/{html.escape(slug)}">{html.escape(slug)}</a></strong>
                <span class="badge">{html.escape(ptype)}</span>
              </div>
              <div style="font-size:0.78rem;color:#808098">
                deps: {deps_html}{cycle_warn}<br>
                targets: {targets_html}
                {('<br>env: ' + env_html) if env_html else ''}
                {('<br>health:' + health_html) if health_html else ''}
              </div>
              <div style="margin-top:0.4rem">
                <button hx-get="/deploy/validate/{html.escape(slug)}" hx-target="#validate-{safe_id}"
                        hx-swap="innerHTML" style="padding:0.15rem 0.5rem;font-size:0.72rem">validate</button>
                <span id="validate-{safe_id}" style="font-size:0.72rem;margin-left:0.3rem"></span>
              </div>
            </div>"""

        # Parallel groups visualization (swim lanes)
        lanes_html = ""
        for i, group in enumerate(parallel):
            group_items = " ".join(
                f'<span style="background:#1a1a30;border:1px solid #2a2a4a;border-radius:4px;padding:0.2rem 0.5rem;font-size:0.78rem">{html.escape(p)}</span>'
                for p in group
            )
            lanes_html += f"""
            <div style="display:flex;align-items:center;gap:0.6rem;margin-bottom:0.4rem">
              <span class="muted" style="font-size:0.72rem;width:50px;text-align:right">phase {i+1}</span>
              <span style="color:#2a2a4a">&#x25B6;</span>
              <div style="display:flex;gap:0.4rem;flex-wrap:wrap">{group_items}</div>
            </div>"""

        # Dependency graph edges
        graph_edges = ""
        for slug, _, v in projects_info:
            for dep in v["deps"]:
                graph_edges += f'<div style="font-size:0.78rem;color:#808098;margin-left:2rem"><code>{html.escape(dep)}</code> <span style="color:#4a9eff">&#x2192;</span> <code>{html.escape(slug)}</code></div>'

        return f"""<h3>Deployment Logic</h3>
<div style="display:flex;flex-wrap:wrap;gap:0.6rem;margin:0.8rem 0">{cards_html}</div>
<h3>Parallel Groups</h3>{lanes_html}
<h3>Dependencies</h3>{graph_edges}
"""
    except Exception as e:
        return f'<div class="muted">Deployment logic unavailable: {e}</div>'
