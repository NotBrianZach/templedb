#!/usr/bin/env python3
"""
TempleDB Web GUI — FastAPI + HTMX
"""
import html
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db_utils import query_all, query_one

from fastapi import FastAPI, Form, Query
from fastapi.responses import HTMLResponse

app = FastAPI(title="TempleDB")

TEMPLEDB = str(Path(__file__).parent.parent / "templedb")


# ── CLI helpers ───────────────────────────────────────────────────────────────

def _run(*args: str) -> tuple[int, str, str]:
    r = subprocess.run([TEMPLEDB] + list(args), capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


# ── HTML helpers ──────────────────────────────────────────────────────────────

CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: monospace; background: #0f0f1a; color: #d0d0e8; display: flex; min-height: 100vh; font-size: 14px; }
nav { width: 180px; background: #13131f; padding: 1.2rem 1rem; border-right: 1px solid #1e1e3a; flex-shrink: 0; display: flex; flex-direction: column; gap: 0.2rem; }
nav h1 { color: #e94560; font-size: 1.1rem; margin-bottom: 1.2rem; letter-spacing: 0.05em; }
nav a { color: #808098; text-decoration: none; padding: 0.35rem 0.5rem; border-radius: 4px; display: block; }
nav a:hover { background: #1e1e3a; color: #d0d0e8; }
nav a.active { background: #1a1a30; color: #e94560; }
main { flex: 1; padding: 1.5rem 2rem; overflow: auto; }
h2 { color: #e94560; font-size: 1rem; margin-bottom: 1rem; text-transform: uppercase; letter-spacing: 0.08em; }
h3 { color: #a0a0c0; font-size: 0.9rem; margin-bottom: 0.6rem; }
table { width: 100%; border-collapse: collapse; margin-bottom: 1rem; }
th { text-align: left; padding: 0.4rem 0.6rem; background: #13131f; color: #606080; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.06em; border-bottom: 1px solid #1e1e3a; }
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
"""


def _base(title: str, body: str, active: str = "") -> HTMLResponse:
    nav = "\n".join(
        f'<a href="{href}" class="{"active" if active == k else ""}">{label}</a>'
        for k, href, label in [
            ("projects", "/projects", "Projects"),
            ("vcs",      "/vcs",      "VCS"),
            ("secrets",  "/secrets",  "Secrets"),
            ("status",   "/status",   "Status"),
        ]
    )
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)} — TempleDB</title>
<script src="https://unpkg.com/htmx.org@1.9.10"></script>
<style>{CSS}</style>
</head>
<body>
<nav>
  <h1>TempleDB</h1>
  {nav}
</nav>
<main>
{body}
</main>
</body>
</html>"""
    return HTMLResponse(page)


def _table(headers: list[str], rows: list[list[str]], empty: str = "No results.") -> str:
    if not rows:
        return f'<p class="muted">{html.escape(empty)}</p>'
    ths = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    trs = ""
    for row in rows:
        tds = "".join(f"<td>{cell}</td>" for cell in row)
        trs += f"<tr>{tds}</tr>"
    return f"<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>"


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


# ── Root ──────────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/projects")


# ── Projects ──────────────────────────────────────────────────────────────────

@app.get("/projects", response_class=HTMLResponse)
def projects_list():
    rows_data = query_all("""
        SELECT p.slug, p.name, p.repo_url, p.updated_at,
               (SELECT COUNT(*) FROM project_files WHERE project_id = p.id) AS files,
               (SELECT COALESCE(SUM(lines_of_code),0) FROM project_files WHERE project_id = p.id) AS loc,
               (SELECT checkout_path FROM checkouts c WHERE c.project_id = p.id AND c.is_active=1 ORDER BY last_sync_at DESC LIMIT 1) AS checkout_path,
               (SELECT MAX(last_sync_at) FROM checkouts c WHERE c.project_id = p.id AND c.is_active=1) AS last_synced,
               (SELECT vc.commit_hash FROM vcs_commits vc WHERE vc.project_id = p.id ORDER BY vc.commit_timestamp DESC LIMIT 1) AS last_commit_hash,
               (SELECT vc.commit_message FROM vcs_commits vc WHERE vc.project_id = p.id ORDER BY vc.commit_timestamp DESC LIMIT 1) AS last_commit_msg,
               (SELECT vc.commit_timestamp FROM vcs_commits vc WHERE vc.project_id = p.id ORDER BY vc.commit_timestamp DESC LIMIT 1) AS last_commit_at
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
        ]
        for r in rows_data
    ]
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
    body = f"""
<h2>Projects</h2>
{_table(["Slug", "Name", "Files", "LOC", "Location", "Updated", "Synced", "Latest Commit"], rows, "No projects found.")}
{import_form}
"""
    return _base("Projects", body, "projects")


@app.post("/projects/import", response_class=HTMLResponse)
def projects_import(path: str = Form(...), slug: str = Form("")):
    cmd = ["project", "import", path]
    if slug.strip():
        cmd += ["--slug", slug.strip()]
    rc, out, err = _run(*cmd)
    msg = out or err or "Done"
    return HTMLResponse(_msg(msg, ok=rc == 0))


@app.get("/projects/{slug}", response_class=HTMLResponse)
def project_files(slug: str, q: str = Query(default="")):
    proj = query_one("SELECT id, name FROM projects WHERE slug = ?", (slug,))
    if not proj:
        return _base("Not found", f'<p class="muted">Project "{html.escape(slug)}" not found.</p>', "projects")

    files_html = _file_rows(slug, q)
    body = f"""
<h2><a href="/projects">Projects</a> / {html.escape(slug)}</h2>
<div class="row">
  <input id="search-input" type="text" name="q" value="{html.escape(q)}"
    placeholder="Search files…"
    hx-get="/projects/{html.escape(slug)}/search"
    hx-target="#file-list"
    hx-trigger="keyup changed delay:250ms"
    hx-include="[name='q']"
  >
</div>
<div id="file-list">
{files_html}
</div>
"""
    return _base(slug, body, "projects")


@app.get("/projects/{slug}/search", response_class=HTMLResponse)
def project_files_search(slug: str, q: str = Query(default="")):
    return HTMLResponse(_file_rows(slug, q))


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


@app.get("/projects/{slug}/file", response_class=HTMLResponse)
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

@app.get("/vcs", response_class=HTMLResponse)
def vcs_index():
    projects = query_all("SELECT slug, name FROM projects ORDER BY slug")
    rows = [
        [
            f'<a href="/vcs/{html.escape(r["slug"])}">{html.escape(r["slug"])}</a>',
            html.escape(r["name"] or ""),
        ]
        for r in projects
    ]
    body = f"<h2>VCS — Select Project</h2>{_table(['Slug', 'Name'], rows, 'No projects.')}"
    return _base("VCS", body, "vcs")


@app.get("/vcs/{slug}", response_class=HTMLResponse)
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
{_table(["Hash", "Branch", "Author", "Message", "Date"], rows, "No commits yet.")}
"""
    return _base(f"VCS: {slug}", body, "vcs")


@app.get("/vcs/{slug}/commits/{commit_hash}", response_class=HTMLResponse)
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
        SELECT pf.file_path, fs.state
        FROM vcs_file_states fs
        JOIN project_files pf ON fs.file_id = pf.id
        WHERE fs.commit_id = (SELECT id FROM vcs_commits WHERE commit_hash LIKE ? LIMIT 1)
        ORDER BY pf.file_path
    """, (f"{commit_hash}%",))

    icons = {"added": "✦", "modified": "✎", "deleted": "✗"}
    file_rows = [
        [icons.get(r["state"], "?"), html.escape(r["file_path"]), html.escape(r["state"])]
        for r in files
    ]

    rc, diff_out, diff_err = _run("vcs", "diff", slug, "--commit", commit_hash[:8])
    diff_html = (
        f'<pre>{_colorize_diff(diff_out)}</pre>'
        if rc == 0 and diff_out
        else f'<p class="muted">{html.escape(diff_err or "No diff available.")}</p>'
    )

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


@app.get("/vcs/{slug}/branches", response_class=HTMLResponse)
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


@app.get("/vcs/{slug}/staging", response_class=HTMLResponse)
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
        SELECT id FROM vcs_branches WHERE project_id = ? AND is_default = 1
    """, (proj["id"],))
    if not branch:
        return '<p class="muted">No default branch.</p>'

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


@app.post("/vcs/{slug}/staging/stage/{file_id}", response_class=HTMLResponse)
def vcs_stage_file(slug: str, file_id: int):
    proj = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
    branch = query_one("SELECT id FROM vcs_branches WHERE project_id = ? AND is_default = 1", (proj["id"],))
    from db_utils import execute
    execute("UPDATE vcs_working_state SET staged = 1 WHERE file_id = ? AND project_id = ? AND branch_id = ?",
            (file_id, proj["id"], branch["id"]))
    return HTMLResponse(_staging_area(slug))


@app.post("/vcs/{slug}/staging/unstage/{file_id}", response_class=HTMLResponse)
def vcs_unstage_file(slug: str, file_id: int):
    proj = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
    branch = query_one("SELECT id FROM vcs_branches WHERE project_id = ? AND is_default = 1", (proj["id"],))
    from db_utils import execute
    execute("UPDATE vcs_working_state SET staged = 0 WHERE file_id = ? AND project_id = ? AND branch_id = ?",
            (file_id, proj["id"], branch["id"]))
    return HTMLResponse(_staging_area(slug))


@app.post("/vcs/{slug}/staging/add-all", response_class=HTMLResponse)
def vcs_stage_all(slug: str):
    _run("vcs", "add", "-p", slug, "--all")
    return HTMLResponse(_staging_area(slug))


@app.post("/vcs/{slug}/staging/reset-all", response_class=HTMLResponse)
def vcs_unstage_all(slug: str):
    _run("vcs", "reset", "-p", slug, "--all")
    return HTMLResponse(_staging_area(slug))


@app.post("/vcs/{slug}/commit", response_class=HTMLResponse)
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

@app.get("/secrets", response_class=HTMLResponse)
def secrets_list():
    secrets = query_all("""
        SELECT p.slug AS project_slug, psb.profile, sb.created_at, sb.updated_at
        FROM project_secret_blobs psb
        JOIN projects p ON psb.project_id = p.id
        JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
        ORDER BY p.slug, psb.profile
    """)
    rows = [
        [
            f'<a href="/secrets/{html.escape(r["project_slug"])}/{html.escape(r["profile"])}">'
            f'{html.escape(r["project_slug"])}</a>',
            html.escape(r["profile"]),
            html.escape((r["created_at"] or "")[:10]),
            html.escape((r["updated_at"] or "")[:10]),
        ]
        for r in secrets
    ]
    body = f"<h2>Secrets</h2>{_table(['Project', 'Profile', 'Created', 'Updated'], rows, 'No secrets found.')}"
    return _base("Secrets", body, "secrets")


@app.get("/secrets/{slug}/{profile}", response_class=HTMLResponse)
def secret_detail(slug: str, profile: str):
    rc, out, err = _run("secret", "export", slug, "--profile", profile, "--format", "json")

    if rc == 0 and out:
        try:
            data = json.loads(out)
            keys = sorted(data.keys())
            rows = [[html.escape(k), '<span class="muted">••••••</span>'] for k in keys]
            table = _table(["Key", "Value"], rows, "No keys.")
            note = '<p class="muted" style="margin-top:0.5rem">Values hidden. Use CLI to view: <code>templedb secret export ' + html.escape(slug) + '</code></p>'
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


# ── Status ────────────────────────────────────────────────────────────────────

@app.get("/status", response_class=HTMLResponse)
def status():
    project_count = (query_one("SELECT COUNT(*) AS n FROM projects") or {}).get("n", 0)
    file_count = (query_one("SELECT COUNT(*) AS n FROM project_files") or {}).get("n", 0)
    commit_count = (query_one("SELECT COUNT(*) AS n FROM vcs_commits") or {}).get("n", 0)
    loc = (query_one("SELECT COALESCE(SUM(lines_of_code),0) AS n FROM project_files") or {}).get("n", 0)

    try:
        from config import default_db_path
        db_path = default_db_path()
        db_size = os.path.getsize(db_path) / 1024 / 1024
        db_info = f'{db_size:.1f} MB — <span class="muted">{html.escape(str(db_path))}</span>'
    except Exception:
        db_info = "unknown"

    stats = [
        (project_count, "Projects"),
        (f"{file_count:,}", "Files"),
        (f"{commit_count:,}", "Commits"),
        (f"{loc:,}", "Lines of Code"),
    ]
    stats_html = "".join(
        f'<div class="stat"><div class="val">{v}</div><div class="key">{k}</div></div>'
        for v, k in stats
    )

    body = f"""
<h2>Status</h2>
<div style="margin-bottom:1.5rem">{stats_html}</div>
<p class="muted">Database: {db_info}</p>
"""
    return _base("Status", body, "status")
