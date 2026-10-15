"""The scanner must not silently drop a file the project tracks.

`get_file_type` returning None used to mean "skip", so any name no pattern
matched vanished from `templedb commit` while the commit still reported
success for the files it did see. A `justfile` was lost that way.
"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))


def git_repo(files):
    """Create a temp git repo containing FILES (path -> content). Returns dir.

    Files are added to the index so `git ls-files` reports them, which is
    what the scanner consults for project membership.
    """
    tmp = tempfile.mkdtemp(prefix='templedb-scanner-test-')
    env = {**os.environ, 'GIT_CONFIG_GLOBAL': '/dev/null',
           'GIT_CONFIG_SYSTEM': '/dev/null'}
    subprocess.run(['git', 'init', '-q'], cwd=tmp, check=True, env=env)
    for rel, content in files.items():
        p = Path(tmp) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content)
    subprocess.run(['git', 'add', '-A'], cwd=tmp, check=True, env=env)
    return tmp


class TestClassifyPath(unittest.TestCase):
    """Pure classification — no filesystem, no git."""

    def classify(self, path):
        from importer.scanner import classify_path
        return classify_path(path)

    def test_extensionless_build_files(self):
        self.assertEqual(self.classify('justfile'), 'justfile')
        self.assertEqual(self.classify('Justfile'), 'justfile')
        self.assertEqual(self.classify('Makefile'), 'makefile')
        self.assertEqual(self.classify('Dockerfile'), 'docker_file')
        self.assertEqual(self.classify('Caddyfile'), 'caddyfile')
        self.assertEqual(self.classify('CODEOWNERS'), 'codeowners')

    def test_nested_extensionless_names(self):
        """The anchors must allow a subdirectory, not just the repo root."""
        self.assertEqual(self.classify('ops/justfile'), 'justfile')
        self.assertEqual(self.classify('deploy/Caddyfile'), 'caddyfile')

    def test_a_justfile_is_not_matched_as_a_suffix(self):
        """`myjustfile` is a different file; don't claim it."""
        self.assertIsNone(self.classify('myjustfile'))

    def test_dockerfile_variants(self):
        self.assertEqual(self.classify('Dockerfile.dev'), 'docker_file')
        self.assertEqual(self.classify('Dockerfile.prod'), 'docker_file')

    def test_plain_text_and_configs(self):
        self.assertEqual(self.classify('notes.txt'), 'text_file')
        self.assertEqual(self.classify('setup.cfg'), 'config_file')
        self.assertEqual(self.classify('app.conf'), 'config_file')
        self.assertEqual(self.classify('pytest.ini'), 'pytest_config')
        self.assertEqual(self.classify('LICENSE.txt'), 'license')

    def test_interface_and_doc_formats(self):
        self.assertEqual(self.classify('api.proto'), 'protobuf')
        self.assertEqual(self.classify('schema.graphql'), 'graphql')
        self.assertEqual(self.classify('readme.rst'), 'document')
        self.assertEqual(self.classify('fix.patch'), 'patch')

    def test_specific_patterns_still_win_over_generic(self):
        """Order matters: the generic .txt rule must not shadow these."""
        self.assertEqual(self.classify('requirements.txt'), 'pip_requirements')
        self.assertEqual(self.classify('robots.txt'), 'robots_txt')
        self.assertEqual(self.classify('CMakeLists.txt'), 'cmake')

    def test_still_returns_none_for_the_genuinely_unknown(self):
        self.assertIsNone(self.classify('mystery.qqq'))


class TestScanCoverage(unittest.TestCase):
    """The regression: nothing git tracks may be absent from a scan."""

    def scan(self, root):
        from importer.scanner import FileScanner
        scanner = FileScanner(root)
        return scanner, {f.relative_path for f in scanner.scan_directory()}

    def test_justfile_is_scanned(self):
        root = git_repo({'justfile': 'build:\n\tcargo build\n',
                         'README.md': '# x\n'})
        _, seen = self.scan(root)
        self.assertIn('justfile', seen)
        self.assertIn('README.md', seen)

    def test_unknown_extension_is_scanned_when_git_tracks_it(self):
        """The structural fix: unrecognised != out of scope."""
        root = git_repo({'weird.qqq': 'data\n', 'main.py': 'x = 1\n'})
        scanner, seen = self.scan(root)
        self.assertIn('weird.qqq', seen)
        self.assertEqual(scanner.skipped_files, [])

    def test_generic_fallback_type_distinguishes_binary(self):
        root = git_repo({'blob.qqq': b'\x00\x01\x02binary',
                         'plain.qqq': 'just text\n'})
        from importer.scanner import FileScanner
        by_path = {f.relative_path: f.file_type
                   for f in FileScanner(root).scan_directory()}
        self.assertEqual(by_path['plain.qqq'], 'text_file')
        self.assertEqual(by_path['blob.qqq'], 'binary_asset')

    def test_every_git_tracked_file_is_scanned(self):
        """The invariant, stated directly."""
        root = git_repo({
            'justfile': 'x:\n\ttrue\n',
            'Makefile': 'all:\n\ttrue\n',
            'Dockerfile.dev': 'FROM alpine\n',
            'CODEOWNERS': '* @me\n',
            'notes.txt': 'hello\n',
            'setup.cfg': '[x]\n',
            'api.proto': 'message M {}\n',
            'src/main.rs': 'fn main() {}\n',
            'nested/dir/thing.unknownext': 'z\n',
        })
        scanner, seen = self.scan(root)
        tracked = set(subprocess.run(
            ['git', 'ls-files'], cwd=root, capture_output=True, text=True,
        ).stdout.split())
        self.assertTrue(tracked)
        self.assertEqual(tracked - seen, set(),
                         "git tracks files the scanner did not return")
        self.assertEqual(scanner.skipped_files, [])

    def test_gitignored_files_are_still_excluded(self):
        """The fallback must not override .gitignore."""
        root = git_repo({'.gitignore': 'secret.qqq\n', 'keep.py': 'x = 1\n'})
        (Path(root) / 'secret.qqq').write_text('nope\n')
        _, seen = self.scan(root)
        self.assertIn('keep.py', seen)
        self.assertNotIn('secret.qqq', seen)

    def test_non_git_directory_records_skips_instead_of_hiding_them(self):
        """With no authority on membership, skipping is still the behaviour —
        but it has to be visible."""
        tmp = tempfile.mkdtemp(prefix='templedb-scanner-nogit-')
        (Path(tmp) / 'main.py').write_text('x = 1\n')
        (Path(tmp) / 'mystery.qqq').write_text('?\n')
        scanner, seen = self.scan(tmp)
        self.assertIn('main.py', seen)
        self.assertNotIn('mystery.qqq', seen)
        self.assertEqual(scanner.skipped_files, ['mystery.qqq'])

    def test_skipped_files_resets_between_scans(self):
        tmp = tempfile.mkdtemp(prefix='templedb-scanner-nogit2-')
        (Path(tmp) / 'mystery.qqq').write_text('?\n')
        from importer.scanner import FileScanner
        scanner = FileScanner(tmp)
        scanner.scan_directory()
        scanner.scan_directory()
        self.assertEqual(scanner.skipped_files, ['mystery.qqq'])


if __name__ == '__main__':
    unittest.main()
