"""AgentService - orchestration layer for Temple Agent.

Manages the lifecycle of sessions and runs, dispatches to providers,
handles streaming with batched writes, and crash recovery.
"""
import threading
import time
import json
from datetime import datetime

from logger import get_logger
from agent import events
from agent.events import (
    make_event,
    RUN_STARTED, RUN_COMPLETED, RUN_FAILED, RUN_INTERRUPTED,
    ASSISTANT_STARTED, ASSISTANT_DELTA, ASSISTANT_COMPLETED,
    TOOL_STARTED, TOOL_COMPLETED, TOOL_FAILED,
    SESSION_RUNNING, SESSION_WAITING, SESSION_COMPLETED,
    SESSION_FAILED, SESSION_INTERRUPTED, SESSION_CANCELLED,
    RUN_STATUS_RUNNING, RUN_STATUS_COMPLETED, RUN_STATUS_FAILED,
    RUN_STATUS_INTERRUPTED, RUN_STATUS_CANCELLED,
    ROLE_USER, ROLE_ASSISTANT,
)
from agent import store
from agent.providers.fake import FakeProvider

logger = get_logger("AgentService")

# Minimum interval between DB writes for streaming text (seconds)
FLUSH_INTERVAL = 0.25


def _get_provider(provider_kind, config=None):
    """Instantiate a provider by kind."""
    if provider_kind == "fake":
        return FakeProvider()
    elif provider_kind == "claude_code":
        from agent.providers.claude_code import ClaudeCodeProvider
        return ClaudeCodeProvider(config)
    else:
        raise ValueError(f"Unknown provider kind: {provider_kind}")


