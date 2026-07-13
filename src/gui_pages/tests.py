"""TempleDB GUI — Tests pages."""
import html
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from fastapi import APIRouter, Form, Query
from fastapi.responses import HTMLResponse

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import execute, query_all, query_one

router = APIRouter()

# Import helpers from parent gui module
import gui as _gui
_base = _gui._base
_table = _gui._table
_search_bar = _gui._search_bar
_msg = _gui._msg
_status_badge = _gui._status_badge

@router.get("/tests", response_class=HTMLResponse)
def tests_page():
    """Tests Dashboard — run QA tests against projects."""
    from test_runner import detect_project_type, PROJECT_TESTS, STRUCTURE_TESTS

    projects = query_all("SELECT slug, repo_url, name FROM projects ORDER BY slug")

    rows = []
    for p in projects:
        slug = p["slug"]
        checkout = Path.home() / ".config" / "templedb" / "checkouts" / slug
        repo_path = Path(p.get("repo_url") or "") if p.get("repo_url") else None

        # Pick best path
        if repo_path and repo_path.exists() and (
            (repo_path / "src" / "gui.py").exists() or
            (repo_path / "frontend" / "package.json").exists() or
            (repo_path / "package.json").exists() or
            (repo_path / "backend" / "app.py").exists() or
            (repo_path / "app.py").exists()
        ):
            project_path = repo_path
        elif checkout.exists():
            project_path = checkout
        elif repo_path and repo_path.exists():
            project_path = repo_path
        else:
            project_path = None

        if not project_path:
            continue

        ptype = detect_project_type(project_path)
        has_tests = slug in PROJECT_TESTS
        has_struct = slug in STRUCTURE_TESTS

        badges = []
        if has_tests:
            badges.append('<span style="background:#1a3a1a;color:#8f8;padding:1px 6px;border-radius:3px;font-size:0.72rem">server tests</span>')
        if has_struct:
            badges.append('<span style="background:#1a2a3a;color:#8af;padding:1px 6px;border-radius:3px;font-size:0.72rem">structure tests</span>')
        if not badges:
            badges.append('<span style="color:#606080;font-size:0.72rem">auto-detect only</span>')

        run_btn = (
            f'<button hx-post="/tests/run/{slug}" '
            f'hx-target="#test-result-{slug}" hx-swap="innerHTML" '
            f'hx-indicator="#test-spinner-{slug}" '
            f'style="background:#1a1a3a;border:1px solid #2a2a4a;color:#d0d0e8;'
            f'padding:2px 8px;border-radius:3px;cursor:pointer;font-family:monospace;font-size:0.78rem">'
            f'Run Tests</button>'
            f'<span id="test-spinner-{slug}" class="htmx-indicator" style="color:#606080;font-size:0.72rem"> running...</span>'
        )

        rows.append([
            f'<a href="/tests/{html.escape(slug)}" style="color:#d0d0e8"><strong>{html.escape(slug)}</strong></a>',
            html.escape(ptype),
            " ".join(badges),
            run_btn,
            f'<div id="test-result-{slug}" class="muted" style="font-size:0.78rem">—</div>',
        ])

    table = _table(
        ["Project", "Type", "Tests", "Action", "Results"],
        rows, "No testable projects found", "tests-table")

    body = f"""
<h2>Tests Dashboard</h2>
<p class="muted" style="margin-bottom:1rem">
  Run QA tests against TempleDB-managed projects. Structure tests run instantly.
  Server tests start the app and check page loads + endpoints.
</p>

<button hx-post="/tests/run-all" hx-target="#run-all-results" hx-swap="innerHTML"
  hx-indicator="#run-all-spinner"
  style="background:#1a1a3a;border:1px solid #3a3a5a;color:#d0d0e8;
  padding:4px 12px;border-radius:4px;cursor:pointer;font-family:monospace;
  font-size:0.85rem;margin-bottom:1rem">Run All Tests</button>
<span id="run-all-spinner" class="htmx-indicator" style="color:#606080"> running all...</span>
<div id="run-all-results"></div>

{_search_bar("tests-table", "Filter projects...")}
{table}
"""
    return _base("Tests", body, "tests")


