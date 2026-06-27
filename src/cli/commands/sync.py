#!/usr/bin/env python3
"""
Sync commands — cr-sqlite CRDT sync between machines.
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class SyncCommands(Command):
    """CRDT sync command handlers."""

    def init(self, args) -> int:
        """Initialize cr-sqlite CRDT on the database."""
        from sync_engine import SyncEngine

        engine = SyncEngine()
        print("Initializing cr-sqlite sync...")

        try:
            result = engine.initialize()

            print(f"\n  Site ID:    {result['site_id']}")
            print(f"  DB Version: {result['db_version']}")

            if result["initialized"]:
                print(f"\n  Initialized {len(result['initialized'])} table(s):")
                for t in result["initialized"]:
                    print(f"    + {t}")

            if result["skipped"]:
                print(f"\n  Skipped {len(result['skipped'])} (already initialized or missing):")
                for t in result["skipped"]:
                    print(f"    - {t}")

            if result["errors"]:
                print(f"\n  Errors ({len(result['errors'])}):")
                for table, err in result["errors"]:
                    print(f"    ! {table}: {err}")

            engine.close()
            return 0

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            print("  Ensure lib/crsqlite.so exists", file=sys.stderr)
            return 1

    def status(self, args) -> int:
        """Show sync status."""
        from sync_engine import SyncEngine, discover_tailscale_peers, probe_peer, DEFAULT_SYNC_PORT

        engine = SyncEngine()
        try:
            info = engine.initialize()
        except Exception as e:
            print(f"Sync not available: {e}")
            print("  Run: templedb sync init")
            return 1

        print(f"\nSync Status")
        print(f"  Site ID:    {info['site_id']}")
        print(f"  DB Version: {info['db_version']}")
        print(f"  Tables:     {len(info['initialized']) + len(info['skipped'])} synced")

        # Check if server is running
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect(("127.0.0.1", DEFAULT_SYNC_PORT))
            s.close()
            print(f"  Server:     running on port {DEFAULT_SYNC_PORT}")
        except Exception:
            print(f"  Server:     not running (start with: templedb sync serve)")

        # Discover Tailscale peers
        print(f"\n  Tailscale Peers:")
        peers = discover_tailscale_peers()
        if peers:
            for peer in peers:
                ts_info = probe_peer(peer["ip"])
                if ts_info:
                    print(f"    {peer['hostname']:20s} {peer['ip']:18s} "
                          f"TempleDB v{ts_info.get('db_version', '?')} "
                          f"[{ts_info.get('site_id', '?')[:12]}]")
                else:
                    print(f"    {peer['hostname']:20s} {peer['ip']:18s} (no TempleDB sync)")
        else:
            print("    No Tailscale peers found")
            print("    Install: https://tailscale.com/download")

        engine.close()
        return 0

    def serve(self, args) -> int:
        """Start the sync server."""
        from sync_engine import SyncEngine, SyncServer

        port = args.port if hasattr(args, 'port') and args.port else 9420

        engine = SyncEngine()
        try:
            info = engine.initialize()
        except Exception as e:
            print(f"Error: {e}")
            return 1

        print(f"TempleDB Sync Server")
        print(f"  Site ID: {info['site_id']}")
        print(f"  Port:    {port}")
        print(f"  Tables:  {len(info['initialized']) + len(info['skipped'])}")
        print(f"\nListening for peer connections... (Ctrl+C to stop)")

        server = SyncServer(engine, port=port)
        try:
            server.start(background=False)
        except KeyboardInterrupt:
            print("\nStopping...")
            server.stop()
            engine.close()

        return 0

    def pull(self, args) -> int:
        """Pull changes from a peer."""
        from sync_engine import SyncEngine, SyncClient

        engine = SyncEngine()
        try:
            engine.initialize()
        except Exception as e:
            print(f"Error: {e}")
            return 1

        host = args.peer
        port = args.port if hasattr(args, 'port') and args.port else 9420

        print(f"Pulling from {host}:{port}...")
        client = SyncClient(engine)

        try:
            result = client.pull(host, port)
            if result:
                print(f"  Received: {len(result.get('changes', []))} changes")
                print(f"  Applied:  {result.get('local_applied', 0)}")
                print(f"  Remote version: {result.get('db_version', '?')}")
            else:
                print(f"  No response from {host}:{port}")
                return 1
        except Exception as e:
            print(f"  Failed: {e}")
            return 1

        engine.close()
        return 0

    def push(self, args) -> int:
        """Push changes to a peer."""
        from sync_engine import SyncEngine, SyncClient

        engine = SyncEngine()
        try:
            engine.initialize()
        except Exception as e:
            print(f"Error: {e}")
            return 1

        host = args.peer
        port = args.port if hasattr(args, 'port') and args.port else 9420

        print(f"Pushing to {host}:{port}...")
        client = SyncClient(engine)

        try:
            result = client.push(host, port)
            if result:
                print(f"  Remote applied: {result.get('applied', 0)}")
                print(f"  Remote version: {result.get('db_version', '?')}")
            else:
                print(f"  No response from {host}:{port}")
                return 1
        except Exception as e:
            print(f"  Failed: {e}")
            return 1

        engine.close()
        return 0

    def do_sync(self, args) -> int:
        """Full bidirectional sync with a peer."""
        from sync_engine import SyncEngine, SyncClient

        engine = SyncEngine()
        try:
            engine.initialize()
        except Exception as e:
            print(f"Error: {e}")
            return 1

        host = args.peer
        port = args.port if hasattr(args, 'port') and args.port else 9420

        print(f"Syncing with {host}:{port}...")
        client = SyncClient(engine)

        try:
            result = client.sync(host, port)
            if result:
                print(f"  Sent:     {len(result.get('changes', []))} changes from peer")
                print(f"  Applied:  {result.get('local_applied', 0)} locally")
                print(f"  Remote:   applied {result.get('applied', 0)}")
                print(f"  Versions: local={engine.get_db_version()}, remote={result.get('db_version', '?')}")
            else:
                print(f"  No response from {host}:{port}")
                return 1
        except Exception as e:
            print(f"  Failed: {e}")
            return 1

        engine.close()
        return 0

    def peers(self, args) -> int:
        """Discover Tailscale peers running TempleDB."""
        from sync_engine import discover_tailscale_peers, probe_peer

        print("Discovering peers on Tailscale network...\n")

        peers = discover_tailscale_peers()
        if not peers:
            print("No Tailscale peers found.")
            print("  Is Tailscale running? tailscale status")
            return 0

        for peer in peers:
            ts_info = probe_peer(peer["ip"])
            status = ""
            if ts_info:
                status = f"TempleDB sync (v{ts_info.get('db_version', '?')}, {ts_info.get('site_id', '?')[:12]})"
            else:
                status = "no TempleDB sync server"

            print(f"  {peer['hostname']:20s} {peer['ip']:18s} {peer.get('os', ''):8s} {status}")

        print(f"\nTo sync: templedb sync sync <hostname-or-ip>")
        return 0


def register(cli):
    """Register sync commands."""
    cmd = SyncCommands()

    sync_parser = cli.register_command(
        'sync', None, help_text='CRDT sync between machines (cr-sqlite + Tailscale)'
    )
    subparsers = sync_parser.add_subparsers(dest='sync_subcommand', required=True)

    # sync init
    subparsers.add_parser('init', help='Initialize cr-sqlite CRDT on the database')
    cli.commands['sync.init'] = cmd.init

    # sync status
    subparsers.add_parser('status', help='Show sync status and peers')
    cli.commands['sync.status'] = cmd.status

    # sync serve
    sp = subparsers.add_parser('serve', help='Start sync server')
    sp.add_argument('--port', type=int, default=9420, help='Port (default: 9420)')
    cli.commands['sync.serve'] = cmd.serve

    # sync pull
    pp = subparsers.add_parser('pull', help='Pull changes from a peer')
    pp.add_argument('peer', help='Peer hostname or IP')
    pp.add_argument('--port', type=int, default=9420)
    cli.commands['sync.pull'] = cmd.pull

    # sync push
    pu = subparsers.add_parser('push', help='Push changes to a peer')
    pu.add_argument('peer', help='Peer hostname or IP')
    pu.add_argument('--port', type=int, default=9420)
    cli.commands['sync.push'] = cmd.push

    # sync sync (bidirectional)
    ss = subparsers.add_parser('sync', help='Full bidirectional sync with peer')
    ss.add_argument('peer', help='Peer hostname or IP')
    ss.add_argument('--port', type=int, default=9420)
    cli.commands['sync.sync'] = cmd.do_sync

    # sync peers
    subparsers.add_parser('peers', help='Discover Tailscale peers running TempleDB')
    cli.commands['sync.peers'] = cmd.peers

    # Consolidated: network commands under sync
    from cli.commands import network
    network.register_subcommands(subparsers, cli, prefix='sync')
