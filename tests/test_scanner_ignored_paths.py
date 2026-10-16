"""Atomic-write debris must not be ingested as content.

`<name>.tmp.<pid>[.<suffix>]` only survives when a writer died between
writing the temp file and `os.replace`-ing it onto the target. 67 such
paths had been recorded in project_files before the scanner learned the
shape. Unlike an unrecognised name, these are declared out of scope, so
they are skipped silently — the same contract SKIP_DIRS has for
node_modules — rather than reported as unclassifiable.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


class TestIsIgnoredPath(unittest.TestCase):

    def ignored(self, p):
        from importer.scanner import is_ignored_path
        return is_ignored_path(p)

    def test_the_two_shapes_actually_found_in_the_db(self):
        # pid + millisecond timestamp (a JS writer), 65 of the 67
        self.assertTrue(self.ignored(
            'components/BookUpload.tsx.tmp.241132.1784033891676'))
        # pid + hex, the other 2
        self.assertTrue(self.ignored(
            'configuration.nix.tmp.722264.a35eb9e85bd7'))

    def test_templedbs_own_shape(self):
        """cli/commands/file.py writes `{target}.tmp.{pid}` with no suffix."""
        self.assertTrue(self.ignored('src/foo.py.tmp.12345'))

    def test_other_debris(self):
        self.assertTrue(self.ignored('src/.#locked.py'))
        self.assertTrue(self.ignored('notes.txt~'))
        self.assertTrue(self.ignored('assets/.DS_Store'))
        self.assertTrue(self.ignored('src/merged.py.orig'))
        self.assertTrue(self.ignored('src/merged.py.rej'))

    def test_real_files_are_not_ignored(self):
        """The patterns must not swallow legitimate names."""
        for p in ('src/main.py', 'tmp/real.py', 'src/tmpfile.py',
                  'docs/a.tmp.md', 'src/temperature.py',
                  'scripts/mktemp.sh', 'src/.gitignore'):
            self.assertFalse(self.ignored(p), p)

    def test_a_tmp_dir_is_not_debris(self):
        """`tmp` as a directory component is ordinary."""
        self.assertFalse(self.ignored('tmp/keep.py'))


class TestScanSkipsDebris(unittest.TestCase):

    def test_debris_is_skipped_even_when_git_tracks_it(self):
        """Checked before the git filter: a repo that committed debris by
        accident must not keep re-ingesting it."""
        from importer.scanner import FileScanner
        repo = tempfile.mkdtemp(prefix='templedb-ignored-')
        env = {**os.environ, 'GIT_CONFIG_GLOBAL': '/dev/null',
               'GIT_CONFIG_SYSTEM': '/dev/null'}
        subprocess.run(['git', 'init', '-q'], cwd=repo, check=True, env=env)
        (Path(repo) / 'main.py').write_text('x = 1\n')
        (Path(repo) / 'main.py.tmp.4242.1784033891676').write_text('x = 1\n')
        subprocess.run(['git', 'add', '-A'], cwd=repo, check=True, env=env)

        scanner = FileScanner(repo)
        seen = {f.relative_path for f in scanner.scan_directory()}
        self.assertIn('main.py', seen)
        self.assertNotIn('main.py.tmp.4242.1784033891676', seen)
        # Declared policy, so silent — not reported as unrecognised.
        self.assertEqual(scanner.skipped_files, [])

    def test_debris_does_not_keep_a_tree_unprunable(self):
        """One abandoned temp file used to read as untracked work."""
        from repositories.checkout_repository import CheckoutRepository
        tree = tempfile.mkdtemp(prefix='templedb-ignored-tree-')
        (Path(tree) / 'kept.py').write_text('x = 1\n')
        (Path(tree) / 'kept.py.tmp.99.1784033891676').write_text('partial')
        untracked = CheckoutRepository._untracked_in_tree(
            tree, tracked={'kept.py'}, nested_roots=set())
        self.assertEqual(untracked, [])


if __name__ == '__main__':
    unittest.main()
