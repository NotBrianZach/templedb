"""ClaudeCodeProvider - real Claude Code CLI integration.

Launches Claude Code as a subprocess with --output-format stream-json,
parses the streaming events, and converts them into normalized Temple Agent events.
"""
import json
import os
import shutil
import subprocess
import time

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
        self._session_id = None
        self._model = None
        self._active_tools = {}  # tool_use_id -> {name, input, start_time}

    def doctor(self):
        details = []
        if not self._claude_path:
            return {"ok": False, "details": ["Claude Code CLI not found"],
                    "error": "Install Claude Code: npm install -g @anthropic-ai/claude-code"}
        details.append(f"CLI: {self._claude_path}")
        try:
            result = subprocess.run(
                [self._claude_path, "--version"],
                capture_output=True, text=True, timeout=5)
            details.append(f"Version: {result.stdout.strip()}")
        except Exception as e:
            details.append(f"Version check failed: {e}")
        try:
            result = subprocess.run(
                [self._claude_path, "-p", "--output-format", "json",
                 "--bare", "--max-budget-usd", "0", "test"],
                capture_output=True, text=True, timeout=10)
            if "login" in result.stdout.lower():
                return {"ok": False, "details": details,
                        "error": "Not logged in. Run: claude auth login"}
            details.append("Auth: OK")
        except subprocess.TimeoutExpired:
            details.append("Auth: timeout (may be OK)")
        except Exception as e:
            details.append(f"Auth check: {e}")
        return {"ok": True, "details": details}

    def start(self, session_external_id=None, model=None):
        self._model = model
        if session_external_id:
            self._session_id = session_external_id
            return {"external_session_id": session_external_id}
        return {"external_session_id": None}

    def send(self, messages, context=None):
        self._cancelled = False
        self._active_tools = {}

        if not messages:
            return
        if not self._claude_path:
            yield make_event(RUN_FAILED, summary="Claude Code CLI not found",
                             error="Install Claude Code")
            return

        last_message = messages[-1].get("content_text", "")

        cmd = [self._claude_path, "-p",
               "--output-format", "stream-json",
               "--verbose",
               "--include-partial-messages"]
        if self._model:
            cmd.extend(["--model", self._model])
        if self._session_id:
            cmd.extend(["--resume", self._session_id])
        cmd.append("--dangerously-skip-permissions")
        cmd.append(last_message)

        logger.info(f"Launching Claude: {' '.join(cmd[:6])}...")
        yield make_event(RUN_STARTED, summary="Sending to Claude Code")

        try:
            self._process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1,
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

                for normalized in self._normalize_claude_event(
                        event, assistant_started, accumulated_text):
                    if normalized.get("type") == ASSISTANT_STARTED:
                        assistant_started = True
                    yield normalized

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
        event_type = event.get("type", "")
        subtype = event.get("subtype", "")

        if event_type == "system" and subtype == "init":
            self._session_id = event.get("session_id")
            return

        elif event_type == "assistant":
            message = event.get("message", {})
            content = message.get("content", [])

            error = event.get("error")
            if error == "authentication_failed":
                yield make_event(PROVIDER_LOGIN_REQUIRED,
                                 summary="Login required. Run: claude auth login")
                return

            for block in content:
                block_type = block.get("type", "")

                if block_type == "text":
                    text = block.get("text", "")
                    if text:
                        if not assistant_started:
                            yield make_event(ASSISTANT_STARTED,
                                             summary="Generating response")
                        full_so_far = "".join(accumulated_text)
                        if text.startswith(full_so_far):
                            delta = text[len(full_so_far):]
                        else:
                            delta = text
                        if delta:
                            accumulated_text.clear()
                            accumulated_text.append(text)
                            yield make_event(ASSISTANT_DELTA, text=delta)

                elif block_type == "tool_use":
                    tool_id = block.get("id", "")
                    tool_name = block.get("name", "tool")
                    tool_input = block.get("input", {})

                    # Track this tool for matching with results
                    self._active_tools[tool_id] = {
                        "name": tool_name,
                        "input": tool_input,
                        "start_time": time.time(),
                    }

                    summary = _tool_summary(tool_name, tool_input)
                    input_text = _tool_input_display(tool_name, tool_input)

                    yield make_event(TOOL_STARTED,
                                     summary=summary,
                                     tool_name=tool_name,
                                     tool_id=tool_id,
                                     tool_input=input_text)

                elif block_type == "tool_result":
                    tool_use_id = block.get("tool_use_id", "")
                    is_error = block.get("is_error", False)
                    result_content = block.get("content", "")

                    # Extract text from result
                    output_text = ""
                    if isinstance(result_content, list):
                        parts = []
                        for item in result_content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                parts.append(item.get("text", ""))
                            elif isinstance(item, str):
                                parts.append(item)
                        output_text = "\n".join(parts)
                    elif isinstance(result_content, str):
                        output_text = result_content

                    # Get timing from tracked tool
                    tool_info = self._active_tools.pop(tool_use_id, {})
                    tool_name = tool_info.get("name", "tool")
                    duration = None
                    if tool_info.get("start_time"):
                        duration = round(time.time() - tool_info["start_time"], 1)

                    summary = _tool_summary(tool_name, tool_info.get("input", {}))

                    if is_error:
                        yield make_event(TOOL_FAILED,
                                         summary=summary,
                                         tool_name=tool_name,
                                         tool_id=tool_use_id,
                                         tool_output=output_text[:2000],
                                         duration=duration)
                    else:
                        yield make_event(TOOL_COMPLETED,
                                         summary=summary,
                                         tool_name=tool_name,
                                         tool_id=tool_use_id,
                                         tool_output=output_text[:2000],
                                         duration=duration)

        elif event_type == "rate_limit_event":
            info = event.get("rate_limit_info", {})
            if info.get("status", "") != "allowed":
                yield make_event(PROVIDER_RATE_LIMITED,
                                 summary="Rate limited",
                                 resets_at=info.get("resetsAt"))

        elif event_type == "result":
            is_error = event.get("is_error", False)
            if is_error:
                result_text = event.get("result", "Unknown error")
                if "login" in result_text.lower():
                    yield make_event(PROVIDER_LOGIN_REQUIRED,
                                     summary="Login required. Run: claude auth login")
                else:
                    yield make_event(RUN_FAILED, summary=result_text, error=result_text)

    def cancel(self):
        self._cancelled = True
        self._kill_process()

    def _kill_process(self):
        if self._process and self._process.poll() is None:
            try:
                self._process.terminate()
                try:
                    self._process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self._process.kill()
            except Exception as e:
                logger.warning(f"Error killing Claude process: {e}")

    def cleanup(self):
        self._kill_process()
        self._cancelled = False
        self._process = None
        self._active_tools = {}


