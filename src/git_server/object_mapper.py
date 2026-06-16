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

        # Cache for git objects (keyed by git SHA1, not TempleDB hash)
        self._blob_cache = {}
        self._tree_cache = {}
        self._commit_cache = {}
        self._templedb_to_git_hash = {}  # Map TempleDB hash -> git SHA1

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
                # Validate commit hash (must be 40-character hex string for SHA1)
                if len(branch['head_commit']) != 40:
                    logger.warning(f"Skipping invalid commit hash for branch {branch['branch_name']}: {branch['head_commit']} (length {len(branch['head_commit'])})")
                    continue

                # Get the actual git commit object to get its real SHA1
                commit = self.get_commit(branch['head_commit'])
                if commit:
                    ref_name = f"refs/heads/{branch['branch_name']}".encode()
                    # Use the actual git object ID, not the TempleDB hash
                    commit_hash = commit.id
                    refs[ref_name] = commit_hash
                else:
                    logger.warning(f"Could not get commit object for {branch['head_commit']}")

        logger.debug(f"Found {len(refs)} refs for {self.project_slug}")
        return refs

    def get_commit(self, commit_hash: str) -> Optional[Commit]:
        """
        Convert a TempleDB commit to a git Commit object

        Args:
            commit_hash: TempleDB commit hash OR git SHA1

        Returns:
            dulwich Commit object or None if not found
        """
        # Check if this is already a git SHA1 in cache
        if commit_hash in self._commit_cache:
            return self._commit_cache[commit_hash]

        # Check if we have a mapping from TempleDB hash to git hash
        if commit_hash in self._templedb_to_git_hash:
            git_hash = self._templedb_to_git_hash[commit_hash]
            if git_hash in self._commit_cache:
                return self._commit_cache[git_hash]

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

        # Create git Commit object using private attributes
        commit = Commit()

        # Parse timestamp - TempleDB stores as ISO8601 string
        import time
        from datetime import datetime
        dt = datetime.fromisoformat(commit_row['commit_timestamp'])
        timestamp = int(dt.timestamp())
        timezone = 0  # UTC

        # Set commit attributes (use private _ attributes for dulwich)
        commit._message = commit_row['commit_message'].encode('utf-8')
        commit._author = commit_row['author'].encode('utf-8')
        commit._committer = commit_row['author'].encode('utf-8')
        commit._author_time = timestamp
        commit._commit_time = timestamp
        commit._author_timezone = timezone
        commit._commit_timezone = timezone
        commit._author_timezone_neg_utc = False
        commit._commit_timezone_neg_utc = False

        # Get tree for this commit
        tree = self.get_tree_for_commit(commit_hash)
        if tree:
            commit._tree = tree.id
        else:
            # Tree is required - create an empty tree if none exists
            logger.warning(f"No tree found for commit {commit_hash}, using empty tree")
            empty_tree = Tree()
            commit._tree = empty_tree.id

        # Set parent commits (empty for root commits)
        # TODO: Track parent relationships in TempleDB for proper commit graph
        commit._parents = []

        # Cache by actual git SHA1 (commit.id) not TempleDB hash
        git_hash = commit.id.decode()
        self._commit_cache[git_hash] = commit
        # Store mapping from TempleDB hash to git hash
        self._templedb_to_git_hash[commit_hash] = git_hash

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
