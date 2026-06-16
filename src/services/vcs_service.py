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

    def get_current_branch(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Get active branch, falling back to default."""
        branch = self.vcs_repo.get_active_branch(project_id)
        if not branch:
            branch = self.get_default_branch(project_id)
        return branch

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
        branch = self.get_current_branch(project['id'])

        if not branch:
            raise ResourceNotFoundError(
                "No branch found",
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

    def add_untracked_file(self, project_slug: str, file_path: str) -> bool:
        """
        Add a new untracked file to the project and stage it.

        Creates project_files and vcs_working_state records for a file
        that exists on disk but isn't yet tracked in the database.

        Args:
            project_slug: Project slug
            file_path: Relative file path within the project

        Returns:
            True if file was added and staged successfully
        """
        import os
        from pathlib import Path

        # Normalize path (remove ./ prefix, resolve)
        file_path = str(Path(file_path))

        project = self.get_project(project_slug)
        branch = self.get_current_branch(project['id'])
        if not branch:
            raise ResourceNotFoundError("No branch found")

        # Determine the checkout directory
        checkout_dir = os.path.expanduser(
            f"~/.config/templedb/checkouts/{project_slug}"
        )
        full_path = Path(checkout_dir) / file_path

        if not full_path.exists():
            return False

        # Detect file type from extension
        ext_to_type = {
            '.sh': 'shell_script', '.bash': 'shell_script',
            '.py': 'python', '.js': 'javascript', '.mjs': 'javascript',
            '.ts': 'typescript', '.tsx': 'tsx_component',
            '.jsx': 'jsx_component', '.css': 'css', '.scss': 'scss',
            '.html': 'html', '.sql': 'sql_file',
            '.json': 'config_json', '.yaml': 'config_yaml', '.yml': 'config_yaml',
            '.md': 'markdown', '.nix': 'nix_file',
            '.el': 'emacs_lisp', '.env': 'env_file',
        }
        ext = full_path.suffix.lower()
        type_name = ext_to_type.get(ext, 'javascript')  # fallback

        # Get file_type_id
        file_type = self.vcs_repo.query_one(
            "SELECT id FROM file_types WHERE type_name = ?", (type_name,)
        )
        if not file_type:
            # Fallback to first type
            file_type = self.vcs_repo.query_one("SELECT id FROM file_types LIMIT 1")

        file_type_id = file_type['id']
        file_name = full_path.name

        # Read content
        try:
            content = full_path.read_text()
        except UnicodeDecodeError:
            content = None

        # Insert project_files record
        self.vcs_repo.execute("""
            INSERT OR IGNORE INTO project_files (project_id, file_type_id, file_path, file_name, status)
            VALUES (?, ?, ?, ?, 'active')
        """, (project['id'], file_type_id, file_path, file_name))

        # Get the file record
        file_record = self.vcs_repo.query_one("""
            SELECT id FROM project_files WHERE project_id = ? AND file_path = ?
        """, (project['id'], file_path))

        if not file_record:
            return False

        # Create working state record
        self.vcs_repo.execute("""
            INSERT OR REPLACE INTO vcs_working_state
                (project_id, branch_id, file_id, content_text, state, staged)
            VALUES (?, ?, ?, ?, 'added', 1)
        """, (project['id'], branch['id'], file_record['id'], content))

        return True

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
        branch = self.get_current_branch(project['id'])

        if not branch:
            raise ResourceNotFoundError("No branch found")

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
            branch = self.get_current_branch(project['id'])

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
        branch = self.get_current_branch(project['id'])

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
