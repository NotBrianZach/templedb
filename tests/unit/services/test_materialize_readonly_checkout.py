#!/usr/bin/env python3
"""materialize must be able to rewrite its own read-only output.

lock_checkout() chmods every checkout file to 0444 so that people edit
through `templedb edit` rather than the generated tree. That lock is
aimed at humans, but it also stopped TempleDB: on 2026-09-28 materialize
died with EACCES on the first of system_config's 56 locked files.

The consequence was disproportionate. A failed materialize is reported by
the caller as "the checkout diverges from the database", so
`nixos home-rebuild` refused to build and offered two remedies —
`publish run` and `vcs commit` — neither of which fixes a file mode, and
the first of which pushes a project to its git mirror. The rebuild was
blocked for three attempts by a permission bit.
"""
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest


@pytest.fixture
def ensure_writable():
    from services.system_service import _ensure_writable
    return _ensure_writable


def _mode(p):
    return stat.S_IMODE(p.stat().st_mode)


def test_locked_file_becomes_writable(ensure_writable, tmp_path):
    """0444 is exactly what lock_checkout() writes."""
    f = tmp_path / "locked.nix"
    f.write_text("x")
    f.chmod(0o444)
    ensure_writable(f)
    assert _mode(f) & 0o200, "owner-write must be set"
    f.write_text("rewritten")          # the operation that used to raise
    assert f.read_text() == "rewritten"


def test_other_permission_bits_are_preserved(ensure_writable, tmp_path):
    """Only u+w is added. Widening to 0644 would quietly strip the
    executable bit that _apply_git_file_modes sets from `git ls-files -s`,
    and two 203/EXEC outages came from scripts losing that bit."""
    f = tmp_path / "script.sh"
    f.write_text("#!/bin/sh\n")
    f.chmod(0o555)
    ensure_writable(f)
    assert _mode(f) == 0o755, f"expected 0o755, got {oct(_mode(f))}"


def test_already_writable_file_is_untouched(ensure_writable, tmp_path):
    f = tmp_path / "normal.txt"
    f.write_text("x")
    f.chmod(0o644)
    ensure_writable(f)
    assert _mode(f) == 0o644


def test_missing_file_is_not_an_error(ensure_writable, tmp_path):
    """materialize calls this before writing a file that may not exist
    yet; it must be a no-op rather than a failure."""
    ensure_writable(tmp_path / "does-not-exist.txt")   # must not raise


def test_unchmoddable_path_does_not_raise(ensure_writable, tmp_path):
    """Swallowing failure is deliberate: the subsequent write produces a
    clearer error than anything this helper could raise."""
    d = tmp_path / "ro-dir"
    d.mkdir()
    f = d / "f.txt"
    f.write_text("x")
    f.chmod(0o444)
    d.chmod(0o555)
    try:
        ensure_writable(f)              # must not raise
    finally:
        d.chmod(0o755)


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores permission bits")
def test_reproduces_the_original_failure_without_the_helper(tmp_path):
    """Pins why the helper exists: writing a 0444 file raises
    PermissionError, which is what materialize hit."""
    f = tmp_path / "locked.nix"
    f.write_text("x")
    f.chmod(0o444)
    with pytest.raises(PermissionError):
        f.write_text("new content")
