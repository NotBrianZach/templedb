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

# Override cathedral with local patch (adds name resolution + post-import hints)
_cathedral_patch = _LOCAL / "src" / "cli" / "commands" / "cathedral.py"
if _cathedral_patch.exists():
    _PATCHES["cli.commands.cathedral"] = str(_cathedral_patch)

# Override nixos with local patch (adds dirty-state tracking for generate/rebuild)
_nixos_patch = _LOCAL / "src" / "cli" / "commands" / "nixos.py"
if _nixos_patch.exists():
    _PATCHES["cli.commands.nixos"] = str(_nixos_patch)

# Override backup with local patch (adds backup gcs command)
_backup_patch = _LOCAL / "src" / "cli" / "commands" / "backup.py"
if _backup_patch.exists():
    _PATCHES["cli.commands.backup"] = str(_backup_patch)

# Override project with local patch (adds project set-category command)
_project_patch = _LOCAL / "src" / "cli" / "commands" / "project.py"
if _project_patch.exists():
    _PATCHES["cli.commands.project"] = str(_project_patch)

# Override main.py with local patch (fixes secret_blobs query to use junction table)
_main_patch = _LOCAL / "src" / "main.py"
if _main_patch.exists():
    _PATCHES["main"] = str(_main_patch)

# Override vcs with local patch (fixes commit query: content_text is in content_blobs, not file_contents)
_vcs_patch = _LOCAL / "src" / "cli" / "commands" / "vcs.py"
if _vcs_patch.exists():
    _PATCHES["cli.commands.vcs"] = str(_vcs_patch)

# Override system_service with local patch (symlinks home.nix alongside flake/configuration.nix)
_system_service_patch = _LOCAL / "src" / "services" / "system_service.py"
if _system_service_patch.exists():
    _PATCHES["services.system_service"] = str(_system_service_patch)

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


import re as _re
_NIX_STORE_LINE_RE = _re.compile(
    r'^\s*File "[^"]*?/nix/store/[^"]+",\s*line \d+'
)
_NIX_STORE_PATH_RE = _re.compile(
    r'/nix/store/[a-z0-9]+-[^/\s"\']+(?:/[^\s"\']+)*'
)


