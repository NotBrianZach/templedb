"""TempleDB GUI — Reports pages.

Routes:
  GET /reports                     -- listing across every project
  GET /reports?project=<slug>      -- listing scoped to one project
  GET /reports/{filename}          -- one report, project inferred
  GET /reports/{slug}/{filename}   -- one report, project explicit

Reports are HTML files under a project's `reports/` directory, one file
per report. Listing is derived from the DB, not the filesystem.

Previously both routes hardcoded REPORT_PROJECT = "templedb", so a
report in any other project was unreachable and invisible. Every report
that exists today is still a templedb one (46 of them); this makes the
other projects addressable rather than migrating anything.

Bare `/reports/{filename}` is kept working because all existing links
use it. Filenames are date-prefixed and unique across projects today; if
two ever collide the explicit two-segment form disambiguates, and the
bare form says so instead of silently picking one.
"""
import html
import re
import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import query_all

from gui_helpers import _base

router = APIRouter()

REPORT_DIR = "reports"

# Dated convention: YYYY-MM-DD[-HHMM]-slug.html. Excludes reports/index.html.
_REPORT_GLOB = f"{REPORT_DIR}/[0-9][0-9][0-9][0-9]-*.html"

_TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
_LEDE_RE = re.compile(
    r'<p\s+class="lede"[^>]*>(.*?)</p>', re.IGNORECASE | re.DOTALL
)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", _TAG_STRIP_RE.sub("", s)).strip()


def _parse_report(slug, path, html_text):
    """Derive (slug, filename, date_str, title, lede) from one report."""
    filename = path.removeprefix(f"{REPORT_DIR}/")
    # Filename format: YYYY-MM-DD[-HHMM]-slug.html. HHMM is optional for
    # backward compat with reports created before the convention was
    # tightened; when present, display as "YYYY-MM-DD HH:MM" so multiple
    # reports the same day are visually distinguishable.
    m = re.search(r"^(\d{4}-\d{2}-\d{2})(?:-(\d{4}))?-", filename)
    if m:
        date_str = m.group(1)
        if m.group(2):
            date_str = f"{date_str} {m.group(2)[:2]}:{m.group(2)[2:]}"
    else:
        date_str = "----------"

    title = "(untitled)"
    tm = _TITLE_RE.search(html_text)
    if tm:
        title = _strip_tags(tm.group(1))
        title = re.sub(r"\s*[—-]\s*TempleDB\s*$", "", title, flags=re.I)
    else:
        hm = _H1_RE.search(html_text)
        if hm:
            title = _strip_tags(hm.group(1))

    lede_m = _LEDE_RE.search(html_text)
    lede = _strip_tags(lede_m.group(1)) if lede_m else ""
    return (slug, filename, date_str, title, lede)


def _list_reports(project=None):
    """Reports newest-first, optionally scoped to one project slug."""
    sql = """
        SELECT p.slug, pf.file_path, cb.content_text
          FROM project_files pf
          JOIN projects p ON p.id = pf.project_id
          JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
          JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
         WHERE pf.status = 'active'
           AND pf.file_path GLOB ?
    """
    params = [_REPORT_GLOB]
    if project:
        sql += " AND p.slug = ?"
        params.append(project)
    # Sort by filename so the date prefix orders them, then by slug for a
    # stable tie-break when two projects file a report the same minute.
    sql += " ORDER BY pf.file_path DESC, p.slug ASC"
    rows = query_all(sql, tuple(params))
    return [
        _parse_report(r["slug"], r["file_path"], r["content_text"] or "")
        for r in rows
    ]


def _report_counts():
    """[(slug, n)] for projects that have reports, most first."""
    rows = query_all(
        """
        SELECT p.slug, COUNT(*) AS n
          FROM project_files pf
          JOIN projects p ON p.id = pf.project_id
         WHERE pf.status = 'active' AND pf.file_path GLOB ?
         GROUP BY p.slug
         ORDER BY n DESC, p.slug ASC
        """,
        (_REPORT_GLOB,),
    )
    return [(r["slug"], r["n"]) for r in rows]


