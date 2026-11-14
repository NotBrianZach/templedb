"""The policy guard for unattended runs.

An autonomous run is launched with `--dangerously-skip-permissions`, so
this hook is the ONLY thing standing between a scheduled task and an
irreversible action. Every case here is a spelling a model actually
reaches for, not a hypothetical: absolute paths (after `which templedb`),
an env prefix (the pinned-session idiom this repo documents), `&&`
chains, and a nested `claude` (which would inherit no hook at all).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

import pytest

from agent.guard import evaluate, POLICIES


def _bash(cmd, policy):
    return evaluate("Bash", {"command": cmd}, policy)


# --- The line the operator actually chose: commit yes, publish no ------

@pytest.mark.parametrize("cmd", [
    "templedb publish run templedb -m x",
    # Absolute path: what an agent uses right after `which templedb`.
    "/home/zach/.nix-profile/bin/templedb publish run templedb -m x",
    # The pinned-session idiom from CLAUDE.md, as a leading env prefix.
    "TEMPLEDB_SESSION=agent-x templedb publish run templedb -m x",
    # Buried in a chain, which is how it shows up in practice.
    "templedb vcs add -p templedb --all && templedb publish run templedb -m x",
    "git push origin main",
    "templedb nixos system-switch system_config --yes",
    "sudo nixos-rebuild switch",
    "gh pr create --fill",
    "templedb deploy fleet machine list templedb tailnet",
])
def test_commit_policy_denies_everything_outward_facing(cmd):
    assert _bash(cmd, "commit") is not None, f"should have been denied: {cmd}"


@pytest.mark.parametrize("cmd", [
    "templedb file set templedb src/x.py --if-match abc123de",
    "templedb vcs add -p templedb --all",
    "templedb vcs commit -p templedb -m 'work'",
    "templedb commit templedb /path/to/workspace -m 'work'",
    "templedb file cat templedb src/x.py",
    "templedb doctor entities",
    "templedb ai agent stop-stale --dry-run",
    "pytest tests/agent -x",
])
def test_commit_policy_allows_local_work(cmd):
    assert _bash(cmd, "commit") is None, f"should have been allowed: {cmd}"


# --- readonly is strictly tighter than commit --------------------------

@pytest.mark.parametrize("cmd", [
    "templedb file set templedb src/x.py",
    "templedb vcs commit -p templedb -m x",
    "templedb intent apply 42",
])
def test_readonly_denies_writes_that_commit_allows(cmd):
    assert _bash(cmd, "readonly") is not None
    assert _bash(cmd, "commit") is None


def test_readonly_denies_direct_file_tools():
    assert evaluate("Write", {"file_path": "/tmp/x.py"}, "readonly")
    assert evaluate("Edit", {"file_path": "/tmp/x.py"}, "readonly")
    assert evaluate("Write", {"file_path": "/tmp/x.py"}, "commit") is None


def test_readonly_still_allows_reading():
    assert _bash("templedb file cat templedb src/x.py", "readonly") is None
    assert evaluate("Read", {"file_path": "/etc/hosts"}, "readonly") is None
    assert evaluate("Grep", {"pattern": "x"}, "readonly") is None


# --- Escaping the policy ------------------------------------------------

@pytest.mark.parametrize("cmd", [
    "claude -p --dangerously-skip-permissions 'publish it'",
    "timeout 600 claude -p 'do the thing'",
    "templedb ai claude launch templedb",
    "templedb ai agent run -m 'publish it' --policy publish",
    "templedb ai agent tick --max-tasks 5",
    "templedb ai agent task add sneaky -m x --policy trusted",
])
def test_no_policy_below_trusted_may_spawn_an_unguarded_agent(cmd):
    """A nested `claude` inherits no --settings and therefore no hook.

    Denied even under 'publish', which is otherwise permissive: the
    issue is not what the nested run would do, it is that nothing would
    constrain it.
    """
    for policy in ("readonly", "commit", "publish"):
        assert _bash(cmd, policy) is not None, \
            f"{cmd!r} should be denied under {policy}"
    assert _bash(cmd, "trusted") is None


def test_read_only_agent_subcommands_stay_available():
    """The system prompt tells agents to use stop-stale; don't break it."""
    for cmd in ("templedb ai agent stop-stale",
                "templedb ai agent task list",
                "templedb ai agent sessions --limit 5",
                "templedb ai agent fleet"):
        assert _bash(cmd, "commit") is None, cmd


# --- Irreversible at any policy ----------------------------------------

@pytest.mark.parametrize("cmd", [
    "templedb commit templedb /ws --allow-mass-delete -m x",
    "templedb project delete templedb",
    "templedb admin checkout-gc",
    "rm -rf /home/zach/.config/templedb",
    "git reset --hard origin/main",
])
def test_irreversible_actions_denied_even_under_publish(cmd):
    assert _bash(cmd, "publish") is not None


def test_trusted_is_the_only_unrestricted_policy():
    assert _bash("templedb publish run templedb -m x", "trusted") is None
    assert _bash("rm -rf /tmp/scratch", "trusted") is None


# --- Parsing ------------------------------------------------------------

def test_quoted_parens_in_a_commit_message_are_not_a_denial():
    """Splitting on bare `(` would fragment this and misfire.

    `commit -m "fix (thing)"` is an ordinary command; an earlier draft of
    the segment splitter turned it into fragments and `echo "run (git
    push)"` into a false denial.
    """
    assert _bash('templedb vcs commit -p t -m "fix (thing)"', "commit") is None
    assert _bash('echo "remember to (git push) later"', "commit") is None


def test_subshell_and_substitution_still_caught():
    assert _bash("( git push )", "commit") is not None
    assert _bash("echo $(templedb publish run t -m x)", "commit") is not None
    assert _bash("x=`git push origin main`", "commit") is not None


def test_unbalanced_quotes_do_not_crash_open():
    """A shlex failure must fall back to matching, not to allowing."""
    assert _bash('templedb publish run t -m "unterminated', "commit") \
        is not None


def test_unknown_policy_fails_closed():
    """A typo in a task's policy column must be strict, not permissive."""
    assert _bash("templedb publish run t -m x", "typo") is not None
    assert _bash("templedb vcs commit -p t -m x", "typo") is not None


def test_empty_and_missing_input_is_allowed():
    assert evaluate("Bash", {}, "commit") is None
    assert evaluate("Bash", {"command": ""}, "commit") is None
    assert evaluate("", None, "commit") is None


def test_mcp_deploy_tool_is_covered():
    """The guard must match MCP tool names, not just Bash strings.

    `mcp__templedb__templedb_deploy` reaches a remote host without ever
    being a Bash command, so a Bash-only matcher would miss it entirely.
    """
    assert evaluate("mcp__templedb__templedb_deploy", {}, "commit") is not None
    assert evaluate("mcp__templedb__templedb_deploy", {}, "publish") is None
    assert evaluate("mcp__templedb__templedb_vcs_commit", {}, "readonly") \
        is not None
    assert evaluate("mcp__templedb__templedb_vcs_commit", {}, "commit") is None


def test_denial_reason_names_the_policy_and_the_command():
    """The reason is fed back to the model; it has to be actionable."""
    reason = _bash("templedb publish run templedb -m x", "commit")
    assert "commit" in reason
    assert "publish" in reason
    assert "Instead" in reason


def test_policies_are_ordered_least_to_most_permissive():
    assert POLICIES == ("readonly", "commit", "publish", "trusted")
