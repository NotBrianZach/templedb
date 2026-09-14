"""TempleDB GUI — Agent Sessions browser (read-only).

Routes:
  GET /agent-sessions                      List sessions with filters
  GET /agent-sessions/{sid}                Session detail: runs + messages
  GET /agent-sessions/{sid}/runs/{rid}     Run detail: events timeline

The Emacs agent buffer is the interactive surface; this page is the
"where's my history / what did the agent do" browser — useful for
cross-machine access, reviewing old sessions, and sharing links to
specific runs.
"""
import html
import json
import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import query_all, query_one

from gui_helpers import _base

router = APIRouter()


_STATUS_COLOR = {
    "running":     "#e94560",
    "waiting":     "#7ec7ff",
    "completed":   "#3ea866",
    "failed":      "#e94560",
    "interrupted": "#a06060",
    "cancelled":   "#808080",
    "created":     "#8080a0",
}


def _pill(status: str) -> str:
    color = _STATUS_COLOR.get((status or "").lower(), "#8080a0")
    return (
        f'<span style="display:inline-block;padding:0 6px;border-radius:3px;'
        f'font-size:0.7rem;font-weight:600;color:{color};'
        f'border:1px solid {color};background:transparent">'
        f'{html.escape(status or "?")}</span>'
    )


def _list_filter_chip(current: str, value: str, label: str,
                      other_params: str = "") -> str:
    href = "/agent-sessions"
    parts = []
    if value:
        parts.append(f"status={value}")
    if other_params:
        parts.append(other_params)
    qs = "&".join(parts)
    if qs:
        href += "?" + qs
    on = "on" if current == value else ""
    return f'<a class="{on}" href="{href}">{label}</a>'


@router.get("/agent-sessions", response_class=HTMLResponse)
def agent_sessions_list(status: str = "", project: str = "",
                        provider: str = "", limit: int = 100):
    where = []
    params: list = []
    if status:
        where.append("s.status = ?")
        params.append(status)
    if project:
        where.append("p.slug = ?")
        params.append(project)
    if provider:
        where.append("ap.name = ?")
        params.append(provider)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = query_all(
        f"""
        SELECT s.id, s.title, s.status, s.model, s.created_at, s.updated_at,
               s.session_uuid, s.project_id,
               ap.name AS provider_name_col, p.slug AS project_slug,
               (SELECT COUNT(*) FROM agent_runs r WHERE r.session_id = s.id) AS run_count,
               (SELECT COUNT(*) FROM agent_messages m WHERE m.session_id = s.id) AS msg_count,
               (SELECT MAX(mm.created_at) FROM agent_messages mm WHERE mm.session_id = s.id) AS last_msg_at
          FROM agent_sessions s
          LEFT JOIN agent_providers ap ON ap.id = s.provider_id
          LEFT JOIN projects p ON p.id = s.project_id
        {where_sql}
         ORDER BY s.updated_at DESC
         LIMIT ?
        """,
        (*params, limit),
    )

    # Distinct statuses/providers for filter bar
    status_rows = query_all(
        "SELECT status, COUNT(*) c FROM agent_sessions GROUP BY status ORDER BY c DESC",
        (),
    )

    styles = """
    <style>
      .sess-table { border-collapse:collapse; width:100%; font-size:0.88rem; }
      .sess-table th {
        text-align:left; color:#8080a0; font-weight:500; padding:0.4rem 0.6rem;
        border-bottom:1px solid #1e1e3a;
      }
      .sess-table td {
        padding:0.55rem 0.6rem; border-bottom:1px solid #1e1e3a;
        vertical-align:top;
      }
      .sess-table tr:hover { background:#13131f; }
      .sess-table a { color:#7ec7ff; text-decoration:none; }
      .sess-table a:hover { text-decoration:underline; }
      .sess-title { color:#d0d0e8; max-width:32rem; }
      .sess-muted { color:#8080a0; font-family:ui-monospace,monospace; font-size:0.78rem; }
      .filter-bar { margin-bottom:1rem; display:flex; gap:0.4rem; flex-wrap:wrap; font-size:0.85rem; }
      .filter-bar a {
        padding:2px 8px; border-radius:3px; text-decoration:none;
        color:#a0a0c0; background:#13131f; border:1px solid #1e1e3a;
      }
      .filter-bar a.on { color:#e94560; border-color:#e94560; }
      .filter-bar a:hover { color:#e94560; }
    </style>
    """

    filter_bar = (
        '<div class="filter-bar">'
        + _list_filter_chip(status, "", "all")
        + "".join(
            _list_filter_chip(status, r["status"] or "",
                              f'{r["status"] or "?"} ({r["c"]})')
            for r in status_rows
        )
        + '</div>'
    )

    if not rows:
        body = (
            styles + '<h2>Agent Sessions</h2>' + filter_bar
            + '<p class="muted">No sessions match this filter.</p>'
        )
        return _base("Agent Sessions", body, active="agent-sessions")

    row_html = []
    for r in rows:
        title = (r["title"] or "").strip() or "(untitled)"
        row_html.append(
            f'<tr>'
            f'<td><a href="/agent-sessions/{r["id"]}">#{r["id"]}</a></td>'
            f'<td class="sess-title">'
            f'  <a href="/agent-sessions/{r["id"]}">{html.escape(title[:80])}'
            f'{"…" if len(title) > 80 else ""}</a>'
            f'  <div class="sess-muted">{html.escape(r["session_uuid"] or "")[:20]}'
            f'{" · " + html.escape(r["model"]) if r["model"] else ""}</div>'
            f'</td>'
            f'<td>{_pill(r["status"])}</td>'
            f'<td class="sess-muted">{html.escape(r["provider_name_col"] or "?")}</td>'
            f'<td class="sess-muted">'
            f'  {"<a href=\"/projects/" + html.escape(r["project_slug"]) + "\">" + html.escape(r["project_slug"]) + "</a>" if r["project_slug"] else "—"}'
            f'</td>'
            f'<td style="text-align:right"><span class="sess-muted">{r["run_count"]}r · {r["msg_count"]}m</span></td>'
            f'<td class="sess-muted">{html.escape(r["updated_at"] or "")[:19]}</td>'
            f'</tr>'
        )

    body = (
        styles
        + '<h2>Agent Sessions</h2>'
        + '<p class="muted" style="margin-bottom:0.8rem">'
        + f'{len(rows)} session(s), newest activity first. '
        + '<code>r</code>=runs, <code>m</code>=messages.</p>'
        + filter_bar
        + '<table class="sess-table">'
        + '<thead><tr><th>id</th><th>title</th><th>status</th>'
        + '<th>provider</th><th>project</th><th style="text-align:right">counts</th>'
        + '<th>updated</th></tr></thead>'
        + '<tbody>'
        + "".join(row_html)
        + '</tbody></table>'
    )
    return _base("Agent Sessions", body, active="agent-sessions")


