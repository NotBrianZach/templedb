#!/usr/bin/env python3
"""
Cathedral Export Engine - Export TempleDB projects to .cathedral packages
"""

import os
import sqlite3
import getpass
import logging
import fnmatch
from pathlib import Path
from typing import Optional, List, Dict, Any

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    # Fallback iterator
    def tqdm(iterable, **kwargs):
        return iterable

from cathedral_format import (
    CathedralPackage,
    CathedralManifest,
    ProjectMetadata,
    FileMetadata,
    create_manifest,
    CATHEDRAL_FORMAT_VERSION
)
from cathedral_compression import auto_compress, ZSTD_AVAILABLE

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger('cathedral.export')


def default_db_path() -> Path:
    """Get default database path"""
    return Path.home() / ".local" / "share" / "templedb" / "templedb.sqlite"


def dict_from_row(row: sqlite3.Row) -> Dict:
    """Convert sqlite3.Row to dict"""
    return {key: row[key] for key in row.keys()}


class CathedralExporter:
    """Export TempleDB projects to .cathedral packages"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or default_db_path()
        self.conn = None

    def __enter__(self):
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.conn.close()

    def get_project(self, slug: str) -> Optional[Dict]:
        """Get project by slug"""
        cursor = self.conn.cursor()
        row = cursor.execute(
            "SELECT * FROM projects WHERE slug = ?",
            (slug,)
        ).fetchone()
        return dict_from_row(row) if row else None

    def get_all_file_data_batched(self, project_id: int) -> List[Dict]:
        """
        OPTIMIZED: Get all file data in a single query with JOINs

        This replaces individual queries per file with a single batched query.
        Performance: 1212 queries -> 1 query (404x improvement for 404 files)
        """
        cursor = self.conn.cursor()

        rows = cursor.execute("""
            SELECT
                -- File metadata
                pf.id as file_id,
                pf.file_path,
                pf.file_name,
                pf.lines_of_code,
                pf.created_at as file_created_at,

                -- File type
                ft.type_name as file_type_name,

                -- Current content
                cb.content_text,
                cb.content_blob,
                cb.content_type,
                COALESCE(cb.file_size_bytes, 0) as file_size_bytes,
                COALESCE(fc.content_hash, '') as hash_sha256,

                -- Latest version metadata
                COALESCE(fv_latest.version_number, 1) as version_number,
                fv_latest.author,
                fv_latest.created_at as version_created_at

            FROM project_files pf

            -- Join file type
            LEFT JOIN file_types ft
                ON pf.file_type_id = ft.id

            -- Join current content
            LEFT JOIN file_contents fc
                ON pf.id = fc.file_id
                AND fc.is_current = 1

            -- Join content blobs (actual content storage)
            LEFT JOIN content_blobs cb
                ON fc.content_hash = cb.hash_sha256

            -- Join latest version from VCS system (subquery to get latest commit per file)
            LEFT JOIN (
                SELECT
                    vfs.file_id,
                    ROW_NUMBER() OVER (PARTITION BY vfs.file_id ORDER BY vc.commit_timestamp DESC) as version_number,
                    vc.author,
                    vc.commit_timestamp as created_at,
                    ROW_NUMBER() OVER (PARTITION BY vfs.file_id ORDER BY vc.commit_timestamp DESC) as rn
                FROM vcs_file_states vfs
                JOIN vcs_commits vc ON vfs.commit_id = vc.id
            ) fv_latest
                ON pf.id = fv_latest.file_id
                AND fv_latest.rn = 1

            WHERE pf.project_id = ?
            ORDER BY pf.file_path
        """, (project_id,)).fetchall()

        return [dict_from_row(row) for row in rows]

    def get_vcs_branches(self, project_id: int) -> List[Dict]:
        """Get VCS branches"""
        cursor = self.conn.cursor()
        rows = cursor.execute("""
            SELECT id, branch_name, parent_branch_id, is_default, created_at
            FROM vcs_branches
            WHERE project_id = ?
            ORDER BY id
        """, (project_id,)).fetchall()
        return [dict_from_row(row) for row in rows]

    def get_vcs_commits(self, project_id: int) -> List[Dict]:
        """Get VCS commits"""
        cursor = self.conn.cursor()
        rows = cursor.execute("""
            SELECT id, branch_id, parent_commit_id, commit_hash, author,
                   commit_message, commit_timestamp
            FROM vcs_commits
            WHERE project_id = ?
            ORDER BY commit_timestamp
        """, (project_id,)).fetchall()
        return [dict_from_row(row) for row in rows]

    def get_vcs_history(self, project_id: int) -> List[Dict]:
        """Get VCS file history"""
        cursor = self.conn.cursor()
        # Check if table exists
        table_check = cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='vcs_file_history'
        """).fetchone()

        if not table_check:
            return []

        rows = cursor.execute("""
            SELECT commit_id, file_id, change_type, old_file_path, new_file_path
            FROM vcs_file_history
            WHERE commit_id IN (
                SELECT id FROM vcs_commits WHERE project_id = ?
            )
            ORDER BY commit_id
        """, (project_id,)).fetchall()
        return [dict_from_row(row) for row in rows]

    def get_environments(self, project_id: int) -> List[Dict]:
        """Get Nix environments"""
        cursor = self.conn.cursor()
        rows = cursor.execute("""
            SELECT env_name, description, base_packages, profile, created_at
            FROM nix_environments
            WHERE project_id = ?
        """, (project_id,)).fetchall()
        return [dict_from_row(row) for row in rows]

    def get_project_statistics(self, project_id: int) -> Dict[str, Any]:
        """Calculate project statistics"""
        cursor = self.conn.cursor()

        # Total files and lines
        row = cursor.execute("""
            SELECT
                COUNT(*) as total_files,
                SUM(pf.lines_of_code) as total_lines,
                SUM(COALESCE(fc.file_size_bytes, 0)) as total_bytes
            FROM project_files pf
            LEFT JOIN file_contents fc ON pf.id = fc.file_id AND fc.is_current = 1
            WHERE pf.project_id = ?
        """, (project_id,)).fetchone()

        stats = dict_from_row(row)

        # File types distribution
        type_rows = cursor.execute("""
            SELECT ft.type_name, COUNT(*) as count
            FROM project_files pf
            LEFT JOIN file_types ft ON pf.file_type_id = ft.id
            WHERE pf.project_id = ?
            GROUP BY ft.type_name
        """, (project_id,)).fetchall()

        stats['file_types'] = {row['type_name']: row['count'] for row in type_rows if row['type_name']}

        return stats

    def export_project(
        self,
        slug: str,
        output_path: Path,
        include_files: bool = True,
        include_vcs: bool = True,
        include_environments: bool = True,
        include_secrets: bool = False,
        compress: bool = False,
        compression_level: Optional[int] = None,
        exclude_patterns: Optional[List[str]] = None
    ) -> bool:
        """
        Export a project to a .cathedral package

        Args:
            slug: Project slug
            output_path: Output directory for the package
            include_files: Include file contents
            include_vcs: Include VCS data
            include_environments: Include Nix environments
            include_secrets: Include encrypted secrets (not implemented yet)
            compress: Compress the package after export
            compression_level: Compression level (gzip: 1-9 default 6, zstd: 1-22 default 3)
            exclude_patterns: List of glob patterns to exclude (e.g., ["*.log", "node_modules/*"])

        Returns:
            True if export succeeded
        """
        logger.info(f"🏗️  Exporting project: {slug}")

        # Get project
        project_data = self.get_project(slug)
        if not project_data:
            logger.error(f"❌ Project not found: {slug}")
            return False

        project_id = project_data['id']

        # Create package
        package_path = output_path / f"{slug}.cathedral"
        package = CathedralPackage(package_path)
        package.create_structure()

        logger.info(f"📦 Created package structure: {package_path}")

        # Get project statistics
        stats = self.get_project_statistics(project_id)

        # Export project metadata
        project_meta = ProjectMetadata(
            slug=project_data['slug'],
            name=project_data['name'] or slug,
            description=None,  # TODO: Add description field
            repository_url=project_data.get('repo_url'),
            default_branch=project_data.get('git_branch'),
            git_ref=project_data.get('git_ref'),
            created_at=project_data['created_at'],
            updated_at=project_data['updated_at'],
            metadata={},  # TODO: Add custom metadata
            statistics=stats
        )
        package.write_project(project_meta)
        logger.info(f"✓ Wrote project metadata")

        # Export files
        files_exported = 0
        if include_files:
            logger.info(f"📁 Exporting files...")

            # OPTIMIZED: Get all file data in one query
            files_data = self.get_all_file_data_batched(project_id)
            file_metadata_list = []

            # Initialize exclude patterns
            exclude_patterns = exclude_patterns or []
            files_excluded = 0

            # Use tqdm for progress bar if available
            iterator = tqdm(files_data, desc="Exporting files", unit="file") if TQDM_AVAILABLE else files_data

            for file_data in iterator:
                file_id = file_data['file_id']
                file_path = file_data['file_path']

                # Check if file matches any exclude pattern
                should_exclude = False
                for pattern in exclude_patterns:
                    if fnmatch.fnmatch(file_path, pattern) or fnmatch.fnmatch(str(Path(file_path).name), pattern):
                        should_exclude = True
                        files_excluded += 1
                        break

                if should_exclude:
                    continue

                # Create file metadata (data already includes version info)
                file_meta = FileMetadata(
                    file_id=file_id,
                    file_path=file_data['file_path'],
                    file_type=file_data.get('file_type_name'),
                    lines_of_code=file_data['lines_of_code'] or 0,
                    file_size_bytes=file_data['file_size_bytes'] or 0,
                    hash_sha256=file_data['hash_sha256'] or '',
                    version_number=file_data.get('version_number', 1),
                    author=file_data.get('author'),
                    created_at=file_data['file_created_at'],
                    metadata={}
                )
                file_metadata_list.append(file_meta)

                # Write file metadata
                package.write_file_metadata(file_id, file_meta)

                # Get and write file content (already fetched in batch query)
                content = b''
                if file_data['content_blob']:
                    content = file_data['content_blob']
                elif file_data['content_text']:
                    content = file_data['content_text'].encode('utf-8')

                # Always write content, even if empty (prevents import errors)
                package.write_file_content(file_id, content)

                files_exported += 1

            # Write files manifest
            package.write_files_manifest(file_metadata_list)
            if files_excluded > 0:
                logger.info(f"✓ Exported {files_exported} files ({files_excluded} excluded)")
            else:
                logger.info(f"✓ Exported {files_exported} files")

        # Export VCS data
        if include_vcs:
            logger.info(f"🌿 Exporting VCS data...")
            branches = self.get_vcs_branches(project_id)
            commits = self.get_vcs_commits(project_id)
            history = self.get_vcs_history(project_id)
            package.write_vcs_data(branches, commits, history)
            logger.info(f"✓ Exported {len(branches)} branches, {len(commits)} commits")

        # Export environments
        if include_environments:
            environments = self.get_environments(project_id)
            if environments:
                logger.info(f"🔧 Exporting environments...")
                for env in tqdm(environments, desc="Exporting environments", unit="env") if TQDM_AVAILABLE else environments:
                    env_file = package.environments_dir / f"{env['env_name']}.json"
                    import json
                    with open(env_file, 'w') as f:
                        json.dump(env, f, indent=2)
                logger.info(f"✓ Exported {len(environments)} environments")

        # Create manifest
        creator = getpass.getuser()

        logger.info(f"🔍 Calculating package size and checksum...")
        total_size = sum((f.stat().st_size for f in package.package_path.rglob('*') if f.is_file()))

        manifest = create_manifest(
            project_slug=slug,
            project_name=project_data['name'] or slug,
            creator=creator,
            total_files=files_exported,
            total_commits=len(commits) if include_vcs else 0,
            total_branches=len(branches) if include_vcs else 0,
            total_size_bytes=total_size,
            has_secrets=include_secrets,
            has_environments=include_environments and len(environments) > 0
        )

        # Calculate checksum and update manifest
        checksum = package.calculate_package_checksum()
        manifest.checksums['sha256'] = checksum

        package.write_manifest(manifest)
        logger.info(f"✓ Wrote manifest with checksum: {checksum[:16]}...")

        logger.info(f"\n✅ Export complete: {package_path}")
        logger.info(f"📊 Package size: {total_size / 1024 / 1024:.2f} MB")

        # Compress if requested
        if compress:
            logger.info(f"\n🗜️  Compressing package...")
            try:
                compressed_path = auto_compress(
                    package_path,
                    prefer_zstd=ZSTD_AVAILABLE,
                    level=compression_level
                )
                logger.info(f"✅ Compressed package: {compressed_path}")

                # Remove uncompressed directory
                import shutil
                shutil.rmtree(package_path)
                logger.info(f"🗑️  Removed uncompressed directory")

            except Exception as e:
                logger.error(f"❌ Compression failed: {e}")
                logger.info(f"Keeping uncompressed package: {package_path}")

        return True


def export_project(
    slug: str,
    output_dir: Optional[Path] = None,
    compress: bool = False,
    compression_level: Optional[int] = None,
    exclude_patterns: Optional[List[str]] = None,
    **kwargs
) -> bool:
    """
    Export a project to .cathedral package

    Args:
        slug: Project slug
        output_dir: Output directory (default: current directory)
        compress: Compress the package (default: False)
        compression_level: Compression level (gzip: 1-9, zstd: 1-22)
        exclude_patterns: List of glob patterns to exclude (e.g., ["*.log", "node_modules/*"])
        **kwargs: Additional options (include_files, include_vcs, etc)

    Returns:
        True if export succeeded
    """
    output_dir = output_dir or Path.cwd()

    with CathedralExporter() as exporter:
        return exporter.export_project(
            slug, output_dir,
            compress=compress,
            compression_level=compression_level,
            exclude_patterns=exclude_patterns,
            **kwargs
        )


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 cathedral_export.py <project-slug>")
        sys.exit(1)

    slug = sys.argv[1]
    success = export_project(slug)
    sys.exit(0 if success else 1)
