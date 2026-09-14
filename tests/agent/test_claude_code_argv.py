"""Regression: ClaudeCodeProvider.send() must insert `--` before the
prompt so a user message starting with `-` isn't misparsed as an option.

Bug context: on 2026-09-13 a run failed with `error: unknown option
'- **Reprovision from scratch**...'` because commander.js in the
claude CLI treated the leading dash as a flag.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from agent.providers.claude_code import ClaudeCodeProvider


class _FakePopen:
    """Captures the argv, then acts like a Popen that exits cleanly with
    no stdout — enough for the generator to reach the wait/returncode
    path without launching a real subprocess."""

    captured_cmd = None

    def __init__(self, cmd, **kwargs):
        _FakePopen.captured_cmd = list(cmd)
        self.stdout = iter([])
        self.stderr = _EmptyStream()
        self.returncode = 0

    def wait(self):
        return 0

    def poll(self):
        return 0


class _EmptyStream:
    def read(self):
        return ""


def _drain(gen):
    for _ in gen:
        pass


def test_dash_leading_prompt_gets_double_dash_separator(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)

    provider = ClaudeCodeProvider(config={"executable": "/fake/claude"})
    prompt = "- **Reprovision from scratch** using nixos-anywhere..."
    _drain(provider.send([{"content_text": prompt}]))

    cmd = _FakePopen.captured_cmd
    assert cmd is not None, "Popen was never invoked"
    assert prompt in cmd, "prompt not passed to claude"
    prompt_idx = cmd.index(prompt)
    assert "--" in cmd, f"expected `--` separator in argv: {cmd}"
    dashdash_idx = cmd.index("--")
    assert dashdash_idx < prompt_idx, (
        f"`--` must appear before prompt; got --@{dashdash_idx}, "
        f"prompt@{prompt_idx}: {cmd}"
    )


def test_normal_prompt_still_works(monkeypatch):
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)

    provider = ClaudeCodeProvider(config={"executable": "/fake/claude"})
    prompt = "hello, how are you"
    _drain(provider.send([{"content_text": prompt}]))

    cmd = _FakePopen.captured_cmd
    assert prompt == cmd[-1], f"prompt should be last argv element: {cmd}"


def test_double_dash_precedes_prompt_even_with_mcp_config(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "Popen", _FakePopen)
    # Steer _write_mcp_config to a no-op by pretending templedb isn't on PATH,
    # so the mcp branch doesn't try to shutil.which() a real binary.
    monkeypatch.setattr(
        "agent.providers.claude_code.shutil.which", lambda _: None
    )

    provider = ClaudeCodeProvider(config={"executable": "/fake/claude"})
    prompt = "-abc could be misread as flags"
    _drain(provider.send(
        [{"content_text": prompt}],
        context={"agent_session_id": 999},
    ))

    cmd = _FakePopen.captured_cmd
    assert "--" in cmd
    assert cmd.index("--") < cmd.index(prompt)