@router.get("/agent-sessions/{sid}", response_class=HTMLResponse)
def agent_session_detail(sid: int):
    session = query_one(
        """
        SELECT s.*, ap.name AS provider_name_col, p.slug AS project_slug
          FROM agent_sessions s
          LEFT JOIN agent_providers ap ON ap.id = s.provider_id
          LEFT JOIN projects p ON p.id = s.project_id
         WHERE s.id = ?
        """,
        (sid,),
    )
    if not session:
        return _base(
            "Session not found",
            f'<p>No agent session with id <code>{sid}</code>.</p>'
            '<p><a href="/agent-sessions">&larr; Back</a></p>',
            active="agent-sessions",
        )
    session = dict(session)

    runs = query_all(
        """
        SELECT id, status, started_at, completed_at, last_event_sequence,
               error_text
          FROM agent_runs
         WHERE session_id = ?
         ORDER BY id DESC
        """,
        (sid,),
    )

    # Messages tail (last 20)
    messages = query_all(
        """
        SELECT id, run_id, sequence_number, role, content_text, created_at
          FROM agent_messages
         WHERE session_id = ?
         ORDER BY sequence_number DESC
         LIMIT 20
        """,
        (sid,),
    )
    messages = list(reversed(messages))

    # Meta block
    title = (session.get("title") or "").strip() or "(untitled)"
    meta_rows = [
        ("id",           f'#{session["id"]}'),
        ("status",       _pill(session["status"])),
        ("provider",     html.escape(session.get("provider_name_col") or "?")),
        ("model",        html.escape(session.get("model") or "—")),
        ("project",      f'<a href="/projects/{html.escape(session["project_slug"])}" style="color:#7ec7ff">{html.escape(session["project_slug"])}</a>' if session.get("project_slug") else "—"),
        ("uuid",         html.escape(session.get("session_uuid") or "—")),
        ("external",     html.escape(session.get("external_session_id") or "—")),
        ("created_at",   html.escape(session.get("created_at") or "?")),
        ("updated_at",   html.escape(session.get("updated_at") or "?")),
    ]
    meta_html = (
        '<table style="border-collapse:collapse;margin-bottom:1rem;font-size:0.85rem">'
        + "".join(
            f'<tr>'
            f'<td style="color:#8080a0;padding:2px 0.7rem 2px 0;'
            f'font-family:ui-monospace,monospace">{label}</td>'
            f'<td style="padding:2px 0;color:#d0d0e8">{val}</td>'
            f'</tr>'
            for label, val in meta_rows
        )
        + '</table>'
    )

    # Runs table
    if runs:
        run_rows = []
        for r in runs:
            dur = ""
            if r["started_at"] and r["completed_at"]:
                import datetime as _dt
                try:
                    t1 = _dt.datetime.fromisoformat(r["started_at"])
                    t2 = _dt.datetime.fromisoformat(r["completed_at"])
                    d = int((t2 - t1).total_seconds())
                    dur = f"{d // 60}m{d % 60}s" if d >= 60 else f"{d}s"
                except (TypeError, ValueError):
                    pass
            err = html.escape((r.get("error_text") or "")[:80])
            if err:
                err = f'<div style="color:#e94560;font-size:0.8rem">{err}</div>'
            run_rows.append(
                f'<tr>'
                f'<td><a href="/agent-sessions/{sid}/runs/{r["id"]}">#{r["id"]}</a></td>'
                f'<td>{_pill(r["status"])}</td>'
                f'<td style="font-family:ui-monospace,monospace;font-size:0.78rem;color:#8080a0">{html.escape(r.get("started_at") or "")[:19]}</td>'
                f'<td style="font-family:ui-monospace,monospace;font-size:0.78rem;color:#8080a0">{dur}</td>'
                f'<td style="font-family:ui-monospace,monospace;font-size:0.78rem;color:#8080a0">{r["last_event_sequence"]}</td>'
                f'<td>{err}</td>'
                f'</tr>'
            )
        runs_html = (
            '<h3 style="margin-top:1.2rem">Runs</h3>'
            '<table style="width:100%;border-collapse:collapse;font-size:0.88rem">'
            '<thead><tr>'
            '<th style="text-align:left;color:#8080a0;padding:0.35rem 0.6rem;border-bottom:1px solid #1e1e3a">id</th>'
            '<th style="text-align:left;color:#8080a0;padding:0.35rem 0.6rem;border-bottom:1px solid #1e1e3a">status</th>'
            '<th style="text-align:left;color:#8080a0;padding:0.35rem 0.6rem;border-bottom:1px solid #1e1e3a">started</th>'
            '<th style="text-align:left;color:#8080a0;padding:0.35rem 0.6rem;border-bottom:1px solid #1e1e3a">dur</th>'
            '<th style="text-align:left;color:#8080a0;padding:0.35rem 0.6rem;border-bottom:1px solid #1e1e3a">events</th>'
            '<th style="text-align:left;color:#8080a0;padding:0.35rem 0.6rem;border-bottom:1px solid #1e1e3a">error</th>'
            '</tr></thead><tbody>'
            + "".join(run_rows)
            + '</tbody></table>'
        )
    else:
        runs_html = '<h3 style="margin-top:1.2rem">Runs</h3><p class="muted">No runs.</p>'

    # Messages tail
    msg_rows = []
    for m in messages:
        role = m["role"]
        role_color = "#7ec7ff" if role == "user" else "#3ea866" if role == "assistant" else "#a0a0c0"
        content = (m.get("content_text") or "").strip()
        preview = content[:400] + ("…" if len(content) > 400 else "")
        msg_rows.append(
            f'<div style="margin-bottom:0.7rem;border-left:2px solid {role_color};'
            f'padding-left:0.7rem">'
            f'<div style="color:{role_color};font-weight:600;font-size:0.85rem">'
            f'{html.escape(role)} '
            f'<span class="muted" style="font-size:0.75rem;font-weight:normal">'
            f'seq {m["sequence_number"]}'
            f'{" · run " + str(m["run_id"]) if m["run_id"] else ""} · '
            f'{html.escape(m.get("created_at") or "")[:19]}</span></div>'
            f'<div style="color:#d0d0e8;font-size:0.92rem;line-height:1.45;'
            f'white-space:pre-wrap;margin-top:0.15rem">{html.escape(preview)}</div>'
            f'</div>'
        )
    msgs_html = (
        '<h3 style="margin-top:1.2rem">Latest messages'
        + f' <span class="muted" style="font-size:0.75rem;font-weight:normal">'
        + f'(showing last {len(messages)})</span></h3>'
        + ("".join(msg_rows) if msg_rows else '<p class="muted">No messages.</p>')
    )

    body = (
        '<div style="margin-bottom:0.6rem">'
        '  <a href="/agent-sessions" style="color:#7ec7ff">&larr; Agent Sessions</a>'
        '</div>'
        + f'<h2 style="margin-bottom:0.3rem">{html.escape(title[:100])}</h2>'
        + meta_html
        + runs_html
        + msgs_html
    )
    return _base(f"Session #{sid}", body, active="agent-sessions")


