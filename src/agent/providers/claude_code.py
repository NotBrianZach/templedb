"""ClaudeCodeProvider - real Claude Code CLI integration.

Launches Claude Code as a subprocess with --output-format stream-json,
parses the streaming events, and converts them into normalized Temple Agent events.
"""
import json
import os
import shutil
import signal
import subprocess
import threading
from pathlib import Path

from logger import get_logger
from agent.events import (
    make_event,
    RUN_STARTED, RUN_COMPLETED, RUN_FAILED, RUN_INTERRUPTED,
    ASSISTANT_STARTED, ASSISTANT_DELTA, ASSISTANT_COMPLETED,
    TOOL_STARTED, TOOL_COMPLETED, TOOL_FAILED,
    PROVIDER_RATE_LIMITED, PROVIDER_LOGIN_REQUIRED,
)
from agent.providers.base import BaseProvider

logger = get_logger("ClaudeCodeProvider")


def _find_claude():
    """Find the claude CLI executable."""
    path = shutil.which("claude")
    if path:
        return path
    # Check common nix locations
    for candidate in [
        os.path.expanduser("~/.nix-profile/bin/claude"),
        "/run/current-system/sw/bin/claude",
    ]:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


class ClaudeCodeProvider(BaseProvider):
    """Real Claude Code CLI provider."""

    def __init__(self, config=None):
        self._config = config or {}
        self._claude_path = self._config.get("executable") or _find_claude()
        self._process = None
        self._cancelled = False
        self._session_id = None  # Claude's own session ID
        self._model = None

    def doctor(self):
        """Check if Claude Code is installed and logged in."""
        details = []

        if not self._claude_path:
            return {"ok": False, "details": ["Claude Code CLI not found"],
                    "error": "Install Claude Code: npm install -g @anthropic-ai/claude-code"}

        details.append(f"CLI: {self._claude_path}")

        # Check version
        try:
            result = subprocess.run(
                [self._claude_path, "--version"],
                capture_output=True, text=True, timeout=5
            )
            version = result.stdout.strip()
            details.append(f"Version: {version}")
        except Exception as e:
            details.append(f"Version check failed: {e}")

        # Check auth by running a minimal command
        try:
            result = subprocess.run(
                [self._claude_path, "-p", "--output-format", "json",
                 "--bare", "--max-budget-usd", "0", "test"],
                capture_output=True, text=True, timeout=10
            )
            output = result.stdout.strip()
            if "login" in output.lower() or "auth" in output.lower():
                return {"ok": False, "details": details,
                        "error": "Not logged in. Run: claude auth login"}
            details.append("Auth: OK")
        except subprocess.TimeoutExpired:
            details.append("Auth: timeout (may be OK)")
        except Exception as e:
            details.append(f"Auth check: {e}")

        return {"ok": True, "details": details}

    def start(self, session_external_id=None, model=None):
        """Start or resume a Claude session."""
        self._model = model
        if session_external_id:
            self._session_id = session_external_id
            return {"external_session_id": session_external_id}
        return {"external_session_id": None}  # Will be set after first send

    def send(self, messages, context=None):
        """Send messages to Claude and yield normalized events."""
        self._cancelled = False

        if not messages:
            return

        if not self._claude_path:
            yield make_event(RUN_FAILED, summary="Claude Code CLI not found",
                             error="Install Claude Code")
            return

        last_message = messages[-1].get("content_text", "")

        # Build command
        cmd = [self._claude_path, "-p",
               "--output-format", "stream-json",
               "--verbose",
               "--include-partial-messages"]

        # Add model if specified
        if self._model:
            cmd.extend(["--model", self._model])

        # Resume session if we have one
        if self._session_id:
            cmd.extend(["--resume", self._session_id])

        # Skip permissions for non-interactive use
        cmd.append("--dangerously-skip-permissions")

        # Add the prompt
        cmd.append(last_message)

        logger.info(f"Launching Claude: {' '.join(cmd[:6])}...")

        yield make_event(RUN_STARTED, summary="Sending to Claude Code")

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=context.get("cwd") if context else None,
            )

            assistant_started = False
            accumulated_text = []

            for line in self._process.stdout:
                if self._cancelled:
                    self._kill_process()
                    yield make_event(RUN_INTERRUPTED, summary="Cancelled by user")
                    return

                line = line.strip()
                if not line:
                    continue

                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Convert Claude events to normalized events
                for normalized in self._normalize_claude_event(
                        event, assistant_started, accumulated_text):
                    if normalized.get("type") == ASSISTANT_STARTED:
                        assistant_started = True
                    yield normalized

            # Wait for process to finish
            self._process.wait()

            if self._process.returncode == 0:
                if accumulated_text:
                    yield make_event(ASSISTANT_COMPLETED,
                                     summary="Response complete",
                                     full_text="".join(accumulated_text))
                yield make_event(RUN_COMPLETED, summary="Done")
            else:
                stderr = self._process.stderr.read() if self._process.stderr else ""
                yield make_event(RUN_FAILED,
                                 summary=f"Claude exited with code {self._process.returncode}",
                                 error=stderr[:500])

        except Exception as e:
            logger.error(f"Claude provider error: {e}")
            yield make_event(RUN_FAILED, summary=f"Error: {e}", error=str(e))
        finally:
            self._process = None

    def _normalize_claude_event(self, event, assistant_started, accumulated_text):
        """Convert a Claude stream-json event into normalized events."""
        event_type = event.get("type", "")
        subtype = event.get("subtype", "")

        if event_type == "system" and subtype == "init":
            # Extract Claude's session ID
            self._session_id = event.get("session_id")
            return  # No event to yield for init

        elif event_type == "assistant":
            message = event.get("message", {})
            content = message.get("content", [])

            # Check for auth error
            error = event.get("error")
            if error == "authentication_failed":
                yield make_event(PROVIDER_LOGIN_REQUIRED,
                                 summary="Login required. Run: claude auth login")
                return

            # Extract text content
            for block in content:
                if block.get("type") == "text":
                    text = block.get("text", "")
                    if text:
                        if not assistant_started:
                            yield make_event(ASSISTANT_STARTED,
                                             summary="Generating response")
                        # For partial messages, we get the full text so far each time
                        # We need to compute the delta
                        full_so_far = "".join(accumulated_text)
                        if text.startswith(full_so_far):
                            delta = text[len(full_so_far):]
                        else:
                            delta = text
                        if delta:
                            accumulated_text.clear()
                            accumulated_text.append(text)
                            yield make_event(ASSISTANT_DELTA, text=delta)

                elif block.get("type") == "tool_use":
                    tool_name = block.get("name", "tool")
                    tool_input = block.get("input", {})
                    summary = _tool_summary(tool_name, tool_input)
                    yield make_event(TOOL_STARTED, summary=summary,
                                     tool_name=tool_name)

                elif block.get("type") == "tool_result":
                    tool_name = block.get("name", "tool")
                    is_error = block.get("is_error", False)
                    if is_error:
                        yield make_event(TOOL_FAILED, summary=f"{tool_name} failed",
                                         tool_name=tool_name)
                    else:
                        yield make_event(TOOL_COMPLETED, summary=f"{tool_name} done",
                                         tool_name=tool_name)

        elif event_type == "rate_limit_event":
            info = event.get("rate_limit_info", {})
            status = info.get("status", "")
            if status != "allowed":
                yield make_event(PROVIDER_RATE_LIMITED,
                                 summary="Rate limited",
                                 resets_at=info.get("resetsAt"))

        elif event_type == "result":
            # Final result - handled by send() after stdout closes
            is_error = event.get("is_error", False)
            if is_error:
                result_text = event.get("result", "Unknown error")
                if "login" in result_text.lower():
                    yield make_event(PROVIDER_LOGIN_REQUIRED,
                                     summary="Login required. Run: claude auth login")
                else:
                    yield make_event(RUN_FAILED, summary=result_text,
                                     error=result_text)

    def cancel(self):
        """Cancel the current Claude run."""
        self._cancelled = True
        self._kill_process()

    def _kill_process(self):
        """Kill the Claude subprocess."""
        if self._process and self._process.poll() is None:
            try:
                # Send SIGTERM first
                self._process.terminate()
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            except Exception as e:
                logger.warning(f"Error killing Claude process: {e}")

    def cleanup(self):
        """Clean up provider resources."""
        self._kill_process()
        self._cancelled = False
        self._process = None


def _tool_summary(tool_name, tool_input):
    """Generate a human-readable summary for a tool use."""
    if tool_name in ("Read", "read"):
        return f"Reading {tool_input.get('file_path', 'file')}"
    elif tool_name in ("Edit", "edit"):
        return f"Editing {tool_input.get('file_path', 'file')}"
    elif tool_name in ("Write", "write"):
        return f"Writing {tool_input.get('file_path', 'file')}"
    elif tool_name in ("Bash", "bash"):
        cmd = tool_input.get("command", "")
        return f"Running: {cmd[:60]}"
    elif tool_name in ("Grep", "grep"):
        return f"Searching for '{tool_input.get('pattern', '')}'"
    elif tool_name in ("Glob", "glob"):
        return f"Finding files: {tool_input.get('pattern', '')}"
    elif tool_name in ("WebSearch", "web_search"):
        return f"Searching web: {tool_input.get('query', '')}"
    elif tool_name in ("WebFetch", "web_fetch"):
        return f"Fetching URL"
    else:
        return f"{tool_name}"
