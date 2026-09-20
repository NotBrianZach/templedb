"""TempleDB GUI — Reports pages.

Two routes:
  GET /reports              -- GUI-chromed listing of all reports
  GET /reports/{filename}   -- raw HTML content of one report (self-contained)

Reports live in the templedb project itself under `reports/`, one file per
report. Listing is derived from the DB, not the filesystem.
"""
import html
import re
import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import query_all, query_one

from gui_helpers import _base

router = APIRouter()

REPORT_PROJECT = "templedb"
REPORT_DIR = "reports"

_TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
_LEDE_RE = re.compile(
    r'<p\s+class="lede"[^>]*>(.*?)</p>', re.IGNORECASE | re.DOTALL
)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", _TAG_STRIP_RE.sub("", s)).strip()


def _list_reports():
    """Return [(file_path, filename, date_str, title, lede)] newest-first."""
    rows = query_all(
        """
        SELECT pf.file_path, cb.content_text
          FROM project_files pf
          JOIN projects p ON p.id = pf.project_id
          JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
          JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
         WHERE p.slug = ? AND pf.status = 'active'
           AND pf.file_path GLOB ?
         ORDER BY pf.file_path DESC
        """,
        (REPORT_PROJECT, f"{REPORT_DIR}/[0-9][0-9][0-9][0-9]-*.html"),
    )
    out = []
    for r in rows:
        path = r["file_path"]
        html_text = r["content_text"] or ""
        filename = path.removeprefix(f"{REPORT_DIR}/")
        # Filename format: YYYY-MM-DD[-HHMM]-slug.html. HHMM is optional
        # for backward compat with reports created before the convention
        # was tightened; when present, display as "YYYY-MM-DD HH:MM" so
        # multiple reports the same day are visually distinguishable.
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
        out.append((path, filename, date_str, title, lede))
    return out


@router.get("/reports", response_class=HTMLResponse)
def reports_list():
    reports = _list_reports()
    if not reports:
        body = (
            '<h2>Reports</h2>'
            '<p class="muted">No reports yet.</p>'
            '<p>Create one with <code>templedb reports new "your title"</code>, '
            'then <code>templedb reports reindex</code>.</p>'
        )
        return _base("Reports", body, active="reports")

    items = []
    for _path, filename, date_str, title, lede in reports:
        items.append(
            f'<a class="report-card" href="/reports/{html.escape(filename)}">'
            f'  <div class="report-row">'
            f'    <span class="report-date">{html.escape(date_str)}</span>'
            f'    <span class="report-title">{html.escape(title)}</span>'
            f'  </div>'
            f'  <div class="report-summary">{html.escape(lede) if lede else "<span class=\'muted\'>(no lede)</span>"}</div>'
            f'</a>'
        )

    styles = """
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
      .report-summary {
        color: #d0d0e8; font-size: 0.9rem; line-height: 1.5;
        padding-left: 6.3rem;
      }
    </style>
    """

    body = (
        styles
        + f'<h2>Reports</h2>'
        + f'<p class="muted" style="margin-bottom:1.2rem">'
        + f'{len(reports)} report(s), newest first. Each opens in its own '
        + f'styled page. Add new reports via '
        + f'<code>templedb reports new</code> then <code>reindex</code>.</p>'
        + "".join(items)
    )
    return _base("Reports", body, active="reports")


@router.get("/reports/{filename:path}", response_class=HTMLResponse)
def reports_view(filename: str):
    # Serve the raw report HTML — it's self-contained with its own styling,
    # and wrapping in the GUI chrome would fight its layout.
    if ".." in filename or filename.startswith("/"):
        return HTMLResponse(status_code=400, content="Bad request")
    file_path = f"{REPORT_DIR}/{filename}"
    row = query_one(
        """
        SELECT cb.content_text, cb.content_blob, ft.type_name
          FROM project_files pf
          JOIN projects p ON p.id = pf.project_id
          JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
          JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
          LEFT JOIN file_types ft ON ft.id = pf.file_type_id
         WHERE p.slug = ? AND pf.file_path = ? AND pf.status = 'active'
        """,
        (REPORT_PROJECT, file_path),
    )
    if not row:
        return HTMLResponse(
            status_code=404,
            content=(
                f"<html><body style='font-family:monospace;background:#0f0f1a;color:#d0d0e8;padding:2rem'>"
                f"<h1 style='color:#e94560'>Report not found</h1>"
                f"<p>{html.escape(file_path)}</p>"
                f"<p><a style='color:#7ec7ff' href='/reports'>&larr; Back to reports</a></p>"
                f"</body></html>"
            ),
        )

    content = row["content_text"]
    if content is None and row["content_blob"] is not None:
        try:
            content = row["content_blob"].decode("utf-8")
        except Exception:
            content = "<pre>[binary content]</pre>"

    # Inject a small floating "back" link at the top-left so users can navigate
    # back to the GUI reports list without hitting browser back.
    back_link = (
        '<div style="position:fixed;top:0.6rem;left:0.6rem;z-index:100;'
        'background:#13131f;border:1px solid #1e1e3a;border-radius:4px;'
        'padding:0.3rem 0.6rem;font-family:monospace;font-size:0.8rem">'
        '<a href="/reports" style="color:#7ec7ff;text-decoration:none">'
        '&larr; reports</a></div>'
    )
    if "<body" in content:
        content = re.sub(
            r"(<body[^>]*>)", r"\1" + back_link, content, count=1
        )
    return HTMLResponse(content=content)