@router.post("/tests/run/{slug}", response_class=HTMLResponse)
def tests_run_project(slug: str):
    """Run tests for a single project and return results as HTML."""
    from test_runner import run_tests, detect_project_type, TestResult

    project = query_one("SELECT slug, repo_url FROM projects WHERE slug = ?", (slug,))
    if not project:
        return HTMLResponse(f'<span style="color:#e94560">Project not found</span>')

    # Resolve path
    checkout = Path.home() / ".config" / "templedb" / "checkouts" / slug
    repo_path = Path(project.get("repo_url") or "") if project.get("repo_url") else None

    if repo_path and repo_path.exists() and (
        (repo_path / "src" / "gui.py").exists() or
        (repo_path / "frontend" / "package.json").exists() or
        (repo_path / "package.json").exists() or
        (repo_path / "backend" / "app.py").exists() or
        (repo_path / "app.py").exists()
    ):
        project_path = repo_path
    elif checkout.exists():
        project_path = checkout
    elif repo_path and repo_path.exists():
        project_path = repo_path
    else:
        return HTMLResponse(f'<span style="color:#e94560">No project path found</span>')

    # Capture test output
    import io
    old_stdout = sys.stdout
    sys.stdout = captured = io.StringIO()

    try:
        success = run_tests(slug, project_path, verbose=True)
    except Exception as e:
        sys.stdout = old_stdout
        return HTMLResponse(f'<span style="color:#e94560">Error: {html.escape(str(e))}</span>')
    finally:
        sys.stdout = old_stdout

    output = captured.getvalue()

    # Parse results from output
    lines = output.strip().split("\n")
    result_parts = []
    for line in lines:
        line_clean = re.sub(r'\033\[[0-9;]*m', '', line)  # strip ANSI
        if "PASS" in line_clean:
            test_name = line_clean.replace("PASS", "").strip()
            result_parts.append(f'<div style="color:#4a9a6a;font-size:0.75rem">&#x2713; {html.escape(test_name)}</div>')
        elif "FAIL" in line_clean:
            test_name = line_clean.replace("FAIL", "").strip()
            result_parts.append(f'<div style="color:#e94560;font-size:0.75rem">&#x2717; {html.escape(test_name)}</div>')

    # Summary line
    for line in lines:
        if "Results:" in line:
            line_clean = re.sub(r'\033\[[0-9;]*m', '', line)
            if success:
                summary = f'<div style="color:#4a9a6a;font-weight:bold;margin-top:4px">{html.escape(line_clean.strip())}</div>'
            else:
                summary = f'<div style="color:#e94560;font-weight:bold;margin-top:4px">{html.escape(line_clean.strip())}</div>'
            result_parts.append(summary)
            break

    if not result_parts:
        if success:
            result_parts.append('<div style="color:#4a9a6a">All tests passed</div>')
        else:
            result_parts.append(f'<div style="color:#e94560">Tests failed</div>')

    # Collapsible detail
    detail_id = f"detail-{slug}"
    result_html = (
        f'<details><summary style="cursor:pointer;color:#a0a0c0;font-size:0.78rem">'
        f'{"&#x2713;" if success else "&#x2717;"} '
        f'{result_parts[-1] if result_parts else ""}</summary>'
        f'<div style="margin-top:4px;padding:4px 8px;background:#0a0a15;border-radius:4px">'
        f'{"".join(result_parts[:-1])}'
        f'</div></details>'
    )

    return HTMLResponse(result_html)


@router.post("/tests/run-all", response_class=HTMLResponse)
def tests_run_all():
    """Run tests for all testable projects."""
    from test_runner import PROJECT_TESTS, STRUCTURE_TESTS

    testable = set(list(PROJECT_TESTS.keys()) + list(STRUCTURE_TESTS.keys()))
    results = []

    for slug in sorted(testable):
        # Trigger individual test and collect summary
        r = tests_run_project(slug)
        body = r.body.decode() if hasattr(r, 'body') else str(r)
        results.append(f'<div style="margin-bottom:4px"><strong>{html.escape(slug)}</strong>: {body}</div>')

        # Also update the individual result span via OOB
        results.append(
            f'<div id="test-result-{html.escape(slug)}" hx-swap-oob="innerHTML">{body}</div>'
        )

    return HTMLResponse("".join(results))


