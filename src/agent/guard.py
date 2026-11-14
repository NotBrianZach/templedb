"""Policy guard for unattended agent runs.

An autonomous run has nobody watching the permission prompt, and the
provider launches Claude with `--dangerously-skip-permissions` (see
src/agent/providers/claude_code.py) because an interactive prompt in a
`-p` subprocess has no UI to answer it. So the only place a policy can
be enforced is a PreToolUse hook, which runs regardless of permission
mode.

`evaluate()` is the whole policy: a pure function from (tool_name,
tool_input, policy) to an optional denial reason. The CLI entry point
(`templedb ai agent guard`) is a thin stdin/stdout wrapper around it so
the decision logic is unit-testable without a subprocess.

── What this is and is not ─────────────────────────────────────────────

This is a speed bump on the *direct* paths to an irreversible action,
not a sandbox. It denies `templedb publish run` and the dozen spellings
of it that a model actually reaches for. It cannot stop an agent that
writes the command into a file and executes that, or base64-decodes it
-- a PreToolUse hook sees one tool call at a time and has no way to know
what a script will do when run.

Treat it accordingly: it keeps a *well-behaved* run inside its lane,
which is the actual failure mode (a model that reads "commit your work"
and reasonably decides publishing is implied). If you need a guarantee
rather than a lane marker, the enforcement has to sit where the
irreversible thing happens -- a push needs credentials, so withhold
them -- not in the agent's own process.
"""
import os
import re
import shlex

# Policy ordering, least to most permitted. A policy permits everything
# the policies before it permit.
POLICIES = ("readonly", "commit", "publish", "trusted")

DEFAULT_POLICY = "commit"


# Denial rules as (min_policy, pattern, reason, suggestion).
#
# `min_policy` is the first policy in POLICIES ALLOWED to do this; every
# policy before it is denied. Patterns match a normalized single command
# segment (see `_segments`) and are compiled once at import.
_RAW_RULES = [
    # ── Reaches outside this machine, or changes what boots ───────────
    # Denied below 'publish'. These are the actions whose blast radius
    # leaves the DB: the public GitHub mirror, a deployed host, or the
    # running system closure.
    ("publish", r"^templedb\s+publish\b",
     "`publish run` commits AND materializes AND pushes",
     "stage the work and let the operator publish it"),
    ("publish", r"^templedb\s+nixos\b",
     "a nixos rebuild changes what this machine boots",
     "describe the change; an operator runs the switch"),
    ("publish", r"^templedb\s+deploy\b",
     "deploy reaches a remote host",
     None),
    ("publish", r"^templedb\s+sync\s+(push|serve)\b",
     "sync push/serve exposes or writes another node's DB",
     None),
    ("publish", r"^templedb\s+reconcile\b",
     "reconcile opens SSH sessions to fleet machines",
     "`templedb doctor` is the passive equivalent"),
    ("publish", r"^git\s+push\b",
     "git push reaches the remote",
     None),
    ("publish", r"^gh\s+(pr\s+(create|merge)|release\b|repo\s+(create|delete))",
     "this publishes to GitHub",
     None),
    ("publish", r"^nixos-rebuild\b",
     "a nixos rebuild changes what this machine boots",
     None),
    ("publish", r"^(nix\s+(copy|run)|nix-copy-closure)\b",
     "this can push a closure to a remote store",
     None),

    # ── Mutates tracked content ───────────────────────────────────────
    # Denied below 'commit'. A readonly task may read anything and write
    # findings, but may not change source.
    ("commit", r"^templedb\s+file\s+set\b",
     "`file set` replaces the whole file",
     "a readonly task should report the diff, not apply it"),
    ("commit", r"^templedb\s+(vcs\s+)?commit\b",
     "committing is a write",
     None),
    ("commit", r"^templedb\s+vcs\s+(add|reset|merge|switch|branch)\b",
     "this mutates VCS state",
     None),
    ("commit", r"^templedb\s+intent\s+apply\b",
     "`intent apply` rewrites file_contents",
     None),
    ("commit", r"^templedb\s+admin\s+db\s+migrate\b",
     "a migration changes the schema under the deployed binary",
     None),
    ("commit", r"^templedb\s+storage\s+blob\s+migrate\b",
     "this rewrites blob storage",
     None),

    # ── Would escape this run's own policy ────────────────────────────
    # The guard is injected per-run as a PreToolUse hook on the Claude
    # subprocess the provider launches. A *nested* `claude` started from
    # a Bash tool inherits none of that -- no --settings, no hook, and
    # the agent would reasonably pass --dangerously-skip-permissions to
    # make it non-interactive. That nested run could then publish. So
    # spawning one is denied below 'trusted' no matter what the task is
    # allowed to do itself.
    ("trusted", r"^claude\b",
     "a nested `claude` would not inherit this run's policy guard",
     "use the Agent tool for subagents -- it stays inside this process"),
    ("trusted", r"^templedb\s+ai\s+claude\s+launch\b",
     "this launches an unguarded Claude",
     None),
    ("trusted", r"^templedb\s+ai\s+agent\s+(run|tick|serve|resume)\b",
     "starting another agent run from inside one would not inherit this "
     "run's policy, and can recurse",
     "`templedb ai agent stop-stale` and the read-only subcommands are "
     "still available"),
    ("trusted", r"^templedb\s+ai\s+agent\s+task\s+(add|rm|remove|enable|disable|set)\b",
     "an unattended run editing its own queue is self-replication",
     "`task list` and `task show` are still available"),

    # ── Irreversible at any policy below 'trusted' ────────────────────
    # Not "dangerous because unattended" -- dangerous full stop, and
    # each one is a real incident in this repo's history. An unattended
    # run has no reason to reach for any of them, so the rule costs
    # nothing and the one time it fires it will matter.
    ("trusted", r"--allow-mass-delete\b",
     "this flag overrides the guard against deleting most of a project",
     "if the deletion is real, an operator should confirm it"),
    ("trusted", r"^templedb\s+project\s+(delete|remove)\b",
     "deleting a project is not recoverable from the DB",
     None),
    ("trusted", r"^templedb\s+project\s+checkout\b.*--force\b",
     "`checkout --force` stray-purges enclosed checkouts",
     None),
    ("trusted", r"^templedb\s+admin\s+checkout-gc\b",
     "checkout-gc cascades and orphans File entities",
     None),
    ("trusted", r"^rm\s+(-[a-zA-Z]*[rR][a-zA-Z]*f|-[a-zA-Z]*f[a-zA-Z]*[rR])",
     "recursive force delete",
     None),
    ("trusted", r"^git\s+(reset\s+--hard|clean\s+-[a-zA-Z]*[dfx])",
     "this discards uncommitted work in a checkout",
     None),
]

