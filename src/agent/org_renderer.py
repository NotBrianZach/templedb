"""Org-mode renderer for Temple Agent.

Converts session state (messages, events, notes) into Org-formatted text.
This runs server-side so Emacs receives pre-formatted Org content.
"""
from datetime import datetime


def render_session(session, messages, events_by_run=None, notes=None):
    """Render a full session as an Org document.

    Args:
        session: Session dict from store.
        messages: List of message dicts from store.
        events_by_run: Optional dict of {run_id: [events]} for tool activity.
        notes: Optional session notes dict.

    Returns:
        Complete Org document string.
    """
    lines = []

    # Header
    lines.append(f"#+TITLE: Temple Agent")
    lines.append(f"#+TDB_SESSION_ID: {session.get('id', '')}")
    project = session.get('project_slug') or ''
    if not project and session.get('project_id'):
        project = f"(project {session['project_id']})"
    lines.append(f"#+TDB_PROJECT: {project}")
    lines.append(f"#+TDB_STATUS: {session.get('status', 'created')}")
    lines.append(f"#+TDB_PROVIDER: {session.get('provider_name', '')}")
    if session.get('model'):
        lines.append(f"#+TDB_MODEL: {session['model']}")
    lines.append("")

    # Now section
    lines.append("* Now")
    lines.append("")
    status = session.get('status', 'created')
    now_text = {
        'created': 'Ready',
        'running': 'Working...',
        'waiting': 'Ready',
        'interrupted': 'Interrupted',
        'completed': 'Session complete',
        'failed': 'Failed',
        'cancelled': 'Cancelled',
    }.get(status, status)
    lines.append(now_text)
    lines.append("")

    # Goal section
    lines.append("* Goal")
    lines.append("")
    if notes and notes.get('goal_org'):
        lines.append(notes['goal_org'])
    lines.append("")

    # Context section
    lines.append("* Context")
    lines.append("")
    if project:
        lines.append(f"- Current project: {project}")
    if session.get('provider_name'):
        lines.append(f"- Provider: {session['provider_name']}")
    if session.get('model'):
        lines.append(f"- Model: {session['model']}")
    lines.append("")

    # Conversation section
    lines.append("* Conversation")
    lines.append("")
    if messages:
        for msg in messages:
            lines.extend(_render_message(msg, events_by_run))
    lines.append("")

    # Next Prompt section
    lines.append("* Next Prompt")
    lines.append("")
    lines.append("")

    # Notes section
    lines.append("* Notes")
    lines.append("")
    if notes and notes.get('notes_org'):
        lines.append(notes['notes_org'])
    lines.append("")

    # Scratch section
    lines.append("* Scratch")
    lines.append("")
    if notes and notes.get('scratch_org'):
        lines.append(notes['scratch_org'])
    lines.append("")

    return "\n".join(lines)


def _render_message(msg, events_by_run=None):
    """Render a single message as Org heading lines."""
    lines = []
    role = msg.get('role', 'unknown')
    text = msg.get('content_text', '')
    run_id = msg.get('run_id')

    # Skip empty assistant messages (streaming placeholders)
    if role == 'assistant' and not text.strip():
        return lines

    heading = _role_heading(role)
    lines.append(f"** {heading}")
    lines.append("")

    if text.strip():
        # Indent content for readability but keep it as Org body
        lines.append(text)
        lines.append("")

    # Insert tool events for this message's run (if assistant)
    if role == 'assistant' and run_id and events_by_run:
        run_events = events_by_run.get(run_id, [])
        for event in run_events:
            event_type = event.get('event_type', '')
            summary = event.get('summary', '')
            if event_type.startswith('tool.'):
                status = _tool_status(event_type)
                lines.append(f"*** {status} {summary}")
        if run_events:
            lines.append("")

    return lines


def _role_heading(role):
    """Convert a message role to an Org heading prefix."""
    return {
        'user': 'User',
        'assistant': 'Assistant',
        'system': 'System',
        'tool': 'Tool',
        'templedb': 'TempleDB',
    }.get(role, role.capitalize())


def _tool_status(event_type):
    """Convert event type to Org TODO-style status."""
    return {
        'tool.started': 'RUNNING',
        'tool.completed': 'DONE',
        'tool.failed': 'FAILED',
    }.get(event_type, '')


def render_events_org(events):
    """Render a list of events as folded Org headings.

    Used for appending tool activity to the buffer incrementally.
    """
    lines = []
    for event in events:
        event_type = event.get('event_type', event.get('type', ''))
        summary = event.get('summary', '')

        if event_type.startswith('tool.'):
            status = _tool_status(event_type)
            lines.append(f"** {status} {summary}")
        elif event_type == 'run.started':
            lines.append(f"** RUNNING {summary}")
        elif event_type == 'run.completed':
            pass  # Don't add heading for run completion
        elif event_type == 'run.failed':
            lines.append(f"** FAILED {summary}")

    return "\n".join(lines)


def render_session_list(sessions):
    """Render session list as Org table."""
    if not sessions:
        return "No sessions found.\n"

    lines = []
    lines.append("| ID | Title | Provider | Status | Updated |")
    lines.append("|----+-------+----------+--------+---------|")
    for s in sessions:
        title = (s.get('title') or '(untitled)')[:40]
        lines.append(
            f"| {s['id']} | {title} | {s.get('provider_name', '')} "
            f"| {s.get('status', '')} | {_short_time(s.get('updated_at', ''))} |"
        )
    lines.append("")
    return "\n".join(lines)


def _short_time(timestamp_str):
    """Shorten a timestamp for display."""
    if not timestamp_str:
        return ""
    try:
        dt = datetime.fromisoformat(timestamp_str)
        now = datetime.utcnow()
        if dt.date() == now.date():
            return dt.strftime("%H:%M")
        return dt.strftime("%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(timestamp_str)[:16]
