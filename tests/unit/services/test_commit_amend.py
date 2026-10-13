#!/usr/bin/env python3
"""`vcs commit --amend` — replace the last commit's message, and nothing else.

Two bugs made this worth having. A message passed with -m is a shell
string, so backtick spans in it are command-substituted before argv
exists: commit 217092EC lost three quoted command names and printed
three "command not found" lines while reporting success. And there was
no amend, so repairing that meant hand-writing an UPDATE against
vcs_commits — the kind of thing that is fine once and a habit worth not
forming.

Message-only, deliberately. Git needs --amend to fold staged files
because commits are content-addressed and appending one rewrites every
hash after it. Nothing here is: commit_hash is
sha256(slug:branch:message:time.time())[:16], and the wall clock means
it cannot be recomputed from the row at all. A follow-up commit costs
nothing structural, so folding content would be risk with no payoff.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

from db_utils import execute, query_one


@pytest.fixture(scope="module", autouse=True)
def _isolated_db(module_db):
    """This module hand-builds a partial schema; keep it out of the shared DB."""


@pytest.fixture
def amender(monkeypatch):
    """A VCSCommands whose branch lookup is satisfied, plus row helpers."""
    for stmt in (
        """CREATE TABLE IF NOT EXISTS projects (
               id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, slug TEXT UNIQUE)""",
        """CREATE TABLE IF NOT EXISTS vcs_branches (
               id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
               branch_name TEXT, is_default INTEGER DEFAULT 0)""",
        """CREATE TABLE IF NOT EXISTS vcs_commits (
               id INTEGER PRIMARY KEY AUTOINCREMENT, project_id INTEGER,
               branch_id INTEGER, commit_hash TEXT, git_commit_hash TEXT,
               commit_message TEXT, commit_timestamp TEXT)""",
    ):
        execute(stmt)
    for t in ('vcs_commits', 'vcs_branches', 'projects'):
        execute(f"DELETE FROM {t}")

    execute("INSERT INTO projects (name, slug) VALUES ('p','p')")
    pid = query_one("SELECT id FROM projects WHERE slug='p'")['id']
    execute("""INSERT INTO vcs_branches (project_id, branch_name, is_default)
               VALUES (?, 'main', 1)""", (pid,))
    bid = query_one("SELECT id FROM vcs_branches WHERE project_id=?",
                    (pid,))['id']

    from cli.commands.vcs import VCSCommands
    cmd = VCSCommands()
    monkeypatch.setattr(cmd.vcs_repo, 'get_active_branch',
                        lambda _pid: {'id': bid, 'branch_name': 'main'})

    class Harness:
        project = {'id': pid, 'slug': 'p'}
        command = cmd

        def add_commit(self, h, msg, git_sha=None, ts='2026-10-13 10:00:00'):
            execute("""INSERT INTO vcs_commits
                         (project_id, branch_id, commit_hash, git_commit_hash,
                          commit_message, commit_timestamp)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (pid, bid, h, git_sha, msg, ts))

        def amend(self, message, branch=None, force=False):
            from argparse import Namespace
            return cmd._amend_message(
                self.project, Namespace(branch=branch, force=force), message)

        def message_of(self, h):
            return query_one("SELECT commit_message FROM vcs_commits "
                             "WHERE commit_hash = ?", (h,))['commit_message']

    return Harness()


def _args(**kw):
    from argparse import Namespace
    kw.setdefault('message', None)
    kw.setdefault('message_file', None)
    return Namespace(**kw)


# --- the message source -----------------------------------------------

def test_a_message_file_survives_backticks_and_dollars():
    """The incident. -m cannot carry this, because the shell eats it
    before argv exists; a file is never evaluated."""
    from cli.commit_message import resolve_message
    body = 'fixed it\n\nvia `admin checkout-gc` and $PATH\n'
    p = Path('/tmp/templedb_amend_test_msg.txt')
    p.write_text(body)
    got = resolve_message(_args(message_file=str(p)))
    assert '`admin checkout-gc`' in got
    assert '$PATH' in got
    p.unlink()


def test_only_trailing_newlines_are_stripped():
    """Body indentation and blank-line structure are the message. Only
    the editor's trailing newline is noise."""
    from cli.commit_message import resolve_message
    p = Path('/tmp/templedb_amend_test_msg2.txt')
    p.write_text('subject\n\n  indented body\n\n\n')
    got = resolve_message(_args(message_file=str(p)))
    assert got == 'subject\n\n  indented body'
    p.unlink()


