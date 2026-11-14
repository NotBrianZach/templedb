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
    'mirror.templedb.github',
    'mirror.nixos_anywhere_vultr_woofs.github',
    'zMothership2.mirror.templedb.github',
])
def test_mirror_keys_are_not_renderable(key):
    """publish reads mirror.* out of system_config directly, and grep
    for "mirror" across both generated files returns 0 (2026-11-13).
    Adding the Vultr mirror URL on 2026-11-11 was enough to make
    system-switch announce a pending generate that would have rewritten
    flake.nix -- clobbering the pinned input rev -- and applied
    nothing."""
    assert _is_generated_key(key, HOSTS) is False


@pytest.mark.parametrize("key", [
    'nixos.attr.services.openssh.enable',
    'nixos.pkg.user.cli_utilities.fzf',
    'zMothership2.nixos.flake.input.templedb',
    'zMothership2.videoDriver',
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
    assert sorted(manual) == ['mirror.x.y', 'woofs.enable',
                              'zMothership2.woofs.enable']
    assert sorted(generated) == ['nixos.timeZone']
    assert len(generated) + len(manual) == len(changed)


def test_bookkeeping_keys_are_dropped_before_the_split():
    """`admin db check` rewrites admin.db.check.last_pin_probe on every
    run, so a timestamp-only dirty check reports it as a pending user
    change. It was half of the bogus "2 config keys changed" prompt on
    2026-11-13. Dropped outright rather than listed as unrenderable --
    nobody set it and nobody needs to hear about it."""
    from cli.commands.nixos import _changed_keys

    rows = [('admin.db.check.last_pin_probe',), ('nixos.timeZone',),
            ('mirror.templedb.github',)]

    class _Conn:
        def execute(self, sql, *a, **k):
            class _R:
                @staticmethod
                def fetchone():
                    return ('2026-10-14 18:21:53',)

                @staticmethod
                def fetchall():
                    return rows
            return _R()

    assert sorted(_changed_keys(_Conn())) == [
        'mirror.templedb.github', 'nixos.timeZone']
