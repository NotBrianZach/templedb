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


def _retry_on_lock(fn, max_retries=3, delay=0.5):
    """Retry a DB operation on sqlite3.OperationalError (database locked)."""
    for attempt in range(max_retries):
        try:
            return fn()
        except sqlite3.OperationalError as e:
            if "locked" in str(e).lower() and attempt < max_retries - 1:
                _logger.warning(f"DB locked, retry {attempt+1}/{max_retries} in {delay}s")
                time.sleep(delay * (attempt + 1))
            else:
                raise


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _retry_on_lock(fn, max_retries=3, base_delay=0.5):
    """Retry a DB operation on OperationalError (database locked).

    Uses exponential backoff. Prevents agent sessions from dying
    when the FUSE mount or GUI holds a brief write lock.
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


def list_sessions(project_id=None, status=None, limit=50):
    """List sessions with optional filters."""
    sql = """SELECT s.*, p.name as provider_name
             FROM agent_sessions s
             JOIN agent_providers p ON s.provider_id = p.id
             WHERE 1=1"""
    params = []
    if project_id is not None:
        sql += " AND s.project_id = ?"
        params.append(project_id)
    if status:
        sql += " AND s.status = ?"
        params.append(status)
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
    and is most likely to collide with FUSE/GUI writes.
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
    subprocess writers that race against the agent service, FUSE mount,
    GUI, and any parallel templedb activity. Without retry, four
    rapid-fire `templedb_agent_*` calls from Claude reliably lose the
    lock race and return `database is locked` to the model."""
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
