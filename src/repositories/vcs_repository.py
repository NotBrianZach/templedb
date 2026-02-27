"""
VCS repository for managing version control operations.
"""

from typing import Optional, List, Dict, Any

from .base import BaseRepository
from logger import get_logger

logger = get_logger(__name__)


class VCSRepository(BaseRepository):
    """
    Repository for version control system operations.

    Provides a clean interface for:
    - Managing branches
    - Creating commits
    - Recording file changes
    - Getting version history
    """

    def get_or_create_branch(self, project_id: int, branch_name: str = 'main') -> int:
        """
        Get existing branch or create it if it doesn't exist.

        Args:
            project_id: Project ID
            branch_name: Branch name (default: 'main')

        Returns:
            Branch ID
        """
        # Try to get existing branch
        branch = self.query_one("""
            SELECT id FROM vcs_branches
            WHERE project_id = ? AND branch_name = ?
        """, (project_id, branch_name))

        if branch:
            logger.debug(f"Found existing branch '{branch_name}' with ID {branch['id']}")
            return branch['id']

        # Create new branch
        logger.info(f"Creating branch '{branch_name}' for project {project_id}")
        branch_id = self.execute("""
            INSERT INTO vcs_branches
            (project_id, branch_name, is_default)
            VALUES (?, ?, ?)
        """, (project_id, branch_name, 1 if branch_name == 'main' else 0), commit=False)

        logger.info(f"Created branch '{branch_name}' with ID {branch_id}")
        return branch_id

    def create_commit(self, project_id: int, branch_id: int, commit_hash: str,
                     author: str, message: str) -> int:
        """
        Create a new commit record.

        Args:
            project_id: Project ID
            branch_id: Branch ID
            commit_hash: Commit hash (SHA-256)
            author: Commit author
            message: Commit message

        Returns:
            Commit ID
        """
        logger.info(f"Creating commit for project {project_id} on branch {branch_id}")
        commit_id = self.execute("""
            INSERT INTO vcs_commits
            (project_id, branch_id, commit_hash, author, commit_message, commit_timestamp)
            VALUES (?, ?, ?, ?, ?, datetime('now'))
        """, (project_id, branch_id, commit_hash, author, message), commit=False)

        logger.info(f"Created commit {commit_id} with hash {commit_hash[:8]}")
        return commit_id

    def record_file_change(self, commit_id: int, file_id: int, change_type: str,
                          old_hash: Optional[str] = None, new_hash: Optional[str] = None,
                          old_path: Optional[str] = None, new_path: Optional[str] = None) -> None:
        """
        Record a file change in a commit.

        Args:
            commit_id: Commit ID
            file_id: File ID
            change_type: 'added', 'modified', or 'deleted'
            old_hash: Old content hash (for modified/deleted)
            new_hash: New content hash (for added/modified)
            old_path: Old file path (for deleted/renamed)
            new_path: New file path (for added/renamed)
        """
        logger.debug(f"Recording {change_type} change for file {file_id} in commit {commit_id}")
        self.execute("""
            INSERT INTO commit_files
            (commit_id, file_id, change_type, old_content_hash, new_content_hash, old_file_path, new_file_path)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (commit_id, file_id, change_type, old_hash, new_hash, old_path, new_path), commit=False)

    def get_commit_history(self, project_id: int, branch_name: Optional[str] = None,
                          limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get commit history for a project.

        Args:
            project_id: Project ID
            branch_name: Optional branch name to filter by
            limit: Maximum number of commits to return (default: 50)

        Returns:
            List of commit dictionaries ordered by timestamp DESC
        """
        if branch_name:
            logger.debug(f"Getting commit history for project {project_id}, branch {branch_name}")
            return self.query_all("""
                SELECT
                    c.id,
                    c.commit_hash,
                    c.author,
                    c.commit_message,
                    c.commit_timestamp,
                    b.branch_name,
                    (SELECT COUNT(*) FROM commit_files WHERE commit_id = c.id) as files_changed
                FROM vcs_commits c
                JOIN vcs_branches b ON c.branch_id = b.id
                WHERE c.project_id = ? AND b.branch_name = ?
                ORDER BY c.commit_timestamp DESC
                LIMIT ?
            """, (project_id, branch_name, limit))
        else:
            logger.debug(f"Getting commit history for project {project_id}")
            return self.query_all("""
                SELECT
                    c.id,
                    c.commit_hash,
                    c.author,
                    c.commit_message,
                    c.commit_timestamp,
                    b.branch_name,
                    (SELECT COUNT(*) FROM commit_files WHERE commit_id = c.id) as files_changed
                FROM vcs_commits c
                JOIN vcs_branches b ON c.branch_id = b.id
                WHERE c.project_id = ?
                ORDER BY c.commit_timestamp DESC
                LIMIT ?
            """, (project_id, limit))

    def get_commit_files(self, commit_id: int) -> List[Dict[str, Any]]:
        """
        Get all file changes for a commit.

        Args:
            commit_id: Commit ID

        Returns:
            List of file change dictionaries
        """
        logger.debug(f"Getting file changes for commit {commit_id}")
        return self.query_all("""
            SELECT
                cf.file_id,
                cf.change_type,
                cf.old_content_hash,
                cf.new_content_hash,
                cf.old_file_path,
                cf.new_file_path,
                pf.file_path as current_path
            FROM commit_files cf
            LEFT JOIN project_files pf ON cf.file_id = pf.id
            WHERE cf.commit_id = ?
            ORDER BY pf.file_path
        """, (commit_id,))

    def get_branches(self, project_id: int) -> List[Dict[str, Any]]:
        """
        Get all branches for a project.

        Args:
            project_id: Project ID

        Returns:
            List of branch dictionaries
        """
        logger.debug(f"Getting branches for project {project_id}")
        return self.query_all("""
            SELECT
                vb.id,
                vb.branch_name,
                vb.is_default,
                vb.created_at,
                (SELECT COUNT(*) FROM vcs_commits WHERE branch_id = vb.id) as commit_count
            FROM vcs_branches vb
            WHERE vb.project_id = ?
            ORDER BY vb.is_default DESC, vb.branch_name
        """, (project_id,))

    # ========== Commit Metadata Operations ==========

    def create_commit_metadata(
        self,
        commit_id: int,
        intent: Optional[str] = None,
        change_type: Optional[str] = None,
        scope: Optional[str] = None,
        is_breaking: bool = False,
        breaking_change_description: Optional[str] = None,
        migration_notes: Optional[str] = None,
        related_issues: Optional[str] = None,
        related_commits: Optional[str] = None,
        impact_level: Optional[str] = None,
        risk_level: Optional[str] = None,
        ai_assisted: bool = False,
        ai_tool: Optional[str] = None,
        confidence_level: Optional[str] = None,
        review_status: Optional[str] = None,
        tags: Optional[str] = None,
        **kwargs
    ) -> int:
        """
        Create commit metadata record.

        Args:
            commit_id: Commit ID
            intent: High-level "why" behind the commit
            change_type: Type of change (feature, bugfix, refactor, etc.)
            scope: Area of codebase affected
            is_breaking: Whether this is a breaking change
            breaking_change_description: Description of breaking changes
            migration_notes: How to migrate from previous version
            related_issues: JSON array of issue IDs/URLs
            related_commits: JSON array of related commit hashes
            impact_level: low, medium, high, critical
            risk_level: low, medium, high
            ai_assisted: Whether AI was used
            ai_tool: Which AI tool was used
            confidence_level: Developer's confidence (low, medium, high)
            review_status: Review status
            tags: JSON array of custom tags
            **kwargs: Additional metadata fields

        Returns:
            Metadata ID
        """
        logger.debug(f"Creating metadata for commit {commit_id}")

        # Build dynamic SQL for optional fields
        fields = ['commit_id']
        values = [commit_id]

        field_map = {
            'intent': intent,
            'change_type': change_type,
            'scope': scope,
            'is_breaking': is_breaking,
            'breaking_change_description': breaking_change_description,
            'migration_notes': migration_notes,
            'related_issues': related_issues,
            'related_commits': related_commits,
            'impact_level': impact_level,
            'risk_level': risk_level,
            'ai_assisted': ai_assisted,
            'ai_tool': ai_tool,
            'confidence_level': confidence_level,
            'review_status': review_status,
            'tags': tags,
        }

        # Add additional kwargs
        field_map.update(kwargs)

        for field, value in field_map.items():
            if value is not None:
                fields.append(field)
                values.append(value)

        placeholders = ', '.join(['?' for _ in values])
        field_names = ', '.join(fields)

        metadata_id = self.execute(f"""
            INSERT INTO vcs_commit_metadata ({field_names})
            VALUES ({placeholders})
        """, tuple(values), commit=False)

        logger.info(f"Created commit metadata {metadata_id} for commit {commit_id}")
        return metadata_id

    def get_commit_metadata(self, commit_id: int) -> Optional[Dict[str, Any]]:
        """
        Get metadata for a commit.

        Args:
            commit_id: Commit ID

        Returns:
            Metadata dictionary or None
        """
        return self.query_one("""
            SELECT * FROM vcs_commit_metadata
            WHERE commit_id = ?
        """, (commit_id,))

    def update_commit_metadata(self, commit_id: int, **kwargs) -> None:
        """
        Update commit metadata.

        Args:
            commit_id: Commit ID
            **kwargs: Fields to update
        """
        if not kwargs:
            return

        logger.debug(f"Updating metadata for commit {commit_id}")

        # Build dynamic UPDATE statement
        set_clauses = []
        values = []

        for field, value in kwargs.items():
            set_clauses.append(f"{field} = ?")
            values.append(value)

        values.append(commit_id)

        self.execute(f"""
            UPDATE vcs_commit_metadata
            SET {', '.join(set_clauses)}, updated_at = datetime('now')
            WHERE commit_id = ?
        """, tuple(values), commit=False)

        logger.info(f"Updated metadata for commit {commit_id}")

    def create_file_change_metadata(
        self,
        commit_id: int,
        file_id: int,
        change_intent: Optional[str] = None,
        change_summary: Optional[str] = None,
        change_complexity: Optional[str] = None,
        requires_testing: bool = True,
        test_file_path: Optional[str] = None,
        **kwargs
    ) -> int:
        """
        Create file-specific change metadata.

        Args:
            commit_id: Commit ID
            file_id: File ID
            change_intent: Why this specific file was changed
            change_summary: Brief summary of changes
            change_complexity: trivial, simple, moderate, complex
            requires_testing: Whether testing is needed
            test_file_path: Associated test file
            **kwargs: Additional metadata fields

        Returns:
            Metadata ID
        """
        logger.debug(f"Creating file change metadata for file {file_id} in commit {commit_id}")

        fields = ['commit_id', 'file_id']
        values = [commit_id, file_id]

        field_map = {
            'change_intent': change_intent,
            'change_summary': change_summary,
            'change_complexity': change_complexity,
            'requires_testing': requires_testing,
            'test_file_path': test_file_path,
        }

        field_map.update(kwargs)

        for field, value in field_map.items():
            if value is not None:
                fields.append(field)
                values.append(value)

        placeholders = ', '.join(['?' for _ in values])
        field_names = ', '.join(fields)

        metadata_id = self.execute(f"""
            INSERT INTO vcs_file_change_metadata ({field_names})
            VALUES ({placeholders})
        """, tuple(values), commit=False)

        logger.info(f"Created file change metadata {metadata_id}")
        return metadata_id

    def get_file_change_metadata(self, commit_id: int, file_id: int) -> Optional[Dict[str, Any]]:
        """
        Get file-specific change metadata.

        Args:
            commit_id: Commit ID
            file_id: File ID

        Returns:
            Metadata dictionary or None
        """
        return self.query_one("""
            SELECT * FROM vcs_file_change_metadata
            WHERE commit_id = ? AND file_id = ?
        """, (commit_id, file_id))

    def add_commit_tag(self, commit_id: int, tag_name: str, tag_category: Optional[str] = None) -> int:
        """
        Add a tag to a commit.

        Args:
            commit_id: Commit ID
            tag_name: Tag name
            tag_category: Optional category (type, priority, team, custom)

        Returns:
            Tag ID
        """
        logger.debug(f"Adding tag '{tag_name}' to commit {commit_id}")

        tag_id = self.execute("""
            INSERT OR IGNORE INTO vcs_commit_tags (commit_id, tag_name, tag_category)
            VALUES (?, ?, ?)
        """, (commit_id, tag_name, tag_category), commit=False)

        return tag_id

    def get_commit_tags(self, commit_id: int) -> List[Dict[str, Any]]:
        """
        Get all tags for a commit.

        Args:
            commit_id: Commit ID

        Returns:
            List of tag dictionaries
        """
        return self.query_all("""
            SELECT tag_name, tag_category, created_at
            FROM vcs_commit_tags
            WHERE commit_id = ?
            ORDER BY tag_name
        """, (commit_id,))

    def get_commits_with_metadata(
        self,
        project_id: int,
        change_type: Optional[str] = None,
        is_breaking: Optional[bool] = None,
        ai_assisted: Optional[bool] = None,
        impact_level: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Get commits with their metadata, optionally filtered.

        Args:
            project_id: Project ID
            change_type: Filter by change type
            is_breaking: Filter by breaking changes
            ai_assisted: Filter by AI assistance
            impact_level: Filter by impact level
            limit: Maximum number of commits

        Returns:
            List of commit dictionaries with metadata
        """
        where_clauses = ["c.project_id = ?"]
        params = [project_id]

        if change_type:
            where_clauses.append("m.change_type = ?")
            params.append(change_type)

        if is_breaking is not None:
            where_clauses.append("m.is_breaking = ?")
            params.append(1 if is_breaking else 0)

        if ai_assisted is not None:
            where_clauses.append("m.ai_assisted = ?")
            params.append(1 if ai_assisted else 0)

        if impact_level:
            where_clauses.append("m.impact_level = ?")
            params.append(impact_level)

        params.append(limit)

        where_clause = " AND ".join(where_clauses)

        return self.query_all(f"""
            SELECT
                c.*,
                m.intent,
                m.change_type,
                m.scope,
                m.is_breaking,
                m.impact_level,
                m.ai_assisted,
                m.ai_tool,
                m.confidence_level,
                m.review_status
            FROM vcs_commits c
            LEFT JOIN vcs_commit_metadata m ON c.id = m.commit_id
            WHERE {where_clause}
            ORDER BY c.commit_timestamp DESC
            LIMIT ?
        """, tuple(params))

    def get_current_file_version(self, file_id: int) -> Optional[Dict[str, Any]]:
        """
        Get the current version information for a file.

        Args:
            file_id: File ID

        Returns:
            Version dictionary with version, content_hash, commit info
        """
        logger.debug(f"Getting current version for file {file_id}")
        return self.query_one("""
            SELECT
                fc.version,
                fc.content_hash,
                c.author,
                c.commit_timestamp
            FROM file_contents fc
            LEFT JOIN commit_files cf ON cf.file_id = fc.file_id AND cf.new_content_hash = fc.content_hash
            LEFT JOIN vcs_commits c ON c.id = cf.commit_id
            WHERE fc.file_id = ? AND fc.is_current = 1
        """, (file_id,))
