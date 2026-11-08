#!/usr/bin/env python3
"""The read-only checkout guard must not lock git's own state.

Regression for a silent-no-op publish observed 2026-11-08. `project
checkout` (no --writable) called `make_readonly`, which walked the whole
tree and left `.git` at 0555 and `.git/index` at 0444. Every later
`templedb publish run` then failed `git add -A` with EACCES on
`.git/index.lock`, skipped the materialize commit, and pushed the
*previous* head to the mirror while printing "Published to 1 mirror(s)" —
after which a flake pin taken from that head built stale source.

The tests assert the two halves of the fix: the walkers skip `.git`, and
git still works on a locked checkout (which is the property that actually
matters — a future walker that locks `.git` some other way fails here).
"""

import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from sync.permissions import make_readonly, make_writable


GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@localhost",
    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@localhost",
}


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=str(repo), env=GIT_ENV,
                          capture_output=True, text=True, check=False)


@pytest.fixture
def checkout(tmp_path):
    """A git repo shaped like a materialized checkout: one commit, one dirty file."""
    repo = tmp_path / "checkout"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "app.py").write_text("print('v1')\n")
    assert _git(repo, "init", "-q").returncode == 0
    assert _git(repo, "add", "-A").returncode == 0
    assert _git(repo, "commit", "-q", "-m", "initial").returncode == 0
    # The state publish materializes into: new content on disk, uncommitted.
    (repo / "src" / "app.py").write_text("print('v2')\n")
    return repo


def test_make_readonly_leaves_git_writable(checkout):
    make_readonly(checkout)

    git_dir = checkout / ".git"
    assert os.stat(git_dir).st_mode & stat.S_IWUSR, ".git must stay writable"
    index = git_dir / "index"
    assert index.exists()
    assert os.stat(index).st_mode & stat.S_IWUSR, ".git/index must stay writable"


def test_make_readonly_still_locks_db_owned_files(checkout):
    """The guard it exists for still has to work."""
    make_readonly(checkout)

    tracked = checkout / "src" / "app.py"
    assert not os.stat(tracked).st_mode & stat.S_IWUSR
    # Subdirectories lose their write bit too (the walk does not touch the
    # root it was handed, which is why `is_writable` is not asserted here).
    assert not os.stat(checkout / "src").st_mode & stat.S_IWUSR


def test_git_can_commit_in_a_locked_checkout(checkout):
    """The property that actually broke publish.

    Staging a *modification* is what materialize does, and it needs a
    writable .git/index — not a writable worktree file.
    """
    make_readonly(checkout)

    add = _git(checkout, "add", "-A")
    assert add.returncode == 0, f"git add failed on a locked checkout: {add.stderr}"
    commit = _git(checkout, "commit", "-q", "-m", "TempleDB materialize (1 files)")
    assert commit.returncode == 0, f"git commit failed: {commit.stderr or commit.stdout}"

    head = _git(checkout, "log", "-1", "--format=%s").stdout.strip()
    assert head == "TempleDB materialize (1 files)"
    assert _git(checkout, "status", "--porcelain").stdout.strip() == ""


def test_ensure_writable_lets_materialize_add_a_file_to_a_locked_dir(checkout):
    """Creating a file needs the write bit on the directory, not the file.

    A locked checkout has 0555 directories, so publishing a *newly added*
    DB file failed with EACCES while an edit to an existing file beside it
    succeeded.
    """
    from services.system_service import _ensure_writable

    make_readonly(checkout)
    new_file = checkout / "src" / "added.py"

    _ensure_writable(new_file)
    new_file.write_text("print('added')\n")  # EACCES before the fix

    assert new_file.read_text() == "print('added')\n"
    # The guard that matters is untouched: generated files stay read-only.
    assert not os.stat(checkout / "src" / "app.py").st_mode & stat.S_IWUSR


def test_make_writable_leaves_git_hooks_executable(checkout):
    """A blanket 0644 over .git would strip the exec bit from every hook."""
    hook = checkout / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 0\n")
    hook.chmod(0o755)

    make_readonly(checkout)
    make_writable(checkout)

    assert os.stat(hook).st_mode & stat.S_IXUSR, "hook lost its exec bit"
    assert os.stat(checkout / "src" / "app.py").st_mode & stat.S_IWUSR
