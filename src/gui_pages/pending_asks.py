"""TempleDB GUI — Pending Asks pages.

Second surface for `mcp__templedb__templedb_ask_user` prompts, so a
run isn't dead in the water when the Emacs ask widget was missed
(see 2026-09-13 incident where an ask sat unanswered for its full
600s MCP timeout).

Routes:
  GET  /pending-asks                     List active + recent asks
  GET  /pending-asks/{ask_id}            Detail (single ask + form)
  POST /pending-asks/{ask_id}/respond    Submit answer, redirect back

The MCP tool poller (`mcp_server.tool_ask_user`) polls
`agent_pending_asks` every 0.2s, so answering here unblocks the
running Claude subprocess just as fast as answering in Emacs.
"""
import html
import json
import re
import sys
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import query_all, query_one, execute

from gui_helpers import _base

router = APIRouter()

MCP_ASK_TIMEOUT_SECS = 600  # mirrors mcp_server.tool_ask_user's deadline


def _age_secs(created_at: str) -> int:
    """Seconds since CREATED_AT (assumed UTC ISO)."""
    import datetime as _dt
    try:
        t = _dt.datetime.fromisoformat(created_at)
    except (TypeError, ValueError):
        return -1
    return int((_dt.datetime.utcnow() - t).total_seconds())


def _state_for(row: dict) -> str:
    """pending | responded | expired.

    Expired = created > MCP_ASK_TIMEOUT_SECS ago and still pending;
    the MCP-side poller has already given up, so answering now won't
    unblock anything (the row is only kept for audit)."""
    if row.get("status") == "responded":
        return "responded"
    if _age_secs(row.get("created_at") or "") > MCP_ASK_TIMEOUT_SECS:
        return "expired"
    return "pending"


_STATE_STYLE = {
    "pending":   ("#e94560", "pending"),
    "responded": ("#3ea866", "answered"),
    "expired":   ("#a06060", "expired"),
}


def _pill(state):
    color, label = _STATE_STYLE[state]
    return (
        f'<span style="display:inline-block;padding:0 6px;border-radius:3px;'
        f'font-size:0.7rem;font-weight:600;color:{color};'
        f'border:1px solid {color};background:transparent">{label}</span>'
    )


def _fmt_time_ago(created_at: str) -> str:
    secs = _age_secs(created_at)
    if secs < 0:
        return "?"
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _parse_payload(raw: str) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


