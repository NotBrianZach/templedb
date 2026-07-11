#!/usr/bin/env python3
"""
TempleDB FUSE Filesystem — mount the database as a filesystem.

Mount point layout:
    <mountpoint>/
        <project_slug>/
            <file_path>           # from project_files + content_blobs

Reads come from content_blobs (content-addressable store).
Writes go back to content_blobs + file_contents, and auto-stage
in vcs_working_state for the next commit.

Usage:
    templedb mount ~/temple
    templedb mount ~/temple --foreground
    templedb unmount ~/temple

Requires: fusepy (python3Packages.fusepy in nixpkgs)
"""

import errno
import hashlib
import logging
import os
import sqlite3
import stat
import sys
import threading
import time
from pathlib import Path

try:
    from fuse import FUSE, FuseOSError, Operations
except ImportError:
    # Try the alternate import path
    try:
        from fusepy import FUSE, FuseOSError, Operations
    except ImportError:
        print("Error: fusepy not installed.", file=sys.stderr)
        print("  Install with: pip install fusepy", file=sys.stderr)
        print("  Or in nix:    python3Packages.fusepy", file=sys.stderr)
        sys.exit(1)

logger = logging.getLogger(__name__)

# In-memory write buffer for open files
_WRITE_BUFFERS = {}  # fd -> {"path": str, "data": bytearray, "dirty": bool}
_NEXT_FD = 100
_FD_LOCK = threading.Lock()


def _get_db_path():
    """Get database path, same logic as db_utils."""
    if 'TEMPLEDB_PATH' in os.environ:
        return os.environ['TEMPLEDB_PATH']
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        return f'/home/{sudo_user}/.local/share/templedb/templedb.sqlite'
    return os.path.expanduser("~/.local/share/templedb/templedb.sqlite")