def _resolve(ref):
    """Map a URL ref to (slug, filename, candidates).

    `ref` is either "filename.html" or "slug/filename.html". Returns
    candidates so an ambiguous bare filename can be reported rather than
    resolved arbitrarily.
    """
    ref = ref.strip("/")
    slug, sep, filename = ref.partition("/")
    if sep and filename:
        return slug, filename, None

    filename = ref
    rows = query_all(
        """
        SELECT p.slug
          FROM project_files pf
          JOIN projects p ON p.id = pf.project_id
         WHERE pf.status = 'active' AND pf.file_path = ?
         ORDER BY p.slug ASC
        """,
        (f"{REPORT_DIR}/{filename}",),
    )
    slugs = [r["slug"] for r in rows]
    if len(slugs) == 1:
        return slugs[0], filename, None
    return None, filename, slugs


def _fetch(slug, filename):
    rows = query_all(
        """
        SELECT cb.content_text, cb.content_blob
          FROM project_files pf
          JOIN projects p ON p.id = pf.project_id
          JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
          JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
         WHERE p.slug = ? AND pf.file_path = ? AND pf.status = 'active'
        """,
        (slug, f"{REPORT_DIR}/{filename}"),
    )
    return rows[0] if rows else None


_STYLES = """
<style>
  .report-card {
    display: block; padding: 0.9rem 1.1rem; margin-bottom: 0.7rem;
    background: #13131f; border: 1px solid #1e1e3a; border-radius: 5px;
    text-decoration: none; color: #d0d0e8;
    transition: border-color 0.15s;
  }
  .report-card:hover { border-color: #e94560; }
  .report-row {
    display: flex; align-items: baseline; gap: 0.8rem; margin-bottom: 0.3rem;
  }
  .report-date {
    font-family: "JetBrains Mono", ui-monospace, monospace;
    color: #8080a0; font-size: 0.82rem; min-width: 5.5rem;
  }
  .report-title { color: #7ec7ff; font-weight: 600; font-size: 1.02rem; }
  .report-proj {
    font-family: "JetBrains Mono", ui-monospace, monospace;
    font-size: 0.72rem; color: #9a9ac0; background: #1b1b2e;
    border: 1px solid #262647; border-radius: 3px; padding: 0.05rem 0.4rem;
  }
  .report-summary {
    color: #d0d0e8; font-size: 0.9rem; line-height: 1.5;
    padding-left: 6.3rem;
  }
  .proj-filter { margin: 0 0 1.1rem; display: flex; flex-wrap: wrap; gap: 0.4rem; }
  .proj-chip {
    font-family: "JetBrains Mono", ui-monospace, monospace; font-size: 0.78rem;
    padding: 0.2rem 0.6rem; border-radius: 3px; text-decoration: none;
    background: #13131f; border: 1px solid #1e1e3a; color: #9a9ac0;
  }
  .proj-chip:hover { border-color: #e94560; color: #d0d0e8; }
  .proj-chip.active {
    background: #1b1b2e; border-color: #7ec7ff; color: #7ec7ff; font-weight: 600;
  }
</style>
"""


def _filter_bar(counts, active):
    """Project chips. Omitted entirely when only one project has reports."""
    if len(counts) < 2:
        return ""
    total = sum(n for _s, n in counts)
    chips = [
        f'<a class="proj-chip{"" if active else " active"}" href="/reports">'
        f'all ({total})</a>'
    ]
    for slug, n in counts:
        cls = " active" if active == slug else ""
        chips.append(
            f'<a class="proj-chip{cls}" href="/reports?project={html.escape(slug)}">'
            f'{html.escape(slug)} ({n})</a>'
        )
    return f'<div class="proj-filter">{"".join(chips)}</div>'


