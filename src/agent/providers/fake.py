"""FakeProvider - test provider that simulates Claude-like responses.

Yields realistic event sequences for testing the full pipeline
without needing a real AI backend.
"""
import time
from agent.events import (
    make_event,
    RUN_STARTED, RUN_COMPLETED,
    ASSISTANT_STARTED, ASSISTANT_DELTA, ASSISTANT_COMPLETED,
    TOOL_STARTED, TOOL_COMPLETED,
)
from agent.providers.base import BaseProvider


# Canned responses keyed by simple keyword matching
CANNED_RESPONSES = {
    "hello": "Hello! I'm the Temple Agent fake provider. I can simulate responses for testing.",
    "test": "All tests passed. The fake provider is working correctly.",
    "default": (
        "TempleDB stores all project data in SQLite. "
        "It uses a FUSE mount for transparent file access, "
        "and tracks VCS history, deployments, environments, and more. "
        "The CLI provides commands like `templedb vcs status`, `templedb deploy`, "
        "and `templedb ai agent` for AI-powered workflows."
    ),
}

FAKE_TOOLS = [
    {"name": "Read file", "summary": "Reading src/agent/service.py", "duration": 0.1},
    {"name": "Search", "summary": "Searching for 'agent' in codebase", "duration": 0.15},
]


class FakeProvider(BaseProvider):
    """Simulates an AI provider for testing."""

    def __init__(self):
        self._cancelled = False
        self._session_counter = 0

    def doctor(self):
        return {"ok": True, "details": ["FakeProvider ready", "No login required"]}

    def start(self, session_external_id=None, model=None):
        if session_external_id:
            return {"external_session_id": session_external_id}
        self._session_counter += 1
        return {"external_session_id": f"fake-{self._session_counter}"}

    def send(self, messages, context=None):
        self._cancelled = False

        if not messages:
            return

        last_message = messages[-1].get("content_text", "")

        # Pick response
        response_text = CANNED_RESPONSES["default"]
        for keyword, text in CANNED_RESPONSES.items():
            if keyword != "default" and keyword in last_message.lower():
                response_text = text
                break

        # Simulate run start
        yield make_event(RUN_STARTED, summary="Processing message")

        # Simulate tool use (if message is long enough to warrant it)
        if len(last_message) > 20:
            for tool in FAKE_TOOLS:
                if self._cancelled:
                    return
                yield make_event(TOOL_STARTED, summary=tool["summary"],
                                 tool_name=tool["name"])
                time.sleep(tool["duration"])
                yield make_event(TOOL_COMPLETED, summary=tool["summary"],
                                 tool_name=tool["name"])

        if self._cancelled:
            return

        # Stream the response in chunks
        yield make_event(ASSISTANT_STARTED, summary="Generating response")

        words = response_text.split()
        chunk_size = 3
        for i in range(0, len(words), chunk_size):
            if self._cancelled:
                return
            chunk = " ".join(words[i:i + chunk_size])
            if i > 0:
                chunk = " " + chunk
            yield make_event(ASSISTANT_DELTA, text=chunk)
            time.sleep(0.05)  # Simulate streaming delay

        yield make_event(ASSISTANT_COMPLETED, summary="Response complete",
                         full_text=response_text)

        yield make_event(RUN_COMPLETED, summary="Done")

    def cancel(self):
        self._cancelled = True

    def cleanup(self):
        self._cancelled = False
