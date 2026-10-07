"""Regression: a LIKE pattern built from user input must be a literal.

`entity search` interpolated its query straight into `f"%{q}%"`, so `_`
kept its LIKE meaning of "any character". On the live database
`entity search deploy_` returned 874 rows against a ground truth of
262, the extras being names like `SafeDeploymentQueries` where
`deploym` satisfied `deploy_`; `gui_` gave 539 against 370. Nothing in
the output distinguished a wildcard hit from a real one, and 9,846 of
55,196 `entities` rows have an underscore in `external_ref` — so this
was the normal case for anyone searching Python identifiers or Nix
store paths, not an edge case.

These tests run against real in-memory SQLite rather than asserting on
the escaped string, because the bug is in how the pattern and the
`ESCAPE` clause pair up. A string-equality test on `like_escape`'s
output would pass just as happily with a wrong escape character.
"""
import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from db_utils import like_escape, LIKE_ESCAPE_CHAR  # noqa: E402

# Rows chosen so that a literal search and a wildcard search give
# different answers: `deploy_run` is the intended hit for "deploy_",
# `deployment` is the false one LIKE would add.
ROWS = [
    'deploy_run',
    'deployment',
    'deploy_',
    'gui_pages',
    'guimain',
    '100%done',
    '100xdone',
    r'back\slash',
    'plain',
]


class TestLikeEscape(unittest.TestCase):

    def setUp(self):
        self.con = sqlite3.connect(':memory:')
        self.con.execute('CREATE TABLE t (v TEXT)')
        self.con.executemany('INSERT INTO t VALUES (?)',
                             [(r,) for r in ROWS])

    def tearDown(self):
        self.con.close()

    def literal(self, needle):
        """Rows containing `needle` as a literal, via escaped LIKE."""
        sql = (f"SELECT v FROM t WHERE v LIKE ? "
               f"ESCAPE '{LIKE_ESCAPE_CHAR}' ORDER BY v")
        pattern = f"%{like_escape(needle)}%"
        return [r[0] for r in self.con.execute(sql, (pattern,))]

    def unescaped(self, needle):
        """The old behaviour, for contrast."""
        return [r[0] for r in self.con.execute(
            "SELECT v FROM t WHERE v LIKE ? ORDER BY v",
            (f"%{needle}%",))]

    def test_underscore_is_literal(self):
        self.assertEqual(self.literal('deploy_'),
                         ['deploy_', 'deploy_run'])

    def test_underscore_unescaped_is_the_bug(self):
        """The contrast that makes the fix meaningful."""
        self.assertIn('deployment', self.unescaped('deploy_'))
        self.assertNotIn('deployment', self.literal('deploy_'))

    def test_percent_is_literal(self):
        self.assertEqual(self.literal('100%'), ['100%done'])
        self.assertIn('100xdone', self.unescaped('100%'))

    def test_backslash_is_literal(self):
        """The escape character itself must survive being searched for.

        Escaped last would be wrong: it would escape the escapes added
        for % and _ rather than itself.
        """
        self.assertEqual(self.literal('\\'), [r'back\slash'])

    def test_plain_text_unaffected(self):
        self.assertEqual(like_escape('plain'), 'plain')
        self.assertEqual(self.literal('plain'), ['plain'])

    def test_empty_matches_everything(self):
        """An empty query is still a valid prefix of every row."""
        self.assertEqual(len(self.literal('')), len(ROWS))

    def test_escape_is_idempotent_on_safe_input(self):
        for s in ('abc', 'A-B.C', 'a/b:c'):
            with self.subTest(s=s):
                self.assertEqual(like_escape(s), s)

    def test_every_row_finds_itself(self):
        """Whole-string round trip: each row is a literal of itself.

        Catches an escape scheme that is self-consistent but wrong for
        some character, which the hand-picked cases above could miss.
        """
        for row in ROWS:
            with self.subTest(row=row):
                self.assertIn(row, self.literal(row))


if __name__ == '__main__':
    unittest.main()
