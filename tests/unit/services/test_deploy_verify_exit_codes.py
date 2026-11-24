#!/usr/bin/env python3
"""Unit tests for `deploy health-check`'s exit code classification.

Every case here is a firing of templedb-deploy-verify-bza.timer that
exited 1 and meant something different. The timer was installed
2026-11-22 11:31 CST and produced four reds in its first day, no two for
the same reason and not one of them the production fault it exists to
catch:

    11:26  HTTP 200 OK    live commit FAIL  live 4F2B8338, graph 158F5F0D
    11:31  HTTP 200 OK    live commit FAIL  live 4F2B8338, graph B5A0EC2C
    13:12  HTTP FAIL      NameResolutionError on aireadalong.com
    07:03  HTTP FAIL      NameResolutionError, cleared on its own

`systemctl status` showed `status=1/FAILURE` for all four. These
assertions are what makes the first two distinguishable from the last
two without opening the journal.

Pure-function tests on purpose: the unreachable branch cannot be
exercised against a live target from a host whose DNS works, and the
degraded branch needs a `/api/version` that answers 200 without a sha,
which production does not do. Both are one struct away here.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest

from cli.commands.deploy_ops import (
    VERIFY_DEGRADED,
    VERIFY_DRIFT,
    VERIFY_OK,
    VERIFY_UNREACHABLE,
    DeployOpsMixin,
    classify_verify_result,
)
from services.deployment_tracking_service import HealthCheckResult


def _http(status, status_code=None, error=None):
    return HealthCheckResult(
        check_type='http',
        check_name='HTTP Response',
        status=status,
        status_code=status_code,
        response_time_ms=0 if status_code is None else 500,
        endpoint='https://aireadalong.com',
        error_message=error,
    )


def _version(status, status_code=None, live=None, expected=None, error=None):
    """A version result shaped the way run_version_health_check shapes it.

    `details` is filled only in the branch that actually read a live sha,
    which is the whole discriminator — so a caller passing `live=None`
    gets the "answered, but no sha in the body" shape rather than a
    mismatch.
    """
    details = None
    if live is not None:
        details = '{"live": "%s", "expected": "%s"}' % (live, expected)
    return HealthCheckResult(
        check_type='http',
        check_name='live commit matches graph',
        status=status,
        status_code=status_code,
        response_time_ms=0 if status_code is None else 500,
        endpoint='https://aireadalong.com/api/version',
        error_message=error,
        details=details,
    )


def test_both_pass_is_ok():
    assert classify_verify_result(
        _http('pass', 200),
        _version('pass', 200, live='B5A0EC2C', expected='B5A0EC2C'),
    ) == VERIFY_OK


def test_mismatch_with_both_shas_is_drift():
    """The 11:26 and 11:31 firings. Routine: nobody deployed yet."""
    assert classify_verify_result(
        _http('pass', 200),
        _version('fail', 200, live='4F2B8338', expected='158F5F0D',
                 error='live 4F2B8338, graph 158F5F0D'),
    ) == VERIFY_DRIFT


def test_name_resolution_failure_is_unreachable():
    """The 13:12 and 07:03 firings — and the reason this module exists.

    Both checks fail, so the pre-fix code called it exactly what it
    called drift. A failure with no status_code means no HTTP response
    came back at all.
    """
    err = ("HTTPSConnectionPool(host='aireadalong.com', port=443): "
           "Failed to resolve 'aireadalong.com'")
    assert classify_verify_result(
        _http('fail', None, error=err),
        _version('fail', None, error=err),
    ) == VERIFY_UNREACHABLE


def test_drift_does_not_outrank_an_unreachable_version_endpoint():
    """`/` up, `/api/version` unreachable: two requests, one flaky DNS.

    Not drift, because no live sha was ever read. Reporting "production
    is behind" here would be inventing a fact.
    """
    assert classify_verify_result(
        _http('pass', 200),
        _version('fail', None, error='Failed to resolve'),
    ) == VERIFY_UNREACHABLE


def test_timeout_is_unreachable():
    assert classify_verify_result(
        _http('timeout', None, error='Request timed out after 10s'),
        _version('timeout', None, error='Request timed out after 20s'),
    ) == VERIFY_UNREACHABLE


def test_non_200_outranks_a_stale_sha():
    """A 503 alongside drift is not drift.

    This is why precedence is unreachable, then degraded, then drift
    rather than first-failure-wins. The site answered and answered
    wrong; that it is also behind is incidental and must not be the
    verdict.
    """
    assert classify_verify_result(
        _http('fail', 503, error='Expected 200, got 503'),
        _version('fail', 503, live='4F2B8338', expected='158F5F0D',
                 error='live 4F2B8338, graph 158F5F0D'),
    ) == VERIFY_DEGRADED


def test_version_endpoint_without_a_sha_is_degraded():
    """200 from `/api/version`, no `sha` field: the endpoint is broken.

    Calling this drift would report "nobody deployed" about a response
    whose shape changed, which is the same category error as calling a
    DNS failure drift.
    """
    assert classify_verify_result(
        _http('pass', 200),
        _version('fail', 200, error="no 'sha' in the response body"),
    ) == VERIFY_DEGRADED


def test_skip_is_not_a_failure():
    """A host with no `requests` cannot probe anything.

    Reporting that as drift would make the exit code useless to the
    timer, which is the behaviour the pre-fix comment already protected
    and this must not regress.
    """
    assert classify_verify_result(
        _http('skip', None, error='requests module not available'),
        _version('skip', None, error='requests module not available'),
    ) == VERIFY_OK


def test_no_version_check_attempted():
    """A project with no commits has no expected head to compare.

    `health_check` passes None rather than a fabricated result, so the
    HTTP check alone decides.
    """
    assert classify_verify_result(_http('pass', 200), None) == VERIFY_OK
    assert classify_verify_result(
        _http('fail', None, error='Failed to resolve'), None
    ) == VERIFY_UNREACHABLE
    assert classify_verify_result(
        _http('fail', 503, error='Expected 200, got 503'), None
    ) == VERIFY_DEGRADED


def test_codes_avoid_systemd_lsb_labels():
    """Not a style assertion — the reason the codes are not 2 and 3.

    systemd renders low exit codes through its LSB table, so exit 2
    prints `status=2/INVALIDARGUMENT` and exit 3 prints
    `status=3/NOTIMPLEMENTED`. Both are false for this command, and a
    mislabelled code is a worse signal than a bare number. Verified with
    `systemd-run --user --wait /bin/sh -c 'exit N'` on 2026-11-23: 10 and
    11 print `status=10/n/a`.
    """
    codes = (VERIFY_DRIFT, VERIFY_UNREACHABLE, VERIFY_DEGRADED)
    assert all(c >= 8 for c in codes)
    assert len(set(codes)) == 3
    assert VERIFY_OK == 0
    # Below systemd's own 200-242 range, which it also labels.
    assert all(c < 200 for c in codes)


# ----------------------------------------------------------------------
# The same four verdicts, but through `health_check` rather than the
# classifier it calls.
#
# Worth the fakes: classify_verify_result being right proves nothing if
# health_check stops consulting it, or consults it with the results the
# wrong way round. That is the mistake a later edit is most likely to
# make, since the two results are structurally identical and only the
# parameter position distinguishes them.
#
# No network and no database. The tracking service is replaced wholesale
# — health_check imports it inside the function body, so the patch
# target is the module it imports from — and query_all is the only other
# collaborator it reaches.
# ----------------------------------------------------------------------


class _Args:
    slug = 'bza'
    target = 'production'


class _FakeTracking:
    """Returns the two results it was constructed with, and nothing else.

    `default_branch_head` answers a real sha so the version branch is
    taken; returning None would skip it, which is a separate case
    covered by test_no_version_check_attempted.
    """

    def __init__(self, http_result, version_result):
        self._http = http_result
        self._version = version_result

    def get_deployment_history(self, **kwargs):
        return [{'id': 441, 'status': 'success'}]

    def run_http_health_check(self, **kwargs):
        return self._http

    def default_branch_head(self, project_id):
        return '59F2B104B6955553'

    def run_version_health_check(self, **kwargs):
        return self._version


class _Host(DeployOpsMixin):
    """The mixin needs a query_all; DeployCommands supplies a real one."""

    def query_all(self, sql, params=None):
        return [{
            'access_url': 'https://aireadalong.com',
            'host': 'aireadalong.com',
            'project_id': 1,
        }]


def _health_check(http_result, version_result):
    with patch('services.deployment_tracking_service.'
               'DeploymentTrackingService',
               lambda *a, **k: _FakeTracking(http_result, version_result)):
        return _Host().health_check(_Args())


def test_health_check_returns_drift_code():
    assert _health_check(
        _http('pass', 200),
        _version('fail', 200, live='B5A0EC2C', expected='59F2B104',
                 error='live B5A0EC2C, graph 59F2B104'),
    ) == VERIFY_DRIFT


def test_health_check_returns_unreachable_code():
    err = "Failed to resolve 'aireadalong.com'"
    assert _health_check(
        _http('fail', None, error=err),
        _version('fail', None, error=err),
    ) == VERIFY_UNREACHABLE


def test_health_check_returns_degraded_code():
    assert _health_check(
        _http('pass', 200),
        _version('fail', 200, error="no 'sha' in the response body"),
    ) == VERIFY_DEGRADED


def test_health_check_returns_zero_when_current():
    assert _health_check(
        _http('pass', 200),
        _version('pass', 200, live='59F2B104', expected='59F2B104'),
    ) == VERIFY_OK


def test_health_check_names_the_verdict_in_its_output(capsys):
    """The exit code is for systemd; the journal line is for the human.

    systemd reports the number and nothing else, so a reader who sees
    `status=11/n/a` goes to the journal next. A verdict word there is
    cheaper than reconstructing one from two check lines, and it is also
    what makes the codes self-documenting for anyone who has not read
    the unit file.
    """
    err = "Failed to resolve 'aireadalong.com'"
    _health_check(_http('fail', None, error=err),
                  _version('fail', None, error=err))
    assert 'UNREACHABLE' in capsys.readouterr().out

    _health_check(_http('pass', 200),
                  _version('fail', 200, live='B5A0EC2C', expected='59F2B104',
                           error='live B5A0EC2C, graph 59F2B104'))
    assert 'DRIFT' in capsys.readouterr().out


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v']))
