#!/usr/bin/env python3
"""
Cache management commands for deployment artifacts
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

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
        entries = self.cache_service.db_utils.query_all(f"""
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

        # Confirm
        if project_id:
            project_slug = self.project_repo.get_by_id(project_id)['slug']
            confirm = input(f"Clear cache for project '{project_slug}'? [y/N]: ")
        else:
            confirm = input("Clear ALL deployment cache? [y/N]: ")

        if confirm.lower() != 'y':
            print("Cancelled")
            return 0

        # Clear cache
        if project_id:
            self.cache_service.invalidate_project_cache(project_id, "Manual cache clear")
            print(f"✓ Cleared cache for project")
        else:
            # Clear all
            projects = self.cache_service.db_utils.query_all(
                "SELECT DISTINCT project_id FROM deployment_cache WHERE is_valid = 1"
            )
            for row in projects:
                self.cache_service.invalidate_project_cache(row['project_id'], "Manual cache clear (all)")
            print(f"✓ Cleared cache for all projects ({len(projects)} projects)")

        return 0

    def cache_cleanup(self, args) -> int:
        """Clean up old cache entries"""
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

    @classmethod
    def register(cls, subparsers):
        """Register cache commands"""
        cache_parser = subparsers.add_parser('cache', help='Manage deployment cache')
        cache_subparsers = cache_parser.add_subparsers(dest='cache_command', required=True)

        # cache stats
        stats_parser = cache_subparsers.add_parser('stats', help='Show cache statistics')
        stats_parser.add_argument('--project', help='Show stats for specific project')
        stats_parser.set_defaults(func=lambda args: cls().cache_stats(args))

        # cache list
        list_parser = cache_subparsers.add_parser('list', help='List cached deployments')
        list_parser.add_argument('--project', help='List cache for specific project')
        list_parser.set_defaults(func=lambda args: cls().cache_list(args))

        # cache clear
        clear_parser = cache_subparsers.add_parser('clear', help='Clear deployment cache')
        clear_parser.add_argument('--project', help='Clear cache for specific project')
        clear_parser.set_defaults(func=lambda args: cls().cache_clear(args))

        # cache cleanup
        cleanup_parser = cache_subparsers.add_parser('cleanup', help='Clean up old cache entries')
        cleanup_parser.add_argument('--project', help='Clean cache for specific project')
        cleanup_parser.add_argument('--max-age', type=int, default=30, help='Max age in days (default: 30)')
        cleanup_parser.add_argument('--max-entries', type=int, default=10, help='Max entries per project (default: 10)')
        cleanup_parser.set_defaults(func=lambda args: cls().cache_cleanup(args))
