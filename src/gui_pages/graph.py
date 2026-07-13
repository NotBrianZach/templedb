"""TempleDB GUI — Graph pages."""
import html
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
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
_file_link = _gui._file_link
_msg = _gui._msg
_status_badge = _gui._status_badge
_run = _gui._run
TEMPLEDB = _gui.TEMPLEDB


@router.get("/graph", response_class=HTMLResponse)
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


@router.get("/graph/{slug}", response_class=HTMLResponse)
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

