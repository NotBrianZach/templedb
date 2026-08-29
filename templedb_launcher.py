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

# sys.path priority order (highest first):
#   1. Materialized checkout — kept fresh by `templedb publish run`, so it
#      always matches the DB. Prefer this to avoid drift.
#   2. Local src/ — historical patches and dev overrides. Wins over the nix
#      package but loses to the checkout when both exist.
#   3. Nix package (via env PYTHONPATH set by the wrapper).
#
# The checkout path used to shadow-drift silently: the launcher only added
# _LOCAL/src, and if a dev forgot to sync it to the DB, stale code shipped.
# Prepending the checkout closes that gap without disturbing the fallback.
_HOME = Path.home()
_CHECKOUT_SRC = _HOME / ".config" / "templedb" / "checkouts" / "templedb" / "src"

_src = _LOCAL / "src"
if _src.exists() and str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

# Inserted last so it ends up at index 0 (ahead of _LOCAL/src).
if _CHECKOUT_SRC.exists() and str(_CHECKOUT_SRC) not in sys.path:
    sys.path.insert(0, str(_CHECKOUT_SRC))

# Map module names to local patched files
_PATCHES = {}

# Override cathedral with local patch (adds name resolution + post-import hints)
_cathedral_patch = _LOCAL / "src" / "cli" / "commands" / "cathedral.py"
if _cathedral_patch.exists():
    _PATCHES["cli.commands.cathedral"] = str(_cathedral_patch)

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

