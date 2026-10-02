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
from gui_helpers import CLI_REFERENCE
_base = _base
_table = _table
_search_bar = _search_bar
_file_link = _file_link
_msg = _msg
_status_badge = _status_badge
_run = _run
TEMPLEDB = TEMPLEDB

from urllib.parse import quote

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*$")
_TOC_RE = re.compile(r"^(table of contents|contents|toc)$", re.IGNORECASE)


def _anchor(heading: str) -> str:
    """GitHub-style anchor slug for a heading."""
    s = heading.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    return re.sub(r"[-\s]+", "-", s).strip("-")


def _doc_category(file_path: str) -> str:
    """Group docs by where they actually live.

    The old readme_files.category was inferred by regex over the content
    ('setup', 'api', 'deployment', ...), which meant two docs in the same
    directory could land in different buckets for no visible reason. The
    directory is both cheaper and something you can act on.
    """
    parts = file_path.split("/")
    if len(parts) == 1:
        return "root"
    if parts[0] == "docs":
        return parts[1] if len(parts) > 2 else "docs"
    return parts[0]


def _parse_markdown(row) -> dict:
    """Extract title, description, headings and counts from markdown.

    Fenced code blocks are skipped: a shell block full of `# comment` lines
    would otherwise register as a pile of H1 headings.
    """
    text = row["content_text"] or ""
    lines = text.splitlines()

    title = None
    description = None
    sections = []
    has_toc = False
    in_fence = False

    for i, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue

        m = _HEADING_RE.match(line)
        if m:
            level = len(m.group(1))
            heading = m.group(2).strip()
            if _TOC_RE.match(heading):
                has_toc = True
            if level == 1 and title is None:
                title = heading
                continue
            sections.append({
                "level": level,
                "heading": heading,
                "anchor": _anchor(heading),
                "line_number": i,
            })
            continue

        # First real prose line after the title becomes the description.
        if description is None and title is not None and stripped \
                and not stripped.startswith(("|", ">", "-", "*", "<!--", "[")):
            description = stripped[:200]

    return {
        "slug": row["slug"],
        "file_path": row["file_path"],
        "title": title or row["file_path"].rsplit("/", 1)[-1],
        "description": description or "",
        "category": _doc_category(row["file_path"]),
        "sections": sections,
        "has_toc": has_toc,
        "word_count": len(text.split()),
        "updated_at": row["updated_at"],
    }


@router.get("/docs", response_class=HTMLResponse)
def docs_list(project: str = Query(""), category: str = Query("")):
    # Markdown is read straight from the committed files. This page used to
    # render the readme_files / readme_topics / readme_sections tables, but
    # that index had no refresh path: its only writer was
    # scripts/dogfood_readme_system.py, a one-off script with no CLI command
    # wired to it. It ran once and stopped, so every row still read
    # last_scanned_at = 2026-04-05 and 15 of templedb's 132 docs were simply
    # invisible here -- including the docs describing the system you were
    # looking at.
    #
    # Parsing on request costs ~315 files / 3.3 MB across 15 projects, which
    # is cheap next to an index that silently lies. Nothing to go stale, and
    # nothing to re-run after a commit.
    rows = query_all("""
        SELECT p.slug, pf.file_path, cb.content_text, fc.updated_at
        FROM project_files pf
        JOIN projects p       ON p.id = pf.project_id
        JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
        JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
        WHERE pf.status = 'active'
          AND lower(pf.file_path) LIKE '%.md'
          -- Skip dotted directories: 21 of the 315 markdown files live in
          -- .claude/ or a .release-backup-<date>/ snapshot, and listing a
          -- backup copy beside the real doc is worse than not listing it.
          AND pf.file_path NOT LIKE '.%'
          AND pf.file_path NOT LIKE '%/.%'
        ORDER BY p.slug, pf.file_path
    """)
    all_docs = [_parse_markdown(r) for r in rows]

    all_projects_rows = query_all("SELECT slug FROM projects ORDER BY slug")
    all_projects = sorted({r["slug"] for r in all_projects_rows})
    all_categories = sorted({d["category"] for d in all_docs})

    # Filter
    filtered = all_docs
    if project:
        filtered = [d for d in filtered if d["slug"] == project]
    if category:
        filtered = [d for d in filtered if d["category"] == category]

    by_category: dict = defaultdict(list)
    for d in filtered:
        by_category[d["category"]].append(d)

    cat_opts = '<option value="">All categories</option>' + "".join(
        f'<option value="{html.escape(c)}" {"selected" if c == category else ""}>{html.escape(c)}</option>'
        for c in all_categories
    )

    sections_html = ""
    for cat in sorted(by_category.keys()):
        docs = by_category[cat]
        rows_html = []
        for d in docs:
            toc_badge = (
                '<span class="badge green" style="font-size:0.68rem">TOC</span>'
                if d["has_toc"] else ""
            )
            title_cell = (
                f'<strong>{_file_link(d["slug"], d["file_path"], d["title"])}</strong>'
            )
            desc_cell = (
                f'<span class="muted" style="font-size:0.8rem">{html.escape(d["description"])}</span>'
                if d["description"] else ""
            )

            sec_detail = ""
            if d["sections"]:
                sec_trs = []
                for s in d["sections"]:
                    indent = "&nbsp;" * (s["level"] - 1) * 3
                    sec_trs.append([
                        f'<span class="muted" style="font-size:0.75rem">H{s["level"]}</span>',
                        f'<a href="/projects/{html.escape(d["slug"])}/file'
                        f'?path={quote(d["file_path"], safe="")}#{html.escape(s["anchor"])}" '
                        f'style="font-size:0.78rem">{indent}{html.escape(s["heading"])}</a>',
                        f'<span class="muted">{s["line_number"]}</span>',
                    ])
                sec_inner = _table(["Lvl", "Heading", "Line"], sec_trs)
                n = len(d["sections"])
                sec_detail = (
                    f'<details style="margin-top:0.15rem">'
                    f'<summary style="cursor:pointer;color:#606080;font-size:0.75rem">'
                    f'{n} section{"s" if n != 1 else ""}</summary>'
                    f'<div style="margin-top:0.3rem">{sec_inner}</div></details>'
                )

            rows_html.append([
                title_cell + (f'<br>{desc_cell}' if desc_cell else ""),
                html.escape(d["slug"]),
                f'{d["word_count"]:,}',
                sec_detail or '<span class="muted">0</span>',
                toc_badge,
                html.escape((d["updated_at"] or "")[:10]),
            ])

        section_table = _table(
            ["Title", "Project", "Words", "Sections", "Flags", "Updated"],
            rows_html,
        )
        sections_html += (
            f'<div class="fsec" style="margin-top:1.5rem">'
            f'<h3>{html.escape(cat)} '
            f'<span class="muted" style="font-weight:normal;font-size:0.85rem">({len(docs)})</span></h3>'
            f'{section_table}</div>'
        )

    total = len(filtered)
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

