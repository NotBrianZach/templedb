#!/usr/bin/env python3
"""Agent reports — stored as rows in `reports`.

  templedb reports list                -- newest-first, every project
  templedb reports list --project bza  -- one project
  templedb reports new "Title"         -- create a row and print how to edit it
  templedb reports view <query>        -- render one and open it in a browser

── They used to be files ────────────────────────────────────────────────

A report was an HTML file under a project's `reports/` directory, found by
the glob `reports/[0-9][0-9][0-9][0-9]-*.html`. The bytes were in SQLite
all along, but existence came from the glob, the date from the filename,
and the title and lede from regexes over the document's own markup.

Three consequences this module carried:

  - `REPORT_PROJECT = "templedb"` was hardcoded, so `reports new` could
    only ever create a templedb report. A bza report had to be written by
    hand with `file set`.
  - `reindex` existed because `index.html` was a generated artifact that
    could disagree with the directory it described.
  - A markdown report was invisible, because the glob ends in `.html`.

Migration 143 made reports rows. `format` is a column, `created_at` is a
timestamp, `slug` is a stable per-project id, and the listing is a SELECT.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from db_utils import query_all, query_one, execute
from cli.core import Command

EXTRACT_DIR = Path(tempfile.gettempdir()) / "templedb-reports"

# The default project for `reports new`.
#
# A default rather than the old hardcoding: most reports are about
# templedb, and `--project` now means a report about anything else is a
# first-class thing to create rather than something to hand-write.
DEFAULT_PROJECT = "templedb"


def _slugify(title: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    # 60 chars, matching what the filename convention produced, so slugs
    # migrated from paths and slugs created here look the same.
    return s[:60].rstrip("-")


def _project_id(slug: str):
    row = query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
    return row["id"] if row else None


def _rows(project=None):
    sql = """
        SELECT r.id, p.slug AS project, r.slug, r.title, r.lede,
               r.format, r.created_at, r.legacy_path
          FROM reports r
          JOIN projects p ON p.id = r.project_id
    """
    params = []
    if project:
        sql += " WHERE p.slug = ?"
        params.append(project)
    sql += " ORDER BY r.created_at DESC, r.slug ASC"
    return query_all(sql, tuple(params))


# No `# {title}` heading, deliberately.
#
# The row carries the title and the markdown page chrome renders it as the
# <h1>. A heading here as well puts the title on the page twice -- which
# the first version did, as an <h1> from the chrome followed immediately by
# an <h2> from the body. The lede is also a column, so it is not repeated
# in the body either.
_MD_TEMPLATE = """{lede_placeholder}

## Background

## What I found

