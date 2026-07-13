"""TempleDB GUI — Projects pages."""
import html
import json
import os
import subprocess
from pathlib import Path

from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse

from db_utils import execute, query_all, query_one
from gui_helpers import _base, _table, _search_bar, _file_link, _msg, _status_badge, CSS

router = APIRouter()

@router.get("/projects", response_class=HTMLResponse)
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



def _backup_history_exists() -> bool:
    try:
        query_one("SELECT 1 FROM backup_history LIMIT 1")
        return True
    except Exception:
        return False


@router.post("/projects/import", response_class=HTMLResponse)
def projects_import(path: str = Form(...), slug: str = Form("")):
    cmd = ["project", "import", path]
    if slug.strip():
        cmd += ["--slug", slug.strip()]
    rc, out, err = _run(*cmd)
    msg = out or err or "Done"
    return HTMLResponse(_msg(msg, ok=rc == 0))



@router.post("/projects/{slug}/sync", response_class=HTMLResponse)
def project_sync(slug: str):
    rc, out, err = _run("project", "sync", slug)
    text = (out or err or "Done").split("\n")[0][:80]
    ok_cls = "color:#4a9a6a" if rc == 0 else "color:#e94560"
    return HTMLResponse(f' <span style="{ok_cls};font-size:0.75rem">{html.escape(text)}</span>')



@router.post("/projects/sync-all", response_class=HTMLResponse)
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



@router.post("/projects/{slug}/set-type", response_class=HTMLResponse)
def project_set_type(slug: str, project_type: str = Form(...)):
    """Set project type."""
    rc, out, err = _run("nixos", "set-type", slug, project_type)
    return HTMLResponse(_msg(out or err or f"Set type to {project_type}", ok=rc == 0))



@router.get("/projects/{slug}", response_class=HTMLResponse)
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



@router.get("/projects/{slug}/search", response_class=HTMLResponse)
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


@router.get("/projects/{slug}/file", response_class=HTMLResponse)
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


