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
import sys
from pathlib import Path
from typing import Optional

from logger import get_logger

logger = get_logger(__name__)


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
    # The residual hole is honest and small: a single-line -m containing
    # backticks is still corruptible, and nothing here can detect it,
    # because by the time argv exists the substitution has already
    # happened and the evidence is gone.
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

    return inline
