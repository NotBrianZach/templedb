#!/usr/bin/env python3
"""Agent report management.

Reports are self-contained HTML overview documents living at
`reports/YYYY-MM-DD-kebab-title.html` inside the templedb project. Each is a
snapshot of an analysis, design discussion, or session recap.

CLI:
  templedb reports list           -- newest-first, date + title
  templedb reports view [query]   -- extract all + open in browser
  templedb reports new <title>    -- scaffold a new report from template
  templedb reports reindex        -- rebuild index.html from files in reports/
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)

REPORT_PROJECT = "templedb"
REPORT_DIR = "reports"
EXTRACT_DIR = Path(tempfile.gettempdir()) / "templedb-reports"

# Kebab-case slug allowed characters in filenames
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
_LEDE_RE = re.compile(
    r'<p\s+class="lede"[^>]*>(.*?)</p>', re.IGNORECASE | re.DOTALL
)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _slugify(title: str) -> str:
    return _SLUG_RE.sub("-", title.lower()).strip("-")[:60]


def _strip_tags(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_STRIP_RE.sub("", html)).strip()


def _list_report_files():
    """Return sorted list of (file_path, date_str, title, lede) tuples.

    Newest first. Reads from templedb project via db_utils rather than the
    checkout so this works whether or not the project is materialized.
    """
    from db_utils import get_simple_connection
    conn = get_simple_connection(row_factory=True)
    try:
        # Match reports/YYYY-*.html (dated reports only); exclude index.html
        # and any other non-dated files that live in the reports dir.
        rows = conn.execute("""
            SELECT pf.file_path, cb.content_text
              FROM project_files pf
              JOIN projects p ON p.id = pf.project_id
              JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
              JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
             WHERE p.slug = ? AND pf.status = 'active'
               AND pf.file_path GLOB ?
             ORDER BY pf.file_path DESC
        """, (REPORT_PROJECT, f"{REPORT_DIR}/[0-9][0-9][0-9][0-9]-*.html")).fetchall()
    finally:
        conn.close()

    out = []
    for r in rows:
        path = r["file_path"]
        html = r["content_text"] or ""
        # File date/time from filename: YYYY-MM-DD[-HHMM]-slug.html.
        # HHMM was added late so we accept both forms and render time
        # only when present.
        m = re.search(r"/(\d{4}-\d{2}-\d{2})(?:-(\d{4}))?-", path)
        if m:
            date_str = m.group(1)
            if m.group(2):
                date_str = f"{date_str} {m.group(2)[:2]}:{m.group(2)[2:]}"
        else:
            date_str = "----------"
        # Prefer <title>, fall back to first <h1>, then filename stem
        title = "(untitled)"
        tm = _TITLE_RE.search(html)
        if tm:
            title = _strip_tags(tm.group(1))
            # Drop " — TempleDB" or similar suffix
            title = re.sub(r"\s*[—-]\s*TempleDB\s*$", "", title, flags=re.I)
        else:
            hm = _H1_RE.search(html)
            if hm:
                title = _strip_tags(hm.group(1))
        lede_m = _LEDE_RE.search(html)
        lede = _strip_tags(lede_m.group(1)) if lede_m else ""
        out.append((path, date_str, title, lede))
    return out


def _extract_all_to(dest: Path):
    """Extract index.html + all reports to dest for browser viewing.

    Recreates the same layout so cross-links work.
    """
    from db_utils import get_simple_connection
    conn = get_simple_connection(row_factory=True)
    try:
        rows = conn.execute("""
            SELECT pf.file_path, cb.content_text, cb.content_blob
              FROM project_files pf
              JOIN projects p ON p.id = pf.project_id
              JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
              JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
             WHERE p.slug = ? AND pf.status = 'active'
               AND (pf.file_path = 'index.html' OR pf.file_path LIKE ?)
        """, (REPORT_PROJECT, f"{REPORT_DIR}/%.html")).fetchall()
    finally:
        conn.close()

    dest.mkdir(parents=True, exist_ok=True)
    for r in rows:
        p = dest / r["file_path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        if r["content_text"] is not None:
            p.write_text(r["content_text"])
        elif r["content_blob"] is not None:
            p.write_bytes(r["content_blob"])
    return len(rows)


def _open_in_browser(path: Path):
    opener = os.environ.get("BROWSER") or "xdg-open"
    try:
        subprocess.Popen([opener, str(path)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False


_REPORT_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
  :root {{
    --bg: #0f0f1a;
    --panel: #13131f;
    --border: #1e1e3a;
    --text: #d0d0e8;
    --muted: #8080a0;
    --accent: #e94560;
    --link: #7ec7ff;
    --code-bg: #0a0a14;
  }}
  html, body {{ background: var(--bg); color: var(--text); }}
  body {{
    font-family: "IBM Plex Sans", "Inter", -apple-system, system-ui, sans-serif;
    max-width: 820px; margin: 3rem auto 6rem; padding: 0 1.5rem;
    line-height: 1.65; font-size: 16.5px;
  }}
  h1 {{ color: var(--accent); font-size: 1.6rem; margin: 0 0 0.4rem; }}
  h2 {{ color: var(--accent); font-size: 1.05rem; margin: 2.6rem 0 0.7rem;
       text-transform: uppercase; letter-spacing: 0.06em;
       border-top: 1px solid var(--border); padding-top: 1.3rem; }}
  h3 {{ color: #b0b0d0; font-size: 1rem; margin: 1.6rem 0 0.5rem; }}
  .lede {{ color: var(--muted); margin-bottom: 2rem; font-size: 0.95rem; }}
  p {{ margin: 0 0 1rem; }}
  code {{ background: var(--code-bg); color: #b0e0b0;
         padding: 1px 5px; border-radius: 3px; font-size: 0.88em;
         font-family: "JetBrains Mono", ui-monospace, monospace; }}
  pre {{ background: var(--code-bg); border: 1px solid var(--border);
        padding: 0.85rem 1rem; border-radius: 5px; overflow-x: auto;
        font-family: "JetBrains Mono", ui-monospace, monospace;
        font-size: 0.83em; line-height: 1.55; margin: 0.9rem 0; }}
  a {{ color: var(--link); text-decoration: none; border-bottom: 1px dotted var(--link); }}
  .callout {{ background: var(--panel); border-left: 3px solid var(--accent);
             padding: 0.75rem 1.1rem; margin: 1.2rem 0; border-radius: 0 4px 4px 0; }}
</style>
</head>
<body>

<h1>{title}</h1>
<p class="lede">
  {lede_placeholder}
</p>

<h2>Section</h2>
<p>Body.</p>

</body>
</html>
"""


