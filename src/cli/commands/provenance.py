#!/usr/bin/env python3
"""`templedb provenance` — preset workflow queries over the entity graph.

Thin wrappers on top of `templedb entity trace` that spell out the
common workflow queries the observer/integrator plan built the graph
for. Each command is a preset (start entity, direction, via, depth).

Workflows named in the reports:
    provenance machine <name>     Workflow B (deploy archaeology)
                                  Machine → Generation → Commit
    provenance deployment <id>    Workflow B, from the other side
                                  Deployment → Machine + Commit + StorePath
    provenance report <path>      Workflow F
                                  Report → motivated → Commit
    provenance commit <hash>      Reverse-walk: which reports motivated
                                  this commit, which deployments include it
    provenance intent <id>        Workflow A (multi-agent refactor)
                                  EditIntent → applied-to → Commit
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from cli.commands.entity import EntityCommands
from logger import get_logger

logger = get_logger(__name__)


class ProvenanceCommands(Command):
    """Preset workflow-query commands over the entity graph."""

    def __init__(self):
        super().__init__()
        self._ent = EntityCommands()

    def machine(self, args):
        """Workflow B: what did this machine ever run?

        Machine → ran → Generation → built-from → Commit + installs → StorePath.
        """
        import argparse
        return self._ent.graph_trace(argparse.Namespace(
            entity=f"Machine/{args.name}",
            depth=args.depth,
            direction='out',
            via='ran,built-from,installs,contains',
            limit=args.limit,
        ))

    def deployment(self, args):
        """Workflow B from the deployment side.

        Deployment → targets → Machine, from-commit → Commit, ...
        """
        import argparse
        return self._ent.graph_trace(argparse.Namespace(
            entity=f"Deployment/{args.id}",
            depth=args.depth,
            direction='both',
            via='targets,from-commit,contains,ran',
            limit=args.limit,
        ))

    def report(self, args):
        """Workflow F: which commits did this report motivate?

        Report → motivated → Commit → contains → File.
        """
        import argparse
        return self._ent.graph_trace(argparse.Namespace(
            entity=f"Report/{args.path}",
            depth=args.depth,
            direction='out',
            via='motivated,contains',
            limit=args.limit,
        ))

    def commit(self, args):
        """Reverse-walk from a commit.

        Commit ← motivated ← Report,
        Commit ← from-commit ← Deployment ← targets → Machine,
        Commit ← built-from ← Generation ← ran ← Machine,
        Commit ← applied-to ← EditIntent.
        """
        import argparse
        # Accept prefix; find matching Commit external_ref.
        from db_utils import query_one
        commit_ref = args.hash
        if '/' not in commit_ref:
            # User gave just the hash — find the project prefix.
            # Prefix match: 'aaabbb' matches 'testproj/aaabbbccc...'
            # Use LIKE '%/HASH%' to allow the given argument to be a
            # prefix, not just the full hash.
            found = query_one(
                """SELECT external_ref FROM entities
                    WHERE kind = 'Commit'
                      AND (external_ref LIKE '%/' || ? || '%'
                           OR LOWER(external_ref) LIKE
                              '%/' || LOWER(?) || '%')
                    LIMIT 1""",
                (commit_ref, commit_ref),
            )
            if not found:
                logger.error(f"No Commit entity matches {commit_ref!r}")
                return 1
            commit_ref = found['external_ref']
        return self._ent.graph_trace(argparse.Namespace(
            entity=f"Commit/{commit_ref}",
            depth=args.depth,
            direction='both',
            via='motivated,from-commit,built-from,applied-to,contains,ran,targets',
            limit=args.limit,
        ))

    def callers(self, args):
        """Who calls this Symbol? Inbound walk over 'calls' relations.

        Accepts either 'Symbol/ref' or just 'ref' for convenience.
        """
        import argparse
        entity = (args.symbol if args.symbol.startswith('Symbol/')
                  else f"Symbol/{args.symbol}")
        return self._ent.graph_trace(argparse.Namespace(
            entity=entity,
            depth=args.depth,
            direction='in',
            via='calls',
            limit=args.limit,
        ))

    def callees(self, args):
        """What does this Symbol call? Outbound walk over 'calls'."""
        import argparse
        entity = (args.symbol if args.symbol.startswith('Symbol/')
                  else f"Symbol/{args.symbol}")
        return self._ent.graph_trace(argparse.Namespace(
            entity=entity,
            depth=args.depth,
            direction='out',
            via='calls',
            limit=args.limit,
        ))

    def intent(self, args):
        """Workflow A: what did this edit intent lead to?

        EditIntent → applied-to → Commit.
        """
        import argparse
        return self._ent.graph_trace(argparse.Namespace(
            entity=f"EditIntent/{args.id}",
            depth=args.depth,
            direction='both',
            via='applied-to,proposed,contains',
            limit=args.limit,
        ))


def register(cli):
    """Register `templedb provenance ...` subcommands."""
    cmd = ProvenanceCommands()

    parser = cli.subparsers.add_parser(
        'provenance',
        help='Preset workflow queries over the entity graph',
    )
    sub = parser.add_subparsers(dest='provenance_subcommand', required=True)

    m = sub.add_parser('machine',
                       help='Workflow B: what did this machine run?')
    m.add_argument('name', help='Machine name (e.g. zMothership2)')
    m.add_argument('--depth', default=4)
    m.add_argument('--limit', default=15)
    cli.commands['provenance.machine'] = cmd.machine

    d = sub.add_parser('deployment',
                       help='Workflow B (from deployment): its target + commit')
    d.add_argument('id', help='Deployment id (numeric)')
    d.add_argument('--depth', default=3)
    d.add_argument('--limit', default=10)
    cli.commands['provenance.deployment'] = cmd.deployment

    r = sub.add_parser('report',
                       help='Workflow F: which commits did this report motivate?')
    r.add_argument('path',
                   help='reports/YYYY-MM-DD-...html (external_ref)')
    r.add_argument('--depth', default=3)
    r.add_argument('--limit', default=15)
    cli.commands['provenance.report'] = cmd.report

    c = sub.add_parser('commit',
                       help='Reverse-walk: what led to / uses this commit?')
    c.add_argument('hash', help='Commit hash or prefix')
    c.add_argument('--depth', default=3)
    c.add_argument('--limit', default=15)
    cli.commands['provenance.commit'] = cmd.commit

    i = sub.add_parser('intent',
                       help='Workflow A: what did this intent apply to?')
    i.add_argument('id', help='EditIntent id')
    i.add_argument('--depth', default=3)
    i.add_argument('--limit', default=15)
    cli.commands['provenance.intent'] = cmd.intent

    ca = sub.add_parser('callers',
                        help='Who calls this Python Symbol? '
                             '(inbound walk via calls)')
    ca.add_argument('symbol',
                    help='Symbol/<slug>:<file>:<name> or bare '
                         '<slug>:<file>:<name>')
    ca.add_argument('--depth', default=2)
    ca.add_argument('--limit', default=20)
    cli.commands['provenance.callers'] = cmd.callers

    ce = sub.add_parser('callees',
                        help='What does this Python Symbol call? '
                             '(outbound walk via calls)')
    ce.add_argument('symbol',
                    help='Symbol/<slug>:<file>:<name> or bare '
                         '<slug>:<file>:<name>')
    ce.add_argument('--depth', default=2)
    ce.add_argument('--limit', default=20)
    cli.commands['provenance.callees'] = cmd.callees
