"""
Patched mcp_server module — loaded by templedb_launcher.py instead of the
installed mcp_server.py.

Fixes:
  1. templedb_root was set to a wrong nix-store path (config.py PROJECT_ROOT bug)
     — overridden to the actual templeDB checkout directory.
  2. Adds templedb_var_* tools (set/get/list/export/tag_add) that delegate to
     the 'templedb var ...' CLI, which lives in this same checkout.
"""
import importlib.util
import sys
import json
import os
import logging
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1. Load and re-export the INSTALLED mcp_server (avoid self-import)
# ---------------------------------------------------------------------------
_INSTALLED_PATH = Path(
    "/nix/store/3pldkw59m4n8p6dlpajhpa30s79libp5-templedb-0.1.0"
    "/lib/python3.13/site-packages/mcp_server.py"
)
_spec = importlib.util.spec_from_file_location("_mcp_server_installed", str(_INSTALLED_PATH))
_installed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_installed)

# Re-export everything the installed module defines (so 'from mcp_server import X' works)
globals().update({k: getattr(_installed, k) for k in dir(_installed) if not k.startswith("__")})

# The real TempleDB directory (where ./templedb launcher lives)
_TEMPLEDB_ROOT = Path(__file__).parent


# ---------------------------------------------------------------------------
# 2. Monkeypatch TempleDBMCPServer
# ---------------------------------------------------------------------------
TempleDBMCPServer = _installed.TempleDBMCPServer

_orig_init = TempleDBMCPServer.__init__


def _patched_init(self, *args, **kwargs):
    _orig_init(self, *args, **kwargs)

    # Fix wrong PROJECT_ROOT → real checkout directory
    self.templedb_root = _TEMPLEDB_ROOT

    # Register new var tools
    self.tool_handlers.update({
        "templedb_var_set":     self._tool_var_set,
        "templedb_var_get":     self._tool_var_get,
        "templedb_var_list":    self._tool_var_list,
        "templedb_var_export":  self._tool_var_export,
        "templedb_var_tag_add": self._tool_var_tag_add,
    })


TempleDBMCPServer.__init__ = _patched_init


# ---------------------------------------------------------------------------
# 3. Patch list_tools to include var tool definitions
# ---------------------------------------------------------------------------
_orig_list_tools = TempleDBMCPServer.list_tools


def _patched_list_tools(self) -> List[Dict[str, Any]]:
    tools = _orig_list_tools(self)
    tools.extend([
        {
            "name": "templedb_var_set",
            "description": (
                "Set a variable (env var or secret) with scope (project/global/tag). "
                "Scope resolution order: project+target > project > tag > global+target > global."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project":  {"type": "string", "description": "Project slug (omit with --global or --tag)"},
                    "key":      {"type": "string", "description": "Variable name"},
                    "value":    {"type": "string", "description": "Variable value"},
                    "target":   {"type": "string", "description": "Deployment target (e.g. staging, production)"},
                    "global_scope": {"type": "boolean", "description": "Set at global scope"},
                    "tag":      {"type": "string", "description": "Tag name for tag-scoped variable"},
                    "secret":   {"type": "boolean", "description": "Store as age-encrypted secret"},
                    "keys":     {"type": "string", "description": "Comma-separated key names (required with secret=true)"},
                    "profile":  {"type": "string", "description": "Secret profile (default: 'default')"},
                },
                "required": ["key", "value"],
            },
        },
        {
            "name": "templedb_var_get",
            "description": "Get a variable with full scope resolution (project+target > project > tag > global).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project":      {"type": "string", "description": "Project slug"},
                    "key":          {"type": "string", "description": "Variable name"},
                    "target":       {"type": "string", "description": "Deployment target"},
                    "global_scope": {"type": "boolean", "description": "Look up in global scope only"},
                    "secret":       {"type": "boolean", "description": "Look up in secrets"},
                    "profile":      {"type": "string", "description": "Secret profile"},
                },
                "required": ["key"],
            },
        },
        {
            "name": "templedb_var_list",
            "description": (
                "List variables for a project, annotated by scope (global/tag/project/secrets). "
                "Omit project to list all variables across all scopes."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project":      {"type": "string", "description": "Project slug (optional)"},
                    "target":       {"type": "string", "description": "Filter by deployment target"},
                    "global_scope": {"type": "boolean", "description": "Show global vars only"},
                    "tag":          {"type": "string", "description": "Show tag vars only"},
                    "profile":      {"type": "string", "description": "Secret profile for listing secret keys"},
                },
            },
        },
        {
            "name": "templedb_var_export",
            "description": (
                "Export merged variables for a project (env vars + secrets) with scope resolution applied. "
                "Returns shell-eval-able output by default."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "project":    {"type": "string", "description": "Project slug"},
                    "target":     {"type": "string", "description": "Deployment target"},
                    "format":     {"type": "string", "enum": ["shell", "dotenv", "json"], "description": "Output format"},
                    "no_secrets": {"type": "boolean", "description": "Skip secrets (no age key needed)"},
                    "profile":    {"type": "string", "description": "Secret profile"},
                },
                "required": ["project"],
            },
        },
        {
            "name": "templedb_var_tag_add",
            "description": "Add one or more projects to a tag group (creates the tag if it doesn't exist).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "tag_name": {"type": "string", "description": "Tag name"},
                    "projects": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Project slugs to add to the tag",
                    },
                },
                "required": ["tag_name", "projects"],
            },
        },
    ])
    return tools


