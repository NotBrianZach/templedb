"""The provider must turn a run's policy into actual claude flags.

The guard logic is tested in test_guard.py; what matters here is the
wiring. A policy that never reaches the `claude` argv is a policy that
does not exist, and because the provider also passes
`--dangerously-skip-permissions`, a silently-dropped `--settings` would
leave an unattended run completely unrestricted while every CLI surface
still reported its policy.
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from agent.providers.claude_code import ClaudeCodeProvider


class _FakePopen:
    captured_cmd = None
    captured_env = None

    def __init__(self, cmd, **kwargs):
        _FakePopen.captured_cmd = list(cmd)
        _FakePopen.captured_env = dict(kwargs.get("env") or {})
        self.stdout = _EmptyStream()
        self.stderr = _EmptyStream()
        self.returncode = 0

    def wait(self):
        return 0

    def poll(self):
        return 0


class _EmptyStream:
    def read(self):
        return ""

    def readline(self):
        return ""

    def fileno(self):
        return 0


def _send(monkeypatch, context):
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    # select.select() is handed our fake stream; make it report "no data"
    # so the generator falls through to the poll()-based exit path.
    import select
    monkeypatch.setattr(select, "select", lambda *a, **k: ([], [], []))
    _FakePopen.captured_cmd = None
    provider = ClaudeCodeProvider(config={"executable": "/fake/claude"})
    for _ in provider.send([{"content_text": "do the thing"}], context):
        pass
    return _FakePopen.captured_cmd


def _flag_value(cmd, flag):
    """Return the argument following FLAG, or None if absent."""
    if flag not in cmd:
        return None
    return cmd[cmd.index(flag) + 1]


def test_policy_installs_a_pretooluse_hook(monkeypatch):
    cmd = _send(monkeypatch, {"policy": "commit", "autonomous": True})

    settings = _flag_value(cmd, "--settings")
    assert settings is not None, "no --settings; the policy was dropped"
    parsed = json.loads(settings)
    hooks = parsed["hooks"]["PreToolUse"]
    assert len(hooks) == 1
    # Matcher must not be scoped to Bash: the policy also covers
    # Edit/Write and the MCP deploy tool.
    assert hooks[0]["matcher"] == "*"
    hook_cmd = hooks[0]["hooks"][0]["command"]
    assert "ai agent guard" in hook_cmd
    assert "--policy commit" in hook_cmd


def test_trusted_policy_installs_no_hook(monkeypatch):
    cmd = _send(monkeypatch, {"policy": "trusted", "autonomous": True})
    assert _flag_value(cmd, "--settings") is None


def test_no_policy_means_no_hook_so_emacs_is_unchanged(monkeypatch):
    """An interactive run passes no policy and must behave as before."""
    cmd = _send(monkeypatch, {})
    assert _flag_value(cmd, "--settings") is None
    assert "--dangerously-skip-permissions" in cmd


def test_autonomous_prompt_replaces_the_emacs_prompt(monkeypatch):
    """The Emacs tail tells the agent to ask the user questions.

    Unattended there is nobody to answer, and templedb_ask_user blocks
    until it times out — so the autonomous run must get a different
    briefing, not an additional one.
    """
    cmd = _send(monkeypatch, {"policy": "commit", "autonomous": True,
                              "agent_session_id": 1})
    prompt = _flag_value(cmd, "--append-system-prompt")
    assert prompt is not None
    assert "UNATTENDED" in prompt
    assert "Do NOT use mcp__templedb__templedb_ask_user" in prompt
    assert "inside Emacs" not in prompt


def test_interactive_run_keeps_the_emacs_prompt(monkeypatch):
    cmd = _send(monkeypatch, {"agent_session_id": 1})
    prompt = _flag_value(cmd, "--append-system-prompt")
    if prompt is not None:  # None when `templedb` is absent from PATH
        assert "inside Emacs" in prompt
        assert "UNATTENDED" not in prompt


def test_policy_is_briefed_in_the_system_prompt(monkeypatch):
    """Tell the agent the rule, so it doesn't learn it by being denied."""
    cmd = _send(monkeypatch, {"policy": "commit", "autonomous": True})
    prompt = _flag_value(cmd, "--append-system-prompt")
    assert "COMMIT" in prompt
    assert "PreToolUse hook" in prompt


def test_session_id_and_policy_reach_the_child_env(monkeypatch):
    """A hook is spawned by claude and inherits only this env.

    Without TEMPLEDB_AGENT_SESSION_ID the guard can still deny, but the
    denial lands nowhere a human will ever see it.
    """
    _send(monkeypatch, {"policy": "commit", "autonomous": True,
                        "agent_session_id": 42})
    env = _FakePopen.captured_env
    assert env.get("TEMPLEDB_AGENT_SESSION_ID") == "42"
    assert env.get("TEMPLEDB_AGENT_POLICY") == "commit"
