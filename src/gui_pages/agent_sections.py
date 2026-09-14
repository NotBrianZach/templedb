"""TempleDB GUI — Agent-writable sections viewer.

Shows what agents have written into agent_session_sections via
  mcp__templedb__templedb_agent_note_finding
  mcp__templedb__templedb_agent_todo_add
  mcp__templedb__templedb_agent_question_add
  mcp__templedb__templedb_agent_section_write

These are visible in the Emacs agent buffer per-session; this page
gives you a cross-session mining view — "show me every finding an
agent ever wrote about bza" or "what open todos are still open."

Route:
  GET /agent-sections     Filterable by section type and session.

Read-only — user can flip a todo to done via `templedb agent-todo done`
CLI (or in Emacs); no write path from the GUI yet.
"""
import html
import json
import sys
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import query_all

from gui_helpers import _base

router = APIRouter()


_SECTION_STYLE = {
    "findings":       ("#7ec7ff", "finding"),
    "todo":           ("#e8b060", "todo"),
    "open-questions": ("#e94560", "question"),
    # dynamic:* sections use a shared style, but per-name distinct label
}


def _section_pill(section: str) -> str:
    color, label = _SECTION_STYLE.get(section, ("#a0a0c0", section))
    if section.startswith("dynamic:"):
        color = "#c090e0"
        label = section.split(":", 1)[1] or section
    return (
        f'<span style="display:inline-block;padding:0 6px;border-radius:3px;'
        f'font-size:0.7rem;font-weight:600;color:{color};'
        f'border:1px solid {color};background:transparent">'
        f'{html.escape(label)}</span>'
    )


def _parse_entry(raw: str) -> dict:
    if not raw:
        return {}
    try:
        v = json.loads(raw)
        if isinstance(v, dict):
            return v
    except (ValueError, TypeError):
        pass
    return {"text": str(raw)}


