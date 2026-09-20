#!/usr/bin/env python3
"""
Nix code generator — produces nix expressions from system_config DB keys.

Key prefixes:
  nixos.attr.*           Direct nix attribute paths (1:1 mapping)
                           nixos.attr.services.pipewire.enable = true
                           → services.pipewire.enable = true;

  nixos.pkg.user.*       home.packages list items
  nixos.pkg.system.*     environment.systemPackages list items
  nixos.alias.*          shellAliases entries
  nixos.firewall.tcp     firewall.allowedTCPPorts (JSON list)
  nixos.flake.input.*    flake input URLs (regex replacement)

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


def _nix_value(val: str) -> str:
    """Convert a string value to a nix literal."""
    if val in ("true", "True", "1"):
        return "true"
    if val in ("false", "False", "0"):
        return "false"
    # Integers
    try:
        int(val)
        return val
    except ValueError:
        pass
    # JSON arrays/objects pass through as-is
    if val.startswith("[") or val.startswith("{"):
        return val
    # Everything else is a quoted string
    return f'"{val}"'


def _replace_section(content: str, section_name: str, new_code: str) -> str:
    """Replace a managed section in nix code, or append if not found."""
    begin = BEGIN.format(section_name)
    end = END.format(section_name)

    begin_idx = content.find(begin)
    end_idx = content.find(end)

    if begin_idx != -1 and end_idx != -1:
        end_idx += len(end)
        return content[:begin_idx] + begin + "\n" + new_code + "\n    " + end + content[end_idx:]

    return None


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

def generate_attrs() -> str:
    """Generate direct nix attribute assignments from nixos.attr.* keys.

    nixos.attr.services.pipewire.enable = true → services.pipewire.enable = true;
    nixos.attr.hardware.bluetooth.enable = true → hardware.bluetooth.enable = true;
    """
    rows = _get_keys("nixos.attr.")
    if not rows:
        return ""

    lines = []
    for r in rows:
        attr_path = r["key"].replace("nixos.attr.", "")
        lines.append(f"  {attr_path} = {_nix_value(r['value'])};")

    return "\n".join(lines)


def generate_user_packages() -> str:
    """Generate home.packages list from nixos.pkg.user.* keys."""
    rows = _get_keys("nixos.pkg.user.")
    if not rows:
        return ""

    categories = {}
    for r in rows:
        parts = r["key"].replace("nixos.pkg.user.", "").split(".", 1)
        if len(parts) == 2:
            cat, pkg = parts
        else:
            cat, pkg = "other", parts[0]
        categories.setdefault(cat, []).append(pkg)

    lines = []
    for cat in sorted(categories.keys()):
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


def generate_home_files() -> str:
    """Generate home.file entries from nixos.home.file.* keys.

    nixos.home.file..authinfo.gpg = .authinfo.gpg
      → ".authinfo.gpg" = { source = ./.authinfo.gpg; target = ".authinfo.gpg"; };

    nixos.home.file..claude/settings.json = claude/settings.json
      → ".claude/settings.json".source = ./claude/settings.json;
    """
    rows = _get_keys("nixos.home.file.")
    if not rows:
        return ""

    lines = []
    for r in rows:
        target = r["key"].replace("nixos.home.file.", "")
        source = r["value"]
        lines.append(f'    "{target}".source = ./{source};')

    return "\n".join(lines)


def generate_firewall_ports() -> str:
    """Generate firewall.allowedTCPPorts from nixos.firewall.tcp."""
    row = query_one("SELECT value FROM system_config WHERE key = 'nixos.firewall.tcp'")
    if not row:
        return ""

    try:
        ports = json.loads(row["value"])
        chunks = []
        for i in range(0, len(ports), 8):
            chunk = " ".join(str(p) for p in ports[i:i+8])
            chunks.append(f"      {chunk}")
        return "\n".join(chunks)
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# File updaters
# ---------------------------------------------------------------------------

def update_flake_inputs(flake_path: Path, dry_run: bool = False) -> int:
    """Update flake input URLs from nixos.flake.input.* DB keys."""
    rows = _get_keys("nixos.flake.input.")
    if not rows:
        return 0

    content = flake_path.read_text()
    updated = 0

    for r in rows:
        input_name = r["key"].replace("nixos.flake.input.", "")
        new_url = r["value"]

        pattern = re.compile(
            rf'(\s+{re.escape(input_name)}\.url\s*=\s*)"[^"]*"(;)',
            re.MULTILINE
        )
        new_content = pattern.sub(rf'\1"{new_url}"\2', content)
        if new_content != content:
            content = new_content
            updated += 1

    if updated > 0 and not dry_run:
        flake_path.write_text(content)

    return updated


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
            m = re.search(r'(    shellAliases = \{)\n(.*?)(    \};)', content, re.DOTALL)
            if m:
                begin = BEGIN.format("aliases")
                end = END.format("aliases")
                replacement = f"{m.group(1)}\n      {begin}\n{alias_code}\n      {end}\n{m.group(3)}"
                content = content[:m.start()] + replacement + content[m.end():]
                updated += 1

    # --- Home files ---
    hf_code = generate_home_files()
    if hf_code:
        result = _replace_section(content, "home-files", hf_code)
        if result:
            content = result
            updated += 1
        else:
            # Try to inject into existing home.file block
            m = re.search(r'(  home\.file = \{)\n(.*?)(  \};)', content, re.DOTALL)
            if m:
                begin = BEGIN.format("home-files")
                end = END.format("home-files")
                replacement = f"{m.group(1)}\n    {begin}\n{hf_code}\n    {end}\n{m.group(3)}"
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

    # --- Attributes (services, hardware, security, programs, etc.) ---
    attr_code = generate_attrs()
    if attr_code:
        result = _replace_section(content, "attrs", attr_code)
        if result:
            content = result
            updated += 1
        else:
            begin = BEGIN.format("attrs")
            end = END.format("attrs")
            last_brace = content.rfind("}")
            if last_brace > 0:
                insert = f"\n  {begin}\n{attr_code}\n  {end}\n"
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