def _tool_summary(tool_name, tool_input):
    """Human-readable one-line summary for a tool use."""
    if tool_name in ("Read", "read"):
        path = tool_input.get("file_path", "file")
        return f"Read({_short_path(path)})"
    elif tool_name in ("Edit", "edit"):
        return f"Edit({_short_path(tool_input.get('file_path', 'file'))})"
    elif tool_name in ("Write", "write"):
        return f"Write({_short_path(tool_input.get('file_path', 'file'))})"
    elif tool_name in ("Bash", "bash"):
        cmd = tool_input.get("command", "")
        desc = tool_input.get("description", "")
        label = desc if desc else cmd[:60]
        return f"Bash({label})"
    elif tool_name in ("Grep", "grep"):
        return f"Grep({tool_input.get('pattern', '')})"
    elif tool_name in ("Glob", "glob"):
        return f"Glob({tool_input.get('pattern', '')})"
    elif tool_name in ("WebSearch", "web_search"):
        return f"WebSearch({tool_input.get('query', '')})"
    elif tool_name in ("WebFetch", "web_fetch"):
        return f"WebFetch"
    elif tool_name == "ToolSearch":
        return f"ToolSearch({tool_input.get('query', '')})"
    elif tool_name in ("Task", "TaskCreate"):
        return f"Task({tool_input.get('description', '')[:40]})"
    elif tool_name == "Agent":
        return f"Agent({tool_input.get('description', '')[:40]})"
    else:
        return tool_name


def _tool_input_display(tool_name, tool_input):
    """Format tool input for display in the Org buffer."""
    if tool_name in ("Bash", "bash"):
        return tool_input.get("command", "")
    elif tool_name in ("Read", "read"):
        path = tool_input.get("file_path", "")
        parts = [path]
        if tool_input.get("offset"):
            parts.append(f"offset: {tool_input['offset']}")
        if tool_input.get("limit"):
            parts.append(f"limit: {tool_input['limit']}")
        return "\n".join(parts) if len(parts) > 1 else path
    elif tool_name in ("Edit", "edit"):
        path = tool_input.get("file_path", "")
        old = tool_input.get("old_string", "")
        new = tool_input.get("new_string", "")
        if old and new:
            return f"{path}\n-{_truncate(old, 100)}\n+{_truncate(new, 100)}"
        return path
    elif tool_name in ("Write", "write"):
        path = tool_input.get("file_path", "")
        content = tool_input.get("content", "")
        return f"{path} ({len(content)} chars)"
    elif tool_name in ("Grep", "grep"):
        parts = [f"pattern: {tool_input.get('pattern', '')}"]
        if tool_input.get("path"):
            parts.append(f"path: {tool_input['path']}")
        if tool_input.get("glob"):
            parts.append(f"glob: {tool_input['glob']}")
        return "\n".join(parts)
    elif tool_name in ("Glob", "glob"):
        return tool_input.get("pattern", "")
    else:
        # Generic: show as compact JSON
        return json.dumps(tool_input, indent=2)[:500]


def _short_path(path):
    """Shorten a file path for display."""
    if not path:
        return ""
    parts = path.split("/")
    if len(parts) > 3:
        return "/".join(["..."] + parts[-3:])
    return path


def _truncate(text, max_len):
    """Truncate text with ellipsis."""
    text = text.replace("\n", "\\n")
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text