def _sanitize_stderr(text: str) -> str:
    """Strip nix store internals from error output so users see clean messages."""
    lines = []
    for line in text.splitlines():
        # Drop 'File "/nix/store/..." line N' traceback lines entirely
        if _NIX_STORE_LINE_RE.match(line):
            continue
        # Shorten any remaining nix store paths
        line = _NIX_STORE_PATH_RE.sub("<templedb>", line)
        lines.append(line)
    return "\n".join(lines)


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

        # Sanitize nix store paths out of all CLI error output
        _orig_run_cli = self._run_templedb_cli.__func__

        def _clean_run_cli(inner_self, cli_args):
            result = _orig_run_cli(inner_self, cli_args)
            if result["returncode"] != 0:
                result = dict(result, stderr=_sanitize_stderr(result["stderr"]))
            return result

        import types
        self._run_templedb_cli = types.MethodType(_clean_run_cli, self)
        def _run_var(sub_args):
            result = self._run_templedb_cli(["var"] + sub_args)
            if result["returncode"] != 0:
                err = _sanitize_stderr(result["stderr"] or result["stdout"])
                return {"content": [{"type": "text", "text": err}], "isError": True}
            return {"content": [{"type": "text", "text": result["stdout"].strip() or "done"}]}

        def tool_var_set(args):
            cmd = ["set"]
            if args.get("nixos"):
                cmd += [args["key"], args["value"], "--nixos"]
                if args.get("description"): cmd += ["--description", args["description"]]
            elif args.get("global_scope"):
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

        def _run_nixos(sub_args):
            result = self._run_templedb_cli(["nixos"] + sub_args)
            if result["returncode"] != 0:
                err = _sanitize_stderr(result["stderr"] or result["stdout"])
                return {"content": [{"type": "text", "text": err}], "isError": True}
            return {"content": [{"type": "text", "text": result["stdout"].strip() or "done"}]}

        def tool_nixos_status(args):
            cmd = ["status"]
            if args.get("slug"): cmd.append(args["slug"])
            return _run_nixos(cmd)

        def tool_nixos_config_list(args):
            return _run_nixos(["config-list"])

        def tool_nixos_config_get(args):
            return _run_nixos(["config-get", args["key"]])

        def tool_nixos_config_set(args):
            cmd = ["config-set", args["key"], args["value"]]
            return _run_nixos(cmd)

        def tool_nixos_generate(args):
            cmd = ["generate"]
            if args.get("slug"): cmd.append(args["slug"])
            return _run_nixos(cmd)

        def _gcs_get_token(creds: dict) -> str:
            """Mint a short-lived OAuth2 access token from a service-account JSON dict."""
            import base64, time, json as _json
            import requests as _req
            from cryptography.hazmat.primitives import hashes, serialization
            from cryptography.hazmat.primitives.asymmetric import padding

            now = int(time.time())
            header  = base64.urlsafe_b64encode(_json.dumps({"alg": "RS256", "typ": "JWT"}).encode()).rstrip(b"=").decode()
            claim   = base64.urlsafe_b64encode(_json.dumps({
                "iss":   creds["client_email"],
                "scope": "https://www.googleapis.com/auth/devstorage.read_write",
                "aud":   "https://oauth2.googleapis.com/token",
                "iat":   now, "exp": now + 3600,
            }).encode()).rstrip(b"=").decode()
            priv = serialization.load_pem_private_key(creds["private_key"].encode(), None)
            sig  = base64.urlsafe_b64encode(
                priv.sign(f"{header}.{claim}".encode(), padding.PKCS1v15(), hashes.SHA256())
            ).rstrip(b"=").decode()
            jwt  = f"{header}.{claim}.{sig}"

            resp = _req.post("https://oauth2.googleapis.com/token", data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion":  jwt,
            })
            resp.raise_for_status()
            return resp.json()["access_token"]

        def _gcs_backup_push(bucket="templedb-backups-poink"):
            """Create a local backup then upload it to GCS using the stored service account."""
            import tempfile, os as _os, subprocess as _sp, json as _json
            import requests as _req
            from datetime import datetime, timezone

            # --- 1. Decrypt credentials from DB ---
            try:
                from db_utils import get_connection as _gc
                conn = _gc()
                # Load var.py locally to access _age_decrypt
                import importlib.util as _ilu
                _spec = _ilu.spec_from_file_location("_var_local", str(_LOCAL / "src/cli/commands/var.py"))
                _vm = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_vm)
                row = conn.execute("""
                    SELECT sb.secret_blob FROM secret_blobs sb
                    WHERE sb.secret_name = 'GOOGLE_APPLICATION_CREDENTIALS'
                      AND sb.profile = 'default'
                      AND NOT EXISTS (SELECT 1 FROM project_secret_blobs psb WHERE psb.secret_blob_id = sb.id)
                """).fetchone()
                if not row:
                    return {"content": [{"type": "text",
                        "text": "GOOGLE_APPLICATION_CREDENTIALS not found in global secrets.\n"
                                "Store with: templedb var set --global --secret GOOGLE_APPLICATION_CREDENTIALS <json> --keys templedb-primary,age-key"}],
                        "isError": True}
                creds = _json.loads(_vm._age_decrypt(row[0]))
            except Exception as e:
                return {"content": [{"type": "text", "text": f"Failed to load credentials: {e}"}], "isError": True}

            # --- 2. Create local backup ---
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_path = _os.path.expanduser(f"~/.local/share/templedb/backups/templedb_backup_{ts}.sqlite")
            result = _sp.run([str(_LOCAL / "templedb"), "backup", "local", backup_path],
                             capture_output=True, text=True)
            if result.returncode != 0:
                return {"content": [{"type": "text", "text": f"Local backup failed:\n{result.stderr}"}], "isError": True}

            # --- 3. Upload to GCS ---
            try:
                token   = _gcs_get_token(creds)
                obj     = _os.path.basename(backup_path)
                size    = _os.path.getsize(backup_path)
                with open(backup_path, "rb") as fh:
                    resp = _req.put(
                        f"https://storage.googleapis.com/{bucket}/{obj}",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type":  "application/octet-stream",
                            "Content-Length": str(size),
                        },
                        data=fh,
                        timeout=600,
                    )
                resp.raise_for_status()
            except Exception as e:
                return {"content": [{"type": "text", "text": f"GCS upload failed: {e}"}], "isError": True}

            return {"content": [{"type": "text",
                "text": f"✓ Backup uploaded to gs://{bucket}/{obj} ({size // 1024 // 1024} MB)"}]}

        def tool_backup_gcs(args):
            return _gcs_backup_push()

        self.tools.update({
            "templedb_var_set":          tool_var_set,
            "templedb_var_get":          tool_var_get,
            "templedb_var_list":         tool_var_list,
            "templedb_var_export":       tool_var_export,
            "templedb_var_tag_add":      tool_var_tag_add,
            "templedb_nixos_status":     tool_nixos_status,
            "templedb_nixos_config_list": tool_nixos_config_list,
            "templedb_nixos_config_get": tool_nixos_config_get,
            "templedb_nixos_config_set": tool_nixos_config_set,
            "templedb_nixos_generate":   tool_nixos_generate,
            "templedb_backup_gcs":       tool_backup_gcs,
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
                 "nixos":        {"type": "boolean", "description": "Write to system NixOS config (no project needed)"},
                 "description":  {"type": "string", "description": "Human-readable description for --nixos keys"},
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
            {"name": "templedb_nixos_status",
             "description": "Show NixOS pipeline state: pending config changes, last generate, last rebuild, and what needs to run next.",
             "inputSchema": {"type": "object", "properties": {
                 "slug": {"type": "string", "description": "NixOS config project slug (auto-detects if only one exists)"},
             }}},
            {"name": "templedb_nixos_config_list",
             "description": "List all NixOS system_config key-value pairs (woofs.*, nixos.*, git_server.*, etc.).",
             "inputSchema": {"type": "object", "properties": {}}},
            {"name": "templedb_nixos_config_get",
             "description": "Get a single NixOS system_config value by key.",
             "inputSchema": {"type": "object", "properties": {
                 "key": {"type": "string"},
             }, "required": ["key"]}},
            {"name": "templedb_nixos_config_set",
             "description": "Set a NixOS system_config key. Marks config dirty (generate needed before next rebuild).",
             "inputSchema": {"type": "object", "properties": {
                 "key":   {"type": "string"},
                 "value": {"type": "string"},
             }, "required": ["key", "value"]}},
            {"name": "templedb_nixos_generate",
             "description": "Generate .nix modules from current system_config values and mark config clean.",
             "inputSchema": {"type": "object", "properties": {
                 "slug": {"type": "string", "description": "NixOS config project slug (auto-detects if only one exists)"},
             }}},
            {"name": "templedb_backup_gcs",
             "description": "Push a fresh templedb backup to Google Cloud Storage using credentials stored in the DB.",
             "inputSchema": {"type": "object", "properties": {}}},
        ]

    _MCPServer.get_tool_definitions = _patched_list_tools

except Exception as _e:
    import warnings
    warnings.warn(f"templedb-launcher: local extensions failed to load: {_e}")

# Run the CLI
sys.argv[0] = "templedb"
import runpy
runpy.run_module("cli", run_name="__main__", alter_sys=True)
