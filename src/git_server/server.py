"""
Git HTTP Smart Protocol Server

Implements git's smart HTTP protocol to serve repositories from TempleDB.
"""

import os
import io
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional, Dict
from urllib.parse import urlparse, parse_qs

from dulwich.pack import write_pack_objects
from dulwich.protocol import Protocol
from dulwich.server import Backend, TCPGitServer
from dulwich.web import (
    get_info_refs,
    get_text_file,
    get_loose_object,
    get_pack_file,
    get_idx_file,
    handle_service_request,
    send_file,
    HTTPGitRequest,
    HTTPGitApplication
)

from .object_mapper import ObjectMapper
from .repository import TempleDBRepo
from db_utils import get_connection
from logger import get_logger

logger = get_logger(__name__)


class TempleDBBackend(Backend):
    """
    Git backend that serves repositories from TempleDB database
    """

    def __init__(self):
        self.repos = {}  # Cache of TempleDBRepo instances

    def open_repository(self, path: str):
        """
        Open a repository by project slug

        Args:
            path: Project slug (e.g., '/templedb' or 'templedb')

        Returns:
            TempleDBRepo instance
        """
        # Strip leading slash
        project_slug = path.lstrip('/')

        if project_slug not in self.repos:
            self.repos[project_slug] = TempleDBRepo(project_slug)

        return self.repos[project_slug]


