#!/usr/bin/env python3
"""
TempleDB MCP Daemon — shared MCP server + hook socket.

One persistent process that serves:
1. MCP over HTTP/SSE on port 8421 (multiple Claude instances share this)
2. Hook queries over Unix socket at /tmp/templedb-hook.sock (instant responses)

Each component opens its own DB connection with a bounded life (WAL mode,
busy_timeout=30s) — see MCPDaemon. A third thread checkpoints the WAL
periodically; see WalMaintainer.

Usage:
    templedb ai mcp daemon          # start daemon (foreground)
    templedb ai mcp daemon --port 8421  # custom port
"""

import json
import logging
import os
import signal
import socket
import sqlite3
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent))

from config import DB_PATH
from logger import get_logger

logger = get_logger(__name__)

HOOK_SOCKET_PATH = "/tmp/templedb-hook.sock"
DEFAULT_PORT = 8421


# ============================================================================
# Hook Engine — DB-backed project/path lookups, cached in memory
# ============================================================================

class HookEngine:
    """Answers hook queries using a shared DB connection with in-memory cache."""

    GIT_REDIRECTS = {
        "git status": "templedb vcs status <project> --refresh",
        "git add": "templedb vcs add -p <project>",
        "git commit": "templedb vcs commit -p <project> -m <message>",
        "git push": "templedb publish run <project> -m <message>",
        "git log": "templedb vcs log <project>",
        "git diff": "templedb vcs diff <project>",
        "git branch": "templedb vcs branch <project>",
        "git checkout": "templedb vcs switch <project> <branch>",
        "git switch": "templedb vcs switch <project> <branch>",
        "git merge": "templedb vcs merge <project> <branch>",
    }

    SYSTEM_REDIRECTS = {
        "sudo nixos-rebuild switch": "templedb nixos system-switch system_config --yes",
        "sudo nixos-rebuild build": "templedb nixos rebuild system_config --dry-run",
        "sudo nixos-rebuild test": "templedb nixos rebuild system_config --yes",
        "sudo nixos-rebuild": "templedb nixos rebuild system_config --yes",
        "nixos-rebuild switch": "templedb nixos system-switch system_config --yes",
        "nixos-rebuild build": "templedb nixos rebuild system_config --dry-run",
        "nixos-rebuild test": "templedb nixos rebuild system_config --yes",
        "nixos-rebuild": "templedb nixos rebuild system_config --yes",
        "home-manager switch": "templedb nixos home-rebuild system_config",
        "home-manager build": "templedb nixos home-rebuild system_config",
    }

    def __init__(self, conn_factory):
        """conn_factory: callable returning a fresh, pragma-configured connection.

        A factory rather than a connection, because this engine lives as
        long as the daemon does. It was handed the daemon's single
        process-lifetime connection, and `_refresh_cache` below is
        reachable at runtime from the hook socket -- so every refresh
        opened a cursor on a connection nobody would ever close, which in
        WAL mode is how the -wal file grows without bound (a read
        transaction pins the checkpoint). The cache is two columns of one
        small table read a handful of times a day; owning a connection
        for that is all cost and no benefit.
        """
        self._conn_factory = conn_factory
        self._lock = threading.Lock()
        self._project_cache = {}  # repo_url -> slug
        self._slug_set = set()
        self._checkout_prefix = os.path.join(str(Path.home()), ".config", "templedb", "checkouts")
        self._refresh_cache()

    def _refresh_cache(self):
        """Reload project data from DB into memory.

        Opens and closes its own connection: see __init__ for why this
        engine does not hold one.
        """
        with self._lock:
            conn = None
            try:
                conn = self._conn_factory()
                cur = conn.cursor()
                try:
                    cur.execute(
                        "SELECT slug, repo_url FROM projects WHERE repo_url IS NOT NULL")
                    rows = cur.fetchall()
                finally:
                    # Finalize the statement explicitly rather than leaving
                    # it to refcounting -- the same fix db_utils made in
                    # _pooled_cursor and mcp_server made in _fresh_cursor.
                    cur.close()
                self._project_cache = {}
                self._slug_set = set()
                for row in rows:
                    slug, repo_url = row[0], row[1]
                    self._slug_set.add(slug)
                    if repo_url:
                        self._project_cache[repo_url] = slug
                logger.info(f"Hook cache refreshed: {len(self._project_cache)} projects")
            except Exception as e:
                logger.error(f"Cache refresh failed: {e}")
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

    def _is_templedb_project(self, cwd: str) -> bool:
        if cwd in self._project_cache:
            return True
        basename = os.path.basename(cwd)
        for repo_url in self._project_cache:
            if basename in repo_url:
                return True
        return False

    def _detect_slug(self, cwd: str) -> Optional[str]:
        if cwd in self._project_cache:
            return self._project_cache[cwd]
        basename = os.path.basename(cwd)
        if basename in self._slug_set:
            return basename
        for repo_url, slug in self._project_cache.items():
            if basename in repo_url:
                return slug
        return None

    def handle_bash_hook(self, command: str, cwd: str) -> Optional[Dict]:
        """Handle pre-tool bash hook. Returns block response or None to allow."""
        cmd = command.strip()

        for sys_cmd, templedb_cmd in self.SYSTEM_REDIRECTS.items():
            if cmd.startswith(sys_cmd):
                return {
                    "decision": "block",
                    "reason": f"Use templedb instead of raw system commands.\n"
                              f"  Instead of: {cmd}\n"
                              f"  Use:        {templedb_cmd}"
                }

        if not self._is_templedb_project(cwd):
            return None

        for git_cmd, templedb_cmd in self.GIT_REDIRECTS.items():
            if cmd.startswith(git_cmd):
                slug = self._detect_slug(cwd) or "<project>"
                suggestion = templedb_cmd.replace("<project>", slug)
                return {
                    "decision": "block",
                    "reason": f"Use templedb instead of git in TempleDB-managed projects.\n"
                              f"  Instead of: {cmd}\n"
                              f"  Use:        {suggestion}"
                }

        return None

    def handle_file_hook(self, file_path: str) -> Optional[Dict]:
        """Handle pre-tool edit/write hook. Returns block response or None to allow."""
        if not file_path:
            return None

        file_path = os.path.expanduser(file_path)

        blocked_prefixes = [self._checkout_prefix]
        for repo_url in self._project_cache:
            if os.path.isabs(repo_url):
                blocked_prefixes.append(repo_url)

        for prefix in blocked_prefixes:
            if not file_path.startswith(prefix):
                continue

            slug = None
            rel_path = None
            rest = file_path[len(prefix):].lstrip("/")

            if prefix == self._checkout_prefix:
                parts = rest.split("/", 1)
                slug = parts[0] if parts else None
                rel_path = parts[1] if len(parts) > 1 else rest
            else:
                slug = self._project_cache.get(prefix)
                rel_path = rest

            if slug:
                from cli.commands.edit import edit_workspace_path
                ws = edit_workspace_path(slug)
                hint = (
                    f"Open a writable workspace instead:\n"
                    f"    templedb edit {slug}\n"
                    f"then edit files under {ws}/ and commit with:\n"
                    f"    templedb commit {slug} {ws} -m \"...\"\n"
                )
            else:
                hint = (
                    "Use `templedb edit <slug>` to open a writable workspace, "
                    "or `templedb file set <slug> <path>` for a single-file edit.\n"
                )

            return {
                "decision": "block",
                "reason": (
                    f"Direct edits to the checkout/repo are read-only "
                    f"(materialized state — will be overwritten by publish).\n"
                    f"  Blocked: {file_path}\n"
                    f"{hint}"
                )
            }

        return None


