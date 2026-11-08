#!/usr/bin/env python3
"""`file where` must probe the *resolved* trees, not hardcoded paths.

`where` exists to make drift between the DB and its filesystem mirrors
visible. It used to build those mirror paths by hand:

    ~/.config/templedb/checkouts/<slug>/<path>
    ~/.config/templedb/edit-workspaces/<slug>/<path>

The second can never match. Edit workspaces live at
`edit-workspaces/<slug>/<session-name>/<path>`, so the probe omitted the
session component, `.exists()` was always False, and `where` skips
missing mirrors silently rather than printing them. The result was the
worst possible failure for a drift-detector: the one copy most likely to
be stale — the tree `vcs status` scans and `vcs commit` reads — was the
only mirror it never reported, while it printed "✓ match" and exited 0
for the rest.

Same bug class as the one `_write_content_to_db` already carries a
comment about (2026-09-24): asking about a tree that isn't the one in
use. That one cost commit 7A3BF285 a file.

Both roots now come from `SyncManager.get_checkout_path(purpose)` —
PURPOSE_BUILD for the materialised tree, PURPOSE_EDIT for the workspace.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

from cli.commands.file import FileCommands
from repositories.checkout_repository import CheckoutRepository


@pytest.fixture
def probe(tmp_path, monkeypatch):
    """Run `where` against fake checkout roots; return the paths it probed.

    Stubs the two DB touchpoints (`fuzzy_match_project`,
    `_get_current_hash`) so the test is about mirror *resolution* only,
    and records every path whose hash got taken.
    """
    def _run(roots, content_by_root):
        probed = []

        monkeypatch.setattr(
            'cli.commands.file.fuzzy_match_project',
            lambda *a, **k: {'id': 1, 'slug': 'p'},
        )

        class _FakeSync:
            def __init__(self, slug):
                pass

            def get_checkout_path(self, purpose=None):
                if purpose not in roots:
                    raise ValueError(f"no checkout for purpose {purpose}")
                return roots[purpose]

        import sync.manager
        monkeypatch.setattr(sync.manager, 'SyncManager', _FakeSync)

        # Lay the file down under each root with the given content.
        for root, text in content_by_root.items():
            target = Path(root) / 'src' / 'f.py'
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)

        cmds = FileCommands()
        import hashlib
        db_hash = hashlib.sha256(b"db-content").hexdigest()
        monkeypatch.setattr(
            FileCommands, '_get_current_hash', lambda self, *a: db_hash
        )

        real_read_bytes = Path.read_bytes

        def _spy(self):
            probed.append(str(self))
            return real_read_bytes(self)

        monkeypatch.setattr(Path, 'read_bytes', _spy)

        rc = cmds.where(SimpleNamespace(project='p', file_path='src/f.py'))
        return rc, probed

    return _run


def test_probes_the_session_scoped_edit_workspace(probe, tmp_path):
    """The edit mirror is found at <root>/<session-name>/<path>.

    This is the regression. With the hardcoded path the edit workspace
    was invisible, so `where` reported DB + checkout only.
    """
    canonical = tmp_path / 'checkouts' / 'p'
    workspace = tmp_path / 'edit-workspaces' / 'p' / 'agent-session'
    rc, probed = probe(
        {
            CheckoutRepository.PURPOSE_BUILD: canonical,
            CheckoutRepository.PURPOSE_EDIT: workspace,
        },
        {canonical: "db-content", workspace: "drifted"},
    )

    assert str(workspace / 'src' / 'f.py') in probed, (
        "the session-scoped edit workspace was never probed"
    )
    assert rc == 1, "drift in the edit workspace must exit 1, not 0"


def test_identical_roots_are_probed_once(probe, tmp_path):
    """BUILD and EDIT often resolve to the same tree; don't print it twice."""
    only = tmp_path / 'checkouts' / 'p'
    rc, probed = probe(
        {
            CheckoutRepository.PURPOSE_BUILD: only,
            CheckoutRepository.PURPOSE_EDIT: only,
        },
        {only: "db-content"},
    )

    target = str(only / 'src' / 'f.py')
    assert probed.count(target) == 1, f"probed {probed.count(target)}x: {probed}"
    assert rc == 0


def test_absent_edit_workspace_is_not_an_error(probe, tmp_path):
    """Most projects have no edit workspace. That is a missing mirror,
    not a failure — `get_checkout_path` raises and `where` moves on."""
    canonical = tmp_path / 'checkouts' / 'p'
    rc, probed = probe(
        {CheckoutRepository.PURPOSE_BUILD: canonical},
        {canonical: "db-content"},
    )

    assert rc == 0
    assert str(canonical / 'src' / 'f.py') in probed
