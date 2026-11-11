"""TempleDB GUI — Reports pages.

Routes:
  GET /reports                     -- listing across every project
  GET /reports?project=<slug>      -- listing scoped to one project
  GET /reports/{project}/{slug}    -- one report
  GET /reports/{slug}              -- one report, project inferred
  GET /reports/{legacy-filename}   -- an old dated .html path, still resolved

── Reports are rows ─────────────────────────────────────────────────────

They were files under a project's `reports/` directory, discovered by the
glob `reports/[0-9][0-9][0-9][0-9]-*.html`. The bytes were always in
SQLite -- a report is a tracked project file -- but the MODEL was the
filesystem: existence came from the glob, the date from a regex over the
filename, and the title and lede from regexes over the document's own
markup.

Every oddity this page used to carry came from that. A markdown report
was invisible, because the glob ends in `.html`. The title fell back to
"(untitled)" when a document had no `<title>`, because presentation
markup was being read as metadata. Filenames could collide across
projects, so `_resolve` had to report ambiguity. And `reports reindex`
existed because a generated index could disagree with the directory.

Migration 143 made them rows: `format` is a column, so markdown renders;
`created_at` is a timestamp, so the filename carries nothing; and `slug`
is a stable id, unique per project, so there is nothing to disambiguate.

Old `/reports/2026-10-27-1952-thing.html` links still resolve, through
`reports.legacy_path`. Those URLs are in published commit messages and
inside other reports, so they have to keep working; they are a
forwarding address and not an identity.
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

_TAG_STRIP_RE = re.compile(r"<[^>]+>")


def _strip_tags(s: str) -> str:
    return _TAG_STRIP_RE.sub("", s or "").strip()


# ── Markdown, rendered here rather than by a dependency ──────────────────
#
# This page imports nothing but the stdlib and fastapi, and adding a
# markdown package would mean a nix rebuild to render a document the
# database already holds. The subset below is the subset reports actually
# use -- headings, paragraphs, fenced code, tables, blockquotes, lists and
# inline emphasis -- and anything outside it degrades to a paragraph
# rather than to an error.
#
# It exists because `format` is a column now. A markdown report used to be
# invisible; it would be a poor fix to make it visible and then unreadable.

_MD_INLINE = (
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
    (re.compile(r"\*\*([^*]+)\*\*"), r"<b>\1</b>"),
    (re.compile(r"(?<![*\w])\*([^*\n]+)\*"), r"<em>\1</em>"),
    (re.compile(r"\[([^\]]+)\]\(([^)]+)\)"), r'<a href="\2">\1</a>'),
)


def _md_inline(s: str) -> str:
    out = html.escape(s)
    for pattern, repl in _MD_INLINE:
        out = pattern.sub(repl, out)
    return out


def _render_markdown(src: str) -> str:
    lines = (src or "").split("\n")
    out, para, i = [], [], 0

    def flush():
        if para:
            out.append(f"<p>{_md_inline(' '.join(para).strip())}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            flush()
            i += 1
            code = []
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append(
                "<pre><code>" + html.escape("\n".join(code)) + "</code></pre>"
            )
            continue
        m = re.match(r"^(#{1,4}) +(.*)$", line)
        if m:
            flush()
            level = min(len(m.group(1)) + 1, 4)
            out.append(f"<h{level}>{_md_inline(m.group(2))}</h{level}>")
            i += 1
            continue
        if line.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                rows.append(lines[i])
                i += 1
            # The |---|---| separator carries no content.
            rows = [r for r in rows if not re.fullmatch(r"\|[\s|:-]+\|", r.strip())]
            if rows:
                def cells(r):
                    return [c.strip() for c in r.strip().strip("|").split("|")]
                trs = ["<tr>" + "".join(
                    f"<th>{_md_inline(c)}</th>" for c in cells(rows[0])
                ) + "</tr>"]
                for r in rows[1:]:
                    trs.append("<tr>" + "".join(
                        f"<td>{_md_inline(c)}</td>" for c in cells(r)
                    ) + "</tr>")
                out.append("<table>" + "".join(trs) + "</table>")
            continue
        if line.startswith("> "):
            flush()
            quote = []
            while i < len(lines) and (lines[i].startswith("> ") or lines[i] == ">"):
                quote.append(re.sub(r"^>\s?", "", lines[i]))
                i += 1
            out.append(f"<blockquote>{_md_inline(' '.join(quote).strip())}</blockquote>")
            continue
        if re.match(r"^([-*] |\d+\. )", line):
            flush()
            ordered = bool(re.match(r"^\d+\. ", line))
            items = []
            while i < len(lines):
                if re.match(r"^([-*] |\d+\. )", lines[i]):
                    items.append(re.sub(r"^([-*]|\d+\.) ", "", lines[i]))
                elif re.match(r"^\s+\S", lines[i]) and items:
                    items[-1] += " " + lines[i].strip()
                else:
                    break
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(
                f"<{tag}>"
                + "".join(f"<li>{_md_inline(x)}</li>" for x in items)
                + f"</{tag}>"
            )
            continue
        if not line.strip():
            flush()
            i += 1
            continue
        para.append(line)
        i += 1

    flush()
    return "\n".join(out)


# ── Reads. All of them hit `reports`; none of them touch a path ───────────

def _list_reports(project=None):
    """Reports newest-first, optionally scoped to one project slug."""
    sql = """
        SELECT p.slug AS project, r.slug, r.title, r.lede, r.created_at,
               r.format, r.supersedes_id,
               (SELECT COUNT(*) FROM reports s WHERE s.supersedes_id = r.id)
                   AS superseded_by_count
          FROM reports r
          JOIN projects p ON p.id = r.project_id
    """
    params = []
    if project:
        sql += " WHERE p.slug = ?"
        params.append(project)
    # created_at DESC, then slug for a stable tie-break when two reports
    # share a timestamp -- which the old filename sort got for free and a
    # timestamp with minute precision does not.
    sql += " ORDER BY r.created_at DESC, r.slug ASC"
    return query_all(sql, tuple(params))


def _report_counts():
    """[(slug, n)] for projects that have reports, most first."""
    rows = query_all(
        """
        SELECT p.slug, COUNT(*) AS n
          FROM reports r
          JOIN projects p ON p.id = r.project_id
         GROUP BY p.slug
         ORDER BY n DESC, p.slug ASC
        """
    )
    return [(r["slug"], r["n"]) for r in rows]


def _fetch(ref):
    """One report from a URL ref, or None.

    `ref` is `project/slug`, a bare `slug`, or a legacy dated filename.
    Tried in that order, which is also most-specific first.

    A bare slug can in principle match two projects. That was a real
    ambiguity under filenames and is a near-impossibility now -- `slug` is
    only unique per project, so the two-segment form is the addressable
    one and this is a convenience. When it is ambiguous, nothing is
    guessed: the caller is handed the candidates.
    """
    ref = ref.strip("/")
    project, sep, slug = ref.partition("/")

    if sep and slug:
        rows = query_all(
            """
            SELECT r.*, p.slug AS project FROM reports r
              JOIN projects p ON p.id = r.project_id
             WHERE p.slug = ? AND (r.slug = ? OR r.legacy_path = ?)
            """,
            # Legacy too, and this form matters MORE than the bare one: the
            # old index generated two-segment hrefs of the shape
            # /reports/<project>/<dated-filename>.html, so that is what most
            # in-the-wild links actually look like. Matching only the slug
            # here would have broken every link the previous GUI emitted.
            (project, slug, f"reports/{slug}"),
        )
        return (rows[0] if rows else None), []

    # Bare: a slug, or a legacy path. `legacy_path` is matched with the
    # directory prefix restored, since that is how the column was written.
    rows = query_all(
        """
        SELECT r.*, p.slug AS project FROM reports r
          JOIN projects p ON p.id = r.project_id
         WHERE r.slug = ? OR r.legacy_path = ?
         ORDER BY p.slug ASC
        """,
        (ref, f"reports/{ref}"),
    )
    if len(rows) == 1:
        return rows[0], []
    if not rows:
        return None, []
    return None, [r["project"] for r in rows]
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
    total = sum(n for _slug, n in counts)
    chips = [
        f'<a class="proj-chip{"" if active else " active"}" href="/reports">'
        f'all <span class="n">{total}</span></a>'
    ]
    for slug, n in counts:
        cls = " active" if slug == active else ""
        chips.append(
            f'<a class="proj-chip{cls}" href="/reports?project={html.escape(slug)}">'
            f'{html.escape(slug)} <span class="n">{n}</span></a>'
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
            + '<p>Create one with <code>templedb reports new "your title"</code>.</p>'
        )
        return _base("Reports", body, active="reports")

    show_badge = project is None and len(counts) > 1

    items = []
    for r in reports:
        summary = (
            html.escape(r["lede"]) if r["lede"]
            else '<span class="muted">(no lede)</span>'
        )
        badge = (
            f'<span class="report-proj">{html.escape(r["project"])}</span>'
            if show_badge else ""
        )
        # Minute precision only when there is one, so a date-only report
        # does not display a meaningless 00:00.
        stamp = r["created_at"] or ""
        shown = stamp[:16] if not stamp.endswith("00:00:00") else stamp[:10]
        # Markdown is now a first-class state, so it is labelled rather
        # than being the silent reason a report used to be missing.
        fmt = (
            '<span class="report-proj">md</span>'
            if r["format"] == "markdown" else ""
        )
        superseded = (
            '<span class="report-proj">superseded</span>'
            if r["superseded_by_count"] else ""
        )
        href = f'/reports/{html.escape(r["project"])}/{html.escape(r["slug"])}'
        items.append(
            f'<a class="report-card" href="{href}">'
            f'  <div class="report-row">'
            f'    <span class="report-date">{html.escape(shown)}</span>'
            f'    <span class="report-title">{html.escape(r["title"])}</span>'
            f'    {badge}{fmt}{superseded}'
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
          f'{len(reports)} report(s){scope}, newest first. Stored as rows in '
          f'<code>reports</code>; add one with '
          f'<code>templedb reports new</code>.</p>'
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


# Minimal page for a markdown body, which has no styling of its own.
#
# An HTML report ships its own <style> and is served untouched -- that is
# the "one browser tab, no missing dependencies" invariant and it is a
# property of the document. A markdown report has no such thing, so the
# chrome is supplied here.
_MD_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
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
  h3,h4 {{ color:#a0a0c0; font-size:0.95rem; margin:1.8rem 0 0.6rem; }}
  .lede {{ color:var(--muted); margin-bottom:2rem; font-size:0.95rem; }}
  code {{ background:var(--code); color:#b0e0b0; padding:1px 5px;
          border-radius:3px; font-size:0.88em;
          font-family:"JetBrains Mono",ui-monospace,monospace; }}
  pre {{ background:var(--code); border:1px solid var(--border);
         border-radius:5px; padding:0.9rem 1.1rem; overflow-x:auto;
         font-size:0.84em; line-height:1.5; }}
  pre code {{ background:none; padding:0; }}
  table {{ width:100%; border-collapse:collapse; margin:1rem 0 1.4rem; }}
  th {{ text-align:left; padding:0.45rem 0.6rem; color:var(--muted);
        font-size:0.78rem; text-transform:uppercase; letter-spacing:0.06em;
        border-bottom:1px solid var(--border); }}
  td {{ padding:0.42rem 0.6rem; border-bottom:1px solid #1a1a2e;
        font-size:0.9rem; vertical-align:top; }}
  blockquote {{ border-left:2px solid var(--border); margin:1.2rem 0;
                padding:0.2rem 0 0.2rem 1.1rem; color:var(--muted); }}
  a {{ color:var(--link); }}
  ul,ol {{ padding-left:1.3rem; }} li {{ margin-bottom:0.45rem; }}
</style></head><body>{back}<h1>{title}</h1>{lede}{body}</body></html>"""


