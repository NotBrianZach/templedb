#!/usr/bin/env python3
"""
Knowledge graph query commands.
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class GraphCommands(Command):
    """Knowledge graph query handlers"""

    def search(self, args) -> int:
        """Fuzzy search across everything."""
        from knowledge_graph import search_everywhere

        results = search_everywhere(args.query, limit=args.limit)

        if not results:
            print(f"No results for '{args.query}'")
            return 0

        if args.json:
            print(json.dumps(results, indent=2, default=str))
            return 0

        total = sum(len(v) for v in results.values())
        print(f"\nSearch: '{args.query}' ({total} results)\n")

        for category, items in results.items():
            print(f"  {category} ({len(items)})")
            for item in items[:5]:
                if category == "projects":
                    print(f"    {item['slug']:25s} {item.get('project_type', '')}")
                elif category == "files":
                    print(f"    {item['slug']:15s} {item['file_path']}")
                elif category == "env_vars":
                    val = "****" if item.get('is_secret') else (item.get('var_value', '')[:40])
                    print(f"    {item.get('slug', ''):15s} {item['var_name']} = {val}")
                elif category == "secrets":
                    print(f"    {item['slug']:15s} {item['secret_name']} [{item.get('profile', '')}]")
                elif category == "config":
                    print(f"    {item['key']:40s} {item['value'][:60]}")
                elif category == "commits":
                    print(f"    {item['slug']:15s} {item['commit_hash'][:8]} {item.get('commit_message', '')[:50]}")
                elif category == "symbols":
                    print(f"    {item['slug']:15s} {item['symbol_type']:10s} {item.get('symbol_name', '')}")
            if len(items) > 5:
                print(f"    ... +{len(items) - 5} more")
            print()
        return 0

    def who_uses(self, args) -> int:
        """Find which projects use a secret, env var, or contain a string."""
        from knowledge_graph import who_uses

        results = who_uses(args.name)

        if args.json:
            print(json.dumps(results, indent=2, default=str))
            return 0

        if not results:
            print(f"'{args.name}' not found in any project")
            return 0

        print(f"\nWho uses '{args.name}':\n")
        for category, items in results.items():
            print(f"  {category.replace('_', ' ')} ({len(items)})")
            for item in items[:10]:
                if 'var_name' in item:
                    print(f"    {item['slug']:20s} {item['var_name']}")
                elif 'secret_name' in item:
                    print(f"    {item['slug']:20s} {item['secret_name']}")
                elif 'file_path' in item:
                    print(f"    {item['slug']:20s} {item['file_path']}")
            if len(items) > 10:
                print(f"    ... +{len(items) - 10} more")
            print()
        return 0

    def changes(self, args) -> int:
        """Show what changed since last deploy."""
        from knowledge_graph import changes_since_deploy

        results = changes_since_deploy(args.project)

        if args.json:
            print(json.dumps(results, indent=2, default=str))
            return 0

        if "error" in results:
            print(f"Error: {results['error']}")
            return 1

        print(f"\nChanges for {args.project} since last deploy")
        print(f"  Last deploy: {results['last_deploy'] or 'never'}\n")

        commits = results.get("commits_since", [])
        if commits:
            print(f"  Commits ({len(commits)}):")
            for c in commits[:10]:
                print(f"    {c['commit_hash'][:8]} {c.get('commit_message', '')[:60]} ({c['author']})")
        else:
            print("  No new commits")

        changes = results.get("uncommitted_changes", [])
        if changes:
            print(f"\n  Uncommitted ({len(changes)}):")
            for w in changes:
                staged = "+" if w.get("staged") else " "
                print(f"    {staged} [{w['state']:8s}] {w['file_path']}")

        print()
        return 0

    def deps(self, args) -> int:
        """Show project dependency graph."""
        from knowledge_graph import project_dependencies

        results = project_dependencies(args.project)

        if args.json:
            print(json.dumps(results, indent=2, default=str))
            return 0

        if "error" in results:
            print(f"Error: {results['error']}")
            return 1

        proj = results["project"]
        print(f"\n{proj['slug']} ({proj.get('project_type', 'regular')})")
        print(f"  Path: {proj.get('repo_url', 'N/A')}\n")

        if results["file_types"]:
            print("  File types:")
            for ft in results["file_types"]:
                print(f"    {ft['type_name']:25s} {ft['count']} files")

        if results["env_vars"]:
            print(f"\n  Env vars ({len(results['env_vars'])}):")
            for ev in results["env_vars"][:10]:
                val = "****" if ev["is_secret"] else ev["var_value"][:40]
                print(f"    {ev['var_name']:30s} {val}")

        if results["secrets"]:
            print(f"\n  Secrets ({len(results['secrets'])}):")
            for s in results["secrets"]:
                print(f"    {s['secret_name']:30s} [{s['profile']}]")

        if results["flake_inputs"]:
            print(f"\n  Flake inputs:")
            for fi in results["flake_inputs"]:
                name = fi["key"].replace("nixos.flake.input.", "")
                print(f"    {name:25s} {fi['value']}")

        if results["deploys"]:
            d = results["deploys"]
            print(f"\n  Deploys: {d.get('total', 0)} total, {d.get('successful', 0)} successful")
            print(f"  Last: {d.get('last_deploy', 'never')}")

        print()
        return 0

    def overview(self, args) -> int:
        """Cross-project analysis."""
        from knowledge_graph import cross_project_analysis

        results = cross_project_analysis()

        if args.json:
            print(json.dumps(results, indent=2, default=str))
            return 0

        print("\nTempleDB Knowledge Graph Overview\n")

        print("Projects:")
        for p in results["projects"]:
            print(f"  {p['slug']:25s} {p.get('project_type', ''):15s} "
                  f"{p['file_count']:>4} files  {p['commit_count']:>3} commits  "
                  f"{p['env_var_count']:>2} vars  {p['secret_count']:>2} secrets")

        if results["shared_secrets"]:
            print(f"\nShared secrets:")
            for s in results["shared_secrets"]:
                print(f"  {s['secret_name']:30s} used by: {s['projects']}")

        if results["shared_vars"]:
            print(f"\nShared env vars:")
            for v in results["shared_vars"]:
                print(f"  {v['var_name']:30s} used by: {v['projects']}")

        if results["recent_activity"]:
            print(f"\nRecent activity:")
            for r in results["recent_activity"][:10]:
                print(f"  {r['slug']:15s} {r['commit_hash'][:8]} {r.get('commit_message', '')[:50]}")

        print()
        return 0


def register(cli):
    """Register knowledge graph commands."""
    cmd = GraphCommands()

    graph_parser = cli.register_command(
        'graph', None, help_text='Knowledge graph queries across projects'
    )
    subparsers = graph_parser.add_subparsers(dest='graph_subcommand', required=True)

    # graph search
    s = subparsers.add_parser('search', help='Fuzzy search across everything')
    s.add_argument('query', help='Search query')
    s.add_argument('--limit', type=int, default=50)
    s.add_argument('--json', action='store_true')
    cli.commands['graph.search'] = cmd.search

    # graph who-uses
    w = subparsers.add_parser('who-uses', help='Find which projects use a secret/var/string')
    w.add_argument('name', help='Secret name, env var, or search string')
    w.add_argument('--json', action='store_true')
    cli.commands['graph.who-uses'] = cmd.who_uses

    # graph changes
    c = subparsers.add_parser('changes', help='What changed since last deploy')
    c.add_argument('project', help='Project slug')
    c.add_argument('--json', action='store_true')
    cli.commands['graph.changes'] = cmd.changes

    # graph deps
    d = subparsers.add_parser('deps', help='Project dependency graph')
    d.add_argument('project', help='Project slug')
    d.add_argument('--json', action='store_true')
    cli.commands['graph.deps'] = cmd.deps

    # graph overview
    o = subparsers.add_parser('overview', help='Cross-project analysis')
    o.add_argument('--json', action='store_true')
    cli.commands['graph.overview'] = cmd.overview
