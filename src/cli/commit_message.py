#!/usr/bin/env python3
"""Where a commit message comes from, for every command that takes one.

`-m` cannot carry this codebase's own prose. An inline message is a
double-quoted shell string, so each backtick span in it is
command-substituted before argv is built: commit 217092EC lost three
quoted command names, printed three "command not found" lines on
stderr, and reported success. The failure is quiet — the rest of the
message renders normally — and messages here quote CLI commands
constantly, so `-m` is the form that corrupts prose.

**A multi-line `-m` is therefore refused**, since 2026-11-11. Writing
that hazard down here was not enough: the same trap was hit twice more
in one session by someone who had already read this paragraph, because
"remember to use -F for prose" is a judgement call made at exactly the
moment attention is on the prose. The rule is now structural — a subject
goes in `-m`, a body comes from `-F` — so there is nothing left to
remember. See `resolve_message`.

Shared rather than copied because there are two commit commands with
near-identical names and very different blast radius (`vcs commit -p`,
staged-only and session-scoped; `templedb commit <slug> <dir>`, which
diffs a whole directory). `vcs commit` got `-F` first and the whole-tree
one did not, which left the more dangerous command as the only one that
could still eat a message.
"""
import os
import re
import shlex
import sys
from pathlib import Path
from typing import List, Optional

from logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# The residual hole, and why it was not one
# ---------------------------------------------------------------------------
#
# This file used to end its guard with: "a single-line -m containing
# backticks is still corruptible, and nothing here can detect it, because
# by the time argv exists the substitution has already happened and the
# evidence is gone."
#
# The first clause is true and the second is false. Two facts recover the
# evidence:
#
#  1. A backtick that SURVIVES into argv was never a substitution — it was
#     single-quoted or backslash-escaped, so that spelling is already safe
#     and needs no detection. Only the vanished ones are the bug.
#  2. The shell that performed the substitution is this process's parent,
#     and a non-interactive shell holds its whole `-c` string in
#     /proc/<pid>/cmdline — UNEXPANDED. `shlex` re-reads that string
#     without substituting anything, so the original message is available
#     to compare against the one argv received.
#
# That covers the case this actually keeps happening in — an agent or
# script invoking through `bash -c` — and degrades to no protection, never
# to a false refusal, for an interactive shell whose cmdline is just
# "-bash".
#
# WHAT IS REFUSED IS LOSS, NOT EXPANSION, and that distinction is the
# whole reason this needs no opt-out flag. `-m "bump to $(git rev-parse
# --short HEAD)"` is a deliberate interpolation that produces text, and
# refusing it would be this guard overreaching into a legitimate use. The
# bug is a span that collapsed to NOTHING: a command that does not exist,
# or an unset variable. So the test is not "did the shell change this" but
# "did the shell delete part of this", which is exactly the silent failure
# and nothing else.

_SHELLS = frozenset({'bash', 'sh', 'dash', 'zsh', 'ksh', 'mksh', 'busybox'})

# Everything the shell replaces with the output of something else.
#
# Both command-substitution spellings plus parameter expansion, because an
# unset `$FOO` vanishing out of a commit message is the same silent loss as
# a backticked word and arrives by the same route. Nested `$( $() )` is
# deliberately not matched — the pattern then finds nothing, which costs a
# detection rather than inventing one.
_EXPANSION = re.compile(
    r'`[^`]*`'                      # `cmd`
    r'|\$\([^()]*\)'                # $(cmd)
    r'|\$\{[^}]*\}'                 # ${VAR}
    r'|\$[A-Za-z_][A-Za-z0-9_]*'    # $VAR
)

# What bash itself unescapes inside double quotes. Applied so the SAFE
# spelling is recognised as safe outright, rather than by falling through
# the comparison below — Python's shlex leaves `\<backtick>` as two
# characters where bash leaves one.
_DQ_ESCAPE = re.compile(r'\\([`$"\\])')


def _raw_shell_command() -> Optional[str]:
    """The parent shell's unexpanded `-c` string, or None.

    None for every case that is not a non-interactive shell parent: no
    /proc, a parent that is not a shell, an interactive shell (no `-c`).
    All of them mean "no evidence available", and the caller's correct
    response is to let the message through — a guard that guessed here
    would refuse good commits on platforms where it simply cannot see.
    """
    try:
        with open(f'/proc/{os.getppid()}/cmdline', 'rb') as handle:
            raw = handle.read()
    except OSError:
        return None
    argv = [part.decode('utf-8', 'replace') for part in raw.split(b'\0') if part]
    if not argv or os.path.basename(argv[0]) not in _SHELLS:
        return None
    try:
        return argv[argv.index('-c') + 1]
    except (ValueError, IndexError):
        return None