@router.get("/reports/{ref:path}", response_class=HTMLResponse)
def reports_view(ref: str):
    # One route for every form rather than several, because {ref:path} is
    # greedy and would shadow a two-segment route depending on declaration
    # order.
    if ".." in ref or ref.startswith("/"):
        return HTMLResponse(status_code=400, content="Bad request")

    row, candidates = _fetch(ref)

    if row is None:
        if candidates:
            links = "".join(
                f"<li><a style='color:#7ec7ff' "
                f"href='/reports/{html.escape(s)}/{html.escape(ref)}'>"
                f"{html.escape(s)}</a></li>"
                for s in candidates
            )
            return _error_page(
                "Ambiguous report slug",
                f"<p><code>{html.escape(ref)}</code> exists in more than one "
                f"project:</p><ul>{links}</ul>",
            )
        return _error_page("Report not found", f"<p>{html.escape(ref)}</p>")

    # Floating back link, carrying the project so returning lands on that
    # project's filtered list.
    back = (
        '<div style="position:fixed;top:0.6rem;left:0.6rem;z-index:100;'
        'background:#13131f;border:1px solid #1e1e3a;border-radius:4px;'
        'padding:0.3rem 0.6rem;font-family:monospace;font-size:0.8rem">'
        f'<a href="/reports?project={html.escape(row["project"])}" '
        'style="color:#7ec7ff;text-decoration:none">'
        f'&larr; {html.escape(row["project"])} reports</a></div>'
    )

    if row["format"] == "markdown":
        lede = (
            f'<p class="lede">{html.escape(row["lede"])}</p>'
            if row["lede"] else ""
        )
        return HTMLResponse(content=_MD_PAGE.format(
            title=html.escape(row["title"]),
            back=back,
            lede=lede,
            body=_render_markdown(row["body"]),
        ))

    # HTML: served as authored. The back link is injected after <body> when
    # there is one, and prepended otherwise -- a fragment without a <body>
    # is still a legal report body.
    content = row["body"] or ""
    if "<body" in content:
        content = re.sub(r"(<body[^>]*>)", r"\1" + back, content, count=1)
    else:
        content = back + content
    return HTMLResponse(content=content)
