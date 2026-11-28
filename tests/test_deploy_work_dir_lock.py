#!/usr/bin/env python3
"""Two deploys of one project must not share a working directory.

`AppDeployService.deploy` rsyncs `-a --delete` into `config.working_dir` and
then builds with cwd set to it, and took no lock. A deploy that started while
another was building deleted and rewrote the tree under it, and the first then
recorded `Build failed (exit 1)` against sources that build. bza's
deployment_history rows 450, 455 and 459 are each that: a failure with a
success 32-35 seconds behind it, on the same commit, with nothing committed
between the two starts.

The second deploy was not a second person. One session launched both ~70
seconds apart — a deploy, then a deliberate relaunch of a deploy it believed
had died, because a backgrounded deploy killed at an agent turn boundary looks
exactly like one still building. So the guard refuses and names the live
holder, rather than queueing: telling those two states apart is the whole
point, and waiting in line would deploy twice anyway.

What matters here and is easy to regress:

  - the lock path must not depend on $TMPDIR. Two callers with different
    TMPDIRs would lock different files and never contend, and a lock only the
    callers who agree on its path can see is not a lock. nix-shell sets a
    private TMPDIR, so this is a live difference on this host.
  - a holder killed by a signal must leave nothing behind. What kills deploys
    here is SIGKILL from a harness, not a clean exit, so a pidfile-shaped
    guard would wedge releases shut.
  - a refused deploy must record no deployment_history row. It did no work,
    and a row would read as a deploy that failed — the one signal those rows
    exist to carry, and the signal the three pairs above were diagnosed from.
  - deploy() must release the fd rather than leaking it to process exit:
    flock conflicts with itself across two open file descriptions, so a leak
    would refuse the next sequential deploy in the same process.
"""

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import services.app_deploy_service as mod
from services.app_deploy_service import (
    AppDeployConfig,
    AppDeployService,
    _work_dir_lock_path,
)

SLUG = 'locktest'


def _acquire(work_dir, target='production'):
    return AppDeployService()._acquire_work_dir_lock(SLUG, str(work_dir), target)


@pytest.fixture
def work_dir(tmp_path):
    """A working directory, with its lock file removed afterwards.

    The lock file is deliberately never unlinked by the code under test, so
    the test cleans up after itself instead.
    """
    d = tmp_path / 'working'
    d.mkdir()
    yield d
    _work_dir_lock_path(SLUG, str(d)).unlink(missing_ok=True)


