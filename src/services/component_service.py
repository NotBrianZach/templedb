"""
Component Service - Manage cross-project component library.

This service enables storing components once and referencing them
across multiple projects, eliminating duplication.

ARCHITECTURE (v2 - No redundant components table):
- Uses existing `project_files` table with `is_shared` flag
- Uses `shared_file_references` for cross-project mapping
- All content stored in content-addressable `content_blobs`

Key features:
- Register components (React, Vue, Python classes, functions)
- Link components to projects
- Update components (affects all users)
- Query component usage
- Content-addressed storage (deduplication)
"""

import hashlib
from typing import List, Dict, Optional
from pathlib import Path

from .base import BaseService, ErrorCategory, ServiceError
from ..compression import ContentCompressor, CompressionResult, calculate_content_hash


class ComponentService(BaseService):
    """Manage component library and cross-project reuse"""

    def register_component(
        self,
        name: str,
        component_type: str,
        content: str,
        file_path: Optional[str] = None,
        description: Optional[str] = None,
        is_shared: bool = False,
        git_sha: Optional[str] = None,
        owner: Optional[str] = None,
        compress: bool = True,
        project_slug: Optional[str] = None
    ) -> int:
        """
        Register a component in the library using project_files table.

        Args:
            name: Component name (e.g., 'Button', 'useAuth')
            component_type: Type (e.g., 'react_component', 'python_class')
            content: The actual code
            file_path: Where it lives in git repo
            description: Human-readable description
            is_shared: Can other projects use this?
            git_sha: Git commit hash (for history)
            owner: Team/person responsible
            compress: Apply compression to content
            project_slug: Project to register component in (required for non-shared)

        Returns:
            file_id (project_files.id)

        Raises:
            ServiceError: If registration fails
        """
        try:
            # Convert content to bytes
            content_bytes = content.encode('utf-8')

            # Calculate hash
            content_hash = calculate_content_hash(content_bytes)

            # Compress if requested
            if compress:
                compressor = ContentCompressor()
                result = compressor.compress_zlib(content_bytes)

                # Store in content_blobs
                self.db.execute("""
                    INSERT OR IGNORE INTO content_blobs (
                        hash_sha256,
                        content_text,
                        content_blob,
                        content_type,
                        file_size_bytes,
                        original_size_bytes,
                        compression
                    ) VALUES (?, NULL, ?, 'text', ?, ?, 'zlib')
                """, (
                    content_hash,
                    result.compressed_data,
                    result.compressed_size,
                    result.original_size
                ))
            else:
                # Store uncompressed
                self.db.execute("""
                    INSERT OR IGNORE INTO content_blobs (
                        hash_sha256,
                        content_text,
                        content_type,
                        file_size_bytes,
                        original_size_bytes,
                        compression
                    ) VALUES (?, ?, 'text', ?, ?, 'none')
                """, (
                    content_hash,
                    content,
                    len(content_bytes),
                    len(content_bytes)
                ))

            # Get or create project (for shared components, use a special "shared" project)
            if is_shared:
                # Use special "shared" project for shared components
                project = self.db.query_one("""
                    SELECT id FROM projects WHERE slug = 'shared-components'
                """)

                if not project:
                    # Create shared-components project
                    project_id = self.db.execute("""
                        INSERT INTO projects (name, slug, description)
                        VALUES ('Shared Components', 'shared-components', 'Cross-project shared components')
                        RETURNING id
                    """)
                else:
                    project_id = project['id']
            else:
                # Non-shared components must belong to a specific project
                if not project_slug:
                    raise ServiceError(
                        "project_slug required for non-shared components",
                        ErrorCategory.VALIDATION
                    )

                project = self.db.query_one("""
                    SELECT id FROM projects WHERE slug = ?
                """, (project_slug,))

                if not project:
                    raise ServiceError(
                        f"Project not found: {project_slug}",
                        ErrorCategory.NOT_FOUND
                    )

                project_id = project['id']

            # Get file type
            file_type = self.db.query_one("""
                SELECT id FROM file_types WHERE type_name = ?
            """, (component_type,))

            if not file_type:
                # Create file type if it doesn't exist
                file_type_id = self.db.execute("""
                    INSERT INTO file_types (type_name, category, description)
                    VALUES (?, 'component', ?)
                    RETURNING id
                """, (component_type, f'Component type: {component_type}'))
            else:
                file_type_id = file_type['id']

            # Register in project_files table
            file_id = self.db.execute("""
                INSERT INTO project_files (
                    project_id,
                    file_type_id,
                    file_path,
                    file_name,
                    component_name,
                    description,
                    owner,
                    is_shared,
                    last_commit_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, file_path) DO UPDATE SET
                    component_name = excluded.component_name,
                    description = excluded.description,
                    owner = excluded.owner,
                    is_shared = excluded.is_shared,
                    last_commit_hash = excluded.last_commit_hash,
                    updated_at = datetime('now')
                RETURNING id
            """, (
                project_id,
                file_type_id,
                file_path or f'components/{name}',
                Path(file_path).name if file_path else name,
                name,  # component_name
                description,
                owner,
                is_shared,
                git_sha
            ))

            # Store content in file_contents
            self.db.execute("""
                INSERT INTO file_contents (
                    file_id,
                    content_hash,
                    content_type,
                    file_size_bytes,
                    is_current
                ) VALUES (?, ?, 'text', ?, 1)
                ON CONFLICT(file_id, is_current) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    file_size_bytes = excluded.file_size_bytes,
                    updated_at = datetime('now')
            """, (
                file_id,
                content_hash,
                len(content_bytes)
            ))

            # Update reference count
            self.db.execute("""
                UPDATE content_blobs
                SET reference_count = reference_count + 1
                WHERE hash_sha256 = ?
            """, (content_hash,))

            return file_id

        except ServiceError:
            raise
        except Exception as e:
            raise ServiceError(
                f"Failed to register component '{name}': {e}",
                ErrorCategory.DATABASE,
                {"name": name, "type": component_type}
            )

    def link_component_to_project(
        self,
        project_slug: str,
        component_name: str,
        alias: Optional[str] = None
    ):
        """
        Link a component to a project (no duplication!).

        Args:
            project_slug: Project to link to
            component_name: Component to link
            alias: Optional import alias

        Raises:
            ServiceError: If linking fails
        """
        try:
            # Get project
            project = self.db.query_one("""
                SELECT id FROM projects WHERE slug = ?
            """, (project_slug,))

            if not project:
                raise ServiceError(
                    f"Project not found: {project_slug}",
                    ErrorCategory.NOT_FOUND
                )

            # Get component (shared file)
            component = self.db.query_one("""
                SELECT pf.id, pf.project_id, fc.content_hash
                FROM project_files pf
                JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
                WHERE pf.component_name = ? AND pf.is_shared = 1
            """, (component_name,))

            if not component:
                raise ServiceError(
                    f"Shared component not found: {component_name}",
                    ErrorCategory.NOT_FOUND
                )

            # Create shared file reference
            self.db.execute("""
                INSERT INTO shared_file_references (
                    source_project_id,
                    source_file_id,
                    using_project_id,
                    alias
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(source_file_id, using_project_id) DO UPDATE SET
                    alias = excluded.alias,
                    last_used_at = datetime('now')
            """, (
                component['project_id'],
                component['id'],
                project['id'],
                alias
            ))

            # Update reference count
            self.db.execute("""
                UPDATE content_blobs
                SET reference_count = reference_count + 1
                WHERE hash_sha256 = ?
            """, (component['content_hash'],))

        except ServiceError:
            raise
        except Exception as e:
            raise ServiceError(
                f"Failed to link component '{component_name}' to '{project_slug}': {e}",
                ErrorCategory.DATABASE
            )

    def get_component(self, name: str) -> Optional[Dict]:
        """
        Get component by name with content.

        Args:
            name: Component name

        Returns:
            Component dict with content, or None if not found
        """
        return self.db.query_one("""
            SELECT
                pf.id,
                pf.component_name as name,
                ft.type_name as component_type,
                pf.is_shared,
                pf.file_path,
                pf.description,
                pf.owner,
                cb.content_text,
                cb.file_size_bytes,
                cb.original_size_bytes,
                cb.compression,
                pf.created_at,
                pf.updated_at
            FROM project_files pf
            JOIN file_types ft ON pf.file_type_id = ft.id
            JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
            JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
            WHERE pf.component_name = ?
        """, (name,))

    def get_components_for_project(self, project_slug: str) -> List[Dict]:
        """
        Get all components used by a project.

        Args:
            project_slug: Project slug

        Returns:
            List of component dicts
        """
        return self.db.query("""
            SELECT
                pf.component_name as name,
                ft.type_name as component_type,
                pf.file_path,
                pf.description,
                sfr.alias,
                cb.file_size_bytes,
                sfr.linked_at as imported_at,
                sfr.last_used_at
            FROM shared_file_references sfr
            JOIN project_files pf ON sfr.source_file_id = pf.id
            JOIN file_types ft ON pf.file_type_id = ft.id
            JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
            JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
            JOIN projects p ON sfr.using_project_id = p.id
            WHERE p.slug = ?
            ORDER BY pf.component_name
        """, (project_slug,))

    def find_component_usage(self, component_name: str) -> List[Dict]:
        """
        Find which projects use this component.

        Args:
            component_name: Component name

        Returns:
            List of project dicts
        """
        return self.db.query("""
            SELECT
                p.slug,
                p.name,
                sfr.alias,
                sfr.linked_at as imported_at,
                sfr.last_used_at
            FROM projects p
            JOIN shared_file_references sfr ON p.id = sfr.using_project_id
            JOIN project_files pf ON sfr.source_file_id = pf.id
            WHERE pf.component_name = ?
            ORDER BY p.slug
        """, (component_name,))

    def update_component(
        self,
        component_name: str,
        new_content: str,
        git_sha: Optional[str] = None
    ) -> Dict:
        """
        Update a component (affects all projects using it!).

        Args:
            component_name: Component to update
            new_content: New code content
            git_sha: Git commit hash

        Returns:
            Dict with impact info:
                - component: name
                - affected_projects: list of project slugs
                - impact_count: number of affected projects

        Raises:
            ServiceError: If update fails
        """
        try:
            # Get current component
            component = self.db.query_one("""
                SELECT
                    pf.id,
                    pf.component_name,
                    fc.content_hash as old_hash
                FROM project_files pf
                JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
                WHERE pf.component_name = ?
            """, (component_name,))

            if not component:
                raise ServiceError(
                    f"Component not found: {component_name}",
                    ErrorCategory.NOT_FOUND
                )

            # Find projects using it
            projects = self.find_component_usage(component_name)

            # Calculate new hash
            content_bytes = new_content.encode('utf-8')
            new_hash = calculate_content_hash(content_bytes)

            # Store new content (compressed)
            compressor = ContentCompressor()
            result = compressor.compress_zlib(content_bytes)

            self.db.execute("""
                INSERT OR IGNORE INTO content_blobs (
                    hash_sha256,
                    content_blob,
                    content_type,
                    file_size_bytes,
                    original_size_bytes,
                    compression
                ) VALUES (?, ?, 'text', ?, ?, 'zlib')
            """, (
                new_hash,
                result.compressed_data,
                result.compressed_size,
                result.original_size
            ))

            # Update file_contents
            self.db.execute("""
                UPDATE file_contents
                SET content_hash = ?,
                    file_size_bytes = ?,
                    updated_at = datetime('now')
                WHERE file_id = ? AND is_current = 1
            """, (new_hash, len(content_bytes), component['id']))

            # Update project_files
            self.db.execute("""
                UPDATE project_files
                SET last_commit_hash = ?,
                    updated_at = datetime('now')
                WHERE id = ?
            """, (git_sha, component['id']))

            return {
                'component': component_name,
                'affected_projects': [p['slug'] for p in projects],
                'impact_count': len(projects),
                'old_hash': component['old_hash'],
                'new_hash': new_hash
            }

        except ServiceError:
            raise
        except Exception as e:
            raise ServiceError(
                f"Failed to update component '{component_name}': {e}",
                ErrorCategory.DATABASE
            )

    def list_components(
        self,
        shared_only: bool = False,
        component_type: Optional[str] = None
    ) -> List[Dict]:
        """
        List all components.

        Args:
            shared_only: Only show shared components
            component_type: Filter by type

        Returns:
            List of component dicts
        """
        query = """
            SELECT
                pf.component_name as name,
                ft.type_name as component_type,
                pf.is_shared,
                pf.file_path,
                pf.description,
                pf.owner,
                cb.file_size_bytes,
                cb.original_size_bytes,
                (SELECT COUNT(*) FROM shared_file_references sfr WHERE sfr.source_file_id = pf.id) as usage_count,
                pf.created_at,
                pf.updated_at
            FROM project_files pf
            JOIN file_types ft ON pf.file_type_id = ft.id
            JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
            JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
            WHERE pf.component_name IS NOT NULL
        """

        params = []

        if shared_only:
            query += " AND pf.is_shared = 1"

        if component_type:
            query += " AND ft.type_name = ?"
            params.append(component_type)

        query += " ORDER BY pf.component_name"

        return self.db.query(query, tuple(params))

    def delete_component(self, component_name: str, force: bool = False):
        """
        Delete a component (soft delete).

        Args:
            component_name: Component to delete
            force: Force delete even if in use

        Raises:
            ServiceError: If deletion fails or component is in use
        """
        try:
            # Check usage
            usage = self.find_component_usage(component_name)

            if usage and not force:
                raise ServiceError(
                    f"Component '{component_name}' is used by {len(usage)} projects. "
                    f"Use --force to delete anyway.",
                    ErrorCategory.VALIDATION,
                    {"usage": [p['slug'] for p in usage]}
                )

            # Get component
            component = self.db.query_one("""
                SELECT
                    pf.id,
                    fc.content_hash
                FROM project_files pf
                JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
                WHERE pf.component_name = ?
            """, (component_name,))

            if not component:
                raise ServiceError(
                    f"Component not found: {component_name}",
                    ErrorCategory.NOT_FOUND
                )

            # Remove from shared_file_references
            self.db.execute("""
                DELETE FROM shared_file_references WHERE source_file_id = ?
            """, (component['id'],))

            # Soft delete content blob
            self.db.execute("""
                UPDATE content_blobs
                SET is_deleted = 1,
                    reference_count = reference_count - 1
                WHERE hash_sha256 = ?
            """, (component['content_hash'],))

            # Delete file_contents
            self.db.execute("""
                DELETE FROM file_contents WHERE file_id = ?
            """, (component['id'],))

            # Delete from project_files
            self.db.execute("""
                DELETE FROM project_files WHERE id = ?
            """, (component['id'],))

        except ServiceError:
            raise
        except Exception as e:
            raise ServiceError(
                f"Failed to delete component '{component_name}': {e}",
                ErrorCategory.DATABASE
            )