def _regenerate_index(reports_data) -> str:
    """Build index.html content from a list of (path, date, title, lede)."""
    entries = []
    for path, dt, title, lede in reports_data:
        # index.html lives in reports/, so hrefs are relative to that dir
        rel = path.removeprefix(f"{REPORT_DIR}/")
        entries.append(
            f'<a class="report" href="{rel}">\n'
            f'  <div class="row">\n'
            f'    <span class="date">{dt}</span>\n'
            f'    <span class="title">{title}</span>\n'
            f'  </div>\n'
            f'  <div class="summary">\n'
            f'    {lede or "(no lede)"}\n'
            f'  </div>\n'
            f'</a>\n'
        )
    entries_html = "\n".join(entries) if entries else '<p class="empty">(no reports yet)</p>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Agent Reports — TempleDB</title>
<style>
  :root {{
    --bg: #0f0f1a; --panel: #13131f; --border: #1e1e3a; --text: #d0d0e8;
    --muted: #8080a0; --accent: #e94560; --link: #7ec7ff; --code-bg: #0a0a14;
  }}
  html, body {{ background: var(--bg); color: var(--text); }}
  body {{ font-family: "IBM Plex Sans", "Inter", system-ui, sans-serif;
         max-width: 780px; margin: 3rem auto 6rem; padding: 0 1.5rem;
         line-height: 1.65; font-size: 16.5px; }}
  h1 {{ color: var(--accent); font-size: 1.6rem; margin: 0 0 0.4rem; }}
  h2 {{ color: var(--accent); font-size: 1rem; margin: 2.6rem 0 1rem;
       text-transform: uppercase; letter-spacing: 0.08em;
       border-top: 1px solid var(--border); padding-top: 1.2rem; }}
  .lede {{ color: var(--muted); margin-bottom: 2rem; font-size: 0.95rem; }}
  code {{ background: var(--code-bg); color: #b0e0b0;
         padding: 1px 5px; border-radius: 3px; font-size: 0.88em;
         font-family: "JetBrains Mono", ui-monospace, monospace; }}
  .report {{ display: block; padding: 0.9rem 1.1rem; margin-bottom: 0.7rem;
            background: var(--panel); border: 1px solid var(--border);
            border-radius: 5px; text-decoration: none;
            transition: border-color 0.15s; }}
  .report:hover {{ border-color: var(--accent); }}
  .report .row {{ display: flex; align-items: baseline; gap: 0.8rem; margin-bottom: 0.3rem; }}
  .report .date {{ font-family: "JetBrains Mono", ui-monospace, monospace;
                  color: var(--muted); font-size: 0.82rem; min-width: 5.5rem; }}
  .report .title {{ color: var(--link); font-weight: 600; font-size: 1.02rem; }}
  .report .summary {{ color: var(--text); font-size: 0.9rem; line-height: 1.5; padding-left: 6.3rem; }}
  .empty {{ color: var(--muted); font-style: italic; }}
</style>
</head>
<body>

<h1>Agent Reports</h1>
<p class="lede">
  Readable HTML overviews produced by agents while working on TempleDB. Each
  entry is a self-contained snapshot; no report is edited in place.
  Auto-generated by <code>templedb reports reindex</code>.
</p>

<h2>Reports</h2>

{entries_html}

<h2>Adding a report</h2>
<p>
  <code>templedb reports new "Your title here"</code> scaffolds a new file at
  <code>reports/YYYY-MM-DD-your-title-here.html</code> with the standard
  template. Fill in the body, then <code>templedb reports reindex</code>
  regenerates this page from filenames and <code>&lt;p class="lede"&gt;</code>
  contents.
