"""TempleDB GUI — Agent check-ins (the `agent_notifications` queue).

Two routes:
  GET /notifications          -- newest first, filterable by kind
  GET /notifications/{id}     -- the full body_md of one check-in

Why this page exists. Every autonomous task run enqueues a row here
(`agent.store.create_notification`, called from the tick at
`cli/commands/agent.py`), carrying the task name, status, duration, the
error text and the agent's own summary. The tick then tries to mail them
via `EmailService.drain`. That drain had never once succeeded: 21 rows
had accumulated unsent between 2026-09-20 and 2026-11-15, because the
SMTP secrets were never set.

So the content existed and nothing could read it. The queue was write-
only in practice, and `agent_notifications` appeared nowhere in
gui_pages. This is the read surface, and it deliberately needs no
transport: with the GUI served to the tailnet, "what did my agents do
and what broke" is answerable from a phone without SMTP, a push
provider, or an account anywhere.

Reading here does NOT mark a row sent. `sent_at` means "the mail went
out", and claiming delivery because someone opened a web page would
make the drain skip rows it never sent. Unsent is shown as a state, not
hidden.
"""
import html
import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import query_all, query_one

from gui_helpers import _base

router = APIRouter()

# kind is a free TEXT column; these are the values the tick actually
# writes ('final' on success, 'error' otherwise) plus 'decision', which
# the decision-point columns are for. Anything else renders as itself
# rather than being dropped — a filter that silently hides unknown kinds
# is how a new producer becomes invisible.
_KIND_STYLE = {
    "error": ("red", "error"),
    "final": ("green", "done"),
    "decision": ("blue", "decision"),
}


def _pill(kind):
    cls, label = _KIND_STYLE.get(kind, ("", html.escape(kind or "?")))
    return f'<span class="badge {cls}">{label}</span>'


def _sent_cell(row):
    """Delivery state. Unsent is the common case here and is not an error."""
    if row.get("sent_at"):
        return f'<span class="badge green">sent</span>'
    if row.get("send_error"):
        err = html.escape(str(row["send_error"])[:60])
        return (f'<span class="badge red">failed</span> '
                f'<span class="muted">{err}</span>')
    attempts = row.get("send_attempts") or 0
    if attempts:
        return f'<span class="badge">unsent ({attempts} tries)</span>'
    return '<span class="badge">unsent</span>'


@router.get("/notifications", response_class=HTMLResponse)
def notifications_list(kind: str = ""):
    counts = {
        r["kind"]: r["n"] for r in query_all(
            "SELECT kind, COUNT(*) n FROM agent_notifications GROUP BY kind")
    }
    total = sum(counts.values())

    if kind:
        rows = query_all(
            """SELECT n.*, s.title AS session_title
                 FROM agent_notifications n
                 LEFT JOIN agent_sessions s ON s.id = n.session_id
                WHERE n.kind = ?
                ORDER BY n.created_at DESC, n.id DESC
                LIMIT 200""", (kind,))
    else:
        rows = query_all(
            """SELECT n.*, s.title AS session_title
                 FROM agent_notifications n
                 LEFT JOIN agent_sessions s ON s.id = n.session_id
                ORDER BY n.created_at DESC, n.id DESC
                LIMIT 200""")

    def flink(k, label):
        active = ' style="color:#e94560"' if kind == k else ""
        href = f"/notifications?kind={k}" if k else "/notifications"
        return f'<a href="{href}"{active}>{label}</a>'

    filters = " · ".join(
        [flink("", f"all ({total})")]
        + [flink(k, f"{k} ({counts[k]})") for k in sorted(counts)]
    )

    if not rows:
        body = (f'<h2>Agent check-ins</h2><div class="row">{filters}</div>'
                f'<p class="muted">No check-ins{" of this kind" if kind else ""} '
                f'yet. Every autonomous task run enqueues one.</p>')
        return _base("Check-ins", body, active="notifications")

    trs = []
    for r in rows:
        subj = html.escape(r["subject"] or "")
        sess = (f'<a href="/agent-sessions/{r["session_id"]}">'
                f'#{r["session_id"]}</a>') if r.get("session_id") else \
               '<span class="muted">—</span>'
        trs.append(
            f'<tr>'
            f'<td>{_pill(r["kind"])}</td>'
            f'<td><a href="/notifications/{r["id"]}">{subj}</a></td>'
            f'<td>{sess}</td>'
            f'<td>{_sent_cell(r)}</td>'
            f'<td class="muted">{html.escape(str(r["created_at"] or ""))}</td>'
            f'</tr>'
        )

    body = (
        f'<h2>Agent check-ins</h2>'
        f'<div class="row">{filters}</div>'
        f'<div class="row"><input type="text" class="full" '
        f'placeholder="filter visible rows…" '
        f'oninput="tFilter(\'checkins\', this.value)"></div>'
        f'<div id="checkins"><table>'
        f'<thead><tr><th>Kind</th><th>Subject</th><th>Session</th>'
        f'<th>Delivery</th><th>Created</th></tr></thead>'
        f'<tbody>{"".join(trs)}</tbody></table></div>'
    )
    return _base("Check-ins", body, active="notifications")


@router.get("/notifications/{notification_id}", response_class=HTMLResponse)
def notifications_view(notification_id: int):
    row = query_one(
        """SELECT n.*, s.title AS session_title
             FROM agent_notifications n
             LEFT JOIN agent_sessions s ON s.id = n.session_id
            WHERE n.id = ?""", (notification_id,))
    if not row:
        return _base(
            "Check-in",
            f'<h2>Check-in {notification_id}</h2>'
            f'<div class="msg err">No such check-in.</div>'
            f'<p><a href="/notifications">← all check-ins</a></p>',
            active="notifications")

    # body_md is markdown, rendered as preformatted text rather than
    # converted. The producer writes a small fixed shape (bold labels and
    # a fenced error block), there is no markdown dependency in this
    # codebase, and a half-renderer that mangles the fenced traceback
    # would lose the one part worth reading.
    body_md = html.escape(row["body_md"] or "")

    meta = [
        ("Kind", _pill(row["kind"])),
        ("Delivery", _sent_cell(row)),
        ("Created", html.escape(str(row["created_at"] or ""))),
    ]
    if row.get("session_id"):
        title = html.escape(row.get("session_title") or "")
        meta.append(("Session",
                     f'<a href="/agent-sessions/{row["session_id"]}">'
                     f'#{row["session_id"]}</a> {title}'))
    if row.get("decision"):
        meta.append(("Decision", html.escape(str(row["decision"]))))

    meta_html = "".join(
        f'<tr><th style="width:8rem">{k}</th><td>{v}</td></tr>'
        for k, v in meta)

    body = (
        f'<h2>{html.escape(row["subject"] or "")}</h2>'
        f'<table>{meta_html}</table>'
        f'<pre>{body_md}</pre>'
        f'<p><a href="/notifications">← all check-ins</a></p>'
    )
    return _base("Check-in", body, active="notifications")
