#!/usr/bin/env python3
"""Where a commit message may come from.

The assertion that matters is `test_multiline_inline_is_refused`. Every
other case here is scaffolding around it.

A double-quoted inline message is command-substituted by the shell before
argv exists, so a backtick span in one is replaced by the output of
running its contents — usually nothing, plus a "command not found" on
stderr that scrolls past. Commit 217092EC lost three quoted command names
that way and reported success.

`cli/commit_message.py` has documented that hazard for a while, and
documenting it did not work: the same trap was hit twice more in one
session by someone who had already written the warning. So the rule is
structural now — a subject goes in -m, a body comes from -F — and this
file is what keeps it structural. If somebody relaxes it back to a
warning, these fail.

Run: python3 -m pytest tests/unit/test_commit_message.py
"""
import sys
import unittest
from argparse import ArgumentParser, Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from cli.commit_message import add_message_args, resolve_message


class TestResolveMessage(unittest.TestCase):

    def test_single_line_inline_is_accepted(self):
        """A subject is the one thing -m is still for."""
        self.assertEqual(
            resolve_message(Namespace(message="reports: rows, not files",
                                      message_file=None)),
            "reports: rows, not files",
        )

    def test_multiline_inline_is_refused(self):
        """THE POINT OF THIS FILE.

        None means refuse; the caller exits 1. A body in -m is the shape
        that silently loses backticked words, so it is rejected before it
        can reach a commit rather than warned about afterwards.
        """
        self.assertIsNone(
            resolve_message(Namespace(
                message="subject\n\nBody prose quoting `vcs commit`.",
                message_file=None,
            ))
        )

    def test_a_bare_trailing_newline_is_still_refused(self):
        """No special case for the easy-looking version.

        A trailing newline is harmless in itself, but carving an exception
        for it means deciding which newlines are benign — which is the
        judgement call the refusal exists to delete.
        """
        self.assertIsNone(
            resolve_message(Namespace(message="subject\n", message_file=None))
        )

    def test_multiline_from_a_file_is_accepted(self):
        """The same body is fine once it comes from -F.

        A heredoc with a quoted delimiter performs no substitution, so the
        backticks arrive intact. That is the whole mechanism.
        """
        import tempfile
        body = "subject\n\nBody prose quoting `vcs commit` and $HOME.\n"
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(body)
            path = f.name
        got = resolve_message(Namespace(message=None, message_file=path))
        # Trailing newlines are stripped; the backticks and $ are not.
        self.assertEqual(got, body.rstrip("\n"))
        self.assertIn("`vcs commit`", got)
        self.assertIn("$HOME", got)

    def test_internal_callers_may_pass_a_body(self):
        """The exemption is about provenance, not trust.

        `publish` resolves its own -m/-F and then calls
        VCSCommands.commit in-process with a hand-built Namespace. That
        string never went through a shell, so a newline in it means a real
        body from a file. Without the exemption, `publish run -F body.txt`
        would be refused by a guard aimed at a danger it cannot be in.
        """
        body = "subject\n\nBody quoting `vcs commit`."
        self.assertEqual(
            resolve_message(Namespace(
                message=body, message_file=None, message_is_internal=True
            )),
            body,
        )

    def test_the_exemption_is_off_by_default(self):
        """Absent means not exempt — the flag is only ever set by code."""
        body = "subject\n\nbody"
        self.assertIsNone(
            resolve_message(Namespace(message=body, message_file=None))
        )
        self.assertIsNone(
            resolve_message(Namespace(
                message=body, message_file=None, message_is_internal=False
            ))
        )

    def test_both_options_is_refused(self):
        self.assertIsNone(
            resolve_message(Namespace(message="x", message_file="/dev/null"))
        )

    def test_neither_option_is_refused(self):
        self.assertIsNone(
            resolve_message(Namespace(message=None, message_file=None))
        )

    def test_empty_file_is_refused(self):
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("\n\n   \n")
            path = f.name
        self.assertIsNone(
            resolve_message(Namespace(message=None, message_file=path))
        )

    def test_unreadable_file_is_refused_not_raised(self):
        """A missing path is a message to the user, not a traceback."""
        self.assertIsNone(
            resolve_message(Namespace(
                message=None, message_file="/nonexistent/nope.txt"
            ))
        )

    def test_namespace_without_message_file_still_works(self):
        """publish builds a Namespace by hand with no message_file.

        resolve_message reads through getattr for exactly this caller, so
        a missing attribute must not raise.
        """
        self.assertEqual(
            resolve_message(Namespace(message="publish subject")),
            "publish subject",
        )

    def test_help_text_says_one_line(self):
        """The constraint is discoverable from --help, not only on failure."""
        parser = ArgumentParser()
        add_message_args(parser)
        help_text = parser.format_help()
        self.assertIn("ONE LINE", help_text)
        self.assertIn("-F", help_text)


if __name__ == "__main__":
    unittest.main()
