#!/usr/bin/env python3
"""
GUI test harness for TempleDB web interface.

Starts the GUI server on a random port, tests routes via urllib, and shuts down.
No external dependencies — uses only stdlib + the TempleDB nix env.

Usage:
    ./templedb test-gui              # via templedb wrapper (uses correct python)
    python3 tests/test_gui.py        # direct (needs fastapi/uvicorn on path)
    python3 tests/test_gui.py -v     # verbose output
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path

# Ensure src/ is on path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

VERBOSE = "-v" in sys.argv or "--verbose" in sys.argv


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


PORT = find_free_port()
BASE = f"http://127.0.0.1:{PORT}"
server_thread = None
passed = 0
failed = 0
errors = []


def start_server():
    """Start the GUI server in a background thread."""
    import uvicorn
    from gui import app
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="error")


def wait_for_server(timeout=10):
    """Wait for the server to be ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{BASE}/", timeout=2)
            return True
        except Exception:
            time.sleep(0.2)
    return False


def get(path):
    """GET request, return (status_code, body_text)."""
    try:
        r = urllib.request.urlopen(f"{BASE}{path}", timeout=15)
        return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


def post(path, data=None):
    """POST request, return (status_code, body_text)."""
    try:
        if data:
            body = urllib.parse.urlencode(data).encode()
        else:
            body = b""
        req = urllib.request.Request(f"{BASE}{path}", data=body, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        r = urllib.request.urlopen(req, timeout=30)
        return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


import urllib.parse  # noqa: E402


def check(name, condition, detail=""):
    """Record a test result."""
    global passed, failed
    if condition:
        passed += 1
        if VERBOSE:
            print(f"  PASS  {name}")
    else:
        failed += 1
        errors.append((name, detail))
        print(f"  FAIL  {name}: {detail}")


# ── Test Definitions ─────────────────────────────────────────────────────────

def test_pages_load():
    """Every nav page should return 200."""
    pages = [
        ("/", "Dashboard"),
        ("/projects", "Projects"),
        ("/vcs", "VCS"),
        ("/env", "Env"),
        ("/nix", "Nix"),
        ("/deploy", "Deploy"),
        ("/audit", "Audit"),
        ("/domains", "Domains"),
        ("/docs", "Docs"),
        ("/schema-browser", "Schema"),
        ("/systemd", "Systemd"),
        ("/fleet-sync", "Fleet Sync"),
    ]
    for path, title in pages:
        status, body = get(path)
        check(f"GET {path} returns 200", status == 200, f"got {status}")
        check(f"GET {path} contains '{title}'", title in body, f"missing '{title}'")


def test_nav_links():
    """Navigation should contain all expected links."""
    status, body = get("/")
    for path in ["/projects", "/vcs", "/deploy", "/fleet-sync", "/systemd"]:
        check(f"Nav has link to {path}", f'href="{path}"' in body, "missing link")


def test_fleet_sync_page():
    """Fleet sync page has expected sections."""
    status, body = get("/fleet-sync")
    check("Fleet sync has Local Reference", "Local Reference" in body)
    check("Fleet sync has Machines", "Machines" in body)
    check("Fleet sync has Probe All", "Probe All" in body)


def test_fleet_sync_probe_unknown():
    """Probing unknown machine returns error."""
    status, body = post("/fleet-sync/probe/nonexistent_xyz")
    check("Probe unknown returns 200", status == 200, f"got {status}")
    check("Probe unknown says 'Unknown'", "Unknown" in body or "unknown" in body, body[:100])


def test_fleet_sync_probe_local():
    """Probing local machine should succeed."""
    hostname = socket.gethostname()
    status, body = post(f"/fleet-sync/probe/{hostname}")
    check("Probe local returns 200", status == 200, f"got {status}")
    check("Probe local has SSH info", "SSH" in body or "in-sync" in body or "no data" in body, body[:100])


def test_fleet_sync_push_local_rejected():
    """Push to localhost should be rejected."""
    hostname = socket.gethostname()
    status, body = post(f"/fleet-sync/push/{hostname}")
    check("Push local returns 200", status == 200, f"got {status}")
    check("Push local rejected", "Cannot" in body or "local" in body.lower(), body[:100])


def test_fleet_sync_probe_all():
    """Probe all should return results."""
    status, body = post("/fleet-sync/probe-all")
    check("Probe all returns 200", status == 200, f"got {status}")
    check("Probe all has content", len(body) > 10, f"body too short: {len(body)}")


def test_backup_commands():
    """Backup buttons should call correct commands (not 'Unknown command')."""
    # GCS may timeout if no credentials configured — that's OK, just check it doesn't say "Unknown command"
    status, body = post("/backup/gcs")
    check("Backup GCS returns", status in (200, 0), f"got {status}")  # 0 = timeout
    if status == 200:
        check("Backup GCS no 'Unknown command'", "Unknown command" not in body, body[:200])

    status, body = post("/backup/local")
    check("Backup local returns 200", status == 200, f"got {status}")
    check("Backup local no 'Unknown command'", "Unknown command" not in body, body[:200])


def test_project_not_found():
    """Non-existent project shows not found."""
    status, body = get("/projects/nonexistent_project_xyz_123")
    check("Missing project returns 200", status == 200, f"got {status}")
    check("Missing project says not found", "not found" in body.lower(), body[:100])


def test_dashboard_content():
    """Dashboard has stats and action buttons."""
    status, body = get("/")
    check("Dashboard has projects info", "Project" in body)
    check("Dashboard has backup button", "Backup" in body or "backup" in body)


# ── Runner ───────────────────────────────────────────────────────────────────

def main():
    global server_thread

    print(f"Starting GUI test server on port {PORT}...")
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    if not wait_for_server():
        print("ERROR: Server failed to start")
        sys.exit(1)

    print(f"Server ready. Running tests...\n")

    tests = [
        test_pages_load,
        test_nav_links,
        test_fleet_sync_page,
        test_fleet_sync_probe_unknown,
        test_fleet_sync_probe_local,
        test_fleet_sync_push_local_rejected,
        test_fleet_sync_probe_all,
        test_backup_commands,
        test_project_not_found,
        test_dashboard_content,
    ]

    for test_fn in tests:
        try:
            if VERBOSE:
                print(f"\n── {test_fn.__name__} ──")
            test_fn()
        except Exception as e:
            failed_name = test_fn.__name__
            errors.append((failed_name, f"EXCEPTION: {e}"))
            print(f"  FAIL  {failed_name}: EXCEPTION: {e}")

    print(f"\n{'='*60}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    if errors:
        print(f"\nFailures:")
        for name, detail in errors:
            print(f"  - {name}: {detail}")
    print(f"{'='*60}")

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