# Override nixos_generator with local patch (use python3 not python311 for detected packages)
_nixos_generator_patch = _LOCAL / "src" / "nixos_generator.py"
if _nixos_generator_patch.exists():
    _PATCHES["nixos_generator"] = str(_nixos_generator_patch)

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

    # Register llm command from local source
    _llm_py = _LOCAL / "src" / "cli" / "commands" / "llm.py"
    if _llm_py.exists():
        _load_local("templedb_local_llm", _llm_py).register(_templedb_cli)

    # Register test command from local source
    _test_py = _LOCAL / "src" / "cli" / "commands" / "test.py"
    if _test_py.exists():
        _load_local("templedb_local_test", _test_py).register(_templedb_cli)

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

        # ── AST tools for agents ──────────────────────────────────────
        # Structured read/write access to the config-compiler AST so
        # agents can grab a focused subtree of NixOS/home config as
        # typed context instead of reading whole .nix files, and can
        # propose changes as validated AST diffs instead of Edit-through-
        # FUSE writes (which have historically truncated silently).
        def tool_ast_subtree(args):
            import json as _json
            try:
                from services.config_compiler import ConfigCompilerService
                svc = ConfigCompilerService()
                scope = args.get("scope", "system")
                host = args.get("host") or None
                path = args.get("path") or ""
                tree = svc.resolve(scope, host)
                node = tree
                if path:
                    for part in path.split("."):
                        child = None
                        for c in node.children:
                            if c.name == part:
                                child = c; break
                        if child is None:
                            return {"content": [{"type": "text",
                                "text": f"no node at path {path!r} in scope={scope} host={host}"}],
                                "isError": True}
                        node = child
                out = svc.emit_json(node)
                # Truncate deep subtrees so a naive whole-scope query doesn't
                # blow the context window; agents can re-query a deeper path.
                text = _json.dumps(out, indent=2, default=str)
                if len(text) > 40000:
                    text = text[:40000] + "\n\n… (truncated at 40KB; request a narrower path)"
                return {"content": [{"type": "text", "text": text}]}
            except Exception as e:
                return {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}

        def tool_ast_apply(args):
            """Apply a list of typed AST operations in a single DB transaction.
            operations = [
              {"op": "set_leaf",       "scope": "system", "path": "services.x.enable",
               "value": "true", "node_type": "Bool", "host": null?},
              {"op": "add_list_item",  "scope": "system", "path": "environment.systemPackages",
               "value": "htop", "node_type": "Package", "host": "zMothership2"},
              {"op": "enable",         "node_id": 938},
              {"op": "disable",        "node_id": 938},
              {"op": "remove",         "node_id": 1151}
            ]
            """
            import json as _json
            try:
                from services.config_compiler import ConfigCompilerService
                svc = ConfigCompilerService()
                ops = args.get("operations") or []
                if not isinstance(ops, list) or not ops:
                    return {"content": [{"type": "text",
                        "text": "operations must be a non-empty list"}], "isError": True}
                results = []
                # Resolve host names → ids up front so ops referring to a
                # bad host name fail fast, before any partial mutation.
                host_ids = {}
                for op in ops:
                    hn = op.get("host")
                    if hn and hn not in host_ids:
                        hrow = svc.get_host(hn)
                        if not hrow:
                            return {"content": [{"type": "text",
                                "text": f"unknown host {hn!r}"}], "isError": True}
                        host_ids[hn] = hrow["id"]
                # Apply (single-connection auto-commit; TempleDB writes are
                # each their own txn — no BEGIN/COMMIT wrapper here yet, so
                # partial success is possible on op-level exception).
                for op in ops:
                    kind = op.get("op")
                    host_id = host_ids.get(op.get("host"))
                    try:
                        if kind == "set_leaf":
                            nid = svc.set_leaf(
                                scope=op["scope"], path=op["path"],
                                value=str(op["value"]),
                                node_type=op.get("node_type", "String"),
                                host_id=host_id, category=op.get("category"),
                                project_slug=op.get("project"),
                            )
                            results.append({"op": kind, "path": op["path"], "node_id": nid, "ok": True})
                        elif kind == "add_list_item":
                            nid = svc.add_list_item(
                                scope=op["scope"], path=op["path"],
                                value=str(op["value"]),
                                node_type=op.get("node_type", "Identifier"),
                                host_id=host_id, category=op.get("category"),
                                project_slug=op.get("project"),
                            )
                            results.append({"op": kind, "path": op["path"], "node_id": nid, "ok": True})
                        elif kind == "enable":
                            svc.enable_node(op["node_id"])
                            results.append({"op": kind, "node_id": op["node_id"], "ok": True})
                        elif kind == "disable":
                            svc.disable_node(op["node_id"])
                            results.append({"op": kind, "node_id": op["node_id"], "ok": True})
                        elif kind == "remove":
                            svc.remove_node(op["node_id"])
                            results.append({"op": kind, "node_id": op["node_id"], "ok": True})
                        else:
                            results.append({"op": kind, "ok": False,
                                            "error": f"unknown op kind: {kind}"})
                    except Exception as e:
                        results.append({"op": kind, "ok": False, "error": str(e)})
                text = _json.dumps({"results": results}, indent=2)
                any_fail = any(not r.get("ok") for r in results)
                return {"content": [{"type": "text", "text": text}], "isError": any_fail}
            except Exception as e:
                return {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True}

        # ── Agent-to-user bridge tools ────────────────────────────────
        # Used when Claude Code runs as a child of `templedb ai agent serve`
        # under Emacs. The session_id (from agent_sessions.id) is passed via
        # env TEMPLEDB_AGENT_SESSION_ID by the provider when it writes the
        # per-session MCP config. Both tools rendezvous with Emacs through
        # the agent_pending_asks table (migration 080): this handler writes
        # the ask, the agent service polls the table and emits an event to
        # Emacs, Emacs runs a picker and calls ask.respond, and this handler
        # returns the response.
        import uuid as _uuid, time as _time, os as _os, json as _json_asks

        def _ask_session_id():
            sid = _os.environ.get("TEMPLEDB_AGENT_SESSION_ID")
            if not sid:
                return None
            try:
                return int(sid)
            except ValueError:
                return None

        def _wait_for_ask_response(ask_id, timeout_s=600, poll_s=0.2):
            from agent import store as _agent_store
            deadline = _time.time() + timeout_s
            while _time.time() < deadline:
                row = _agent_store.get_pending_ask(ask_id)
                if row and row.get("status") == "responded":
                    try:
                        return _json_asks.loads(row["response"])
                    except (ValueError, TypeError):
                        return {"raw": row.get("response")}
                _time.sleep(poll_s)
            return None

        def tool_ask_user(args):
            session_id = _ask_session_id()
            if session_id is None:
                return {"content": [{"type": "text",
                    "text": "templedb_ask_user requires TEMPLEDB_AGENT_SESSION_ID env "
                            "(only available when Claude runs under `templedb ai agent`)"}],
                    "isError": True}
            questions = args.get("questions") or []
            if not isinstance(questions, list) or not questions:
                return {"content": [{"type": "text",
                    "text": "questions must be a non-empty list"}], "isError": True}
            ask_id = _uuid.uuid4().hex
            from agent import store as _agent_store
            _agent_store.create_pending_ask(
                ask_id, session_id, "question",
                {"questions": questions},
            )
            response = _wait_for_ask_response(ask_id)
            if response is None:
                return {"content": [{"type": "text",
                    "text": "User did not respond in time. Try asking again or proceed "
                            "with a reasonable default and note what you assumed."}],
                    "isError": True}
            return {"content": [{"type": "text",
                "text": _json_asks.dumps(response)}]}

        def tool_message_user(args):
            session_id = _ask_session_id()
            if session_id is None:
                return {"content": [{"type": "text",
                    "text": "templedb_message_user requires TEMPLEDB_AGENT_SESSION_ID env"}],
                    "isError": True}
            header = args.get("header") or "Message"
            body = args.get("body") or ""
            ask_id = _uuid.uuid4().hex
            from agent import store as _agent_store
            _agent_store.create_pending_ask(
                ask_id, session_id, "message",
                {"header": header, "body": body},
            )
            # One-way: don't block on a response, just mark as delivered.
            return {"content": [{"type": "text", "text": "delivered"}]}

        # --- Agent-writable sections (Phase D) ---
        # Each of these tools:
        #  1. persists the entry to agent_session_sections
        #  2. enqueues a JSON-line event on agent_pending_events
        # The agent service's poll loop forwards the event to Emacs,
        # which mutates the corresponding section in the buffer.

        def _sections_session_id_or_error(tool_name):
            sid = _ask_session_id()
            if sid is None:
                return None, {"content": [{"type": "text",
                    "text": f"{tool_name} requires TEMPLEDB_AGENT_SESSION_ID env "
                            "(only available when Claude runs under `templedb ai agent`)"}],
                    "isError": True}
            return sid, None

        def _emit_section_event(session_id, event_type, payload, summary=None):
            from agent import store as _agent_store
            _agent_store.create_pending_event(session_id, event_type, payload, summary)

        def tool_agent_note_finding(args):
            session_id, err = _sections_session_id_or_error("templedb_agent_note_finding")
            if err: return err
            text = (args.get("text") or "").strip()
            if not text:
                return {"content": [{"type": "text", "text": "text is required"}], "isError": True}
            refs = args.get("refs") or []
            entry_id = _uuid.uuid4().hex[:12]
            from agent import store as _agent_store
            _agent_store.upsert_section_entry(session_id, "findings", entry_id,
                                              {"text": text, "refs": refs})
            _emit_section_event(session_id, "agent.section.finding.add",
                                {"id": entry_id, "text": text, "refs": refs},
                                summary="Finding recorded")
            return {"content": [{"type": "text", "text": f"finding {entry_id} recorded"}]}

        def tool_agent_todo_add(args):
            session_id, err = _sections_session_id_or_error("templedb_agent_todo_add")
            if err: return err
            text = (args.get("text") or "").strip()
            if not text:
                return {"content": [{"type": "text", "text": "text is required"}], "isError": True}
            priority = args.get("priority")
            entry_id = _uuid.uuid4().hex[:12]
            from agent import store as _agent_store
            _agent_store.upsert_section_entry(session_id, "todo", entry_id,
                                              {"text": text, "priority": priority, "done": False})
            payload = {"id": entry_id, "text": text}
            if priority:
                payload["priority"] = priority
            _emit_section_event(session_id, "agent.section.todo.add", payload,
                                summary="Todo added")
            return {"content": [{"type": "text", "text": f"todo {entry_id} added"}]}

        def tool_agent_todo_done(args):
            session_id, err = _sections_session_id_or_error("templedb_agent_todo_done")
            if err: return err
            entry_id = args.get("id")
            if not entry_id:
                return {"content": [{"type": "text", "text": "id is required"}], "isError": True}
            from agent import store as _agent_store
            _agent_store.merge_section_entry(session_id, "todo", entry_id, {"done": True})
            _emit_section_event(session_id, "agent.section.todo.done", {"id": entry_id})
            return {"content": [{"type": "text", "text": f"todo {entry_id} marked done"}]}

        def tool_agent_question_add(args):
            session_id, err = _sections_session_id_or_error("templedb_agent_question_add")
            if err: return err
            text = (args.get("text") or "").strip()
            if not text:
                return {"content": [{"type": "text", "text": "text is required"}], "isError": True}
            entry_id = _uuid.uuid4().hex[:12]
            from agent import store as _agent_store
            _agent_store.upsert_section_entry(session_id, "open-questions", entry_id,
                                              {"text": text, "answered": False})
            _emit_section_event(session_id, "agent.section.question.add",
                                {"id": entry_id, "text": text},
                                summary="Question flagged")
            return {"content": [{"type": "text", "text": f"question {entry_id} added"}]}

        def tool_agent_question_answered(args):
            session_id, err = _sections_session_id_or_error("templedb_agent_question_answered")
            if err: return err
            entry_id = args.get("id")
            answer = args.get("answer")
            if not entry_id:
                return {"content": [{"type": "text", "text": "id is required"}], "isError": True}
            from agent import store as _agent_store
            _agent_store.merge_section_entry(session_id, "open-questions", entry_id,
                                             {"answered": True, "answer": answer})
            _emit_section_event(session_id, "agent.section.question.answered",
                                {"id": entry_id, "answer": answer})
            return {"content": [{"type": "text", "text": f"question {entry_id} answered"}]}

        def tool_agent_section_write(args):
            """Write to (create if missing) an agent-invented dynamic section.
            Distinct from the three fixed sections above; use this when the
            desired category doesn't fit Findings/Todo/Open Questions."""
            session_id, err = _sections_session_id_or_error("templedb_agent_section_write")
            if err: return err
            section_name = (args.get("section") or "").strip()
            text = (args.get("text") or "").strip()
            mode = args.get("mode") or "append"
            if not section_name or not text:
                return {"content": [{"type": "text",
                    "text": "section and text are required"}], "isError": True}
            entry_id = _uuid.uuid4().hex[:12]
            db_section = f"dynamic:{section_name}"
            from agent import store as _agent_store
            if mode == "replace":
                _agent_store.remove_section(session_id, db_section)
            _agent_store.upsert_section_entry(session_id, db_section, entry_id,
                                              {"text": text})
            _emit_section_event(session_id, "agent.section.dynamic.write",
                                {"section": section_name, "id": entry_id,
                                 "text": text, "mode": mode})
            return {"content": [{"type": "text",
                "text": f"wrote to '{section_name}' ({mode})"}]}

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
            "templedb_ast_subtree":      tool_ast_subtree,
            "templedb_ast_apply":        tool_ast_apply,
            "templedb_ask_user":         tool_ask_user,
            "templedb_message_user":     tool_message_user,
            "templedb_agent_note_finding":       tool_agent_note_finding,
            "templedb_agent_todo_add":           tool_agent_todo_add,
            "templedb_agent_todo_done":          tool_agent_todo_done,
            "templedb_agent_question_add":       tool_agent_question_add,
            "templedb_agent_question_answered":  tool_agent_question_answered,
            "templedb_agent_section_write":      tool_agent_section_write,
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
            {"name": "templedb_ast_subtree",
             "description":
                 "Read a typed AST subtree from the NixOS config-compiler. "
                 "Returns the resolved node tree at (scope, path) for a given host, "
                 "with each node's type, value, callee, owner projects, and host scope. "
                 "Prefer this over reading whole .nix files when you only need a slice — "
                 "e.g. path='services.pipewire' scope='system' host='zMothership2' returns "
                 "just the pipewire subtree after shared+host deep-merge. Truncates at 40KB.",
             "inputSchema": {"type": "object", "properties": {
                 "scope": {"type": "string", "enum": ["system", "home", "flake"],
                           "description": "AST scope (defaults to 'system')"},
                 "path":  {"type": "string",
                           "description": "Dotted attribute path (empty = root)"},
                 "host":  {"type": "string",
                           "description": "Host name (see templedb config-ast host list); "
                                          "omit for shared-only view"},
             }}},
            {"name": "templedb_ast_apply",
             "description":
                 "Apply a list of typed AST operations to config_nodes. Each op is one of: "
                 "set_leaf {scope,path,value,node_type,host?,project?}, "
                 "add_list_item {scope,path,value,node_type,host?,project?}, "
                 "enable {node_id}, disable {node_id}, remove {node_id}. "
                 "Returns per-op status. Use this INSTEAD of file editing when changing "
                 "NixOS config — it sidesteps the FUSE write-path entirely and produces "
                 "structured changes that flow through the AST-deploy pipeline. "
                 "After a successful apply, run `templedb deploy run system_config "
                 "--target <host>` (or `templedb ast build --host <host> --nix-build`) "
                 "to promote and activate.",
             "inputSchema": {"type": "object", "properties": {
                 "operations": {"type": "array", "items": {"type": "object"},
                                "description": "List of typed op objects"},
             }, "required": ["operations"]}},
            {"name": "templedb_ask_user",
             "description":
                 "Ask the user a multiple-choice question and wait for the answer. "
                 "Use this INSTEAD of AskUserQuestion when running under TempleDB / Emacs "
                 "— AskUserQuestion has no working UI in this environment and gets "
                 "auto-cancelled. Requires TEMPLEDB_AGENT_SESSION_ID env (set by the "
                 "agent provider when it launches Claude). Blocks for up to 600s waiting "
                 "for a response; if the user doesn't answer, returns an error and you "
                 "should either ask again or proceed with a reasonable default and note "
                 "what you assumed. Question shape mirrors AskUserQuestion: each has "
                 "{question, header, options: [{label, description}], multiSelect}.",
             "inputSchema": {"type": "object", "properties": {
                 "questions": {"type": "array", "minItems": 1, "items": {
                     "type": "object", "properties": {
                         "question":    {"type": "string"},
                         "header":      {"type": "string"},
                         "multiSelect": {"type": "boolean", "default": False},
                         "options": {"type": "array", "items": {
                             "type": "object", "properties": {
                                 "label":       {"type": "string"},
                                 "description": {"type": "string"},
                             }, "required": ["label"]}}}}}}, "required": ["questions"]}},
            {"name": "templedb_message_user",
             "description":
                 "Send a one-way, informational message to the user without asking "
                 "anything back. Renders as a distinct entry in the Emacs conversation "
                 "buffer. Use for out-of-band status updates, quick notices, or "
                 "surfacing findings that don't need a decision from the user. Requires "
                 "TEMPLEDB_AGENT_SESSION_ID env. Returns 'delivered' immediately.",
             "inputSchema": {"type": "object", "properties": {
                 "header": {"type": "string", "description": "Short label (max ~12 chars)"},
                 "body":   {"type": "string", "description": "Message body (markdown ok)"},
             }, "required": ["body"]}},
            # Agent-writable sections (Phase D).
            # Each of these writes to a dedicated Emacs section that the user
            # can read at a glance without scrolling the conversation. Use
            # these to externalise state that would otherwise clutter your
            # reply text. All require TEMPLEDB_AGENT_SESSION_ID; state is
            # persisted to agent_session_sections and survives session
            # close/reopen.
            {"name": "templedb_agent_note_finding",
             "description":
                 "Record a discovery you made during this session into the "
                 "* Findings section of the Emacs agent buffer. Use for concrete, "
                 "non-obvious facts worth surfacing (e.g. 'the auth cookie sets "
                 "SameSite=None only in prod'). Prefer this over inlining findings "
                 "in your reply when the user is likely to want to scan them later. "
                 "refs is optional — pass file paths or tool_ids that back up the claim.",
             "inputSchema": {"type": "object", "properties": {
                 "text": {"type": "string", "description": "One-line finding summary"},
                 "refs": {"type": "array", "items": {"type": "string"},
                          "description": "Optional file paths or tool_ids"},
             }, "required": ["text"]}},
            {"name": "templedb_agent_todo_add",
             "description":
                 "Add a todo item to the * Todo section. Use for actions the user "
                 "should take (or that you should take later) that don't fit in the "
                 "current run. Priority: 'low' | 'medium' | 'high' (optional).",
             "inputSchema": {"type": "object", "properties": {
                 "text":     {"type": "string"},
                 "priority": {"type": "string", "enum": ["low", "medium", "high"]},
             }, "required": ["text"]}},
            {"name": "templedb_agent_todo_done",
             "description":
                 "Mark a todo item as done by its id. Use when you completed a "
                 "previously-added todo in a later turn.",
             "inputSchema": {"type": "object", "properties": {
                 "id": {"type": "string"},
             }, "required": ["id"]}},
            {"name": "templedb_agent_question_add",
             "description":
                 "Flag an open question in the * Open Questions section. Use when "
                 "you identified something you (or the user) will need to answer "
                 "later but not right now — don't clutter the reply text with them.",
             "inputSchema": {"type": "object", "properties": {
                 "text": {"type": "string"},
             }, "required": ["text"]}},
            {"name": "templedb_agent_question_answered",
             "description":
                 "Mark an open question as answered by its id. Optionally include "
                 "the answer text so it appears next to the question.",
             "inputSchema": {"type": "object", "properties": {
                 "id":     {"type": "string"},
                 "answer": {"type": "string"},
             }, "required": ["id"]}},
            {"name": "templedb_agent_section_write",
             "description":
                 "Write to a dynamic, agent-invented section. Use this when the "
                 "content doesn't fit Findings/Todo/Open Questions and would be "
                 "useful as its own section in the Emacs buffer (e.g. 'Blockers', "
                 "'Decisions', 'Session Recap'). Section is created on first write. "
                 "mode: 'append' (default) or 'replace' (clear the section first).",
             "inputSchema": {"type": "object", "properties": {
                 "section": {"type": "string", "description": "Section name (e.g. 'Blockers')"},
                 "text":    {"type": "string", "description": "Entry text"},
                 "mode":    {"type": "string", "enum": ["append", "replace"], "default": "append"},
             }, "required": ["section", "text"]}},
        ]

    _MCPServer.get_tool_definitions = _patched_list_tools

except Exception as _e:
    import warnings
    warnings.warn(f"templedb-launcher: local extensions failed to load: {_e}")

# Run the CLI
sys.argv[0] = "templedb"
import runpy
runpy.run_module("cli", run_name="__main__", alter_sys=True)
