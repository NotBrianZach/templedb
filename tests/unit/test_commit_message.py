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

from cli.commit_message import (
    add_message_args, collapsed_expansion, resolve_message,
)


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


class TestCollapsedExpansion(unittest.TestCase):
    """The single-line hole the newline rule cannot reach.

    This file used to rest on the claim that a one-line `-m` with
    backticks was undetectable, "because by the time argv exists the
    substitution has already happened and the evidence is gone". It is
    not gone: a non-interactive parent shell holds its whole `-c` string
    in /proc/<pid>/cmdline, unexpanded, and shlex re-reads it without
    substituting. So the original and the arrival can be compared.

    The distinction every test here turns on is LOSS versus EXPANSION. A
    span that produced nothing is the bug; a span that produced text is a
    deliberate interpolation and must still work, which is why this needs
    no opt-out flag.
    """

    # What bash would really have put in argv for each raw line below,
    # written out rather than computed, so a wrong expectation is visible.
    def test_eaten_backtick_span_is_detected(self):
        self.assertEqual(
            collapsed_expansion(
                "docs: see  for the rule",
                'templedb vcs commit -p x -m "docs: see `vcs commit` for the rule"',
            ),
            "docs: see `vcs commit` for the rule",
        )

    def test_it_returns_the_original_so_the_error_can_show_it(self):
        original = collapsed_expansion(
            "fix ", 'tdb commit -m "fix `resolve_message`"')
        self.assertEqual(original, "fix `resolve_message`")

    def test_single_quoted_backticks_survive_and_are_not_refused(self):
        """The safe spelling. argv holds the backticks, so nothing was lost."""
        self.assertIsNone(collapsed_expansion(
            "docs: see `vcs commit` for the rule",
            "templedb vcs commit -m 'docs: see `vcs commit` for the rule'",
        ))

    def test_escaped_backticks_survive_and_are_not_refused(self):
        r"""The other safe spelling: \` inside double quotes.

        Python's shlex leaves the backslash where bash removes it, so the
        recovered token is compared in both forms. Without that, this
        correct message would be reported as corrupted.
        """
        self.assertIsNone(collapsed_expansion(
            "docs: see `vcs commit` for the rule",
            r'templedb vcs commit -m "docs: see \`vcs commit\` for the rule"',
        ))

    def test_a_substitution_that_produced_text_is_allowed(self):
        """THE CASE THAT KEEPS THIS FROM OVERREACHING.

        A deliberate interpolation is a legitimate use of -m. Refusing it
        would make this guard a nuisance that gets switched off, and it is
        distinguishable for free: deleting the spans from the original
        does not yield what argv holds, because the span produced output.
        """
        self.assertIsNone(collapsed_expansion(
            "bump to a1b2c3d",
            'templedb vcs commit -m "bump to $(git rev-parse --short HEAD)"',
        ))

    def test_an_unset_variable_that_vanished_is_also_detected(self):
        """Same silent loss, same route, so it is the same bug."""
        self.assertEqual(
            collapsed_expansion(
                "deploy to  tonight",
                'templedb vcs commit -m "deploy to $TARGET_HOST tonight"',
            ),
            "deploy to $TARGET_HOST tonight",
        )

    def test_a_set_variable_is_allowed(self):
        self.assertIsNone(collapsed_expansion(
            "released by zach",
            'templedb vcs commit -m "released by $USER"',
        ))

    def test_a_nested_command_line_is_still_searched(self):
        """THE CASE THE FIRST VERSION MISSED, in the setting that motivated it.

        The command is usually not at the top level of the shell string:
        an agent harness wraps it in `eval '…'`, and so do ssh and su. One
        shlex pass returns the whole inner command as a single token, so
        `-m` is not a token and nothing is found. Measured against the
        real wrapper: 38 tokens, 0 candidates, until the scan recursed.
        """
        self.assertEqual(
            collapsed_expansion(
                "docs: see  rule",
                """bash -c 'cd /tmp && eval "templedb vcs commit -m \\"docs: see `vcs commit` rule\\""'""",
            ),
            "docs: see `vcs commit` rule",
        )

    def test_prose_mentioning_the_flag_is_not_mistaken_for_a_command(self):
        """Recursion descends into anything containing "-m ", which is fine.

        A false candidate cannot produce a refusal, because the match
        demands that deleting every expansion from it yield the received
        message exactly. This message talks about -m and has no expansion
        at all, so it survives.
        """
        self.assertIsNone(collapsed_expansion(
            "use -m for subjects and -F for bodies",
            'tdb commit -m "use -m for subjects and -F for bodies"',
        ))

    def test_recursion_is_bounded(self):
        """A pathological nest must not hang or recurse without end."""
        nested = 'tdb -m "x"'
        for _ in range(12):
            nested = f"""bash -c '{nested} -m "wrapped"'"""
        self.assertIsNone(collapsed_expansion("nothing matching", nested))

    def test_no_raw_command_means_no_opinion(self):
        """An interactive shell, or a platform with no /proc.

        None means "no evidence", and the only safe reading of no evidence
        is to let the commit through. A guard that refused here would fail
        closed on exactly the users it cannot see.
        """
        self.assertIsNone(collapsed_expansion("anything at all", None))

    def test_unbalanced_quotes_are_not_an_error(self):
        """The shell already ran it; this is not the place to object."""
        self.assertIsNone(collapsed_expansion(
            "whatever", 'templedb vcs commit -m "unterminated'))

    def test_a_line_with_no_message_flag_is_ignored(self):
        self.assertIsNone(collapsed_expansion(
            "subject", "templedb vcs status bza --refresh"))

    def test_several_commands_on_one_line_do_not_cross_contaminate(self):
        """`a -m x && b -m y` gives two candidates and no way to know ours.

        Resolved conservatively: a candidate identical to what arrived
        proves nothing was expanded, so the clean sibling vouches for us
        rather than the dirty one convicting us.
        """
        self.assertIsNone(collapsed_expansion(
            "second subject",
            'tdb commit -m "first `eaten`" && tdb commit -m "second subject"',
        ))

    def test_resolve_message_refuses_a_corrupted_one_liner(self):
        """End to end, with the parent lookup stubbed.

        Patched rather than faked with a real subprocess: the point under
        test is the comparison, and spawning a shell to prove that bash
        substitutes backticks would be testing bash.
        """
        import cli.commit_message as mod
        original = mod._raw_shell_command
        mod._raw_shell_command = lambda: (
            'templedb vcs commit -p bza -m "docs: see `vcs commit`"')
        try:
            self.assertIsNone(resolve_message(Namespace(
                message="docs: see ", message_file=None)))
        finally:
            mod._raw_shell_command = original

    def test_an_internal_caller_is_exempt(self):
        """publish resolves its own message and calls commit in-process.

        That string never passed through a shell, so the parent's command
        line says nothing about it and must not be consulted.
        """
        import cli.commit_message as mod
        original = mod._raw_shell_command
        mod._raw_shell_command = lambda: (
            'templedb publish run x -m "docs: see `vcs commit`"')
        try:
            self.assertEqual(
                resolve_message(Namespace(
                    message="docs: see ", message_file=None,
                    message_is_internal=True)),
                "docs: see ",
            )
        finally:
            mod._raw_shell_command = original


if __name__ == "__main__":
    unittest.main()