@router.get("/agent-sections", response_class=HTMLResponse)
def agent_sections_list(section: str = "", session: str = "",
                        state: str = ""):
    where, params = [], []
    if section:
        where.append("ss.section = ?")
        params.append(section)
    if session:
        try:
            sid = int(session)
            where.append("ss.session_id = ?")
            params.append(sid)
        except ValueError:
            pass
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows = query_all(
        f"""
        SELECT ss.*, s.title AS session_title, p.slug AS project_slug
          FROM agent_session_sections ss
          LEFT JOIN agent_sessions s ON s.id = ss.session_id
          LEFT JOIN projects p ON p.id = s.project_id
        {where_sql}
         ORDER BY ss.updated_at DESC
        """,
        tuple(params),
    )
    rows = [dict(r) for r in rows]

    # Apply the todo-done / question-answered filter in Python since it
    # lives inside entry_json.
    if state in ("done", "open") and section == "todo":
        want_done = state == "done"
        rows = [
            r for r in rows
            if bool(_parse_entry(r.get("entry_json") or "").get("done"))
               == want_done
        ]
    if state in ("answered", "unanswered") and section == "open-questions":
        want_answered = state == "answered"
        rows = [
            r for r in rows
            if bool(_parse_entry(r.get("entry_json") or "").get("answered"))
               == want_answered
        ]

    # Section counts (unfiltered) — for filter chips
    section_rows = query_all(
        "SELECT section, COUNT(*) c FROM agent_session_sections "
        "GROUP BY section ORDER BY c DESC",
        (),
    )

    styles = """
    <style>
      .sec-item {
        display:flex; gap:0.9rem; padding:0.65rem 0.9rem;
        margin-bottom:0.5rem;
        background:#13131f; border:1px solid #1e1e3a; border-radius:5px;
      }
      .sec-item .sec-side {
        display:flex; flex-direction:column; gap:0.25rem; min-width:8rem;
        font-size:0.75rem;
      }
      .sec-item .sec-body {
        flex-grow:1; color:#d0d0e8; font-size:0.92rem; line-height:1.45;
      }
      .sec-item.done { opacity:0.5; }
      .sec-item.done .sec-body { text-decoration:line-through; }
      .filter-bar { margin-bottom:0.7rem; display:flex; gap:0.4rem; flex-wrap:wrap; font-size:0.83rem; }
      .filter-bar a {
        padding:2px 8px; border-radius:3px; text-decoration:none;
        color:#a0a0c0; background:#13131f; border:1px solid #1e1e3a;
      }
      .filter-bar a.on { color:#e94560; border-color:#e94560; }
      .filter-bar a:hover { color:#e94560; }
      .ref-pill {
        display:inline-block; padding:1px 5px; border-radius:3px;
        background:#1a1a2e; color:#a0a0c0; font-size:0.7rem;
        font-family:ui-monospace,monospace; margin-right:0.25rem;
      }
      .priority-h { color:#e94560; font-weight:600; }
      .priority-m { color:#e8b060; }
      .priority-l { color:#8080a0; }
    </style>
    """

    def sec_link(v, label):
        params_l = []
        current = section
        if v != current:
            params_l.append(f"section={v}")
        if session:
            params_l.append(f"session={session}")
        if state:
            params_l.append(f"state={state}")
        qs = "&".join(params_l)
        href = "/agent-sections" + (("?" + qs) if qs else "")
        on = "on" if v == current else ""
        return f'<a class="{on}" href="{href}">{label}</a>'

    def state_link(v, label):
        params_l = []
        if section:
            params_l.append(f"section={section}")
        if session:
            params_l.append(f"session={session}")
        if v != state:
            params_l.append(f"state={v}")
        qs = "&".join(params_l)
        href = "/agent-sections" + (("?" + qs) if qs else "")
        on = "on" if v == state else ""
        return f'<a class="{on}" href="{href}">{label}</a>'

    section_bar = (
        '<div class="filter-bar">'
        + f'<a class="{"on" if not section else ""}" href="/agent-sections">all sections</a>'
        + "".join(
            sec_link(r["section"], f'{r["section"]} ({r["c"]})')
            for r in section_rows
        )
        + '</div>'
    )

    # State bar shown only when a state-bearing section is selected
    state_bar = ""
    if section == "todo":
        state_bar = (
            '<div class="filter-bar">'
            + state_link("", "all todos")
            + state_link("open", "open")
            + state_link("done", "done")
            + '</div>'
        )
    elif section == "open-questions":
        state_bar = (
            '<div class="filter-bar">'
            + state_link("", "all questions")
            + state_link("unanswered", "unanswered")
            + state_link("answered", "answered")
            + '</div>'
        )

    if not rows:
        body = (
            styles + '<h2>Agent Sections</h2>' + section_bar + state_bar
            + '<p class="muted">No entries match this filter.</p>'
        )
        return _base("Agent Sections", body, active="agent-sections")

    # Render each row
    items_html = []
    for r in rows:
        entry = _parse_entry(r.get("entry_json") or "")
        sec = r["section"] or ""
        text = entry.get("text", "") or ""
        done = bool(entry.get("done"))
        answered = bool(entry.get("answered"))
        priority = entry.get("priority")
        refs = entry.get("refs") or []
        if isinstance(refs, str):
            refs = [refs]

        # Priority indicator (todo only)
        pri_html = ""
        if priority and sec == "todo":
            cls = {
                "high": "priority-h", "medium": "priority-m", "low": "priority-l",
            }.get(priority, "priority-l")
            pri_html = f' <span class="{cls}">[{priority}]</span>'

        # Refs
        refs_html = ""
        if refs:
            refs_html = "<div style='margin-top:0.3rem'>" + "".join(
                f'<span class="ref-pill">{html.escape(str(ref))}</span>'
                for ref in refs
            ) + "</div>"

        # State marker for questions
        state_indicator = ""
        if sec == "open-questions":
            state_indicator = (
                ' <span style="color:#3ea866;font-weight:600">[answered]</span>'
                if answered
                else ' <span style="color:#e94560;font-weight:600">[unanswered]</span>'
            )

        session_link = (
            f'<a href="/agent-sessions/{r["session_id"]}" '
            f'style="color:#7ec7ff">#{r["session_id"]}</a>'
            if r.get("session_id") else "—"
        )
        session_title = html.escape((r.get("session_title") or "")[:35])
        proj = (
            f'<a href="/projects/{html.escape(r["project_slug"])}" '
            f'style="color:#7ec7ff">{html.escape(r["project_slug"])}</a>'
            if r.get("project_slug") else ""
        )

        item_class = "sec-item"
        if done:
            item_class += " done"

        items_html.append(
            f'<div class="{item_class}">'
            f'  <div class="sec-side">'
            f'    <div>{_section_pill(sec)}{pri_html}</div>'
            f'    <div>{session_link} {session_title}</div>'
            f'    <div>{proj}</div>'
            f'    <div class="muted" style="font-family:ui-monospace,monospace;font-size:0.7rem">'
            f'      {html.escape((r.get("updated_at") or "")[:19])}</div>'
            f'  </div>'
            f'  <div class="sec-body">{html.escape(text)}{state_indicator}{refs_html}</div>'
            f'</div>'
        )

    body = (
        styles
        + '<h2>Agent Sections</h2>'
        + '<p class="muted" style="margin-bottom:0.8rem">'
        + f'{len(rows)} entrie(s) matching. Findings / todos / open '
        + 'questions written by agents via '
        + '<code>mcp__templedb__templedb_agent_*</code> tools. '
        + 'Cross-session view — dig into '
        + '<a href="/agent-sessions" style="color:#7ec7ff">/agent-sessions</a> '
        + 'for the conversation each was written in.</p>'
        + section_bar
        + state_bar
        + "".join(items_html)
    )
    return _base("Agent Sections", body, active="agent-sections")
