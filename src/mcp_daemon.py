#!/usr/bin/env python3
"""
TempleDB MCP Daemon — shared MCP server + hook socket.

One persistent process that serves:
1. MCP over HTTP/SSE on port 8421 (multiple Claude instances share this)
2. Hook queries over Unix socket at /tmp/templedb-hook.sock (instant responses)

Both interfaces share a single DB connection (WAL mode, busy_timeout=30s).

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

    def __init__(self, db_conn: sqlite3.Connection):
        self._db = db_conn
        self._lock = threading.Lock()
        self._project_cache = {}  # repo_url -> slug
        self._slug_set = set()
        self._fuse_mount = None
        self._checkout_prefix = os.path.join(str(Path.home()), ".config", "templedb", "checkouts")
        self._refresh_cache()

    def _refresh_cache(self):
        """Reload project data from DB into memory."""
        with self._lock:
            try:
                cur = self._db.cursor()
                cur.execute("SELECT slug, repo_url FROM projects WHERE repo_url IS NOT NULL")
                self._project_cache = {}
                self._slug_set = set()
                for row in cur.fetchall():
                    slug, repo_url = row[0], row[1]
                    self._slug_set.add(slug)
                    if repo_url:
                        self._project_cache[repo_url] = slug
                cur.execute(
                    "SELECT value FROM system_config WHERE key LIKE '%fuse.mount_path' "
                    "ORDER BY key DESC LIMIT 1"
                )
                row = cur.fetchone()
                self._fuse_mount = row[0] if row else os.path.join(str(Path.home()), "temple")
                logger.info(f"Hook cache refreshed: {len(self._project_cache)} projects")
            except Exception as e:
                logger.error(f"Cache refresh failed: {e}")

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

            fuse_mount = self._fuse_mount or os.path.join(str(Path.home()), "temple")
            fuse_path = os.path.join(fuse_mount, slug, rel_path) if slug and rel_path else fuse_mount

            return {
                "decision": "block",
                "reason": (
                    f"Edit files through the FUSE mount, not the checkout/repo directly.\n"
                    f"  Blocked: {file_path}\n"
                    f"  Use:     {fuse_path}\n"
                    f"FUSE writes go to the DB (source of truth) and auto-stage for VCS."
                )
            }

        return None


# ============================================================================
# Unix Socket Server — serves hook queries (~1ms per call)
# ============================================================================

class HookSocketServer(threading.Thread):
    """Listens on a Unix socket for hook queries from Claude Code hooks."""

    def __init__(self, engine: HookEngine, socket_path: str = HOOK_SOCKET_PATH):
        super().__init__(daemon=True)
        self.engine = engine
        self.socket_path = socket_path
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
# MCPDaemon — orchestrates everything
# ============================================================================

class MCPDaemon:
    """Shared MCP daemon: HTTP server + hook socket, one DB connection."""

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self._db_conn = None
        self._mcp_server = None
        self._hook_engine = None
        self._hook_socket = None
        self._http_server = None

    def _get_db_connection(self) -> sqlite3.Connection:
        if self._db_conn is None:
            self._db_conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
            self._db_conn.row_factory = sqlite3.Row
            self._db_conn.execute("PRAGMA journal_mode=WAL")
            self._db_conn.execute("PRAGMA busy_timeout=30000")
            self._db_conn.execute("PRAGMA synchronous=NORMAL")
            self._db_conn.execute("PRAGMA cache_size=-64000")
            self._db_conn.execute("PRAGMA foreign_keys=ON")
        return self._db_conn

    def run(self):
        """Start the daemon (blocking)."""
        db = self._get_db_connection()

        # Import and create MCP server (reuse existing implementation)
        from mcp_server import MCPServer
        self._mcp_server = MCPServer()
        self._mcp_server._db_conn = db

        # Start hook engine + socket
        self._hook_engine = HookEngine(db)
        self._hook_socket = HookSocketServer(self._hook_engine)
        self._hook_socket.start()

        # Start HTTP server for MCP
        self._http_server = ThreadedHTTPServer(
            ("127.0.0.1", self.port),
            MCPHTTPHandler,
            mcp_server=self._mcp_server,
        )

        def shutdown(signum, frame):
            logger.info("Shutting down...")
            self._hook_socket.stop()
            self._http_server.shutdown()
            if self._db_conn:
                self._db_conn.close()
            sys.exit(0)

        signal.signal(signal.SIGTERM, shutdown)
        signal.signal(signal.SIGINT, shutdown)

        logger.info(f"TempleDB MCP Daemon starting")
        logger.info(f"  MCP HTTP: http://127.0.0.1:{self.port}/mcp")
        logger.info(f"  MCP SSE:  http://127.0.0.1:{self.port}/sse")
        logger.info(f"  Hook socket: {HOOK_SOCKET_PATH}")
        logger.info(f"  DB: {DB_PATH}")

        print(f"TempleDB MCP Daemon running", file=sys.stderr)
        print(f"  MCP:  http://127.0.0.1:{self.port}/mcp", file=sys.stderr)
        print(f"  Hook: {HOOK_SOCKET_PATH}", file=sys.stderr)

        self._http_server.serve_forever()


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
