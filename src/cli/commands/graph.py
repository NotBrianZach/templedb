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


def _print_candidates(header: str, rows, cols, usage_hint: str) -> None:
    """Pretty-print a ranked candidate list with a usage hint."""
    if not rows:
        print(f"\n{header}\n  (no candidates found)\n\n  {usage_hint}\n")
        return
    print(f"\n{header}\n")
    widths = [max(len(c[0]), max((len(str(r.get(c[1], ''))) for r in rows), default=0))
              for c in cols]
    header_row = "  " + "  ".join(f"{c[0]:<{w}}" for c, w in zip(cols, widths))
    print(header_row)
    print("  " + "  ".join("-" * w for w in widths))
    for r in rows:
        print("  " + "  ".join(f"{str(r.get(c[1], '')):<{w}}"
                                for c, w in zip(cols, widths)))
    print(f"\n  {usage_hint}\n")


class GraphCommands(Command):
    """Knowledge graph query handlers"""

    def search(self, args) -> int:
        """Fuzzy search across everything."""
        from knowledge_graph import search_everywhere
        from graph_frecency import log_query, rank_candidates

        if not args.query:
            log_query("graph.search")
            cands = rank_candidates("project", "graph.search", limit=10)
            _print_candidates(
                "graph search — enter any string to fuzzy-match projects, files, "
                "env vars, secrets, config, commits, and symbols.\n"
                "  Recently active projects (hint at what's searchable):",
                cands, [("project", "name"), ("full name", "project_name")],
                "Usage: templedb graph search <query>")
            return 0

        log_query("graph.search", args={"query": args.query})
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
        from graph_frecency import log_query, rank_candidates

        if not args.name:
            log_query("graph.who-uses")
            env_vars = rank_candidates("env_var", "graph.who-uses", limit=10)
            secrets = rank_candidates("secret", "graph.who-uses", limit=10)
            _print_candidates(
                "graph who-uses — pass an env var or secret name to see which "
                "projects reference it.\n"
                "  Top env vars by cross-project usage:",
                env_vars, [("name", "name"), ("projects", "project_count")],
                "Usage: templedb graph who-uses <NAME>")
            if secrets:
                _print_candidates(
                    "Top secrets by cross-project usage:",
                    secrets, [("name", "name"), ("projects", "project_count")],
                    "Usage: templedb graph who-uses <NAME>")
            return 0

        log_query("graph.who-uses", target_kind="env_var", target_key=args.name,
                  args={"name": args.name})
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
        from graph_frecency import log_query, rank_candidates

        if not args.project:
            log_query("graph.changes")
            cands = rank_candidates("project", "graph.changes", limit=12)
            _print_candidates(
                "graph changes — show commits & uncommitted files since last deploy.\n"
                "  Recently updated projects:",
                cands, [("project", "name"), ("full name", "project_name")],
                "Usage: templedb graph changes <PROJECT>")
            return 0

        log_query("graph.changes", target_kind="project", target_key=args.project,
                  args={"project": args.project})
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
        from graph_frecency import log_query, rank_candidates

        if not args.project:
            log_query("graph.deps")
            cands = rank_candidates("project", "graph.deps", limit=12)
            _print_candidates(
                "graph deps — show a project's file types, env vars, secrets, "
                "flake inputs, and deploy history.\n"
                "  Recently updated projects:",
                cands, [("project", "name"), ("full name", "project_name")],
                "Usage: templedb graph deps <PROJECT>")
            return 0

        log_query("graph.deps", target_kind="project", target_key=args.project,
                  args={"project": args.project})
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

    def build_deps(self, args) -> int:
        """Build file dependency graph for a project."""
        from file_deps import build_file_deps_for_project
        from graph_frecency import log_query, rank_candidates

        if not args.project:
            log_query("graph.build-deps")
            cands = rank_candidates("project", "graph.build-deps", limit=12)
            _print_candidates(
                "graph build-deps — (re)build the file-import graph for a project.\n"
                "  Recently updated projects:",
                cands, [("project", "name"), ("full name", "project_name")],
                "Usage: templedb graph build-deps <PROJECT>")
            return 0

        log_query("graph.build-deps", target_kind="project", target_key=args.project,
                  args={"project": args.project})
        project = args.project
        print(f"Building file dependency graph for {project}...")
        result = build_file_deps_for_project(project)

        if "error" in result:
            print(f"Error: {result['error']}")
            return 1

        print(f"  Files scanned: {result['files_scanned']}")
        print(f"  Imports found: {result['imports_found']}")
        print(f"  Resolved: {result['resolved']}")
        print(f"  Unresolved: {result['unresolved']}")
        return 0

    def importers(self, args) -> int:
        """Find what imports a given file."""
        from knowledge_graph import file_importers
        from graph_frecency import log_query, rank_candidates

        if not args.project:
            log_query("graph.importers")
            cands = rank_candidates("project_with_file_deps", "graph.importers", limit=12)
            _print_candidates(
                "graph importers — find files that import a given file.\n"
                "  Projects with file-dependency data (most edges first):",
                cands, [("project", "name"), ("dep edges", "dep_count")],
                "Usage: templedb graph importers <PROJECT> <FILE>")
            return 0

        if not args.file:
            log_query("graph.importers", target_kind="project",
                      target_key=args.project, project_slug=args.project)
            cands = rank_candidates("file", "graph.importers",
                                    project_slug=args.project, limit=15)
            _print_candidates(
                f"graph importers {args.project} — top files by importer count:",
                cands, [("file", "name"), ("importers", "importer_count")],
                f"Usage: templedb graph importers {args.project} <FILE>")
            return 0

        log_query("graph.importers", target_kind="file", target_key=args.file,
                  project_slug=args.project,
                  args={"project": args.project, "file": args.file})
        results = file_importers(args.project, args.file)
        if not results:
            print(f"No files import {args.file}")
            return 0

        print(f"\nFiles importing {args.file}:")
        for r in results:
            print(f"  {r['importer']:50s} ({r['dependency_type']})")
        return 0

    def callers(self, args) -> int:
        """Find what calls a given symbol."""
        from knowledge_graph import symbol_callers
        from graph_frecency import log_query, rank_candidates

        if not args.project:
            log_query("graph.callers")
            cands = rank_candidates("project_with_symbols", "graph.callers", limit=12)
            _print_candidates(
                "graph callers — find symbols that call a given symbol.\n"
                "  Projects with code-symbol data (most symbols first):",
                cands, [("project", "name"), ("symbols", "symbol_count")],
                "Usage: templedb graph callers <PROJECT> <SYMBOL>")
            return 0

        if not args.symbol:
            log_query("graph.callers", target_kind="project",
                      target_key=args.project, project_slug=args.project)
            cands = rank_candidates("symbol", "graph.callers",
                                    project_slug=args.project, limit=15)
            _print_candidates(
                f"graph callers {args.project} — top symbols by caller count:",
                cands, [("symbol", "name"), ("kind", "symbol_type"),
                        ("callers", "caller_count")],
                f"Usage: templedb graph callers {args.project} <SYMBOL>")
            return 0

        log_query("graph.callers", target_kind="symbol", target_key=args.symbol,
                  project_slug=args.project,
                  args={"project": args.project, "symbol": args.symbol})
        results = symbol_callers(args.project, args.symbol)
        if not results:
            print(f"No callers found for {args.symbol}")
            return 0

        print(f"\nCallers of {args.symbol}:")
        for r in results:
            print(f"  {r['caller']:30s} {r['caller_file']:40s} line {r.get('call_line', '?')}")
        return 0

    def overview(self, args) -> int:
        """Cross-project analysis."""
        from knowledge_graph import cross_project_analysis
        from graph_frecency import log_query

        log_query("graph.overview")
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

    # graph search — query optional so we can show hint when omitted
    s = subparsers.add_parser('search', help='Fuzzy search across everything')
    s.add_argument('query', nargs='?', help='Search query (omit for a usage hint)')
    s.add_argument('--limit', type=int, default=50)
    s.add_argument('--json', action='store_true')
    cli.commands['graph.search'] = cmd.search

    # graph who-uses
    w = subparsers.add_parser('who-uses', help='Find which projects use a secret/var/string')
    w.add_argument('name', nargs='?',
                   help='Secret name, env var, or search string (omit for top candidates)')
    w.add_argument('--json', action='store_true')
    cli.commands['graph.who-uses'] = cmd.who_uses

    # graph changes
    c = subparsers.add_parser('changes', help='What changed since last deploy')
    c.add_argument('project', nargs='?', help='Project slug (omit for top candidates)')
    c.add_argument('--json', action='store_true')
    cli.commands['graph.changes'] = cmd.changes

    # graph deps
    d = subparsers.add_parser('deps', help='Project dependency graph')
    d.add_argument('project', nargs='?', help='Project slug (omit for top candidates)')
    d.add_argument('--json', action='store_true')
    cli.commands['graph.deps'] = cmd.deps

    # graph overview
    o = subparsers.add_parser('overview', help='Cross-project analysis')
    o.add_argument('--json', action='store_true')
    cli.commands['graph.overview'] = cmd.overview

    # graph build-deps
    bd = subparsers.add_parser('build-deps', help='Build file dependency graph')
    bd.add_argument('project', nargs='?', help='Project slug (omit for top candidates)')
    cli.commands['graph.build-deps'] = cmd.build_deps

    # graph importers
    im = subparsers.add_parser('importers', help='Find what imports a file')
    im.add_argument('project', nargs='?', help='Project slug (omit for top candidates)')
    im.add_argument('file', nargs='?', help='File path (omit for top files in project)')
    cli.commands['graph.importers'] = cmd.importers

    # graph callers
    ca = subparsers.add_parser('callers', help='Find what calls a symbol')
    ca.add_argument('project', nargs='?', help='Project slug (omit for top candidates)')
    ca.add_argument('symbol', nargs='?', help='Symbol name (omit for top symbols in project)')
    cli.commands['graph.callers'] = cmd.callers
