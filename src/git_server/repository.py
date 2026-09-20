"""
TempleDB Repository - Git repository interface backed by database

Implements dulwich's repository interface to serve from SQLite.
"""

from typing import Dict, List, Optional
from dulwich.repo import BaseRepo
from dulwich.objects import ShaFile
from .object_mapper import ObjectMapper
from logger import get_logger

logger = get_logger(__name__)


class TempleDBRepo(BaseRepo):
    """
    Git repository backed by TempleDB database

    Implements dulwich's BaseRepo interface to work with git clients.
    """

    def __init__(self, project_slug: str):
        from dulwich.objects import DEFAULT_OBJECT_FORMAT

        self.project_slug = project_slug
        self.mapper = ObjectMapper(project_slug)

        # Initialize bare repo (no working directory, SHA1 object format)
        super().__init__(None, None, object_format=DEFAULT_OBJECT_FORMAT)

    def get_refs(self) -> Dict[bytes, bytes]:
        """Get all refs for this repository"""
        refs = self.mapper.get_refs()

        # Add HEAD symbolic ref pointing to main or first available branch
        if b'refs/heads/main' in refs:
            refs[b'HEAD'] = refs[b'refs/heads/main']
        elif refs:
            # Point to first available branch
            first_branch = next(iter(refs.items()))
            refs[b'HEAD'] = first_branch[1]

        return refs

    def get_peeled(self, ref: bytes) -> bytes:
        """Get the peeled value of a ref (resolve tags to commits)"""
        # For now, we don't support tags, so just return the ref value
        return self.get_refs().get(ref, b'')

    def set_symbolic_ref(self, name: bytes, target: bytes):
        """Set a symbolic ref (like HEAD -> refs/heads/main)"""
        # TODO: Store symbolic refs in database
        pass

    def get_named_file(self, path: str):
        """Get a file from the repository by path"""
        # Not needed for smart HTTP protocol
        raise NotImplementedError()

    def __getitem__(self, name: bytes) -> ShaFile:
        """
        Get a git object by its hash

        This is the main interface for retrieving objects.
        """
        sha_hex = name.decode() if isinstance(name, bytes) else name

        # Try to get as commit
        commit = self.mapper.get_commit(sha_hex)
        if commit:
            return commit

        # Try to get as blob from cache
        blob = self.mapper._blob_cache.get(sha_hex)
        if blob:
            return blob

        # Try to get as tree from cache
        tree = self.mapper._tree_cache.get(f"tree:{sha_hex}")
        if tree:
            return tree

        logger.warning(f"Object not found: {sha_hex}")
        raise KeyError(name)

    def __contains__(self, name: bytes) -> bool:
        """Check if an object exists"""
        try:
            self[name]
            return True
        except KeyError:
            return False

    def get_all_commits(self) -> List[bytes]:
        """Get actual git SHA1 hashes of all valid commits (not TempleDB hashes)"""
        templedb_commits = self.mapper.db.execute("""
            SELECT commit_hash FROM vcs_commits
            WHERE project_id = ? AND LENGTH(commit_hash) = 40
            ORDER BY commit_timestamp DESC
        """, (self.mapper.project_id,)).fetchall()

        # Convert TempleDB hashes to actual git SHA1 hashes
        git_hashes = []
        for c in templedb_commits:
            commit_obj = self.mapper.get_commit(c['commit_hash'])
            if commit_obj:
                git_hashes.append(commit_obj.id)

        return git_hashes

    def close(self):
        """Close the repository"""
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