@router.get("/tests/{slug}", response_class=HTMLResponse)
def tests_detail(slug: str):
    """Per-project test detail page with editable test definitions."""
    project = query_one("SELECT * FROM projects WHERE slug = ?", (slug,))
    if not project:
        return _base("Not found", f'<p class="muted">Project "{html.escape(slug)}" not found.</p>', "tests")

    pid = project["id"]

    # Load test definitions
    tests = query_all(
        "SELECT * FROM project_tests WHERE project_id = ? ORDER BY test_type, path, file_path", (pid,))

    # Group by type
    page_tests = [t for t in tests if t["test_type"] == "page"]
    post_tests = [t for t in tests if t["test_type"] == "post"]
    struct_file_tests = [t for t in tests if t["test_type"] == "structure_file"]
    struct_dir_tests = [t for t in tests if t["test_type"] == "structure_dir"]

    # Build page tests table
    page_rows = []
    for t in page_tests:
        enabled = '&#x2713;' if t["enabled"] else '&#x2717;'
        toggle_btn = (
            f'<button hx-post="/tests/{slug}/toggle/{t["id"]}" hx-target="#test-row-{t["id"]}" hx-swap="outerHTML" '
            f'style="background:none;border:none;color:#d0d0e8;cursor:pointer;font-size:0.8rem" '
            f'title="Toggle enabled">{"&#x1f7e2;" if t["enabled"] else "&#x26aa;"}</button>')
        delete_btn = (
            f'<button hx-delete="/tests/{slug}/delete/{t["id"]}" hx-target="#test-row-{t["id"]}" hx-swap="outerHTML" '
            f'hx-confirm="Delete this test?" '
            f'style="background:none;border:none;color:#e94560;cursor:pointer;font-size:0.8rem">&#x2717;</button>')
        page_rows.append(f'<tr id="test-row-{t["id"]}"><td><code>{html.escape(t["path"] or "")}</code></td>'
                        f'<td>{html.escape(t["expected_text"] or "")}</td>'
                        f'<td>{html.escape(t["description"] or "")}</td>'
                        f'<td>{toggle_btn} {delete_btn}</td></tr>')

    # Build structure tests table
    struct_rows = []
    for t in struct_file_tests + struct_dir_tests:
        ttype = "file" if t["test_type"] == "structure_file" else "dir"
        toggle_btn = (
            f'<button hx-post="/tests/{slug}/toggle/{t["id"]}" hx-target="#test-row-{t["id"]}" hx-swap="outerHTML" '
            f'style="background:none;border:none;color:#d0d0e8;cursor:pointer;font-size:0.8rem">'
            f'{"&#x1f7e2;" if t["enabled"] else "&#x26aa;"}</button>')
        delete_btn = (
            f'<button hx-delete="/tests/{slug}/delete/{t["id"]}" hx-target="#test-row-{t["id"]}" hx-swap="outerHTML" '
            f'hx-confirm="Delete this test?" '
            f'style="background:none;border:none;color:#e94560;cursor:pointer;font-size:0.8rem">&#x2717;</button>')
        struct_rows.append(f'<tr id="test-row-{t["id"]}"><td>{ttype}</td>'
                          f'<td><code>{html.escape(t["file_path"] or "")}</code></td>'
                          f'<td>{html.escape(t["description"] or "")}</td>'
                          f'<td>{toggle_btn} {delete_btn}</td></tr>')

    # Post tests table
    post_rows = []
    for t in post_tests:
        toggle_btn = (
            f'<button hx-post="/tests/{slug}/toggle/{t["id"]}" hx-target="#test-row-{t["id"]}" hx-swap="outerHTML" '
            f'style="background:none;border:none;color:#d0d0e8;cursor:pointer;font-size:0.8rem">'
            f'{"&#x1f7e2;" if t["enabled"] else "&#x26aa;"}</button>')
        delete_btn = (
            f'<button hx-delete="/tests/{slug}/delete/{t["id"]}" hx-target="#test-row-{t["id"]}" hx-swap="outerHTML" '
            f'hx-confirm="Delete this test?" '
            f'style="background:none;border:none;color:#e94560;cursor:pointer;font-size:0.8rem">&#x2717;</button>')
        post_rows.append(f'<tr id="test-row-{t["id"]}"><td><code>{html.escape(t["path"] or "")}</code></td>'
                        f'<td>{html.escape(t["expected_text"] or "")}</td>'
                        f'<td>{html.escape(t["description"] or "")}</td>'
                        f'<td>{toggle_btn} {delete_btn}</td></tr>')

    # Test history
    history = query_all(
        "SELECT * FROM test_runs WHERE project_id = ? ORDER BY created_at DESC LIMIT 10", (pid,))
    history_rows = []
    for h in history:
        color = "#4a9a6a" if h["failed"] == 0 else "#e94560"
        history_rows.append([
            f'<span style="color:{color}">{h["passed"]}/{h["passed"] + h["failed"]}</span>',
            f'{h.get("duration_ms", 0) or 0}ms',
            f'<span class="muted">{html.escape((h["created_at"] or "")[:19])}</span>',
        ])

    # Add test forms
    input_style = ('style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;'
                   'padding:4px 8px;border-radius:3px;font-family:monospace;font-size:0.8rem;width:250px"')
    btn_style = ('style="background:#1a3a1a;border:1px solid #2a4a2a;color:#8f8;'
                 'padding:4px 10px;border-radius:3px;cursor:pointer;font-family:monospace;font-size:0.8rem"')

    add_page_form = f"""
<form hx-post="/tests/{slug}/add" hx-target="#add-page-result" hx-swap="innerHTML"
  style="display:flex;gap:8px;align-items:center;margin-top:8px">
  <input type="hidden" name="test_type" value="page">
  <input name="path" placeholder="/path" {input_style} style="width:150px">
  <input name="expected_text" placeholder="Expected text" {input_style} style="width:180px">
  <input name="description" placeholder="Description" {input_style} style="width:180px">
  <button type="submit" {btn_style}>+ Add Page Test</button>
  <span id="add-page-result"></span>
</form>"""

    add_post_form = f"""
<form hx-post="/tests/{slug}/add" hx-target="#add-post-result" hx-swap="innerHTML"
  style="display:flex;gap:8px;align-items:center;margin-top:8px">
  <input type="hidden" name="test_type" value="post">
  <input name="path" placeholder="/path" {input_style} style="width:150px">
  <input name="expected_text" placeholder="Expected text" {input_style} style="width:180px">
  <input name="description" placeholder="Description" {input_style} style="width:180px">
  <button type="submit" {btn_style}>+ Add POST Test</button>
  <span id="add-post-result"></span>
</form>"""

    add_struct_form = f"""
<form hx-post="/tests/{slug}/add" hx-target="#add-struct-result" hx-swap="innerHTML"
  style="display:flex;gap:8px;align-items:center;margin-top:8px">
  <select name="test_type" style="background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;padding:4px;border-radius:3px;font-family:monospace;font-size:0.8rem">
    <option value="structure_file">File</option>
    <option value="structure_dir">Dir</option>
  </select>
  <input name="file_path" placeholder="relative/path" {input_style} style="width:200px">
  <input name="description" placeholder="Description" {input_style} style="width:180px">
  <button type="submit" {btn_style}>+ Add Structure Test</button>
  <span id="add-struct-result"></span>
</form>"""

    # Load test deps
    test_deps = query_all(
        "SELECT * FROM project_test_deps WHERE project_id = ? ORDER BY nix_package", (pid,))
    dep_rows = []
    for d in test_deps:
        resolved = ""
        try:
            from test_runner import _find_nix_binary
            binary = _find_nix_binary(d["nix_package"], d.get("binary_name"))
            resolved = f'<span style="color:#8f8;font-size:0.7rem">{html.escape(str(binary))}</span>' if binary else '<span style="color:#f88;font-size:0.7rem">not found</span>'
        except Exception:
            resolved = '<span style="color:#888;font-size:0.7rem">?</span>'
        enabled_color = "#8f8" if d["enabled"] else "#888"
        dep_rows.append(
            f'<tr id="dep-row-{d["id"]}">'
            f'<td><code>{html.escape(d["nix_package"])}</code></td>'
            f'<td>{html.escape(d.get("env_var") or "")}</td>'
            f'<td>{html.escape(d.get("binary_name") or "")}</td>'
            f'<td>{html.escape(d.get("reason") or "")}</td>'
            f'<td>{resolved}</td>'
            f'<td>'
            f'<button hx-post="/tests/{slug}/dep/toggle/{d["id"]}" hx-target="#dep-row-{d["id"]}" hx-swap="outerHTML" '
            f'style="background:none;border:none;cursor:pointer;color:{enabled_color}">{"●" if d["enabled"] else "○"}</button> '
            f'<button hx-delete="/tests/{slug}/dep/delete/{d["id"]}" hx-target="#dep-row-{d["id"]}" hx-swap="outerHTML" '
            f'style="background:none;border:none;cursor:pointer;color:#f66">✕</button>'
            f'</td></tr>'
        )
    deps_table_html = (
        f'<table><thead><tr><th>Package</th><th>Env Var</th><th>Binary</th><th>Reason</th><th>Resolved</th><th></th></tr></thead>'
        f'<tbody>{"".join(dep_rows)}</tbody></table>' if dep_rows else '<p class="muted">No test dependencies</p>')

    add_dep_form = f"""
<form hx-post="/tests/{slug}/dep/add" hx-target="#add-dep-result" hx-swap="innerHTML"
  style="display:flex;gap:8px;align-items:center;margin-top:8px">
  <input name="nix_package" placeholder="chromium" {input_style} style="width:120px">
  <input name="env_var" placeholder="CHROME_PATH" {input_style} style="width:120px">
  <input name="binary_name" placeholder="chromium" {input_style} style="width:120px">
  <input name="reason" placeholder="Reason" {input_style} style="width:160px">
  <button type="submit" {btn_style}>+ Add Dep</button>
  <span id="add-dep-result"></span>
</form>"""

    # Run button
    run_btn = (
        f'<button hx-post="/tests/run/{slug}" hx-target="#run-result" hx-swap="innerHTML" '
        f'hx-indicator="#run-spinner" '
        f'style="background:#1a1a3a;border:1px solid #3a3a5a;color:#d0d0e8;'
        f'padding:6px 16px;border-radius:4px;cursor:pointer;font-family:monospace;'
        f'font-size:0.85rem;margin-bottom:1rem">Run All Tests</button>'
        f'<span id="run-spinner" class="htmx-indicator" style="color:#606080"> running...</span>'
    )

    page_table_html = (
        f'<table><thead><tr><th>Path</th><th>Expected</th><th>Description</th><th></th></tr></thead>'
        f'<tbody>{"".join(page_rows)}</tbody></table>' if page_rows else '<p class="muted">No page tests</p>')

    post_table_html = (
        f'<table><thead><tr><th>Path</th><th>Expected</th><th>Description</th><th></th></tr></thead>'
        f'<tbody>{"".join(post_rows)}</tbody></table>' if post_rows else '<p class="muted">No POST tests</p>')

    struct_table_html = (
        f'<table><thead><tr><th>Type</th><th>Path</th><th>Description</th><th></th></tr></thead>'
        f'<tbody>{"".join(struct_rows)}</tbody></table>' if struct_rows else '<p class="muted">No structure tests</p>')

    body = f"""
<h2>Tests: {html.escape(slug)}</h2>
<p><a href="/tests" style="color:#606080">&larr; All Projects</a></p>

{run_btn}
<div id="run-result" style="margin-bottom:1.5rem"></div>

<h3>Page Tests ({len(page_tests)})</h3>
{page_table_html}
{add_page_form}

<h3 style="margin-top:1.5rem">POST Tests ({len(post_tests)})</h3>
{post_table_html}
{add_post_form}

<h3 style="margin-top:1.5rem">Structure Tests ({len(struct_file_tests) + len(struct_dir_tests)})</h3>
{struct_table_html}
{add_struct_form}

<h3 style="margin-top:1.5rem">Test Dependencies (Nix Packages)</h3>
{deps_table_html}
{add_dep_form}

<h3 style="margin-top:1.5rem">Run History</h3>
{_table(["Result", "Duration", "Date"], history_rows, "No test runs yet.")}
"""
    return _base(f"Tests: {slug}", body, "tests")


