#!/usr/bin/env python3
"""
Web GUI launcher command
"""
import sys
import webbrowser
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from cli.core import Command


class GUICommands(Command):
    """Web GUI command handlers"""

    def launch_gui(self, args) -> int:
        """Launch the TempleDB web GUI"""
        try:
            import uvicorn
        except ImportError:
            print("Error: uvicorn is not installed", file=sys.stderr)
            print("Install with: pip install uvicorn fastapi", file=sys.stderr)
            return 1

        try:
            import fastapi  # noqa: F401
        except ImportError:
            print("Error: fastapi is not installed", file=sys.stderr)
            print("Install with: pip install fastapi", file=sys.stderr)
            return 1

        port = getattr(args, "port", 8420) or 8420
        host = getattr(args, "host", None) or "127.0.0.1"
        url = f"http://{host}:{port}"

        # The GUI authenticates nobody. Every page is reachable by whoever
        # can open the socket, and /pending-asks, /actions and the vcs
        # pages all WRITE. So the default stays loopback, and widening it
        # is a decision the caller has to type out.
        #
        # The supported way to reach it from another device is to bind the
        # tailscale interface address (100.x.y.z, from `tailscale ip -4`):
        # that interface only carries WireGuard traffic from tailnet peers,
        # so it is reachable from the phone and NOT from the LAN. With
        # MagicDNS on, the peer uses http://<host>.<tailnet>.ts.net:8420.
        #
        # `tailscale serve 8420` would be nicer still -- real TLS, no bind
        # change -- but it blocks forever provisioning a cert unless HTTPS
        # Certificates are enabled for the tailnet in the admin console.
        if host not in ("127.0.0.1", "localhost", "::1"):
            print(f"warning: GUI is unauthenticated and binding {host} — "
                  f"anyone who can reach that address can write to this "
                  f"database", file=sys.stderr)
            if host in ("0.0.0.0", "::"):
                print("warning: 0.0.0.0 includes every LAN and public "
                      "interface. Bind the specific tailscale address "
                      "(`tailscale ip -4`) instead.", file=sys.stderr)

        # Open browser after server is up. Pointless when serving a
        # non-loopback bind from a systemd unit, where there is no session
        # to open a browser in, and it spawns a stray process there.
        if host in ("127.0.0.1", "localhost", "::1"):
            def _open_browser():
                time.sleep(0.8)
                webbrowser.open(url)

            threading.Thread(target=_open_browser, daemon=True).start()

        print(f"TempleDB GUI → {url}", file=sys.stderr)
        print("Press Ctrl+C to stop.", file=sys.stderr)

        gui_path = Path(__file__).parent.parent.parent / "gui.py"
        # uvicorn needs the app as an import string; load from file path instead
        import importlib.util
        spec = importlib.util.spec_from_file_location("templedb_gui", str(gui_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        try:
            uvicorn.run(mod.app, host=host, port=port, log_level="warning")
        except KeyboardInterrupt:
            pass

        return 0


def register(cli):
    """Register GUI commands"""
    cmd = GUICommands()
    gui_parser = cli.register_command(
        "gui",
        cmd.launch_gui,
        help_text="Launch interactive web GUI"
    )
    gui_parser.add_argument(
        "--port", type=int, default=8420,
        help="Port to listen on (default: 8420)"
    )
    gui_parser.add_argument(
        "--host", default="127.0.0.1",
        help="Address to bind (default: 127.0.0.1). The GUI is "
             "unauthenticated and can write, so to reach it from another "
             "device bind the tailscale address from `tailscale ip -4` "
             "rather than 0.0.0.0 — that interface carries only tailnet "
             "peers, not the LAN."
    )