# ============================================================================
# Unix Socket Server — serves hook queries (~1ms per call)
# ============================================================================

class HookSocketServer(threading.Thread):
    """Listens on a Unix socket for hook queries from Claude Code hooks."""

    def __init__(self, engine: HookEngine, socket_path: Optional[str] = None):
        """socket_path defaults to HOOK_SOCKET_PATH, resolved at call time.

        It used to be a default *argument*, which binds at def time and
        so ignored any later override of the module constant. run()
        below unlinks whatever is at the path before binding, so the
        practical effect was that a test or a smoke script could not
        point this anywhere else and would silently take over the live
        daemon's socket -- leaving the real daemon holding an unlinked
        inode and every Claude Code hook failing until it restarted.
        Done exactly that once; hence resolving late.
        """
        super().__init__(daemon=True)
        self.engine = engine
        self.socket_path = socket_path if socket_path is not None else HOOK_SOCKET_PATH
        self._running = False

    def run(self):
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(self.socket_path)
        os.chmod(self.socket_path, 0o600)
        sock.listen(8)
        sock.settimeout(1.0)
        self._running = True

        logger.info(f"Hook socket listening at {self.socket_path}")

        while self._running:
            try:
                conn, _ = sock.accept()
            except socket.timeout:
                continue
            except Exception:
                continue

            threading.Thread(target=self._handle_client, args=(conn,), daemon=True).start()

        sock.close()
        if os.path.exists(self.socket_path):
            os.unlink(self.socket_path)

    def _handle_client(self, conn: socket.socket):
        """Handle a single hook query.

        Protocol: client sends one JSON line, server responds with one JSON line.
        Request format:
            {"type": "bash", "command": "git status", "cwd": "/home/..."}
            {"type": "edit", "file_path": "/home/.../file.py"}
            {"type": "refresh"}
        """
        try:
            data = b""
            while True:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break

            line = data.decode("utf-8").strip()
            if not line:
                return

            request = json.loads(line)
            hook_type = request.get("type", "")

            if hook_type == "bash":
                result = self.engine.handle_bash_hook(
                    request.get("command", ""),
                    request.get("cwd", "")
                )
            elif hook_type in ("edit", "write"):
                result = self.engine.handle_file_hook(
                    request.get("file_path", "")
                )
            elif hook_type == "refresh":
                self.engine._refresh_cache()
                result = {"status": "ok", "projects": len(self.engine._project_cache)}
            else:
                result = None

            response = json.dumps(result) if result else "{}"
            conn.sendall((response + "\n").encode("utf-8"))

        except Exception as e:
            logger.debug(f"Hook client error: {e}")
        finally:
            conn.close()

    def stop(self):
        self._running = False


