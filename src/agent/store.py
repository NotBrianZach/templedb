"""AgentStore - database layer for Temple Agent.

Single writer pattern: all agent table mutations go through this module.
Uses db_utils for connection pooling and transactions.
"""
import json
import uuid
from datetime import datetime

from db_utils import query_one, query_all, execute, transaction
from agent.events import (
    SESSION_CREATED, RUN_STATUS_RUNNING, RUN_STATUS_COMPLETED,
    RUN_STATUS_INTERRUPTED, RUN_STATUS_FAILED, RUN_STATUS_CANCELLED,
)


def _now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


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
    """Update session status."""
    execute(
        "UPDATE agent_sessions SET status = ?, updated_at = ? WHERE id = ?",
        (status, _now(), session_id),
    )


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
    """Mark a run as completed/failed/interrupted."""
    execute(
        "UPDATE agent_runs SET status = ?, completed_at = ?, error_text = ? WHERE id = ?",
        (status, _now(), error_text, run_id),
    )


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
    """Update message content (for streaming accumulation)."""
    execute(
        "UPDATE agent_messages SET content_text = ?, updated_at = ? WHERE id = ?",
        (content_text, _now(), message_id),
    )


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
    """Add an event to a run. Auto-assigns sequence number. Returns event row."""
    # Get next sequence from run's counter
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

    return query_one("SELECT * FROM agent_events WHERE id = ?", (event_id,))


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
