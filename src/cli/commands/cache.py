#!/usr/bin/env python3
"""
Cache management commands for deployment artifacts
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import db_utils
from cli.core import Command
from services.deployment_cache import DeploymentCacheService
from repositories import ProjectRepository
from logger import get_logger

logger = get_logger(__name__)


class CacheCommands(Command):
    """Cache management command handlers"""

    def __init__(self):
        super().__init__()
        self.cache_service = DeploymentCacheService()
        self.project_repo = ProjectRepository()

    def cache_stats(self, args) -> int:
        """Show cache statistics"""
        print("📊 Deployment Cache Statistics\n")

        # Get project if specified
        project_id = None
        if hasattr(args, 'project') and args.project:
            project = self.project_repo.get_by_slug(args.project)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1
            project_id = project['id']
            print(f"Project: {args.project}\n")

        # Get stats
        stats = self.cache_service.get_cache_stats(project_id)

        if stats['total_deployments'] == 0:
            print("No deployments recorded yet")
            return 0

        print(f"Total Deployments:  {stats['total_deployments']}")
        print(f"Cache Hits:         {stats['cache_hits']} ({stats['hit_rate_percent']}%)")
        print(f"Cache Misses:       {stats['cache_misses']}")
        print()

        if stats['avg_cached_time_sec'] and stats['avg_uncached_time_sec']:
            print(f"Avg Time (cached):    {stats['avg_cached_time_sec']:.1f}s")
            print(f"Avg Time (uncached):  {stats['avg_uncached_time_sec']:.1f}s")
            print(f"Time Saved per Hit:   {stats['avg_uncached_time_sec'] - stats['avg_cached_time_sec']:.1f}s")
            print()
            print(f"✨ Total Time Saved:   {stats['estimated_time_saved_sec']:.1f}s ({stats['estimated_time_saved_sec'] / 60:.1f} min)")

        return 0

    def cache_list(self, args) -> int:
        """List cached deployments"""
        # Get project if specified
        where_clause = "1=1"
        params = []

        if hasattr(args, 'project') and args.project:
            project = self.project_repo.get_by_slug(args.project)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1
            where_clause = "project_id = ?"
            params = [project['id']]

        # Query active cache entries
        entries = db_utils.query_all(f"""
            SELECT
                p.slug AS project_slug,
                dc.target,
                dc.content_hash,
                dc.cache_created_at,
                dc.last_used_at,
                dc.use_count,
                dc.file_count,
                ROUND(dc.total_size_bytes / 1024.0 / 1024.0, 2) AS size_mb,
                ROUND((julianday('now') - julianday(dc.last_used_at)) * 24, 1) AS hours_since_use
            FROM deployment_cache dc
            JOIN projects p ON dc.project_id = p.id
            WHERE dc.is_valid = 1 AND {where_clause}
            ORDER BY dc.last_used_at DESC
        """, tuple(params))

        if not entries:
            print("No cached deployments found")
            return 0

        print(f"📦 Cached Deployments ({len(entries)}):\n")

        for entry in entries:
            print(f"  {entry['project_slug']} → {entry['target']}")
            print(f"    Hash:       {entry['content_hash'][:12]}")
            print(f"    Created:    {entry['cache_created_at']}")
            print(f"    Last used:  {entry['last_used_at']} ({entry['hours_since_use']:.1f}h ago)")
            print(f"    Use count:  {entry['use_count']}")
            print(f"    Size:       {entry['size_mb']} MB ({entry['file_count']} files)")
            print()

        return 0

    def cache_clear(self, args) -> int:
        """Clear deployment cache"""
        # Get project if specified
        project_id = None
        if hasattr(args, 'project') and args.project:
            project = self.project_repo.get_by_slug(args.project)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1
            project_id = project['id']

        # Confirm via confirm_action rather than a bare input().
        #
        # The bare call reported "Error: EOF when reading a line" and
        # exited 1 under automation. The outcome was safe -- nothing was
        # deleted -- but it read as a failure rather than a declined
        # prompt, and this path is now reached by a flag on a routine
        # command (`cleanup --all`), so it is more likely to meet a
        # closed stdin. confirm_action treats EOF and ^C as "no".
        from cli.error_handling_utils import confirm_action

        if project_id:
            project_slug = self.project_repo.get_by_id(project_id)['slug']
            prompt = f"Clear cache for project '{project_slug}'?"
        else:
            prompt = "Clear ALL deployment cache?"

        if not confirm_action(prompt, default=False):
            print("Cancelled")
            return 0

        # Clear cache
        if project_id:
            self.cache_service.invalidate_project_cache(project_id, "Manual cache clear")
            print(f"✓ Cleared cache for project")
        else:
            # Clear all
            projects = db_utils.query_all(
                "SELECT DISTINCT project_id FROM deployment_cache WHERE is_valid = 1"
            )
            for row in projects:
                self.cache_service.invalidate_project_cache(row['project_id'], "Manual cache clear (all)")
            print(f"✓ Cleared cache for all projects ({len(projects)} projects)")

        return 0

    def cache_cleanup(self, args) -> int:
        """Clean up cache entries by retention, or all of them with --all.

        `--all` absorbed the former `admin cache clear` (2026-10-27).
        Both verbs deleted cache rows and differed only in scope, but
        they differed in one way worth preserving: clearing everything
        asked for confirmation and retention cleanup did not. Folding
        them naively would either have put a prompt on the routine
        command or taken it off the destructive one, so `--all` keeps the
        prompt and the default path stays silent.
        """
        if getattr(args, 'all', False):
            return self.cache_clear(args)

        max_age_days = args.max_age if hasattr(args, 'max_age') else 30
        max_entries = args.max_entries if hasattr(args, 'max_entries') else 10

        print(f"🧹 Cleaning up deployment cache...")
        print(f"   Max age: {max_age_days} days")
        print(f"   Max entries per project: {max_entries}")
        print()

        # Get project if specified
        project_id = None
        if hasattr(args, 'project') and args.project:
            project = self.project_repo.get_by_slug(args.project)
            if not project:
                logger.error(f"Project '{args.project}' not found")
                return 1
            project_id = project['id']

        # Run cleanup
        self.cache_service.cleanup_old_cache(project_id, max_age_days, max_entries)

        print("✓ Cleanup complete")
        return 0

    # No register() here on purpose -- the seventh dead one found in this
    # sweep, after schema.py and query_open.py.
    #
    # This classmethod registered a top-level `cache` group duplicating
    # all four subcommands. Nothing called it: admin.py imports
    # CacheCommands, instantiates it, and builds the parsers itself under
    # `admin cache`, and there has never been a top-level `templedb
    # cache`. Deleted rather than wired, same reasoning as the others --
    # wiring it would add a second spelling of a working group.
    #
    # It had also drifted: it still registered `clear`, which folded into
    # `cleanup --all` on 2026-10-27, so reviving it would have brought
    # back a command that no longer exists.
