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

class LocalPatchFinder(MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname in _PATCHES:
            return importlib.util.spec_from_file_location(fullname, _PATCHES[fullname])
        return None


if _PATCHES:
    sys.meta_path.insert(0, LocalPatchFinder())


def _load_local(module_name, file_path):
    """Load a local .py file as a module without touching sys.modules['cli']."""
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    from cli.core import cli as _templedb_cli

    # Register var command from local source
    _var_py = _LOCAL / "src" / "cli" / "commands" / "var.py"
    if _var_py.exists():
        _load_local("templedb_local_var", _var_py).register(_templedb_cli)

    # Fix MCP server: templedb_root pointed to the wrong nix-store path;
    # also add templedb_var_* tools.
    from mcp_server import MCPServer as _MCPServer

    _orig_mcp_init = _MCPServer.__init__

    def _patched_mcp_init(self, *args, **kwargs):
        _orig_mcp_init(self, *args, **kwargs)
        self.templedb_root = _LOCAL          # fix broken PROJECT_ROOT path
        def _run_var(sub_args):
            result = self._run_templedb_cli(["var"] + sub_args)
            if result["returncode"] != 0:
                return {"content": [{"type": "text", "text": result["stderr"] or result["stdout"]}], "isError": True}
            return {"content": [{"type": "text", "text": result["stdout"].strip() or "done"}]}

        def tool_var_set(args):
            cmd = ["set"]
            if args.get("global_scope"):
                cmd += ["--global", args["key"], args["value"]]
            elif args.get("tag"):
                cmd += ["--tag", args["tag"], args["key"], args["value"]]
            else:
                cmd += [args["project"], args["key"], args["value"]]
            if args.get("target"):   cmd += ["--target", args["target"]]
            if args.get("secret"):   cmd += ["--secret"]
            if args.get("keys"):     cmd += ["--keys", args["keys"]]
            if args.get("profile"):  cmd += ["--profile", args["profile"]]
            return _run_var(cmd)

        def tool_var_get(args):
            cmd = ["get"]
            if args.get("global_scope"): cmd += ["--global"]
            elif args.get("project"):    cmd += [args["project"]]
            cmd += [args["key"]]
            if args.get("target"):  cmd += ["--target", args["target"]]
            if args.get("secret"):  cmd += ["--secret"]
            if args.get("profile"): cmd += ["--profile", args["profile"]]
            return _run_var(cmd)

        def tool_var_list(args):
            cmd = ["list"]
            if args.get("global_scope"):  cmd += ["--global"]
            elif args.get("tag"):         cmd += ["--tag", args["tag"]]
            elif args.get("project"):     cmd += [args["project"]]
            if args.get("target"):  cmd += ["--target", args["target"]]
            if args.get("profile"): cmd += ["--profile", args["profile"]]
            return _run_var(cmd)

        def tool_var_export(args):
            cmd = ["export", args["project"]]
            if args.get("target"):     cmd += ["--target", args["target"]]
            if args.get("format"):     cmd += ["--format", args["format"]]
            if args.get("no_secrets"): cmd += ["--no-secrets"]
            if args.get("profile"):    cmd += ["--profile", args["profile"]]
            return _run_var(cmd)

        def tool_var_tag_add(args):
            return _run_var(["tag", "add", args["tag_name"]] + args["projects"])

        self.tool_handlers.update({
            "templedb_var_set":     tool_var_set,
            "templedb_var_get":     tool_var_get,
            "templedb_var_list":    tool_var_list,
            "templedb_var_export":  tool_var_export,
            "templedb_var_tag_add": tool_var_tag_add,
        })

    _MCPServer.__init__ = _patched_mcp_init

    # Patch get_tool_definitions to advertise the new tools
    _orig_get_tool_defs = _MCPServer.get_tool_definitions

    def _patched_list_tools(self):
        return _orig_get_tool_defs(self) + [
            {"name": "templedb_var_set",
             "description": "Set a variable (env var or secret) at project/global/tag scope.",
             "inputSchema": {"type": "object", "properties": {
                 "project":      {"type": "string"},
                 "key":          {"type": "string"},
                 "value":        {"type": "string"},
                 "target":       {"type": "string"},
                 "global_scope": {"type": "boolean"},
                 "tag":          {"type": "string"},
                 "secret":       {"type": "boolean"},
                 "keys":         {"type": "string", "description": "Comma-separated key names (required with secret=true)"},
                 "profile":      {"type": "string"},
             }, "required": ["key", "value"]}},
            {"name": "templedb_var_get",
             "description": "Get a variable with scope resolution (project+target > project > tag > global).",
             "inputSchema": {"type": "object", "properties": {
                 "project":      {"type": "string"},
                 "key":          {"type": "string"},
                 "target":       {"type": "string"},
                 "global_scope": {"type": "boolean"},
                 "secret":       {"type": "boolean"},
                 "profile":      {"type": "string"},
             }, "required": ["key"]}},
            {"name": "templedb_var_list",
             "description": "List variables for a project annotated by scope (global/tag/project/secrets).",
             "inputSchema": {"type": "object", "properties": {
                 "project":      {"type": "string"},
                 "target":       {"type": "string"},
                 "global_scope": {"type": "boolean"},
                 "tag":          {"type": "string"},
                 "profile":      {"type": "string"},
             }}},
            {"name": "templedb_var_export",
             "description": "Export merged vars for a project (env vars + secrets) with scope resolution.",
             "inputSchema": {"type": "object", "properties": {
                 "project":    {"type": "string"},
                 "target":     {"type": "string"},
                 "format":     {"type": "string", "enum": ["shell", "dotenv", "json"]},
                 "no_secrets": {"type": "boolean"},
                 "profile":    {"type": "string"},
             }, "required": ["project"]}},
            {"name": "templedb_var_tag_add",
             "description": "Add projects to a tag group (creates tag if new).",
             "inputSchema": {"type": "object", "properties": {
                 "tag_name": {"type": "string"},
                 "projects": {"type": "array", "items": {"type": "string"}},
             }, "required": ["tag_name", "projects"]}},
        ]

    _MCPServer.get_tool_definitions = _patched_list_tools

except Exception as _e:
    import warnings
    warnings.warn(f"templedb-launcher: local extensions failed to load: {_e}")

# Run the CLI
sys.argv[0] = "templedb"
import runpy
runpy.run_module("cli", run_name="__main__", alter_sys=True)
