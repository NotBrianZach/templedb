#!/usr/bin/env python3
"""
TempleDB CLI launcher with local patches applied via import hooks.
Allows overriding specific modules from the installed nix package.
"""
import sys
import importlib.util
from importlib.abc import MetaPathFinder
from pathlib import Path

_LOCAL = Path(__file__).parent

# Map module names to local patched files
_PATCHES = {}

# Override vibe_realtime if a patched version exists locally
_vibe_realtime_patch = _LOCAL / "vibe_realtime_patched.py"
if _vibe_realtime_patch.exists():
    _PATCHES["cli.commands.vibe_realtime"] = str(_vibe_realtime_patch)

# Patch mcp_server: fixes templedb_root path and adds var tools
_mcp_server_patch = _LOCAL / "mcp_server_patched.py"
if _mcp_server_patch.exists():
    _PATCHES["mcp_server"] = str(_mcp_server_patch)


class LocalPatchFinder(MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname in _PATCHES:
            return importlib.util.spec_from_file_location(fullname, _PATCHES[fullname])
        return None


if _PATCHES:
    sys.meta_path.insert(0, LocalPatchFinder())

# Register local extensions (var command) before running the installed CLI.
# We load var.py directly via importlib (not via the cli package) to avoid caching
# our local src/cli/__init__.py over the installed one, then register on the
# installed cli.core singleton before runpy executes the installed main().
_local_var_py = _LOCAL / "src" / "cli" / "commands" / "var.py"
if _local_var_py.exists():
    try:
        _var_spec = importlib.util.spec_from_file_location(
            "templedb_local_var", str(_local_var_py)
        )
        _var_mod = importlib.util.module_from_spec(_var_spec)
        _var_spec.loader.exec_module(_var_mod)
        # Get the installed cli.core singleton
        from cli.core import cli as _templedb_cli
        _var_mod.register(_templedb_cli)
    except Exception as _e:
        import warnings
        warnings.warn(f"templedb-launcher: failed to register local var command: {_e}")

# Run the CLI
sys.argv[0] = "templedb"
import runpy
runpy.run_module("cli", run_name="__main__", alter_sys=True)
