"""TempleDB GUI — Domains pages."""
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
templedb sync sync &lt;peer&gt;                 # bidirectional sync
templedb sync network setup                # configure Tailscale
templedb sync network sync-all             # sync all peers</pre>
</div>

</div>
</details>
"""


