"""TempleDB GUI — Handoffs pages.

Three routes:
  GET  /handoffs                 -- list of handoff notes with state (unread/read/acked/expired)
  GET  /handoffs/{id}            -- detail view; marks read_at on load
  POST /handoffs/{id}/ack        -- ack the handoff, redirect back to list

Handoffs live in the `handoff_notes` table (see migration for
Cross-session handoff / Phase 2.5 in CLAUDE.md). CLI equivalents:

  templedb handoff list [--unread]
  templedb handoff show <id>
  templedb handoff ack <id> [-m note]
  templedb handoff pop [--for SID]

The GUI adds discoverability — unread pill on the dashboard already
counts them; this page lets you actually read the body.
"""
import html
import re
import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, RedirectResponse

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import query_all, query_one, execute

from gui_helpers import _base

router = APIRouter()


def _state_for(row):
    """Derive a display state: acked > expired > unread > read.
    Acked wins because an acked note is 'done', even if it was
    otherwise expired or unread first."""
    if row.get("acked_at"):
        return "acked"
    if row.get("expires_at"):
        import datetime as _dt
        try:
            exp = _dt.datetime.fromisoformat(row["expires_at"])
            if exp < _dt.datetime.utcnow():
                return "expired"
        except (TypeError, ValueError):
            pass
    if row.get("read_at"):
        return "read"
    return "unread"


_STATE_STYLE = {
    "unread":  ("#e94560", "unread"),
    "read":    ("#8080a0", "read"),
    "acked":   ("#3ea866", "acked"),
    "expired": ("#a06060", "expired"),
}


def _pill(state):
    color, label = _STATE_STYLE[state]
    return (
        f'<span style="display:inline-block;padding:0 6px;border-radius:3px;'
        f'font-size:0.7rem;font-weight:600;color:{color};'
        f'border:1px solid {color};background:transparent">'
        f'{label}</span>'
    )


def _fmt_tags(tags_raw):
    if not tags_raw:
        return ""
    # tags stored as JSON list per templedb handoff send --tag T
    import json
    try:
        parts = json.loads(tags_raw)
    except (ValueError, TypeError):
        parts = [tags_raw]
    if isinstance(parts, str):
        parts = [parts]
    return "".join(
        f'<span style="display:inline-block;margin-right:0.3rem;padding:1px 6px;'
        f'border-radius:3px;background:#1a1a2e;color:#a0a0c0;font-size:0.7rem;'
        f'font-family:ui-monospace,monospace">{html.escape(str(t))}</span>'
        for t in parts if t
    )


def _fmt_body(body: str) -> str:
    """Render body preserving line breaks + tabify triple-backtick blocks.
    Deliberately not a full markdown renderer — CLI handoffs are typically
    plain text with fenced code blocks."""
    if not body:
        return '<span class="muted">(empty)</span>'
    escaped = html.escape(body)
    # Fenced code blocks
    escaped = re.sub(
        r'```([\w-]*)\n(.*?)```',
        lambda m: (
            f'<pre style="background:#0a0a14;border:1px solid #1e1e3a;'
            f'border-radius:4px;padding:0.7rem;overflow-x:auto;color:#c0c0e0;'
            f'font-family:ui-monospace,monospace;font-size:0.85rem">'
            f'{m.group(2)}</pre>'
        ),
        escaped,
        flags=re.DOTALL,
    )
    # Inline code
    escaped = re.sub(
        r'`([^`\n]+)`',
        r'<code style="background:#0a0a14;padding:0 4px;border-radius:2px;'
        r'color:#c0c0e0;font-family:ui-monospace,monospace;font-size:0.88em">\1</code>',
        escaped,
    )
    # Preserve line breaks outside fenced blocks
    lines = []
    in_pre = False
    for line in escaped.split("\n"):
        if "<pre " in line:
            in_pre = True
        if in_pre:
            lines.append(line)
            if "</pre>" in line:
                in_pre = False
                lines.append("")  # blank after fenced block
        else:
            lines.append(line + "<br>")
    return "\n".join(lines)


