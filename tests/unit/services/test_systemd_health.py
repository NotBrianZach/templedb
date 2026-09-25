#!/usr/bin/env python3
"""Unit tests for services.systemd_health.

Every assertion here is a reproduction of something that actually went
unnoticed: a unit crash-looping without ever reading as `failed`, and a
health pane reporting green because it had not looked at anything.
"""
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest


def _record(**overrides):
    """One `systemctl show` stanza with healthy defaults."""
    fields = {
        'Id': 'thing.service',
        'ActiveState': 'active',
        'SubState': 'running',
        'Result': 'success',
        'NRestarts': '0',
        'InactiveEnterTimestamp': '',
    }
    fields.update(overrides)
    return '\n'.join(f"{k}={v}" for k, v in fields.items())


def _show_output(*records):
    return '\n\n'.join(records) + '\n'


def _fake_systemctl(stdout='', returncode=0, stderr=''):
    """Patch both the binary lookup and the subprocess call."""
    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, returncode, stdout, stderr)
    return patch.multiple(
        'services.systemd_health',
        shutil=_Shim(), subprocess=_SubprocessShim(run),
    )


class _Shim:
    @staticmethod
    def which(_name):
        return '/run/current-system/sw/bin/systemctl'


class _SubprocessShim:
    """Stands in for the subprocess module, preserving the exception types."""

    SubprocessError = subprocess.SubprocessError
    TimeoutExpired = subprocess.TimeoutExpired
    CompletedProcess = subprocess.CompletedProcess

    def __init__(self, run):
        self.run = run


# --- classification -------------------------------------------------

def test_failed_unit_is_reported():
    from services.systemd_health import collect

    out = _show_output(_record(
        Id='woofs-sync.service', ActiveState='failed',
        SubState='failed', Result='exit-code',
        InactiveEnterTimestamp='@1790354274'))
    with _fake_systemctl(out):
        health = collect(scopes=('system',))

    assert len(health.failed) == 1
    assert health.failed[0].unit == 'woofs-sync.service'
    assert health.failed[0].failed_since == 1790354274.0


def test_auto_restart_loop_is_reported_though_never_failed():
    """The regression that hid templedb-mcp.service for months.

    ActiveState is `activating`, not `failed`, so `systemctl --failed`
    lists nothing and every dashboard reads green.
    """
    from services.systemd_health import collect

    out = _show_output(_record(
        Id='voiceai.service', ActiveState='activating',
        SubState='auto-restart', Result='exit-code', NRestarts='11965'))
    with _fake_systemctl(out):
        health = collect(scopes=('user',))

    assert health.failed == []
    assert len(health.looping) == 1
    assert health.looping[0].restarts == 11965
    assert not health.healthy


def test_restarted_but_healthy_unit_is_not_flagged():
    """systemd-journald sits at NRestarts=1 forever; flagging it makes
    the pane noise, and a noisy pane is one nobody reads."""
    from services.systemd_health import collect

    out = _show_output(
        _record(Id='systemd-journald.service', NRestarts='1'),
        _record(Id='ssh-agent.service'),
    )
    with _fake_systemctl(out):
        health = collect(scopes=('system',))

    assert health.units == []
    assert health.healthy
    assert health.totals == {'system': 2}


def test_high_restarts_with_bad_result_counts_as_looping():
    """Sampled outside the backoff window a looper reads as plain
    `activating`, so SubState alone misses it half the time."""
    from services.systemd_health import collect

    out = _show_output(_record(
        Id='flappy.service', ActiveState='activating', SubState='start',
        Result='exit-code', NRestarts='900'))
    with _fake_systemctl(out):
        health = collect(scopes=('user',))

    assert len(health.looping) == 1


def test_failed_sorts_before_looping():
    from services.systemd_health import collect

    out = _show_output(
        _record(Id='loop.service', SubState='auto-restart',
                Result='exit-code', NRestarts='9000'),
        _record(Id='dead.service', ActiveState='failed',
                SubState='failed', Result='exit-code'),
    )
    with _fake_systemctl(out):
        health = collect(scopes=('system',))

    assert [u.unit for u in health.units] == ['dead.service', 'loop.service']


# --- degradation ----------------------------------------------------

def test_missing_systemctl_is_unavailable_not_healthy():
    """`healthy` must never be true for a scan that did not happen —
    that is the same silent-green failure this module exists to catch."""
    from services.systemd_health import collect

    class _NoBinary:
        @staticmethod
        def which(_name):
            return None

    with patch('services.systemd_health.shutil', _NoBinary()):
        health = collect()

    assert not health.available
    assert not health.healthy
    assert health.unreachable == ['system', 'user']


