"""TempleDB GUI — Nix pages."""
import html
import json
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import execute, query_all, query_one
from config import FUSE_MOUNT_PATH

router = APIRouter()

import gui as _gui
_base = _gui._base
_table = _gui._table
_search_bar = _gui._search_bar
_file_link = _gui._file_link
_msg = _gui._msg
_status_badge = _gui._status_badge
_run = _gui._run
_colorize_diff = _gui._colorize_diff
_highlight_template = _gui._highlight_template
TEMPLEDB = _gui.TEMPLEDB


@router.post("/nixos/generate-all", response_class=HTMLResponse)
def nixos_generate_all():
    rc, out, err = _run("nixos", "generate-all")
    return HTMLResponse(_msg(out or err or "Generated", ok=rc == 0))


@router.post("/nixos/host-clone", response_class=HTMLResponse)
def nixos_host_clone(source: str = Form(...), target: str = Form(...)):
    rc, out, err = _run("nixos", "host", "clone", source, target)
    return HTMLResponse(_msg(out or err or f"Cloned {source} → {target}", ok=rc == 0))


@router.post("/nixos/dotfiles-apply", response_class=HTMLResponse)
def nixos_dotfiles_apply():
    rc, out, err = _run("nixos", "dotfiles-apply", "--force")
    return HTMLResponse(_msg(out or err or "Applied", ok=rc == 0))


@router.post("/db/migrate", response_class=HTMLResponse)
def db_migrate():
    rc, out, err = _run("db", "migrate")
    return HTMLResponse(_msg(out or err or "Done", ok=rc == 0))


# ── CRUD: system_config ───────────────────────────────────────────────────────

@router.post("/config/set", response_class=HTMLResponse)
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


@router.post("/config/delete", response_class=HTMLResponse)
def config_delete(key: str = Form(...)):
    """Delete a system_config key."""
    from db_utils import execute
    execute("DELETE FROM system_config WHERE key = ?", (key,))
    return HTMLResponse(_msg(f"Deleted {key}", ok=True))


# ── CRUD: environment variables ──────────────────────────────────────────────

@router.post("/env/set", response_class=HTMLResponse)
def env_var_set(project: str = Form(...), var_name: str = Form(...), var_value: str = Form(...)):
    """Set an environment variable."""
    rc, out, err = _run("env", "set", project, var_name, var_value)
    return HTMLResponse(_msg(out or err or f"Set {var_name}", ok=rc == 0))


@router.post("/env/delete", response_class=HTMLResponse)
def env_var_delete(project: str = Form(...), var_name: str = Form(...)):
    """Delete an environment variable."""
    rc, out, err = _run("env", "rm", project, var_name)
    return HTMLResponse(_msg(out or err or f"Deleted {var_name}", ok=rc == 0))


# ── CRUD: dotfiles ───────────────────────────────────────────────────────────

@router.post("/dotfiles/add", response_class=HTMLResponse)
def dotfiles_add(project: str = Form(...), source: str = Form(...), target: str = Form(...)):
    """Add a dotfile mapping."""
    rc, out, err = _run("nixos", "dotfiles-add", project, source, target)
    return HTMLResponse(_msg(out or err or f"Added {source}", ok=rc == 0))


@router.post("/dotfiles/remove", response_class=HTMLResponse)
def dotfiles_remove(project: str = Form(...), source: str = Form(...)):
    """Remove a dotfile mapping."""
    rc, out, err = _run("nixos", "dotfiles-remove", project, source)
    return HTMLResponse(_msg(out or err or f"Removed {source}", ok=rc == 0))


# ── CRUD: project settings ──────────────────────────────────────────────────

@router.post("/projects/{slug}/set-type", response_class=HTMLResponse)
def project_set_type(slug: str, project_type: str = Form(...)):
    """Set project type."""
    rc, out, err = _run("nixos", "set-type", slug, project_type)
    return HTMLResponse(_msg(out or err or f"Set type to {project_type}", ok=rc == 0))


@router.post("/mount/toggle", response_class=HTMLResponse)
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

@router.get("/vcs", response_class=HTMLResponse)
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


@router.get("/vcs/{slug}", response_class=HTMLResponse)
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