class GitHTTPHandler(BaseHTTPRequestHandler):
    """HTTP request handler for git smart protocol"""

    def do_GET(self):
        """Handle GET requests (info/refs, objects, etc.)"""
        try:
            logger.info(f"GET {self.path}")

            # Parse URL
            parsed = urlparse(self.path)
            repo_path = parsed.path  # Path without query string

            # Extract project slug (e.g., '/templedb/info/refs' -> 'templedb')
            parts = repo_path.strip('/').split('/')
            if not parts:
                self.send_error(404, "Repository not found")
                return

            project_slug = parts[0]

            # Get repository
            try:
                repo = TempleDBRepo(project_slug)
            except ValueError as e:
                self.send_error(404, str(e))
                return

            # Route based on path (without query string)
            if repo_path.endswith('/info/refs'):
                self._handle_info_refs(repo, parsed)
            elif '/objects/' in repo_path:
                self._handle_get_object(repo, repo_path)
            else:
                self.send_error(404, "Not found")

        except Exception as e:
            logger.error(f"Error handling GET: {e}", exc_info=True)
            self.send_error(500, str(e))

    def do_POST(self):
        """Handle POST requests (git-upload-pack, git-receive-pack)"""
        try:
            path = self.path
            logger.info(f"POST {path}")

            # Parse URL
            parsed = urlparse(path)
            repo_path = parsed.path

            # Extract project slug
            parts = repo_path.strip('/').split('/')
            if not parts:
                self.send_error(404, "Repository not found")
                return

            project_slug = parts[0]

            # Get repository
            try:
                repo = TempleDBRepo(project_slug)
            except ValueError as e:
                self.send_error(404, str(e))
                return

            # Route based on service
            if path.endswith('/git-upload-pack'):
                self._handle_upload_pack(repo)
            elif path.endswith('/git-receive-pack'):
                self._handle_receive_pack(repo)
            else:
                self.send_error(404, "Not found")

        except Exception as e:
            logger.error(f"Error handling POST: {e}", exc_info=True)
            self.send_error(500, str(e))

    def _handle_info_refs(self, repo, parsed):
        """Handle /info/refs?service=git-upload-pack"""
        query = parse_qs(parsed.query)
        service = query.get('service', [None])[0]

        if service == 'git-upload-pack':
            # Get refs from repository
            refs = repo.get_refs()

            # Build response
            response = b''

            # Service announcement
            response += self._pkt_line(b"# service=git-upload-pack\n")
            response += b'0000'  # Flush packet

            # Send refs with capabilities on the first ref
            if refs:
                first = True
                for ref_name, commit_hash in refs.items():
                    if first:
                        # First ref includes capabilities
                        # Note: multi_ack_detailed is required for stateless-rpc
                        caps = b"multi_ack_detailed multi_ack thin-pack side-band side-band-64k ofs-delta shallow no-progress include-tag"
                        line = commit_hash + b" " + ref_name + b"\x00" + caps + b"\n"
                        first = False
                    else:
                        line = commit_hash + b" " + ref_name + b"\n"
                    response += self._pkt_line(line)

            response += b'0000'  # Flush packet

            # Send response
            self.send_response(200)
            self.send_header('Content-Type', 'application/x-git-upload-pack-advertisement')
            self.send_header('Content-Length', str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        else:
            self.send_error(400, "Invalid service")

    def _handle_upload_pack(self, repo):
        """Handle POST /git-upload-pack (client wants to fetch/clone)"""
        # Read request body
        content_length = int(self.headers.get('Content-Length', 0))
        request_data = self.rfile.read(content_length)

        logger.debug(f"upload-pack request: {request_data[:100]}")

        # Parse client wants (simplified - just send all objects for now)
        # TODO: Implement proper negotiation

        # Get all commits
        commit_hashes = repo.get_all_commits()

        # Build pack file
        pack_data = io.BytesIO()

        # Collect all objects (commits, trees, blobs)
        objects = []
        for commit_hash in commit_hashes:
            # Get the actual Commit object
            commit = repo.mapper.get_commit(commit_hash.decode())
            if commit:
                objects.append((commit, None))  # (object, path)

                # Add tree and blobs
                tree = repo.mapper.get_tree_for_commit(commit_hash.decode())
                if tree:
                    objects.append((tree, None))

                    # Add all blobs in tree
                    for entry in tree.items():
                        name, mode, sha = entry
                        blob = repo.mapper._blob_cache.get(sha.decode())
                        if blob:
                            objects.append((blob, None))

        # Write pack file with object format
        from dulwich.objects import DEFAULT_OBJECT_FORMAT
        write_pack_objects(pack_data.write, objects, object_format=DEFAULT_OBJECT_FORMAT)

        pack_bytes = pack_data.getvalue()

        # Build response with side-band
        response = b''
        response += b'0008NAK\n'  # NAK = no common commits

        # Send pack data in side-band channel 1
        # Split into chunks
        chunk_size = 65515  # Max packet size
        for i in range(0, len(pack_bytes), chunk_size):
            chunk = pack_bytes[i:i+chunk_size]
            # Side-band format: 0001<data>
            pkt = b'\x01' + chunk
            response += self._pkt_line(pkt)

        response += b'0000'  # Flush

        # Send response
        self.send_response(200)
        self.send_header('Content-Type', 'application/x-git-upload-pack-result')
        self.send_header('Content-Length', str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def _handle_receive_pack(self, repo):
        """Handle POST /git-receive-pack (client wants to push)"""
        # TODO: Implement push support
        self.send_error(403, "Push not yet supported")

    def _handle_get_object(self, repo, path):
        """Handle GET /objects/... (loose objects, pack files)"""
        # TODO: Implement object retrieval
        self.send_error(404, "Loose objects not supported")

    def _pkt_line(self, data: bytes) -> bytes:
        """Format data as a git pkt-line"""
        size = len(data) + 4
        return f"{size:04x}".encode() + data

    def log_message(self, format, *args):
        """Override to use our logger"""
        logger.info(format % args)


class GitServer:
    """
    Git HTTP server for TempleDB

    Serves git repositories directly from the database.
    """

    def __init__(self, host: str = 'localhost', port: int = 9418):
        self.host = host
        self.port = port
        self.server = None
        self.thread = None

    def start(self):
        """Start the git server"""
        if self.server:
            logger.warning("Server already running")
            return

        logger.info(f"Starting git server on {self.host}:{self.port}")

        self.server = HTTPServer((self.host, self.port), GitHTTPHandler)

        logger.info(f"Git server bound to http://{self.host}:{self.port}")

    def stop(self):
        """Stop the git server"""
        if not self.server:
            logger.warning("Server not running")
            return

        logger.info("Stopping git server")
        self.server.shutdown()
        self.server.server_close()
        self.server = None

    def serve_forever(self):
        """Run the server (blocking call)"""
        if not self.server:
            raise RuntimeError("Server not started. Call start() first.")

        logger.info("Starting serve_forever loop")
        self.server.serve_forever()

    def is_running(self) -> bool:
        """Check if server is running"""
        return self.server is not None

    def get_url(self, project_slug: str) -> str:
        """Get git URL for a project"""
        return f"http://{self.host}:{self.port}/{project_slug}"
