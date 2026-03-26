"""
Maps TempleDB database records to git objects

Converts TempleDB's VCS data structures to git's object model:
- vcs_commits → git commit objects
- vcs_file_states → git tree objects
- content_blobs → git blob objects
- vcs_branches → git refs
"""

import hashlib
from typing import Optional, Dict, List, Tuple
from pathlib import Path
from dulwich.objects import Commit, Tree, Blob, Tag
from dulwich.repo import BaseRepo
from db_utils import get_connection
from logger import get_logger

logger = get_logger(__name__)


class ObjectMapper:
    """Maps TempleDB data to git objects"""

    def __init__(self, project_slug: str):
        self.project_slug = project_slug
        self.db = get_connection()

        # Get project ID
        project = self.db.execute(
            "SELECT id, slug FROM projects WHERE slug = ?",
            (project_slug,)
        ).fetchone()

        if not project:
            raise ValueError(f"Project not found: {project_slug}")

        self.project_id = project['id']

        # Cache for git objects
        self._blob_cache = {}
        self._tree_cache = {}
        self._commit_cache = {}

    def get_refs(self) -> Dict[bytes, bytes]:
        """
        Get all refs (branches and tags) for the project

        Returns:
            Dict mapping ref names to commit hashes (both as bytes)
        """
        refs = {}

        # Get branches
        branches = self.db.execute("""
            SELECT branch_name,
                   (SELECT commit_hash FROM vcs_commits
                    WHERE branch_id = vcs_branches.id
                    ORDER BY commit_timestamp DESC LIMIT 1) as head_commit
            FROM vcs_branches
            WHERE project_id = ?
        """, (self.project_id,)).fetchall()

        for branch in branches:
            if branch['head_commit']:
                ref_name = f"refs/heads/{branch['branch_name']}".encode()
                commit_hash = branch['head_commit'].encode()
                refs[ref_name] = commit_hash

        logger.debug(f"Found {len(refs)} refs for {self.project_slug}")
        return refs

    def get_commit(self, commit_hash: str) -> Optional[Commit]:
        """
        Convert a TempleDB commit to a git Commit object

        Args:
            commit_hash: TempleDB commit hash

        Returns:
            dulwich Commit object or None if not found
        """
        if commit_hash in self._commit_cache:
            return self._commit_cache[commit_hash]

        # Get commit from database
        commit_row = self.db.execute("""
            SELECT c.*, b.branch_name
            FROM vcs_commits c
            JOIN vcs_branches b ON c.branch_id = b.id
            WHERE c.project_id = ? AND c.commit_hash = ?
        """, (self.project_id, commit_hash)).fetchone()

        if not commit_row:
            logger.warning(f"Commit not found: {commit_hash}")
            return None

        # Create git Commit object
        commit = Commit()
        commit.message = commit_row['commit_message'].encode('utf-8')
        commit.author = commit_row['author'].encode('utf-8')
        commit.committer = commit_row['author'].encode('utf-8')

        # Parse timestamp - TempleDB stores as ISO8601 string
        import time
        from datetime import datetime
        dt = datetime.fromisoformat(commit_row['commit_timestamp'])
        timestamp = int(dt.timestamp())
        timezone = 0  # UTC

        commit.author_time = timestamp
        commit.commit_time = timestamp
        commit.author_timezone = timezone
        commit.commit_timezone = timezone

        # Get tree for this commit
        tree = self.get_tree_for_commit(commit_hash)
        if tree:
            commit.tree = tree.id

        # TODO: Handle parent commits (for now, all commits are root commits)
        # We'll need to track parent relationships in TempleDB

        self._commit_cache[commit_hash] = commit
        return commit

    def get_tree_for_commit(self, commit_hash: str) -> Optional[Tree]:
        """
        Build a git Tree object from vcs_file_states for a commit

        Args:
            commit_hash: TempleDB commit hash

        Returns:
            dulwich Tree object representing the file tree at this commit
        """
        cache_key = f"tree:{commit_hash}"
        if cache_key in self._tree_cache:
            return self._tree_cache[cache_key]

        # Get commit ID
        commit_row = self.db.execute("""
            SELECT id FROM vcs_commits
            WHERE project_id = ? AND commit_hash = ?
        """, (self.project_id, commit_hash)).fetchone()

        if not commit_row:
            return None

        commit_id = commit_row['id']

        # Get all files in this commit
        files = self.db.execute("""
            SELECT
                pf.file_path,
                vfs.content_hash,
                vfs.change_type
            FROM vcs_file_states vfs
            JOIN project_files pf ON vfs.file_id = pf.id
            WHERE vfs.commit_id = ? AND vfs.change_type != 'deleted'
        """, (commit_id,)).fetchall()

        # Build tree structure
        tree = self._build_tree_from_files(files)

        self._tree_cache[cache_key] = tree
        return tree

    def _build_tree_from_files(self, files: List[Dict]) -> Tree:
        """
        Build a git Tree from a flat list of files

        This creates a hierarchical tree structure from flat file paths.
        """
        # For simplicity, we'll create a flat tree first
        # TODO: Implement proper directory hierarchy
        tree = Tree()

        for file in files:
            path = file['file_path']
            content_hash = file['content_hash']

            # Get blob for this file
            blob = self.get_blob(content_hash)
            if blob:
                # Add to tree (mode 0100644 = regular file)
                tree.add(path.encode('utf-8'), 0o100644, blob.id)

        return tree

    def get_blob(self, content_hash: str) -> Optional[Blob]:
        """
        Convert file content from database to git Blob object

        Args:
            content_hash: SHA256 hash of content in content_blobs table

        Returns:
            dulwich Blob object or None if not found
        """
        if content_hash in self._blob_cache:
            return self._blob_cache[content_hash]

        # Get content from database
        content_row = self.db.execute("""
            SELECT content_text, content_type
            FROM content_blobs
            WHERE hash_sha256 = ?
        """, (content_hash,)).fetchone()

        if not content_row:
            logger.warning(f"Content not found: {content_hash}")
            return None

        if content_row['content_type'] != 'text':
            logger.warning(f"Binary content not supported yet: {content_hash}")
            return None

        # Create git Blob
        blob = Blob()
        blob.data = content_row['content_text'].encode('utf-8')

        self._blob_cache[content_hash] = blob
        return blob

    def resolve_ref(self, ref_name: bytes) -> Optional[bytes]:
        """
        Resolve a ref name to a commit hash

        Args:
            ref_name: Git ref name (e.g. b'refs/heads/main')

        Returns:
            Commit hash as bytes or None
        """
        refs = self.get_refs()
        return refs.get(ref_name)