TempleDBMCPServer.list_tools = _patched_list_tools


# ---------------------------------------------------------------------------
# 4. Tool handler implementations (delegate to ./templedb var ...)
# ---------------------------------------------------------------------------

def _run_var(self, cmd_args: List[str]) -> Dict[str, Any]:
    """Helper: run 'templedb var <cmd_args>' and return MCP response dict."""
    result = self._run_templedb_cli(["var"] + cmd_args)
    if result["returncode"] != 0:
        return {
            "content": [{"type": "text", "text": result["stderr"] or result["stdout"]}],
            "isError": True,
        }
    return {"content": [{"type": "text", "text": result["stdout"].strip() or "done"}]}


def _tool_var_set(self, args: Dict[str, Any]) -> Dict[str, Any]:
    cmd = ["set"]
    if args.get("global_scope"):
        cmd += ["--global", args["key"], args["value"]]
    elif args.get("tag"):
        cmd += ["--tag", args["tag"], args["key"], args["value"]]
    else:
        if not args.get("project"):
            return {"content": [{"type": "text", "text": "error: project required (or set global_scope/tag)"}], "isError": True}
        cmd += [args["project"], args["key"], args["value"]]
    if args.get("target"):
        cmd += ["--target", args["target"]]
    if args.get("secret"):
        cmd += ["--secret"]
        if args.get("keys"):
            cmd += ["--keys", args["keys"]]
    if args.get("profile"):
        cmd += ["--profile", args["profile"]]
    return _run_var(self, cmd)


def _tool_var_get(self, args: Dict[str, Any]) -> Dict[str, Any]:
    cmd = ["get"]
    if args.get("global_scope"):
        cmd += ["--global"]
    elif args.get("project"):
        cmd += [args["project"]]
    cmd += [args["key"]]
    if args.get("target"):
        cmd += ["--target", args["target"]]
    if args.get("secret"):
        cmd += ["--secret"]
    if args.get("profile"):
        cmd += ["--profile", args["profile"]]
    return _run_var(self, cmd)


def _tool_var_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
    cmd = ["list"]
    if args.get("global_scope"):
        cmd += ["--global"]
    elif args.get("tag"):
        cmd += ["--tag", args["tag"]]
    elif args.get("project"):
        cmd += [args["project"]]
    if args.get("target"):
        cmd += ["--target", args["target"]]
    if args.get("profile"):
        cmd += ["--profile", args["profile"]]
    return _run_var(self, cmd)


def _tool_var_export(self, args: Dict[str, Any]) -> Dict[str, Any]:
    cmd = ["export", args["project"]]
    if args.get("target"):
        cmd += ["--target", args["target"]]
    if args.get("format"):
        cmd += ["--format", args["format"]]
    if args.get("no_secrets"):
        cmd += ["--no-secrets"]
    if args.get("profile"):
        cmd += ["--profile", args["profile"]]
    return _run_var(self, cmd)


def _tool_var_tag_add(self, args: Dict[str, Any]) -> Dict[str, Any]:
    cmd = ["tag", "add", args["tag_name"]] + args["projects"]
    return _run_var(self, cmd)


TempleDBMCPServer._tool_var_set     = _tool_var_set
TempleDBMCPServer._tool_var_get     = _tool_var_get
TempleDBMCPServer._tool_var_list    = _tool_var_list
TempleDBMCPServer._tool_var_export  = _tool_var_export
TempleDBMCPServer._tool_var_tag_add = _tool_var_tag_add


# ---------------------------------------------------------------------------
# 5. Re-export main (mcp.py does 'from mcp_server import main')
# ---------------------------------------------------------------------------
main = _installed.main
