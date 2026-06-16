#!/usr/bin/env python3
"""
Git history analyzer for project import
"""
import subprocess
from pathlib import Path
from typing import Optional, Dict
from dataclasses import dataclass


@dataclass
class GitInfo:
    """Git information for a file"""
    commit_hash: Optional[str] = None
    author: Optional[str] = None
    email: Optional[str] = None
    timestamp: Optional[str] = None
    branch: Optional[str] = None


class GitAnalyzer:
    """Analyzes Git history for files"""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root).resolve()
        self._is_git_repo = self._check_git_repo()
        self._git_author = self._get_git_author() if self._is_git_repo else None

    def _check_git_repo(self) -> bool:
        """Check if project root is a git repository"""
        try:
            subprocess.run(
                ['git', 'rev-parse', '--git-dir'],
                cwd=self.project_root,
                capture_output=True,
                check=True,
                timeout=5
            )
            return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def _get_git_author(self) -> Dict[str, str]:
        """Get git config author info"""
        try:
            name = subprocess.run(
                ['git', 'config', 'user.name'],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=5
            ).stdout.strip()

            email = subprocess.run(
                ['git', 'config', 'user.email'],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=5
            ).stdout.strip()

            return {'name': name or 'unknown', 'email': email or 'unknown@localhost'}
        except Exception:
            return {'name': 'unknown', 'email': 'unknown@localhost'}

    def get_current_branch(self) -> Optional[str]:
        """Get current git branch"""
        if not self._is_git_repo:
            return None

        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=5,
                check=True
            )
            return result.stdout.strip()
        except Exception:
            return None

    def get_file_info(self, file_path: Path) -> GitInfo:
        """Get git information for a specific file"""
        if not self._is_git_repo:
            return GitInfo()

        rel_path = str(file_path.relative_to(self.project_root))

        try:
            # Get last commit hash
            hash_result = subprocess.run(
                ['git', 'log', '-1', '--format=%H', '--', rel_path],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=5
            )
            commit_hash = hash_result.stdout.strip() or None

            # Get author
            author_result = subprocess.run(
                ['git', 'log', '-1', '--format=%an', '--', rel_path],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=5
            )
            author = author_result.stdout.strip() or None

            # Get author email
            email_result = subprocess.run(
                ['git', 'log', '-1', '--format=%ae', '--', rel_path],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=5
            )
            email = email_result.stdout.strip() or None

            # Get timestamp
            timestamp_result = subprocess.run(
                ['git', 'log', '-1', '--format=%ai', '--', rel_path],
                cwd=self.project_root,
                capture_output=True,
                text=True,
                timeout=5
            )
            timestamp = timestamp_result.stdout.strip() or None

            # Get current branch
            branch = self.get_current_branch()

            return GitInfo(
                commit_hash=commit_hash,
                author=author,
                email=email,
                timestamp=timestamp,
                branch=branch
            )
        except Exception:
            return GitInfo()

    @property
    def author_info(self) -> Dict[str, str]:
        """Get author information"""
        return self._git_author or {'name': 'unknown', 'email': 'unknown@localhost'}
