"""TempleDB GUI — Vcs pages."""
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



# ── Routes migrated from nix.py ──

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


