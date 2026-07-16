"""TempleDB GUI — Docs pages."""
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


@router.get("/docs", response_class=HTMLResponse)
def docs_list(project: str = Query(""), category: str = Query("")):
    readme_files = query_all("""
        SELECT rf.id, p.slug, rf.title, rf.file_path, rf.category, rf.scope,
               rf.word_count, rf.section_count, rf.has_toc, rf.last_scanned_at,
               rf.description
        FROM readme_files rf JOIN projects p ON rf.project_id = p.id
        ORDER BY p.slug, rf.category NULLS LAST, rf.title
    """)

    topics_rows = query_all("""
        SELECT rt.readme_id, rt.topic, rt.relevance
        FROM readme_topics rt
        ORDER BY rt.readme_id, rt.relevance DESC
    """)
    topics_by_doc: dict = defaultdict(list)
    for t in topics_rows:
        topics_by_doc[t["readme_id"]].append(t)  # t["relevance"] is the score

    sections_rows = query_all("""
        SELECT rs.readme_id, rs.heading, rs.level, rs.anchor, rs.line_number
        FROM readme_sections rs ORDER BY rs.readme_id, rs.line_number
    """)
    sections_by_doc: dict = defaultdict(list)
    for s in sections_rows:
        sections_by_doc[s["readme_id"]].append(s)

    # Collect filter options — include ALL projects, not just those with READMEs
    readme_projects = sorted({r["slug"] for r in readme_files})
    all_projects_rows = query_all("SELECT slug FROM projects ORDER BY slug")
    all_projects = sorted({r["slug"] for r in all_projects_rows})
    all_categories = sorted({r["category"] or "uncategorized" for r in readme_files})

    # Filter
    filtered = readme_files
    if project:
        filtered = [r for r in filtered if r["slug"] == project]
    if category:
        cat_match = None if category == "uncategorized" else category
        filtered = [r for r in filtered if (r["category"] or None) == cat_match]

    # Group by category
    by_category: dict = defaultdict(list)
    for r in filtered:
        by_category[r["category"] or "uncategorized"].append(r)

    # Filter dropdowns
    proj_opts = '<option value="">All projects</option>' + "".join(
        f'<option value="{html.escape(p)}" {"selected" if p == project else ""}>{html.escape(p)}</option>'
        for p in all_projects
    )
    cat_opts = '<option value="">All categories</option>' + "".join(
        f'<option value="{html.escape(c)}" {"selected" if c == category else ""}>{html.escape(c)}</option>'
        for c in all_categories
    )

    sections_html = ""
    for cat in sorted(by_category.keys()):
        docs = by_category[cat]
        cat_label = cat.title() if cat != "uncategorized" else "Uncategorized"
        rows = []
        for r in docs:
            doc_topics = topics_by_doc.get(r["id"], [])
            doc_sections = sections_by_doc.get(r["id"], [])
            topic_badges = " ".join(
                f'<span class="badge blue" style="font-size:0.68rem">{html.escape(t["topic"])}</span>'
                for t in doc_topics[:5]
            )
            toc_badge = '<span class="badge green" style="font-size:0.68rem">TOC</span>' if r["has_toc"] else ""
            scope_badge = (
                f'<span class="badge" style="font-size:0.68rem">{html.escape(r["scope"])}</span>'
                if r["scope"] else ""
            )
            title_cell = (
                f'<strong>{_file_link(r["slug"], r["file_path"], r["title"] or r["file_path"])}</strong>'
                if r["file_path"] else f'<strong>{html.escape(r["title"] or "")}</strong>'
            )
            desc = html.escape(r["description"] or "")
            desc_cell = f'<span class="muted" style="font-size:0.8rem">{desc}</span>' if desc else ""

            # Sections expander
            sec_detail = ""
            if doc_sections:
                sec_trs = []
                for s in doc_sections:
                    indent = "&nbsp;" * (s["level"] - 1) * 3
                    anchor_link = (
                        f'<a href="/projects/{html.escape(r["slug"])}/file?path={html.escape(r["file_path"] or "")}#{html.escape(s["anchor"] or "")}" '
                        f'style="font-size:0.78rem">{indent}{html.escape(s["heading"])}</a>'
                        if r["file_path"] else f'{indent}{html.escape(s["heading"])}'
                    )
                    sec_trs.append([
                        f'<span class="muted" style="font-size:0.75rem">H{s["level"]}</span>',
                        anchor_link,
                        f'<span class="muted">{s["line_number"]}</span>',
                    ])
                sec_inner = _table(["Lvl", "Heading", "Line"], sec_trs)
                sec_detail = (
                    f'<details style="margin-top:0.15rem">'
                    f'<summary style="cursor:pointer;color:#606080;font-size:0.75rem">'
                    f'{len(doc_sections)} section{"s" if len(doc_sections) != 1 else ""}</summary>'
                    f'<div style="margin-top:0.3rem">{sec_inner}</div></details>'
                )

            rows.append([
                title_cell + (f'<br>{desc_cell}' if desc_cell else ""),
                f'{r["slug"]}',
                f'{r["word_count"] or 0:,}',
                sec_detail or f'<span class="muted">{r["section_count"] or 0}</span>',
                f'{toc_badge} {scope_badge}'.strip(),
                topic_badges,
                html.escape((r["last_scanned_at"] or "")[:10]),
            ])

        section_table = _table(
            ["Title", "Project", "Words", "Sections", "Flags", "Topics", "Scanned"],
            rows,
        )
        sections_html += (
            f'<div class="fsec" style="margin-top:1.5rem">'
            f'<h3>{html.escape(cat_label)} <span class="muted" style="font-weight:normal;font-size:0.85rem">({len(docs)})</span></h3>'
            f'{section_table}</div>'
        )

    total = len(filtered)

    # ── File Tree Browser ─────────────────────────────────────────────────
    file_tree_html = ""
    browse_slug = project or "system_config"
    try:
        browse_proj = query_one("SELECT id, slug FROM projects WHERE slug = ?", (browse_slug,))
        if browse_proj:
            doc_files = query_all("""
                SELECT pf.file_path, cb.file_size_bytes
                FROM project_files pf
                JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
                JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
                WHERE pf.project_id = ? AND pf.status = 'active'
                AND (pf.file_path LIKE '%.md' OR pf.file_path LIKE '%.nix'
                     OR pf.file_path LIKE '%.json' OR pf.file_path LIKE '%.yaml'
                     OR pf.file_path LIKE '%.yml' OR pf.file_path LIKE '%.toml'
                     OR pf.file_path LIKE '%.sh' OR pf.file_path LIKE '%.py'
                     OR pf.file_path LIKE '%.ts' OR pf.file_path LIKE '%.js'
                     OR pf.file_path LIKE '%.txt' OR pf.file_path LIKE '%.sql'
                     OR pf.file_path LIKE '%.hs' OR pf.file_path LIKE '%.css'
                     OR pf.file_path LIKE '%.html' OR pf.file_path LIKE '%.envrc')
                ORDER BY pf.file_path
            """, (browse_proj["id"],))

            if doc_files:
                # Build tree structure
                tree = {}
                for f in doc_files:
                    parts = f["file_path"].split("/")
                    node = tree
                    for i, p in enumerate(parts[:-1]):
                        node = node.setdefault(p, {})
                    node[parts[-1]] = f

                def _render_tree(node, prefix="", depth=0):
                    result = ""
                    indent = "&nbsp;" * depth * 3
                    for name in sorted(node.keys()):
                        val = node[name]
                        if isinstance(val, dict) and "file_path" not in val:
                            # Directory
                            result += f'<div style="margin:0.1rem 0">{indent}<span style="color:#808098">📁</span> <strong style="font-size:0.82rem;color:#a0a0c0">{html.escape(name)}/</strong></div>'
                            result += _render_tree(val, prefix + name + "/", depth + 1)
                        else:
                            # File
                            fp = val["file_path"]
                            size = val["file_size_bytes"]
                            size_str = f"{size:,}" if size < 10000 else f"{size/1024:.0f}K"
                            ext = name.rsplit(".", 1)[-1] if "." in name else ""
                            icon = {"md": "📄", "nix": "❄", "json": "📋", "py": "🐍", "sh": "⚡", "ts": "📘", "js": "📘", "sql": "🗄"}.get(ext, "📄")
                            result += (
                                f'<div style="margin:0.1rem 0">{indent}{icon} '
                                f'<a href="/projects/{html.escape(browse_slug)}/file?path={html.escape(fp)}" '
                                f'style="font-size:0.82rem">{html.escape(name)}</a> '
                                f'<span class="muted" style="font-size:0.7rem">{size_str}</span></div>'
                            )
                    return result

                tree_rendered = _render_tree(tree)
                file_tree_html = f"""
<div style="border:1px solid #1e1e3a;border-radius:6px;padding:1rem;margin-bottom:1.5rem;max-height:500px;overflow-y:auto">
  <h3 style="margin-bottom:0.5rem">{html.escape(browse_slug)} File Browser
    <span class="help-tip" style="position:relative">?<span class="tip">Browse project files. Click any file to view its contents. Shows text files (.nix, .md, .json, .py, .sh, etc.).</span></span>
  </h3>
  {tree_rendered}
</div>
"""
    except Exception:
        pass

    # ── Project selector for file browser ─────────────────────────────────
    all_proj_opts = "".join(
        f'<option value="{html.escape(s)}"{" selected" if s == browse_slug else ""}>{html.escape(s)}</option>'
        for s in all_projects
    )

    body = f"""
<h2>Docs</h2>

<div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-bottom:1rem;align-items:center">
  <form method="get" style="display:flex;gap:0.5rem;align-items:center">
    <label style="font-size:0.85rem;color:#808098">Browse project:</label>
    <select name="project" onchange="this.form.submit()" style="font-size:0.85rem;padding:0.3rem;background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;border-radius:4px">{all_proj_opts}</select>
    <select name="category" onchange="this.form.submit()" style="font-size:0.85rem;padding:0.3rem;background:#13131f;border:1px solid #2a2a4a;color:#d0d0e8;border-radius:4px">{cat_opts}</select>
    {"" if not (project or category) else '<a href="/docs" style="font-size:0.8rem">clear</a>'}
  </form>
</div>

{file_tree_html}

<h3>Project Documentation ({total})</h3>
{_search_bar("docs-content", "Filter docs…")}
<div id="docs-content">{sections_html or '<p class="muted">No docs found.</p>'}</div>

{CLI_REFERENCE}

<h3 style="margin-top:1.5rem">Quick Config Links</h3>
{_project_config_links()}
"""
    return _base("Docs", body, "docs")


