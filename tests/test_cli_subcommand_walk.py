"""Regression: the subcommand walk must terminate.

`templedb deploy fleet deploy <project> <network>` hung forever. Not
slowly — the process sat in state R with no children and no output
until it was killed, which is the worst failure shape available because
a hang is indistinguishable from slow work. There was nothing wrong
with the fleet handler; the walk never reached it.

The cause is that the walk keys on the subcommand *value* rather than
the level. `deploy` registers dest='deploy_subcommand' and fleet
registers dest='fleet_subcommand', so a fleet verb named `deploy`
closes a cycle:

    parts=['deploy']           deploy_subcommand -> 'fleet'
    parts=['deploy','fleet']   fleet_subcommand  -> 'deploy'
    parts=[...,'deploy']       deploy_subcommand -> 'fleet'     (again)

`parts` grows without bound. Any subcommand sharing a name with one of
its ancestors does this, so the guard is tested as a property and not
just on the one path that happened to trip it.

Each test fails by hanging rather than by asserting, which no runner
reports usefully, so the walk is called in a thread with a timeout. A
plain call would wedge the whole suite.
"""
import sys
import threading
import unittest
from argparse import Namespace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from cli.core import walk_subcommand_chain  # noqa: E402

TIMEOUT_SECONDS = 10


def walk_with_timeout(args):
    """Run the walk in a thread; fail loudly instead of hanging the suite.

    The thread is left running on timeout — it is in an unbounded loop
    appending to a list and cannot be interrupted from outside. It dies
    with the interpreter. That is acceptable for a test that has
    already failed, and is why the loop needs a bound in the first
    place.
    """
    box = {}

    def run():
        box['parts'] = walk_subcommand_chain(args)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(TIMEOUT_SECONDS)
    if t.is_alive():
        raise AssertionError(
            f"walk_subcommand_chain did not terminate within "
            f"{TIMEOUT_SECONDS}s for {args!r} — the dest-consumed guard "
            f"is gone and the walk is cycling again")
    return box['parts']


class TestSubcommandWalkTerminates(unittest.TestCase):

    def test_self_named_subcommand_resolves(self):
        """`deploy fleet deploy` — the path that actually hung."""
        args = Namespace(command='deploy',
                         deploy_subcommand='fleet',
                         fleet_subcommand='deploy')
        self.assertEqual(walk_with_timeout(args),
                         ['deploy', 'fleet', 'deploy'])

    def test_self_named_subcommand_other_verbs_unaffected(self):
        """Sibling verbs that never collided must still resolve."""
        for verb in ('status', 'destroy', 'check', 'ssh', 'diff'):
            with self.subTest(verb=verb):
                args = Namespace(command='deploy',
                                 deploy_subcommand='fleet',
                                 fleet_subcommand=verb)
                self.assertEqual(walk_with_timeout(args),
                                 ['deploy', 'fleet', verb])

    def test_four_level_chain_still_resolves(self):
        """The depth the cap removal was for is not regressed by the guard."""
        args = Namespace(command='deploy',
                         deploy_subcommand='fleet',
                         fleet_subcommand='network',
                         network_command='list')
        self.assertEqual(walk_with_timeout(args),
                         ['deploy', 'fleet', 'network', 'list'])

    def test_immediate_self_reference(self):
        """A verb named after its own parent, one level up."""
        args = Namespace(command='deploy', deploy_subcommand='deploy')
        self.assertEqual(walk_with_timeout(args), ['deploy', 'deploy'])

    def test_longer_cycle(self):
        """Three-way cycle, not just the two-way one observed."""
        args = Namespace(command='a', a_subcommand='b',
                         b_subcommand='c', c_subcommand='a')
        parts = walk_with_timeout(args)
        self.assertEqual(parts, ['a', 'b', 'c', 'a'])

    def test_missing_nested_value_stops_walk(self):
        """dest present but None → stop, so a shorter key can match."""
        args = Namespace(command='deploy',
                         deploy_subcommand='fleet',
                         fleet_subcommand=None)
        self.assertEqual(walk_with_timeout(args), ['deploy', 'fleet'])

    def test_no_command(self):
        self.assertEqual(walk_with_timeout(Namespace(command=None)), [])

    def test_leaf_command(self):
        self.assertEqual(walk_with_timeout(Namespace(command='summary')),
                         ['summary'])

    def test_command_suffix_variant(self):
        """`_command` is honoured as well as `_subcommand`."""
        args = Namespace(command='storage', storage_command='blob',
                         blob_command='status')
        self.assertEqual(walk_with_timeout(args),
                         ['storage', 'blob', 'status'])


if __name__ == '__main__':
    unittest.main()
