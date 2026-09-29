#!/usr/bin/env python3
"""Claims: what we know about a revision, and how firmly.

Phase 1 read surface (docs/CLAIMS_AND_WARRANTS.md). Deliberately a
table, not a graph view: claim graphs are shallow (a claim rests on one
or two evidence rows) and wide (thousands of claims), which is the shape
node-link diagrams are worst at. Browsing the edges is already free via
`templedb entity show Claim <id>` — claims are mirrored as entities.

CLI:
  templedb claims list <slug>     -- coverage table, HEAD-covering first
  templedb claims show <id>       -- one claim, its scope and evidence
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class ClaimsCommands(Command):
    """Inspect recorded claims."""

    def list(self, args):
        from services.claims_service import coverage, ready
        if not ready():
            print("claims tables not present — migration 116 has not been "
                  "applied yet (needs `templedb publish run templedb` and a "
                  "nix rebuild; the migrator reads site-packages/migrations).")
            return 1

        rows = coverage(args.project_slug, limit=args.limit)
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        if not rows:
            print(f"No claims recorded for '{args.project_slug}'.")
            print("Claims are asserted automatically by work that produces "
                  "evidence (test runs, AST builds) — run some.")
            return 0

        covering = sum(1 for r in rows if r["covers_head"])
        print(f"\n{len(rows)} claim(s) for {args.project_slug}: "
              f"{covering} covering HEAD, {len(rows) - covering} at older "
              f"revisions\n")
        for r in rows:
            mark = "HEAD" if r["covers_head"] else r["revision"]
            flag = "!" if r["undercutting"] else " "
            print(f"  [{mark:>12}]{flag} #{r['id']}  {r['statement']}")
            scope = f"warrant={r['warrant_kind']}  by={r['asserted_by']}"
            if r["host_name"]:
                scope += f"  host={r['host_name']}"
            print(f"                  {scope}")
            if not r["covers_head"]:
                print(f"                  still true at {r['revision']}; "
                      f"says nothing about HEAD")
            print()
        return 0

    def show(self, args):
        from db_utils import query_all, query_one
        claim = query_one("""
            SELECT c.*, p.slug, substr(vc.commit_hash, 1, 12) AS revision
              FROM claims c
              JOIN projects p ON p.id = c.project_id
              JOIN vcs_commits vc ON vc.id = c.commit_id
             WHERE c.id = ?""", (args.claim_id,))
        if not claim:
            print(f"No claim #{args.claim_id}.")
            return 1

        print(f"\nclaim #{claim['id']}: {claim['statement']}\n")
        print(f"  scope      {claim['slug']} @ {claim['revision']}"
              + (f" on {claim['host_name']}" if claim["host_name"] else ""))
        print(f"  warrant    {claim['warrant_kind']}")
        if claim["warrant_gloss"]:
            print(f"             {claim['warrant_gloss']}")
        print(f"  asserted   {claim['asserted_by']} at {claim['created_at']}")
        if claim["report_ref"]:
            print(f"  report     {claim['report_ref']}")
        if claim["inputs_json"]:
            print(f"  inputs     {claim['inputs_json']}")

        evidence = query_all(
            "SELECT evidence_kind, evidence_ref, role FROM claim_evidence "
            "WHERE claim_id = ? ORDER BY role, evidence_kind", (args.claim_id,))
        print(f"\n  evidence ({len(evidence)}):")
        for e in evidence or []:
            print(f"    {e['role']:<10} {e['evidence_kind']} {e['evidence_ref']}")
        if not evidence:
            print("    (none — this claim is an assertion, not an observation)")

        print("\n  Phase 1 records warrants but does not check them; there is "
              "no verdict here yet.\n")
        return 0


def register(cli):
    """Register templedb claims command tree."""
    cmd = ClaimsCommands()
    parser = cli.register_command(
        'claims', None, help_text='Recorded claims and their revision scope')
    sub = parser.add_subparsers(dest='claims_subcommand', required=True)

    ls = sub.add_parser('list', help='Coverage table for a project')
    ls.add_argument('project_slug', help='Project slug')
    ls.add_argument('--limit', type=int, default=200)
    ls.add_argument('--json', action='store_true')
    cli.commands['claims.list'] = cmd.list

    sh = sub.add_parser('show', help='One claim: scope, warrant, evidence')
    sh.add_argument('claim_id', type=int)
    cli.commands['claims.show'] = cmd.show
