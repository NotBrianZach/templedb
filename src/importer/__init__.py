#!/usr/bin/env python3
"""
Project importer - Unified Python importer for TempleDB

Replaces all Node.js populate_*.cjs scripts with a single,
modular Python implementation.
"""
import sys
from pathlib import Path
from typing import Optional, Dict, List
from dataclasses import dataclass

sys.path.insert(0, str(Path(__file__).parent.parent))
from db_utils import query_one, query_all, execute, executemany, get_connection, transaction

from importer.scanner import FileScanner, ScannedFile
from importer.git_analyzer import GitAnalyzer
from importer.content import ContentStore, FileContent
from importer.sql_analyzer import SqlAnalyzer, SqlObject
from importer.dependency_analyzer import DependencyAnalyzer, Dependency


@dataclass
class ImportStats:
    """Statistics from import operation"""
    total_files_scanned: int = 0
    files_imported: int = 0
    files_skipped: int = 0
    content_stored: int = 0
    versions_created: int = 0
    sql_objects_found: int = 0
    dependencies_found: int = 0
    metadata_entries: int = 0


class ProjectImporter:
    """Main project importer - orchestrates file scanning, content storage, and metadata extraction"""

    def __init__(self, project_slug: str, project_root: str, dry_run: bool = False):
        self.project_slug = project_slug
        self.project_root = Path(project_root).resolve()
        self.dry_run = dry_run
        self.stats = ImportStats()

        # Initialize components
        self.scanner = FileScanner(self.project_root)
        self.git_analyzer = GitAnalyzer(self.project_root)
        self.content_store = ContentStore()

        # Get project from database
        self.project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if not self.project:
            raise ValueError(f"Project '{project_slug}' not found in database")

        self.project_id = self.project['id']

        # Load file type IDs
        self.file_types = self._load_file_types()

        # Storage for SQL objects (analyzed before metadata population)
        self.sql_objects_by_file = {}

    def _load_file_types(self) -> Dict[str, int]:
        """Load file type IDs from database"""
        file_types = {}
        rows = query_all("SELECT id, type_name FROM file_types")
        for row in rows:
            file_types[row['type_name']] = row['id']
        return file_types

    def import_files(self) -> ImportStats:
        """Scan and import project files"""
        print(f"\n{'='*80}")
        print(f"Importing project: {self.project_slug}")
        print(f"{'='*80}")
        print(f"Project root: {self.project_root}")
        print(f"Dry run: {self.dry_run}\n")

        # Step 1: Scan files
        print("🔍 Scanning files...")
        scanned_files = self.scanner.scan_directory()
        self.stats.total_files_scanned = len(scanned_files)
        print(f"   Found {len(scanned_files)} trackable files")

        # Show file type distribution
        type_dist = self.scanner.get_type_distribution(scanned_files)
        print("\n📊 File type distribution:")
        for file_type, count in type_dist.items():
            print(f"   {file_type}: {count}")

        if self.dry_run:
            print("\n🏃 Dry run - no changes made")
            return self.stats

        # Wrap entire import in transaction for atomicity
        with transaction():
            # Step 2: Import file metadata
            print("\n💾 Importing file metadata...")
            self._import_file_metadata(scanned_files)
            print(f"   Imported {self.stats.files_imported} files")

            # Step 3: Store file contents and create versions
            print("\n📄 Storing file contents...")
            self._store_file_contents()
            print(f"   Stored {self.stats.content_stored} files")
            print(f"   Created {self.stats.versions_created} versions")

            # Step 4: Analyze SQL files
            print("\n🔬 Analyzing SQL files...")
            sql_files = [f for f in scanned_files if f.file_type in ('sql_file', 'sql_migration')]
            self._analyze_sql_files(sql_files)
            print(f"   Found {self.stats.sql_objects_found} SQL objects")

            # Step 5: Analyze dependencies
            print("\n🔗 Analyzing dependencies...")
            self._analyze_dependencies(scanned_files)
            print(f"   Found {self.stats.dependencies_found} dependencies")

            # Step 6: Populate file metadata
            print("\n📋 Populating file metadata...")
            self._populate_file_metadata(scanned_files)
            print(f"   Created {self.stats.metadata_entries} metadata entries")

        # Transaction committed successfully
        print(f"\n{'='*80}")
        print("✅ Import complete!")
        print(f"{'='*80}\n")

        return self.stats

    def _import_file_metadata(self, files: List[ScannedFile]):
        """Import file metadata into project_files table"""
        records = []

        for file in files:
            # Skip if file type not recognized
            if file.file_type not in self.file_types:
                self.stats.files_skipped += 1
                continue

            # Get git info
            git_info = self.git_analyzer.get_file_info(Path(file.absolute_path))

            records.append((
                self.project_id,
                self.file_types[file.file_type],
                file.relative_path,
                file.file_name,
                file.component_name,
                file.lines_of_code,
                git_info.commit_hash,
                'active'
            ))

        # Batch insert (commit=False because we're in a transaction)
        if records:
            executemany("""
                INSERT OR REPLACE INTO project_files
                (project_id, file_type_id, file_path, file_name, component_name,
                 lines_of_code, last_commit_hash, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, records, commit=False)

            self.stats.files_imported = len(records)

    def _store_file_contents(self):
        """Store file contents and create versions"""
        # Get all tracked files for this project
        files = query_all("""
            SELECT id, file_path
            FROM project_files
            WHERE project_id = ?
        """, (self.project_id,))

        # Get author info
        author_info = self.git_analyzer.author_info
        author = author_info['name']

        for file in files:
            file_path = self.project_root / file['file_path']

            if not file_path.exists():
                self.stats.files_skipped += 1
                continue

            # Read content
            file_content = self.content_store.read_file_content(file_path)
            if not file_content:
                self.stats.files_skipped += 1
                continue

            # Check if content changed
            existing = query_one(
                "SELECT content_hash FROM file_contents WHERE file_id = ?",
                (file['id'],)
            )

            if not self.content_store.content_changed(
                existing['content_hash'] if existing else None,
                file_content.hash_sha256
            ):
                continue

            # First, store content blob (content-addressable storage)
            # Use INSERT OR IGNORE to avoid duplicates
            if file_content.content_type == 'text':
                execute("""
                    INSERT OR IGNORE INTO content_blobs
                    (hash_sha256, content_text, content_blob, content_type, encoding, file_size_bytes)
                    VALUES (?, ?, NULL, ?, ?, ?)
                """, (
                    file_content.hash_sha256,
                    file_content.content_text,
                    file_content.content_type,
                    file_content.encoding,
                    file_content.file_size
                ), commit=False)
            else:
                execute("""
                    INSERT OR IGNORE INTO content_blobs
                    (hash_sha256, content_text, content_blob, content_type, encoding, file_size_bytes)
                    VALUES (?, NULL, ?, ?, ?, ?)
                """, (
                    file_content.hash_sha256,
                    file_content.content_blob,
                    file_content.content_type,
                    file_content.encoding,
                    file_content.file_size
                ), commit=False)

            # Then, reference the blob in file_contents
            execute("""
                INSERT OR REPLACE INTO file_contents
                (file_id, content_hash, file_size_bytes, line_count, is_current)
                VALUES (?, ?, ?, ?, 1)
            """, (
                file['id'],
                file_content.hash_sha256,
                file_content.file_size,
                file_content.line_count
            ), commit=False)

            self.stats.content_stored += 1

            # Note: Versions are now managed by VCS system (vcs_commits + vcs_file_states)
            # Not creating file_versions entries during import - they'll be created on commit

    def _analyze_sql_files(self, sql_files: List[ScannedFile]):
        """Analyze SQL files and extract database objects (stored for metadata)"""
        # Store SQL objects in memory for use in _populate_file_metadata
        self.sql_objects_by_file = {}

        for sql_file in sql_files:
            file_path = self.project_root / sql_file.relative_path

            if not file_path.exists():
                continue

            try:
                # Analyze SQL file
                sql_objects = SqlAnalyzer.analyze_sql_file(file_path)

                if sql_objects:
                    self.sql_objects_by_file[sql_file.relative_path] = sql_objects
                    self.stats.sql_objects_found += len(sql_objects)

            except Exception as e:
                print(f"   Warning: Failed to analyze {sql_file.relative_path}: {e}")
                continue

    def _analyze_dependencies(self, files: List[ScannedFile]):
        """Analyze file dependencies and populate file_dependencies table"""
        # Get all file IDs for this project for cleanup
        file_ids = query_all("""
            SELECT id FROM project_files WHERE project_id = ?
        """, (self.project_id,))

        if file_ids:
            # Clear existing dependencies for these files
            file_id_list = ','.join(str(f['id']) for f in file_ids)
            execute(f"""
                DELETE FROM file_dependencies
                WHERE parent_file_id IN ({file_id_list})
            """, commit=False)

        # Build file path to ID mapping for faster lookups
        file_map = {}
        all_project_files = query_all("""
            SELECT id, file_path FROM project_files WHERE project_id = ?
        """, (self.project_id,))

        for f in all_project_files:
            file_map[f['file_path']] = f['id']
            # Also add without extension for module lookups
            base = Path(f['file_path']).stem
            if base not in file_map:
                file_map[base] = f['id']

        all_dependencies = []

        # Only analyze Python and JS files (skip SQL for now as it's slow)
        relevant_types = {'python', 'javascript', 'typescript', 'jsx_component', 'tsx_component'}

        for scanned_file in files:
            if scanned_file.file_type not in relevant_types:
                continue

            file_path = self.project_root / scanned_file.relative_path

            if not file_path.exists():
                continue

            # Get file_id from map
            file_id = file_map.get(scanned_file.relative_path)
            if not file_id:
                continue

            # Read content
            try:
                content = file_path.read_text(encoding='utf-8', errors='ignore')
            except Exception:
                continue

            # Analyze dependencies
            dependencies = DependencyAnalyzer.analyze_file(
                file_path,
                content,
                scanned_file.file_type
            )

            for dep in dependencies:
                # Skip external dependencies
                if dep.is_external:
                    continue

                # Try to find target file in project using map
                target_file_id = None

                # Try exact match first
                if dep.imported_module in file_map:
                    target_file_id = file_map[dep.imported_module]
                else:
                    # Try with extensions
                    for ext in ['.py', '.js', '.ts', '.tsx', '.jsx']:
                        potential_path = dep.imported_module + ext
                        if potential_path in file_map:
                            target_file_id = file_map[potential_path]
                            break

                # Only add if we found a target file (internal dependencies)
                if target_file_id:
                    dependency_type = dep.import_type
                    is_hard = 1  # Internal dependencies are hard dependencies
                    usage_context = f"module: {dep.imported_module}"

                    all_dependencies.append((
                        file_id,
                        target_file_id,
                        dependency_type,
                        is_hard,
                        usage_context
                    ))

        # Batch insert dependencies (deduplicate first)
        if all_dependencies:
            # Deduplicate based on (parent, dependency, type)
            seen = set()
            unique_deps = []
            for dep in all_dependencies:
                key = (dep[0], dep[1], dep[2])  # parent_file_id, dependency_file_id, dependency_type
                if key not in seen:
                    seen.add(key)
                    unique_deps.append(dep)

            if unique_deps:
                executemany("""
                    INSERT INTO file_dependencies
                    (parent_file_id, dependency_file_id, dependency_type,
                     is_hard_dependency, usage_context)
                    VALUES (?, ?, ?, ?, ?)
                """, unique_deps, commit=False)

                self.stats.dependencies_found = len(unique_deps)

    def _populate_file_metadata(self, files: List[ScannedFile]):
        """Populate file_metadata table with structured metadata"""
        # Clear existing metadata
        execute("""
            DELETE FROM file_metadata
            WHERE file_id IN (
                SELECT id FROM project_files WHERE project_id = ?
            )
        """, (self.project_id,), commit=False)

        metadata_records = []

        for scanned_file in files:
            # Get file_id
            file_record = query_one("""
                SELECT id FROM project_files
                WHERE project_id = ? AND file_path = ?
            """, (self.project_id, scanned_file.relative_path))

            if not file_record:
                continue

            file_id = file_record['id']

            # Determine metadata type based on file type
            metadata_type = None
            metadata_json = {}

            if scanned_file.file_type in ('sql_file', 'sql_migration'):
                # Get SQL objects from memory (analyzed earlier)
                sql_objects = self.sql_objects_by_file.get(scanned_file.relative_path, [])

                if sql_objects:
                    metadata_type = 'sql_object'
                    metadata_json = {
                        'object_count': len(sql_objects),
                        'object_types': list(set(obj.object_type for obj in sql_objects)),
                        'objects': [
                            {
                                'type': obj.object_type,
                                'name': obj.object_name,
                                'schema': obj.schema_name,
                                'has_rls': obj.has_rls_enabled,
                                'has_foreign_keys': obj.has_foreign_keys
                            }
                            for obj in sql_objects
                        ]
                    }

            elif scanned_file.file_type in ('jsx_component', 'tsx_component'):
                metadata_type = 'js_component'
                metadata_json = {
                    'component_name': scanned_file.component_name,
                    'file_type': scanned_file.file_type
                }

            elif scanned_file.file_type == 'edge_function':
                metadata_type = 'edge_function'
                metadata_json = {
                    'function_name': scanned_file.component_name,
                    'file_path': scanned_file.relative_path
                }

            elif scanned_file.file_type in ('package_json', 'tsconfig', 'config_json', 'config_yaml'):
                metadata_type = 'config'
                metadata_json = {
                    'config_type': scanned_file.file_type,
                    'file_name': scanned_file.file_name
                }

            if metadata_type:
                import json
                metadata_records.append((
                    file_id,
                    metadata_type,
                    scanned_file.component_name or scanned_file.file_name,
                    json.dumps(metadata_json)
                ))

        # Batch insert metadata
        if metadata_records:
            executemany("""
                INSERT INTO file_metadata
                (file_id, metadata_type, object_name, metadata_json)
                VALUES (?, ?, ?, ?)
            """, metadata_records, commit=False)

            self.stats.metadata_entries = len(metadata_records)


def main():
    """CLI entry point for importer"""
    import argparse

    parser = argparse.ArgumentParser(description='Import project into TempleDB')
    parser.add_argument('project_root', help='Project root directory')
    parser.add_argument('project_slug', help='Project slug')
    parser.add_argument('--dry-run', action='store_true', help='Dry run (no changes)')

    args = parser.parse_args()

    try:
        importer = ProjectImporter(args.project_slug, args.project_root, args.dry_run)
        stats = importer.import_files()

        print("\n📈 Import Statistics:")
        print(f"   Total files scanned: {stats.total_files_scanned}")
        print(f"   Files imported: {stats.files_imported}")
        print(f"   Files skipped: {stats.files_skipped}")
        print(f"   Content stored: {stats.content_stored}")
        print(f"   Versions created: {stats.versions_created}")
        print(f"   SQL objects found: {stats.sql_objects_found}")
        print(f"   Dependencies found: {stats.dependencies_found}")
        print(f"   Metadata entries: {stats.metadata_entries}")

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


class WorkingStateDetector:
    """Detects file changes for VCS working state"""

    def __init__(self, project_slug: str, project_root: str):
        self.project_slug = project_slug
        self.project_root = Path(project_root).resolve()

        # Get project from database
        self.project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if not self.project:
            raise ValueError(f"Project '{project_slug}' not found in database")

        self.project_id = self.project['id']

    def detect_changes(self) -> Dict[str, int]:
        """Detect file changes and update vcs_working_state table"""
        print(f"\n🔍 Detecting changes in {self.project_slug}...")

        # Get default branch
        branch = query_one("""
            SELECT id FROM vcs_branches
            WHERE project_id = ? AND is_default = 1
        """, (self.project_id,))

        if not branch:
            print("   Error: No default branch found")
            return {}

        branch_id = branch['id']

        # Scan current files
        scanner = FileScanner(self.project_root)
        current_files = scanner.scan_directory()

        # Get all tracked files from database
        tracked_files = query_all("""
            SELECT id, file_path FROM project_files
            WHERE project_id = ?
        """, (self.project_id,))

        # Create lookup maps
        tracked_by_path = {f['file_path']: f['id'] for f in tracked_files}
        current_by_path = {f.relative_path: f for f in current_files}

        changes = {
            'added': 0,
            'modified': 0,
            'deleted': 0,
            'unmodified': 0
        }

        # Clear existing working state
        execute("""
            DELETE FROM vcs_working_state
            WHERE project_id = ? AND branch_id = ?
        """, (self.project_id, branch_id), commit=False)

        records = []

        # Check for added and modified files
        for rel_path, scanned_file in current_by_path.items():
            if rel_path not in tracked_by_path:
                # New file
                state = 'added'
                changes['added'] += 1
            else:
                # Check if modified
                file_id = tracked_by_path[rel_path]

                # Get last committed content hash
                last_content = query_one("""
                    SELECT content_hash FROM file_contents
                    WHERE file_id = ?
                """, (file_id,))

                # Read current content hash
                file_path = self.project_root / rel_path
                file_content = ContentStore.read_file_content(file_path)

                if not file_content:
                    continue

                if last_content and last_content['content_hash'] == file_content.hash_sha256:
                    state = 'unmodified'
                    changes['unmodified'] += 1
                else:
                    state = 'modified'
                    changes['modified'] += 1

                records.append((
                    self.project_id,
                    branch_id,
                    file_id,
                    state,
                    0,  # staged
                    file_content.hash_sha256
                ))

        # Check for deleted files
        for file_path, file_id in tracked_by_path.items():
            if file_path not in current_by_path:
                state = 'deleted'
                changes['deleted'] += 1

                records.append((
                    self.project_id,
                    branch_id,
                    file_id,
                    state,
                    0,  # staged
                    None  # No hash for deleted files
                ))

        # Insert working state
        if records:
            executemany("""
                INSERT INTO vcs_working_state
                (project_id, branch_id, file_id, state, staged, content_hash)
                VALUES (?, ?, ?, ?, ?, ?)
            """, records, commit=False)

        print(f"   Added: {changes['added']}")
        print(f"   Modified: {changes['modified']}")
        print(f"   Deleted: {changes['deleted']}")
        print(f"   Unmodified: {changes['unmodified']}")

        return changes


if __name__ == '__main__':
    main()
