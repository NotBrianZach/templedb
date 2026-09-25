"""Git owns the executable bit; materialize defers to it.

The decision recorded 2026-09-25: TempleDB has no mode column in
project_files or file_contents and is not getting one -- that would
commit to the DB-authoritative endpoint, while git already stores the
bit for free. Before this, every script TempleDB materialized landed
0644 and the published mirror recorded 100644 for all 771 tracked
files, install.sh included. Two 203/EXEC outages came from it.
"""
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

from services.system_service import SystemService


pytestmark = pytest.mark.skipif(
    subprocess.run(["git", "--version"], capture_output=True).returncode != 0,
    reason="git not available",
)


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo),
                          capture_output=True, text=True, check=False)


@pytest.fixture
def repo(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@t")
    _git(tmp_path, "config", "user.name", "t")
    return tmp_path


def _rows(*paths):
    """The shape materialize passes in: sqlite rows keyed by file_path."""
    return [{"file_path": p} for p in paths]


def is_exec(path):
    return bool(path.stat().st_mode & 0o111)


def test_git_100755_sets_the_bit(repo):
    script = repo / "run.sh"
    script.write_text("#!/bin/sh\necho hi\n")
    script.chmod(0o755)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "x")

    script.chmod(0o644)          # what materialize's rewrite leaves behind
    assert not is_exec(script)

    SystemService._apply_git_file_modes(repo, _rows("run.sh"))
    assert is_exec(script), "git recorded 100755 and was ignored"


def test_git_100644_clears_the_bit(repo):
    """Authority runs both ways: if git says it is not executable, a
    stray local chmod +x does not survive materialize."""
    doc = repo / "notes.md"
    doc.write_text("# hi\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "x")

    doc.chmod(0o755)
    SystemService._apply_git_file_modes(repo, _rows("notes.md"))
    assert not is_exec(doc)


def test_unknown_file_falls_back_to_shebang(repo):
    """A file git has never seen has no recorded opinion. Without the
    shebang fallback a newly added script is born 0644 and has to be
    fixed by hand before git can record anything better."""
    new = repo / "fresh.sh"
    new.write_text("#!/usr/bin/env bash\necho hi\n")
    new.chmod(0o644)

    SystemService._apply_git_file_modes(repo, _rows("fresh.sh"))
    assert is_exec(new)


def test_unknown_file_without_shebang_stays_plain(repo):
    new = repo / "data.json"
    new.write_text('{"a": 1}\n')
    SystemService._apply_git_file_modes(repo, _rows("data.json"))
    assert not is_exec(new)


def test_git_overrides_the_shebang(repo):
    """A tracked file's recorded mode wins over the heuristic -- that is
    what 'git is the authority' means. A shebang'd file deliberately
    committed as 100644 stays non-executable."""
    script = repo / "sourced.sh"
    script.write_text("#!/bin/sh\n# meant to be sourced, not run\n")
    script.chmod(0o644)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "x")

    SystemService._apply_git_file_modes(repo, _rows("sourced.sh"))
    assert not is_exec(script)


def test_non_git_directory_still_applies_shebang_rule(tmp_path):
    """First materialize into a fresh directory: no index to consult."""
    script = tmp_path / "boot.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o644)

    SystemService._apply_git_file_modes(tmp_path, _rows("boot.sh"))
    assert is_exec(script)


def test_missing_file_is_skipped_not_fatal(repo):
    assert SystemService._apply_git_file_modes(repo, _rows("gone.sh")) == 0


def test_returns_number_actually_changed(repo):
    a, b = repo / "a.sh", repo / "b.txt"
    a.write_text("#!/bin/sh\n")
    b.write_text("plain\n")
    a.chmod(0o644)
    b.chmod(0o644)

    assert SystemService._apply_git_file_modes(repo, _rows("a.sh", "b.txt")) == 1
    # Idempotent: a second pass has nothing left to do.
    assert SystemService._apply_git_file_modes(repo, _rows("a.sh", "b.txt")) == 0


def test_does_not_grant_exec_beyond_read_permission(repo):
    """chmod +x semantics: mirror the read bits rather than forcing
    0755, so a 0600 private script becomes 0700, not world-executable."""
    script = repo / "private.sh"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o600)

    SystemService._apply_git_file_modes(repo, _rows("private.sh"))
    assert script.stat().st_mode & 0o777 == 0o700