@router.get("/reports", response_class=HTMLResponse)
def reports_list(project: str = None):
    counts = _report_counts()
    known = {slug for slug, _n in counts}

    if project and project not in known:
        body = (
            _STYLES
            + "<h2>Reports</h2>"
            + _filter_bar(counts, None)
            + f'<p class="muted">No reports for project '
              f'<code>{html.escape(project)}</code>.</p>'
        )
        return _base("Reports", body, active="reports")

    reports = _list_reports(project)
    if not reports:
        body = (
            _STYLES
            + "<h2>Reports</h2>"
            + '<p class="muted">No reports yet.</p>'
            + '<p>Create one with <code>templedb reports new "your title"</code>, '
              'then <code>templedb reports reindex</code>.</p>'
        )
        return _base("Reports", body, active="reports")

    # Show the project badge only when the list spans more than one, so a
    # single-project view is not cluttered by a constant label.
    show_badge = project is None and len(counts) > 1

    items = []
    for slug, filename, date_str, title, lede in reports:
        summary = (
            html.escape(lede) if lede
            else '<span class="muted">(no lede)</span>'
        )
        badge = (
            f'<span class="report-proj">{html.escape(slug)}</span>'
            if show_badge else ""
        )
        href = f"/reports/{html.escape(slug)}/{html.escape(filename)}"
        items.append(
            f'<a class="report-card" href="{href}">'
            f'  <div class="report-row">'
            f'    <span class="report-date">{html.escape(date_str)}</span>'
            f'    <span class="report-title">{html.escape(title)}</span>'
            f'    {badge}'
            f'  </div>'
            f'  <div class="report-summary">{summary}</div>'
            f'</a>'
        )

    scope = f" in <code>{html.escape(project)}</code>" if project else ""
    body = (
        _STYLES
        + "<h2>Reports</h2>"
        + _filter_bar(counts, project)
        + f'<p class="muted" style="margin-bottom:1.2rem">'
          f'{len(reports)} report(s){scope}, newest first. Each opens in its '
          f'own styled page. Add new reports via '
          f'<code>templedb reports new</code> then <code>reindex</code>.</p>'
        + "".join(items)
    )
    return _base("Reports", body, active="reports")


def _error_page(heading, detail):
    return HTMLResponse(
        status_code=404,
        content=(
            "<html><body style='font-family:monospace;background:#0f0f1a;"
            "color:#d0d0e8;padding:2rem'>"
            f"<h1 style='color:#e94560'>{html.escape(heading)}</h1>"
            f"{detail}"
            "<p><a style='color:#7ec7ff' href='/reports'>&larr; "
            "Back to reports</a></p>"
            "</body></html>"
        ),
    )


@router.get("/reports/{ref:path}", response_class=HTMLResponse)
def reports_view(ref: str):
    # Serve the raw report HTML — it's self-contained with its own styling,
    # and wrapping in the GUI chrome would fight its layout.
    #
    # One route handles both "filename" and "slug/filename" rather than two,
    # because {ref:path} is greedy and would shadow a separate two-segment
    # route depending on declaration order.
    if ".." in ref or ref.startswith("/"):
        return HTMLResponse(status_code=400, content="Bad request")

    slug, filename, candidates = _resolve(ref)

    if slug is None:
        if candidates:
            links = "".join(
                f"<li><a style='color:#7ec7ff' "
                f"href='/reports/{html.escape(s)}/{html.escape(filename)}'>"
                f"{html.escape(s)}</a></li>"
                for s in candidates
            )
            return _error_page(
                "Ambiguous report name",
                f"<p>{html.escape(filename)} exists in more than one "
                f"project:</p><ul>{links}</ul>",
            )
        return _error_page(
            "Report not found",
            f"<p>{html.escape(filename)}</p>",
        )

    row = _fetch(slug, filename)
    if not row:
        return _error_page(
            "Report not found",
            f"<p>{html.escape(slug)}/{REPORT_DIR}/{html.escape(filename)}</p>",
        )

    content = row["content_text"]
    if content is None and row["content_blob"] is not None:
        try:
            content = row["content_blob"].decode("utf-8")
        except Exception:
            content = "<pre>[binary content]</pre>"

    # Floating "back" link so users can return to the listing without the
    # browser back button. Carries the project through, so returning from a
    # report lands on that project's filtered list.
    back_link = (
        '<div style="position:fixed;top:0.6rem;left:0.6rem;z-index:100;'
        'background:#13131f;border:1px solid #1e1e3a;border-radius:4px;'
        'padding:0.3rem 0.6rem;font-family:monospace;font-size:0.8rem">'
        f'<a href="/reports?project={html.escape(slug)}" '
        'style="color:#7ec7ff;text-decoration:none">'
        f'&larr; {html.escape(slug)} reports</a></div>'
    )
    if "<body" in content:
        content = re.sub(
            r"(<body[^>]*>)", r"\1" + back_link, content, count=1
        )
    return HTMLResponse(content=content)