@router.get("/vcs/{slug}/commits/{commit_hash}", response_class=HTMLResponse)
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


@router.get("/vcs/{slug}/branches", response_class=HTMLResponse)
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


@router.get("/vcs/{slug}/staging", response_class=HTMLResponse)
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


@router.post("/vcs/{slug}/staging/stage/{file_id}", response_class=HTMLResponse)
def vcs_stage_file(slug: str, file_id: int):
    proj = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
    branch = query_one("SELECT COALESCE(p.active_branch_id, vb.id) as id FROM projects p LEFT JOIN vcs_branches vb ON vb.project_id = p.id AND vb.is_default = 1 WHERE p.id = ?", (proj["id"],))
    from db_utils import execute
    execute("UPDATE vcs_working_state SET staged = 1 WHERE file_id = ? AND project_id = ? AND branch_id = ?",
            (file_id, proj["id"], branch["id"]))
    return HTMLResponse(_staging_area(slug))


@router.post("/vcs/{slug}/staging/unstage/{file_id}", response_class=HTMLResponse)
def vcs_unstage_file(slug: str, file_id: int):
    proj = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
    branch = query_one("SELECT COALESCE(p.active_branch_id, vb.id) as id FROM projects p LEFT JOIN vcs_branches vb ON vb.project_id = p.id AND vb.is_default = 1 WHERE p.id = ?", (proj["id"],))
    from db_utils import execute
    execute("UPDATE vcs_working_state SET staged = 0 WHERE file_id = ? AND project_id = ? AND branch_id = ?",
            (file_id, proj["id"], branch["id"]))
    return HTMLResponse(_staging_area(slug))


@router.post("/vcs/{slug}/staging/add-all", response_class=HTMLResponse)
def vcs_stage_all(slug: str):
    _run("vcs", "add", "-p", slug, "--all")
    return HTMLResponse(_staging_area(slug))


@router.post("/vcs/{slug}/staging/reset-all", response_class=HTMLResponse)
def vcs_unstage_all(slug: str):
    _run("vcs", "reset", "-p", slug, "--all")
    return HTMLResponse(_staging_area(slug))


@router.post("/vcs/{slug}/commit", response_class=HTMLResponse)
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

@router.get("/secrets", response_class=HTMLResponse)
def secrets_list():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/env")


@router.get("/secrets/{slug}/{profile}", response_class=HTMLResponse)
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

@router.get("/vars", response_class=HTMLResponse)
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


@router.get("/vars", response_class=HTMLResponse)
def vars_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/env")


# ── Env (unified vars + secrets) ──────────────────────────────────────────────

@router.get("/env", response_class=HTMLResponse)
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


@router.get("/nix", response_class=HTMLResponse)
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


@router.post("/nix/packages/{pkg_id}/toggle", response_class=HTMLResponse)
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

@router.get("/nix/host/{hostname}", response_class=HTMLResponse)
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

        return f"""
<h3>Deployment Logic <span class="muted" style="font-weight:normal;font-size:0.78rem">Prolog engine &middot; <code>deploy_logic.pl</code></span></h3>
<p class="muted" style="font-size:0.8rem;margin-bottom:0.8rem">Declarative dependency resolution. Edit rules in <code>src/services/deploy_logic.pl</code></p>

<div style="display:flex;gap:1.5rem;margin-bottom:1.2rem;flex-wrap:wrap">
  <div style="flex:1;min-width:300px">
    <h3 style="font-size:0.85rem;color:#808098;margin-bottom:0.5rem">Deploy Order (parallel phases)</h3>
    {lanes_html}
  </div>
  <div style="flex:0 0 auto;min-width:200px">
    <h3 style="font-size:0.85rem;color:#808098;margin-bottom:0.5rem">Dependency Edges</h3>
    {graph_edges if graph_edges else '<span class="muted" style="font-size:0.78rem">no edges</span>'}
  </div>
</div>

<div style="display:flex;gap:0.8rem;flex-wrap:wrap;margin-bottom:1.5rem">
{cards_html}
</div>
"""
    except Exception as e:
        return f'<div class="muted" style="margin-bottom:1.5rem">Prolog engine error: {html.escape(str(e))}</div>'


