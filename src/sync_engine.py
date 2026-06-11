#!/usr/bin/env python3
"""
TempleDB Sync Engine — cr-sqlite CRDT sync between machines.

Uses cr-sqlite for conflict-free replication and supports multiple
transport layers:
  - Direct TCP (Tailscale/LAN)
  - GCS bucket (async/offline)
  - HTTP relay (future)

Architecture:
  1. Load cr-sqlite extension into the DB
  2. Mark tables as CRRs (conflict-free replicated relations)
  3. Exchange changesets between peers via chosen transport
"""

import base64
import json
import logging
import os
import socket
import sqlite3
import struct
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

logger = logging.getLogger(__name__)

# Shadow tables for sync — mirrors of main tables without UNIQUE constraints.
# cr-sqlite needs tables without unique indexes (besides PK).
# We sync the shadow tables, then reconcile to main tables.
SYNC_SHADOW_SCHEMA = {
    "sync_system_config": """
        CREATE TABLE IF NOT EXISTS sync_system_config (
            id INTEGER PRIMARY KEY NOT NULL,
            key TEXT DEFAULT '',
            value TEXT DEFAULT '',
            updated_at TEXT DEFAULT ''
        )
    """,
    "sync_projects": """
        CREATE TABLE IF NOT EXISTS sync_projects (
            id INTEGER PRIMARY KEY NOT NULL,
            slug TEXT DEFAULT '',
            name TEXT DEFAULT '',
            repo_url TEXT DEFAULT '',
            project_type TEXT DEFAULT '',
            is_nix_project INTEGER DEFAULT 0,
            project_category TEXT DEFAULT ''
        )
    """,
    "sync_environment_variables": """
        CREATE TABLE IF NOT EXISTS sync_environment_variables (
            id INTEGER PRIMARY KEY NOT NULL,
            scope_type TEXT DEFAULT '',
            scope_id INTEGER DEFAULT 0,
            var_name TEXT DEFAULT '',
            var_value TEXT DEFAULT '',
            is_secret INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT ''
        )
    """,
    "sync_vcs_commits": """
        CREATE TABLE IF NOT EXISTS sync_vcs_commits (
            id INTEGER PRIMARY KEY NOT NULL,
            project_id INTEGER DEFAULT 0,
            branch_id INTEGER DEFAULT 0,
            commit_hash TEXT DEFAULT '',
            author TEXT DEFAULT '',
            commit_message TEXT DEFAULT '',
            commit_timestamp TEXT DEFAULT ''
        )
    """,
    "sync_nixos_config": """
        CREATE TABLE IF NOT EXISTS sync_nixos_config (
            id INTEGER PRIMARY KEY NOT NULL,
            key TEXT DEFAULT '',
            value TEXT DEFAULT '',
            host TEXT DEFAULT '',
            updated_at TEXT DEFAULT ''
        )
    """,
}

# Mapping from shadow table → (main table, key columns for upsert)
SHADOW_TO_MAIN = {
    "sync_system_config": ("system_config", "key"),
    "sync_projects": ("projects", "slug"),
    "sync_environment_variables": ("environment_variables", "scope_type, scope_id, var_name"),
    "sync_vcs_commits": ("vcs_commits", "commit_hash"),
    "sync_nixos_config": ("system_config", "key"),
}

def _find_crsqlite():
    """Find the crsqlite extension — checks env var, then lib/ dir."""
    env_path = os.environ.get('TEMPLEDB_CRSQLITE_PATH')
    if env_path:
        return env_path
    # Fallback: lib/crsqlite.so relative to repo root
    local = Path(__file__).parent.parent / "lib" / "crsqlite"
    if Path(str(local) + ".so").exists():
        return str(local)
    return "crsqlite"  # hope it's on the search path

CRSQLITE_PATH = _find_crsqlite()


def _get_db_path():
    if 'TEMPLEDB_PATH' in os.environ:
        return os.environ['TEMPLEDB_PATH']
    sudo_user = os.environ.get('SUDO_USER')
    if sudo_user:
        return f'/home/{sudo_user}/.local/share/templedb/templedb.sqlite'
    return os.path.expanduser("~/.local/share/templedb/templedb.sqlite")


