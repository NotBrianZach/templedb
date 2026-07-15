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

import calendar
import errno
import hashlib
import logging
import os
import queue
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

_CACHE_TTL = 5.0  # seconds before tree cache expires


def _get_db_path():
    """Get database path, same logic as db_utils."""
    if 'TEMPLEDB_PATH' in os.environ:
        return os.environ['TEMPLEDB_PATH']
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        return f'/home/{sudo_user}/.local/share/templedb/templedb.sqlite'
    return os.path.expanduser("~/.local/share/templedb/templedb.sqlite")


def _parse_db_datetime(s):
    """Parse SQLite datetime string to Unix timestamp."""
    if not s:
        return 0.0
    try:
        return calendar.timegm(time.strptime(s, "%Y-%m-%d %H:%M:%S"))
    except (ValueError, TypeError):
        return 0.0


class TempleFS(Operations):
    """FUSE filesystem backed by TempleDB's SQLite database."""

    def __init__(self, db_path=None, readonly=False, pool_size=8):
        self.db_path = db_path or _get_db_path()
        self.readonly = readonly
        self.uid = os.getuid()
        self.gid = os.getgid()
        # Connection pool with bounded size
        self._pool = queue.Queue(maxsize=pool_size)
        self._pool_size = pool_size
        self._pool_created = 0
        self._pool_lock = threading.Lock()
        # Per-project directory tree cache
        self._tree_cache = {}
        self._tree_lock = threading.Lock()

    def _make_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0, isolation_level=None,
                               check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _conn(self) -> sqlite3.Connection:
        """Borrow a connection from the pool. Must be returned via _return_conn."""
        try:
            return self._pool.get_nowait()
        except queue.Empty:
            with self._pool_lock:
                if self._pool_created < self._pool_size:
                    self._pool_created += 1
                    return self._make_conn()
            # Pool exhausted, block until one is returned
            return self._pool.get(timeout=30.0)

    def _return_conn(self, conn: sqlite3.Connection):
        """Return a connection to the pool."""
        try:
            self._pool.put_nowait(conn)
        except queue.Full:
            conn.close()

    class _BorrowedConn:
        """Context manager for borrowing a pooled connection."""
        def __init__(self, fs):
            self._fs = fs
            self._conn = None
        def __enter__(self):
            self._conn = self._fs._conn()
            return self._conn
        def __exit__(self, *exc):
            if self._conn is not None:
                self._fs._return_conn(self._conn)
                self._conn = None

    def _borrow(self):
        return self._BorrowedConn(self)

    def destroy(self, path):
        """Called on unmount — close all pooled connections."""
        while not self._pool.empty():
            try:
                self._pool.get_nowait().close()
            except queue.Empty:
                break

    # ── Directory tree cache ─────────────────────────────────────────────

    def _get_tree(self, conn, project_id):
        """Get or build the cached file/directory tree for a project.

        Returns {"files": {path: {"size": int, "mtime": float}},
                 "dirs": set(path), "children": {dir_path: set(name)},
                 "expires": float}
        """
        with self._tree_lock:
            cached = self._tree_cache.get(project_id)
            if cached and time.time() < cached["expires"]:
                return cached

        rows = conn.execute(
            "SELECT pf.file_path, cb.file_size_bytes, "
            "COALESCE(fc.updated_at, pf.last_modified) as mtime "
            "FROM project_files pf "
            "JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1 "
            "JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash "
            "WHERE pf.project_id = ? AND pf.status = 'active'",
            (project_id,)
        ).fetchall()

        files = {}
        dirs = set()
        children = {}  # dir_path -> set of immediate child names

        for row in rows:
            fp = row["file_path"]
            mtime = _parse_db_datetime(row["mtime"])
            files[fp] = {"size": row["file_size_bytes"], "mtime": mtime}

            parts = fp.split("/")
            for i in range(len(parts)):
                parent = "/".join(parts[:i]) if i > 0 else ""
                child = parts[i]
                if parent not in children:
                    children[parent] = set()
                children[parent].add(child)
                if i > 0:
                    dirs.add(parent)

        tree = {"files": files, "dirs": dirs, "children": children,
                "expires": time.time() + _CACHE_TTL}
        with self._tree_lock:
            self._tree_cache[project_id] = tree
        return tree

    def _invalidate_tree(self, project_id):
        """Invalidate cached tree for a project after a mutation."""
        with self._tree_lock:
            self._tree_cache.pop(project_id, None)

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

    def _get_project(self, conn, slug):
        return conn.execute(
            "SELECT id, slug FROM projects WHERE slug = ?", (slug,)
        ).fetchone()

    def _get_file(self, conn, project_id, file_path):
        return conn.execute(
            "SELECT pf.id, pf.file_path, fc.content_hash, cb.content_text, "
            "cb.content_blob, cb.file_size_bytes, cb.content_type "
            "FROM project_files pf "
            "JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1 "
            "JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash "
            "WHERE pf.project_id = ? AND pf.file_path = ?",
            (project_id, file_path)
        ).fetchone()

    def _get_file_content(self, conn, project_id, file_path) -> bytes:
        row = self._get_file(conn, project_id, file_path)
        if not row:
            return None
        if row["content_text"] is not None:
            return row["content_text"].encode("utf-8")
        elif row["content_blob"] is not None:
            return bytes(row["content_blob"])
        return b""

    def _list_projects(self, conn):
        return conn.execute(
            "SELECT slug FROM projects ORDER BY slug"
        ).fetchall()

    # ── FUSE Operations ───────────────────────────────────────────────────

    def getattr(self, path, fh=None):
        slug, file_path = self._parse_path(path)

        # Root directory
        if slug is None:
            return self._dir_stat()

        with self._borrow() as conn:
            project = self._get_project(conn, slug)
            if not project:
                raise FuseOSError(errno.ENOENT)

            # Project root directory
            if file_path is None:
                return self._dir_stat()

            tree = self._get_tree(conn, project["id"])

            # Check if it's a file
            finfo = tree["files"].get(file_path)
            if finfo:
                size = finfo["size"]
                mtime = finfo["mtime"]
                # Check write buffer for modified size
                with _FD_LOCK:
                    for buf in _WRITE_BUFFERS.values():
                        if buf["path"] == path:
                            size = len(buf["data"])
                            break
                return self._file_stat(size, mtime)

            # Check if it's a directory
            if file_path in tree["dirs"]:
                return self._dir_stat()

        raise FuseOSError(errno.ENOENT)

    def readdir(self, path, fh):
        yield "."
        yield ".."

        slug, file_path = self._parse_path(path)

        if slug is None:
            # Root: list projects
            with self._borrow() as conn:
                for row in self._list_projects(conn):
                    yield row["slug"]
            return

        with self._borrow() as conn:
            project = self._get_project(conn, slug)
            if not project:
                return

            tree = self._get_tree(conn, project["id"])
            dir_key = file_path or ""
            for entry in sorted(tree["children"].get(dir_key, ())):
                yield entry

    def read(self, path, size, offset, fh):
        # Check write buffer first
        with _FD_LOCK:
            buf = _WRITE_BUFFERS.get(fh)
        if buf is not None:
            data = bytes(buf["data"])
            return data[offset:offset + size]

        slug, file_path = self._parse_path(path)
        if not slug or not file_path:
            raise FuseOSError(errno.EISDIR)

        with self._borrow() as conn:
            project = self._get_project(conn, slug)
            if not project:
                raise FuseOSError(errno.ENOENT)

            content = self._get_file_content(conn, project["id"], file_path)
            if content is None:
                raise FuseOSError(errno.ENOENT)

            return content[offset:offset + size]

    def open(self, path, flags):
        global _NEXT_FD
        slug, file_path = self._parse_path(path)
        if not slug or not file_path:
            raise FuseOSError(errno.EISDIR)

        with self._borrow() as conn:
            project = self._get_project(conn, slug)
            if not project:
                raise FuseOSError(errno.ENOENT)

            content = self._get_file_content(conn, project["id"], file_path)
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
            with self._borrow() as conn:
                project = self._get_project(conn, slug)
                content = self._get_file_content(conn, project["id"], file_path) or b""
            # Find existing buffer for this path
            with _FD_LOCK:
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
            logger.error(f"FUSE DATA LOSS: failed to write {path} to DB: {e}")
            print(f"FUSE DATA LOSS: failed to write {path} to DB: {e}", file=sys.stderr)

        return 0

    def create(self, path, mode, fi=None):
        """Create a new file."""
        global _NEXT_FD
        if self.readonly:
            raise FuseOSError(errno.EROFS)

        slug, file_path = self._parse_path(path)
        if not slug or not file_path:
            raise FuseOSError(errno.EACCES)

        with self._borrow() as conn:
            project = self._get_project(conn, slug)
            if not project:
                raise FuseOSError(errno.ENOENT)

            # Create empty file in DB
            self._create_file(conn, project["id"], slug, file_path, b"")
            self._invalidate_tree(project["id"])

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

        with self._borrow() as conn:
            project = self._get_project(conn, slug)
            if not project:
                raise FuseOSError(errno.ENOENT)

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
            self._auto_stage(conn, project["id"], row["id"], "deleted")
            self._invalidate_tree(project["id"])

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

        with self._borrow() as conn:
            project = self._get_project(conn, old_slug)
            if not project:
                raise FuseOSError(errno.ENOENT)

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
            self._invalidate_tree(project["id"])

    # ── Stat helpers ──────────────────────────────────────────────────────

    def _dir_stat(self):
        now = time.time()
        return {
            'st_mode': stat.S_IFDIR | 0o755,
            'st_nlink': 2,
            'st_uid': self.uid,
            'st_gid': self.gid,
            'st_size': 4096,
            'st_atime': now,
            'st_mtime': now,
            'st_ctime': now,
        }

    def _file_stat(self, size, mtime=0.0):
        now = time.time()
        if not mtime:
            mtime = now
        return {
            'st_mode': stat.S_IFREG | (0o444 if self.readonly else 0o644),
            'st_nlink': 1,
            'st_uid': self.uid,
            'st_gid': self.gid,
            'st_size': size,
            'st_atime': now,
            'st_mtime': mtime,
            'st_ctime': mtime,
        }

    # ── Write-back to DB ──────────────────────────────────────────────────

    def _write_file(self, slug, file_path, content: bytes):
        """Write file content back to the database."""
        with self._borrow() as conn:
            project = self._get_project(conn, slug)
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
                self._create_file(conn, project["id"], slug, file_path, content)
                self._invalidate_tree(project["id"])
                return

            file_id = file_row["id"]

            # Update file_contents: upsert current version
            line_count = text.count('\n') + 1 if (content_type == "text" and text) else 0
            conn.execute("""
                INSERT INTO file_contents (file_id, content_hash, file_size_bytes, line_count, is_current)
                VALUES (?, ?, ?, ?, 1)
                ON CONFLICT(file_id, is_current) DO UPDATE SET
                    content_hash = excluded.content_hash,
                    file_size_bytes = excluded.file_size_bytes,
                    line_count = excluded.line_count,
                    updated_at = datetime('now')
            """, (file_id, content_hash, len(content), line_count))

            # Auto-stage for VCS
            self._auto_stage(conn, project["id"], file_id, "modified")
            self._invalidate_tree(project["id"])
            logger.debug(f"FUSE write: {slug}/{file_path} ({len(content)} bytes, hash={content_hash[:12]})")

    def _create_file(self, conn, project_id, slug, file_path, content: bytes):
        """Create a new file in the database."""
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

        self._auto_stage(conn, project_id, file_id, "added")
        conn.execute("COMMIT")

    def _auto_stage(self, conn, project_id, file_id, change_state):
        """Auto-stage a file change in vcs_working_state."""
        try:
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
