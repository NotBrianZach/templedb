#!/usr/bin/env python3
"""
TempleDB MCP Server - Model Context Protocol integration for Claude Code

Exposes templedb operations as native tools that Claude can invoke directly.
Uses stdio transport for local integration.
"""

import sys
import json
import re
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from repositories import ProjectRepository
from llm_context import TempleDBContext
from config import DB_PATH, PROJECT_ROOT, FUSE_MOUNT_PATH
from logger import get_logger

# Configure logging to stderr so stdout is clean for MCP protocol
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = get_logger(__name__)


# MCP Error Codes (following JSON-RPC 2.0 conventions)
# Standard JSON-RPC errors: -32768 to -32000 (reserved)
# Application-specific errors: -32000 to -32099
class ErrorCode:
    """MCP Error codes for TempleDB operations"""
    # Project errors (-32010 to -32019)
    PROJECT_NOT_FOUND = -32010
    PROJECT_ALREADY_EXISTS = -32011
    PROJECT_IMPORT_FAILED = -32012
    PROJECT_SYNC_FAILED = -32013

    # Query errors (-32020 to -32029)
    QUERY_FAILED = -32020
    QUERY_INVALID = -32021

    # VCS errors (-32030 to -32039)
    VCS_OPERATION_FAILED = -32030
    VCS_NO_CHANGES = -32031
    VCS_CONFLICT = -32032

    # Secret errors (-32040 to -32049)
    SECRET_NOT_FOUND = -32040
    SECRET_DECRYPT_FAILED = -32041
    SECRET_ENCRYPT_FAILED = -32042
    SECRET_KEY_NOT_FOUND = -32043

    # Cathedral errors (-32050 to -32059)
    CATHEDRAL_EXPORT_FAILED = -32050
    CATHEDRAL_IMPORT_FAILED = -32051
    CATHEDRAL_INVALID_PACKAGE = -32052

    # Deployment errors (-32060 to -32069)
    DEPLOYMENT_FAILED = -32060
    DEPLOYMENT_TARGET_NOT_FOUND = -32061

    # Environment errors (-32070 to -32079)
    ENV_VAR_NOT_FOUND = -32070
    ENV_VAR_INVALID = -32071

    # Workflow errors (-32080 to -32089)
    WORKFLOW_NOT_FOUND = -32080
    WORKFLOW_INVALID = -32081
    WORKFLOW_EXECUTION_FAILED = -32082
    WORKFLOW_VALIDATION_FAILED = -32083

    # Generic application errors
    INTERNAL_ERROR = -32000
    VALIDATION_ERROR = -32001
    NOT_FOUND = -32002
    PERMISSION_DENIED = -32003


