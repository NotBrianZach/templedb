"""TempleDB GUI — Agent Work Log (read-only dashboard).

Rolls up per-run stats from agent_work_log:
  cost_usd, input/output tokens, duration_ms, num_turns
  tools_used, files_read/modified, commands_run
  user_message + assistant_response_preview + summary

Route:
  GET /agent-work-log     Filterable table + aggregate totals

The CLI equivalent is `templedb ai agent log`; this page adds a
sortable/filterable view and running-total callouts that the CLI
doesn't currently expose.
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


_STATUS_COLOR = {
    "completed": "#3ea866",
    "failed":    "#e94560",
    "interrupted": "#a06060",
    "cancelled": "#808080",
}


def _pill(status: str) -> str:
    color = _STATUS_COLOR.get((status or "").lower(), "#8080a0")
    return (
        f'<span style="display:inline-block;padding:0 6px;border-radius:3px;'
        f'font-size:0.7rem;font-weight:600;color:{color};'
        f'border:1px solid {color};background:transparent">'
        f'{html.escape(status or "?")}</span>'
    )


def _fmt_dollars(v) -> str:
    if v is None:
        return '<span class="muted">—</span>'
    if v < 0.001:
        return f'<span class="muted" style="font-family:ui-monospace,monospace">${v:.5f}</span>'
    return f'<span style="font-family:ui-monospace,monospace">${v:.4f}</span>'


def _fmt_int(v) -> str:
    if v is None:
        return '<span class="muted">—</span>'
    if v > 1_000_000:
        return f'<span style="font-family:ui-monospace,monospace">{v/1_000_000:.1f}M</span>'
    if v > 1_000:
        return f'<span style="font-family:ui-monospace,monospace">{v/1_000:.1f}k</span>'
    return f'<span style="font-family:ui-monospace,monospace">{v}</span>'


def _fmt_duration_ms(ms) -> str:
    if ms is None:
        return '<span class="muted">—</span>'
    s = ms / 1000
    if s < 60:
        return f'<span style="font-family:ui-monospace,monospace">{s:.1f}s</span>'
    m = s / 60
    if m < 60:
        return f'<span style="font-family:ui-monospace,monospace">{int(m)}m{int(s % 60)}s</span>'
    h = m / 60
    return f'<span style="font-family:ui-monospace,monospace">{int(h)}h{int(m % 60)}m</span>'


def _parse_list_field(raw) -> list:
    """tools_used / files_read etc. are stored either as JSON arrays or
    as comma-separated strings — handle both."""
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        return list(raw)
    s = str(raw).strip()
    if s.startswith("["):
        try:
            v = json.loads(s)
            if isinstance(v, list):
                return v
        except (ValueError, TypeError):
            pass
    return [p.strip() for p in s.split(",") if p.strip()]


@router.get("/agent-work-log", response_class=HTMLResponse)
def agent_work_log_list(project: str = "", status: str = "", limit: int = 200):
    where, params = [], []
    if project:
        where.append("p.slug = ?")
        params.append(project)
    if status:
        where.append("w.status = ?")
        params.append(status)
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    rows = query_all(
        f"""
        SELECT w.*, p.slug AS project_slug, s.title AS session_title
          FROM agent_work_log w
          LEFT JOIN projects p ON p.id = w.project_id
          LEFT JOIN agent_sessions s ON s.id = w.session_id
        {where_sql}
         ORDER BY w.id DESC
         LIMIT ?
        """,
        (*params, limit),
    )
    rows = [dict(r) for r in rows]

    # Aggregates over the filtered result set. Where cost/tokens are NULL
    # we skip. Uses list, not SQL SUM, so filtered-set aggregates match.
    total_cost = sum((r["cost_usd"] or 0) for r in rows)
    total_in_tok = sum((r["input_tokens"] or 0) for r in rows)
    total_out_tok = sum((r["output_tokens"] or 0) for r in rows)
    total_dur_ms = sum((r["duration_ms"] or 0) for r in rows)
    total_turns = sum((r["num_turns"] or 0) for r in rows)
    n = len(rows)

    # Tools histogram — the most common signal of "what has the agent
    # actually been doing this week"
    tool_counter: dict = {}
    for r in rows:
        for t in _parse_list_field(r.get("tools_used")):
            tool_counter[t] = tool_counter.get(t, 0) + 1
    top_tools = sorted(tool_counter.items(), key=lambda kv: -kv[1])[:8]

    # Distinct projects/statuses for filter chips
    proj_rows = query_all(
        """
        SELECT p.slug AS slug, COUNT(*) AS c
          FROM agent_work_log w
          LEFT JOIN projects p ON p.id = w.project_id
         WHERE p.slug IS NOT NULL
         GROUP BY p.slug ORDER BY c DESC
        """, (),
    )
    status_rows = query_all(
        "SELECT status, COUNT(*) c FROM agent_work_log GROUP BY status ORDER BY c DESC",
        (),
    )

    styles = """
    <style>
      .stat-cards {
        display:flex; gap:0.6rem; flex-wrap:wrap; margin-bottom:1rem;
      }
      .stat-card {
        background:#13131f; border:1px solid #1e1e3a; border-radius:5px;
        padding:0.6rem 0.9rem; min-width:8rem;
      }
      .stat-card .stat-label {
        color:#8080a0; font-size:0.75rem; text-transform:uppercase;
        letter-spacing:0.5px; margin-bottom:0.15rem;
      }
      .stat-card .stat-value {
        color:#d0d0e8; font-size:1.15rem; font-weight:600;
        font-family:ui-monospace,monospace;
      }
      .filter-bar { margin-bottom:0.9rem; display:flex; gap:0.4rem; flex-wrap:wrap; font-size:0.83rem; }
      .filter-bar a {
        padding:2px 8px; border-radius:3px; text-decoration:none;
        color:#a0a0c0; background:#13131f; border:1px solid #1e1e3a;
      }
      .filter-bar a.on { color:#e94560; border-color:#e94560; }
      .filter-bar a:hover { color:#e94560; }
      .wl-table { border-collapse:collapse; width:100%; font-size:0.83rem; }
      .wl-table th {
        text-align:left; color:#8080a0; font-weight:500; padding:0.35rem 0.55rem;
        border-bottom:1px solid #1e1e3a; white-space:nowrap;
      }
      .wl-table td {
        padding:0.5rem 0.55rem; border-bottom:1px solid #1e1e3a;
        vertical-align:top;
      }
      .wl-table tr:hover { background:#13131f; }
      .wl-table a { color:#7ec7ff; text-decoration:none; }
      .wl-table a:hover { text-decoration:underline; }
      .msg-preview { color:#d0d0e8; max-width:22rem; }
      .msg-preview .um { display:block; font-weight:500; }
      .msg-preview .sm { display:block; color:#a0a0c0; font-size:0.78rem;
                         margin-top:0.15rem;
                         white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
      .tool-pill {
        display:inline-block; padding:1px 5px; border-radius:3px;
        background:#1a1a2e; color:#a0a0c0; font-size:0.7rem;
        font-family:ui-monospace,monospace; margin-right:0.25rem;
      }
    </style>
    """

    def flink(kind, value, label):
        current = {"project": project, "status": status}[kind]
        parts = []
        if kind == "project" and value != current:
            parts.append(f"project={value}")
        elif kind == "project" and value == current:
            pass  # toggle off
        else:
            if project:
                parts.append(f"project={project}")
        if kind == "status" and value != current:
            parts.append(f"status={value}")
        elif kind == "status" and value == current:
            pass
        else:
            if status:
                parts.append(f"status={status}")
        qs = "&".join(parts)
        href = "/agent-work-log" + (("?" + qs) if qs else "")
        on = "on" if value == current else ""
        return f'<a class="{on}" href="{href}">{label}</a>'

    proj_bar = (
        '<div class="filter-bar">'
        + f'<a class="{"on" if not project else ""}" href="/agent-work-log{("?status=" + status) if status else ""}">all projects</a>'
        + "".join(
            flink("project", r["slug"], f'{r["slug"]} ({r["c"]})')
            for r in proj_rows
        )
        + '</div>'
    )
    status_bar = (
        '<div class="filter-bar">'
        + f'<a class="{"on" if not status else ""}" href="/agent-work-log{("?project=" + project) if project else ""}">all status</a>'
        + "".join(
            flink("status", r["status"] or "", f'{r["status"] or "?"} ({r["c"]})')
            for r in status_rows
        )
        + '</div>'
    )

    stat_cards = (
        '<div class="stat-cards">'
        + f'<div class="stat-card"><div class="stat-label">runs</div>'
        + f'<div class="stat-value">{n}</div></div>'
        + f'<div class="stat-card"><div class="stat-label">total cost</div>'
        + f'<div class="stat-value">${total_cost:.3f}</div></div>'
        + f'<div class="stat-card"><div class="stat-label">input tokens</div>'
        + f'<div class="stat-value">{total_in_tok/1000:.1f}k</div></div>'
        + f'<div class="stat-card"><div class="stat-label">output tokens</div>'
        + f'<div class="stat-value">{total_out_tok/1000:.1f}k</div></div>'
        + f'<div class="stat-card"><div class="stat-label">duration</div>'
        + f'<div class="stat-value">'
        + (f'{int(total_dur_ms/1000/60)}m' if total_dur_ms >= 60000 else f'{int(total_dur_ms/1000)}s')
        + f'</div></div>'
        + f'<div class="stat-card"><div class="stat-label">turns</div>'
        + f'<div class="stat-value">{total_turns}</div></div>'
        + '</div>'
    )

    tools_html = ""
    if top_tools:
        tools_html = (
            '<div style="margin-bottom:1rem;font-size:0.83rem;color:#a0a0c0">'
            'top tools: '
            + "".join(
                f'<span class="tool-pill">{html.escape(name)} ×{cnt}</span>'
                for name, cnt in top_tools
            )
            + '</div>'
        )

    if not rows:
        body = (
            styles + '<h2>Agent Work Log</h2>' + proj_bar + status_bar
            + '<p class="muted">No matching work-log entries.</p>'
        )
        return _base("Agent Work Log", body, active="agent-work-log")

    row_html = []
    for r in rows:
        um = (r.get("user_message") or "").strip()
        sm = (r.get("summary") or "").strip()
        row_html.append(
            f'<tr>'
            f'<td><a href="/agent-sessions/{r["session_id"]}/runs/{r["run_id"]}">'
            f'#{r["run_id"]}</a>'
            f'<div class="muted" style="font-size:0.7rem">sess {r["session_id"]}</div></td>'
            f'<td>{_pill(r["status"])}</td>'
            f'<td class="msg-preview">'
            f'<span class="um">{html.escape(um[:80])}{"…" if len(um) > 80 else ""}</span>'
            f'<span class="sm">{html.escape(sm[:100])}</span>'
            f'</td>'
            f'<td>{"<a href=\"/projects/" + html.escape(r["project_slug"] or "") + "\">" + html.escape(r["project_slug"]) + "</a>" if r.get("project_slug") else "—"}</td>'
            f'<td style="text-align:right">{_fmt_dollars(r["cost_usd"])}</td>'
            f'<td style="text-align:right">{_fmt_int(r["input_tokens"])}</td>'
            f'<td style="text-align:right">{_fmt_int(r["output_tokens"])}</td>'
            f'<td style="text-align:right">{_fmt_duration_ms(r["duration_ms"])}</td>'
            f'<td style="text-align:right">{_fmt_int(r["num_turns"])}</td>'
            f'<td class="muted" style="font-family:ui-monospace,monospace;font-size:0.75rem">{html.escape((r.get("created_at") or "")[:19])}</td>'
            f'</tr>'
        )

    body = (
        styles
        + '<h2>Agent Work Log</h2>'
        + '<p class="muted" style="margin-bottom:0.9rem">'
        + f'{n} run(s), newest first. NULL cost/token fields are older '
        + 'runs from before the provider started reporting them; treat '
        + 'the totals as a lower bound.</p>'
        + proj_bar
        + status_bar
        + stat_cards
        + tools_html
        + '<table class="wl-table">'
        + '<thead><tr>'
        + '<th>run</th><th>status</th><th>message / summary</th>'
        + '<th>project</th>'
        + '<th style="text-align:right">$</th>'
        + '<th style="text-align:right">in</th>'
        + '<th style="text-align:right">out</th>'
        + '<th style="text-align:right">dur</th>'
        + '<th style="text-align:right">turns</th>'
        + '<th>created</th></tr></thead>'
        + '<tbody>' + "".join(row_html) + '</tbody></table>'
    )
    return _base("Agent Work Log", body, active="agent-work-log")
