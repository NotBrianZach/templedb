"""TempleDB GUI — Audit pages."""
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


@router.get("/audit", response_class=HTMLResponse)
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