</p>

</body>
</html>
"""


class ReportsCommands(Command):
    """Agent HTML report management."""

    def list(self, args):
        reports = _list_report_files()
        if args.json:
            print(json.dumps([{
                "path": p, "date": d, "title": t, "lede": l
            } for p, d, t, l in reports], indent=2))
            return 0
        if not reports:
            print("No reports yet. Create one with:")
            print("  templedb reports new <title>")
            return 0
        print(f"\n{len(reports)} report(s), newest first:\n")
        for path, dt, title, _lede in reports:
            print(f"  {dt}  {title}")
            print(f"             {path}\n")
        return 0

    def view(self, args):
        reports = _list_report_files()
        if not reports:
            print("No reports to view. Create one with: templedb reports new <title>")
            return 1

        # Refresh extraction dir every call
        if EXTRACT_DIR.exists():
            shutil.rmtree(EXTRACT_DIR)
        n = _extract_all_to(EXTRACT_DIR)

        target = EXTRACT_DIR / REPORT_DIR / "index.html"
        if args.query:
            q = args.query.lower()
            matches = [p for p, _d, _t, _l in reports if q in p.lower()]
            if not matches:
                # Try matching by title
                matches = [p for p, _d, t, _l in reports if q in t.lower()]
            if not matches:
                print(f"No report matches '{args.query}'.")
                print(f"Available:")
                for p, dt, t, _ in reports:
                    print(f"  {dt}  {t}")
                return 1
            if len(matches) > 1:
                print(f"Multiple matches for '{args.query}':")
                for p in matches:
                    print(f"  {p}")
                print("Refine the query.")
                return 1
            target = EXTRACT_DIR / matches[0]

        if not target.exists():
            print(f"Not extracted: {target}")
            return 1

        print(f"Opening {target}")
        if not _open_in_browser(target):
            print(f"No browser opener available. Path:")
            print(f"  file://{target}")
        return 0

    def new(self, args):
        title = args.title.strip()
        if not title:
            print("Title required.")
            return 1
        slug = _slugify(title)
        # HHMM in the filename so multiple reports per day sort and
        # display distinctly in the CLI list and GUI index.
        now = datetime.now()
        stamp = now.strftime("%Y-%m-%d-%H%M")
        filename = f"{stamp}-{slug}.html"
        rel_path = f"{REPORT_DIR}/{filename}"

        # Refuse to overwrite an existing report
        existing = {p for p, *_ in _list_report_files()}
        if rel_path in existing:
            print(f"A report already exists at {rel_path}. Refusing to overwrite.")
            print("Pick a different title or edit the existing report.")
            return 1

        content = _REPORT_TEMPLATE.format(
            title=title,
            lede_placeholder=(
                "One-paragraph summary of what this report covers and why."
            ),
        )

        # Write to a tempfile then set via file set (avoids FUSE)
        tmp = Path(tempfile.mkdtemp()) / filename
        tmp.write_text(content)
        r = subprocess.run(
            ["templedb", "file", "set", REPORT_PROJECT, rel_path, "--verify"],
            stdin=open(tmp), capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"file set failed: {r.stderr}")
            return r.returncode

        print(f"Created {rel_path}")
        print(f"Edit with:  templedb file edit {REPORT_PROJECT} {rel_path}")
        print(f"After edit: templedb reports reindex")
        return 0

    def regenerate_index(self, args):
        reports = _list_report_files()
        content = _regenerate_index(reports)
        tmp = Path(tempfile.mkdtemp()) / "index.html"
        tmp.write_text(content)
        r = subprocess.run(
            ["templedb", "file", "set", REPORT_PROJECT,
             f"{REPORT_DIR}/index.html", "--verify"],
            stdin=open(tmp), capture_output=True, text=True,
        )
        if r.returncode != 0:
            print(f"file set failed: {r.stderr}")
            return r.returncode
        print(f"Regenerated index.html from {len(reports)} report(s).")
        return 0


def register(cli):
    """Register templedb reports command tree."""
    cmd = ReportsCommands()
    reports_parser = cli.register_command(
        'reports', None, help_text='Agent HTML reports (in templedb/reports/)'
    )
    sub = reports_parser.add_subparsers(dest='reports_subcommand', required=True)

    ls = sub.add_parser('list', help='List reports newest-first')
    ls.add_argument('--json', action='store_true')
    cli.commands['reports.list'] = cmd.list

    v = sub.add_parser('view', help='Extract reports and open in browser')
    v.add_argument('query', nargs='?',
                   help='Substring match (omit to open the index)')
    cli.commands['reports.view'] = cmd.view

    n = sub.add_parser('new', help='Scaffold a new report from the template')
    n.add_argument('title', help='Report title (turned into a kebab-case slug)')
    cli.commands['reports.new'] = cmd.new

    ri = sub.add_parser('reindex', aliases=['regenerate-index'],
                        help='Rebuild reports/index.html from filenames + ledes')
    cli.commands['reports.reindex'] = cmd.regenerate_index
    cli.commands['reports.regenerate-index'] = cmd.regenerate_index
