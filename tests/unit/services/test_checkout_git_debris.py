"""A path the DB never knew about can still be deliberately-deleted debris.

`_split_deletion_debris` consulted only tombstoned `project_files` rows, so
a file removed by dropping its row outright left nothing to compare against
and was reported as unrescued work. That is how `checkout-gc` came to print
a cp-and-commit recipe for `src/cli/commands/nixops4.py` — a module retired
in migration 130 — and kept four edit trees unprunable.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..',
                                'src'))

GIT_ENV = {**os.environ,
           'GIT_CONFIG_GLOBAL': '/dev/null',
           'GIT_CONFIG_SYSTEM': '/dev/null',
           'GIT_AUTHOR_NAME': 'T', 'GIT_AUTHOR_EMAIL': 't@e',
           'GIT_COMMITTER_NAME': 'T', 'GIT_COMMITTER_EMAIL': 't@e'}


def git(repo, *args):
    return subprocess.run(['git', *args], cwd=repo, check=True,
                           env=GIT_ENV, stdout=subprocess.PIPE).stdout


def repo_with_added_then_deleted_file(rel, content):
    """A git repo where REL was committed and then deleted. Returns the dir."""
    repo = tempfile.mkdtemp(prefix='templedb-gitdebris-')
    git(repo, 'init', '-q')
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'add it')
    p.unlink()
    git(repo, 'add', '-A')
    git(repo, 'commit', '-qm', 'retire it')
    return repo


class FakeRepo:
    """Minimal stand-in: only the two hooks the git pass actually uses."""

    def __init__(self, canonical_path):
        self._canonical = canonical_path
        from repositories.checkout_repository import CheckoutRepository
        self._split = CheckoutRepository._split_git_deletion_debris.__get__(
            self, FakeRepo)

    def query_one(self, _sql, _params=()):
        if self._canonical is None:
            return None
        return {'checkout_path': self._canonical}

    def split(self, root, candidates):
        return self._split(1, root, candidates)


class TestGitDeletionDebris(unittest.TestCase):

    def setUp(self):
        self.tree = tempfile.mkdtemp(prefix='templedb-gitdebris-tree-')

    def write(self, rel, content):
        p = Path(self.tree) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return rel

    def test_identical_to_the_content_before_deletion_is_debris(self):
        rel, body = 'src/cli/commands/retired.py', 'print("old")\n'
        repo = repo_with_added_then_deleted_file(rel, body)
        self.write(rel, body)
        work, debris = FakeRepo(repo).split(self.tree, [rel])
        self.assertEqual(debris, [rel])
        self.assertEqual(work, [])

    def test_edited_after_deletion_is_still_work(self):
        """Bytes that differ are a genuine edit at a deleted path."""
        rel = 'src/cli/commands/retired.py'
        repo = repo_with_added_then_deleted_file(rel, 'print("old")\n')
        self.write(rel, 'print("old")\nprint("my new work")\n')
        work, debris = FakeRepo(repo).split(self.tree, [rel])
        self.assertEqual(work, [rel])
        self.assertEqual(debris, [])

    def test_a_file_git_still_tracks_is_work(self):
        """Present at HEAD means this is not a deletion at all."""
        repo = tempfile.mkdtemp(prefix='templedb-gitdebris-live-')
        git(repo, 'init', '-q')
        (Path(repo) / 'kept.py').write_text('x = 1\n')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', 'add')
        self.write('kept.py', 'x = 1\n')
        work, debris = FakeRepo(repo).split(self.tree, ['kept.py'])
        self.assertEqual(work, ['kept.py'])
        self.assertEqual(debris, [])

    def test_a_path_git_never_saw_is_work(self):
        repo = repo_with_added_then_deleted_file('other.py', 'x\n')
        rel = self.write('brand_new.py', 'genuinely new\n')
        work, debris = FakeRepo(repo).split(self.tree, [rel])
        self.assertEqual(work, [rel])
        self.assertEqual(debris, [])

    def test_no_canonical_checkout_keeps_everything_as_work(self):
        """Failing closed: unknown must not become prunable."""
        rel = self.write('x.py', 'y\n')
        work, debris = FakeRepo(None).split(self.tree, [rel])
        self.assertEqual(work, [rel])
        self.assertEqual(debris, [])

    def test_a_non_git_canonical_path_keeps_everything_as_work(self):
        rel = self.write('x.py', 'y\n')
        not_a_repo = tempfile.mkdtemp(prefix='templedb-gitdebris-nogit-')
        work, debris = FakeRepo(not_a_repo).split(self.tree, [rel])
        self.assertEqual(work, [rel])
        self.assertEqual(debris, [])

    def test_missing_from_the_tree_is_work(self):
        """Candidate listed but absent on disk — do not guess."""
        rel = 'src/gone.py'
        repo = repo_with_added_then_deleted_file(rel, 'x\n')
        work, debris = FakeRepo(repo).split(self.tree, [rel])
        self.assertEqual(work, [rel])
        self.assertEqual(debris, [])

    def test_binary_content_compares_byte_exact(self):
        """The check must not decode; a NUL byte would break text paths."""
        rel = 'assets/blob.bin'
        repo = tempfile.mkdtemp(prefix='templedb-gitdebris-bin-')
        git(repo, 'init', '-q')
        p = Path(repo) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b'\x00\x01\x02retired\xff')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', 'add')
        p.unlink()
        git(repo, 'add', '-A')
        git(repo, 'commit', '-qm', 'delete')
        tp = Path(self.tree) / rel
        tp.parent.mkdir(parents=True, exist_ok=True)
        tp.write_bytes(b'\x00\x01\x02retired\xff')
        work, debris = FakeRepo(repo).split(self.tree, [rel])
        self.assertEqual(debris, [rel])
        self.assertEqual(work, [])


if __name__ == '__main__':
    unittest.main()
