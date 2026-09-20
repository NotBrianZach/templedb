"""TempleDB GUI — Schema pages."""
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


@router.get("/schema-browser", response_class=HTMLResponse)
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