# ============================================================================
# MCP HTTP Handler — serves MCP protocol over HTTP/SSE
# ============================================================================

class MCPHTTPHandler(BaseHTTPRequestHandler):
    """HTTP handler for MCP JSON-RPC requests.

    Claude Code connects to http://localhost:8421/mcp via SSE,
    then sends JSON-RPC requests as POST bodies.
    """

    def log_message(self, format, *args):
        logger.debug(format % args)

    def do_POST(self):
        if self.path != "/mcp":
            self.send_error(404)
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            message = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        response = self.server.mcp_server.handle_message(message)

        response_body = json.dumps(response).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def do_GET(self):
        if self.path == "/health":
            body = json.dumps({"status": "ok"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/sse":
            self._handle_sse()
        else:
            self.send_error(404)

    def _handle_sse(self):
        """SSE transport — sends endpoint URL, then keeps connection alive."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        endpoint = f"http://localhost:{self.server.server_port}/mcp"
        self.wfile.write(f"event: endpoint\ndata: {endpoint}\n\n".encode())
        self.wfile.flush()

        try:
            while True:
                time.sleep(30)
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


class ThreadedHTTPServer(HTTPServer):
    """HTTP server that handles each request in a new thread."""
    allow_reuse_address = True

    def __init__(self, *args, mcp_server=None, **kwargs):
        self.mcp_server = mcp_server
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        thread = threading.Thread(target=self._handle_request_thread,
                                  args=(request, client_address), daemon=True)
        thread.start()

    def _handle_request_thread(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)


# ============================================================================
# WalMaintainer — periodic TRUNCATE checkpoint
# ============================================================================

# Interval between checkpoints. The point is to bound the -wal between
# write bursts, not to react quickly, and a TRUNCATE checkpoint takes a
# brief exclusive lock -- so this is deliberately infrequent.
WAL_CHECKPOINT_INTERVAL_SECONDS = 300

# Short, unlike the standard 30s: if a writer holds the lock, the right
# move is to give up and retry at the next interval rather than sit on
# the database waiting.
WAL_CHECKPOINT_BUSY_TIMEOUT_MS = 2000


class WalMaintainer(threading.Thread):
    """Checkpoint the WAL from the writer side, periodically.

    Cursor finalization and bounded connection lifetimes stop *this*
    process pinning a checkpoint. Neither helps when the holder is
    somebody else, and neither shrinks a -wal that has already grown:
    an automatic (PASSIVE) checkpoint never truncates the file, so a WAL
    that spikes once stays at its high-water mark until something runs a
    TRUNCATE. Historically nothing did, which is how this database
    reached 9.1 GB of -wal in 2026-09 and 4.0 GB in 2026-10.

    The daemon is the natural home for it: it is the only process always
    running, and a checkpoint has to come from a process with the
    database open.

    It reports rather than just acting. A checkpoint that cannot drain
    the log is the signature of a reader holding an old snapshot, and
    that is a bug in whoever holds it -- the one diagnostic that names
    the condition is the gap between `checkpointed` and `log`, which
    only a checkpoint returns. Logging it at WARNING keeps the condition
    visible instead of quietly papering over it; `doctor` still reports
    the file size independently.
    """

    def __init__(self, conn_factory, interval: int = WAL_CHECKPOINT_INTERVAL_SECONDS):
        super().__init__(daemon=True, name="wal-maintainer")
        self._conn_factory = conn_factory
        self._interval = interval
        self._stop = threading.Event()

    def stop(self):
        self._stop.set()

    def run(self):
        # Wait first: at startup the WAL has just been recovered by
        # whoever opened the database, and there is nothing to reclaim.
        while not self._stop.wait(self._interval):
            try:
                self.checkpoint_once()
            except Exception as e:
                logger.warning(f"WAL checkpoint failed: {e}")

    def checkpoint_once(self) -> Optional[tuple]:
        """Run one TRUNCATE checkpoint. Returns (busy, log, checkpointed)."""
        conn = self._conn_factory()
        try:
            conn.execute(f"PRAGMA busy_timeout={WAL_CHECKPOINT_BUSY_TIMEOUT_MS}")
            cur = conn.cursor()
            try:
                cur.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                row = cur.fetchone()
            finally:
                cur.close()
            if row is None:
                return None
            busy, log, checkpointed = row[0], row[1], row[2]
            if busy or checkpointed < log:
                logger.warning(
                    "WAL checkpoint incomplete: busy=%s, checkpointed %s of %s "
                    "frames. A reader is holding an old snapshot; the -wal "
                    "cannot shrink past it.", busy, checkpointed, log)
            else:
                logger.debug(
                    "WAL checkpoint: %s frames reclaimed", checkpointed)
            return (busy, log, checkpointed)
        finally:
            try:
                conn.close()
            except Exception:
                pass


# ============================================================================
# MCPDaemon — orchestrates everything
# ============================================================================

class MCPDaemon:
    """Shared MCP daemon: HTTP server + hook socket + WAL maintenance.

    Deliberately owns no process-lifetime DB connection. It is the
    longest-running process on this database, so any connection it held
    would be the one most able to pin a WAL checkpoint; components get a
    factory and open connections with a bounded life instead.
    """

    def __init__(self, port: int = DEFAULT_PORT,
                 hook_socket_path: Optional[str] = None):
        self.port = port
        # Overridable so a test or smoke run can bind its own socket:
        # HookSocketServer.run() unlinks the path before binding, so
        # anything that cannot be redirected takes over the live one.
        self.hook_socket_path = (
            hook_socket_path if hook_socket_path is not None else HOOK_SOCKET_PATH)
        self._mcp_server = None
        self._hook_engine = None
        self._hook_socket = None
        self._http_server = None
        self._wal_maintainer = None

    def new_db_connection(self) -> sqlite3.Connection:
        """Open a fresh connection with TempleDB's standard pragmas.

        This was an inline copy of the pragma list, and it had drifted:
        it was missing journal_size_limit, which is the pragma that
        bounds what a checkpoint leaves behind, plus temp_store,
        mmap_size and the cr-sqlite extension load (without which any
        write to a sync_* table fails with the opaque "no such function:
        crsql_internal_sync_bit"). mcp_server.py carries a comment about
        making exactly this fix for "the longest-lived connection in the
        system" -- this second copy, in the actual always-on daemon, was
        missed by it.
        """
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        from db_utils import apply_standard_pragmas
        apply_standard_pragmas(conn)
        return conn

    def run(self):
        """Start the daemon (blocking)."""
        # Import and create MCP server (reuse existing implementation)
        from mcp_server import MCPServer
        self._mcp_server = MCPServer()
        # No connection is injected here. It used to be handed this
        # daemon's process-lifetime connection, and that silently
        # disabled MCPServer's own WAL defence: _retire_connection_if_old
        # returns early unless _db_conn_opened_at is set, and assigning
        # _db_conn directly never set it. So the 60-second connection
        # lifetime bound -- written, per its own docstring, *because* the
        # daemon is "the process that outlives every CLI invocation" --
        # was a no-op in the daemon and nowhere else. Letting MCPServer
        # open its own connection restores it, and its state is
        # per-thread, which the injected connection also was not.

        # Start hook engine + socket
        self._hook_engine = HookEngine(self.new_db_connection)
        self._hook_socket = HookSocketServer(
            self._hook_engine, socket_path=self.hook_socket_path)
        self._hook_socket.start()

        # Periodic TRUNCATE checkpoint — see WalMaintainer.
        self._wal_maintainer = WalMaintainer(self.new_db_connection)
        self._wal_maintainer.start()

        # Start HTTP server for MCP
        self._http_server = ThreadedHTTPServer(
            ("127.0.0.1", self.port),
            MCPHTTPHandler,
            mcp_server=self._mcp_server,
        )

        def shutdown(signum, frame):
            """Ask serve_forever() to stop. Must not block.

            The previous version called self._http_server.shutdown()
            directly from here and deadlocked every time.
            BaseServer.shutdown() blocks until serve_forever() returns,
            and a Python signal handler runs on the main thread -- which
            is the thread inside serve_forever(). So it waited for a loop
            that could not proceed until it returned.

            The visible symptom was not a hang but a slow restart:
            `systemctl --user restart templedb-mcp` sat in
            deactivating/stop-sigterm for the full TimeoutStopUSec of
            1min 30s and only finished when systemd escalated to SIGKILL.
            Twice on 2026-10-04. SIGKILL meant the daemon never got to
            close its DB connection, so every restart left WAL recovery
            to the next opener.

            Reproduced standalone before fixing: an HTTPServer whose
            SIGTERM handler calls shutdown() inline is still alive three
            seconds later, while one that hands it to a thread exits
            immediately and serve_forever() returns.

            Cleanup moved to the finally below. Doing it here was also
            wrong on its own terms -- it ran while the server loop was
            still live, and sys.exit() from a signal handler raises
            SystemExit inside whatever the main thread was doing.
            """
            logger.info("Shutting down...")
            threading.Thread(
                target=self._http_server.shutdown, daemon=True).start()

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)

        logger.info(f"TempleDB MCP Daemon starting")
        logger.info(f"  MCP HTTP: http://127.0.0.1:{self.port}/mcp")
        logger.info(f"  MCP SSE:  http://127.0.0.1:{self.port}/sse")
        logger.info(f"  Hook socket: {self.hook_socket_path}")
        logger.info(f"  DB: {DB_PATH}")

        print(f"TempleDB MCP Daemon running", file=sys.stderr)
        print(f"  MCP:  http://127.0.0.1:{self.port}/mcp", file=sys.stderr)
        print(f"  Hook: {self.hook_socket_path}", file=sys.stderr)

        try:
            self._http_server.serve_forever()
        finally:
            # Runs once the loop has actually stopped, so the order is
            # real: stop accepting work, then release the sockets.
            try:
                self._hook_socket.stop()
            except Exception:
                pass
            try:
                self._wal_maintainer.stop()
            except Exception:
                pass
            try:
                self._http_server.server_close()
            except Exception:
                pass
            # No DB connection to close: every component here owns one
            # with a bounded life rather than sharing the daemon's.
            logger.info("Shutdown complete")


def main(port: int = DEFAULT_PORT):
    daemon = MCPDaemon(port=port)
    daemon.run()


if __name__ == "__main__":
    port = DEFAULT_PORT
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])
    main(port=port)