@router.get("/handoffs", response_class=HTMLResponse)
def handoffs_list(state: str = "", topic: str = "", session: str = ""):
    """List handoffs, newest first. Query params:
      ?state=unread|read|acked|expired   -- filter by state
      ?topic=<topic>                     -- filter by to_topic
      ?session=<sid>                     -- filter by to_session
    """
    rows = query_all(
        """
        SELECT h.*, p.slug AS project_slug
          FROM handoff_notes h
          LEFT JOIN projects p ON p.id = h.project_id
         ORDER BY h.id DESC
        """,
        (),
    )
    all_rows = [dict(r) for r in rows]
    # Compute state per row + optional filtering
    filtered = []
    counts = {"unread": 0, "read": 0, "acked": 0, "expired": 0}
    for r in all_rows:
        s = _state_for(r)
        r["_state"] = s
        counts[s] += 1
        if state and s != state:
            continue
        if topic and r.get("to_topic") != topic:
            continue
        if session and r.get("to_session") != session:
            continue
        filtered.append(r)

    styles = """
    <style>
      .handoff-row {
        display:block; padding:0.8rem 1rem; margin-bottom:0.6rem;
        background:#13131f; border:1px solid #1e1e3a; border-radius:5px;
        text-decoration:none; color:#d0d0e8;
      }
      .handoff-row:hover { border-color:#e94560; }
      .handoff-row.unread { border-left:3px solid #e94560; }
      .handoff-row.acked  { opacity:0.65; }
      .handoff-head {
        display:flex; align-items:baseline; gap:0.6rem; flex-wrap:wrap;
        margin-bottom:0.3rem;
      }
      .handoff-title { color:#7ec7ff; font-weight:600; font-size:1rem; }
      .handoff-meta {
        color:#8080a0; font-size:0.78rem; font-family:ui-monospace,monospace;
      }
      .handoff-body-preview {
        color:#a0a0c0; font-size:0.88rem; line-height:1.4;
        white-space:pre-wrap;
        display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical;
        overflow:hidden;
      }
      .filter-bar {
        margin-bottom:1rem; display:flex; gap:0.4rem; flex-wrap:wrap;
        font-size:0.85rem;
      }
      .filter-bar a {
        padding:2px 8px; border-radius:3px; text-decoration:none;
        color:#a0a0c0; background:#13131f; border:1px solid #1e1e3a;
      }
      .filter-bar a.on { color:#e94560; border-color:#e94560; }
      .filter-bar a:hover { color:#e94560; }
    </style>
    """

    def flink(kind, value, label):
        # Build a filter link that toggles this facet.
        params = []
        for k, v in (("state", state), ("topic", topic), ("session", session)):
            if k == kind:
                if v == value:
                    continue  # remove filter
                params.append((k, value))
            else:
                if v:
                    params.append((k, v))
        qs = "&".join(f"{k}={v}" for k, v in params)
        on = "on" if value == locals().get(kind, "") else ""
        # `state` filter compares to the query param, not the current filter
        # value — need explicit lookup because Python 'locals()' inside a
        # nested func isn't guaranteed to see the outer scope on all Pythons.
        current = {"state": state, "topic": topic, "session": session}[kind]
        on_cls = "on" if value == current else ""
        return f'<a class="{on_cls}" href="/handoffs{("?" + qs) if qs else ""}">{label}</a>'

    filter_bar = (
        '<div class="filter-bar">'
        + f'<a class="{"on" if not state else ""}" href="/handoffs">all ({len(all_rows)})</a>'
        + flink("state", "unread",  f'unread ({counts["unread"]})')
        + flink("state", "read",    f'read ({counts["read"]})')
        + flink("state", "acked",   f'acked ({counts["acked"]})')
        + flink("state", "expired", f'expired ({counts["expired"]})')
        + '</div>'
    )

    if not filtered:
        empty_msg = (
            'no handoffs match this filter'
            if any([state, topic, session])
            else "no handoffs yet — send one with "
                 "<code>templedb handoff send --broadcast --subject '...' --body '...'</code>"
        )
        body_html = (
            styles
            + '<h2>Handoffs</h2>'
            + filter_bar
            + f'<p class="muted">{empty_msg}</p>'
        )
        return _base("Handoffs", body_html, active="handoffs")

    items = []
    for r in filtered:
        s = r["_state"]
        # 2-line preview of body
        body_preview = (r.get("body") or "").strip()
        subject = html.escape(r.get("subject") or "(no subject)")
        meta_bits = []
        meta_bits.append(f'#{r["id"]}')
        meta_bits.append(html.escape(r.get("created_at") or "?"))
        if r.get("to_topic"):
            meta_bits.append(f'→ topic: {html.escape(r["to_topic"])}')
        if r.get("to_session"):
            meta_bits.append(f'→ sid: {html.escape(r["to_session"][:20])}')
        if r.get("project_slug"):
            meta_bits.append(f'@ {html.escape(r["project_slug"])}')
        if r.get("from_actor"):
            meta_bits.append(f'from {html.escape(r["from_actor"])}')

        items.append(
            f'<a class="handoff-row {s}" href="/handoffs/{r["id"]}">'
            f'  <div class="handoff-head">'
            f'    <span class="handoff-title">{subject}</span>'
            f'    {_pill(s)}'
            f'    {_fmt_tags(r.get("tags"))}'
            f'  </div>'
            f'  <div class="handoff-meta">{" · ".join(meta_bits)}</div>'
            f'  <div class="handoff-body-preview">{html.escape(body_preview)}</div>'
            f'</a>'
        )

    body_html = (
        styles
        + '<h2>Handoffs</h2>'
        + '<p class="muted" style="margin-bottom:0.9rem">'
        + 'Cross-session/cross-agent notes. Unread notes have a red left '
        + 'border; open one to mark it read; ack it from the detail view '
        + f'when the action is done. Counter also appears on '
        + f'<a href="/summary" style="color:#7ec7ff">/summary</a>.</p>'
        + filter_bar
        + "".join(items)
    )
    return _base("Handoffs", body_html, active="handoffs")


