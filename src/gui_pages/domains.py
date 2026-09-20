"""TempleDB GUI — Domains pages."""
import html
import json
import os
import subprocess
import sys
import time
import sqlite3 as _sqlite3
from collections import defaultdict
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


@router.get("/domains", response_class=HTMLResponse)
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