@router.post("/tests/{slug}/add", response_class=HTMLResponse)
def tests_add(slug: str, test_type: str = Form(...), path: str = Form(""),
              expected_text: str = Form(""), description: str = Form(""),
              file_path: str = Form(""), post_data: str = Form("")):
    """Add a new test definition."""
    project = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
    if not project:
        return HTMLResponse(_msg("Project not found", ok=False))

    if test_type in ("page", "post") and not path:
        return HTMLResponse(_msg("Path is required", ok=False))
    if test_type.startswith("structure_") and not file_path:
        return HTMLResponse(_msg("File path is required", ok=False))

    execute("""
        INSERT INTO project_tests (project_id, test_type, path, expected_text, post_data, file_path, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (project["id"], test_type,
          path or None, expected_text or None,
          post_data or None, file_path or None,
          description or None))

    return HTMLResponse(_msg(f"Added {test_type} test", ok=True))


@router.post("/tests/{slug}/toggle/{test_id}", response_class=HTMLResponse)
def tests_toggle(slug: str, test_id: int):
    """Toggle a test definition enabled/disabled."""
    test = query_one("SELECT * FROM project_tests WHERE id = ?", (test_id,))
    if not test:
        return HTMLResponse("")

    new_enabled = 0 if test["enabled"] else 1
    execute("UPDATE project_tests SET enabled = ?, updated_at = datetime('now') WHERE id = ?",
            (new_enabled, test_id))

    # Return updated row
    test = query_one("SELECT * FROM project_tests WHERE id = ?", (test_id,))
    toggle_icon = "&#x1f7e2;" if test["enabled"] else "&#x26aa;"
    toggle_btn = (
        f'<button hx-post="/tests/{slug}/toggle/{test_id}" hx-target="#test-row-{test_id}" hx-swap="outerHTML" '
        f'style="background:none;border:none;color:#d0d0e8;cursor:pointer;font-size:0.8rem">{toggle_icon}</button>')
    delete_btn = (
        f'<button hx-delete="/tests/{slug}/delete/{test_id}" hx-target="#test-row-{test_id}" hx-swap="outerHTML" '
        f'hx-confirm="Delete this test?" '
        f'style="background:none;border:none;color:#e94560;cursor:pointer;font-size:0.8rem">&#x2717;</button>')

    if test["test_type"] in ("page", "post"):
        return HTMLResponse(
            f'<tr id="test-row-{test_id}"><td><code>{html.escape(test["path"] or "")}</code></td>'
            f'<td>{html.escape(test["expected_text"] or "")}</td>'
            f'<td>{html.escape(test["description"] or "")}</td>'
            f'<td>{toggle_btn} {delete_btn}</td></tr>')
    else:
        ttype = "file" if test["test_type"] == "structure_file" else "dir"
        return HTMLResponse(
            f'<tr id="test-row-{test_id}"><td>{ttype}</td>'
            f'<td><code>{html.escape(test["file_path"] or "")}</code></td>'
            f'<td>{html.escape(test["description"] or "")}</td>'
            f'<td>{toggle_btn} {delete_btn}</td></tr>')


@app.delete("/tests/{slug}/delete/{test_id}", response_class=HTMLResponse)
def tests_delete(slug: str, test_id: int):
    """Delete a test definition."""
    execute("DELETE FROM project_tests WHERE id = ?", (test_id,))
    return HTMLResponse("")


@router.post("/tests/{slug}/dep/add", response_class=HTMLResponse)
def tests_dep_add(slug: str, nix_package: str = Form(...), env_var: str = Form(""),
                  binary_name: str = Form(""), reason: str = Form("")):
    """Add a test dependency (nix package)."""
    project = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
    if not project:
        return HTMLResponse(_msg("Project not found", ok=False))
    if not nix_package.strip():
        return HTMLResponse(_msg("Package name required", ok=False))
    execute("""
        INSERT OR IGNORE INTO project_test_deps (project_id, nix_package, env_var, binary_name, reason)
        VALUES (?, ?, ?, ?, ?)
    """, (project["id"], nix_package.strip(), env_var.strip() or None, binary_name.strip() or None, reason.strip() or None))
    return HTMLResponse(_msg(f"Added dep: {nix_package}", ok=True))


@router.post("/tests/{slug}/dep/toggle/{dep_id}", response_class=HTMLResponse)
def tests_dep_toggle(slug: str, dep_id: int):
    """Toggle a test dependency enabled/disabled."""
    dep = query_one("SELECT * FROM project_test_deps WHERE id = ?", (dep_id,))
    if dep:
        execute("UPDATE project_test_deps SET enabled = ? WHERE id = ?", (0 if dep["enabled"] else 1, dep_id))
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/tests/{slug}", status_code=303)


@app.delete("/tests/{slug}/dep/delete/{dep_id}", response_class=HTMLResponse)
def tests_dep_delete(slug: str, dep_id: int):
    """Delete a test dependency."""
    execute("DELETE FROM project_test_deps WHERE id = ?", (dep_id,))
    return HTMLResponse("")


# ── Modular page routers (split from monolith) ──────────────────────
# Pages are incrementally moved to gui_pages/*.py as APIRouter modules.
# Remaining routes stay in this file until migrated.
#
# To split a page:
# 1. Create gui_pages/{name}.py with `router = APIRouter()`
# 2. Move @app.get/@app.post routes there as @router.get/@router.post
# 3. Delete the routes from this file
# 4. Add `from gui_pages.{name} import router as {name}_router` below
# 5. Add `app.include_router({name}_router)` below
#
# Already split: (none yet — incremental migration in progress)