@router.get("/handoffs/{note_id}", response_class=HTMLResponse)
def handoffs_view(note_id: int):
    row = query_one(
        """
        SELECT h.*, p.slug AS project_slug
          FROM handoff_notes h
          LEFT JOIN projects p ON p.id = h.project_id
         WHERE h.id = ?
        """,
        (note_id,),
    )
    if not row:
        return _base(
            "Handoff not found",
            (
                f'<p>No handoff with id <code>{note_id}</code>.</p>'
                f'<p><a href="/handoffs">&larr; Back to handoffs</a></p>'
            ),
            active="handoffs",
        )
    row = dict(row)
    # Mark read on first view (idempotent — schema.sql pattern).
    if not row.get("read_at"):
        execute(
            "UPDATE handoff_notes SET read_at = datetime('now') "
            "WHERE id = ? AND read_at IS NULL",
            (note_id,),
        )
        row["read_at"] = "just now"  # so state pill flips immediately

    state = _state_for(row)
    subject = html.escape(row.get("subject") or "(no subject)")
    body_rendered = _fmt_body(row.get("body") or "")

    meta_rows = [
        ("id",          f'#{row["id"]}'),
        ("state",       _pill(state)),
        ("subject",     subject),
        ("from",        html.escape(f"{row.get('from_actor') or '?'} "
                                    f"({row.get('from_session') or '?'})")),
        ("to",          html.escape(
            "broadcast" if not (row.get("to_topic") or row.get("to_session"))
            else f"topic={row.get('to_topic') or ''} "
                 f"session={row.get('to_session') or ''}"
        )),
        ("project",     html.escape(row.get("project_slug") or "—")),
        ("tags",        _fmt_tags(row.get("tags")) or '<span class="muted">—</span>'),
        ("created_at",  html.escape(row.get("created_at") or "?")),
        ("read_at",     html.escape(str(row.get("read_at") or "—"))),
        ("acked_at",    html.escape(str(row.get("acked_at") or "—"))),
        ("expires_at",  html.escape(str(row.get("expires_at") or "—"))),
    ]
    for label, ref_key in (
        ("ref_report", "ref_report"),
        ("ref_commit", "ref_commit"),
        ("ref_file",   "ref_file"),
    ):
        val = row.get(ref_key)
        if val:
            v = html.escape(str(val))
            if ref_key == "ref_report":
                v = f'<a href="/reports/{v}" style="color:#7ec7ff">{v}</a>'
            elif ref_key == "ref_commit" and row.get("project_slug"):
                v = (f'<a href="/vcs/{html.escape(row["project_slug"])}'
                     f'/commits/{v}" style="color:#7ec7ff">{v}</a>')
            meta_rows.append((label, v))

    meta_html = (
        '<table style="border-collapse:collapse;margin-bottom:1rem;'
        'font-size:0.85rem">'
        + "".join(
            f'<tr>'
            f'<td style="color:#8080a0;padding:2px 0.7rem 2px 0;'
            f'font-family:ui-monospace,monospace;vertical-align:top">{label}</td>'
            f'<td style="padding:2px 0;color:#d0d0e8;vertical-align:top">{val}</td>'
            f'</tr>'
            for label, val in meta_rows
        )
        + '</table>'
    )

    ack_form = (
        f'<form method="post" action="/handoffs/{row["id"]}/ack" '
        f'style="display:inline-block;margin-right:0.5rem">'
        f'  <button type="submit" '
        f'  style="background:#3ea866;color:#0a0a14;border:0;'
        f'  padding:0.4rem 0.9rem;border-radius:3px;font-weight:600;'
        f'  cursor:pointer">Ack</button>'
        f'</form>'
        if not row.get("acked_at") else
        '<span class="muted" style="font-size:0.85rem">already acked</span>'
    )

    body_html = (
        f'<div style="margin-bottom:0.6rem">'
        f'  <a href="/handoffs" style="color:#7ec7ff">&larr; Handoffs</a>'
        f'</div>'
        f'<h2 style="margin-bottom:0.3rem">{subject}</h2>'
        f'{meta_html}'
        f'<div style="margin-bottom:1rem">{ack_form}</div>'
        f'<div style="background:#13131f;border:1px solid #1e1e3a;'
        f'border-radius:5px;padding:1rem;line-height:1.55;'
        f'font-size:0.94rem;color:#d0d0e8">{body_rendered}</div>'
    )
    return _base(f"Handoff #{note_id}", body_html, active="handoffs")


@router.post("/handoffs/{note_id}/ack", response_class=HTMLResponse)
def handoffs_ack(note_id: int):
    execute(
        "UPDATE handoff_notes "
        "   SET acked_at = datetime('now'), "
        "       read_at = COALESCE(read_at, datetime('now')) "
        " WHERE id = ? AND acked_at IS NULL",
        (note_id,),
    )
    return RedirectResponse(url=f"/handoffs/{note_id}", status_code=303)