def test_unreachable_user_bus_still_scans_system():
    from services.systemd_health import collect

    def run(args, **kwargs):
        if '--user' in args:
            return subprocess.CompletedProcess(args, 1, '', 'no bus')
        return subprocess.CompletedProcess(
            args, 0, _show_output(_record(Id='ok.service')), '')

    with patch.multiple('services.systemd_health',
                        shutil=_Shim(), subprocess=_SubprocessShim(run)):
        health = collect()

    assert health.scanned == ['system']
    assert health.unreachable == ['user']


def test_timeout_is_swallowed():
    from services.systemd_health import collect

    def run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, 10)

    with patch.multiple('services.systemd_health',
                        shutil=_Shim(), subprocess=_SubprocessShim(run)):
        health = collect()

    assert not health.available


def test_falls_back_when_timestamp_unix_unsupported():
    """systemd < 247 rejects --timestamp=unix outright. Losing the age
    is acceptable; losing the whole scan is not."""
    from services.systemd_health import collect

    out = _show_output(_record(
        Id='old.service', ActiveState='failed', SubState='failed',
        Result='exit-code',
        InactiveEnterTimestamp='Fri 2026-09-25 11:41:31 CDT'))

    def run(args, **kwargs):
        if '--timestamp=unix' in args:
            return subprocess.CompletedProcess(args, 1, '', 'unknown option')
        return subprocess.CompletedProcess(args, 0, out, '')

    with patch.multiple('services.systemd_health',
                        shutil=_Shim(), subprocess=_SubprocessShim(run)):
        health = collect(scopes=('system',))

    assert len(health.failed) == 1
    assert health.failed[0].failed_since is None
    assert health.failed[0].failed_for() is None


# --- helpers --------------------------------------------------------

def test_failed_for_is_none_on_loopers():
    """Every restart rewrites the timestamp, so a loop running since May
    reads as five seconds old. Only the restart count means anything."""
    from services.systemd_health import UnitHealth

    unit = UnitHealth(unit='x.service', scope='user', state='looping',
                      active_state='activating', sub_state='auto-restart',
                      result='exit-code', restarts=2143,
                      failed_since=1790354274.0)
    assert unit.failed_for() is None


def test_status_cmd_includes_user_flag():
    from services.systemd_health import UnitHealth

    def make(scope):
        return UnitHealth(unit='x.service', scope=scope, state='failed',
                          active_state='failed', sub_state='failed',
                          result='exit-code', restarts=0)

    assert make('user').status_cmd == 'systemctl --user status x.service'
    assert make('system').status_cmd == 'systemctl status x.service'


def test_exec_targets_extracts_the_execed_binary():
    """argv[] repeats the path and adds arguments; only path= is the
    binary systemd execs, so an argument that happens to look like a
    path must not be mistaken for one."""
    from services.systemd_health import exec_targets

    out = _show_output(
        'Id=poincare-sync.service\n'
        'ExecStart={ path=/home/zach/sync.sh ; argv[]=/home/zach/sync.sh push'
        ' ; ignore_errors=no ; status=1 }\n'
        'ExecStartPre={ path=/run/current-system/sw/bin/mkdir ;'
        ' argv[]=/run/current-system/sw/bin/mkdir -p /tmp/x ; status=0 }')

    with _fake_systemctl(out):
        targets = exec_targets('user')

    assert targets == [
        ('poincare-sync.service', '/home/zach/sync.sh'),
        ('poincare-sync.service', '/run/current-system/sw/bin/mkdir'),
    ]


def test_exec_targets_unreachable_returns_none():
    """None and [] mean different things: nothing to check versus could
    not look. The invariant skips the scope only on None."""
    from services.systemd_health import exec_targets

    class _NoBinary:
        @staticmethod
        def which(_name):
            return None

    with patch('services.systemd_health.shutil', _NoBinary()):
        assert exec_targets('system') is None


def test_exec_targets_handles_units_with_no_exec_lines():
    from services.systemd_health import exec_targets

    with _fake_systemctl(_show_output('Id=target-like.service')):
        assert exec_targets('system') == []


def test_parser_keeps_equals_signs_in_values():
    from services.systemd_health import _parse_records

    records = _parse_records(
        'Id=a.service\nResult=success\nExtra=a=b=c\n\nId=b.service\n')
    assert len(records) == 2
    assert records[0]['Extra'] == 'a=b=c'
    assert records[1]['Id'] == 'b.service'