RULES = tuple(
    (min_policy, re.compile(pattern), reason, suggestion)
    for min_policy, pattern, reason, suggestion in _RAW_RULES
)


# Tools that write files directly, bypassing `templedb file set`.
_WRITE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit", "MultiEdit"})

# MCP tools, keyed by the policy that first permits them.
_MCP_MIN_POLICY = {
    "mcp__templedb__templedb_deploy": "publish",
    "mcp__templedb__templedb_vcs_commit": "commit",
    "mcp__templedb__templedb_config_set": "commit",
    "mcp__templedb__templedb_secret": "commit",
}


def _rank(policy):
    try:
        return POLICIES.index(policy)
    except ValueError:
        # An unknown policy is treated as the strictest rather than the
        # most permissive. A typo in a task row should fail closed.
        return 0


# Wrappers to skip when finding the real command word.
_WRAPPERS = frozenset({
    "env", "sudo", "doas", "nohup", "command", "exec", "time", "timeout",
    "stdbuf", "nice", "ionice", "xargs",
})


def _strip_env_prefix(tokens):
    """Drop leading `VAR=value` assignments and wrapper commands.

    `TEMPLEDB_SESSION=x templedb publish run`, `sudo nixos-rebuild` and
    `timeout 60 claude -p ...` all have to match the same rules as the
    bare command.
    """
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tok):
            i += 1
        elif tok in _WRAPPERS:
            i += 1
        elif tok.startswith("-") or tok.isdigit():
            # A flag or numeric argument belonging to the wrapper we just
            # skipped (`sudo -u zach`, `timeout 60`).
            i += 1
        else:
            break
    return tokens[i:]


def _normalize(segment):
    """Reduce one command segment to `basename arg arg ...`.

    Absolute paths have to match too: an agent that has just run `which
    templedb` will happily use the full path it got back.
    """
    # Strip subshell/grouping punctuation and redirections that can sit
    # in front of the command word. `( git push )` and `{ git push; }`
    # both run git.
    segment = segment.strip().lstrip("({ \t").strip()
    if not segment:
        return ""
    try:
        tokens = shlex.split(segment)
    except ValueError:
        # Unbalanced quotes -- fall back to whitespace splitting rather
        # than letting the guard crash open.
        tokens = segment.split()
    tokens = _strip_env_prefix(tokens)
    if not tokens:
        return ""
    tokens[0] = os.path.basename(tokens[0])
    return " ".join(tokens)


# Shell separators that start a new command. `$(` and a backtick are
# included because `$(git push)` executes; bare `(` is NOT, because
# splitting on it turns `commit -m "fix (thing)"` into fragments and
# `echo "run (git push)"` into a false denial. Leading `(` is handled by
# `_normalize` instead.
_SEP = re.compile(r"&&|\|\||[;\n|&]|\$\(|`")


def _segments(command):
    """Split a Bash command string into individually-checked segments."""
    return [
        norm for norm in (
            _normalize(s) for s in _SEP.split(command or "") if s and s.strip()
        )
        if norm
    ]


def evaluate(tool_name, tool_input, policy=DEFAULT_POLICY):
    """Return a denial reason string, or None to allow.

    Pure: no DB, no filesystem, no environment beyond `os.path.basename`.
    """
    rank = _rank(policy)
    tool_input = tool_input or {}

    # Direct file-writing tools.
    if tool_name in _WRITE_TOOLS and rank < _rank("commit"):
        path = tool_input.get("file_path", "<file>")
        return (
            f"policy '{policy}' forbids editing files ({tool_name} on {path}).\n"
            f"  This task is analysis-only. Record what you would change "
            f"instead of changing it."
        )

    # MCP tools, matched by exact name.
    min_policy = _MCP_MIN_POLICY.get(tool_name)
    if min_policy and rank < _rank(min_policy):
        return (
            f"policy '{policy}' forbids {tool_name} "
            f"(requires '{min_policy}' or higher)."
        )

    if tool_name != "Bash":
        return None

    command = tool_input.get("command", "")
    if not command:
        return None

    for segment in _segments(command):
        for min_policy, pattern, reason, suggestion in RULES:
            if rank >= _rank(min_policy):
                continue
            if pattern.search(segment):
                msg = (
                    f"policy '{policy}' forbids this command: {reason}.\n"
                    f"  Blocked: {segment[:200]}"
                )
                if suggestion:
                    msg += f"\n  Instead: {suggestion}"
                return msg
    return None
