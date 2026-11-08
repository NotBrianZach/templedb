#!/usr/bin/env python3
"""Where a fleet machine lives, and what to say when it cannot be reached.

Extracted from `gui_pages/fleet_sync.py`: neither question is a GUI
concern, and importing that module drags in fastapi, so the logic could
not be tested anywhere the web stack is absent.

The history worth keeping. The GUI resolved a machine's address from
`fleet_machines.target_host` keyed by name, plus hard-coded fallbacks for
exactly two hosts — and those constants (192.168.8.164/172) pointed at a
subnet the machines are not on. Any host with a nixosConfiguration but no
machine row resolved to None, and the probe reported "No IP configured"
without attempting a connection. That is how zachgigamothers presented as
a machine the probe could not handle while being up the entire time, port
22 answering on its tailscale address. Tailscale knew where it was; the
probe never asked.
"""
from typing import Dict, Optional

from logger import get_logger

logger = get_logger(__name__)


def tailscale_addresses() -> Dict[str, str]:
    """Online tailscale peers as {hostname: ip}.

    Empty when tailscale is absent or down — discovery is an enrichment,
    so the caller falls back to what the database knows.
    """
    try:
        from sync_engine import discover_tailscale_peers
        return {p["hostname"]: p["ip"] for p in discover_tailscale_peers()
                if p.get("hostname") and p.get("ip")}
    except Exception as e:
        logger.debug(f"tailscale address discovery unavailable: {e}")
        return {}


def resolve_host(name: str, db_addresses: Dict[str, Optional[str]],
                 ts_addresses: Dict[str, str],
                 local_hostname: str) -> Optional[str]:
    """Address to reach NAME at, or None if nothing knows one.

    Precedence, most authoritative first:
      1. `fleet_machines.target_host` — someone wrote it down on purpose.
      2. This machine — handled in-process, never over SSH.
      3. An online tailscale peer with this hostname, matched
         case-insensitively. Preferred over any hard-coded guess because
         it keeps being right when a DHCP lease moves.

    The case-insensitive step is not cosmetic. Tailscale reports this
    tailnet's Windows box as `zachGigaMothers`; its nixosConfiguration
    attribute — the name everything else here uses — is
    `zachgigamothers`. An exact match finds nothing, which is how the
    machine stayed invisible even once tailscale was being consulted.
    """
    explicit = db_addresses.get(name)
    if explicit:
        return explicit
    if name == local_hostname:
        return "localhost"
    if name in ts_addresses:
        return ts_addresses[name]
    folded = {k.casefold(): v for k, v in ts_addresses.items()}
    return folded.get(name.casefold())


def classify_ssh_error(returncode: int, stderr: str) -> str:
    """Turn ssh's exit into something a human can act on.

    Every failure used to render as "SSH failed", which does not separate
    a machine that is powered off from one that is up and merely has not
    been given this machine's key — opposite problems with opposite
    fixes. Unrecognised failures keep ssh's own last line rather than
    being flattened into a generic string.
    """
    text = (stderr or "").lower()
    if "connection refused" in text:
        return "unreachable: nothing listening on 22"
    if "permission denied" in text or "publickey" in text:
        return "up, but this machine's SSH key is not authorized"
    if ("could not resolve" in text or "name or service not known" in text
            or "nodename nor servname" in text):
        return "name does not resolve"
    if "no route to host" in text or "network is unreachable" in text:
        return "unreachable: no route"
    if "connection timed out" in text or "operation timed out" in text:
        return "unreachable: connection timed out"
    detail = (stderr or "").strip().splitlines()
    if detail:
        return f"SSH failed (rc={returncode}): {detail[-1].strip()}"
    return f"SSH failed (rc={returncode})"