def _inline_arguments(raw_command: str, depth: int = 0) -> List[str]:
    """Every `-m` argument in the raw command line, unexpanded.

    A list because one shell line can hold several commands — `a -m x &&
    b -m y` — and this function has no way to know which one is us. The
    caller handles that ambiguity conservatively.

    RECURSIVE, because the command is often not at the top level. An
    agent harness wraps it (`bash -c "… eval 'templedb … -m \"…\"' …"`),
    and so do `ssh host '…'`, `su -c '…'` and every `eval`. One shlex
    pass over the outer string returns that whole inner command as a
    single token, `-m` never appears as a token of its own, and the
    detector finds nothing — which is how the first version of this
    silently did nothing in exactly the setting that motivated it.
    Measured: 38 tokens recovered, 0 candidates, before this recursed.

    Descending into any token that still looks like a command line is
    safe in the only direction that matters. A false candidate cannot
    cause a refusal: the caller demands that deleting every expansion
    from a candidate yields the received message EXACTLY, and prose that
    merely mentions `-m` will not. It can only ever find the real one.
    """
    if depth > 3:
        return []
    try:
        tokens = shlex.split(raw_command)
    except ValueError:
        # Unbalanced quotes. The string is not something to reason about,
        # and the shell already ran it, so this is not the place to object.
        return []

    found = [tokens[i + 1] for i, token in enumerate(tokens[:-1])
             if token in ('-m', '--message')]
    for token in tokens:
        # A token holding a whole command line, rather than being one
        # argument. Guarded on the flag appearing WITH a space after it so
        # that a plain word is not re-lexed at every level.
        if ('-m ' in token or '--message ' in token) and token != raw_command:
            found.extend(_inline_arguments(token, depth + 1))
    return found


def collapsed_expansion(inline: str, raw_command: Optional[str]) -> Optional[str]:
    """The text the shell replaced with nothing, or None if nothing was lost.

    Returns the ORIGINAL argument, so the caller can show the author what
    they wrote and what arrived. See the module header for why loss rather
    than expansion is the thing being detected.
    """
    if not inline or not raw_command:
        return None

    candidates = _inline_arguments(raw_command)
    # The literal survived: nothing was expanded on the way in. Checked in
    # both spellings because `-m 'a `b` c'` reaches argv verbatim while
    # `-m "a \`b\` c"` reaches it unescaped by one level.
    if any(inline in (raw, _DQ_ESCAPE.sub(r'\1', raw)) for raw in candidates):
        return None

    for raw in candidates:
        if not _EXPANSION.search(raw):
            continue
        # The equality is the proof. If deleting every expansion from the
        # original yields exactly what argv holds, then every one of them
        # produced nothing — which no deliberate interpolation does.
        if _EXPANSION.sub('', raw) == inline:
            return raw
    return None


def add_message_args(parser, *, required_hint: bool = True) -> None:
    """Register -m/--message and -F/--message-file on a commit parser.

    Neither is `required=True`: one of the two must be present rather
    than specifically that one, and argparse cannot express that. The
    check lives in resolve_message, which is also where the error gets
    to name both options.
    """
    parser.add_argument(
        '-m', '--message',
        help='Commit message — ONE LINE only. A body must come from -F; '
             'see resolve_message for why that is enforced rather than '
             'advised.')
    parser.add_argument(
        '-F', '--message-file', metavar='PATH',
        help='Read the commit message from a file (safe for backticks '
             'and $; use "-" for stdin)')


