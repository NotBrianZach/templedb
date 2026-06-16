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
        host = "127.0.0.1"
        url = f"http://{host}:{port}"

        # Open browser after server is up
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
