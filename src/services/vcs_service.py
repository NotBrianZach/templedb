#!/usr/bin/env python3
"""
VCS Service - Business logic for version control operations

Handles staging, committing, branching, and diff operations for
database-native version control.
"""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from services.base import BaseService
from error_handler import ResourceNotFoundError, ValidationError


@dataclass
class CommitResult:
    """Result of a commit operation"""
    commit_id: int
    commit_hash: str
    message: str
    file_count: int
    author: str


class VCSService(BaseService):
    """
    Service layer for version control operations.

    Provides business logic for staging, committing, and managing
    version control state independent of CLI presentation.
    """

    def __init__(self, context):
        super().__init__()
        self.ctx = context
        self.project_repo = context.project_repo

        # Import VCSRepository on demand
        from repositories import VCSRepository
        self.vcs_repo = VCSRepository()

    def get_project(self, slug: str) -> Dict[str, Any]:
        """Get project by slug or raise error"""
        project = self.project_repo.get_by_slug(slug)
        if not project:
            raise ResourceNotFoundError(
                f"Project '{slug}' not found",
                solution="Run 'templedb project list' to see available projects"
            )
        return project

    def get_default_branch(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Get default branch for a project"""
        branches = self.vcs_repo.get_branches(project_id)
        return next((b for b in branches if b.get('is_default')), None)

    def stage_files(
        self,
        project_slug: str,
        file_patterns: Optional[List[str]] = None,
        stage_all: bool = False
    ) -> int:
        """
        Stage files for commit.

        Args:
            project_slug: Project slug
            file_patterns: List of file patterns to stage (optional)
            stage_all: If True, stage all modified files

        Returns:
            Number of files staged

        Raises:
            ResourceNotFoundError: If project or branch not found
            ValidationError: If neither file_patterns nor stage_all provided
        """
        project = self.get_project(project_slug)
        branch = self.get_default_branch(project['id'])

        if not branch:
            raise ResourceNotFoundError(
                "No default branch found",
                solution="Create a branch first"
            )

        if stage_all:
            # Stage all modified files
            self.vcs_repo.execute("""
                UPDATE vcs_working_state
                SET staged = 1
                WHERE project_id = ? AND branch_id = ? AND state != 'unmodified'
            """, (project['id'], branch['id']))

            result = self.vcs_repo.query_one("""
                SELECT COUNT(*) as count FROM vcs_working_state
                WHERE project_id = ? AND branch_id = ? AND staged = 1
            """, (project['id'], branch['id']))

            return result['count'] if result else 0

        elif file_patterns:
            # Stage specific files
            count = 0
            for pattern in file_patterns:
                files = self.vcs_repo.query_all("""
                    SELECT ws.id, pf.file_path
                    FROM vcs_working_state ws
                    JOIN project_files pf ON ws.file_id = pf.id
                    WHERE ws.project_id = ? AND ws.branch_id = ?
                    AND pf.file_path LIKE ?
                """, (project['id'], branch['id'], f"%{pattern}%"))

                for file in files:
                    self.vcs_repo.execute("""
                        UPDATE vcs_working_state
                        SET staged = 1
                        WHERE id = ?
                    """, (file['id'],))
                    count += 1

            return count

        else:
            raise ValidationError(
                "Must specify either file_patterns or stage_all",
                solution="Provide file patterns or use stage_all=True"
            )

    def unstage_files(
        self,
        project_slug: str,
        file_patterns: Optional[List[str]] = None,
        unstage_all: bool = False
    ) -> int:
        """
        Unstage files.

        Args:
            project_slug: Project slug
            file_patterns: List of file patterns to unstage (optional)
            unstage_all: If True, unstage all files

        Returns:
            Number of files unstaged
        """
        project = self.get_project(project_slug)
        branch = self.get_default_branch(project['id'])

        if not branch:
            raise ResourceNotFoundError("No default branch found")

        if unstage_all:
            self.vcs_repo.execute("""
                UPDATE vcs_working_state
                SET staged = 0
                WHERE project_id = ? AND branch_id = ? AND staged = 1
            """, (project['id'], branch['id']))

            result = self.vcs_repo.query_one("""
                SELECT COUNT(*) as count FROM vcs_working_state
                WHERE project_id = ? AND branch_id = ? AND state != 'unmodified'
            """, (project['id'], branch['id']))

            return result['count'] if result else 0

        elif file_patterns:
            count = 0
            for pattern in file_patterns:
                files = self.vcs_repo.query_all("""
                    SELECT ws.id, pf.file_path
                    FROM vcs_working_state ws
                    JOIN project_files pf ON ws.file_id = pf.id
                    WHERE ws.project_id = ? AND ws.branch_id = ?
                    AND ws.staged = 1 AND pf.file_path LIKE ?
                """, (project['id'], branch['id'], f"%{pattern}%"))

                for file in files:
                    self.vcs_repo.execute("""
                        UPDATE vcs_working_state
                        SET staged = 0
                        WHERE id = ?
                    """, (file['id'],))
                    count += 1

            return count

        else:
            raise ValidationError("Must specify either file_patterns or unstage_all")

    def commit(
        self,
        project_slug: str,
        message: str,
        author: Optional[str] = None,
        branch_name: Optional[str] = None
    ) -> CommitResult:
        """
        Create a commit from staged files.

        Args:
            project_slug: Project slug
            message: Commit message
            author: Author name (defaults to git config)
            branch_name: Branch name (defaults to default branch)

        Returns:
            CommitResult with commit information

        Raises:
            ResourceNotFoundError: If project or branch not found
            ValidationError: If no staged files
        """
        project = self.get_project(project_slug)

        # Get author
        if author is None:
            author = self._get_author()

        # Get branch
        if branch_name:
            branches = self.vcs_repo.get_branches(project['id'])
            branch = next((b for b in branches if b['branch_name'] == branch_name), None)
        else:
            branch = self.get_default_branch(project['id'])

        if not branch:
            raise ResourceNotFoundError("Branch not found")

        # Check for staged files
        staged = self.vcs_repo.query_all("""
            SELECT ws.*, fc.content_text, fc.file_size_bytes, fc.line_count
            FROM vcs_working_state ws
            LEFT JOIN file_contents fc ON ws.file_id = fc.file_id
            WHERE ws.project_id = ? AND ws.branch_id = ? AND ws.staged = 1
        """, (project['id'], branch['id']))

        if not staged:
            raise ValidationError(
                "No staged files to commit",
                solution="Use 'templedb add' to stage files first"
            )

        # Create commit via repository
        commit_result = self.vcs_repo.create_commit(
            project_id=project['id'],
            branch_id=branch['id'],
            message=message,
            author=author,
            staged_files=staged
        )

        self.logger.info(
            f"Created commit {commit_result['commit_hash'][:8]} "
            f"with {len(staged)} files"
        )

        return CommitResult(
            commit_id=commit_result['commit_id'],
            commit_hash=commit_result['commit_hash'],
            message=message,
            file_count=len(staged),
            author=author
        )

    def get_status(self, project_slug: str) -> Dict[str, Any]:
        """
        Get VCS status for a project.

        Returns:
            Dictionary with staged, modified, untracked files
        """
        project = self.get_project(project_slug)
        branch = self.get_default_branch(project['id'])

        if not branch:
            return {
                'has_branch': False,
                'staged': [],
                'modified': [],
                'untracked': []
            }

        # Get working state
        working_state = self.vcs_repo.query_all("""
            SELECT ws.state, ws.staged, pf.file_path
            FROM vcs_working_state ws
            JOIN project_files pf ON ws.file_id = pf.id
            WHERE ws.project_id = ? AND ws.branch_id = ?
            ORDER BY pf.file_path
        """, (project['id'], branch['id']))

        staged = [f['file_path'] for f in working_state if f['staged']]
        modified = [f['file_path'] for f in working_state
                   if not f['staged'] and f['state'] == 'modified']
        untracked = [f['file_path'] for f in working_state if f['state'] == 'added']

        return {
            'has_branch': True,
            'branch': branch['branch_name'],
            'staged': staged,
            'modified': modified,
            'untracked': untracked
        }

    def _get_author(self) -> str:
        """Get author name from git config or default"""
        import subprocess
        try:
            result = subprocess.run(
                ['git', 'config', 'user.name'],
                capture_output=True,
                text=True,
                timeout=5
            )
            author = result.stdout.strip()
            if author:
                return author
        except Exception:
            pass
        return "unknown"
