"""AgentStore - database layer for Temple Agent.

Single writer pattern: all agent table mutations go through this module.
Uses db_utils for connection pooling and transactions.
"""
import json
import logging
import sqlite3
import time
import uuid
from datetime import datetime

from db_utils import query_one, query_all, execute, transaction
from agent.events import (
    SESSION_CREATED, RUN_STATUS_RUNNING, RUN_STATUS_COMPLETED,
    RUN_STATUS_INTERRUPTED, RUN_STATUS_FAILED, RUN_STATUS_CANCELLED,
)

_logger = logging.getLogger(__name__)


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _retry_on_lock(fn, max_retries=3, base_delay=0.5):
    """Retry a DB operation on OperationalError (database locked).

    Uses exponential backoff. Prevents agent sessions from dying
    when the GUI or a parallel templedb process holds a brief write lock.
    """
    for attempt in range(max_retries + 1):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower() or attempt == max_retries:
                raise
            delay = base_delay * (2 ** attempt)
            _logger.warning(f"DB locked (attempt {attempt + 1}/{max_retries + 1}), retrying in {delay:.1f}s")
            time.sleep(delay)


# --- Providers ---

def get_provider(name):
    """Get provider by name."""
    return query_one("SELECT * FROM agent_providers WHERE name = ?", (name,))


def get_provider_by_id(provider_id):
    """Get provider by ID."""
    return query_one("SELECT * FROM agent_providers WHERE id = ?", (provider_id,))


def list_providers(enabled_only=True):
    """List all providers."""
    if enabled_only:
        return query_all("SELECT * FROM agent_providers WHERE enabled = 1 ORDER BY name")
    return query_all("SELECT * FROM agent_providers ORDER BY name")


# --- Sessions ---