def resolve_message(args) -> Optional[str]:
    """The message, from -m or -F. None means refuse — the caller exits 1.

    Reads through getattr so a caller that builds an argparse Namespace
    by hand keeps working: publish constructs a four-field one with no
    message_file attribute and calls VCSCommands.commit in-process.
    """
    inline = getattr(args, 'message', None)
    path = getattr(args, 'message_file', None)

    if inline and path:
        logger.error("Pass either -m or -F, not both.")
        return None

    if path:
        try:
            text = sys.stdin.read() if path == '-' else Path(path).read_text()
        except OSError as e:
            logger.error(f"Could not read the message file {path}: {e}")
            return None
        # Trailing newlines only. Leading whitespace can be deliberate
        # and the body's indentation certainly is.
        text = text.rstrip('\n')
        if not text.strip():
            logger.error(f"{path} holds no message.")
            return None
        return text

    if not inline:
        logger.error('A commit message is required: -m "…" or -F <path> '
                     '(-F for anything with backticks).')
        return None

    # A BODY MAY NOT COME FROM -m. This is the guard, and it is a refusal
    # rather than a warning on purpose.
    #
    # The docstring above has described this hazard since commit 217092EC
    # ate three command names, and describing it did not work: the same
    # trap was hit twice more in one session by someone who had already
    # written the warning down. "Remember to use -F for prose" is a
    # judgement call made at the moment of writing prose, which is the
    # worst moment to be making it, and the failure is silent — the rest
    # of the message renders, so nothing prompts a second look.
    #
    # A newline is the right line to draw because it is exactly the
    # boundary between the two uses. A subject is one line and is
    # typically backtick-free; a body quotes commands constantly in this
    # codebase. Refusing multi-line -m makes the safe path the only path
    # for bodies, and leaves the convenient path intact for subjects.
    #
    # NOT a length rule as well. A threshold would reintroduce the thing
    # being removed — "is 119 characters still fine?" is a judgement call,
    # and a magic number is a worse rule than a structural one.
    #
    # The residual hole — a single-line -m whose backticks were eaten — is
    # now caught too, by `collapsed_expansion` below. See the module header:
    # the evidence is not gone, it is in the parent shell's cmdline.
    # An in-process caller is exempt, and the exemption is about PROVENANCE
    # rather than about trust.
    #
    # The hazard is shell command substitution, which happens only on the
    # way into argv. `publish` resolves its own -m/-F and then calls
    # VCSCommands.commit in-process with a hand-built Namespace; that
    # string never passed through a shell, so a newline in it means a real
    # body from a file and not a corrupted one. Without this, a legitimate
    # `publish run -F body.txt` would be refused by a guard aimed at a
    # danger it cannot be in.
    #
    # Named for what it asserts, and only ever set by code. Nothing parses
    # it from the command line.
    if '\n' in inline and not getattr(args, 'message_is_internal', False):
        logger.error(
            'A multi-line message must come from a file, not -m.\n'
            '\n'
            'Inline messages are double-quoted shell strings, so every '
            'backtick span in one is command-substituted before this '
            'program sees it. The quoted word disappears, the rest of the '
            'message renders normally, and the commit reports success — '
            'which is why this is refused rather than warned about.\n'
            '\n'
            'Write it with a quoted heredoc, which disables substitution '
            'entirely, and pass the file:\n'
            '\n'
            "    cat > /tmp/msg.txt <<'EOF'\n"
            '    subject line\n'
            '\n'
            '    Body prose, with `backticks`, $vars and ! all safe.\n'
            '    EOF\n'
            '    … -F /tmp/msg.txt\n'
            '\n'
            'Use -m for a one-line subject.'
        )
        return None

    # THE ONE-LINE CASE, which the newline rule above cannot reach.
    #
    # Exempt for the same provenance reason: an in-process caller's string
    # never passed through a shell, so there is no parent command line that
    # means anything about it.
    if not getattr(args, 'message_is_internal', False):
        original = collapsed_expansion(inline, _raw_shell_command())
        if original is not None:
            logger.error(
                'The shell deleted part of this message before it got here.\n'
                '\n'
                f'  you wrote:  -m "{original}"\n'
                f'  I received: "{inline}"\n'
                '\n'
                'Every backtick span in a double-quoted shell string is run '
                'as a command and replaced by its output — which for a '
                'quoted identifier is nothing at all, plus a "command not '
                'found" on stderr that scrolls past. The commit would have '
                'succeeded with the word missing.\n'
                '\n'
                'Single-quote the message, escape the backticks, or pass a '
                'file:\n'
                '\n'
                f"    … -m '{original}'\n"
                "    … -F /tmp/msg.txt\n"
                '\n'
                'A deliberate substitution that produces text is not '
                'refused — only one that produced nothing.'
            )
            return None

    return inline