@router.get("/pending-asks", response_class=HTMLResponse)
def pending_asks_list(state: str = ""):
    rows = query_all(
        """
        SELECT a.*, s.title AS session_title, p.slug AS project_slug
          FROM agent_pending_asks a
          LEFT JOIN agent_sessions s ON s.id = a.session_id
          LEFT JOIN projects p ON p.id = s.project_id
         ORDER BY a.rowid DESC
        """,
        (),
    )
    all_rows = [dict(r) for r in rows]
    counts = {"pending": 0, "responded": 0, "expired": 0}
    filtered = []
    for r in all_rows:
        s = _state_for(r)
        r["_state"] = s
        counts[s] += 1
        if state and s != state:
            continue
        filtered.append(r)

    styles = """
    <style>
      .ask-row {
        display:block; padding:0.8rem 1rem; margin-bottom:0.6rem;
        background:#13131f; border:1px solid #1e1e3a; border-radius:5px;
        text-decoration:none; color:#d0d0e8;
      }
      .ask-row:hover { border-color:#e94560; }
      .ask-row.pending { border-left:3px solid #e94560; }
      .ask-row.responded { opacity:0.65; }
      .ask-head {
        display:flex; align-items:baseline; gap:0.6rem; flex-wrap:wrap;
        margin-bottom:0.3rem;
      }
      .ask-title { color:#7ec7ff; font-weight:600; font-size:0.98rem; }
      .ask-meta {
        color:#8080a0; font-size:0.78rem; font-family:ui-monospace,monospace;
      }
      .ask-body { color:#a0a0c0; font-size:0.88rem; line-height:1.4; }
      .filter-bar { margin-bottom:1rem; display:flex; gap:0.4rem; flex-wrap:wrap; font-size:0.85rem; }
      .filter-bar a {
        padding:2px 8px; border-radius:3px; text-decoration:none;
        color:#a0a0c0; background:#13131f; border:1px solid #1e1e3a;
      }
      .filter-bar a.on { color:#e94560; border-color:#e94560; }
      .filter-bar a:hover { color:#e94560; }
      .deadline {
        color:#e94560; font-family:ui-monospace,monospace; font-size:0.78rem;
      }
    </style>
    """

    def flink(v, label):
        on = "on" if state == v else ""
        return f'<a class="{on}" href="/pending-asks?state={v}">{label}</a>'

    filter_bar = (
        '<div class="filter-bar">'
        + f'<a class="{"on" if not state else ""}" href="/pending-asks">all ({len(all_rows)})</a>'
        + flink("pending",   f'pending ({counts["pending"]})')
        + flink("responded", f'answered ({counts["responded"]})')
        + flink("expired",   f'expired ({counts["expired"]})')
        + '</div>'
    )

    if not filtered:
        empty = (
            "No asks match this filter."
            if state
            else "No pending asks. When Claude uses "
                 "<code>mcp__templedb__templedb_ask_user</code>, the "
                 "question shows up here (as well as in the Emacs agent buffer)."
        )
        return _base(
            "Pending Asks",
            styles + '<h2>Pending Asks</h2>' + filter_bar
            + f'<p class="muted">{empty}</p>',
            active="pending-asks",
        )

    items = []
    for r in filtered:
        s = r["_state"]
        payload = _parse_payload(r.get("payload") or "")
        questions = payload.get("questions") or []
        first_q = ""
        if questions:
            first_q = questions[0].get("question") or ""
        meta_bits = [
            html.escape(r["ask_id"][:12]),
            _fmt_time_ago(r.get("created_at") or ""),
        ]
        if r.get("session_id"):
            meta_bits.append(f'sess #{r["session_id"]}')
        if r.get("session_title"):
            meta_bits.append(html.escape((r["session_title"] or "")[:40]))
        if r.get("project_slug"):
            meta_bits.append(f'@ {html.escape(r["project_slug"])}')
        # Deadline note for pending asks
        deadline_note = ""
        if s == "pending":
            age = _age_secs(r.get("created_at") or "")
            remaining = MCP_ASK_TIMEOUT_SECS - age
            if remaining > 0:
                deadline_note = (
                    f'<div class="deadline">MCP timeout in '
                    f'{remaining // 60}m {remaining % 60}s — '
                    f'answer soon or the run continues without you.</div>'
                )
        items.append(
            f'<a class="ask-row {s}" href="/pending-asks/{html.escape(r["ask_id"])}">'
            f'  <div class="ask-head">'
            f'    <span class="ask-title">{html.escape(first_q) or "(no question)"}</span>'
            f'    {_pill(s)}'
            f'  </div>'
            f'  <div class="ask-meta">{" · ".join(meta_bits)}</div>'
            f'  {deadline_note}'
            f'</a>'
        )

    body = (
        styles
        + '<h2>Pending Asks</h2>'
        + '<p class="muted" style="margin-bottom:0.8rem">'
        + '<code>mcp__templedb__templedb_ask_user</code> questions from '
        + 'running agents. Answering here unblocks the run just as fast '
        + 'as clicking the Emacs widget — the MCP tool polls the DB '
        + f'every 0.2s. Deadline is {MCP_ASK_TIMEOUT_SECS}s from creation.'
        + '</p>'
        + filter_bar
        + "".join(items)
    )
    return _base("Pending Asks", body, active="pending-asks")


