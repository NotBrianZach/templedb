#!/usr/bin/env python3
"""
Network commands — Tailscale setup, peer management, sync orchestration.
"""
import os
import sys
import subprocess
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command
from logger import get_logger

logger = get_logger(__name__)


class NetworkCommands(Command):
    """Network and Tailscale management."""

    def setup(self, args) -> int:
        """Install and configure Tailscale for TempleDB sync."""
        print("TempleDB Network Setup\n")

        # Step 1: Check if tailscale is installed
        ts_path = self._find_tailscale()
        if ts_path:
            print(f"  Tailscale: installed ({ts_path})")
        else:
            print("  Tailscale: not installed")
            print()
            print("  Install options:")
            print("    NixOS (configuration.nix):")
            print("      services.tailscale.enable = true;")
            print()
            print("    Or add to home.nix packages:")
            print("      tailscale")
            print()
            print("    Or install directly:")
            print("      nix-env -iA nixpkgs.tailscale")
            print()
            print("    After installing, run:")
            print("      sudo systemctl enable --now tailscaled")
            print("      sudo tailscale up")
            print()

            # Offer to add to system_config
            response = input("  Add tailscale to NixOS config? [y/N] ").strip().lower()
            if response == 'y':
                return self._add_tailscale_to_config()
            return 1

        # Step 2: Check if tailscale is running
        status = self._tailscale_status()
        if status is None:
            print("  Tailscale daemon: not running")
            print("    Start with: sudo systemctl start tailscaled")
            print("    Then:       sudo tailscale up")
            return 1

        if not status.get("Self", {}).get("Online"):
            print("  Tailscale: not connected")
            print("    Connect with: sudo tailscale up")
            return 1

        self_node = status.get("Self", {})
        print(f"  Tailscale: connected as {self_node.get('HostName', '?')}")
        ips = self_node.get("TailscaleIPs", [])
        if ips:
            print(f"  Tailscale IP: {ips[0]}")

        # Step 3: Check peers
        peers = status.get("Peer", {})
        online = sum(1 for p in peers.values() if p.get("Online"))
        print(f"  Peers: {online} online / {len(peers)} total")

        # Step 4: Check sync server
        print()
        try:
            import socket
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect(("127.0.0.1", 9420))
            s.close()
            print("  Sync server: running on port 9420")
        except Exception:
            print("  Sync server: not running")
            print("    Start with: templedb sync serve")
            print("    Or enable:  programs.templedb.sync.enable = true  (in NixOS)")

        # Step 5: Check cr-sqlite
        print()
        try:
            from sync_engine import SyncEngine
            engine = SyncEngine()
            info = engine.initialize()
            print(f"  cr-sqlite: initialized (site {info['site_id'][:12]}...)")
            engine.close()
        except Exception as e:
            print(f"  cr-sqlite: not initialized ({e})")
            print("    Run: templedb sync init")

        # Step 6: Probe peers for TempleDB
        if online > 0:
            print(f"\n  Probing {online} online peer(s) for TempleDB sync...")
            from sync_engine import discover_tailscale_peers, probe_peer
            ts_peers = discover_tailscale_peers()
            for peer in ts_peers:
                ts_info = probe_peer(peer["ip"])
                if ts_info:
                    print(f"    {peer['hostname']:20s} {peer['ip']:18s} TempleDB sync READY")
                else:
                    print(f"    {peer['hostname']:20s} {peer['ip']:18s} (no sync server)")

        print("\n  Setup complete. To sync with a peer:")
        print("    templedb sync sync <peer-hostname>")
        return 0

    def status(self, args) -> int:
        """Show network and sync status."""
        ts_path = self._find_tailscale()
        if not ts_path:
            print("Tailscale not installed.")
            print("  Run: templedb network setup")
            return 1

        status = self._tailscale_status()
        if not status:
            print("Tailscale not running.")
            print("  Start: sudo systemctl start tailscaled && sudo tailscale up")
            return 1

        self_node = status.get("Self", {})
        print(f"\nNetwork Status")
        print(f"  Hostname:  {self_node.get('HostName', '?')}")
        ips = self_node.get("TailscaleIPs", [])
        print(f"  Tailscale: {ips[0] if ips else 'no IP'}")
        print(f"  Online:    {self_node.get('Online', False)}")

        peers = status.get("Peer", {})
        online_peers = {k: v for k, v in peers.items() if v.get("Online")}

        print(f"\n  Peers ({len(online_peers)} online):")
        if not online_peers:
            print("    No online peers")
        else:
            from sync_engine import probe_peer
            for node_id, peer in online_peers.items():
                hostname = peer.get("HostName", "?")
                peer_ips = peer.get("TailscaleIPs", [])
                ip = peer_ips[0] if peer_ips else "?"
                ts_info = probe_peer(ip) if peer_ips else None

                sync_status = ""
                if ts_info:
                    sync_status = f"TempleDB v{ts_info.get('db_version', '?')}"
                else:
                    sync_status = "no sync"

                print(f"    {hostname:20s} {ip:18s} {peer.get('OS', ''):8s} {sync_status}")

        return 0

    def connect(self, args) -> int:
        """Connect to Tailscale network."""
        ts_path = self._find_tailscale()
        if not ts_path:
            print("Tailscale not installed. Run: templedb network setup")
            return 1

        print("Connecting to Tailscale...")
        result = subprocess.run(
            ["sudo", ts_path, "up"],
            capture_output=False  # Let user see login URL
        )
        return result.returncode

    def sync_all(self, args) -> int:
        """Sync with all online Tailscale peers that have TempleDB."""
        from sync_engine import SyncEngine, SyncClient, discover_tailscale_peers, probe_peer

        engine = SyncEngine()
        try:
            engine.initialize()
        except Exception as e:
            print(f"Sync not initialized: {e}")
            print("  Run: templedb sync init")
            return 1

        peers = discover_tailscale_peers()
        if not peers:
            print("No Tailscale peers found.")
            return 0

        client = SyncClient(engine)
        synced = 0

        for peer in peers:
            ts_info = probe_peer(peer["ip"])
            if not ts_info:
                continue

            print(f"Syncing with {peer['hostname']} ({peer['ip']})...")
            try:
                result = client.sync(peer["ip"], 9420)
                if result:
                    print(f"  Applied: {result.get('local_applied', 0)} local, "
                          f"{result.get('applied', 0)} remote")
                    synced += 1
            except Exception as e:
                print(f"  Failed: {e}")

        if synced:
            engine.reconcile_to_main()
            print(f"\nSynced with {synced} peer(s)")
        else:
            print("No peers available for sync")

        engine.close()
        return 0

    def _find_tailscale(self):
        import shutil
        return shutil.which("tailscale")

    def _tailscale_status(self):
        ts_path = self._find_tailscale()
        if not ts_path:
            return None
        try:
            result = subprocess.run(
                [ts_path, "status", "--json"],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                return json.loads(result.stdout)
        except Exception:
            pass
        return None

    def _add_tailscale_to_config(self):
        """Add tailscale to NixOS config via system_config."""
        from db_utils import get_connection
        conn = get_connection()

        # Add tailscale package
        conn.execute(
            "INSERT OR REPLACE INTO system_config (key, value, updated_at) "
            "VALUES ('nixos.pkg.user.vpn.tailscale', 'true', datetime('now'))"
        )

        # Add tailscale service
        conn.execute(
            "INSERT OR REPLACE INTO system_config (key, value, updated_at) "
            "VALUES ('nixos.service.system.tailscale', 'true', datetime('now'))"
        )

        conn.commit()
        print("\n  Added to system_config:")
        print("    nixos.pkg.user.vpn.tailscale = true")
        print("    nixos.service.system.tailscale = true")
        print()
        print("  Next steps:")
        print("    templedb nixos generate-all system_config")
        print("    templedb nixos rebuild system_config")
        print("    sudo tailscale up")
        return 0


def register(cli):
    """Register network commands."""
    cmd = NetworkCommands()

    net_parser = cli.register_command(
        'network', None, help_text='Network setup (Tailscale VPN + sync)'
    )
    subparsers = net_parser.add_subparsers(dest='network_subcommand', required=True)

    subparsers.add_parser('setup', help='Install and configure Tailscale for sync')
    cli.commands['network.setup'] = cmd.setup

    subparsers.add_parser('status', help='Show network and peer status')
    cli.commands['network.status'] = cmd.status

    subparsers.add_parser('connect', help='Connect to Tailscale')
    cli.commands['network.connect'] = cmd.connect

    subparsers.add_parser('sync-all', help='Sync with all online TempleDB peers')
    cli.commands['network.sync-all'] = cmd.sync_all
