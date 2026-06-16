#!/usr/bin/env python3
"""
Git History Importer

Imports complete git history into TempleDB database, including:
- All commits with metadata
- All branches and tags
- File versions at each commit
- Commit relationships (parents, merges)
"""

import subprocess
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from logger import get_logger
from repositories import VCSRepository, FileRepository, ProjectRepository
from importer.content import ContentStore, FileContent

logger = get_logger(__name__)


@dataclass
class GitCommit:
    """Represents a git commit"""
    hash: str
    author: str
    author_email: str
    committer: str
    committer_email: str
    timestamp: str
    message: str
    parent_hashes: List[str]
    files_changed: List[str]


@dataclass
class GitRef:
    """Represents a git ref (branch or tag)"""
    name: str
    ref_type: str  # 'branch' or 'tag'
    commit_hash: str


class GitHistoryImporter:
    """Imports complete git history into database"""

    def __init__(self, project_slug: str, git_repo_path: str):
        """
        Initialize git history importer

        Args:
            project_slug: Project slug in database
            git_repo_path: Path to git repository
        """
        self.project_slug = project_slug
        self.git_repo_path = Path(git_repo_path).resolve()

        self.project_repo = ProjectRepository()
        self.vcs_repo = VCSRepository()
        self.file_repo = FileRepository()
        self.content_store = ContentStore()

        # Verify git repo
        if not (self.git_repo_path / '.git').exists():
            raise ValueError(f"Not a git repository: {self.git_repo_path}")

        # Get project
        self.project = self.project_repo.get_by_slug(project_slug)
        if not self.project:
            raise ValueError(f"Project not found: {project_slug}")

        self.project_id = self.project['id']

    def import_full_history(self, branch: Optional[str] = None) -> Dict:
        """
        Import complete git history

        Args:
            branch: Specific branch to import, or None for all branches

        Returns:
            Dictionary with import statistics
        """
        logger.info(f"Importing git history for {self.project_slug}")

        stats = {
            'commits_imported': 0,
            'branches_imported': 0,
            'tags_imported': 0,
            'files_versioned': 0,
            'errors': 0
        }

        try:
            # Get all refs (branches and tags)
            refs = self._get_all_refs()
            logger.info(f"Found {len(refs)} refs")

            # Filter to specific branch if requested
            if branch:
                refs = [r for r in refs if r.name == branch or r.name == f'refs/heads/{branch}']
                if not refs:
                    raise ValueError(f"Branch not found: {branch}")

            # Get all commits reachable from refs
            all_commits = self._get_all_commits(refs)
            logger.info(f"Found {len(all_commits)} commits")

            # Import commits in topological order (parents before children)
            sorted_commits = self._topological_sort(all_commits)

            with self.vcs_repo.transaction():
                # Import commits
                for commit in sorted_commits:
                    try:
                        self._import_commit(commit)
                        stats['commits_imported'] += 1

                        if stats['commits_imported'] % 10 == 0:
                            logger.info(f"Imported {stats['commits_imported']}/{len(sorted_commits)} commits")

                    except Exception as e:
                        logger.error(f"Failed to import commit {commit.hash}: {e}")
                        stats['errors'] += 1

                # Import branches and tags
                for ref in refs:
                    try:
                        if ref.ref_type == 'branch':
                            self._import_branch(ref)
                            stats['branches_imported'] += 1
                        else:
                            self._import_tag(ref)
                            stats['tags_imported'] += 1

                    except Exception as e:
                        logger.error(f"Failed to import ref {ref.name}: {e}")
                        stats['errors'] += 1

            logger.info("Git history import complete")
            logger.info(f"  Commits: {stats['commits_imported']}")
            logger.info(f"  Branches: {stats['branches_imported']}")
            logger.info(f"  Tags: {stats['tags_imported']}")
            if stats['errors'] > 0:
                logger.warning(f"  Errors: {stats['errors']}")

            return stats

        except Exception as e:
            logger.error(f"Git history import failed: {e}", exc_info=True)
            raise

    def _get_all_refs(self) -> List[GitRef]:
        """Get all branches and tags from git repository"""
        refs = []

        try:
            # Get branches
            output = subprocess.check_output(
                ['git', 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/heads/'],
                cwd=self.git_repo_path,
                text=True
            ).strip()

            for line in output.split('\n'):
                if not line:
                    continue

                parts = line.split()
                if len(parts) >= 2:
                    ref_name = parts[0]
                    commit_hash = parts[1]

                    refs.append(GitRef(
                        name=ref_name,
                        ref_type='branch',
                        commit_hash=commit_hash
                    ))

            # Get tags
            output = subprocess.check_output(
                ['git', 'for-each-ref', '--format=%(refname) %(objectname)', 'refs/tags/'],
                cwd=self.git_repo_path,
                text=True
            ).strip()

            for line in output.split('\n'):
                if not line:
                    continue

                parts = line.split()
                if len(parts) >= 2:
                    ref_name = parts[0]
                    commit_hash = parts[1]

                    refs.append(GitRef(
                        name=ref_name,
                        ref_type='tag',
                        commit_hash=commit_hash
                    ))

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to get git refs: {e}")

        return refs

    def _get_all_commits(self, refs: List[GitRef]) -> List[GitCommit]:
        """Get all commits reachable from given refs"""
        commits_by_hash = {}

        try:
            # Get commit list with metadata
            # Format: hash|author|author_email|committer|committer_email|timestamp|subject|parents
            format_str = '%H|%an|%ae|%cn|%ce|%ai|%s|%P'

            ref_commits = [ref.commit_hash for ref in refs]

            output = subprocess.check_output(
                ['git', 'log', '--all', f'--format={format_str}'],
                cwd=self.git_repo_path,
                text=True
            ).strip()

            for line in output.split('\n'):
                if not line:
                    continue

                parts = line.split('|')
                if len(parts) < 7:
                    continue

                commit_hash = parts[0]
                author = parts[1]
                author_email = parts[2]
                committer = parts[3]
                committer_email = parts[4]
                timestamp = parts[5]
                subject = parts[6]
                parents = parts[7].split() if len(parts) > 7 else []

                # Get full commit message
                message = self._get_commit_message(commit_hash)

                # Get files changed in this commit
                files_changed = self._get_commit_files(commit_hash)

                commits_by_hash[commit_hash] = GitCommit(
                    hash=commit_hash,
                    author=author,
                    author_email=author_email,
                    committer=committer,
                    committer_email=committer_email,
                    timestamp=timestamp,
                    message=message,
                    parent_hashes=parents,
                    files_changed=files_changed
                )

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to get git commits: {e}")

        return list(commits_by_hash.values())

    def _get_commit_message(self, commit_hash: str) -> str:
        """Get full commit message"""
        try:
            output = subprocess.check_output(
                ['git', 'log', '-1', '--format=%B', commit_hash],
                cwd=self.git_repo_path,
                text=True
            ).strip()
            return output
        except Exception:
            return ""

    def _get_commit_files(self, commit_hash: str) -> List[str]:
        """Get list of files changed in commit"""
        try:
            output = subprocess.check_output(
                ['git', 'diff-tree', '--no-commit-id', '--name-only', '-r', commit_hash],
                cwd=self.git_repo_path,
                text=True
            ).strip()

            return [f for f in output.split('\n') if f]

        except Exception:
            return []

    def _topological_sort(self, commits: List[GitCommit]) -> List[GitCommit]:
        """Sort commits in topological order (parents before children)"""
        commits_by_hash = {c.hash: c for c in commits}

        visited = set()
        result = []

        def visit(commit_hash: str):
            if commit_hash in visited:
                return
            if commit_hash not in commits_by_hash:
                return  # Parent not in our set

            commit = commits_by_hash[commit_hash]

            # Visit parents first
            for parent_hash in commit.parent_hashes:
                visit(parent_hash)

            visited.add(commit_hash)
            result.append(commit)

        # Visit all commits
        for commit in commits:
            visit(commit.hash)

        return result

    def _import_commit(self, commit: GitCommit):
        """Import a single commit into database"""

        # Check if commit already exists
        existing = self.vcs_repo.get_commit_by_hash(self.project_id, commit.hash)
        if existing:
            logger.debug(f"Commit {commit.hash[:8]} already imported")
            return

        # Get or create branch (assume main for now, will be updated by ref import)
        branch_id = self.vcs_repo.get_or_create_branch(self.project_id, 'main')

        # Create commit record
        commit_id = self.vcs_repo.create_commit(
            project_id=self.project_id,
            branch_id=branch_id,
            commit_hash=commit.hash,
            author=commit.author,
            message=commit.message,
            parent_hash=commit.parent_hashes[0] if commit.parent_hashes else None
        )

        # Store additional metadata
        if commit.author_email:
            self.vcs_repo.execute(
                "UPDATE vcs_commits SET author_email = ? WHERE id = ?",
                (commit.author_email, commit_id),
                commit=False
            )

        # Import file versions at this commit
        for file_path in commit.files_changed:
            try:
                self._import_file_version(commit_id, commit.hash, file_path)
            except Exception as e:
                logger.warning(f"Could not import {file_path} at {commit.hash[:8]}: {e}")

    def _import_file_version(self, commit_id: int, commit_hash: str, file_path: str):
        """Import a file version at a specific commit"""

        # Get file content at this commit
        try:
            content = subprocess.check_output(
                ['git', 'show', f'{commit_hash}:{file_path}'],
                cwd=self.git_repo_path
            )

            # Try to decode as text
            try:
                content_text = content.decode('utf-8')
                file_content = FileContent(
                    content_text=content_text,
                    content_blob=None,
                    content_type='text',
                    encoding='utf-8',
                    file_size=len(content),
                    line_count=content_text.count('\n') + 1 if content_text else 0,
                    hash_sha256=hashlib.sha256(content).hexdigest()
                )
            except UnicodeDecodeError:
                # Binary file
                file_content = FileContent(
                    content_text=None,
                    content_blob=content,
                    content_type='binary',
                    encoding=None,
                    file_size=len(content),
                    line_count=0,
                    hash_sha256=hashlib.sha256(content).hexdigest()
                )

            # Get or create file record
            file_record = self.file_repo.get_by_path(self.project_id, file_path)

            if not file_record:
                # Create file record
                file_name = Path(file_path).name
                component_name = Path(file_path).stem
                file_type_id = self._get_file_type_id(file_path)

                file_id = self.file_repo.execute("""
                    INSERT INTO project_files
                    (project_id, file_path, file_name, file_type_id, component_name)
                    VALUES (?, ?, ?, ?, ?)
                """, (self.project_id, file_path, file_name, file_type_id, component_name), commit=False)
            else:
                file_id = file_record['file_id']

            # Store content blob (deduplication via INSERT OR IGNORE)
            if file_content.content_type == 'text':
                self.file_repo.execute("""
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
                self.file_repo.execute("""
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

            # Record in commit_files
            self.vcs_repo.record_file_change(
                commit_id=commit_id,
                file_id=file_id,
                change_type='modified',  # Simplified - could detect add/delete
                old_hash=None,
                new_hash=file_content.hash_sha256,
                new_path=file_path
            )

        except subprocess.CalledProcessError:
            # File was deleted at this commit
            pass

    def _import_branch(self, ref: GitRef):
        """Import a branch reference"""
        branch_name = ref.name.replace('refs/heads/', '')

        # Get or create branch
        branch_id = self.vcs_repo.get_or_create_branch(self.project_id, branch_name)

        # Update branch to point to correct commit
        commit = self.vcs_repo.get_commit_by_hash(self.project_id, ref.commit_hash)

        if commit:
            self.vcs_repo.execute("""
                UPDATE vcs_branches
                SET head_commit_id = ?
                WHERE id = ?
            """, (commit['id'], branch_id), commit=False)

    def _import_tag(self, ref: GitRef):
        """Import a tag reference"""
        tag_name = ref.name.replace('refs/tags/', '')

        # Get commit
        commit = self.vcs_repo.get_commit_by_hash(self.project_id, ref.commit_hash)

        if commit:
            # Store tag (assuming vcs_tags table exists)
            self.vcs_repo.execute("""
                INSERT OR REPLACE INTO vcs_tags
                (project_id, tag_name, commit_id)
                VALUES (?, ?, ?)
            """, (self.project_id, tag_name, commit['id']), commit=False)

    def _get_file_type_id(self, file_path: str) -> Optional[int]:
        """Get file type ID for a file path"""
        extension = Path(file_path).suffix.lstrip('.')

        extension_map = {
            'py': 'python',
            'js': 'javascript',
            'ts': 'typescript',
            'sql': 'sql',
            'md': 'markdown',
            'txt': 'text',
            'json': 'json',
            'yaml': 'yaml',
            'yml': 'yaml',
        }

        type_name = extension_map.get(extension, 'unknown')

        file_type = self.file_repo.query_one("SELECT id FROM file_types WHERE type_name = ?", (type_name,))
        return file_type['id'] if file_type else None
