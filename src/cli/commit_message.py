#!/usr/bin/env python3
"""Where a commit message comes from, for every command that takes one.

`-m` cannot carry this codebase's own prose. An inline message is a
double-quoted shell string, so each backtick span in it is
command-substituted before argv is built: commit 217092EC lost three
quoted command names, printed three "command not found" lines on
stderr, and reported success. The failure is quiet — the rest of the
message renders normally — and messages here quote CLI commands
constantly, so `-m` is the form that corrupts prose.

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
    parser.add_argument('-m', '--message', help='Commit message')
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
    return inline
