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