@router.get("/pending-asks/{ask_id}", response_class=HTMLResponse)
def pending_asks_view(ask_id: str):
    row = query_one(
        """
        SELECT a.*, s.title AS session_title, p.slug AS project_slug
          FROM agent_pending_asks a
          LEFT JOIN agent_sessions s ON s.id = a.session_id
          LEFT JOIN projects p ON p.id = s.project_id
         WHERE a.ask_id = ?
        """,
        (ask_id,),
    )
    if not row:
        return _base(
            "Ask not found",
            f'<p>No ask with id <code>{html.escape(ask_id)}</code>.</p>'
            '<p><a href="/pending-asks">&larr; Back</a></p>',
            active="pending-asks",
        )
    row = dict(row)
    state = _state_for(row)
    payload = _parse_payload(row.get("payload") or "")
    questions = payload.get("questions") or []

    # Meta table
    meta_rows = [
        ("ask_id",       html.escape(row["ask_id"])),
        ("state",        _pill(state)),
        ("kind",         html.escape(row.get("kind") or "?")),
        ("session",      f'<a href="/agent-sessions/{row["session_id"]}" '
                         f'style="color:#7ec7ff">'
                         f'#{row["session_id"]} — {html.escape((row.get("session_title") or "")[:60])}'
                         f'</a>' if row.get("session_id") else "—"),
        ("project",      html.escape(row.get("project_slug") or "—")),
        ("created_at",   html.escape(row.get("created_at") or "?")
                         + f' <span class="muted">({_fmt_time_ago(row.get("created_at") or "")})</span>'),
        ("dispatched",   html.escape(row.get("dispatched_at") or "—")),
        ("responded",    html.escape(row.get("responded_at") or "—")),
    ]
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

    # Prior response (if any)
    resp_html = ""
    if row.get("response"):
        try:
            resp_obj = json.loads(row["response"])
        except (ValueError, TypeError):
            resp_obj = {"raw": row["response"]}
        resp_html = (
            '<h3 style="margin-top:1.2rem">Response</h3>'
            f'<pre style="background:#13131f;border:1px solid #1e1e3a;'
            f'border-radius:4px;padding:0.7rem;overflow-x:auto;color:#c0c0e0;'
            f'font-family:ui-monospace,monospace;font-size:0.85rem">'
            f'{html.escape(json.dumps(resp_obj, indent=2))}</pre>'
        )

    # Answer form for pending (and even expired — user might want to
    # record an answer for audit even if the run has moved on)
    form_html = ""
    if state != "responded":
        deadline_warn = ""
        if state == "expired":
            deadline_warn = (
                '<p style="color:#e94560;font-size:0.85rem">'
                'This ask is past the MCP timeout — the run has already '
                'continued without your answer. Submitting here just '
                'records it for audit; it will NOT unblock anything.</p>'
            )
        elif state == "pending":
            age = _age_secs(row.get("created_at") or "")
            remaining = MCP_ASK_TIMEOUT_SECS - age
            deadline_warn = (
                f'<p class="deadline" style="color:#e94560;font-size:0.85rem">'
                f'MCP tool times out in <b>{remaining // 60}m {remaining % 60}s</b>. '
                f'The Claude subprocess is currently blocked in an epoll_wait '
                f'polling this row.</p>'
            )
        fields = []
        for i, q in enumerate(questions):
            qtext = q.get("question") or f"question {i+1}"
            options = q.get("options") or []
            multi = q.get("multiSelect")
            fields.append(f'<fieldset style="border:1px solid #1e1e3a;'
                          f'border-radius:4px;padding:0.7rem 1rem 0.9rem;'
                          f'margin-bottom:0.8rem"><legend style="color:#7ec7ff;'
                          f'padding:0 0.4rem;font-size:0.92rem">{html.escape(qtext)}</legend>')
            for j, o in enumerate(options):
                label = o.get("label") or f"option {j+1}"
                desc = o.get("description") or ""
                input_type = "checkbox" if multi else "radio"
                fields.append(
                    f'<label style="display:block;margin:0.35rem 0;'
                    f'cursor:pointer;line-height:1.4">'
                    f'  <input type="{input_type}" '
                    f'name="q_{i}"{" required" if not multi and j == 0 else ""} '
                    f'value="{html.escape(label)}" '
                    f'style="margin-right:0.5rem">'
                    f'  <span style="color:#d0d0e8;font-weight:500">'
                    f'{html.escape(label)}</span>'
                    f'  {f" <span class=\"muted\" style=\"font-size:0.85rem\"> — {html.escape(desc)}</span>" if desc else ""}'
                    f'</label>'
                )
            # Preserve question text for response building (server needs it)
            fields.append(f'<input type="hidden" name="qtext_{i}" '
                          f'value="{html.escape(qtext)}">')
            fields.append(f'<input type="hidden" name="qmulti_{i}" '
                          f'value="{"1" if multi else "0"}">')
            fields.append('</fieldset>')

        form_html = (
            '<h3 style="margin-top:1.2rem">Answer</h3>'
            + deadline_warn
            + f'<form method="post" action="/pending-asks/{html.escape(ask_id)}/respond">'
            + f'<input type="hidden" name="_n" value="{len(questions)}">'
            + "".join(fields)
            + '<button type="submit" style="background:#3ea866;color:#0a0a14;'
            + 'border:0;padding:0.5rem 1.1rem;border-radius:3px;'
            + 'font-weight:600;cursor:pointer">Submit answer</button>'
            + '</form>'
        )

    # Show the raw questions payload for pending too (so you can see
    # the full descriptions if the form scrolled)
    q_summary = ""
    if questions and state == "responded":
        q_summary = (
            '<h3 style="margin-top:1.2rem">Question' + ('s' if len(questions) > 1 else '') + '</h3>'
            + "".join(
                f'<p><b>{html.escape(q.get("question") or "?")}</b><br>'
                + "<br>".join(
                    f'&nbsp;&nbsp;{html.escape(o.get("label") or "?")}'
                    + (f" — <span class='muted'>{html.escape(o.get('description') or '')}</span>"
                       if o.get("description") else "")
                    for o in (q.get("options") or [])
                )
                + '</p>'
                for q in questions
            )
        )

    styles = """
    <style>
      .deadline b { color:#ffdd88 }
    </style>
    """

    body = (
        styles
        + '<div style="margin-bottom:0.6rem">'
        + '  <a href="/pending-asks" style="color:#7ec7ff">&larr; Pending Asks</a>'
        + '</div>'
        + f'<h2 style="margin-bottom:0.3rem">Ask {html.escape(ask_id[:12])}…</h2>'
        + meta_html
        + form_html
        + q_summary
        + resp_html
    )
    return _base(f"Ask {ask_id[:8]}", body, active="pending-asks")


@router.post("/pending-asks/{ask_id}/respond", response_class=HTMLResponse)
async def pending_asks_respond(ask_id: str, request: Request):
    """Persist the user's answer. Idempotent on already-responded asks
    (won't overwrite an existing response)."""
    form = await request.form()
    n = int(form.get("_n") or 0)
    answers: dict = {}
    for i in range(n):
        qtext = form.get(f"qtext_{i}") or f"question_{i}"
        multi = form.get(f"qmulti_{i}") == "1"
        vals = form.getlist(f"q_{i}") if hasattr(form, "getlist") else [form.get(f"q_{i}")]
        vals = [v for v in vals if v]
        if not vals:
            continue
        answers[qtext] = vals if multi else vals[0]
    response = {"answers": answers}
    execute(
        """UPDATE agent_pending_asks
             SET status = 'responded',
                 response = ?,
                 responded_at = datetime('now')
           WHERE ask_id = ? AND status = 'pending'""",
        (json.dumps(response), ask_id),
    )
    return RedirectResponse(url=f"/pending-asks/{ask_id}", status_code=303)