class TempleFS(Operations):
    """FUSE filesystem backed by TempleDB's SQLite database."""

    def __init__(self, db_path=None, readonly=False):
        self.db_path = db_path or _get_db_path()
        self.readonly = readonly
        self.uid = os.getuid()
        self.gid = os.getgid()
        self.now = time.time()
        # One connection per thread
        self._local = threading.local()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, 'conn'):
            conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
            conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn = conn
        return self._local.conn

    # ── Path parsing ──────────────────────────────────────────────────────

    def _parse_path(self, path: str):
        """Parse FUSE path into (project_slug, file_path) or (project_slug, None) or (None, None)."""
        path = path.lstrip("/")
        if not path:
            return (None, None)  # root
        parts = path.split("/", 1)
        slug = parts[0]
        file_path = parts[1] if len(parts) > 1 else None
        return (slug, file_path)

    def _get_project(self, slug):
        return self._conn().execute(
            "SELECT id, slug FROM projects WHERE slug = ?", (slug,)
        ).fetchone()

    def _get_file(self, project_id, file_path):
        return self._conn().execute(
            "SELECT pf.id, pf.file_path, fc.content_hash, cb.content_text, "
            "cb.content_blob, cb.file_size_bytes, cb.content_type "
            "FROM project_files pf "
            "JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1 "
            "JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash "
            "WHERE pf.project_id = ? AND pf.file_path = ?",
            (project_id, file_path)
        ).fetchone()

    def _get_file_content(self, project_id, file_path) -> bytes:
        row = self._get_file(project_id, file_path)
        if not row:
            return None
        if row["content_text"] is not None:
            return row["content_text"].encode("utf-8")
        elif row["content_blob"] is not None:
            return bytes(row["content_blob"])
        return b""

    def _list_projects(self):
        return self._conn().execute(
            "SELECT slug FROM projects ORDER BY slug"
        ).fetchall()

    def _list_files(self, project_id):
        """List all files for a project with current content."""
        return self._conn().execute(
            "SELECT pf.file_path, cb.file_size_bytes, cb.content_type, pf.last_modified "
            "FROM project_files pf "
            "JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1 "
            "JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash "
            "WHERE pf.project_id = ? AND pf.status = 'active' "
            "ORDER BY pf.file_path",
            (project_id,)
        ).fetchall()

    def _list_dir_entries(self, project_id, dir_path):
        """List immediate children of a directory path."""
        prefix = (dir_path + "/") if dir_path else ""
        prefix_len = len(prefix)

        rows = self._conn().execute(
            "SELECT pf.file_path FROM project_files pf "
            "JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1 "
            "WHERE pf.project_id = ? AND pf.status = 'active' "
            "AND pf.file_path LIKE ? || '%'",
            (project_id, prefix)
        ).fetchall()

        entries = set()
        for row in rows:
            remainder = row["file_path"][prefix_len:]
            if not remainder:
                continue
            # First component after prefix
            first = remainder.split("/")[0]
            entries.add(first)
        return sorted(entries)

    def _is_dir(self, project_id, dir_path):
        """Check if dir_path is a directory (has files beneath it)."""
        prefix = dir_path + "/"
        row = self._conn().execute(
            "SELECT 1 FROM project_files pf "
            "JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1 "
            "WHERE pf.project_id = ? AND pf.status = 'active' "
            "AND pf.file_path LIKE ? || '%' LIMIT 1",
            (project_id, prefix)
        ).fetchone()
        return row is not None

    # ── FUSE Operations ───────────────────────────────────────────────────

    def getattr(self, path, fh=None):
        slug, file_path = self._parse_path(path)

        # Root directory
        if slug is None:
            return self._dir_stat()

        project = self._get_project(slug)
        if not project:
            raise FuseOSError(errno.ENOENT)

        # Project root directory
        if file_path is None:
            return self._dir_stat()

        # Check if it's a file
        row = self._get_file(project["id"], file_path)
        if row:
            size = row["file_size_bytes"]
            # Check write buffer for modified size
            for buf in _WRITE_BUFFERS.values():
                if buf["path"] == path:
                    size = len(buf["data"])
                    break
            return self._file_stat(size)

        # Check if it's a directory (has children)
        if self._is_dir(project["id"], file_path):
            return self._dir_stat()

        raise FuseOSError(errno.ENOENT)

    def readdir(self, path, fh):
        yield "."
        yield ".."

        slug, file_path = self._parse_path(path)

        if slug is None:
            # Root: list projects
            for row in self._list_projects():
                yield row["slug"]
            return

        project = self._get_project(slug)
        if not project:
            return

        # List directory entries
        entries = self._list_dir_entries(project["id"], file_path)
        for entry in entries:
            yield entry

    def read(self, path, size, offset, fh):
        # Check write buffer first
        if fh in _WRITE_BUFFERS:
            data = bytes(_WRITE_BUFFERS[fh]["data"])
            return data[offset:offset + size]

        slug, file_path = self._parse_path(path)
        if not slug or not file_path:
            raise FuseOSError(errno.EISDIR)

        project = self._get_project(slug)
        if not project:
            raise FuseOSError(errno.ENOENT)

        content = self._get_file_content(project["id"], file_path)
        if content is None:
            raise FuseOSError(errno.ENOENT)

        return content[offset:offset + size]

    def open(self, path, flags):
        global _NEXT_FD
        slug, file_path = self._parse_path(path)
        if not slug or not file_path:
            raise FuseOSError(errno.EISDIR)

        project = self._get_project(slug)
        if not project:
            raise FuseOSError(errno.ENOENT)

        content = self._get_file_content(project["id"], file_path)
        if content is None:
            raise FuseOSError(errno.ENOENT)

        with _FD_LOCK:
            fd = _NEXT_FD
            _NEXT_FD += 1
            _WRITE_BUFFERS[fd] = {
                "path": path,
                "data": bytearray(content),
                "dirty": False,
            }
        return fd

    def write(self, path, data, offset, fh):
        if self.readonly:
            raise FuseOSError(errno.EROFS)

        if fh not in _WRITE_BUFFERS:
            raise FuseOSError(errno.EBADF)

        buf = _WRITE_BUFFERS[fh]
        end = offset + len(data)
        if end > len(buf["data"]):
            buf["data"].extend(b'\0' * (end - len(buf["data"])))
        buf["data"][offset:end] = data
        buf["dirty"] = True
        return len(data)

    def truncate(self, path, length, fh=None):
        if self.readonly:
            raise FuseOSError(errno.EROFS)

        # Find or create buffer
        if fh and fh in _WRITE_BUFFERS:
            buf = _WRITE_BUFFERS[fh]
        else:
            # Load content into a temporary buffer
            slug, file_path = self._parse_path(path)
            project = self._get_project(slug)
            content = self._get_file_content(project["id"], file_path) or b""
            # Find existing buffer for this path
            for existing_fh, existing_buf in _WRITE_BUFFERS.items():
                if existing_buf["path"] == path:
                    buf = existing_buf
                    break
            else:
                raise FuseOSError(errno.EBADF)

        if length < len(buf["data"]):
            buf["data"] = buf["data"][:length]
        else:
            buf["data"].extend(b'\0' * (length - len(buf["data"])))
        buf["dirty"] = True

    def release(self, path, fh):
        """Called when file is closed. Flush dirty data to DB."""
        if fh not in _WRITE_BUFFERS:
            return 0

        buf = _WRITE_BUFFERS.pop(fh)
        if not buf["dirty"]:
            return 0

        # Write back to database
        slug, file_path = self._parse_path(path)
        if not slug or not file_path:
            return 0

        try:
            self._write_file(slug, file_path, bytes(buf["data"]))
        except Exception as e:
            logger.error(f"Failed to write {path} to DB: {e}")

        return 0

    def create(self, path, mode, fi=None):
        """Create a new file."""
        global _NEXT_FD
        if self.readonly:
            raise FuseOSError(errno.EROFS)

        slug, file_path = self._parse_path(path)
        if not slug or not file_path:
            raise FuseOSError(errno.EACCES)

        project = self._get_project(slug)
        if not project:
            raise FuseOSError(errno.ENOENT)

        # Create empty file in DB
        self._create_file(project["id"], slug, file_path, b"")

        with _FD_LOCK:
            fd = _NEXT_FD
            _NEXT_FD += 1
            _WRITE_BUFFERS[fd] = {
                "path": path,
                "data": bytearray(),
                "dirty": False,
            }
        return fd

    def unlink(self, path):
        """Delete a file."""
        if self.readonly:
            raise FuseOSError(errno.EROFS)

        slug, file_path = self._parse_path(path)
        if not slug or not file_path:
            raise FuseOSError(errno.EACCES)

        project = self._get_project(slug)
        if not project:
            raise FuseOSError(errno.ENOENT)

        conn = self._conn()
        row = conn.execute(
            "SELECT id FROM project_files WHERE project_id = ? AND file_path = ?",
            (project["id"], file_path)
        ).fetchone()
        if not row:
            raise FuseOSError(errno.ENOENT)

        conn.execute(
            "UPDATE project_files SET status = 'deleted' WHERE id = ?",
            (row["id"],)
        )
        self._auto_stage(project["id"], row["id"], "deleted")

    def mkdir(self, path, mode):
        """Directories are implicit in TempleDB (derived from file paths). No-op."""
        pass

    def rmdir(self, path):
        """Directories are implicit. Remove all files under this path."""
        if self.readonly:
            raise FuseOSError(errno.EROFS)
        # No-op: directories don't exist as entries
        pass

    def rename(self, old, new):
        """Rename/move a file."""
        if self.readonly:
            raise FuseOSError(errno.EROFS)

        old_slug, old_path = self._parse_path(old)
        new_slug, new_path = self._parse_path(new)

        if old_slug != new_slug:
            raise FuseOSError(errno.EXDEV)  # cross-project move not supported

        if not old_path or not new_path:
            raise FuseOSError(errno.EACCES)

        project = self._get_project(old_slug)
        if not project:
            raise FuseOSError(errno.ENOENT)

        conn = self._conn()
        row = conn.execute(
            "SELECT id FROM project_files WHERE project_id = ? AND file_path = ?",
            (project["id"], old_path)
        ).fetchone()
        if not row:
            raise FuseOSError(errno.ENOENT)

        new_name = new_path.rsplit("/", 1)[-1]
        conn.execute(
            "UPDATE project_files SET file_path = ?, file_name = ? WHERE id = ?",
            (new_path, new_name, row["id"])
        )

    # ── Stat helpers ──────────────────────────────────────────────────────

    def _dir_stat(self):
        return {
            'st_mode': stat.S_IFDIR | 0o755,
            'st_nlink': 2,
            'st_uid': self.uid,
            'st_gid': self.gid,
            'st_size': 4096,
            'st_atime': self.now,
            'st_mtime': self.now,
            'st_ctime': self.now,
        }

    def _file_stat(self, size):
        return {
            'st_mode': stat.S_IFREG | (0o444 if self.readonly else 0o644),
            'st_nlink': 1,
            'st_uid': self.uid,
            'st_gid': self.gid,
            'st_size': size,
            'st_atime': self.now,
            'st_mtime': self.now,
            'st_ctime': self.now,
        }

    # ── Write-back to DB ──────────────────────────────────────────────────

    def _write_file(self, slug, file_path, content: bytes):
        """Write file content back to the database."""
        conn = self._conn()
        project = self._get_project(slug)
        if not project:
            return

        # Compute hash
        content_hash = hashlib.sha256(content).hexdigest()

        # Try to decode as text
        try:
            text = content.decode("utf-8")
            content_type = "text"
        except UnicodeDecodeError:
            text = None
            content_type = "binary"

        # Upsert content blob
        conn.execute("""
            INSERT OR IGNORE INTO content_blobs
            (hash_sha256, content_text, content_blob, content_type, encoding,
             file_size_bytes, reference_count)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (
            content_hash,
            text if content_type == "text" else None,
            content if content_type == "binary" else None,
            content_type, "utf-8",
            len(content),
        ))

        # Get file_id
        file_row = conn.execute(
            "SELECT id FROM project_files WHERE project_id = ? AND file_path = ?",
            (project["id"], file_path)
        ).fetchone()

        if not file_row:
            # File doesn't exist yet, create it
            self._create_file(project["id"], slug, file_path, content)
            return

        file_id = file_row["id"]

        # Update file_contents: replace current version in-place
        line_count = text.count('\n') + 1 if (content_type == "text" and text) else 0
        existing = conn.execute(
            "SELECT id FROM file_contents WHERE file_id = ? AND is_current = 1",
            (file_id,)
        ).fetchone()
        if existing:
            conn.execute("""
                UPDATE file_contents
                SET content_hash = ?, file_size_bytes = ?, line_count = ?, updated_at = datetime('now')
                WHERE id = ?
            """, (content_hash, len(content), line_count, existing["id"]))
        else:
            conn.execute("""
                INSERT INTO file_contents (file_id, content_hash, file_size_bytes, line_count, is_current)
                VALUES (?, ?, ?, ?, 1)
            """, (file_id, content_hash, len(content), line_count))

        # Auto-stage for VCS
        self._auto_stage(project["id"], file_id, "modified")
        logger.debug(f"FUSE write: {slug}/{file_path} ({len(content)} bytes, hash={content_hash[:12]})")

    def _create_file(self, project_id, slug, file_path, content: bytes):
        """Create a new file in the database."""
        conn = self._conn()

        # Compute hash
        content_hash = hashlib.sha256(content).hexdigest()
        try:
            text = content.decode("utf-8")
            content_type = "text"
        except UnicodeDecodeError:
            text = None
            content_type = "binary"

        # Content blob
        conn.execute("BEGIN")
        conn.execute("""
            INSERT OR IGNORE INTO content_blobs
            (hash_sha256, content_text, content_blob, content_type, encoding,
             file_size_bytes, reference_count)
            VALUES (?, ?, ?, ?, ?, ?, 1)
        """, (
            content_hash,
            text if content_type == "text" else None,
            content if content_type == "binary" else None,
            content_type, "utf-8",
            len(content),
        ))

        # Map file extension to file_type_id
        # file_types uses type_name (e.g. 'python_script'), not extension
        ext = Path(file_path).suffix.lstrip(".").lower()
        ext_to_type = {
            "py": "python_script", "js": "javascript", "ts": "typescript",
            "nix": "nix", "sql": "sql_file", "sh": "shell_script",
            "md": "markdown", "json": "json", "yaml": "yaml", "yml": "yaml",
            "toml": "toml", "html": "html", "css": "css", "txt": "text_file",
        }
        type_name = ext_to_type.get(ext)
        ft_row = None
        if type_name:
            ft_row = conn.execute(
                "SELECT id FROM file_types WHERE type_name = ? LIMIT 1", (type_name,)
            ).fetchone()
        if not ft_row:
            # Fallback: get any file type
            ft_row = conn.execute("SELECT id FROM file_types LIMIT 1").fetchone()
        file_type_id = ft_row["id"] if ft_row else 1

        file_name = file_path.rsplit("/", 1)[-1]

        # Insert project_files
        cursor = conn.execute("""
            INSERT INTO project_files (project_id, file_type_id, file_path, file_name,
                                       status, lines_of_code, last_modified)
            VALUES (?, ?, ?, ?, 'active', ?, datetime('now'))
        """, (project_id, file_type_id, file_path, file_name,
              text.count('\n') + 1 if text else 0))
        file_id = cursor.lastrowid

        # file_contents
        line_count = text.count('\n') + 1 if (content_type == "text" and text) else 0
        conn.execute("""
            INSERT INTO file_contents (file_id, content_hash, file_size_bytes, line_count, is_current)
            VALUES (?, ?, ?, ?, 1)
        """, (file_id, content_hash, len(content), line_count))

        conn.execute("COMMIT")
        self._auto_stage(project_id, file_id, "added")

    def _auto_stage(self, project_id, file_id, change_state):
        """Auto-stage a file change in vcs_working_state."""
        try:
            conn = self._conn()
            # Get active branch (falls back to default)
            branch = conn.execute(
                "SELECT active_branch_id as id FROM projects WHERE id = ? AND active_branch_id IS NOT NULL",
                (project_id,)
            ).fetchone()
            if not branch:
                branch = conn.execute(
                    "SELECT id FROM vcs_branches WHERE project_id = ? AND is_default = 1 LIMIT 1",
                    (project_id,)
                ).fetchone()
            if not branch:
                return

            # Upsert working state
            conn.execute("""
                INSERT INTO vcs_working_state (project_id, branch_id, file_id, state, staged, last_modified)
                VALUES (?, ?, ?, ?, 1, datetime('now'))
                ON CONFLICT (project_id, branch_id, file_id)
                DO UPDATE SET state = excluded.state, staged = 1, last_modified = datetime('now')
            """, (project_id, branch["id"], file_id, change_state))
        except Exception as e:
            logger.debug(f"Auto-stage failed (non-fatal): {e}")

    # ── Unsupported operations (graceful) ─────────────────────────────────

    def chmod(self, path, mode):
        pass  # Permissions managed by DB, not filesystem

    def chown(self, path, uid, gid):
        pass

    def utimens(self, path, times=None):
        pass

    def statfs(self, path):
        """Return filesystem statistics."""
        try:
            db_size = os.path.getsize(self.db_path)
        except Exception:
            db_size = 0
        return {
            'f_bsize': 4096,
            'f_frsize': 4096,
            'f_blocks': max(db_size // 4096, 1024),
            'f_bfree': 1024 * 1024,  # plenty of "free" space
            'f_bavail': 1024 * 1024,
            'f_files': 65536,
            'f_ffree': 32768,
            'f_favail': 32768,
            'f_namemax': 255,
        }


def mount(mountpoint: str, db_path: str = None, foreground: bool = False,
          readonly: bool = False, debug: bool = False):
    """Mount TempleDB as a FUSE filesystem."""
    mountpoint = os.path.abspath(mountpoint)
    os.makedirs(mountpoint, exist_ok=True)

    fs = TempleFS(db_path=db_path, readonly=readonly)

    print(f"TempleDB FUSE mount: {mountpoint}")
    print(f"  Database: {fs.db_path}")
    print(f"  Mode: {'read-only' if readonly else 'read-write'}")
    if not foreground:
        print(f"  Running in background (unmount with: fusermount -u {mountpoint})")

    FUSE(fs, mountpoint, foreground=foreground, nothreads=False,
         allow_other=False, nonempty=True, debug=debug)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Mount TempleDB as FUSE filesystem")
    parser.add_argument("mountpoint", help="Mount point directory")
    parser.add_argument("--db-path", help="Database path")
    parser.add_argument("--foreground", "-f", action="store_true")
    parser.add_argument("--readonly", "-r", action="store_true")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    mount(args.mountpoint, args.db_path, args.foreground, args.readonly, args.debug)
