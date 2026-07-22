"""Temple Agent JSON-lines protocol.

Stdio protocol: one JSON object per line.
Requests have 'id' and 'method'. Events have 'method': 'event'.

Methods:
  provider.doctor
  session.create
  session.open
  session.list
  session.close
  message.send
  run.cancel
  run.resume
  events.since
  notes.get
  notes.set
"""
import json
import sys
import threading
import traceback

from logger import get_logger
from agent.service import AgentService

logger = get_logger("AgentProtocol")


class ProtocolServer:
    """JSON-lines protocol server over stdio."""

    def __init__(self, input_stream=None, output_stream=None):
        self.service = AgentService()
        self.input = input_stream or sys.stdin
        self.output = output_stream or sys.stdout
        self._output_lock = threading.Lock()
        self._running = False

        # Register event callback for streaming
        self.service.add_event_callback(self._on_event)

    def _write(self, obj):
        """Write a JSON line to output (thread-safe)."""
        with self._output_lock:
            line = json.dumps(obj, default=str)
            self.output.write(line + "\n")
            self.output.flush()

    def _respond(self, request_id, result=None, error=None):
        """Send a response to a request."""
        resp = {"id": request_id}
        if error:
            resp["error"] = error
        else:
            resp["result"] = result
        self._write(resp)

    def _on_event(self, session_id, run_id, event):
        """Callback from service: push event to client."""
        self._write({
            "method": "event",
            "params": event,
        })

    def run(self):
        """Main loop: read JSON lines, dispatch, respond."""
        # Recover interrupted sessions on startup
        recovered = self.service.recover()
        if recovered:
            self._write({
                "method": "event",
                "params": {
                    "type": "service.recovered",
                    "summary": f"Recovered {len(recovered)} interrupted sessions",
                    "data": {"session_ids": recovered},
                },
            })

        self._running = True
        logger.info("Protocol server started")

        for line in self.input:
            line = line.strip()
            if not line:
                continue

            try:
                request = json.loads(line)
            except json.JSONDecodeError as e:
                self._write({"error": f"Invalid JSON: {e}"})
                continue

            request_id = request.get("id")
            method = request.get("method", "")
            params = request.get("params", {})

            try:
                self._dispatch(request_id, method, params)
            except Exception as e:
                logger.error(f"Error handling {method}: {e}")
                logger.debug(traceback.format_exc())
                if request_id is not None:
                    self._respond(request_id, error=str(e))

        self._running = False
        logger.info("Protocol server stopped")

    def _dispatch(self, request_id, method, params):
        """Route a method to its handler."""
        handlers = {
            "provider.doctor": self._handle_doctor,
            "session.create": self._handle_session_create,
            "session.open": self._handle_session_open,
            "session.list": self._handle_session_list,
            "session.close": self._handle_session_close,
            "message.send": self._handle_message_send,
            "message.queue": self._handle_message_queue,
            "run.cancel": self._handle_run_cancel,
            "run.resume": self._handle_run_resume,
            "events.since": self._handle_events_since,
            "notes.get": self._handle_notes_get,
            "notes.set": self._handle_notes_set,
            "session.fork": self._handle_session_fork,
        }

        handler = handlers.get(method)
        if not handler:
            self._respond(request_id, error=f"Unknown method: {method}")
            return

        handler(request_id, params)

    # --- Handlers ---

    def _handle_doctor(self, request_id, params):
        provider = params.get("provider", "fake")
        result = self.service.doctor(provider)
        self._respond(request_id, result=result)

    def _handle_session_create(self, request_id, params):
        session = self.service.create_session(
            provider_name=params.get("provider", "fake"),
            project_slug=params.get("project"),
            title=params.get("title"),
            model=params.get("model"),
        )
        self._respond(request_id, result=session)

    def _handle_session_open(self, request_id, params):
        session_id = params.get("session_id")
        if not session_id:
            self._respond(request_id, error="session_id required")
            return
        session = self.service.open_session(session_id)
        messages = self.service.get_messages(session_id)
        notes = self.service.get_notes(session_id)

        # Build events-by-run for Org rendering
        from agent import store as agent_store
        events_by_run = {}
        runs = agent_store.list_runs(session_id)
        for run in runs:
            events_by_run[run["id"]] = agent_store.get_all_run_events(run["id"])

        # Pre-render Org document
        from agent.org_renderer import render_session
        org_text = render_session(session, messages, events_by_run, notes)

        self._respond(request_id, result={
            "session": session,
            "messages": messages,
            "notes": notes,
            "org": org_text,
        })

    def _handle_session_list(self, request_id, params):
        sessions = self.service.list_sessions(
            project_slug=params.get("project"),
            status=params.get("status"),
            limit=params.get("limit", 50),
        )
        self._respond(request_id, result=sessions)

    def _handle_session_close(self, request_id, params):
        session_id = params.get("session_id")
        if not session_id:
            self._respond(request_id, error="session_id required")
            return
        self.service.close_session(session_id)
        self._respond(request_id, result={"ok": True})

    def _handle_message_send(self, request_id, params):
        session_id = params.get("session_id")
        content = params.get("content", "")
        context = params.get("context")

        if not session_id:
            self._respond(request_id, error="session_id required")
            return
        if not content.strip():
            self._respond(request_id, error="content required")
            return

        # Run in a thread so we don't block the main read loop
        def run_send():
            try:
                for event in self.service.send_message(session_id, content, context):
                    pass  # Events are pushed via callback
                self._respond(request_id, result={"ok": True})
            except Exception as e:
                logger.error(f"send_message error: {e}")
                self._respond(request_id, error=str(e))

        thread = threading.Thread(target=run_send, daemon=True)
        thread.start()

    def _handle_message_queue(self, request_id, params):
        session_id = params.get("session_id")
        content = params.get("content", "")
        if not session_id:
            self._respond(request_id, error="session_id required")
            return
        if not content.strip():
            self._respond(request_id, error="content required")
            return
        self.service.queue_message(session_id, content)
        self._respond(request_id, result={"ok": True, "queued": True})

    def _handle_run_cancel(self, request_id, params):
        session_id = params.get("session_id")
        if not session_id:
            self._respond(request_id, error="session_id required")
            return
        self.service.cancel_run(session_id)
        self._respond(request_id, result={"ok": True})

    def _handle_run_resume(self, request_id, params):
        session_id = params.get("session_id")
        context = params.get("context")

        if not session_id:
            self._respond(request_id, error="session_id required")
            return

        def run_resume():
            try:
                for event in self.service.resume_run(session_id, context):
                    pass
                self._respond(request_id, result={"ok": True})
            except Exception as e:
                logger.error(f"resume error: {e}")
                self._respond(request_id, error=str(e))

        thread = threading.Thread(target=run_resume, daemon=True)
        thread.start()

    def _handle_events_since(self, request_id, params):
        run_id = params.get("run_id")
        since = params.get("since", 0)
        if not run_id:
            self._respond(request_id, error="run_id required")
            return
        events = self.service.get_events_since(run_id, since)
        self._respond(request_id, result=events)

    def _handle_notes_get(self, request_id, params):
        session_id = params.get("session_id")
        if not session_id:
            self._respond(request_id, error="session_id required")
            return
        notes = self.service.get_notes(session_id)
        self._respond(request_id, result=notes)

    def _handle_notes_set(self, request_id, params):
        session_id = params.get("session_id")
        if not session_id:
            self._respond(request_id, error="session_id required")
            return
        notes = self.service.set_notes(
            session_id,
            goal_org=params.get("goal"),
            notes_org=params.get("notes"),
            scratch_org=params.get("scratch"),
        )
        self._respond(request_id, result=notes)

    def _handle_session_fork(self, request_id, params):
        session_id = params.get("session_id")
        if not session_id:
            self._respond(request_id, error="session_id required")
            return
        new_session = self.service.fork_session(session_id)
        self._respond(request_id, result=new_session)
