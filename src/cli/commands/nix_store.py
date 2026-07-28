#!/usr/bin/env python3
"""
Nix store integration commands for TempleDB.

Track store paths, closures, generations, and serve a binary cache.
The database IS the nix store index.

Commands:
  templedb nix scan          - Index store paths from current system closure
  templedb nix generations   - List NixOS generations with VCS commit links
  templedb nix closure       - Show/diff closures
  templedb nix who-uses      - Find which projects depend on a package
  templedb nix gc-roots      - Analyze what's keeping store paths alive
  templedb nix cache prepare - Prepare closure for binary cache serving
  templedb nix cache stats   - Show binary cache statistics
  templedb nix stats         - Show overall nix store stats
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


def _fmt_size(n):
    """Format bytes to human-readable."""
    if n is None:
        return "?"
    for unit in ['B', 'KiB', 'MiB', 'GiB', 'TiB']:
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PiB"


class NixStoreCommands(Command):
    """Nix store integration command handlers."""

    def _svc(self):
        from services.nix_store_service import NixStoreService
        return NixStoreService()

    def scan(self, args) -> int:
        """Scan and index store paths from a closure."""
        import os
        svc = self._svc()
        root = args.path or os.readlink("/run/current-system")
        print(f"Scanning closure of {root}...")

        result = svc.scan_store_paths(root)
        print(f"  Scanned: {result['scanned']} paths")
        print(f"  New:     {result['new']}")
        print(f"  Updated: {result['updated']}")

        # Also scan and record generations
        print("\nScanning generations...")
        gen_result = svc.scan_generations()
        print(f"  Scanned: {gen_result['scanned']} generations")
        print(f"  New:     {gen_result['new']}")

        return 0

    def generations(self, args) -> int:
        """List NixOS generations with VCS commit links."""
        svc = self._svc()
        machine = args.machine
        limit = args.limit or 20

        gens = svc.get_generations(machine_name=machine, limit=limit)
        if not gens:
            print("No generations tracked. Run 'templedb nix scan' first.")
            return 0

        # Header
        print(f"{'Gen':>5}  {'Machine':<16}  {'Switched':>19}  {'NixOS Version':<28}  {'Commit':<10}  {'Closure':>8}  {'Diff'}")
        print("─" * 120)

        for g in gens:
            gen_num = g.get("generation_number", "?")
            machine_name = g.get("machine_name", "?")[:16]
            switched = (g.get("switched_at") or "?")[:19]
            version = (g.get("nixos_version") or "?")[:28]
            commit = (g.get("commit_hash") or "")[:10]
            commit_msg = (g.get("commit_message") or "")[:30]
            closure_paths = g.get("closure_paths") or 0

            # Diff summary
            diff_parts = []
            if g.get("diff_added"):
                diff_parts.append(f"+{g['diff_added']}")
            if g.get("diff_removed"):
                diff_parts.append(f"-{g['diff_removed']}")
            if g.get("diff_size_delta"):
                diff_parts.append(_fmt_size(g['diff_size_delta']))
            diff_str = " ".join(diff_parts) if diff_parts else ""

            commit_str = f"{commit} {commit_msg}" if commit else ""

            print(f"{gen_num:>5}  {machine_name:<16}  {switched:>19}  {version:<28}  {commit_str:<40}  {closure_paths:>8}  {diff_str}")

        return 0

    def closure_show(self, args) -> int:
        """Show closure details for a store path or generation."""
        svc = self._svc()
        from db_utils import get_connection
        conn = get_connection()

        if args.generation:
            # Look up by generation number
            import os
            machine = args.machine or os.uname().nodename
            gen = conn.execute("""
                SELECT g.*, cl.total_paths, cl.total_size, cl.closure_hash
                FROM nix_generations g
                LEFT JOIN nix_closures cl ON g.closure_id = cl.id
                WHERE g.machine_name = ? AND g.generation_number = ?
            """, (machine, args.generation)).fetchone()

            if not gen:
                print(f"Generation {args.generation} not found for {machine}")
                return 1

            print(f"Generation: {gen['generation_number']} on {gen['machine_name']}")
            print(f"  Toplevel:  {gen['toplevel_path']}")
            print(f"  Switched:  {gen['switched_at']}")
            print(f"  NixOS:     {gen['nixos_version']}")
            if gen.get("total_paths"):
                print(f"  Paths:     {gen['total_paths']}")
                print(f"  Size:      {_fmt_size(gen['total_size'])}")

            # Show diff if available
            diff = svc.get_closure_diff(gen["id"])
            if diff and diff.get("diff"):
                d = diff["diff"]
                if d.get("added"):
                    print(f"\n  Added ({len(d['added'])}):")
                    for item in d["added"][:15]:
                        print(f"    + {item['name']}  ({_fmt_size(item.get('size'))})")
                if d.get("removed"):
                    print(f"\n  Removed ({len(d['removed'])}):")
                    for item in d["removed"][:15]:
                        print(f"    - {item['name']}  ({_fmt_size(item.get('size'))})")
        else:
            # Show by store path
            path = args.path
            if not path:
                import os
                path = os.readlink("/run/current-system")

            closure = conn.execute(
                "SELECT * FROM nix_closures WHERE toplevel_path = ?", (path,)
            ).fetchone()

            if not closure:
                print(f"Closure not recorded for {path}. Run 'templedb nix scan' first.")
                return 1

            print(f"Closure: {path}")
            print(f"  Hash:   {closure['closure_hash'][:16]}")
            print(f"  Paths:  {closure['total_paths']}")
            print(f"  Size:   {_fmt_size(closure['total_size'])}")

        return 0

    def who_uses(self, args) -> int:
        """Find which projects depend on a package."""
        svc = self._svc()
        results = svc.who_uses(args.package)

        if not results:
            print(f"No projects found using '{args.package}'")
            print("  (Run 'templedb nix scan' to index paths first)")
            return 0

        current_project = None
        for r in results:
            if r["slug"] != current_project:
                current_project = r["slug"]
                print(f"\n{r['slug']} ({r['project_name']}):")
            print(f"  [{r['association']}] {r['package_name']}")

        print(f"\n{len(results)} total associations across {len(set(r['slug'] for r in results))} projects")
        return 0

    def gc_analysis(self, args) -> int:
        """Analyze what's keeping store paths alive."""
        svc = self._svc()
        result = svc.gc_analysis()

        print(f"Store Path Analysis:")
        print(f"  Valid paths:       {result['total_valid_paths']}")
        print(f"  In closures:       {result['paths_in_closures']}")
        print(f"  Orphaned:          {result['orphan_paths']}")

        if result.get("largest_orphans"):
            print(f"\nLargest orphaned paths:")
            for o in result["largest_orphans"]:
                print(f"  {_fmt_size(o.get('nar_size')):>10}  {o['name']}")

        return 0

    def cache_prepare(self, args) -> int:
        """Prepare a closure for binary cache serving."""
        import os
        svc = self._svc()
        path = args.path or os.readlink("/run/current-system")
        print(f"Preparing binary cache for {path}...")

        result = svc.prepare_closure_cache(path)
        print(f"  Prepared: {result['prepared']} paths")
        print(f"  Skipped:  {result['skipped']}")
        print(f"\nBinary cache is served at http://localhost:8420/nix-cache/")
        return 0

    def cache_stats(self, args) -> int:
        """Show binary cache statistics."""
        from db_utils import get_connection
        conn = get_connection()

        stats = conn.execute("""
            SELECT
                COUNT(*) as entries,
                SUM(file_size) as total_size,
                SUM(served_count) as total_served,
                MAX(last_served_at) as last_served
            FROM nix_cache_entries
        """).fetchone()

        print(f"Binary Cache:")
        print(f"  Entries:     {stats['entries']}")
        print(f"  Total size:  {_fmt_size(stats['total_size'])}")
        print(f"  Times served: {stats['total_served'] or 0}")
        if stats['last_served']:
            print(f"  Last served: {stats['last_served']}")
        print(f"\n  Serve URL:   http://localhost:8420/nix-cache/")
        print(f"  Usage:       nix build --substituters http://<host>:8420/nix-cache/")
        return 0

    def stats(self, args) -> int:
        """Show overall nix store statistics."""
        svc = self._svc()
        s = svc.get_store_stats()

        if not s or not s.get("total_paths"):
            print("No store data tracked. Run 'templedb nix scan' first.")
            return 0

        print(f"Nix Store Integration:")
        print(f"  Tracked paths:     {s.get('total_paths', 0)}")
        print(f"  Valid paths:       {s.get('valid_paths', 0)}")
        print(f"  Total NAR size:    {_fmt_size(s.get('total_nar_size'))}")
        print(f"  Unique derivers:   {s.get('unique_derivers', 0)}")
        print(f"  Tracked closures:  {s.get('tracked_closures', 0)}")
        print(f"  Tracked gens:      {s.get('tracked_generations', 0)}")
        print(f"  Cache entries:     {s.get('cached_for_serving', 0)}")
        print(f"  Eval cache:        {s.get('eval_cache_entries', 0)}")
        return 0

    def mark_invalid(self, args) -> int:
        """Mark store paths that no longer exist on disk."""
        svc = self._svc()
        print("Checking store paths...")
        count = svc.mark_invalid_paths()
        print(f"  Marked {count} paths as invalid (GC'd from store)")
        return 0