class SyncEngine:
    """Core sync engine using cr-sqlite CRDTs."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or _get_db_path()
        self._conn = None
        self._initialized = False

    def _connect(self) -> sqlite3.Connection:
        # Thread-local connections for safety
        if not hasattr(self, '_local'):
            self._local = threading.local()
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=OFF")
            try:
                conn.enable_load_extension(True)
                conn.load_extension(CRSQLITE_PATH)
            except Exception as e:
                logger.error(f"Failed to load cr-sqlite: {e}")
                raise
            self._local.conn = conn
        return self._local.conn

    def initialize(self) -> Dict[str, Any]:
        """Initialize cr-sqlite CRRs using shadow sync tables.

        Creates shadow tables (no UNIQUE constraints) and marks them
        as CRRs for sync. Populates from main tables on first run.
        Idempotent.
        """
        conn = self._connect()
        initialized = []
        skipped = []
        errors = []

        # Step 1: Create shadow tables
        for table_name, ddl in SYNC_SHADOW_SCHEMA.items():
            try:
                conn.execute(ddl)
            except Exception as e:
                errors.append((table_name, f"create failed: {e}"))

        conn.commit()

        # Step 2: Mark shadow tables as CRRs
        for table_name in SYNC_SHADOW_SCHEMA:
            try:
                conn.execute(f"SELECT crsql_as_crr('{table_name}')")
                initialized.append(table_name)
            except sqlite3.OperationalError as e:
                err_str = str(e).lower()
                if "already a crr" in err_str or "is a crr" in err_str:
                    skipped.append(table_name)
                else:
                    errors.append((table_name, str(e)))

        # Step 3: Populate shadow tables from main tables (first run)
        self._populate_shadow_tables(conn)

        conn.execute("PRAGMA foreign_keys=ON")

        site_id = conn.execute("SELECT crsql_site_id()").fetchone()[0]
        db_version = conn.execute("SELECT crsql_db_version()").fetchone()[0]

        self._initialized = True
        return {
            "site_id": site_id.hex() if isinstance(site_id, bytes) else str(site_id),
            "db_version": db_version,
            "initialized": initialized,
            "skipped": skipped,
            "errors": errors,
        }

    def _populate_shadow_tables(self, conn):
        """Copy data from main tables to shadow tables (initial sync)."""
        # system_config → sync_system_config
        conn.execute("""
            INSERT OR IGNORE INTO sync_system_config (id, key, value, updated_at)
            SELECT rowid, key, value, updated_at FROM system_config
        """)

        # projects → sync_projects
        conn.execute("""
            INSERT OR IGNORE INTO sync_projects (id, slug, name, repo_url, project_type, is_nix_project, project_category)
            SELECT id, slug, name, repo_url, project_type, is_nix_project, project_category FROM projects
        """)

        # environment_variables → sync_environment_variables
        conn.execute("""
            INSERT OR IGNORE INTO sync_environment_variables (id, scope_type, scope_id, var_name, var_value, is_secret, updated_at)
            SELECT id, scope_type, scope_id, var_name, var_value, is_secret, updated_at FROM environment_variables
        """)

        # vcs_commits → sync_vcs_commits
        conn.execute("""
            INSERT OR IGNORE INTO sync_vcs_commits (id, project_id, branch_id, commit_hash, author, commit_message, commit_timestamp)
            SELECT id, project_id, branch_id, commit_hash, author, commit_message, commit_timestamp FROM vcs_commits
        """)

        # Host-scoped system_config → sync_nixos_config
        conn.execute("""
            INSERT OR IGNORE INTO sync_nixos_config (id, key, value, host, updated_at)
            SELECT rowid, key, value,
                   CASE WHEN key LIKE '%.%' AND key NOT LIKE 'nixos.%' AND key NOT LIKE 'gcs.%' AND key NOT LIKE 'git_%' AND key NOT LIKE 'woofs.%'
                        THEN substr(key, 1, instr(key, '.') - 1) ELSE NULL END,
                   updated_at
            FROM system_config
            WHERE key LIKE '%.%'
        """)

        conn.commit()

    def reconcile_to_main(self):
        """Apply shadow table changes back to main tables after sync."""
        conn = self._connect()

        # sync_system_config → system_config
        conn.execute("""
            INSERT OR REPLACE INTO system_config (key, value, updated_at)
            SELECT key, value, updated_at FROM sync_system_config
            WHERE key IS NOT NULL
        """)

        # sync_projects → projects (update existing, don't create new — IDs may differ)
        rows = conn.execute("SELECT * FROM sync_projects").fetchall()
        for r in rows:
            existing = conn.execute(
                "SELECT id FROM projects WHERE slug = ?", (r["slug"],)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE projects SET name=?, repo_url=?, project_type=?, is_nix_project=?, project_category=? WHERE slug=?",
                    (r["name"], r["repo_url"], r["project_type"], r["is_nix_project"], r["project_category"], r["slug"])
                )

        conn.commit()
        logger.info("Reconciled shadow tables to main tables")

    def get_changes(self, since_version: int = 0) -> Tuple[List[dict], int]:
        """Get all changes since a given version.

        Returns (changes, current_db_version).
        """
        conn = self._connect()
        if not self._initialized:
            self.initialize()

        rows = conn.execute(
            "SELECT [table], [pk], [cid], [val], [col_version], "
            "[db_version], [site_id], [cl], [seq] "
            "FROM crsql_changes WHERE db_version > ?",
            (since_version,)
        ).fetchall()

        changes = []
        for r in rows:
            changes.append({
                "table": r[0],
                "pk": base64.b64encode(r[1]).decode() if isinstance(r[1], bytes) else r[1],
                "cid": r[2],
                "val": r[3],
                "col_version": r[4],
                "db_version": r[5],
                "site_id": base64.b64encode(r[6]).decode() if isinstance(r[6], bytes) else r[6],
                "cl": r[7],
                "seq": r[8],
            })

        db_version = conn.execute("SELECT crsql_db_version()").fetchone()[0]
        return changes, db_version

    def apply_changes(self, changes: List[dict]) -> int:
        """Apply changes from a remote peer. Returns count applied."""
        conn = self._connect()
        if not self._initialized:
            self.initialize()

        applied = 0
        for c in changes:
            try:
                pk = base64.b64decode(c["pk"]) if isinstance(c["pk"], str) else c["pk"]
                site_id = base64.b64decode(c["site_id"]) if isinstance(c["site_id"], str) else c["site_id"]

                conn.execute(
                    "INSERT INTO crsql_changes ([table], [pk], [cid], [val], "
                    "[col_version], [db_version], [site_id], [cl], [seq]) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (c["table"], pk, c["cid"], c["val"],
                     c["col_version"], c["db_version"], site_id, c["cl"], c["seq"])
                )
                applied += 1
            except Exception as e:
                logger.debug(f"Failed to apply change: {e}")

        conn.commit()
        return applied

    def get_site_id(self) -> str:
        conn = self._connect()
        site_id = conn.execute("SELECT crsql_site_id()").fetchone()[0]
        return site_id.hex() if isinstance(site_id, bytes) else str(site_id)

    def get_db_version(self) -> int:
        conn = self._connect()
        return conn.execute("SELECT crsql_db_version()").fetchone()[0]

    def close(self):
        if hasattr(self, '_local') and hasattr(self._local, 'conn') and self._local.conn:
            try:
                self._local.conn.execute("SELECT crsql_finalize()")
            except Exception:
                pass
            self._local.conn.close()
            self._local.conn = None


# ── TCP Sync (Tailscale/LAN) ─────────────────────────────────────────────────

DEFAULT_SYNC_PORT = 9420


class SyncServer:
    """TCP sync server — listens for peer connections and exchanges changesets."""

    def __init__(self, engine: SyncEngine, port: int = DEFAULT_SYNC_PORT):
        self.engine = engine
        self.port = port
        self._running = False

    def start(self, background: bool = True):
        """Start the sync server."""
        self._running = True
        if background:
            t = threading.Thread(target=self._serve, daemon=True)
            t.start()
            return t
        else:
            self._serve()

    def stop(self):
        self._running = False

    def _serve(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.settimeout(1.0)
        sock.bind(("0.0.0.0", self.port))
        sock.listen(5)

        logger.info(f"Sync server listening on port {self.port}")

        while self._running:
            try:
                client, addr = sock.accept()
                logger.info(f"Sync connection from {addr}")
                threading.Thread(
                    target=self._handle_client, args=(client, addr), daemon=True
                ).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self._running:
                    logger.error(f"Server error: {e}")

        sock.close()

    def _handle_client(self, client: socket.socket, addr):
        """Handle a sync request from a peer."""
        try:
            client.settimeout(30.0)

            # Read request
            data = self._recv_message(client)
            request = json.loads(data)

            if request.get("action") == "pull":
                # Peer wants our changes since their version
                since = request.get("since_version", 0)
                changes, version = self.engine.get_changes(since)
                response = {
                    "changes": changes,
                    "db_version": version,
                    "site_id": self.engine.get_site_id(),
                }
                self._send_message(client, json.dumps(response))

            elif request.get("action") == "push":
                # Peer is sending us changes
                changes = request.get("changes", [])
                applied = self.engine.apply_changes(changes)
                response = {
                    "applied": applied,
                    "db_version": self.engine.get_db_version(),
                    "site_id": self.engine.get_site_id(),
                }
                self._send_message(client, json.dumps(response))

            elif request.get("action") == "sync":
                # Full bidirectional sync
                # 1. Apply their changes
                their_changes = request.get("changes", [])
                applied = self.engine.apply_changes(their_changes)

                # 2. Send our changes since their version
                since = request.get("since_version", 0)
                our_changes, our_version = self.engine.get_changes(since)

                response = {
                    "applied": applied,
                    "changes": our_changes,
                    "db_version": our_version,
                    "site_id": self.engine.get_site_id(),
                }
                self._send_message(client, json.dumps(response))

            elif request.get("action") == "ping":
                response = {
                    "site_id": self.engine.get_site_id(),
                    "db_version": self.engine.get_db_version(),
                    "hostname": socket.gethostname(),
                }
                self._send_message(client, json.dumps(response))

        except Exception as e:
            logger.error(f"Client handler error: {e}")
        finally:
            client.close()

    def _send_message(self, sock: socket.socket, data: str):
        encoded = data.encode("utf-8")
        sock.sendall(struct.pack("!I", len(encoded)) + encoded)

    def _recv_message(self, sock: socket.socket) -> str:
        header = self._recv_exact(sock, 4)
        length = struct.unpack("!I", header)[0]
        return self._recv_exact(sock, length).decode("utf-8")

    def _recv_exact(self, sock: socket.socket, n: int) -> bytes:
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed")
            data += chunk
        return data


class SyncClient:
    """TCP sync client — connects to a peer and exchanges changesets."""

    def __init__(self, engine: SyncEngine):
        self.engine = engine

    def ping(self, host: str, port: int = DEFAULT_SYNC_PORT) -> Optional[dict]:
        """Ping a peer to check connectivity."""
        try:
            return self._request(host, port, {"action": "ping"})
        except Exception as e:
            return None

    def pull(self, host: str, port: int = DEFAULT_SYNC_PORT,
             since_version: int = 0) -> dict:
        """Pull changes from a peer."""
        response = self._request(host, port, {
            "action": "pull",
            "since_version": since_version,
        })
        if response and response.get("changes"):
            applied = self.engine.apply_changes(response["changes"])
            response["local_applied"] = applied
        return response

    def push(self, host: str, port: int = DEFAULT_SYNC_PORT,
             since_version: int = 0) -> dict:
        """Push local changes to a peer."""
        changes, version = self.engine.get_changes(since_version)
        response = self._request(host, port, {
            "action": "push",
            "changes": changes,
        })
        return response

    def sync(self, host: str, port: int = DEFAULT_SYNC_PORT,
             since_version: int = 0) -> dict:
        """Full bidirectional sync with a peer."""
        our_changes, our_version = self.engine.get_changes(since_version)

        response = self._request(host, port, {
            "action": "sync",
            "changes": our_changes,
            "since_version": since_version,
        })

        if response and response.get("changes"):
            applied = self.engine.apply_changes(response["changes"])
            response["local_applied"] = applied

        return response

    def _request(self, host: str, port: int, data: dict) -> dict:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30.0)
        try:
            sock.connect((host, port))
            # Send
            encoded = json.dumps(data).encode("utf-8")
            sock.sendall(struct.pack("!I", len(encoded)) + encoded)
            # Receive
            header = b""
            while len(header) < 4:
                header += sock.recv(4 - len(header))
            length = struct.unpack("!I", header)[0]
            response_data = b""
            while len(response_data) < length:
                response_data += sock.recv(length - len(response_data))
            return json.loads(response_data.decode("utf-8"))
        finally:
            sock.close()


# ── Peer Discovery (Tailscale) ────────────────────────────────────────────────

def discover_tailscale_peers() -> List[dict]:
    """Find other TempleDB instances on the Tailscale network."""
    import subprocess

    peers = []
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return []

        status = json.loads(result.stdout)

        # Get our own addresses
        self_node = status.get("Self", {})
        self_name = self_node.get("HostName", "")

        # Check each peer
        for node_id, peer in status.get("Peer", {}).items():
            if not peer.get("Online"):
                continue

            hostname = peer.get("HostName", "")
            addresses = peer.get("TailscaleIPs", [])
            if not addresses:
                continue

            ip = addresses[0]  # First Tailscale IP

            peers.append({
                "hostname": hostname,
                "ip": ip,
                "os": peer.get("OS", ""),
                "online": True,
                "node_id": node_id,
            })

    except FileNotFoundError:
        logger.debug("tailscale not found on PATH")
    except Exception as e:
        logger.debug(f"Tailscale discovery failed: {e}")

    return peers


def probe_peer(ip: str, port: int = DEFAULT_SYNC_PORT) -> Optional[dict]:
    """Check if a peer is running TempleDB sync on the given IP."""
    try:
        engine = SyncEngine.__new__(SyncEngine)
        engine.db_path = None
        engine._conn = None
        engine._initialized = False

        client = SyncClient(engine)
        result = client.ping(ip, port)
        return result
    except Exception:
        return None
