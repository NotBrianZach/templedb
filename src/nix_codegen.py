#!/usr/bin/env python3
"""
Nix code generator — produces nix expressions from system_config DB keys.

Generates:
  - home.packages block from nixos.pkg.user.*
  - environment.systemPackages from nixos.pkg.system.*
  - shellAliases from nixos.alias.*
  - services.*.enable from nixos.service.system.*
  - programs.*.enable from nixos.program.*
  - firewall.allowedTCPPorts from nixos.firewall.tcp

Each section is delimited by markers:
  # === BEGIN templedb-managed: <section> ===
  ...generated code...
  # === END templedb-managed: <section> ===

Code outside markers is untouched.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional
from db_utils import query_all, query_one


BEGIN = "# === BEGIN templedb-managed: {} ==="
END = "# === END templedb-managed: {} ==="


def _get_keys(prefix: str) -> List[Dict]:
    """Get all system_config keys with a given prefix."""
    return query_all(
        "SELECT key, value FROM system_config WHERE key LIKE ? ORDER BY key",
        (f"{prefix}%",)
    )


def _replace_section(content: str, section_name: str, new_code: str) -> str:
    """Replace a managed section in nix code, or append if not found."""
    begin = BEGIN.format(section_name)
    end = END.format(section_name)

    # Find existing section
    begin_idx = content.find(begin)
    end_idx = content.find(end)

    if begin_idx != -1 and end_idx != -1:
        # Replace existing section
        end_idx += len(end)
        return content[:begin_idx] + begin + "\n" + new_code + "\n    " + end + content[end_idx:]

    # Section doesn't exist yet — return content unchanged (caller decides where to insert)
    return None


def generate_user_packages() -> str:
    """Generate home.packages list from nixos.pkg.user.* keys."""
    rows = _get_keys("nixos.pkg.user.")
    if not rows:
        return ""

    # Group by category
    categories = {}
    for r in rows:
        # nixos.pkg.user.<category>.<package> = true
        parts = r["key"].replace("nixos.pkg.user.", "").split(".", 1)
        if len(parts) == 2:
            cat, pkg = parts
        else:
            cat, pkg = "other", parts[0]
        categories.setdefault(cat, []).append(pkg)

    lines = []
    for cat in sorted(categories.keys()):
        # Convert category name back to comment
        cat_label = cat.replace("_", " ").title()
        lines.append(f"    # {cat_label}")
        for pkg in sorted(categories[cat]):
            lines.append(f"    {pkg}")
        lines.append("")

    return "\n".join(lines)


def generate_system_packages() -> str:
    """Generate environment.systemPackages from nixos.pkg.system.* keys."""
    rows = _get_keys("nixos.pkg.system.")
    if not rows:
        return ""

    pkgs = sorted(r["key"].replace("nixos.pkg.system.", "") for r in rows)
    lines = [f"    {pkg}" for pkg in pkgs]
    return "\n".join(lines)


def generate_aliases() -> str:
    """Generate shellAliases from nixos.alias.* keys."""
    rows = _get_keys("nixos.alias.")
    if not rows:
        return ""

    lines = []
    for r in rows:
        name = r["key"].replace("nixos.alias.", "")
        value = r["value"].replace('"', '\\"')
        lines.append(f'      {name} = "{value}";')

    return "\n".join(lines)


def generate_services_enable() -> str:
    """Generate services.*.enable statements from nixos.service.system.* keys."""
    rows = _get_keys("nixos.service.system.")
    if not rows:
        return ""

    lines = []
    for r in rows:
        svc = r["key"].replace("nixos.service.system.", "").replace("_", ".")
        val = r["value"]
        lines.append(f"  services.{svc}.enable = {val};")

    return "\n".join(lines)


def generate_programs_enable() -> str:
    """Generate programs.*.enable statements from nixos.program.* keys."""
    rows = _get_keys("nixos.program.")
    if not rows:
        return ""

    lines = []
    for r in rows:
        prog = r["key"].replace("nixos.program.", "")
        # Skip system-prefixed ones (handled in configuration.nix)
        if prog.startswith("system."):
            continue
        lines.append(f"  programs.{prog}.enable = true;")

    return "\n".join(lines)


def generate_firewall_ports() -> str:
    """Generate firewall.allowedTCPPorts from nixos.firewall.tcp."""
    row = query_one("SELECT value FROM system_config WHERE key = 'nixos.firewall.tcp'")
    if not row:
        return ""

    try:
        ports = json.loads(row["value"])
        # Format as nix list, 8 per line
        chunks = []
        for i in range(0, len(ports), 8):
            chunk = " ".join(str(p) for p in ports[i:i+8])
            chunks.append(f"      {chunk}")
        return "\n".join(chunks)
    except Exception:
        return ""


def update_home_nix(home_path: Path, dry_run: bool = False) -> int:
    """Update managed sections in home.nix. Returns count of sections updated."""
    content = home_path.read_text()
    updated = 0

    # --- Packages ---
    pkg_code = generate_user_packages()
    if pkg_code:
        result = _replace_section(content, "user-packages", pkg_code)
        if result:
            content = result
            updated += 1
        else:
            # Insert markers around existing home.packages block
            m = re.search(r'(  home\.packages = with pkgs; \[)\n(.*?)(  \];)', content, re.DOTALL)
            if m:
                begin = BEGIN.format("user-packages")
                end = END.format("user-packages")
                replacement = f"{m.group(1)}\n    {begin}\n{pkg_code}\n    {end}\n{m.group(3)}"
                content = content[:m.start()] + replacement + content[m.end():]
                updated += 1

    # --- Aliases ---
    alias_code = generate_aliases()
    if alias_code:
        result = _replace_section(content, "aliases", alias_code)
        if result:
            content = result
            updated += 1
        else:
            # Insert markers around existing shellAliases block
            m = re.search(r'(    shellAliases = \{)\n(.*?)(    \};)', content, re.DOTALL)
            if m:
                begin = BEGIN.format("aliases")
                end = END.format("aliases")
                replacement = f"{m.group(1)}\n      {begin}\n{alias_code}\n      {end}\n{m.group(3)}"
                content = content[:m.start()] + replacement + content[m.end():]
                updated += 1

    if updated > 0 and not dry_run:
        home_path.write_text(content)

    return updated


def update_configuration_nix(conf_path: Path, dry_run: bool = False) -> int:
    """Update managed sections in configuration.nix. Returns count updated."""
    content = conf_path.read_text()
    updated = 0

    # --- System packages ---
    pkg_code = generate_system_packages()
    if pkg_code:
        result = _replace_section(content, "system-packages", pkg_code)
        if result:
            content = result
            updated += 1
        else:
            m = re.search(r'(  environment\.systemPackages = with pkgs; \[)\n(.*?)(  \];)', content, re.DOTALL)
            if m:
                begin = BEGIN.format("system-packages")
                end = END.format("system-packages")
                replacement = f"{m.group(1)}\n    {begin}\n{pkg_code}\n    {end}\n{m.group(3)}"
                content = content[:m.start()] + replacement + content[m.end():]
                updated += 1

    # --- Services ---
    svc_code = generate_services_enable()
    if svc_code:
        result = _replace_section(content, "services", svc_code)
        if result:
            content = result
            updated += 1
        else:
            # Append before final closing brace
            begin = BEGIN.format("services")
            end = END.format("services")
            # Find a good insertion point — before the last }
            last_brace = content.rfind("}")
            if last_brace > 0:
                insert = f"\n  {begin}\n{svc_code}\n  {end}\n"
                content = content[:last_brace] + insert + content[last_brace:]
                updated += 1

    # --- Firewall ---
    fw_code = generate_firewall_ports()
    if fw_code:
        result = _replace_section(content, "firewall-tcp", fw_code)
        if result:
            content = result
            updated += 1
        else:
            m = re.search(r'(    firewall\.allowedTCPPorts = \[)\n(.*?)(    \];)', content, re.DOTALL)
            if m:
                begin = BEGIN.format("firewall-tcp")
                end = END.format("firewall-tcp")
                replacement = f"{m.group(1)}\n      {begin}\n{fw_code}\n      {end}\n{m.group(3)}"
                content = content[:m.start()] + replacement + content[m.end():]
                updated += 1

    if updated > 0 and not dry_run:
        conf_path.write_text(content)

    return updated
