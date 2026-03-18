#!/usr/bin/env python3
"""
Deployment Caching Service

Content-addressable caching for deployments to avoid rebuilding unchanged projects.
Hashes project files + dependencies and reuses cached artifacts when possible.
"""

import hashlib
import json
import time
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta

from services.base import BaseService
from logger import get_logger

logger = get_logger(__name__)


@dataclass
class ContentHash:
    """Content-addressable hash for a project"""
    files_hash: str      # Hash of all file contents
    deps_hash: str       # Hash of dependency manifests
    content_hash: str    # Combined hash (files + deps)

    def __str__(self):
        return self.content_hash[:12]  # Short hash for display


@dataclass
class CacheEntry:
    """Cached deployment artifacts"""
    cache_id: int
    project_id: int
    target: str
    content_hash: str
    cathedral_path: Optional[Path]
    fhs_env_path: Optional[Path]
    work_dir_path: Optional[Path]
    use_count: int
    last_used_at: datetime
    total_size_bytes: int
    file_count: int


class DeploymentCacheService(BaseService):
    """
    Manages deployment caching for fast repeated deployments.

    Implements content-addressable caching:
    1. Hash project files + dependencies
    2. Check if hash exists in cache
    3. Reuse cached artifacts if available
    4. Track cache hits/misses for analytics
    """

    def __init__(self, cache_dir: Optional[Path] = None):
        """
        Initialize deployment cache service.

        Args:
            cache_dir: Base directory for cache storage (default: ~/.templedb/cache)
        """
        super().__init__()

        if cache_dir is None:
            from config import DB_DIR
            cache_dir = DB_DIR / "deployment-cache"

        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        logger.debug(f"Deployment cache: {self.cache_dir}")

    def compute_content_hash(
        self,
        project_dir: Path,
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None
    ) -> ContentHash:
        """
        Compute content-addressable hash for a project.

        Args:
            project_dir: Project directory to hash
            include_patterns: Glob patterns to include (default: all files)
            exclude_patterns: Glob patterns to exclude (default: common ignores)

        Returns:
            ContentHash with files_hash, deps_hash, and combined content_hash
        """
        if exclude_patterns is None:
            exclude_patterns = [
                '.git/**',
                '__pycache__/**',
                'node_modules/**',
                '*.pyc',
                '.DS_Store',
                '.env',
                '.env.*',
                'dist/**',
                'build/**',
                'target/**',  # Rust
                '.next/**',   # Next.js
                'venv/**',
                '.venv/**',
            ]

        # Hash all file contents
        files_hash = self._hash_directory_contents(
            project_dir,
            include_patterns,
            exclude_patterns
        )

        # Hash dependency manifests (for quicker dep-only checks)
        deps_hash = self._hash_dependency_manifests(project_dir)

        # Combined hash
        combined = hashlib.sha256(
            f"{files_hash}:{deps_hash}".encode()
        ).hexdigest()

        return ContentHash(
            files_hash=files_hash,
            deps_hash=deps_hash,
            content_hash=combined
        )

    def _hash_directory_contents(
        self,
        directory: Path,
        include_patterns: Optional[List[str]],
        exclude_patterns: List[str]
    ) -> str:
        """Hash all files in directory (respecting patterns)"""
        import fnmatch

        hasher = hashlib.sha256()
        files_processed = 0

        # Get all files
        all_files = []
        for path in sorted(directory.rglob('*')):
            if not path.is_file():
                continue

            # Get relative path
            rel_path = path.relative_to(directory)
            rel_path_str = str(rel_path)

            # Check exclusions
            excluded = any(
                fnmatch.fnmatch(rel_path_str, pattern)
                for pattern in exclude_patterns
            )
            if excluded:
                continue

            # Check inclusions (if specified)
            if include_patterns:
                included = any(
                    fnmatch.fnmatch(rel_path_str, pattern)
                    for pattern in include_patterns
                )
                if not included:
                    continue

            all_files.append(path)

        # Hash files in sorted order (deterministic)
        for file_path in all_files:
            try:
                # Include filename in hash (structure matters)
                rel_path = file_path.relative_to(directory)
                hasher.update(str(rel_path).encode())

                # Include content
                with open(file_path, 'rb') as f:
                    # Read in chunks for large files
                    while chunk := f.read(8192):
                        hasher.update(chunk)

                files_processed += 1
            except Exception as e:
                logger.warning(f"Failed to hash {file_path}: {e}")
                continue

        logger.debug(f"Hashed {files_processed} files")
        return hasher.hexdigest()

    def _hash_dependency_manifests(self, project_dir: Path) -> str:
        """Hash dependency manifest files (package.json, requirements.txt, etc.)"""
        hasher = hashlib.sha256()
        manifests_found = []

        # List of manifest files to check
        manifest_files = [
            'package.json',
            'package-lock.json',
            'yarn.lock',
            'pnpm-lock.yaml',
            'requirements.txt',
            'Pipfile',
            'Pipfile.lock',
            'poetry.lock',
            'pyproject.toml',
            'Gemfile',
            'Gemfile.lock',
            'Cargo.toml',
            'Cargo.lock',
            'go.mod',
            'go.sum',
            'composer.json',
            'composer.lock',
        ]

        for manifest in sorted(manifest_files):
            manifest_path = project_dir / manifest
            if manifest_path.exists():
                try:
                    with open(manifest_path, 'rb') as f:
                        hasher.update(manifest.encode())  # Include filename
                        hasher.update(f.read())
                    manifests_found.append(manifest)
                except Exception as e:
                    logger.warning(f"Failed to hash {manifest}: {e}")

        if manifests_found:
            logger.debug(f"Hashed dependency manifests: {', '.join(manifests_found)}")
        else:
            logger.debug("No dependency manifests found")

        return hasher.hexdigest()

    def get_cache_entry(
        self,
        project_id: int,
        target: str,
        content_hash: str
    ) -> Optional[CacheEntry]:
        """
        Look up cached deployment by content hash.

        Args:
            project_id: Project ID
            target: Deployment target
            content_hash: Content hash to look up

        Returns:
            CacheEntry if found and valid, None otherwise
        """
        row = self.db_utils.query_one("""
            SELECT id, project_id, target, content_hash,
                   cathedral_path, fhs_env_path, work_dir_path,
                   use_count, last_used_at, total_size_bytes, file_count
            FROM deployment_cache
            WHERE project_id = ? AND target = ? AND content_hash = ? AND is_valid = 1
        """, (project_id, target, content_hash))

        if not row:
            return None

        # Verify paths still exist
        cathedral_path = Path(row['cathedral_path']) if row['cathedral_path'] else None
        fhs_env_path = Path(row['fhs_env_path']) if row['fhs_env_path'] else None
        work_dir_path = Path(row['work_dir_path']) if row['work_dir_path'] else None

        # Invalidate if any required path is missing
        missing_paths = []
        if cathedral_path and not cathedral_path.exists():
            missing_paths.append('cathedral')
        if fhs_env_path and not fhs_env_path.exists():
            missing_paths.append('fhs_env')
        if work_dir_path and not work_dir_path.exists():
            missing_paths.append('work_dir')

        if missing_paths:
            logger.warning(f"Cache entry invalid: missing {', '.join(missing_paths)}")
            self._invalidate_cache_entry(row['id'], f"Missing artifacts: {', '.join(missing_paths)}")
            return None

        return CacheEntry(
            cache_id=row['id'],
            project_id=row['project_id'],
            target=row['target'],
            content_hash=row['content_hash'],
            cathedral_path=cathedral_path,
            fhs_env_path=fhs_env_path,
            work_dir_path=work_dir_path,
            use_count=row['use_count'],
            last_used_at=datetime.fromisoformat(row['last_used_at']),
            total_size_bytes=row['total_size_bytes'],
            file_count=row['file_count']
        )

    def create_cache_entry(
        self,
        project_id: int,
        target: str,
        content_hash: ContentHash,
        cathedral_path: Optional[Path] = None,
        fhs_env_path: Optional[Path] = None,
        work_dir_path: Optional[Path] = None,
        file_count: int = 0,
        total_size_bytes: int = 0
    ) -> int:
        """
        Create a new cache entry.

        Args:
            project_id: Project ID
            target: Deployment target
            content_hash: Content hash for this deployment
            cathedral_path: Path to cached cathedral export
            fhs_env_path: Path to cached FHS environment
            work_dir_path: Path to cached working directory
            file_count: Number of files in cache
            total_size_bytes: Total size of cached artifacts

        Returns:
            Cache entry ID
        """
        cache_id = self.db_utils.execute("""
            INSERT INTO deployment_cache (
                project_id, target,
                content_hash, files_hash, deps_hash,
                cathedral_path, fhs_env_path, work_dir_path,
                file_count, total_size_bytes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id, target,
            content_hash.content_hash,
            content_hash.files_hash,
            content_hash.deps_hash,
            str(cathedral_path) if cathedral_path else None,
            str(fhs_env_path) if fhs_env_path else None,
            str(work_dir_path) if work_dir_path else None,
            file_count,
            total_size_bytes
        ))

        logger.info(f"Created cache entry {cache_id} (hash: {content_hash})")
        return cache_id

    def record_cache_hit(
        self,
        cache_entry: CacheEntry,
        total_time_seconds: float,
        skipped_cathedral: bool = True,
        skipped_fhs: bool = True,
        skipped_reconstruction: bool = True
    ):
        """Record successful cache hit and update stats"""
        # Update use count
        self.db_utils.execute("""
            UPDATE deployment_cache
            SET use_count = use_count + 1
            WHERE id = ?
        """, (cache_entry.cache_id,))

        # Record stats
        self.db_utils.execute("""
            INSERT INTO deployment_cache_stats (
                project_id, target, cache_hit, content_hash,
                build_time_seconds, total_time_seconds,
                skipped_cathedral_export, skipped_fhs_generation,
                skipped_file_reconstruction
            ) VALUES (?, ?, 1, ?, 0, ?, ?, ?, ?)
        """, (
            cache_entry.project_id,
            cache_entry.target,
            cache_entry.content_hash,
            total_time_seconds,
            skipped_cathedral,
            skipped_fhs,
            skipped_reconstruction
        ))

        logger.info(f"✓ Cache hit recorded (saved ~{total_time_seconds:.1f}s)")

    def record_cache_miss(
        self,
        project_id: int,
        target: str,
        content_hash: str,
        build_time_seconds: float,
        export_time_seconds: float,
        total_time_seconds: float
    ):
        """Record cache miss (full rebuild)"""
        self.db_utils.execute("""
            INSERT INTO deployment_cache_stats (
                project_id, target, cache_hit, content_hash,
                build_time_seconds, export_time_seconds, total_time_seconds,
                skipped_cathedral_export, skipped_fhs_generation,
                skipped_file_reconstruction
            ) VALUES (?, ?, 0, ?, ?, ?, ?, 0, 0, 0)
        """, (
            project_id,
            target,
            content_hash,
            build_time_seconds,
            export_time_seconds,
            total_time_seconds
        ))

    def _invalidate_cache_entry(self, cache_id: int, reason: str):
        """Mark cache entry as invalid"""
        self.db_utils.execute("""
            UPDATE deployment_cache
            SET is_valid = 0, invalidated_at = datetime('now'), invalidation_reason = ?
            WHERE id = ?
        """, (reason, cache_id))

    def invalidate_project_cache(self, project_id: int, reason: str = "Manual invalidation"):
        """Invalidate all cache entries for a project"""
        count = self.db_utils.execute("""
            UPDATE deployment_cache
            SET is_valid = 0, invalidated_at = datetime('now'), invalidation_reason = ?
            WHERE project_id = ? AND is_valid = 1
        """, (reason, project_id))

        if count > 0:
            logger.info(f"Invalidated {count} cache entries for project {project_id}")

    def cleanup_old_cache(
        self,
        project_id: Optional[int] = None,
        max_age_days: int = 30,
        max_entries_per_project: int = 10
    ):
        """
        Clean up old cache entries.

        Args:
            project_id: Specific project to clean (None = all projects)
            max_age_days: Delete entries older than this
            max_entries_per_project: Keep only N most recent per project
        """
        # Delete expired entries
        cutoff = datetime.now() - timedelta(days=max_age_days)
        where_clause = "last_used_at < ?"
        params = [cutoff.isoformat()]

        if project_id:
            where_clause += " AND project_id = ?"
            params.append(project_id)

        deleted = self.db_utils.execute(f"""
            DELETE FROM deployment_cache
            WHERE {where_clause}
        """, tuple(params))

        if deleted > 0:
            logger.info(f"Deleted {deleted} expired cache entries (older than {max_age_days} days)")

        # Keep only N most recent per project/target
        # (SQLite doesn't support DELETE with window functions, so we do it manually)
        if project_id:
            self._cleanup_excess_entries(project_id, max_entries_per_project)
        else:
            # Get all projects
            projects = self.db_utils.query_all("SELECT DISTINCT project_id FROM deployment_cache")
            for row in projects:
                self._cleanup_excess_entries(row['project_id'], max_entries_per_project)

    def _cleanup_excess_entries(self, project_id: int, max_entries: int):
        """Keep only N most recent cache entries for a project"""
        # Get cache IDs to delete (older than Nth most recent)
        rows = self.db_utils.query_all("""
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (PARTITION BY target ORDER BY last_used_at DESC) AS rn
                FROM deployment_cache
                WHERE project_id = ? AND is_valid = 1
            )
            WHERE rn > ?
        """, (project_id, max_entries))

        if rows:
            ids_to_delete = [row['id'] for row in rows]
            placeholders = ','.join('?' * len(ids_to_delete))
            deleted = self.db_utils.execute(f"""
                DELETE FROM deployment_cache WHERE id IN ({placeholders})
            """, tuple(ids_to_delete))

            if deleted > 0:
                logger.info(f"Deleted {deleted} excess cache entries for project {project_id}")

    def get_cache_stats(self, project_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get cache efficiency statistics.

        Args:
            project_id: Specific project (None = all projects)

        Returns:
            Dict with cache stats (hit rate, time saved, etc.)
        """
        where_clause = "1=1"
        params = []

        if project_id:
            where_clause = "project_id = ?"
            params = [project_id]

        stats = self.db_utils.query_one(f"""
            SELECT
                COUNT(*) as total_deployments,
                SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END) as cache_hits,
                SUM(CASE WHEN cache_hit = 0 THEN 1 ELSE 0 END) as cache_misses,
                ROUND(100.0 * SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as hit_rate_percent,
                ROUND(AVG(CASE WHEN cache_hit = 1 THEN total_time_seconds END), 2) as avg_cached_time_sec,
                ROUND(AVG(CASE WHEN cache_hit = 0 THEN total_time_seconds END), 2) as avg_uncached_time_sec
            FROM deployment_cache_stats
            WHERE {where_clause}
        """, tuple(params))

        if not stats or stats['total_deployments'] == 0:
            return {
                'total_deployments': 0,
                'cache_hits': 0,
                'cache_misses': 0,
                'hit_rate_percent': 0.0,
                'avg_cached_time_sec': 0.0,
                'avg_uncached_time_sec': 0.0,
                'estimated_time_saved_sec': 0.0
            }

        # Calculate time saved
        if stats['avg_uncached_time_sec'] and stats['avg_cached_time_sec']:
            time_saved_per_hit = stats['avg_uncached_time_sec'] - stats['avg_cached_time_sec']
            total_time_saved = time_saved_per_hit * stats['cache_hits']
        else:
            total_time_saved = 0.0

        return {
            'total_deployments': stats['total_deployments'],
            'cache_hits': stats['cache_hits'],
            'cache_misses': stats['cache_misses'],
            'hit_rate_percent': stats['hit_rate_percent'],
            'avg_cached_time_sec': stats['avg_cached_time_sec'],
            'avg_uncached_time_sec': stats['avg_uncached_time_sec'],
            'estimated_time_saved_sec': round(total_time_saved, 2)
        }