@router.get("/agent-sessions/{sid}/runs/{rid}", response_class=HTMLResponse)
def agent_run_detail(sid: int, rid: int):
    run = query_one(
        "SELECT * FROM agent_runs WHERE id = ? AND session_id = ?",
        (rid, sid),
    )
    if not run:
        return _base(
            "Run not found",
            f'<p>No run #{rid} in session #{sid}.</p>'
            f'<p><a href="/agent-sessions/{sid}">&larr; back to session</a></p>',
            active="agent-sessions",
        )
    run = dict(run)

    events = query_all(
        """
        SELECT id, sequence_number, event_type, summary, payload_json, created_at
          FROM agent_events
         WHERE run_id = ?
         ORDER BY sequence_number ASC
        """,
        (rid,),
    )

    # Meta
    err = (run.get("error_text") or "").strip()
    meta_rows = [
        ("id",           f'#{run["id"]}'),
        ("session",      f'<a href="/agent-sessions/{sid}" style="color:#7ec7ff">#{sid}</a>'),
        ("status",       _pill(run["status"])),
        ("started_at",   html.escape(run.get("started_at") or "?")),
        ("completed_at", html.escape(run.get("completed_at") or "—")),
        ("events",       str(run.get("last_event_sequence") or 0)),
    ]
    if err:
        meta_rows.append(("error",
                          f'<span style="color:#e94560">{html.escape(err[:400])}</span>'))
    meta_html = (
        '<table style="border-collapse:collapse;margin-bottom:1rem;font-size:0.85rem">'
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

    # Event timeline
    ev_rows = []
    for e in events:
        etype = e["event_type"] or "?"
        color = "#7ec7ff"
        if etype.startswith("run."):
            color = "#e94560"
        elif etype.startswith("assistant."):
            color = "#3ea866"
        elif etype.startswith("tool."):
            color = "#e8b060"
        payload_preview = ""
        if e.get("payload_json"):
            try:
                obj = json.loads(e["payload_json"])
                payload_preview = json.dumps(obj, indent=2)
            except (ValueError, TypeError):
                payload_preview = e["payload_json"]
        payload_html = ""
        if payload_preview and len(payload_preview) < 5000:
            payload_html = (
                f'<pre style="background:#0a0a14;border:1px solid #1e1e3a;'
                f'border-radius:3px;padding:0.5rem;margin:0.3rem 0 0 0;'
                f'overflow-x:auto;color:#c0c0e0;font-family:ui-monospace,monospace;'
                f'font-size:0.78rem">'
                f'{html.escape(payload_preview[:2000])}'
                f'{"…" if len(payload_preview) > 2000 else ""}</pre>'
            )
        summary_line = ""
        if e.get("summary"):
            summary_line = (
                '<div style="color:#d0d0e8;font-size:0.88rem;'
                'margin-top:0.15rem">'
                + html.escape(e.get("summary") or "")
                + '</div>'
            )
        ev_rows.append(
            f'<div style="margin-bottom:0.5rem;border-left:2px solid {color};'
            f'padding-left:0.7rem">'
            f'<div style="font-family:ui-monospace,monospace;font-size:0.85rem">'
            f'<span style="color:{color};font-weight:600">{html.escape(etype)}</span> '
            f'<span class="muted" style="font-size:0.75rem">'
            f'seq {e["sequence_number"]} · '
            f'{html.escape(e.get("created_at") or "")[:19]}</span></div>'
            f'{summary_line}'
            f'{payload_html}'
            f'</div>'
        )
    ev_html = (
        f'<h3 style="margin-top:1.2rem">Events '
        + f'<span class="muted" style="font-size:0.75rem;font-weight:normal">'
        + f'({len(events)} total)</span></h3>'
        + ("".join(ev_rows) if ev_rows else '<p class="muted">No events.</p>')
    )

    body = (
        '<div style="margin-bottom:0.6rem">'
        + f'  <a href="/agent-sessions/{sid}" style="color:#7ec7ff">&larr; session #{sid}</a>'
        + '</div>'
        + f'<h2 style="margin-bottom:0.3rem">Run #{rid}</h2>'
        + meta_html
        + ev_html
    )
    return _base(f"Run #{rid}", body, active="agent-sessions")