def _project_config_links() -> str:
    """Generate quick links to key config files across projects."""
    config_patterns = [
        ("NixOS", ["flake.nix", "home.nix", "configuration.nix"]),
        ("Project", ["package.json", "Cargo.toml", "flake.nix", "shell.nix", "default.nix"]),
        ("Docs", ["README.md", "CHANGELOG.md", "CLAUDE.md", "AGENTS.md"]),
        ("CI/Deploy", [".github/workflows/test.yml", "deploy.sh", "Dockerfile"]),
    ]

    projects = query_all("SELECT slug FROM projects ORDER BY slug")
    if not projects:
        return '<p class="muted">No projects.</p>'

    rows = []
    for proj in projects:
        slug = proj["slug"]
        # Find which config files exist for this project
        files = query_all(
            "SELECT file_path FROM project_files WHERE project_id = "
            "(SELECT id FROM projects WHERE slug = ?) AND status = 'active' "
            "AND (file_path IN (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "OR file_path LIKE '%README%' OR file_path LIKE '%CLAUDE%')"
            "ORDER BY file_path LIMIT 10",
            (slug, "flake.nix", "home.nix", "configuration.nix",
             "package.json", "Cargo.toml", "shell.nix", "default.nix",
             "README.md", "CHANGELOG.md", "AGENTS.md", "Dockerfile")
        )
        if files:
            links = " ".join(
                f'<a href="/projects/{html.escape(slug)}/file?path={html.escape(f["file_path"])}" '
                f'style="font-size:0.75rem">{html.escape(f["file_path"].split("/")[-1])}</a>'
                for f in files
            )
            rows.append([
                f'<a href="/projects/{html.escape(slug)}">{html.escape(slug)}</a>',
                links,
            ])

    if not rows:
        return '<p class="muted">No config files found.</p>'

    return _table(["Project", "Config Files"], rows)


# ── Code Intelligence ─────────────────────────────────────────────────────────