## What I would do
"""


class ReportsCommands(Command):
    """Agent report management, over rows."""

    def list(self, args):
        project = getattr(args, "project", None)
        reports = _rows(project)
        if args.json:
            print(json.dumps([dict(r) for r in reports], indent=2))
            return 0
        if not reports:
            scope = f" for {project}" if project else ""
            print(f"No reports{scope} yet. Create one with:")
            print('  templedb reports new "<title>"')
            return 0
        scope = f" in {project}" if project else ""
        print(f"\n{len(reports)} report(s){scope}, newest first:\n")
        for r in reports:
            stamp = (r["created_at"] or "")[:16]
            fmt = "" if r["format"] == "html" else f"  [{r['format']}]"
            print(f"  {stamp}  {r['title']}{fmt}")
            print(f"                    {r['project']}/{r['slug']}\n")
        return 0

    def view(self, args):
        """Render one report to a temp file and open it.

        A file on disk rather than a GUI URL, deliberately: the GUI may not
        be running, and `reports view` predates it. The temp file is a
        rendering of the row, not a copy of a tracked file -- there is no
        longer a tracked file to copy.
        """
        reports = _rows(getattr(args, "project", None))
        if not reports:
            print("No reports to view.")
            return 1

        q = (args.query or "").lower()
        if q:
            matches = [r for r in reports if q in r["slug"].lower()]
            if not matches:
                matches = [r for r in reports if q in r["title"].lower()]
            if not matches and q:
                matches = [
                    r for r in reports
                    if r["legacy_path"] and q in r["legacy_path"].lower()
                ]
            if not matches:
                print(f"No report matches '{args.query}'. Available:")
                for r in reports:
                    print(f"  {(r['created_at'] or '')[:10]}  {r['title']}")
                return 1
            if len(matches) > 1:
                print(f"Multiple matches for '{args.query}':")
                for r in matches:
                    print(f"  {r['project']}/{r['slug']}  {r['title']}")
                print("Refine the query.")
                return 1
            target_row = matches[0]
        else:
            target_row = reports[0]

        full = query_one(
            "SELECT body, format, title, lede FROM reports WHERE id = ?",
            (target_row["id"],),
        )
        if EXTRACT_DIR.exists():
            shutil.rmtree(EXTRACT_DIR)
        EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
        out = EXTRACT_DIR / f"{target_row['slug']}.html"

        if full["format"] == "html":
            out.write_text(full["body"])
        else:
            # Reuse the GUI's renderer rather than keeping a second one --
            # two markdown implementations would disagree eventually, and
            # the disagreement would be invisible until somebody compared
            # the browser against the terminal.
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from gui_pages.reports import _render_markdown, _MD_PAGE
            lede = (
                f'<p class="lede">{full["lede"]}</p>' if full["lede"] else ""
            )
            out.write_text(_MD_PAGE.format(
                title=full["title"], back="", lede=lede,
                body=_render_markdown(full["body"]),
            ))

        print(f"Opening {out}")
        if not _open_in_browser(out):
            print("No browser opener available. Path:")
            print(f"  file://{out}")
        return 0

    def new(self, args):
        title = args.title.strip()
        if not title:
            print("Title required.")
            return 1

        project = getattr(args, "project", None) or DEFAULT_PROJECT
        pid = _project_id(project)
        if pid is None:
            print(f"No such project: {project}")
            return 1

        slug = _slugify(title)
        if not slug:
            print("Title produced an empty slug. Use some letters or digits.")
            return 1

        # Per-project uniqueness is the table's, not this check's -- the
        # UNIQUE(project_id, slug) constraint is what actually prevents a
        # collision. This exists to say something useful first.
        existing = query_one(
            "SELECT slug FROM reports WHERE project_id = ? AND slug = ?",
            (pid, slug),
        )
        if existing:
            print(f"A report already exists at {project}/{slug}.")
            print("Pick a different title, or edit the existing one.")
            return 1

        fmt = "html" if getattr(args, "html", False) else "markdown"
        lede_placeholder = (
            "One-paragraph summary of what this report covers and why."
        )
        if fmt == "markdown":
            body = _MD_TEMPLATE.format(
                title=title, lede_placeholder=lede_placeholder
            )
        else:
            body = _HTML_TEMPLATE.format(
                title=title, lede_placeholder=lede_placeholder
            )

        execute(
            """
            INSERT INTO reports
                (project_id, slug, title, lede, body, format, created_at,
                 updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (pid, slug, title, lede_placeholder, body, fmt,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        print(f"Created {project}/{slug} ({fmt})")
        print(f"  GUI:  /reports/{project}/{slug}")
        print(f"  Edit: templedb reports edit {project}/{slug}")
        return 0

    def edit(self, args):
        """Open the body in $EDITOR and write it back to the row."""
        ref = args.ref
        project, _sep, slug = ref.partition("/")
        if not slug:
            project, slug = DEFAULT_PROJECT, ref
        row = query_one(
            """
            SELECT r.id, r.body, r.format, r.slug FROM reports r
              JOIN projects p ON p.id = r.project_id
             WHERE p.slug = ? AND r.slug = ?
            """,
            (project, slug),
        )
        if not row:
            print(f"No such report: {project}/{slug}")
            return 1
        suffix = ".md" if row["format"] == "markdown" else ".html"
        tmp = Path(tempfile.mkdtemp()) / f"{row['slug']}{suffix}"
        tmp.write_text(row["body"])
        before = tmp.read_text()
        editor = os.environ.get("EDITOR", "vi")
        subprocess.run([editor, str(tmp)])
        after = tmp.read_text()
        if after == before:
            print("Unchanged.")
            return 0
        # Re-derive the lede from the edited body, so the index summary
        # follows the document rather than going stale the first time
        # somebody rewrites their opening paragraph.
        lede = _derive_lede(after, row["format"])
        execute(
            """
            UPDATE reports
               SET body = ?, lede = COALESCE(?, lede),
                   updated_at = ?
             WHERE id = ?
            """,
            (after, lede, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             row["id"]),
        )
        print(f"Updated {project}/{slug} ({len(after)} chars)")
        return 0

    def regenerate_index(self, args):
        """Kept as a notice rather than removed.

        Removing it would give `argparse` an "invalid choice" error, which
        says nothing about why. The index was a generated file that could
        disagree with the directory; there is no directory now.
        """
        print("reindex is no longer needed.")
        print()
        print("index.html was a generated artifact derived from a directory")
        print("listing. Reports are rows now (migration 143), so the listing")
        print("at /reports is a SELECT and cannot be stale.")
        return 0


def _derive_lede(body: str, fmt: str):
    if fmt == "html":
        m = re.search(
            r'<p\s+class="lede"[^>]*>(.*?)</p>', body,
            re.IGNORECASE | re.DOTALL,
        )
        return re.sub(r"<[^>]+>", "", m.group(1)).strip() if m else None
    # Markdown: the first non-heading, non-blank paragraph.
    for block in re.split(r"\n\s*\n", body):
        b = block.strip()
        if b and not b.startswith("#"):
            return re.sub(r"\s+", " ", b)[:500]
    return None


def _open_in_browser(path: Path) -> bool:
    for opener in ("xdg-open", "wslview", "open"):
        if shutil.which(opener):
            subprocess.Popen(
                [opener, str(path)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return True
    return False


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{ --bg:#0f0f1a; --border:#1e1e3a; --text:#d0d0e8; --muted:#8080a0;
           --accent:#e94560; --link:#7ec7ff; --code:#0a0a14; }}
  html,body {{ background:var(--bg); color:var(--text); }}
  body {{ font-family:"IBM Plex Sans","Inter",system-ui,sans-serif;
          max-width:780px; margin:3rem auto 6rem; padding:0 1.5rem;
          line-height:1.65; font-size:16.5px; }}
  h1 {{ color:var(--accent); font-size:1.6rem; margin:0 0 0.4rem; }}
  h2 {{ color:var(--accent); font-size:1rem; margin:2.6rem 0 1rem;
        text-transform:uppercase; letter-spacing:0.08em;
        border-top:1px solid var(--border); padding-top:1.2rem; }}
  .lede {{ color:var(--muted); margin-bottom:2rem; font-size:0.95rem; }}
  code {{ background:var(--code); color:#b0e0b0; padding:1px 5px;
          border-radius:3px; font-size:0.88em;
          font-family:"JetBrains Mono",ui-monospace,monospace; }}
  pre {{ background:var(--code); border:1px solid var(--border);
         border-radius:5px; padding:0.9rem 1.1rem; overflow-x:auto;
         font-size:0.84em; }}
  a {{ color:var(--link); }}
</style>
</head>
<body>

<h1>{title}</h1>

<p class="lede">{lede_placeholder}</p>

<h2>Background</h2>

<h2>What I found</h2>

<h2>What I would do</h2>

</body>
</html>
"""


def register(cli):
    """Register the templedb reports command tree."""
    cmd = ReportsCommands()
    reports_parser = cli.register_command(
        'reports', None, help_text='Agent reports (rows in the reports table)'
    )
    sub = reports_parser.add_subparsers(
        dest='reports_subcommand', required=True
    )

    ls = sub.add_parser('list', help='List reports newest-first')
    ls.add_argument('--json', action='store_true')
    ls.add_argument('--project', help='Scope to one project slug')
    cli.commands['reports.list'] = cmd.list

    v = sub.add_parser('view', help='Render a report and open it in a browser')
    v.add_argument('query', nargs='?', help='Substring of slug, title or legacy path')
    v.add_argument('--project', help='Scope to one project slug')
    cli.commands['reports.view'] = cmd.view

    n = sub.add_parser('new', help='Create a report')
    n.add_argument('title')
    n.add_argument('--project', help=f'Project slug (default: {DEFAULT_PROJECT})')
    n.add_argument('--html', action='store_true',
                   help='Author as self-contained HTML instead of markdown')
    cli.commands['reports.new'] = cmd.new

    e = sub.add_parser('edit', help='Edit a report body in $EDITOR')
    e.add_argument('ref', help='project/slug, or slug for the default project')
    cli.commands['reports.edit'] = cmd.edit

    ri = sub.add_parser('reindex', aliases=['regenerate-index'],
                        help='(no longer needed; explains why)')
    cli.commands['reports.reindex'] = cmd.regenerate_index
    cli.commands['reports.regenerate-index'] = cmd.regenerate_index
