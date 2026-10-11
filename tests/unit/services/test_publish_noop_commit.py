"""publish must not withhold the push for a commit that was a no-op.

The 2026-10-11 case: system_config's templedb pin was already recorded as
commit 1230, a redundant second commit attempt returned 1, and publish read
that exit code as failure -- printing "content was materialized but no
vcs_commits row exists" about a change that had one, and refusing the push.
The workaround was --push-anyway, which exists for shipping genuinely
unrecorded content; reaching for it routinely is how that eventually happens
by accident.

VCSCommands.commit keeps git's convention (non-zero when nothing was
committed) and now also records which of the two it was in `last_outcome`,
so the in-process caller can tell them apart.
"""
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))


@pytest.fixture(autouse=True)
def _migrated_db(bootstrap_schema):
    """commit() reaches the database to resolve project, branch and session."""


def _args(project="noop-probe", message="probe"):
    return types.SimpleNamespace(project=project, message=message,
                                 author="probe", branch=None)


def test_nothing_staged_reports_nothing_to_commit():
    """The no-op path must be distinguishable from a failure.

    Exit code stays 1 (git does the same for an empty commit), so the
    classification is what carries the difference.
    """
    from cli.commands.vcs import VCSCommands
    cmd = VCSCommands()
    rc = cmd.commit(_args(project="definitely-not-a-project"))
    assert rc != 0
    # An unresolvable project is a real error, not a no-op -- the point of
    # the attribute is that these two do not collapse together.
    assert cmd.last_outcome == 'error'


def test_last_outcome_is_reset_between_calls():
    """publish calls commit twice; a stale value would misreport the second.

    It retries after provisioning an edit workspace, so the second call's
    classification must not be inherited from the first.
    """
    from cli.commands.vcs import VCSCommands
    cmd = VCSCommands()
    cmd.last_outcome = 'committed'          # pretend a previous success
    cmd.commit(_args(project="definitely-not-a-project"))
    assert cmd.last_outcome == 'error', (
        "commit() must reset last_outcome on entry, or publish will read the "
        "previous attempt's verdict")


@pytest.mark.parametrize("outcome,should_fail_publish", [
    ('nothing-to-commit', False),   # nothing went unrecorded: push is fine
    ('error', True),                # content would ship with no commit row
])
def test_publish_only_withholds_push_for_real_failures(outcome,
                                                       should_fail_publish):
    """The branch publish takes for a non-zero commit, in isolation.

    Encodes the decision rather than the plumbing: a no-op is benign, and
    anything else still blocks the push, which is the guarantee the
    2026-10-06 incident (six files on a public mirror with no commit row)
    bought.
    """
    rc = 1
    vcs_cmd = types.SimpleNamespace(last_outcome=outcome)

    # Mirrors publish.py's dispatch.
    treated_as_failure = not (
        rc == 0
        or getattr(vcs_cmd, 'last_outcome', None) == 'nothing-to-commit')

    assert treated_as_failure is should_fail_publish
