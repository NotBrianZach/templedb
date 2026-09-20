"""TempleDB GUI — Code pages."""
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

from gui_helpers import TEMPLEDB, _base, _file_link, _msg, _run, _search_bar, _status_badge, _table
_base = _base
_table = _table
_search_bar = _search_bar
_file_link = _file_link
_msg = _msg
_status_badge = _status_badge
_run = _run
TEMPLEDB = TEMPLEDB


@router.get("/code", response_class=HTMLResponse)
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

