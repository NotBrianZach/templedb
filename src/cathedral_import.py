#!/usr/bin/env python3
"""
Cathedral Import Engine - Import .cathedral packages into TempleDB
"""

import sqlite3
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    def tqdm(iterable, **kwargs):
        return iterable

from cathedral_format import (
    CathedralPackage,
    CathedralManifest,
    ProjectMetadata,
    FileMetadata
)
from cathedral_compression import auto_decompress, detect_compression

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger('cathedral.import')


def default_db_path() -> Path:
    """Get default database path"""
    return Path.home() / ".local" / "share" / "templedb" / "templedb.sqlite"


def dict_from_row(row: sqlite3.Row) -> Dict:
    """Convert sqlite3.Row to dict"""
    return {key: row[key] for key in row.keys()}


class CathedralImporter:
    """Import .cathedral packages into TempleDB"""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or default_db_path()
        self.conn = None

    def __enter__(self):
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            if exc_type is None:
                self.conn.commit()
            else:
                self.conn.rollback()
            self.conn.close()

    def project_exists(self, slug: str) -> bool:
        """Check if project already exists"""
        cursor = self.conn.cursor()
        row = cursor.execute(
            "SELECT id FROM projects WHERE slug = ?",
            (slug,)
        ).fetchone()
        return row is not None

    def create_or_update_project(self, project_meta: ProjectMetadata) -> int:
        """Create or update project, return project_id"""
        cursor = self.conn.cursor()

        # Check if project exists
        existing = cursor.execute(
            "SELECT id FROM projects WHERE slug = ?",
            (project_meta.slug,)
        ).fetchone()

        if existing:
            logger.info(f"   ℹ️  Project '{project_meta.slug}' already exists, updating...")
            project_id = existing['id']

            # Update project
            cursor.execute("""
                UPDATE projects
                SET name = ?, repo_url = ?, git_branch = ?, git_ref = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (
                project_meta.name,
                project_meta.repository_url,
                project_meta.default_branch,
                project_meta.git_ref,
                project_id
            ))
        else:
            logger.info(f"   ✓ Creating new project: {project_meta.slug}")
            cursor.execute("""
                INSERT INTO projects (slug, name, repo_url, git_branch, git_ref)
                VALUES (?, ?, ?, ?, ?)
            """, (
                project_meta.slug,
                project_meta.name,
                project_meta.repository_url,
                project_meta.default_branch,
                project_meta.git_ref
            ))
            project_id = cursor.lastrowid

        return project_id

    def get_or_create_file_type(self, type_name: Optional[str]) -> Optional[int]:
        """Get or create file type, return type_id"""
        if not type_name:
            return None

        cursor = self.conn.cursor()

        # Check if type exists
        row = cursor.execute(
            "SELECT id FROM file_types WHERE type_name = ?",
            (type_name,)
        ).fetchone()

        if row:
            return row['id']

        # Create new type
        cursor.execute("""
            INSERT INTO file_types (type_name, category, description)
            VALUES (?, ?, ?)
        """, (type_name, 'imported', f'Imported from cathedral package'))
        return cursor.lastrowid

    def import_file(self, project_id: int, file_meta: FileMetadata, content: bytes) -> int:
        """Import a single file, return file_id"""
        cursor = self.conn.cursor()

        # Get or create file type
        file_type_id = self.get_or_create_file_type(file_meta.file_type)

        # Check if file already exists
        existing = cursor.execute("""
            SELECT id FROM project_files
            WHERE project_id = ? AND file_path = ?
        """, (project_id, file_meta.file_path)).fetchone()

        if existing:
            file_id = existing['id']
            # Update file metadata
            cursor.execute("""
                UPDATE project_files
                SET file_type_id = ?, lines_of_code = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (file_type_id, file_meta.lines_of_code, file_id))
        else:
            # Extract file name from path
            file_name = Path(file_meta.file_path).name

            # Insert new file
            cursor.execute("""
                INSERT INTO project_files (
                    project_id, file_type_id, file_path, file_name, lines_of_code
                )
                VALUES (?, ?, ?, ?, ?)
            """, (
                project_id,
                file_type_id,
                file_meta.file_path,
                file_name,
                file_meta.lines_of_code
            ))
            file_id = cursor.lastrowid

        # Store file content
        # Determine content type
        try:
            content_text = content.decode('utf-8')
            content_type = 'text'
            content_blob = None
        except UnicodeDecodeError:
            content_text = None
            content_type = 'binary'
            content_blob = content

        # Check if content already exists
        existing_content = cursor.execute("""
            SELECT id FROM file_contents
            WHERE file_id = ? AND is_current = 1
        """, (file_id,)).fetchone()

        if existing_content:
            # Update existing content
            cursor.execute("""
                UPDATE file_contents
                SET content_text = ?, content_blob = ?, content_type = ?,
                    file_size_bytes = ?, hash_sha256 = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (
                content_text,
                content_blob,
                content_type,
                file_meta.file_size_bytes,
                file_meta.hash_sha256,
                existing_content['id']
            ))
        else:
            # Insert new content
            cursor.execute("""
                INSERT INTO file_contents (
                    file_id, content_text, content_blob, content_type,
                    file_size_bytes, line_count, hash_sha256, is_current
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            """, (
                file_id,
                content_text,
                content_blob,
                content_type,
                file_meta.file_size_bytes,
                file_meta.lines_of_code,
                file_meta.hash_sha256
            ))

        # Note: Version history is now managed by VCS system (vcs_commits + vcs_file_states)
        # Cathedral imports will create versions through VCS if VCS data is included in package
        # For packages without VCS data, file_contents provides the current version

        return file_id

    def import_vcs_data(self, project_id: int, branches: List[Dict], commits: List[Dict],
                       commit_files: List[Dict] = None, tags: List[Dict] = None):
        """Import VCS branches, commits, commit files, and tags"""
        cursor = self.conn.cursor()

        # Map old IDs to new IDs
        branch_id_map = {}
        commit_id_map = {}

        # Import branches
        for branch in branches:
            # Check if branch already exists
            existing = cursor.execute("""
                SELECT id FROM vcs_branches
                WHERE project_id = ? AND branch_name = ?
            """, (project_id, branch['branch_name'])).fetchone()

            if existing:
                new_branch_id = existing['id']
            else:
                cursor.execute("""
                    INSERT INTO vcs_branches (
                        project_id, branch_name, is_default, created_at
                    )
                    VALUES (?, ?, ?, ?)
                """, (
                    project_id,
                    branch['branch_name'],
                    branch['is_default'],
                    branch['created_at']
                ))
                new_branch_id = cursor.lastrowid

            branch_id_map[branch['id']] = new_branch_id

        # Import commits
        for commit in commits:
            # Check if commit already exists (by hash globally, not just project)
            existing = cursor.execute("""
                SELECT id FROM vcs_commits
                WHERE commit_hash = ?
            """, (commit['commit_hash'],)).fetchone()

            if existing:
                new_commit_id = existing['id']
            else:
                new_branch_id = branch_id_map.get(commit['branch_id'])
                if not new_branch_id:
                    continue  # Skip if branch not found

                cursor.execute("""
                    INSERT INTO vcs_commits (
                        project_id, branch_id, commit_hash, author, author_email,
                        commit_message, commit_timestamp
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    project_id,
                    new_branch_id,
                    commit['commit_hash'],
                    commit['author'],
                    commit.get('author_email'),  # May be None for old packages
                    commit['commit_message'],
                    commit['commit_timestamp']
                ))
                new_commit_id = cursor.lastrowid

            commit_id_map[commit['id']] = new_commit_id

        # Import commit_files (new git integration data)
        if commit_files:
            file_id_map = self._get_file_id_map(project_id)

            for cf in commit_files:
                new_commit_id = commit_id_map.get(cf['commit_id'])
                # Map old file_id to new file_id using file_path
                old_file_id = cf['file_id']
                new_file_id = file_id_map.get(old_file_id)

                if new_commit_id and new_file_id:
                    # Check if already exists
                    existing = cursor.execute("""
                        SELECT id FROM commit_files
                        WHERE commit_id = ? AND file_id = ?
                    """, (new_commit_id, new_file_id)).fetchone()

                    if not existing:
                        cursor.execute("""
                            INSERT INTO commit_files (
                                commit_id, file_id, change_type,
                                old_content_hash, new_content_hash,
                                old_path, new_path
                            )
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            new_commit_id,
                            new_file_id,
                            cf['change_type'],
                            cf.get('old_content_hash'),
                            cf.get('new_content_hash'),
                            cf.get('old_path'),
                            cf.get('new_path')
                        ))

        # Import tags (new git integration data)
        if tags:
            for tag in tags:
                new_commit_id = commit_id_map.get(tag['commit_id'])

                if new_commit_id:
                    # Check if tag already exists
                    existing = cursor.execute("""
                        SELECT id FROM vcs_tags
                        WHERE project_id = ? AND tag_name = ?
                    """, (project_id, tag['tag_name'])).fetchone()

                    if not existing:
                        cursor.execute("""
                            INSERT INTO vcs_tags (
                                project_id, tag_name, commit_id
                            )
                            VALUES (?, ?, ?)
                        """, (
                            project_id,
                            tag['tag_name'],
                            new_commit_id
                        ))

    def _get_file_id_map(self, project_id: int) -> Dict[int, int]:
        """Get mapping of old file IDs to new file IDs based on file paths"""
        cursor = self.conn.cursor()
        rows = cursor.execute("""
            SELECT id, file_path
            FROM project_files
            WHERE project_id = ?
        """, (project_id,)).fetchall()

        # For now, just return identity mapping - in real use,
        # we'd need to track old_id -> file_path -> new_id
        # This is a simplified version
        return {row['id']: row['id'] for row in rows}

    def import_project(
        self,
        package_path: Path,
        overwrite: bool = False,
        new_slug: Optional[str] = None
    ) -> bool:
        """
        Import a .cathedral package into TempleDB

        Args:
            package_path: Path to .cathedral package directory
            overwrite: If True, overwrite existing project
            new_slug: If provided, import with a different slug

        Returns:
            True if import succeeded
        """
        package_path = Path(package_path)

        if not package_path.exists():
            logger.error(f"❌ Package not found: {package_path}")
            return False

        logger.info(f"📥 Importing package: {package_path}")

        # Auto-decompress if needed
        compression = detect_compression(package_path)
        if compression != 'none':
            logger.info(f"🗜️  Detected {compression} compression, decompressing...")
            try:
                package_path = auto_decompress(package_path)
            except Exception as e:
                logger.error(f"❌ Decompression failed: {e}")
                return False

        if not package_path.is_dir():
            logger.error(f"❌ Package must be a directory after decompression: {package_path}")
            return False

        # Load package
        package = CathedralPackage(package_path)

        # Verify integrity
        logger.info(f"🔍 Verifying package integrity...")
        if not package.verify_integrity():
            logger.error(f"❌ Package integrity verification failed!")
            return False
        logger.info(f"✓ Package integrity verified")

        # Read manifest and project metadata
        manifest = package.read_manifest()
        project_meta = package.read_project()

        # Override slug if requested
        if new_slug:
            project_meta.slug = new_slug

        # Check if project exists
        if self.project_exists(project_meta.slug) and not overwrite:
            logger.error(f"❌ Project '{project_meta.slug}' already exists. Use --overwrite to replace.")
            return False

        # Import project
        project_id = self.create_or_update_project(project_meta)
        logger.info(f"✓ Project created/updated: {project_meta.slug} (ID: {project_id})")

        # Import files
        logger.info(f"📁 Importing files...")
        files_imported = 0

        # Read files manifest
        import json
        files_manifest_path = package.files_dir / "manifest.json"
        if files_manifest_path.exists():
            with open(files_manifest_path, 'r') as f:
                files_manifest = json.load(f)

            # Use tqdm for progress bar if available
            file_list = files_manifest['files']
            iterator = tqdm(file_list, desc="Importing files", unit="file") if TQDM_AVAILABLE else file_list

            for file_info in iterator:
                file_id = file_info['file_id']

                # Read file metadata and content
                try:
                    file_meta = package.read_file_metadata(file_id)
                    content = package.read_file_content(file_id)

                    # Import file
                    self.import_file(project_id, file_meta, content)
                    files_imported += 1
                except Exception as e:
                    logger.warning(f"⚠️  Failed to import file {file_id}: {e}")

        logger.info(f"✓ Imported {files_imported} files")

        # Import VCS data
        vcs_branches_path = package.vcs_dir / "branches.json"
        if vcs_branches_path.exists():
            logger.info(f"🌿 Importing VCS data...")
            branches, commits, history, commit_files, tags = package.read_vcs_data()
            self.import_vcs_data(project_id, branches, commits, commit_files, tags)

            tags_msg = f", {len(tags)} tags" if tags else ""
            commit_files_msg = f", {len(commit_files)} file changes" if commit_files else ""
            logger.info(f"✓ Imported {len(branches)} branches, {len(commits)} commits{tags_msg}{commit_files_msg}")

        logger.info(f"\n✅ Import complete!")
        logger.info(f"📊 Imported: {files_imported} files from package")

        return True


def import_project(
    package_path: Path,
    overwrite: bool = False,
    new_slug: Optional[str] = None
) -> bool:
    """
    Import a .cathedral package into TempleDB

    Args:
        package_path: Path to .cathedral package directory
        overwrite: If True, overwrite existing project
        new_slug: If provided, import with a different slug

    Returns:
        True if import succeeded
    """
    with CathedralImporter() as importer:
        return importer.import_project(package_path, overwrite, new_slug)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python3 cathedral_import.py <package-path> [--overwrite] [--as <new-slug>]")
        sys.exit(1)

    package_path = Path(sys.argv[1])
    overwrite = "--overwrite" in sys.argv
    new_slug = None

    if "--as" in sys.argv:
        idx = sys.argv.index("--as")
        if idx + 1 < len(sys.argv):
            new_slug = sys.argv[idx + 1]

    success = import_project(package_path, overwrite=overwrite, new_slug=new_slug)
    sys.exit(0 if success else 1)