def register(cli):
    """Register nix store commands with CLI."""
    cmd = NixStoreCommands()

    nix_parser = cli.register_command('nix', None, help_text='Nix store integration')
    subparsers = nix_parser.add_subparsers(dest='nix_subcommand', required=True)

    # nix scan
    scan_p = subparsers.add_parser('scan', help='Scan and index store paths from system closure')
    scan_p.add_argument('--path', help='Store path to scan (default: /run/current-system)')
    cli.commands['nix.scan'] = cmd.scan

    # nix generations
    gen_p = subparsers.add_parser('generations', help='List NixOS generations with VCS links')
    gen_p.add_argument('--machine', help='Filter by machine name')
    gen_p.add_argument('--limit', type=int, default=20, help='Max generations to show')
    cli.commands['nix.generations'] = cmd.generations

    # nix closure
    closure_p = subparsers.add_parser('closure', help='Show closure details')
    closure_p.add_argument('--path', help='Store path (default: /run/current-system)')
    closure_p.add_argument('--generation', '-g', type=int, help='Show by generation number')
    closure_p.add_argument('--machine', help='Machine name (for --generation)')
    cli.commands['nix.closure'] = cmd.closure_show

    # nix who-uses
    who_p = subparsers.add_parser('who-uses', help='Find which projects depend on a package')
    who_p.add_argument('package', help='Package name (substring match)')
    cli.commands['nix.who-uses'] = cmd.who_uses

    # nix gc-roots
    gc_p = subparsers.add_parser('gc-roots', help='Analyze what keeps store paths alive')
    cli.commands['nix.gc-roots'] = cmd.gc_analysis

    # nix stats
    stats_p = subparsers.add_parser('stats', help='Show nix store statistics')
    cli.commands['nix.stats'] = cmd.stats

    # nix mark-invalid
    inv_p = subparsers.add_parser('mark-invalid', help='Mark GC\'d store paths as invalid')
    cli.commands['nix.mark-invalid'] = cmd.mark_invalid

    # nix cache (subgroup)
    cache_p = subparsers.add_parser('cache', help='Binary cache management')
    cache_sub = cache_p.add_subparsers(dest='cache_subcommand', required=True)

    prep_p = cache_sub.add_parser('prepare', help='Prepare closure for binary cache')
    prep_p.add_argument('--path', help='Store path (default: /run/current-system)')
    cli.commands['nix.cache.prepare'] = cmd.cache_prepare

    cstats_p = cache_sub.add_parser('stats', help='Show binary cache statistics')
    cli.commands['nix.cache.stats'] = cmd.cache_stats
