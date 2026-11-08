#!/usr/bin/env python3
"""The fleet-sync GUI probe: where it looks for an address, and what it says.

Two reasons the Probe button "didn't work" on zachgigamothers, a machine
that was up the whole time with port 22 answering on 100.73.163.35:

  1. The address came from `fleet_machines.target_host` keyed by machine
     name, plus hard-coded fallbacks for exactly two hosts — and those
     constants (192.168.8.164/172) were wrong anyway, since the machines
     live on 192.168.1.x. A host with a nixosConfiguration but no machine
     row resolved to None, and the probe answered "No IP configured"
     without attempting anything. Tailscale, which knew the address the
     whole time, was never consulted.
  2. Everything that did fail rendered as "SSH failed", which cannot
     distinguish a machine that is powered off from one that is up and
     merely missing this machine's key — opposite problems with opposite
     fixes.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from services.fleet_addressing import (
    classify_ssh_error as _fleet_sync_classify_ssh_error,
    resolve_host as _fleet_sync_resolve_host,
    tailscale_addresses as _fleet_sync_tailscale_addresses,
)


# ── Address resolution ────────────────────────────────────────────────────

def test_explicit_db_address_wins():
    """A written-down target_host beats discovery — someone meant it."""
    assert _fleet_sync_resolve_host(
        'vultr-woofs',
        {'vultr-woofs': '45.32.195.217'},
        {'vultr-woofs': '100.1.2.3'},
        'zMothership2') == '45.32.195.217'


def test_this_machine_resolves_to_localhost_without_a_row():
    assert _fleet_sync_resolve_host(
        'zMothership2', {}, {}, 'zMothership2') == 'localhost'


def test_tailscale_supplies_the_address_when_the_db_has_no_row():
    """The zachgigamothers case: host config, no machine row, up on tailscale."""
    assert _fleet_sync_resolve_host(
        'zachgigamothers', {}, {'zachgigamothers': '100.73.163.35'},
        'zMothership2') == '100.73.163.35'


def test_tailscale_hostname_case_does_not_have_to_match():
    """Tailscale says `zachGigaMothers`; the nix attribute is `zachgigamothers`.

    Exact matching finds nothing, so the machine stayed invisible even
    after tailscale was being consulted at all. Found by resolving
    against the real tailnet rather than a fixture.
    """
    assert _fleet_sync_resolve_host(
        'zachgigamothers', {}, {'zachGigaMothers': '100.73.163.35'},
        'zMothership2') == '100.73.163.35'


def test_exact_match_wins_over_a_case_variant():
    assert _fleet_sync_resolve_host(
        'box', {}, {'box': '100.0.0.1', 'BOX': '100.0.0.2'},
        'zMothership2') == '100.0.0.1'


def test_unknown_machine_resolves_to_nothing():
    assert _fleet_sync_resolve_host('zStation', {}, {}, 'zMothership2') is None


def test_no_hard_coded_subnet_remains():
    """The old fallbacks were stale constants dressed as data."""
    source = (Path(__file__).parent.parent / 'src' / 'gui_pages'
              / 'fleet_sync.py').read_text()
    assert '192.168.8.164' not in source
    assert '192.168.8.172' not in source


def test_tailscale_addresses_survive_tailscale_being_absent(monkeypatch):
    """No tailscale must degrade to "the DB knows best", not an exception."""
    import sync_engine
    monkeypatch.setattr(sync_engine, 'discover_tailscale_peers',
                        lambda: (_ for _ in ()).throw(OSError("no tailscale")))
    assert _fleet_sync_tailscale_addresses() == {}


def test_tailscale_addresses_map_hostname_to_ip(monkeypatch):
    import sync_engine
    monkeypatch.setattr(sync_engine, 'discover_tailscale_peers', lambda: [
        {'hostname': 'zachgigamothers', 'ip': '100.73.163.35', 'os': 'windows'},
        {'hostname': '', 'ip': '100.0.0.1'},          # unnamed peer: skipped
        {'hostname': 'ghost', 'ip': None},            # no address: skipped
    ])
    assert _fleet_sync_tailscale_addresses() == {
        'zachgigamothers': '100.73.163.35'}


# ── Saying what actually went wrong ───────────────────────────────────────

@pytest.mark.parametrize("stderr,expected_fragment", [
    ("ssh: connect to host 192.168.1.242 port 22: Connection refused",
     "nothing listening"),
    ("zach@100.73.163.35: Permission denied (publickey,keyboard-interactive).",
     "key is not authorized"),
    ("ssh: Could not resolve hostname nope: Name or service not known",
     "does not resolve"),
    ("ssh: connect to host 10.0.0.9 port 22: No route to host",
     "no route"),
    ("ssh: connect to host 10.0.0.9 port 22: Connection timed out",
     "timed out"),
])
def test_ssh_failures_are_distinguished(stderr, expected_fragment):
    assert expected_fragment in _fleet_sync_classify_ssh_error(255, stderr)


def test_up_but_unauthorized_is_not_reported_as_unreachable():
    """The distinction that matters: this one needs a key, not a power button."""
    msg = _fleet_sync_classify_ssh_error(
        255, "zach@host: Permission denied (publickey).")
    assert 'up' in msg
    assert 'unreachable' not in msg


def test_unrecognised_failure_keeps_ssh_s_own_words():
    msg = _fleet_sync_classify_ssh_error(255, "ssh: something entirely new\n")
    assert 'something entirely new' in msg
    assert 'rc=255' in msg


def test_empty_stderr_still_produces_a_message():
    assert 'rc=1' in _fleet_sync_classify_ssh_error(1, "")