def test_m_and_F_together_is_refused():
    """Two sources, no defined precedence — better to stop than pick."""
    from cli.commit_message import resolve_message
    assert resolve_message(
        _args(message='x', message_file='/tmp/whatever')) is None


def test_no_message_at_all_is_refused():
    from cli.commit_message import resolve_message
    assert resolve_message(_args()) is None


# --- what amend does --------------------------------------------------

def test_the_last_commit_on_the_branch_is_the_one_amended(amender):
    amender.add_commit('AAAA111122223333', 'old', ts='2026-10-13 09:00:00')
    amender.add_commit('BBBB111122223333', 'newer', ts='2026-10-13 11:00:00')

    assert amender.amend('replaced') == 0
    assert amender.message_of('BBBB111122223333') == 'replaced'
    assert amender.message_of('AAAA111122223333') == 'old', "untouched"


def test_an_unchanged_message_is_a_noop(amender):
    """Re-running the same amend must not report success at changing
    something. It is the shape a script retries into."""
    amender.add_commit('AAAA111122223333', 'same')
    assert amender.amend('same') == 0
    assert amender.command.last_outcome == 'nothing-to-commit'


def test_nothing_to_amend_is_an_error_not_a_crash(amender):
    assert amender.amend('anything') == 1


# --- the guards -------------------------------------------------------

def test_a_mirrored_commit_is_refused(amender):
    """A git_commit_hash means the message is already outside this
    database, so amending here only desyncs the two."""
    amender.add_commit('AAAA111122223333', 'published',
                       git_sha='a' * 40)
    assert amender.amend('rewrite') == 1
    assert amender.message_of('AAAA111122223333') == 'published'


def test_an_ambiguous_hash_format_is_refused_by_default(amender):
    """The guard that is easy to miss, and the reason the mirrored test
    is not sufficient on its own.

    40-char lowercase was minted by TWO generators, both leaving
    git_commit_hash NULL: git-history import (real git SHAs, where
    amending rewrites published history) and `templedb commit <slug>
    <dir>` up to 2026-10-13, which took sha256(...)[:40] and so wore
    git's format while being a native id. Migration 126 gave commit_hash
    one meaning on the premise that the format identified the former, and
    left the latter writing — which is why commit_hash_is_canonical
    climbed back to 77 rows. Nothing in such a row says which it is, so
    the default is refusal.
    """
    amender.add_commit('b11eed331961b421d70ae56dc4e292fa9d361830',
                       'could be either')
    assert amender.amend('rewrite') == 1
    assert amender.message_of(
        'b11eed331961b421d70ae56dc4e292fa9d361830') == 'could be either'


def test_force_amends_an_ambiguous_hash(amender):
    """The other half. Refusing outright would block amending any commit
    `templedb commit` made before the format was fixed, which is
    ordinary local work and the common case."""
    amender.add_commit('b11eed331961b421d70ae56dc4e292fa9d361830', 'mine')
    assert amender.amend('rewritten', force=True) == 0
    assert amender.message_of(
        'b11eed331961b421d70ae56dc4e292fa9d361830') == 'rewritten'


def test_force_does_not_override_a_mirrored_commit(amender):
    """--force covers format ambiguity, not a commit known to be in git.
    There the answer is not in doubt, so there is nothing to override."""
    amender.add_commit('CCCC111122223333', 'published', git_sha='c' * 40)
    assert amender.amend('rewrite', force=True) == 1
    assert amender.message_of('CCCC111122223333') == 'published'


def test_a_lowercase_native_hash_is_also_ambiguous(amender):
    """Native ids from `vcs commit` are uppercase, so lowercase is the
    other half of the same predicate and gets the same treatment."""
    amender.add_commit('abcdef1234567890', 'suspect')
    assert amender.amend('rewrite') == 1
    assert amender.message_of('abcdef1234567890') == 'suspect'


def test_a_canonical_native_hash_needs_no_force(amender):
    """The format the fix makes `templedb commit` emit, and the one
    `vcs commit` always did. Nothing ambiguous, so no flag."""
    amender.add_commit('81B33A4A90E59071', 'local work')
    assert amender.amend('rewritten') == 0
    assert amender.message_of('81B33A4A90E59071') == 'rewritten'