def create_session(provider_name, project_id=None, title=None, model=None):
    """Create a new agent session. Returns the full session row."""
    provider = get_provider(provider_name)
    if not provider:
        raise ValueError(f"Unknown provider: {provider_name}")

    session_uuid = str(uuid.uuid4())
    now = _now()

    session_id = execute(
        """INSERT INTO agent_sessions
           (session_uuid, project_id, provider_id, title, status, model, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_uuid, project_id, provider["id"], title, SESSION_CREATED, model, now, now),
    )
    return get_session(session_id)


def get_session(session_id):
    """Get session by ID with provider info."""
    return query_one(
        """SELECT s.*, p.name as provider_name, p.provider_kind, p.executable
           FROM agent_sessions s
           JOIN agent_providers p ON s.provider_id = p.id
           WHERE s.id = ?""",
        (session_id,),
    )


def get_session_by_uuid(session_uuid):
    """Get session by UUID."""
    return query_one(
        """SELECT s.*, p.name as provider_name, p.provider_kind, p.executable
           FROM agent_sessions s
           JOIN agent_providers p ON s.provider_id = p.id
           WHERE s.session_uuid = ?""",
        (session_uuid,),
    )


def list_sessions(project_id=None, status=None, limit=50,
                  provider_id=None, min_msgs=0, newer_than_days=None):
    """List sessions with optional filters.

    Each result row includes msg_count and pending_asks (computed
    via LEFT JOINs). Filters:
      - project_id / status / provider_id: exact match
      - min_msgs: only rows with COALESCE(msg_count,0) >= N
      - newer_than_days: only rows with updated_at within last N days
    """
    sql = """SELECT s.*, p.name as provider_name,
                    COALESCE(m.msg_count, 0) as msg_count,
                    COALESCE(a.pending_asks, 0) as pending_asks
             FROM agent_sessions s
             JOIN agent_providers p ON s.provider_id = p.id
             LEFT JOIN (SELECT session_id, COUNT(*) as msg_count
                          FROM agent_messages GROUP BY session_id) m
                    ON m.session_id = s.id
             LEFT JOIN (SELECT session_id, COUNT(*) as pending_asks
                          FROM agent_pending_asks WHERE status='pending'
                          GROUP BY session_id) a
                    ON a.session_id = s.id
             WHERE 1=1"""
    params = []
    if project_id is not None:
        sql += " AND s.project_id = ?"
        params.append(project_id)
    if status:
        sql += " AND s.status = ?"
        params.append(status)
    if provider_id is not None:
        sql += " AND s.provider_id = ?"
        params.append(provider_id)
    if min_msgs and min_msgs > 0:
        sql += " AND COALESCE(m.msg_count, 0) >= ?"
        params.append(min_msgs)
    if newer_than_days and newer_than_days > 0:
        sql += " AND datetime(s.updated_at) >= datetime('now', ?)"
        params.append(f"-{int(newer_than_days)} days")
    sql += " ORDER BY s.updated_at DESC LIMIT ?"
    params.append(limit)
    return query_all(sql, tuple(params))


def update_session_status(session_id, status):
    """Update session status. Retries on lock to avoid losing state transitions."""
    _retry_on_lock(lambda: execute(
        "UPDATE agent_sessions SET status = ?, updated_at = ? WHERE id = ?",
        (status, _now(), session_id),
    ))


def update_session_external_id(session_id, external_session_id):
    """Store the provider's external session ID."""
    execute(
        "UPDATE agent_sessions SET external_session_id = ?, updated_at = ? WHERE id = ?",
        (external_session_id, _now(), session_id),
    )


def update_session_title(session_id, title):
    """Update session title (e.g., auto-generated from first message)."""
    execute(
        "UPDATE agent_sessions SET title = ?, updated_at = ? WHERE id = ?",
        (title, _now(), session_id),
    )


# --- Runs ---

def create_run(session_id):
    """Create a new run within a session. Returns the full run row."""
    now = _now()
    run_id = execute(
        """INSERT INTO agent_runs (session_id, status, started_at)
           VALUES (?, ?, ?)""",
        (session_id, RUN_STATUS_RUNNING, now),
    )
    return query_one("SELECT * FROM agent_runs WHERE id = ?", (run_id,))


def complete_run(run_id, status=RUN_STATUS_COMPLETED, error_text=None):
    """Mark a run as completed/failed/interrupted. Retries on lock."""
    _retry_on_lock(lambda: execute(
        "UPDATE agent_runs SET status = ?, completed_at = ?, error_text = ? WHERE id = ?",
        (status, _now(), error_text, run_id),
    ))


def get_run(run_id):
    """Get run by ID."""
    return query_one("SELECT * FROM agent_runs WHERE id = ?", (run_id,))


def get_latest_run(session_id):
    """Get the most recent run for a session."""
    return query_one(
        "SELECT * FROM agent_runs WHERE session_id = ? ORDER BY id DESC LIMIT 1",
        (session_id,),
    )


def list_runs(session_id):
    """List all runs for a session."""
    return query_all(
        "SELECT * FROM agent_runs WHERE session_id = ? ORDER BY id",
        (session_id,),
    )


# --- Messages ---

def add_message(session_id, role, content_text, run_id=None, content_format="org"):
    """Add a message to a session. Auto-assigns sequence number. Returns message row."""
    # Get next sequence number
    row = query_one(
        "SELECT COALESCE(MAX(sequence_number), 0) + 1 as next_seq FROM agent_messages WHERE session_id = ?",
        (session_id,),
    )
    seq = row["next_seq"]
    now = _now()

    msg_id = execute(
        """INSERT INTO agent_messages
           (session_id, run_id, sequence_number, role, content_text, content_format, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, run_id, seq, role, content_text, content_format, now, now),
    )
    return query_one("SELECT * FROM agent_messages WHERE id = ?", (msg_id,))


def update_message_content(message_id, content_text):
    """Update message content (for streaming accumulation).

    Retries on DB lock since this is called frequently during streaming
    and is most likely to collide with GUI or parallel templedb writes.
    """
    _retry_on_lock(lambda: execute(
        "UPDATE agent_messages SET content_text = ?, updated_at = ? WHERE id = ?",
        (content_text, _now(), message_id),
    ))


def get_messages(session_id, limit=200):
    """Get messages for a session in order."""
    return query_all(
        """SELECT * FROM agent_messages
           WHERE session_id = ?
           ORDER BY sequence_number
           LIMIT ?""",
        (session_id, limit),
    )


def get_message(message_id):
    """Get a single message by ID."""
    return query_one("SELECT * FROM agent_messages WHERE id = ?", (message_id,))


# --- Events ---

def add_event(run_id, event_type, summary=None, payload=None, raw_payload=None):
    """Add an event to a run. Auto-assigns sequence number. Returns event row.

    Retries on DB lock since events stream in rapidly during agent runs.

    Phase 3 side effect: for tool.* events, also updates the tool_calls
    table (migration 094). Previously tool_calls was populated only via
    the migration's one-time backfill; this closes the extraction loop
    so new tool invocations become first-class span rows without a
    periodic re-ingest. See docs/ENTITY_GRAPH_DESIGN.md for the
    span-as-first-class-relation framing.

    Failures inside the tool_calls path are swallowed — they must not
    break event ingestion. The graph will just be missing a row until
    the next `templedb ingest agent` sweep.
    """
    def _do():
        row = query_one("SELECT last_event_sequence FROM agent_runs WHERE id = ?", (run_id,))
        if not row:
            raise ValueError(f"Run {run_id} not found")

        seq = row["last_event_sequence"] + 1

        payload_json = json.dumps(payload) if payload else None
        raw_json = json.dumps(raw_payload) if raw_payload else None

        event_id = execute(
            """INSERT INTO agent_events
               (run_id, sequence_number, event_type, summary, payload_json, raw_payload_json, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (run_id, seq, event_type, summary, payload_json, raw_json, _now()),
        )

        # Update run's sequence counter
        execute(
            "UPDATE agent_runs SET last_event_sequence = ? WHERE id = ?",
            (seq, run_id),
            commit=False,
        )

        # Best-effort tool_calls integration.
        try:
            if event_type == 'tool.started':
                _record_tool_call_started(run_id, event_id, payload)
            elif event_type == 'tool.completed':
                _record_tool_call_completed(run_id)
            elif event_type == 'tool.failed':
                _record_tool_call_completed(run_id, failed=True)
        except Exception:
            # Non-fatal — event write is the primary op.
            pass

        return query_one("SELECT * FROM agent_events WHERE id = ?", (event_id,))

    return _retry_on_lock(_do)


def _record_tool_call_started(run_id, event_id, payload):
    """Insert a tool_calls row with status='running' when tool.started
    fires. Called from add_event as a side effect."""
    tool_name = (payload or {}).get('tool_name', 'unknown')
    run = query_one(
        "SELECT session_id FROM agent_runs WHERE id = ?", (run_id,),
    )
    session_id = run['session_id'] if run else None
    execute(
        """INSERT INTO tool_calls
               (run_id, session_id, tool_name, started_at,
                status, source_event_id)
             VALUES (?, ?, ?, datetime('now'), 'running', ?)""",
        (run_id, session_id, tool_name, event_id),
    )


def _record_tool_call_completed(run_id, failed=False):
    """Close out the most recent 'running' tool_call for this run.

    Heuristic: tool.completed doesn't carry which specific tool.started
    it closes (payload is minimal per the observed live data), so
    'most recent running in this run' is the honest approximation.
    Correct in practice for sequential tool invocations, which is
    what Claude Code produces."""
    execute(
        """UPDATE tool_calls
              SET status = ?,
                  finished_at = datetime('now')
            WHERE id = (SELECT id FROM tool_calls
                         WHERE run_id = ? AND status = 'running'
                         ORDER BY started_at DESC LIMIT 1)""",
        ('failed' if failed else 'completed', run_id),
    )


def get_events_since(run_id, since_sequence=0, limit=500):
    """Get events for a run after a given sequence number."""
    return query_all(
        """SELECT * FROM agent_events
           WHERE run_id = ? AND sequence_number > ?
           ORDER BY sequence_number
           LIMIT ?""",
        (run_id, since_sequence, limit),
    )


def get_all_run_events(run_id):
    """Get all events for a run."""
    return query_all(
        "SELECT * FROM agent_events WHERE run_id = ? ORDER BY sequence_number",
        (run_id,),
    )


# --- Session Notes ---

def get_notes(session_id):
    """Get session notes."""
    return query_one("SELECT * FROM agent_session_notes WHERE session_id = ?", (session_id,))


def set_notes(session_id, goal_org=None, notes_org=None, scratch_org=None):
    """Create or update session notes."""
    existing = get_notes(session_id)
    now = _now()
    if existing:
        parts = []
        params = []
        if goal_org is not None:
            parts.append("goal_org = ?")
            params.append(goal_org)
        if notes_org is not None:
            parts.append("notes_org = ?")
            params.append(notes_org)
        if scratch_org is not None:
            parts.append("scratch_org = ?")
            params.append(scratch_org)
        if parts:
            parts.append("updated_at = ?")
            params.append(now)
            params.append(session_id)
            execute(f"UPDATE agent_session_notes SET {', '.join(parts)} WHERE session_id = ?",
                    tuple(params))
    else:
        execute(
            """INSERT INTO agent_session_notes (session_id, goal_org, notes_org, scratch_org, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, goal_org, notes_org, scratch_org, now),
        )
    return get_notes(session_id)


# --- Session Sections (Phase D: agent-writable sections) ---
# Entries are stored one row per (session, section, entry_id) with the
# entry body as a JSON blob. get_sections rehydrates the whole graph
# into a dict keyed by section name → list of entry dicts, ordered by
# creation time. This matches the shape Emacs expects on session.open.

def get_sections(session_id):
    """Return sections state as {section_name: [entry_dict, ...]}.
    Entries are ordered by insertion time (created_at, then id)."""
    rows = query_all(
        """SELECT section, entry_id, entry_json, created_at
             FROM agent_session_sections
            WHERE session_id = ?
            ORDER BY created_at, id""",
        (session_id,),
    )
    out = {}
    for row in rows:
        try:
            entry = json.loads(row["entry_json"])
        except (ValueError, TypeError):
            entry = {}
        entry.setdefault("id", row["entry_id"])
        out.setdefault(row["section"], []).append(entry)
    return out


def search_sections_across_sessions(query, section=None,
                                    project_slug=None, limit=50):
    """Substring-search across every session's agent_session_sections.
    Returns a list of {session_id, project_slug, section, entry_id,
    entry, created_at, session_created_at}, oldest-first.

    QUERY: substring matched against the entry's JSON text
        (case-insensitive). Empty QUERY returns most-recent entries.
    SECTION: if provided, restricts to that section id
        (findings/todo/open-questions/dynamic:NAME).
    PROJECT_SLUG: if provided, restricts to sessions whose project
        matches this slug. When None, includes every session.
    LIMIT: cap on rows returned.

    Backs `templedb_agent_search_findings` and friends. Read-only;
    no retry-on-lock needed."""
    where = ["1=1"]
    params = []
    if section:
        where.append("s.section = ?")
        params.append(section)
    if query:
        where.append("LOWER(s.entry_json) LIKE ?")
        params.append("%" + query.lower() + "%")
    if project_slug:
        where.append("p.slug = ?")
        params.append(project_slug)
    params.append(int(limit))
    rows = query_all(
        f"""SELECT s.session_id       AS session_id,
                   p.slug             AS project_slug,
                   s.section          AS section,
                   s.entry_id         AS entry_id,
                   s.entry_json       AS entry_json,
                   s.created_at       AS created_at,
                   sess.created_at    AS session_created_at
              FROM agent_session_sections s
              JOIN agent_sessions sess ON sess.id = s.session_id
              LEFT JOIN projects p ON p.id = sess.project_id
             WHERE {' AND '.join(where)}
             ORDER BY s.created_at DESC
             LIMIT ?""",
        tuple(params),
    )
    out = []
    for r in rows:
        try:
            entry = json.loads(r["entry_json"])
        except (ValueError, TypeError):
            entry = {}
        entry.setdefault("id", r["entry_id"])
        out.append({
            "session_id": r["session_id"],
            "project_slug": r["project_slug"],
            "section": r["section"],
            "entry_id": r["entry_id"],
            "entry": entry,
            "created_at": r["created_at"],
            "session_created_at": r["session_created_at"],
        })
    return out


def upsert_section_entry(session_id, section, entry_id, entry_dict):
    """Insert or replace the entry (session, section, entry_id).
    entry_dict is stored as JSON; :id is kept in the entry_id column
    for indexing but also mirrored inside the JSON payload for convenience.

    Wrapped in `_retry_on_lock` because MCP tools invoke this from
    subprocess writers that race against the agent service, the GUI, and
    any parallel templedb activity. Without retry, four rapid-fire
    `templedb_agent_*` calls from Claude reliably lose the lock race and
    return `database is locked` to the model."""
    payload = dict(entry_dict)
    payload["id"] = entry_id
    now = _now()
    _retry_on_lock(lambda: execute(
        """INSERT INTO agent_session_sections
               (session_id, section, entry_id, entry_json, created_at, updated_at)
             VALUES (?, ?, ?, ?, ?, ?)
             ON CONFLICT(session_id, section, entry_id) DO UPDATE SET
               entry_json = excluded.entry_json,
               updated_at = excluded.updated_at""",
        (session_id, section, entry_id, json.dumps(payload), now, now),
    ))
    return payload


def merge_section_entry(session_id, section, entry_id, updates):
    """Merge UPDATES (a dict) into the existing entry's JSON body.
    Creates the row if missing (with just the updates)."""
    row = query_one(
        """SELECT entry_json FROM agent_session_sections
            WHERE session_id = ? AND section = ? AND entry_id = ?""",
        (session_id, section, entry_id),
    )
    if row:
        try:
            existing = json.loads(row["entry_json"])
        except (ValueError, TypeError):
            existing = {}
    else:
        existing = {}
    existing.update(updates)
    # upsert_section_entry already retries.
    return upsert_section_entry(session_id, section, entry_id, existing)


def remove_section_entry(session_id, section, entry_id):
    """Delete a single entry. Returns rows affected."""
    return _retry_on_lock(lambda: execute(
        """DELETE FROM agent_session_sections
            WHERE session_id = ? AND section = ? AND entry_id = ?""",
        (session_id, section, entry_id),
    ))


def remove_section(session_id, section):
    """Delete every entry in SECTION. Used for dynamic-section clear."""
    return _retry_on_lock(lambda: execute(
        """DELETE FROM agent_session_sections
            WHERE session_id = ? AND section = ?""",
        (session_id, section),
    ))


# --- Pending events (MCP tool → agent-service poll → Emacs) ---
# Same transport idea as agent_pending_asks, but one-way. MCP tool
# inserts a row; the service's poll loop forwards it to Emacs and
# stamps dispatched_at. See migration 084 for the schema.

def create_pending_event(session_id, event_type, payload, summary=None):
    """Enqueue an outbound event for the agent's Emacs stdio.

    Wrapped in `_retry_on_lock` — see `upsert_section_entry` for
    rationale (MCP tools call these back-to-back from subprocess
    writers)."""
    _retry_on_lock(lambda: execute(
        """INSERT INTO agent_pending_events
               (session_id, event_type, payload_json, summary)
             VALUES (?, ?, ?, ?)""",
        (session_id, event_type, json.dumps(payload or {}), summary),
    ))


PENDING_EVENT_TTL_DAYS = 7
PENDING_EVENT_MAX_BATCH = 500


def undispatched_pending_events_for_session(session_id,
                                            ttl_days=PENDING_EVENT_TTL_DAYS,
                                            limit=PENDING_EVENT_MAX_BATCH):
    """Return not-yet-forwarded events for SESSION_ID, oldest first.

    TTL_DAYS: events older than this are treated as abandoned and
        skipped — happens when Emacs was closed for a long time and
        the poll loop would otherwise replay a week of stale
        `agent.section.*.add` events when the session reopens.
    LIMIT: cap on rows returned per call. The poll loop calls this
        repeatedly; capping the batch means one giant backlog
        doesn't stall the loop or blow memory. Newer events are
        preferred over ancient ones once the cap is reached.

    Related GC: `gc_dispatched_pending_events` (called on session
    close) hard-deletes dispatched rows; TTL only *hides* rows
    from the read path so they can be inspected in the DB for
    debugging."""
    return query_all(
        """SELECT id, event_type, payload_json, summary, created_at
             FROM agent_pending_events
            WHERE session_id = ?
              AND dispatched_at IS NULL
              AND created_at >= datetime('now', ?)
            ORDER BY id
            LIMIT ?""",
        (session_id, f"-{int(ttl_days)} days", int(limit)),
    )


def gc_dispatched_pending_events(session_id=None,
                                 older_than_days=PENDING_EVENT_TTL_DAYS):
    """Hard-delete dispatched pending events. Called on session close
    (per-session) and by admin GC (whole DB). Also sweeps
    undispatched events older than TTL — those are truly abandoned
    (Emacs never came back to consume them) and would otherwise
    bloat the table forever.

    Returns rows deleted."""
    if session_id is not None:
        return _retry_on_lock(lambda: execute(
            """DELETE FROM agent_pending_events
                WHERE session_id = ?
                  AND (dispatched_at IS NOT NULL
                       OR created_at < datetime('now', ?))""",
            (session_id, f"-{int(older_than_days)} days"),
        ))
    return _retry_on_lock(lambda: execute(
        """DELETE FROM agent_pending_events
            WHERE dispatched_at IS NOT NULL
               OR created_at < datetime('now', ?)""",
        (f"-{int(older_than_days)} days",),
    ))


def mark_pending_event_dispatched(event_id):
    """Called from the agent service poll loop after successful emit.
    Retry-wrapped because the poll loop runs continuously and would
    otherwise choke on a transient lock and re-emit the same event."""
    _retry_on_lock(lambda: execute(
        """UPDATE agent_pending_events SET dispatched_at = ?
            WHERE id = ?""",
        (_now(), event_id),
    ))


# --- User edits to agent state (reverse channel, migration 085) ---
# Logged when Emacs tells us the user removed / edited / promoted an
# agent-owned entry. Consumed on the next message.send so the agent
# sees a compact system note about what changed since its last turn.

def log_user_edit(session_id, section, entry_id, action, before=None):
    """Record one user edit to agent-owned state.
    action: 'removed' | 'marked_done' | 'edited' | 'promoted' | 'section_cleared'
    before: optional dict — snapshot of entry pre-edit, stored as JSON."""
    _retry_on_lock(lambda: execute(
        """INSERT INTO agent_user_edits
               (session_id, section, entry_id, action, before_json)
             VALUES (?, ?, ?, ?, ?)""",
        (session_id, section, entry_id, action,
         json.dumps(before) if before is not None else None),
    ))


def unconsumed_user_edits(session_id):
    """Return user edits for SESSION_ID that haven't been surfaced to
    the agent yet, oldest first."""
    return query_all(
        """SELECT id, section, entry_id, action, before_json, created_at
             FROM agent_user_edits
            WHERE session_id = ? AND consumed_at IS NULL
            ORDER BY id""",
        (session_id,),
    )


def mark_user_edits_consumed(session_id):
    """Stamp every unconsumed edit for SESSION_ID as consumed. Called
    right after we prepend the digest to a message.send content."""
    _retry_on_lock(lambda: execute(
        """UPDATE agent_user_edits SET consumed_at = ?
            WHERE session_id = ? AND consumed_at IS NULL""",
        (_now(), session_id),
    ))


# --- Work Log ---

def create_work_log_entry(session_id, run_id, status="completed", stats=None):
    """Auto-generate a work log entry from a completed run.

    Extracts the user message, tool usage summary, files touched,
    and assistant response preview from the run's events and messages.
    """
    session = get_session(session_id)
    if not session:
        return None

    stats = stats or {}
    messages = get_messages(session_id)
    events = get_all_run_events(run_id) if run_id else []

    # Find the user message that triggered this run
    user_msg = ""
    for m in reversed(messages):
        if m["role"] == "user":
            user_msg = m["content_text"]
            break

    # Find the assistant response
    assistant_text = ""
    for m in reversed(messages):
        if m["role"] == "assistant" and m.get("run_id") == run_id:
            assistant_text = m["content_text"]
            break
    if not assistant_text:
        # Fallback: last assistant message
        for m in reversed(messages):
            if m["role"] == "assistant" and m["content_text"]:
                assistant_text = m["content_text"]
                break

    # Extract tool usage from events
    tools_used = set()
    files_read = set()
    files_modified = set()
    commands_run = []

    for evt in events:
        etype = evt.get("event_type", "")
        payload = evt.get("payload_json")
        if payload:
            try:
                data = json.loads(payload) if isinstance(payload, str) else payload
            except (json.JSONDecodeError, TypeError):
                data = {}
        else:
            data = {}

        tool_name = data.get("tool_name", "")
        tool_input = data.get("tool_input", "")

        if etype in ("tool.started", "tool.completed"):
            if tool_name:
                tools_used.add(tool_name)

            if tool_name in ("Read", "read") and tool_input:
                # Extract file path from input
                for line in tool_input.split("\n"):
                    line = line.strip()
                    if line and not line.startswith("offset") and not line.startswith("limit"):
                        files_read.add(line)

            if tool_name in ("Edit", "edit", "Write", "write") and tool_input:
                path = tool_input.split("\n")[0].strip() if tool_input else ""
                if path and not path.startswith("-") and not path.startswith("+"):
                    files_modified.add(path)

            if tool_name in ("Bash", "bash") and tool_input:
                commands_run.append(tool_input[:200])

    # Build summary
    summary_parts = []
    if tools_used:
        summary_parts.append(f"Tools: {', '.join(sorted(tools_used))}")
    if files_modified:
        summary_parts.append(f"Modified: {', '.join(sorted(files_modified)[:5])}")
    if files_read:
        summary_parts.append(f"Read: {len(files_read)} files")
    summary = "; ".join(summary_parts) if summary_parts else "No tools used"

    now = _now()
    entry_id = execute(
        """INSERT INTO agent_work_log
           (session_id, run_id, project_id, user_message, summary,
            tools_used, files_read, files_modified, commands_run,
            assistant_response_preview, status,
            cost_usd, input_tokens, output_tokens, duration_ms, num_turns,
            created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (session_id, run_id, session.get("project_id"),
         user_msg[:1000], summary,
         json.dumps(sorted(tools_used)),
         json.dumps(sorted(files_read)[:20]),
         json.dumps(sorted(files_modified)[:20]),
         json.dumps(commands_run[:10]),
         assistant_text[:500], status,
         stats.get("cost_usd"), stats.get("input_tokens"),
         stats.get("output_tokens"), stats.get("duration_ms"),
         stats.get("turns"),
         now),
    )
    return entry_id


def get_work_log(project_id=None, limit=50):
    """Get work log entries, optionally filtered by project."""
    if project_id:
        return query_all(
            """SELECT wl.*, s.title as session_title, p.slug as project_slug
               FROM agent_work_log wl
               LEFT JOIN agent_sessions s ON wl.session_id = s.id
               LEFT JOIN projects p ON wl.project_id = p.id
               WHERE wl.project_id = ?
               ORDER BY wl.created_at DESC LIMIT ?""",
            (project_id, limit))
    return query_all(
        """SELECT wl.*, s.title as session_title, p.slug as project_slug
           FROM agent_work_log wl
           LEFT JOIN agent_sessions s ON wl.session_id = s.id
           LEFT JOIN projects p ON wl.project_id = p.id
           ORDER BY wl.created_at DESC LIMIT ?""",
        (limit,))


# --- Recovery ---

def recover_interrupted_sessions():
    """Find sessions that were running when the process died.
    Mark their runs as interrupted and sessions as interrupted.
    Returns list of recovered session IDs.
    """
    # Find runs that are still 'running' (orphaned by crash)
    orphaned_runs = query_all(
        "SELECT * FROM agent_runs WHERE status = ?",
        (RUN_STATUS_RUNNING,),
    )
    recovered = set()
    for run in orphaned_runs:
        complete_run(run["id"], status=RUN_STATUS_INTERRUPTED,
                     error_text="Process terminated unexpectedly")
        update_session_status(run["session_id"], "interrupted")
        recovered.add(run["session_id"])
    return list(recovered)


# --- Fork ---

def fork_session(source_session_id, new_provider_name=None):
    """Fork a session: create a new session with copies of all messages.

    Returns the new session row.
    """
    source = get_session(source_session_id)
    if not source:
        raise ValueError(f"Session {source_session_id} not found")

    provider_name = new_provider_name or source["provider_name"]
    new_session = create_session(
        provider_name,
        project_id=source.get("project_id"),
        title=f"Fork of: {source.get('title') or source_session_id}",
        model=source.get("model"),
    )

    # Copy messages
    messages = get_messages(source_session_id)
    now = _now()
    for msg in messages:
        row = query_one(
            "SELECT COALESCE(MAX(sequence_number), 0) + 1 as next_seq FROM agent_messages WHERE session_id = ?",
            (new_session["id"],),
        )
        execute(
            """INSERT INTO agent_messages
               (session_id, run_id, sequence_number, role, content_text, content_format, created_at, updated_at)
               VALUES (?, NULL, ?, ?, ?, ?, ?, ?)""",
            (new_session["id"], row["next_seq"], msg["role"],
             msg["content_text"], msg["content_format"], now, now),
        )

    # Copy notes
    source_notes = get_notes(source_session_id)
    if source_notes:
        set_notes(new_session["id"],
                  goal_org=source_notes.get("goal_org"),
                  notes_org=source_notes.get("notes_org"),
                  scratch_org=source_notes.get("scratch_org"))

    return get_session(new_session["id"])


# ── Pending asks (MCP bridge <→ Emacs round-trip) ─────────────────
# Written by templedb_launcher MCP tool handlers (out-of-process from the
# agent service), polled by the agent service which forwards new asks as
# events to Emacs, updated by the protocol server when Emacs responds.

def create_pending_ask(ask_id, session_id, kind, payload):
    """Insert a new pending ask. `payload` is a JSON-serializable dict."""
    execute(
        """INSERT INTO agent_pending_asks
           (ask_id, session_id, kind, payload, status, created_at)
           VALUES (?, ?, ?, ?, 'pending', ?)""",
        (ask_id, session_id, kind, json.dumps(payload), _now()),
    )


def get_pending_ask(ask_id):
    return query_one(
        "SELECT * FROM agent_pending_asks WHERE ask_id = ?", (ask_id,)
    )


def undispatched_asks_for_session(session_id):
    """Rows the agent service hasn't yet forwarded as events."""
    return query_all(
        """SELECT * FROM agent_pending_asks
           WHERE session_id = ? AND status = 'pending' AND dispatched_at IS NULL
           ORDER BY created_at""",
        (session_id,),
    )


def mark_ask_dispatched(ask_id):
    execute(
        "UPDATE agent_pending_asks SET dispatched_at = ? WHERE ask_id = ?",
        (_now(), ask_id),
    )


def record_ask_response(ask_id, response):
    """Emacs replied — MCP-side poller will see status='responded' and return."""
    execute(
        """UPDATE agent_pending_asks
           SET status = 'responded', response = ?, responded_at = ?
           WHERE ask_id = ? AND status = 'pending'""",
        (json.dumps(response), _now(), ask_id),
    )


# ---------------------------------------------------------------------------
# agent_notifications — outbound check-in queue (migration 106).
# ---------------------------------------------------------------------------

def create_notification(session_id, kind, subject, body_md,
                        pending_until=None, decision_default=None):
    """Insert a notification row. Returns the new id."""
    return _retry_on_lock(lambda: execute(
        """INSERT INTO agent_notifications
             (session_id, kind, subject, body_md,
              pending_until, decision_default)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (session_id, kind, subject, body_md or "",
         pending_until, decision_default),
    ))


def get_notification(notification_id):
    return query_one(
        "SELECT * FROM agent_notifications WHERE id = ?", (notification_id,)
    )


def list_notifications(limit=50, unsent_only=False):
    where = "WHERE sent_at IS NULL" if unsent_only else ""
    return query_all(
        f"""SELECT * FROM agent_notifications
            {where}
            ORDER BY id DESC LIMIT ?""",
        (limit,),
    )


def list_notifications_to_send(limit=50):
    """Unsent rows, oldest first. Used by the drain worker."""
    return query_all(
        """SELECT * FROM agent_notifications
           WHERE sent_at IS NULL
           ORDER BY created_at ASC LIMIT ?""",
        (limit,),
    )


def mark_notification_sent(notification_id):
    execute(
        """UPDATE agent_notifications
             SET sent_at = ?, send_error = NULL
           WHERE id = ?""",
        (_now(), notification_id),
    )


def mark_notification_send_failed(notification_id, error):
    execute(
        """UPDATE agent_notifications
             SET send_attempts = send_attempts + 1,
                 send_error = ?
           WHERE id = ?""",
        (str(error)[:2000], notification_id),
    )


def decide_notification(notification_id, decision):
    """Record a user decision on a decision-point row. Returns row count."""
    if decision not in ("approve", "deny", "timeout"):
        raise ValueError(f"invalid decision: {decision!r}")
    return execute(
        """UPDATE agent_notifications
             SET decision = ?, decided_at = ?
           WHERE id = ?
             AND pending_until IS NOT NULL
             AND decided_at IS NULL""",
        (decision, _now(), notification_id),
    )


# ---------------------------------------------------------------------------
# Fleet roster — one triage row per session, bucketed by who is blocked.
# ---------------------------------------------------------------------------

BUCKET_NEEDS_INPUT = "needs_input"
BUCKET_WORKING = "working"
BUCKET_ATTENTION = "attention"
BUCKET_DONE = "done"
BUCKET_IDLE = "idle"

# Render order. needs_input first because it is the only bucket where a
# session is literally stopped waiting on the human.
FLEET_BUCKET_ORDER = (
    BUCKET_NEEDS_INPUT,
    BUCKET_WORKING,
    BUCKET_ATTENTION,
    BUCKET_DONE,
    BUCKET_IDLE,
)

# A session whose row says 'running' but whose newest event is older than
# this has almost certainly lost its provider: the Emacs buffer was killed,
# `stop-stale` reaped the serve process, or `claude` died without emitting a
# terminal event. Nothing rewrites the status in those cases, so without a
# heartbeat the roster would report work that nobody is doing.
FLEET_STALL_SECONDS = 180

# How long a finished session stays in `done` before it drops to `idle`.
FLEET_IDLE_DAYS = 2

# `tool_ask_user` in mcp_server.py polls its own `agent_pending_asks` row for
# 600s and then returns an error to Claude. Nothing marks the row afterwards,
# so a `status='pending'` ask older than this has no reader left: answering it
# writes into a table nobody is watching. Keep this in sync with that
# deadline, or the roster will queue up asks that can no longer be delivered
# (16 such rows, 8-27 days old, existed when this was written).
FLEET_ASK_DEADLINE_SECONDS = 600


def fleet_rows(project_id=None, newer_than_days=None, limit=200,
               ask_deadline_seconds=FLEET_ASK_DEADLINE_SECONDS):
    """Return one triage row per session, newest activity first.

    Each row is `agent_sessions.*` plus the counts a roster view needs:
    message/ask/decision/section totals, the latest run, and
    `last_event_at` — the real heartbeat, since `updated_at` only moves on
    status transitions and so looks frozen for the whole of a long run.

    Classification is deliberately *not* done here: see
    `classify_fleet_row`, which is pure and therefore testable without a DB.
    """
    sql = """
        SELECT s.*,
               p.name  AS provider_name,
               pr.slug AS project_slug,
               COALESCE(m.msg_count, 0)       AS msg_count,
               COALESCE(a.pending_asks, 0)    AS pending_asks,
               COALESCE(a.live_asks, 0)       AS live_asks,
               COALESCE(a.dead_asks, 0)       AS dead_asks,
               COALESCE(a.pending_msgs, 0)    AS pending_msgs,
               COALESCE(n.pending_decisions, 0) AS pending_decisions,
               COALESCE(sec.findings, 0)      AS findings,
               COALESCE(sec.todos_open, 0)    AS todos_open,
               COALESCE(sec.questions_open, 0) AS questions_open,
               COALESCE(w.cost_usd, 0.0)      AS cost_usd,
               r.id        AS run_id,
               r.status    AS run_status,
               r.started_at AS run_started_at,
               r.error_text AS run_error,
               (SELECT MAX(e.created_at) FROM agent_events e
                 WHERE e.run_id = r.id) AS last_event_at
          FROM agent_sessions s
          JOIN agent_providers p ON s.provider_id = p.id
          LEFT JOIN projects pr ON pr.id = s.project_id
          LEFT JOIN (SELECT session_id, COUNT(*) AS msg_count
                       FROM agent_messages GROUP BY session_id) m
                 ON m.session_id = s.id
          LEFT JOIN (SELECT session_id,
                            SUM(kind = 'question') AS pending_asks,
                            SUM(kind = 'question'
                                AND datetime(created_at) >= datetime('now', ?))
                              AS live_asks,
                            SUM(kind = 'question'
                                AND datetime(created_at) < datetime('now', ?))
                              AS dead_asks,
                            -- messages are one-way: nothing ever flips them
                            -- to 'responded', so delivery is the only
                            -- meaningful notion of outstanding.
                            SUM(kind = 'message' AND dispatched_at IS NULL)
                              AS pending_msgs
                       FROM agent_pending_asks
                      WHERE status = 'pending'
                      GROUP BY session_id) a
                 ON a.session_id = s.id
          LEFT JOIN (SELECT session_id, COUNT(*) AS pending_decisions
                       FROM agent_notifications
                      WHERE kind = 'decision' AND decided_at IS NULL
                      GROUP BY session_id) n
                 ON n.session_id = s.id
          LEFT JOIN (SELECT session_id,
                            SUM(section = 'findings') AS findings,
                            SUM(section = 'todo'
                                AND COALESCE(json_extract(entry_json, '$.done'), 0) = 0)
                              AS todos_open,
                            SUM(section = 'open-questions'
                                AND COALESCE(json_extract(entry_json, '$.answered'), 0) = 0)
                              AS questions_open
                       FROM agent_session_sections GROUP BY session_id) sec
                 ON sec.session_id = s.id
          LEFT JOIN (SELECT session_id, SUM(COALESCE(cost_usd, 0)) AS cost_usd
                       FROM agent_work_log GROUP BY session_id) w
                 ON w.session_id = s.id
          LEFT JOIN agent_runs r
                 ON r.id = (SELECT r2.id FROM agent_runs r2
                             WHERE r2.session_id = s.id
                             ORDER BY r2.id DESC LIMIT 1)
         WHERE 1=1"""
    # The two leading params belong to the live/dead ask split inside the
    # LEFT JOIN, which is textually ahead of this WHERE clause.
    cutoff = f"-{int(ask_deadline_seconds)} seconds"
    params = [cutoff, cutoff]
    if project_id is not None:
        sql += " AND s.project_id = ?"
        params.append(project_id)
    if newer_than_days and newer_than_days > 0:
        sql += " AND datetime(s.updated_at) >= datetime('now', ?)"
        params.append(f"-{int(newer_than_days)} days")
    sql += " ORDER BY datetime(s.updated_at) DESC LIMIT ?"
    params.append(limit)
    return query_all(sql, tuple(params))


def _age_seconds(stamp, now=None):
    """Seconds since a `YYYY-MM-DD HH:MM:SS` UTC stamp, or None."""
    if not stamp:
        return None
    try:
        then = datetime.strptime(str(stamp)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return max(0.0, ((now or datetime.utcnow()) - then).total_seconds())


def classify_fleet_row(row, stall_seconds=FLEET_STALL_SECONDS,
                       idle_days=FLEET_IDLE_DAYS, now=None):
    """Classify one `fleet_rows` row into a bucket.

    Returns a dict of derived fields to merge into the row: `bucket`,
    `reason` (why it landed there, for display), `stalled`, `heartbeat_age`
    and `age_seconds`. Pure — no DB access — so the bucket rules can be
    tested directly.

    The rules in priority order:
      1. a *live* ask or undecided decision outranks everything, because the
         agent is blocked on you and burning its 600s deadline. An ask past
         that deadline is not blocking anything — see
         `FLEET_ASK_DEADLINE_SECONDS` — so it only annotates the row;
      2. 'running' with a dead heartbeat is `working` but flagged stalled,
         never silently dropped into `done`;
      3. failed/cancelled/interrupted is `attention`, not `done` — an
         interrupted run is resumable and should not look finished;
      4. 'waiting' means the agent finished its turn, which is `done`
         *and* your move; it ages out to `idle`.
    """
    now = now or datetime.utcnow()
    status = (row.get("status") or "").strip()
    age = _age_seconds(row.get("updated_at"), now)
    beat = _age_seconds(row.get("last_event_at") or row.get("updated_at"), now)
    # Fall back to the raw count when the caller handed us a row from
    # `list_sessions` rather than `fleet_rows` (no live/dead split).
    live = int(row.get("live_asks") if row.get("live_asks") is not None
               else row.get("pending_asks") or 0)
    dead = int(row.get("dead_asks") or 0)
    decisions = int(row.get("pending_decisions") or 0)
    msgs = int(row.get("pending_msgs") or 0)
    stalled = False

    if live or decisions:
        parts = []
        if live:
            parts.append(f"{live} question{'s' if live > 1 else ''} pending")
        if decisions:
            parts.append(f"{decisions} decision{'s' if decisions > 1 else ''} to approve")
        bucket, reason = BUCKET_NEEDS_INPUT, ", ".join(parts)
    elif status == "running":
        bucket = BUCKET_WORKING
        if beat is not None and beat > stall_seconds:
            stalled = True
            reason = f"no event for {_humanize_age(beat)} — provider may be gone"
        else:
            reason = "working"
    elif status in ("failed", "cancelled"):
        bucket = BUCKET_ATTENTION
        reason = f"{status}: {_error_gist(row.get('run_error'))}" \
            if row.get("run_error") else status
    elif status == "interrupted":
        bucket, reason = BUCKET_ATTENTION, "interrupted — resumable"
    elif status == "created" and not int(row.get("msg_count") or 0):
        bucket, reason = BUCKET_IDLE, "never started"
    else:
        bucket = BUCKET_DONE
        reason = "your turn"
        if int(row.get("questions_open") or 0):
            reason = f"{row['questions_open']} open question(s)"
        if age is not None and age > idle_days * 86400:
            bucket, reason = BUCKET_IDLE, f"idle {_humanize_age(age)}"

    # `attention` ages out too, for the same reason `done` does: a bucket
    # with no aging rule is an archive, not a queue. Without this, every
    # failure and every lost process accumulates there permanently — 15 of
    # them had, going back 13 days, which is what made the bucket unusable.
    # Aging is also the only honest way to "write one off": nothing is
    # destroyed, it stops claiming your attention. The reason line keeps
    # saying what happened, so an aged-out failure is still legible in
    # `--bucket idle`.
    if bucket == BUCKET_ATTENTION and age is not None \
            and age > idle_days * 86400:
        bucket = BUCKET_IDLE
        reason = f"{reason}, {_humanize_age(age)} ago"

    if msgs and bucket != BUCKET_NEEDS_INPUT:
        reason = f"{reason} · {msgs} undelivered message(s)"
    if dead:
        # Worth surfacing: the agent asked, nobody answered inside the
        # deadline, and it carried on (or died) without your input.
        reason = f"{reason} · {dead} ask(s) expired unanswered"

    return {
        "bucket": bucket,
        "reason": reason,
        "stalled": stalled,
        "heartbeat_age": beat,
        "age_seconds": age,
        "expired_asks": dead,
    }


def _error_gist(text):
    """First meaningful clause of a provider error, for a narrow column.

    Provider failures arrive as `idle_timeout; open_tools=['toolu_01...']` —
    the clause before the semicolon is the whole diagnosis, and the tool ids
    after it just push the rest of the row off screen.
    """
    first = (text or "").strip().splitlines()
    if not first:
        return ""
    gist = first[0].split(";")[0].strip()
    return gist[:48] if gist else first[0][:48]


def _humanize_age(seconds):
    """`93847.0` -> `'1d'`. Coarse on purpose: roster columns are narrow."""
    if seconds is None:
        return "?"
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def fleet(project_id=None, newer_than_days=None, limit=200,
          stall_seconds=FLEET_STALL_SECONDS, idle_days=FLEET_IDLE_DAYS,
          ask_deadline_seconds=FLEET_ASK_DEADLINE_SECONDS):
    """`fleet_rows` + classification, grouped for display.

    Returns `{"rows": [...], "counts": {bucket: n}}` with rows carrying the
    derived fields and ordered by bucket priority, then newest activity.
    """
    now = datetime.utcnow()
    rows = []
    for row in fleet_rows(project_id=project_id, newer_than_days=newer_than_days,
                          limit=limit,
                          ask_deadline_seconds=ask_deadline_seconds):
        row = dict(row)
        row.update(classify_fleet_row(row, stall_seconds=stall_seconds,
                                      idle_days=idle_days, now=now))
        row["age_label"] = _humanize_age(row.get("age_seconds"))
        rows.append(row)

    order = {b: i for i, b in enumerate(FLEET_BUCKET_ORDER)}
    rows.sort(key=lambda r: (order.get(r["bucket"], 99),
                             r.get("age_seconds") or 0.0))
    counts = {b: 0 for b in FLEET_BUCKET_ORDER}
    for row in rows:
        counts[row["bucket"]] = counts.get(row["bucket"], 0) + 1
    return {"rows": rows, "counts": counts}


def pending_asks(session_id=None, include_messages=True, only_live=False,
                 ask_deadline_seconds=FLEET_ASK_DEADLINE_SECONDS):
    """Every unanswered ask, oldest first. The roster's needs-input inbox.

    Unlike `undispatched_asks_for_session` this ignores `dispatched_at`: an
    ask already pushed to one Emacs buffer is still unanswered, and the
    roster needs to show it so it can be answered from anywhere.

    Each row gains `age_seconds` and `live` — whether a reader is still
    polling for the answer (see `FLEET_ASK_DEADLINE_SECONDS`). Pass
    `only_live=True` for a queue of asks that can actually be delivered.
    """
    sql = """SELECT a.*, s.title AS session_title, pr.slug AS project_slug
               FROM agent_pending_asks a
               JOIN agent_sessions s ON s.id = a.session_id
               LEFT JOIN projects pr ON pr.id = s.project_id
              WHERE a.status = 'pending'"""
    params = []
    if not include_messages:
        sql += " AND a.kind = 'question'"
    if session_id is not None:
        sql += " AND a.session_id = ?"
        params.append(session_id)
    sql += " ORDER BY datetime(a.created_at)"

    now = datetime.utcnow()
    out = []
    for row in query_all(sql, tuple(params)):
        row = dict(row)
        row["age_seconds"] = _age_seconds(row.get("created_at"), now)
        row["age_label"] = _humanize_age(row["age_seconds"])
        row["live"] = (row["age_seconds"] is not None
                       and row["age_seconds"] <= ask_deadline_seconds)
        if only_live and not row["live"]:
            continue
        out.append(row)
    return out


def expire_stale_asks(ask_deadline_seconds=FLEET_ASK_DEADLINE_SECONDS):
    """Mark asks nobody is polling for any more as 'expired'.

    Housekeeping, not a behaviour change: `tool_ask_user` already gave up on
    these. Flipping the status stops them being counted as outstanding work
    forever, and keeps `status` honest about whether an answer was ever
    delivered. Returns the number of rows changed.
    """
    return execute(
        """UPDATE agent_pending_asks
              SET status = 'expired'
            WHERE status = 'pending'
              AND kind = 'question'
              AND datetime(created_at) < datetime('now', ?)""",
        (f"-{int(ask_deadline_seconds)} seconds",),
    )