class MCPServer:
    """MCP Server implementation for TempleDB"""

    def __init__(self):
        """Initialize MCP server with templedb repositories"""
        self.project_repo = ProjectRepository()
        self.context_gen = TempleDBContext(DB_PATH)

        # MCP protocol version
        self.protocol_version = "2024-11-05"

        # Get TempleDB root directory (where ./templedb script lives)
        # PROJECT_ROOT is already the templeDB directory (not src/)
        self.templedb_root = PROJECT_ROOT

        # SQLite connection for reuse (with thread check)
        self._db_conn = None

        # Default project context (for context switching feature)
        self._default_project = None

        # ── Core MCP tools (minimal set — use templedb_cli for everything else) ──
        self.tools = {
            # Universal CLI wrapper — covers ALL commands
            "templedb_cli": self.tool_cli,
            # Direct DB query (can't do via CLI)
            "templedb_query": self.tool_query,
            # High-frequency project operations
            "templedb_project_list": self.tool_project_list,
            "templedb_project_show": self.tool_project_show,
            # VCS (used constantly during coding sessions)
            "templedb_vcs_status": self.tool_vcs_status,
            "templedb_vcs_commit": self.tool_vcs_commit,
            # Context generation for sessions
            "templedb_context_generate": self.tool_context_generate,
            # Cross-project search (unique to TempleDB)
            "templedb_graph_search": self.tool_graph_search,
            # System config (quick get/set without CLI string composition)
            "templedb_config_get": self.tool_config_get,
            "templedb_config_set": self.tool_config_set,
            # Deploy pipeline (triggers, rollback, multi-target)
            "templedb_deploy": self.tool_deploy,
            # Secret/key management
            "templedb_secret": self.tool_secret,
        }

    def _get_db_connection(self):
        """Get or create database connection (reusable for queries)"""
        if self._db_conn is None:
            self._db_conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30.0)
            self._db_conn.row_factory = sqlite3.Row
            # Enable WAL mode for concurrent access
            self._db_conn.execute("PRAGMA journal_mode=WAL")
            self._db_conn.execute("PRAGMA busy_timeout=30000")
            self._db_conn.execute("PRAGMA synchronous=NORMAL")
            self._db_conn.execute("PRAGMA cache_size=-64000")
            self._db_conn.execute("PRAGMA foreign_keys=ON")
        return self._db_conn

    def _release_db_connection(self):
        """Commit (or rollback on failure) any open transaction on the shared connection.

        Called after every request handler so long-lived MCP server sessions never
        hold an uncommitted write transaction between requests — which would block
        all writers in other processes indefinitely.
        """
        if self._db_conn is not None:
            try:
                self._db_conn.commit()
            except Exception:
                try:
                    self._db_conn.rollback()
                except Exception:
                    pass

    def _run_templedb_cli(self, args: List[str]) -> Dict[str, Any]:
        """Run templedb CLI command and return result.

        Args:
            args: Command arguments (e.g., ["project", "list"])

        Returns:
            Dict with stdout, stderr, returncode
        """
        import subprocess

        cmd = [str(self.templedb_root / "templedb")] + args

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.templedb_root)
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        except Exception as e:
            return {
                "stdout": "",
                "stderr": str(e),
                "returncode": 1
            }

    def _error_response(self, message: str, error_code: int = None, details: Dict[str, Any] = None) -> Dict[str, Any]:
        """Create a standardized error response.

        Args:
            message: Error message
            error_code: Optional error code from ErrorCode class
            details: Optional additional error details

        Returns:
            MCP error response dict
        """
        error_data = {
            "type": "text",
            "text": message
        }

        if error_code is not None:
            error_data["error_code"] = error_code

        if details:
            error_data["details"] = details

        return {
            "content": [error_data],
            "isError": True
        }

    def _success_response(self, data: Any, format_json: bool = True) -> Dict[str, Any]:
        """Create a standardized success response.

        Args:
            data: Response data (will be JSON-encoded if format_json=True)
            format_json: Whether to JSON-encode the data

        Returns:
            MCP success response dict
        """
        if format_json and not isinstance(data, str):
            text = json.dumps(data, indent=2)
        else:
            text = str(data)

        return {
            "content": [{
                "type": "text",
                "text": text
            }]
        }

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return MCP tool definitions — minimal core set.

        Only 10 tools exposed. Use templedb_cli for everything else.
        This saves ~6000 context tokens vs the old 77-tool set.
        """
        return [
            {
                "name": "templedb_cli",
                "description": "Run any TempleDB CLI command. Covers ALL TempleDB operations: nixos, graph, sync, network, backup, deploy, vcs, env, secret, config, mount, etc. Returns stdout/stderr/exit_code. Examples: 'project list', 'vcs status myproject --refresh', 'nixos host clone src dest', 'graph who-uses SUPABASE_URL', 'backup gcs', 'sync status'.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "CLI command and arguments (without 'templedb' prefix)"
                        }
                    },
                    "required": ["command"]
                }
            },
            {
                "name": "templedb_query",
                "description": "Execute a read-only SQL query against the TempleDB SQLite database. For exploring data, checking state, or custom analysis.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "SQL query to execute (SELECT only)"},
                        "params": {"type": "array", "items": {"type": "string"}, "description": "Query parameters"}
                    },
                    "required": ["sql"]
                }
            },
            {
                "name": "templedb_project_list",
                "description": "List all projects tracked in TempleDB with file counts and metadata.",
                "inputSchema": {"type": "object", "properties": {}, "required": []}
            },
            {
                "name": "templedb_project_show",
                "description": "Show detailed information about a specific project.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_vcs_status",
                "description": "Show VCS working directory status for a project (staged, modified, added, deleted files).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project slug"},
                        "refresh": {"type": "boolean", "description": "Re-scan filesystem for changes"}
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_vcs_commit",
                "description": "Create a VCS commit for staged changes in a project.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project slug"},
                        "message": {"type": "string", "description": "Commit message"},
                        "author": {"type": "string", "description": "Author name"},
                        "stage_all": {"type": "boolean", "description": "Stage all changes before committing"}
                    },
                    "required": ["project", "message"]
                }
            },
            {
                "name": "templedb_context_generate",
                "description": "Generate LLM context for a project — file listing, structure, key metadata.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string", "description": "Project slug"}
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_graph_search",
                "description": "Fuzzy search across ALL projects, files, env vars, secrets, commits, symbols, and config. Returns categorized results.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query"}
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "templedb_config_get",
                "description": "Get a system_config value by key.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Config key (e.g. 'nixos.flake_output')"}
                    },
                    "required": ["key"]
                }
            },
            {
                "name": "templedb_config_set",
                "description": "Set a system_config key-value pair. Host-scoped by default (prefixes active host). Use scope='global' for keys shared across all hosts.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Config key"},
                        "value": {"type": "string", "description": "Config value"},
                        "scope": {"type": "string", "enum": ["host", "global"], "description": "Scope: 'host' (default, prefixes active host) or 'global'"},
                        "host": {"type": "string", "description": "Target a specific host (default: active host from nixos.flake_output)"}
                    },
                    "required": ["key", "value"]
                }
            },
            {
                "name": "templedb_deploy",
                "description": "Deploy pipeline operations: run deployments, manage triggers (auto-deploy on commit), list history, rollback. Supports multi-target and commit-specific deploys.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["run", "status", "history", "rollback", "trigger_list", "trigger_add", "trigger_remove", "notify_list"], "description": "Deploy action"},
                        "project": {"type": "string", "description": "Project slug"},
                        "target": {"type": "string", "description": "Deployment target (e.g., production, staging)"},
                        "commit": {"type": "string", "description": "Specific commit hash to deploy (for 'run')"},
                        "branch": {"type": "string", "description": "Branch pattern (for trigger_add) or branch to deploy from"},
                        "all_targets": {"type": "boolean", "description": "Deploy to all targets (for 'run')"},
                        "dry_run": {"type": "boolean", "description": "Simulate without deploying"},
                        "trigger_id": {"type": "integer", "description": "Trigger ID (for trigger_remove)"}
                    },
                    "required": ["action"]
                }
            },
            {
                "name": "templedb_secret",
                "description": "Secret and key management: set/get/list secrets, manage encryption keys, export for deployment.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": ["get", "set", "list", "delete", "export", "key_list", "key_info", "key_test"], "description": "Secret action"},
                        "project": {"type": "string", "description": "Project slug"},
                        "name": {"type": "string", "description": "Secret name"},
                        "value": {"type": "string", "description": "Secret value (for 'set')"},
                        "keys": {"type": "string", "description": "Comma-separated encryption key names (for 'set')"},
                        "format": {"type": "string", "enum": ["shell", "dotenv", "json", "yaml"], "description": "Export format"},
                        "key_name": {"type": "string", "description": "Key name (for key_info, key_test)"}
                    },
                    "required": ["action"]
                }
            },
        ]

    # ── Legacy tool definitions removed ──────────────────────────────────
    # The following 67 tools were removed and consolidated into templedb_cli:
    # project_import, project_sync, commit_list, commit_create,
    # search_files, search_content, vcs_add/reset/log/edit/discard/diff/branch,
    # file_get, file_set, deploy, env_get/set/list,
    # config_list/delete, secret_list/export/show_keys,
    # cathedral_export/import/inspect,
    # fleet_network_create/list/info, fleet_machine_add/list,
    # fleet_deploy/status/check/diff,
    # code_search/show_symbol/show_clusters/impact_analysis/
    # extract_symbols/build_graph/detect_clusters/index_search,
    # workflow_execute/status/list/validate,
    # context_set_default/get_default, schema_explore,
    # readme_scan/create/add_topic/add_reference/generate_index/
    # find_related/verify_links/list,
    # mount_status, db_status/migrate, git_export,
    # dotfiles_list, bootstrap_status,
    # graph_deps, nixos_host_list, nixos_generate_all
    #
    # Use templedb_cli({command: "..."}) for any of these.

    # Keep old method stubs so the code doesn't break if something
    # references them internally. They're just not exposed as MCP tools.

    def _LEGACY_get_tool_definitions(self):
        """Old 77-tool definition list — kept for reference only."""
        pass

    def get_resource_definitions(self) -> List[Dict[str, Any]]:
        """Return MCP resource definitions"""
        return [
            {
                "uri": "templedb://schema",
                "name": "TempleDB Schema",
                "description": "Complete database schema overview including all tables and their structures",
                "mimeType": "application/json"
            },
            {
                "uri": "templedb://projects",
                "name": "Projects List",
                "description": "List of all tracked projects with metadata",
                "mimeType": "application/json"
            },
            {
                "uri": "templedb://config",
                "name": "System Configuration",
                "description": "TempleDB system configuration settings",
                "mimeType": "application/json"
            }
        ]

    def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read a resource by URI"""
        try:
            conn = self._get_db_connection()
            cursor = conn.cursor()

            if uri == "templedb://schema":
                # Return complete schema
                cursor.execute("""
                    SELECT name, type, sql
                    FROM sqlite_master
                    WHERE type IN ('table', 'view', 'index')
                    AND name NOT LIKE 'sqlite_%'
                    ORDER BY type, name
                """)
                objects = cursor.fetchall()

                schema_data = {
                    "tables": [],
                    "views": [],
                    "indexes": []
                }

                for row in objects:
                    obj = {
                        "name": row["name"],
                        "sql": row["sql"]
                    }
                    if row["type"] == "table":
                        schema_data["tables"].append(obj)
                    elif row["type"] == "view":
                        schema_data["views"].append(obj)
                    elif row["type"] == "index":
                        schema_data["indexes"].append(obj)

                return self._success_response(schema_data)

            elif uri == "templedb://projects":
                # Return all projects
                cursor.execute("""
                    SELECT
                        p.id,
                        p.name,
                        p.slug,
                        p.repo_url,
                        p.created_at,
                        COUNT(DISTINCT f.id) as file_count,
                        COUNT(DISTINCT c.id) as commit_count
                    FROM projects p
                    LEFT JOIN project_files f ON f.project_id = p.id
                    LEFT JOIN vcs_commits c ON c.project_id = p.id
                    GROUP BY p.id
                    ORDER BY p.created_at DESC
                """)
                projects = cursor.fetchall()

                projects_data = {
                    "total": len(projects),
                    "projects": [dict(row) for row in projects]
                }

                return self._success_response(projects_data)

            elif uri == "templedb://config":
                # Return system config
                cursor.execute("""
                    SELECT key, value, description, updated_at
                    FROM system_config
                    ORDER BY key
                """)
                configs = cursor.fetchall()

                config_data = {
                    "total": len(configs),
                    "settings": [dict(row) for row in configs]
                }

                return self._success_response(config_data)

            elif uri.startswith("templedb://project/"):
                # Project-specific resource: templedb://project/{slug}/schema
                parts = uri.split("/")
                if len(parts) >= 4:
                    project_slug = parts[3]

                    cursor.execute("""
                        SELECT id, name, slug FROM projects
                        WHERE slug = ?
                    """, (project_slug,))
                    project = cursor.fetchone()

                    if not project:
                        return self._error_response(
                            f"Project '{project_slug}' not found",
                            ErrorCode.PROJECT_NOT_FOUND,
                            {"project": project_slug}
                        )

                    # If asking for schema
                    if len(parts) >= 5 and parts[4] == "schema":
                        cursor.execute("""
                            SELECT
                                CASE
                                    WHEN INSTR(file_name, '.') > 0
                                    THEN SUBSTR(file_name, INSTR(file_name, '.'))
                                    ELSE '(no extension)'
                                END as extension,
                                COUNT(*) as count
                            FROM project_files
                            WHERE project_id = ?
                            GROUP BY extension
                            ORDER BY count DESC
                        """, (project["id"],))
                        file_types = cursor.fetchall()

                        cursor.execute("""
                            SELECT COUNT(*) as count FROM vcs_commits
                            WHERE project_id = ?
                        """, (project["id"],))
                        commit_count = cursor.fetchone()["count"]

                        project_data = {
                            "project": dict(project),
                            "file_types": [dict(row) for row in file_types],
                            "total_commits": commit_count
                        }

                        return self._success_response(project_data)

            # Unknown resource
            return self._error_response(
                f"Resource not found: {uri}",
                ErrorCode.NOT_FOUND,
                {"uri": uri}
            )

        except Exception as e:
            logger.error(f"Error reading resource {uri}: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    # Tool implementations

    def tool_project_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List all projects"""
        try:
            projects = self.project_repo.get_all()
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(projects, indent=2)
                    }
                ]
            }
        except Exception as e:
            logger.error(f"Error listing projects: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_project_show(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Show project details"""
        try:
            project_name = args["project"]

            # Try to get by slug first, then by name
            project = self.project_repo.get_by_slug(project_name)
            if not project:
                # Try as ID if numeric
                try:
                    project_id = int(project_name)
                    project = self.project_repo.get_by_id(project_id)
                except ValueError:
                    pass

            if not project:
                return self._error_response(
                    f"Project '{project_name}' not found",
                    error_code=ErrorCode.PROJECT_NOT_FOUND,
                    details={"project": project_name}
                )

            # Get additional details
            stats = self.project_repo.get_statistics(project['id'])
            if stats:
                project['stats'] = stats

            return self._success_response(project)

        except Exception as e:
            logger.error(f"Error showing project: {e}", exc_info=True)
            return self._error_response(
                f"Internal error: {str(e)}",
                error_code=ErrorCode.INTERNAL_ERROR
            )

    def tool_query(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute SQL query"""
        try:
            query = args.get("sql", args.get("query"))
            if not query:
                return self._error_response("Missing 'sql' parameter")
            format_type = args.get("format", "json")

            conn = self._get_db_connection()
            cursor = conn.cursor()
            # Block write queries - this is a read-only tool
            if re.search(r'\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE)\b', query, re.IGNORECASE):
                return self._error_response("Write queries are not allowed. Use dedicated tools for modifications.")
            cursor.execute(query)
            rows = cursor.fetchall()

            results = [dict(row) for row in rows]

            if format_type == "json":
                output = json.dumps(results, indent=2)
            elif format_type == "table":
                # Simple table format
                if results:
                    headers = list(results[0].keys())
                    lines = [" | ".join(headers)]
                    lines.append("-" * len(lines[0]))
                    for row in results:
                        lines.append(" | ".join(str(row[h]) for h in headers))
                    output = "\n".join(lines)
                else:
                    output = "No results"
            elif format_type == "csv":
                if results:
                    import csv
                    import io
                    output_io = io.StringIO()
                    writer = csv.DictWriter(output_io, fieldnames=results[0].keys())
                    writer.writeheader()
                    writer.writerows(results)
                    output = output_io.getvalue()
                else:
                    output = ""
            else:
                output = json.dumps(results, indent=2)

            return {
                "content": [{"type": "text", "text": output}]
            }
        except Exception as e:
            logger.error(f"Error executing query: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_context_generate(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Generate LLM context for project"""
        try:
            project_name = args["project"]
            max_files = args.get("max_files", 50)

            context_data = self.context_gen.generate_project_context(project_name, max_files=max_files)

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(context_data, indent=2)
                    }
                ]
            }
        except Exception as e:
            logger.error(f"Error generating context: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_vcs_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Show VCS status for project"""
        try:
            project_name = args["project"]

            import subprocess
            result = subprocess.run(
                ["./templedb", "vcs", "status", project_name],
                capture_output=True, text=True, cwd=str(self.templedb_root)
            )

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Status check failed: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout}]
            }
        except Exception as e:
            logger.error(f"Error checking status: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_vcs_commit(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a commit"""
        try:
            project_name = args["project"]
            message = args["message"]
            author = args.get("author", "templedb")
            commit_all = args.get("stage_all", args.get("all", False))

            import subprocess
            # Stage all files first if requested (commit has no --all flag; add does)
            if commit_all:
                add_cmd = ["./templedb", "vcs", "add", "-p", project_name, "--all"]
                add_result = subprocess.run(add_cmd, capture_output=True, text=True, cwd=str(self.templedb_root))
                if add_result.returncode != 0:
                    return {
                        "content": [{"type": "text", "text": f"Commit failed (staging step): {add_result.stderr}"}],
                        "isError": True
                    }

            cmd = ["./templedb", "vcs", "commit", "-p", project_name, "-m", message, "-a", author]
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.templedb_root))

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Commit failed: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout or "Commit created successfully"}]
            }
        except Exception as e:
            logger.error(f"Error creating commit: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_deploy(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Deploy project"""
        try:
            project_name = args["project"]
            target = args.get("target", "default")
            dry_run = args.get("dry_run", False)
            only = args.get("only", None)

            import subprocess
            cmd = ["./templedb", "deploy", "run", project_name]
            if target:
                cmd.extend(["--target", target])
            if dry_run:
                cmd.append("--dry-run")
            if only:
                cmd.extend(["--only", only])

            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.templedb_root))

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Deployment failed: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout or "Deployment completed successfully"}]
            }
        except Exception as e:
            logger.error(f"Error deploying project: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_config_get(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get system config value (simple key-value store)"""
        try:
            key = args["key"]

            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                SELECT key, value, description, updated_at
                FROM system_config
                WHERE key = ?
            """, (key,))

            row = cursor.fetchone()
            if not row:
                return {
                    "content": [{"type": "text", "text": f"Config key '{key}' not found"}],
                    "isError": True
                }

            result = dict(row)
            return {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]}

        except Exception as e:
            logger.error(f"Error getting config: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_config_set(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Set system config value, host-scoped by default."""
        try:
            key = args["key"]
            value = args["value"]
            description = args.get("description", "")
            scope = args.get("scope", "host")

            conn = self._get_db_connection()
            cursor = conn.cursor()

            if scope != "global":
                host = args.get("host")
                if not host:
                    row = cursor.execute(
                        "SELECT value FROM system_config WHERE key = 'nixos.flake_output'"
                    ).fetchone()
                    host = row[0] if row else None

                if host:
                    key = f"{host}.{key}"

            cursor.execute("""
                INSERT OR REPLACE INTO system_config
                (key, value, description, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            """, (key, value, description))

            conn.commit()

            return {
                "content": [{"type": "text", "text": f"Set config {key}={value}"}]
            }

        except Exception as e:
            logger.error(f"Error setting config: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    # Fleet deployment tools

    # ========================================================================
    # CODE INTELLIGENCE TOOLS (Phase 1.7)
    # ========================================================================

    # ========================================================================
    # WORKFLOW ORCHESTRATION TOOLS (Phase 2.2)
    # ========================================================================

    def _list_available_workflows(self) -> str:
        """Helper to list available workflow names"""
        workflows_dir = self.templedb_root / "workflows"
        if not workflows_dir.exists():
            return "none"
        workflow_files = list(workflows_dir.glob("*.yaml"))
        return ", ".join([f.stem for f in workflow_files]) if workflow_files else "none"

    # Context Management Tools

    def handle_message(self, message: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Handle incoming MCP message"""
        msg_type = message.get("method")
        msg_id = message.get("id")
        params = message.get("params", {})

        try:
            if msg_type == "initialize":
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "protocolVersion": self.protocol_version,
                        "capabilities": {
                            "tools": {},
                            "resources": {}
                        },
                        "serverInfo": {
                            "name": "templedb",
                            "version": "1.1.0"
                        }
                    }
                }

            elif msg_type == "tools/list":
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "tools": self.get_tool_definitions()
                    }
                }

            elif msg_type == "resources/list":
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": {
                        "resources": self.get_resource_definitions()
                    }
                }

            elif msg_type == "resources/read":
                uri = params.get("uri")
                if not uri:
                    return {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {
                            "code": -32602,
                            "message": "Missing required parameter: uri"
                        }
                    }

                try:
                    result = self.read_resource(uri)
                finally:
                    self._release_db_connection()
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": result
                }

            elif msg_type == "tools/call":
                tool_name = params.get("name")
                tool_args = params.get("arguments", {})

                if tool_name not in self.tools:
                    return {
                        "jsonrpc": "2.0",
                        "id": msg_id,
                        "error": {
                            "code": -32601,
                            "message": f"Tool not found: {tool_name}"
                        }
                    }

                tool_func = self.tools[tool_name]
                try:
                    result = tool_func(tool_args)
                finally:
                    # Ensure no open transaction lingers between requests
                    self._release_db_connection()

                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "result": result
                }

            else:
                return {
                    "jsonrpc": "2.0",
                    "id": msg_id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {msg_type}"
                    }
                }

        except Exception as e:
            logger.error(f"Error handling message: {e}", exc_info=True)
            return {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}"
                }
            }

    def run(self):
        """Run MCP server on stdin/stdout"""
        logger.info("TempleDB MCP Server starting...")
        logger.info(f"Protocol version: {self.protocol_version}")
        logger.info(f"Registered {len(self.tools)} tools")

        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue

                try:
                    message = json.loads(line)
                    logger.debug(f"Received message: {message.get('method')}")

                    response = self.handle_message(message)
                    if response:
                        output = json.dumps(response)
                        print(output, flush=True)
                        logger.debug(f"Sent response for: {message.get('method')}")

                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON: {e}")
                    continue
                except Exception as e:
                    logger.error(f"Error processing message: {e}", exc_info=True)
                    continue

        except KeyboardInterrupt:
            logger.info("MCP Server shutting down...")
        except Exception as e:
            logger.error(f"Fatal error: {e}", exc_info=True)
            sys.exit(1)

    # ========================================================================
    # File Operations Tools
    # ========================================================================

    # ========================================================================
    # README Cross-Reference System Tools
    # ========================================================================

    # ── New tools: mount, db, git-export, dotfiles, bootstrap ─────────

    def tool_deploy(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Deploy pipeline operations — delegates to CLI."""
        try:
            action = args["action"]
            project = args.get("project", "")

            cmd_map = {
                "run": f"deploy run {project}",
                "status": f"deploy status {project}",
                "history": f"deploy history {project}",
                "rollback": f"deploy rollback {project}",
                "trigger_list": f"deploy trigger list {project}",
                "trigger_add": f"deploy trigger add {project} {args.get('branch', 'main')} {args.get('target', 'production')}",
                "trigger_remove": f"deploy trigger remove {args.get('trigger_id', '')}",
                "notify_list": f"deploy notify list",
            }

            cmd = cmd_map.get(action, f"deploy {action} {project}")

            # Add optional flags
            if args.get("target") and action == "run":
                cmd += f" --target {args['target']}"
            if args.get("commit") and action == "run":
                cmd += f" --commit {args['commit']}"
            if args.get("branch") and action == "run":
                cmd += f" --branch {args['branch']}"
            if args.get("all_targets") and action == "run":
                cmd += " --all-targets"
            if args.get("dry_run"):
                cmd += " --dry-run"

            return self.tool_cli({"command": cmd.strip()})

        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_secret(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Secret and key management — delegates to CLI."""
        try:
            action = args["action"]
            project = args.get("project", "")

            cmd_map = {
                "get": f"env secret get {project} {args.get('name', '')}",
                "set": f"env secret set {project} {args.get('name', '')} {args.get('value', '')} --keys {args.get('keys', '')}",
                "list": f"env secret list {project}",
                "delete": f"env secret delete {project} {args.get('name', '')}",
                "export": f"env secret export {project} --format {args.get('format', 'dotenv')}",
                "key_list": "env key list",
                "key_info": f"env key info {args.get('key_name', '')}",
                "key_test": f"env key test {args.get('key_name', '')}",
            }

            cmd = cmd_map.get(action, f"env secret {action} {project}")
            return self.tool_cli({"command": cmd.strip()})

        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_cli(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Run any TempleDB CLI command."""
        try:
            import subprocess, shlex, shutil
            command = args["command"]
            cmd_parts = shlex.split(command)

            # Find templedb binary
            templedb = shutil.which("templedb")
            if not templedb:
                templedb_path = Path(__file__).parent.parent / "result" / "bin" / "templedb"
                if templedb_path.exists():
                    templedb = str(templedb_path)
                else:
                    templedb = str(Path(__file__).parent.parent / "templedb")

            result = subprocess.run(
                [templedb] + cmd_parts,
                capture_output=True, text=True, timeout=120
            )
            return self._success_response({
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "command": f"templedb {command}",
            })
        except Exception as e:
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_graph_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Search across everything."""
        try:
            from knowledge_graph import search_everywhere
            results = search_everywhere(args["query"], limit=30)
            return self._success_response(results)
        except Exception as e:
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

def main():
    """Entry point for MCP server"""
    server = MCPServer()
    server.run()


if __name__ == "__main__":
    main()