class AgentService:
    """Manages agent sessions, runs, and provider interaction."""

    def __init__(self):
        self._providers = {}  # session_id -> provider instance
        self._active_run = {}  # session_id -> run dict
        self._event_callbacks = []  # list of fn(session_id, run_id, event)
        self._cancel_flags = {}  # session_id -> threading.Event
        self._queued_messages = {}  # session_id -> list of queued content strings
        self._lock = threading.Lock()

    def add_event_callback(self, callback):
        """Register a callback that receives every event as it happens.
        Signature: callback(session_id, run_id, event_dict)
        """
        self._event_callbacks.append(callback)

    def _emit_event(self, session_id, run_id, event):
        """Send event to all registered callbacks."""
        for cb in self._event_callbacks:
            try:
                cb(session_id, run_id, event)
            except Exception as e:
                logger.error(f"Event callback error: {e}")

    # --- Doctor ---

    def doctor(self, provider_name="fake"):
        """Check provider health."""
        provider_row = store.get_provider(provider_name)
        if not provider_row:
            return {"ok": False, "error": f"Provider '{provider_name}' not found"}
        try:
            provider = _get_provider(provider_row["provider_kind"])
            return provider.doctor()
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # --- Sessions ---

    def create_session(self, provider_name="fake", project_slug=None, title=None, model=None):
        """Create a new agent session."""
        project_id = None
        if project_slug:
            from db_utils import query_one
            project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
            if project:
                project_id = project["id"]

        session = store.create_session(provider_name, project_id=project_id,
                                       title=title, model=model)

        # Instantiate provider
        provider = _get_provider(session["provider_kind"])
        result = provider.start(model=model)
        if result.get("external_session_id"):
            store.update_session_external_id(session["id"], result["external_session_id"])

        self._providers[session["id"]] = provider
        return store.get_session(session["id"])

    def open_session(self, session_id):
        """Open/resume an existing session."""
        session = store.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        if session["id"] not in self._providers:
            provider = _get_provider(session["provider_kind"])
            provider.start(session_external_id=session.get("external_session_id"),
                           model=session.get("model"))
            self._providers[session["id"]] = provider

        # Recover if needed
        if session["status"] == SESSION_RUNNING:
            store.update_session_status(session["id"], SESSION_INTERRUPTED)
            latest_run = store.get_latest_run(session["id"])
            if latest_run and latest_run["status"] == RUN_STATUS_RUNNING:
                store.complete_run(latest_run["id"], status=RUN_STATUS_INTERRUPTED,
                                   error_text="Session reopened after interruption")

        return store.get_session(session["id"])

    def list_sessions(self, project_slug=None, status=None, limit=50):
        """List sessions."""
        project_id = None
        if project_slug:
            from db_utils import query_one
            project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
            if project:
                project_id = project["id"]
        return store.list_sessions(project_id=project_id, status=status, limit=limit)

    def get_session(self, session_id):
        """Get full session info."""
        return store.get_session(session_id)

    # --- Messages ---

    def send_message(self, session_id, content, context=None):
        """Send a user message and stream the response.

        This is the main interaction point. It:
        1. Stores the user message
        2. Creates a new run
        3. Sends all messages to the provider
        4. Streams events back, batching DB writes
        5. Stores the final assistant message

        Yields event dicts as they happen.
        """
        session = store.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        provider = self._providers.get(session_id)
        if not provider:
            raise ValueError(f"No provider for session {session_id}. Call open_session first.")

        # Store user message
        store.add_message(session_id, ROLE_USER, content)

        # Auto-title from first message
        if not session.get("title"):
            title = content[:80].strip()
            if len(content) > 80:
                title += "..."
            store.update_session_title(session_id, title)

        # Create run
        run = store.create_run(session_id)
        run_id = run["id"]
        self._active_run[session_id] = run

        # Update session status
        store.update_session_status(session_id, SESSION_RUNNING)

        # Set up cancel flag
        cancel_event = threading.Event()
        self._cancel_flags[session_id] = cancel_event

        # Build message history for provider
        messages = store.get_messages(session_id)
        message_list = [{"role": m["role"], "content_text": m["content_text"]} for m in messages]

        # Create placeholder assistant message for streaming
        assistant_msg = store.add_message(session_id, ROLE_ASSISTANT, "", run_id=run_id)
        accumulated_text = []
        last_flush_time = time.time()

        try:
            for raw_event in provider.send(message_list, context):
                if cancel_event.is_set():
                    # Flush accumulated text
                    if accumulated_text:
                        store.update_message_content(assistant_msg["id"], "".join(accumulated_text))
                    store.complete_run(run_id, status=RUN_STATUS_CANCELLED)
                    store.update_session_status(session_id, SESSION_CANCELLED)
                    cancel_evt = make_event(RUN_INTERRUPTED, summary="Cancelled by user")
                    stored = store.add_event(run_id, cancel_evt["type"],
                                             summary=cancel_evt.get("summary"))
                    yield self._enrich_event(session_id, run_id, stored, cancel_evt)
                    return

                event = provider.normalize_event(raw_event)
                event_type = event.get("type", "")

                # Accumulate streaming text
                if event_type == ASSISTANT_DELTA:
                    text_chunk = event.get("data", {}).get("text", "")
                    accumulated_text.append(text_chunk)

                    # Batched flush
                    now = time.time()
                    if now - last_flush_time >= FLUSH_INTERVAL:
                        store.update_message_content(assistant_msg["id"],
                                                     "".join(accumulated_text))
                        last_flush_time = now

                # Store event (skip deltas from DB - too noisy)
                if event_type != ASSISTANT_DELTA:
                    stored = store.add_event(
                        run_id, event_type,
                        summary=event.get("summary"),
                        payload=event.get("data"),
                    )
                else:
                    stored = {"sequence_number": 0}

                # Emit to callbacks and yield
                enriched = self._enrich_event(session_id, run_id, stored, event)
                self._emit_event(session_id, run_id, enriched)
                yield enriched

                # Final flush on assistant completion
                if event_type == ASSISTANT_COMPLETED:
                    full_text = event.get("data", {}).get("full_text", "".join(accumulated_text))
                    store.update_message_content(assistant_msg["id"], full_text)

                # Mark run complete
                if event_type == RUN_COMPLETED:
                    store.complete_run(run_id, status=RUN_STATUS_COMPLETED)
                    store.update_session_status(session_id, SESSION_WAITING)

                if event_type == RUN_FAILED:
                    error = event.get("data", {}).get("error", "Unknown error")
                    store.complete_run(run_id, status=RUN_STATUS_FAILED, error_text=error)
                    store.update_session_status(session_id, SESSION_FAILED)

        except Exception as e:
            # Flush any accumulated text
            if accumulated_text:
                store.update_message_content(assistant_msg["id"], "".join(accumulated_text))
            store.complete_run(run_id, status=RUN_STATUS_FAILED, error_text=str(e))
            store.update_session_status(session_id, SESSION_FAILED)
            error_event = make_event(RUN_FAILED, summary=f"Error: {e}", error=str(e))
            yield self._enrich_event(session_id, run_id, {}, error_event)
            raise

        finally:
            self._cancel_flags.pop(session_id, None)
            self._active_run.pop(session_id, None)

    def _enrich_event(self, session_id, run_id, stored, event):
        """Add session/run/sequence info to an event for client consumption."""
        return {
            "session_id": session_id,
            "run_id": run_id,
            "sequence": stored.get("sequence_number", 0),
            "type": event.get("type", ""),
            "summary": event.get("summary"),
            "data": event.get("data"),
            "created_at": stored.get("created_at"),
        }

    # --- Control ---

    def queue_message(self, session_id, content):
        """Queue a message to be sent after the current run completes.
        Used when the user types while Claude is working.
        """
        if session_id not in self._queued_messages:
            self._queued_messages[session_id] = []
        self._queued_messages[session_id].append(content)
        # Store immediately so it survives crash
        store.add_message(session_id, ROLE_USER, content)
        logger.info(f"Queued message for session {session_id}")

    def _process_queue(self, session_id, context=None):
        """Process any queued messages after a run completes. Yields events."""
        queue = self._queued_messages.get(session_id, [])
        if not queue:
            return
        # Take the first queued message
        content = queue.pop(0)
        if not queue:
            self._queued_messages.pop(session_id, None)
        # Message already stored by queue_message, so just send to provider
        yield from self._run_with_provider(session_id, context)

    def cancel_run(self, session_id):
        """Cancel the active run for a session."""
        cancel_event = self._cancel_flags.get(session_id)
        if cancel_event:
            cancel_event.set()
        provider = self._providers.get(session_id)
        if provider:
            provider.cancel()

    def resume_run(self, session_id, context=None):
        """Resume an interrupted session by re-sending messages.
        Yields events like send_message.
        """
        session = store.get_session(session_id)
        if not session:
            raise ValueError(f"Session {session_id} not found")

        # Reopen if needed
        if session_id not in self._providers:
            self.open_session(session_id)

        # Get last user message
        messages = store.get_messages(session_id)
        if not messages:
            raise ValueError("No messages to resume from")

        last_user_msg = None
        for m in reversed(messages):
            if m["role"] == ROLE_USER:
                last_user_msg = m
                break

        if not last_user_msg:
            raise ValueError("No user message found to resume from")

        # Re-send via normal flow
        yield from self.send_message(session_id, last_user_msg["content_text"], context)

    # --- Recovery ---

    def recover(self):
        """Recover sessions that were interrupted by process death."""
        recovered = store.recover_interrupted_sessions()
        if recovered:
            logger.info(f"Recovered {len(recovered)} interrupted sessions: {recovered}")
        return recovered

    # --- Cleanup ---

    def close_session(self, session_id):
        """Clean up resources for a session."""
        provider = self._providers.pop(session_id, None)
        if provider:
            provider.cleanup()
        self._cancel_flags.pop(session_id, None)
        self._active_run.pop(session_id, None)

    # --- Events ---

    def get_events_since(self, run_id, since_sequence=0):
        """Get events after a sequence number (for reconnection)."""
        return store.get_events_since(run_id, since_sequence)

    def get_messages(self, session_id):
        """Get all messages for a session."""
        return store.get_messages(session_id)

    def get_notes(self, session_id):
        """Get session notes."""
        return store.get_notes(session_id)

    def set_notes(self, session_id, **kwargs):
        """Update session notes."""
        return store.set_notes(session_id, **kwargs)

    # --- Fork ---

    def fork_session(self, session_id):
        """Fork a session - create a copy with all messages."""
        return store.fork_session(session_id)