@pytest.fixture
def holder(work_dir):
    """A separate process holding the lock on work_dir for the test's length."""
    src = str(Path(__file__).parent.parent / 'src')
    code = (
        "import sys, time\n"
        f"sys.path.insert(0, {src!r})\n"
        "from services.app_deploy_service import AppDeployService\n"
        "fd, held = AppDeployService()._acquire_work_dir_lock("
        f"{SLUG!r}, {str(work_dir)!r}, 'production')\n"
        "print('ACQUIRED' if fd is not None else 'REFUSED', flush=True)\n"
        "time.sleep(120)\n"
    )
    proc = subprocess.Popen([sys.executable, '-c', code],
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == 'ACQUIRED'
    yield proc
    if proc.poll() is None:
        proc.kill()
        proc.wait()


# --- the lock itself ---------------------------------------------------------

def test_second_acquirer_is_refused_and_told_who_holds_it(work_dir, holder):
    fd, held = _acquire(work_dir)
    assert fd is None
    assert f'pid {holder.pid}' in held
    assert str(work_dir) in held
    # the command line, because deployment_history has nowhere to put it:
    # every bza row reads triggered_by=manual regardless of what launched it
    assert 'cmd: ' in held


def test_a_different_working_directory_is_independent(work_dir, holder, tmp_path):
    other = tmp_path / 'other'
    other.mkdir()
    try:
        fd, held = _acquire(other)
        assert held == ''
        assert fd is not None
        os.close(fd)
    finally:
        _work_dir_lock_path(SLUG, str(other)).unlink(missing_ok=True)


def test_a_different_target_is_refused_too(work_dir, holder):
    # production and staging share one working_dir in every config written so
    # far, so they have to take turns; the lock is keyed on the tree.
    fd, held = _acquire(work_dir, target='staging')
    assert fd is None and held != ''


def test_sigkilled_holder_leaves_no_stale_lock(work_dir, holder):
    os.kill(holder.pid, signal.SIGKILL)
    holder.wait()
    for _ in range(50):
        fd, held = _acquire(work_dir)
        if fd is not None:
            break
        time.sleep(0.05)
    assert fd is not None, f'lock still held after SIGKILL: {held}'
    os.close(fd)
    # never unlinked: unlinking races a third process into a fresh inode that
    # nobody else is locking
    assert _work_dir_lock_path(SLUG, str(work_dir)).exists()


def test_same_process_reacquires_after_release_but_not_before(work_dir):
    fd, held = _acquire(work_dir)
    assert fd is not None and held == ''

    blocked_fd, blocked = _acquire(work_dir)
    assert blocked_fd is None and blocked != '', \
        'a leaked fd must refuse the next deploy — this is why deploy() closes it'

    os.close(fd)
    again, held = _acquire(work_dir)
    assert again is not None and held == ''
    os.close(again)


def test_lock_path_ignores_tmpdir(work_dir, monkeypatch):
    before = _work_dir_lock_path(SLUG, str(work_dir))
    monkeypatch.setenv('TMPDIR', '/proc/some-private-tmp')
    assert _work_dir_lock_path(SLUG, str(work_dir)) == before
    assert str(before).startswith('/tmp/')


def test_unusable_lock_directory_fails_open(work_dir, monkeypatch):
    # A lock we cannot take must not become a deploy we cannot run: an
    # unwritable lock directory says nothing about whether this release is
    # safe. It returns no holder, so the caller proceeds unguarded.
    monkeypatch.setattr(
        mod, '_work_dir_lock_path',
        lambda slug, wd: Path('/proc/nonexistent-dir-for-lock-test/x.lock'),
    )
    fd, held = _acquire(work_dir)
    assert fd is None
    assert held == ''


# --- deploy() around the lock ------------------------------------------------

class _FakeTracker:
    """Records what the pipeline would have written to deployment_history."""

    started = []

    def start_deployment(self, **kw):
        type(self).started.append(kw)
        return 9999

    def complete_deployment(self, *a, **kw):
        pass


@pytest.fixture
def service(work_dir, monkeypatch):
    """deploy() with the config, env, sync and tracker stubbed out.

    Everything between the lock and the build is replaced, so these tests
    exercise the deploy()/_deploy_locked split and nothing else: no row is
    written, nothing is rsynced, and `true` stands in for build and deploy.
    """
    import services.deployment_tracking_service as dts

    _FakeTracker.started = []
    monkeypatch.setattr(dts, 'DeploymentTrackingService', _FakeTracker)
    monkeypatch.setattr(mod.db_utils, 'query_one', lambda *a, **kw: {'id': 1})

    class Stub(AppDeployService):
        synced = 0

        def get_config(self, slug):
            return AppDeployConfig(
                platform='custom', working_dir=str(work_dir),
                build_cmd='true', deploy_cmd='true',
            )

        def build_env(self, slug, config, target):
            return os.environ.copy()

        def _sync_from_checkout(self, slug, work_dir):
            type(self).synced += 1

    return Stub()


def _lock_is_free(work_dir):
    fd, _ = _acquire(work_dir)
    if fd is None:
        return False
    os.close(fd)
    return True


def test_deploy_runs_the_pipeline_and_releases_the_lock(service, work_dir):
    result = service.deploy(SLUG)
    assert result.success, result.error
    assert type(service).synced == 1
    assert len(_FakeTracker.started) == 1
    assert result.deployment_id == 9999
    assert _lock_is_free(work_dir)


def test_dry_run_is_inside_the_lock(service, work_dir):
    # Not caution: a dry run runs _sync_from_checkout before it decides to do
    # nothing, so it rewrites a tree a live build may be reading.
    result = service.deploy(SLUG, dry_run=True)
    assert result.success, result.error
    assert type(service).synced == 1
    assert _lock_is_free(work_dir)


def test_refused_deploy_records_nothing_and_touches_nothing(service, work_dir, holder):
    result = service.deploy(SLUG)
    assert not result.success
    assert 'already in flight' in result.error
    assert f'pid {holder.pid}' in result.error
    assert result.deployment_id is None
    assert _FakeTracker.started == []
    assert type(service).synced == 0


def test_lock_is_released_when_the_pipeline_raises(service, work_dir, monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError('build exploded')

    monkeypatch.setattr(mod.subprocess, 'run', boom)
    with pytest.raises(RuntimeError):
        service.deploy(SLUG)
    assert _lock_is_free(work_dir)
