#!/usr/bin/env python3
"""
Git Export Module

Exports database commits back to git repository, enabling the roundtrip:
  External Git → Import → TempleDB → Export → Git
"""

import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass

from logger import get_logger
from repositories import VCSRepository, FileRepository, ProjectRepository

logger = get_logger(__name__)


@dataclass
class ExportStats:
    """Statistics from git export operation"""
    commits_exported: int = 0
    files_written: int = 0
    branches_updated: int = 0
    errors: int = 0


class GitExporter:
    """Exports database commits to git repository"""

    def __init__(self, project_slug: str, git_repo_path: str):
        """
        Initialize git exporter

        Args:
            project_slug: Project slug in database
            git_repo_path: Path to target git repository
        """
        self.project_slug = project_slug
        self.git_repo_path = Path(git_repo_path).resolve()

        self.project_repo = ProjectRepository()
        self.vcs_repo = VCSRepository()
        self.file_repo = FileRepository()

        # Verify git repo
        if not (self.git_repo_path / '.git').exists():
            raise ValueError(f"Not a git repository: {self.git_repo_path}")

        # Get project
        self.project = self.project_repo.get_by_slug(project_slug)
        if not self.project:
            raise ValueError(f"Project not found: {project_slug}")

        self.project_id = self.project['id']

    def export_commits(
        self,
        branch_name: str = 'main',
        since_commit: Optional[str] = None
    ) -> ExportStats:
        """
        Export database commits to git repository

        Args:
            branch_name: Branch to export to
            since_commit: Only export commits after this git commit hash

        Returns:
            Export statistics
        """
        logger.info(f"Exporting commits from {self.project_slug} to git")

        stats = ExportStats()

        try:
            # Get database commits to export
            db_commits = self._get_commits_to_export(branch_name, since_commit)

            if not db_commits:
                logger.info("No new commits to export")
                return stats

            logger.info(f"Found {len(db_commits)} commits to export")

            # Ensure git branch exists and is checked out
            self._prepare_git_branch(branch_name)

            # Export each commit
            for db_commit in db_commits:
                try:
                    self._export_commit(db_commit, stats)
                    stats.commits_exported += 1

                    if stats.commits_exported % 5 == 0:
                        logger.info(f"Exported {stats.commits_exported}/{len(db_commits)} commits")

                except Exception as e:
                    logger.error(f"Failed to export commit {db_commit['commit_hash']}: {e}")
                    stats.errors += 1

            stats.branches_updated = 1

            logger.info(f"Export complete: {stats.commits_exported} commits exported")

            return stats

        except Exception as e:
            logger.error(f"Git export failed: {e}", exc_info=True)
            raise

    def _get_commits_to_export(
        self,
        branch_name: str,
        since_commit: Optional[str]
    ) -> List[Dict]:
        """Get database commits that need to be exported to git"""

        # Get branch
        branch = self.vcs_repo.query_one("""
            SELECT id FROM vcs_branches
            WHERE project_id = ? AND branch_name = ?
        """, (self.project_id, branch_name))

        if not branch:
            logger.warning(f"Branch '{branch_name}' not found in database")
            return []

        # Get commits
        if since_commit:
            # Find the database commit with this hash
            base_commit = self.vcs_repo.query_one("""
                SELECT id FROM vcs_commits
                WHERE project_id = ? AND commit_hash = ?
            """, (self.project_id, since_commit))

            if not base_commit:
                logger.warning(f"Base commit {since_commit} not found in database")
                return []

            # Get commits after this one
            commits = self.vcs_repo.query_all("""
                SELECT
                    id,
                    commit_hash,
                    author,
                    commit_message,
                    commit_timestamp
                FROM vcs_commits
                WHERE project_id = ? AND branch_id = ?
                AND id > ?
                ORDER BY id ASC
            """, (self.project_id, branch['id'], base_commit['id']))
        else:
            # Get all commits
            commits = self.vcs_repo.query_all("""
                SELECT
                    id,
                    commit_hash,
                    author,
                    commit_message,
                    commit_timestamp
                FROM vcs_commits
                WHERE project_id = ? AND branch_id = ?
                ORDER BY id ASC
            """, (self.project_id, branch['id']))

        return commits

    def _prepare_git_branch(self, branch_name: str):
        """Ensure git branch exists and is checked out"""

        try:
            # Check if branch exists
            result = subprocess.run(
                ['git', 'rev-parse', '--verify', branch_name],
                cwd=self.git_repo_path,
                capture_output=True,
                timeout=5
            )

            if result.returncode != 0:
                # Branch doesn't exist, create it
                logger.info(f"Creating git branch: {branch_name}")
                subprocess.run(
                    ['git', 'checkout', '-b', branch_name],
                    cwd=self.git_repo_path,
                    check=True,
                    capture_output=True,
                    timeout=10
                )
            else:
                # Branch exists, check it out
                subprocess.run(
                    ['git', 'checkout', branch_name],
                    cwd=self.git_repo_path,
                    check=True,
                    capture_output=True,
                    timeout=10
                )

        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to prepare git branch: {e}")

    def _export_commit(self, db_commit: Dict, stats: ExportStats):
        """Export a single database commit to git"""

        commit_id = db_commit['id']
        commit_hash = db_commit['commit_hash']
        author = db_commit['author']
        message = db_commit['commit_message']
        timestamp = db_commit['commit_timestamp']

        logger.debug(f"Exporting commit {commit_hash[:8]}: {message[:50]}")

        # Get files changed in this commit
        changed_files = self.vcs_repo.query_all("""
            SELECT
                cf.file_id,
                cf.change_type,
                cf.new_content_hash,
                cf.old_content_hash,
                cf.new_path,
                cf.old_path,
                pf.file_path
            FROM commit_files cf
            JOIN project_files pf ON cf.file_id = pf.id
            WHERE cf.commit_id = ?
        """, (commit_id,))

        # Write files to git working directory
        for file_change in changed_files:
            try:
                self._apply_file_change(file_change)
                stats.files_written += 1
            except Exception as e:
                logger.error(f"Failed to apply change to {file_change['file_path']}: {e}")
                raise

        # Stage all changes
        subprocess.run(
            ['git', 'add', '-A'],
            cwd=self.git_repo_path,
            check=True,
            capture_output=True,
            timeout=30
        )

        # Create git commit with original metadata
        env = {
            **subprocess.os.environ,
            'GIT_AUTHOR_NAME': author or 'TempleDB',
            'GIT_AUTHOR_EMAIL': f'{author}@templedb.local',
            'GIT_AUTHOR_DATE': timestamp or '',
            'GIT_COMMITTER_NAME': 'TempleDB Exporter',
            'GIT_COMMITTER_EMAIL': 'export@templedb.local'
        }

        # Add note about database origin
        full_message = f"{message}\n\n[TempleDB export from commit {commit_hash[:8]}]"

        subprocess.run(
            ['git', 'commit', '-m', full_message, '--allow-empty'],
            cwd=self.git_repo_path,
            env=env,
            check=True,
            capture_output=True,
            timeout=30
        )

        logger.debug(f"Created git commit for {commit_hash[:8]}")

    def _apply_file_change(self, file_change: Dict):
        """Apply a file change to git working directory"""

        change_type = file_change['change_type']
        file_path = file_change.get('new_path') or file_change['file_path']
        target_path = self.git_repo_path / file_path

        if change_type == 'deleted':
            # Delete file
            if target_path.exists():
                target_path.unlink()
                logger.debug(f"Deleted: {file_path}")

        elif change_type in ['added', 'modified']:
            # Get content from database
            content_hash = file_change['new_content_hash']

            content_row = self.file_repo.query_one("""
                SELECT content_text, content_blob, content_type
                FROM content_blobs
                WHERE hash_sha256 = ?
            """, (content_hash,))

            if not content_row:
                raise ValueError(f"Content not found for hash {content_hash}")

            # Ensure parent directory exists
            target_path.parent.mkdir(parents=True, exist_ok=True)

            # Write content
            if content_row['content_type'] == 'text' and content_row['content_text']:
                target_path.write_text(content_row['content_text'])
            elif content_row['content_blob']:
                target_path.write_bytes(content_row['content_blob'])
            else:
                raise ValueError(f"No content available for {file_path}")

            logger.debug(f"{change_type.title()}: {file_path}")

        elif change_type == 'renamed':
            # Handle rename
            old_path = self.git_repo_path / file_change['old_path']
            new_path = self.git_repo_path / file_change['new_path']

            if old_path.exists():
                new_path.parent.mkdir(parents=True, exist_ok=True)
                old_path.rename(new_path)
                logger.debug(f"Renamed: {file_change['old_path']} → {file_change['new_path']}")

    def push_to_remote(
        self,
        remote: str = 'origin',
        branch: str = 'main',
        force: bool = False
    ) -> bool:
        """
        Push exported commits to remote git repository

        Args:
            remote: Remote name (default: origin)
            branch: Branch to push (default: main)
            force: Force push (use with caution)

        Returns:
            True if successful, False otherwise
        """
        try:
            cmd = ['git', 'push', remote, branch]
            if force:
                cmd.append('--force')

            result = subprocess.run(
                cmd,
                cwd=self.git_repo_path,
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode == 0:
                logger.info(f"Pushed to {remote}/{branch}")
                return True
            else:
                logger.error(f"Push failed: {result.stderr}")
                return False

        except subprocess.CalledProcessError as e:
            logger.error(f"Push failed: {e}")
            return False
        except subprocess.TimeoutExpired:
            logger.error("Push timed out")
            return False
