"""`nixos generate`'s dirty-tracking must not claim keys it cannot render.

system_config holds more than the nixos.* namespace. woofs.* in
particular is mirrored into modules/woofs/config.nix by hand, because
that file's template placeholders were destroyed by being substituted in
place. Verified 2026-09-25: grep for "woofs" across both generated files
returns 0, and regenerating after changing woofs.data_owner altered only
the output's timestamp.

Before this, `_dirty_count` counted every changed key, so
`nixos system-switch` blocked with "2 config keys changed since last
generate. Generate now?" for keys a generate could never touch --
offering a fix that cannot work, which is worse than saying nothing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

from cli.commands.nixos import _is_generated_key


HOSTS = frozenset({'zMothership2', 'zStation', 'zMothership3'})


@pytest.mark.parametrize("key", [
    'woofs.enable',
    'woofs.data_owner',
    'woofs.snapshot_sync.project_dir',
])
def test_woofs_keys_are_not_renderable(key):
    assert _is_generated_key(key, HOSTS) is False


@pytest.mark.parametrize("key", [
    'zMothership2.woofs.enable',
    'zStation.woofs.data_owner',
])
def test_host_scoped_woofs_keys_are_not_renderable(key):
    """The host prefix must be stripped before matching, or a
    host-scoped module key reads as renderable purely because its first
    segment happens to be a known host. That was the first cut's bug."""
    assert _is_generated_key(key, HOSTS) is False


@pytest.mark.parametrize("key", [
    'nixos.attr.services.openssh.enable',
    'nixos.pkg.user.cli_utilities.fzf',
    'zMothership2.nixos.flake.input.templedb',
    'zMothership2.videoDriver',
    'mirror.templedb.github',
    'gcs.backup_bucket',
])
def test_everything_else_defaults_to_renderable(key):
    """A DENY-list, so unknown namespaces keep their previous
    behaviour. An allow-list would need exact knowledge of the
    generator's output for every prefix -- host-scoped keys are a mix,
    and guessing would swap one wrong report for another."""
    assert _is_generated_key(key, HOSTS) is True


def test_host_lookalike_without_remainder_is_not_special_cased():
    """A bare host name with no trailing key is not a scoped key."""
    assert _is_generated_key('zMothership2', HOSTS) is True


def test_unknown_host_prefix_is_not_stripped():
    """Only real hosts get their prefix stripped; otherwise
    `woofs.enable` under an unrelated first segment could be missed."""
    assert _is_generated_key('notahost.woofs.enable', HOSTS) is True
    assert _is_generated_key('zMothership2.woofs.enable', HOSTS) is False


def test_split_partitions_without_dropping_anything():
    from cli.commands.nixos import _split_dirty

    class _Conn:
        def execute(self, *a, **k):
            class _R:
                @staticmethod
                def fetchall():
                    return [('nixos.host.zMothership2',)]
            return _R()

    changed = ['woofs.enable', 'zMothership2.woofs.enable',
               'nixos.timeZone', 'mirror.x.y']
    generated, manual = _split_dirty(_Conn(), changed)
    assert sorted(manual) == ['woofs.enable', 'zMothership2.woofs.enable']
    assert sorted(generated) == ['mirror.x.y', 'nixos.timeZone']
    assert len(generated) + len(manual) == len(changed)
