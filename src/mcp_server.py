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

    def tool_project_import(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Import a repository into TempleDB"""
        try:
            repo_url = args["repo_url"]
            name = args.get("name")

            # Import via CLI command
            cmd = ["project", "import", repo_url]
            if name:
                cmd.extend(["--name", name])

            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return {
                    "content": [{"type": "text", "text": f"Import failed: {result['stderr']}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result["stdout"]}]
            }
        except Exception as e:
            logger.error(f"Error importing project: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_project_sync(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Sync project with filesystem"""
        try:
            project_name = args["project"]

            result = self._run_templedb_cli(["project", "sync", project_name])

            if result["returncode"] != 0:
                return {
                    "content": [{"type": "text", "text": f"Sync failed: {result['stderr']}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result["stdout"]}]
            }
        except Exception as e:
            logger.error(f"Error syncing project: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_query(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute SQL query"""
        try:
            query = args["query"]
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

    def tool_commit_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List commits for project"""
        try:
            project_name = args["project"]
            limit = args.get("limit", 20)

            # Get project
            project = self.project_repo.get_by_slug(project_name)
            if not project:
                return {
                    "content": [{"type": "text", "text": f"Project '{project_name}' not found"}],
                    "isError": True
                }

            # Get commits
            import sqlite3
            conn = self._get_db_connection()
            with conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM vcs_commits
                    WHERE project_id = ?
                    ORDER BY commit_timestamp DESC
                    LIMIT ?
                """, (project['id'], limit))
                rows = cursor.fetchall()
                commits = [dict(row) for row in rows]

            return {
                "content": [{"type": "text", "text": json.dumps(commits, indent=2)}]
            }
        except Exception as e:
            logger.error(f"Error listing commits: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_commit_create(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create commit record"""
        try:
            project_name = args["project"]
            commit_hash = args["commit_hash"]
            message = args["message"]
            session_id = args.get("session_id")

            # Use CLI command
            import subprocess
            cmd = ["./templedb", "project", "commit", project_name, commit_hash, message]
            if session_id:
                cmd.extend(["--session-id", str(session_id)])

            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.templedb_root))

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Commit creation failed: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout}]
            }
        except Exception as e:
            logger.error(f"Error creating commit: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_search_files(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Search for files by path pattern"""
        try:
            pattern = args["pattern"]
            project_name = args.get("project")
            limit = args.get("limit", 50)

            import sqlite3
            conn = self._get_db_connection()
            with conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()

                if project_name:
                    project = self.project_repo.get_by_slug(project_name)
                    if not project:
                        return {
                            "content": [{"type": "text", "text": f"Project '{project_name}' not found"}],
                            "isError": True
                        }

                    cursor.execute("""
                        SELECT f.*, p.name as project_name
                        FROM project_files f
                        JOIN projects p ON f.project_id = p.id
                        WHERE f.project_id = ? AND f.file_path LIKE ?
                        ORDER BY f.file_path
                        LIMIT ?
                    """, (project['id'], pattern, limit))
                else:
                    cursor.execute("""
                        SELECT f.*, p.name as project_name
                        FROM project_files f
                        JOIN projects p ON f.project_id = p.id
                        WHERE f.file_path LIKE ?
                        ORDER BY f.file_path
                        LIMIT ?
                    """, (pattern, limit))

                rows = cursor.fetchall()
                results = [dict(row) for row in rows]

            return {
                "content": [{"type": "text", "text": json.dumps(results, indent=2)}]
            }
        except Exception as e:
            logger.error(f"Error searching files: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_search_content(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Search file contents"""
        try:
            query = args["query"]
            project_name = args.get("project")
            file_pattern = args.get("file_pattern")
            limit = args.get("limit", 50)

            # Use CLI search command
            import subprocess
            cmd = ["./templedb", "search", "content", query]
            if project_name:
                cmd.extend(["--project", project_name])
            if file_pattern:
                cmd.extend(["--pattern", file_pattern])
            cmd.extend(["--limit", str(limit)])

            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.templedb_root))

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Search failed: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout}]
            }
        except Exception as e:
            logger.error(f"Error searching content: {e}")
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

    def tool_vcs_add(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Stage files for commit"""
        try:
            project_name = args["project"]
            files = args["files"]

            import subprocess
            # Use --all flag when files is ["."] or empty rather than passing "." as a path
            if not files or files == ["."]:
                cmd = ["./templedb", "vcs", "add", "-p", project_name, "--all"]
            else:
                cmd = ["./templedb", "vcs", "add", "-p", project_name] + files
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.templedb_root))

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Stage failed: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout or f"Staged {len(files)} file(s)"}]
            }
        except Exception as e:
            logger.error(f"Error staging files: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_vcs_reset(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Unstage files"""
        try:
            project_name = args["project"]
            files = args["files"]

            import subprocess
            cmd = ["./templedb", "vcs", "reset", "-p", project_name] + files
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.templedb_root))

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Unstage failed: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout or f"Unstaged {len(files)} file(s)"}]
            }
        except Exception as e:
            logger.error(f"Error unstaging files: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_vcs_commit(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a commit"""
        try:
            project_name = args["project"]
            message = args["message"]
            author = args["author"]
            commit_all = args.get("all", False)

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

    def tool_vcs_log(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Show commit log"""
        try:
            project_name = args["project"]
            limit = args.get("limit", 20)

            import subprocess
            cmd = ["./templedb", "vcs", "log", project_name, "--limit", str(limit)]
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.templedb_root))

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Log retrieval failed: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout}]
            }
        except Exception as e:
            logger.error(f"Error retrieving log: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_vcs_edit(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Enter edit mode (make checkout writable)"""
        try:
            project_name = args["project"]
            reason = args.get("reason")

            import subprocess
            cmd = ["./templedb", "vcs", "edit", project_name]
            if reason:
                cmd.extend(["--reason", reason])

            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.templedb_root))

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Edit mode failed: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout or "Edit mode enabled"}]
            }
        except Exception as e:
            logger.error(f"Error entering edit mode: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_vcs_discard(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Discard changes and return to read-only mode"""
        try:
            project_name = args["project"]
            force = args.get("force", False)

            import subprocess
            cmd = ["./templedb", "vcs", "discard", project_name]
            if force:
                cmd.append("--force")

            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.templedb_root))

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Discard failed: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout or "Changes discarded, checkout is now read-only"}]
            }
        except Exception as e:
            logger.error(f"Error discarding changes: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_vcs_diff(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Show diff"""
        try:
            project_name = args["project"]
            file_path = args.get("file")

            import subprocess
            cmd = ["./templedb", "vcs", "diff", "-p", project_name]
            if file_path:
                cmd.append(file_path)

            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.templedb_root))

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Diff failed: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout or "No differences found"}]
            }
        except Exception as e:
            logger.error(f"Error showing diff: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_vcs_branch(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List or create branches"""
        try:
            project_name = args["project"]
            branch_name = args.get("name")

            import subprocess
            cmd = ["./templedb", "vcs", "branch", project_name]
            if branch_name:
                cmd.append(branch_name)

            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.templedb_root))

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Branch operation failed: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout}]
            }
        except Exception as e:
            logger.error(f"Error with branch operation: {e}")
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

    def tool_env_get(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get environment variable"""
        try:
            project_name = args["project"]
            key = args["key"]

            import subprocess
            result = subprocess.run(
                ["./templedb", "env", "get", "-p", project_name, "-k", key],
                capture_output=True, text=True, cwd=str(self.templedb_root)
            )

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Failed to get variable: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout.strip()}]
            }
        except Exception as e:
            logger.error(f"Error getting env variable: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_env_set(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Set environment variable"""
        try:
            project_name = args["project"]
            key = args["key"]
            value = args["value"]
            target = args.get("target")

            import subprocess
            cmd = ["./templedb", "env", "set", "-p", project_name, "-k", key, "-v", value]
            if target:
                cmd.extend(["--target", target])

            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.templedb_root))

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Failed to set variable: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout or f"Set {key}={value}"}]
            }
        except Exception as e:
            logger.error(f"Error setting env variable: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_env_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List environment variables"""
        try:
            project_name = args["project"]
            target = args.get("target")

            cmd = ["env", "vars", "-p", project_name]
            if target:
                cmd.extend(["--target", target])

            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return {
                    "content": [{"type": "text", "text": f"Failed to list variables: {result['stderr']}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result["stdout"]}]
            }
        except Exception as e:
            logger.error(f"Error listing env variables: {e}")
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

    def tool_config_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List system config values with optional key pattern filter"""
        try:
            key_pattern = args.get("key_pattern")

            conn = self._get_db_connection()
            cursor = conn.cursor()

            # Build query
            query = "SELECT key, value, description, updated_at FROM system_config WHERE 1=1"
            params = []

            if key_pattern:
                query += " AND key LIKE ?"
                params.append(f"%{key_pattern}%")

            query += " ORDER BY key"

            cursor.execute(query, params)
            rows = cursor.fetchall()
            results = [dict(row) for row in rows]

            if not results:
                return {"content": [{"type": "text", "text": "No configs found"}]}

            return {"content": [{"type": "text", "text": json.dumps(results, indent=2)}]}

        except Exception as e:
            logger.error(f"Error listing configs: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_config_delete(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Delete system config value (simple key-value store)"""
        try:
            key = args["key"]

            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                DELETE FROM system_config
                WHERE key = ?
            """, (key,))

            conn.commit()

            if cursor.rowcount == 0:
                return {
                    "content": [{"type": "text", "text": f"Config key '{key}' not found"}],
                    "isError": True
                }

            return {"content": [{"type": "text", "text": f"Deleted config key '{key}'"}]}

        except Exception as e:
            logger.error(f"Error deleting config: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_secret_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List secrets for a project"""
        try:
            project_name = args["project"]
            profile = args.get("profile", "default")

            # Get project
            project = self.project_repo.get_by_slug(project_name)
            if not project:
                return {
                    "content": [{"type": "text", "text": f"Project '{project_name}' not found"}],
                    "isError": True
                }

            # Query secrets from database
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT psb.profile, sb.secret_name, sb.content_type,
                       sb.created_at, sb.updated_at,
                       COUNT(ska.key_id) as key_count
                FROM project_secret_blobs psb
                JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
                LEFT JOIN secret_key_assignments ska ON sb.id = ska.secret_blob_id
                WHERE psb.project_id = ? AND psb.profile = ?
                GROUP BY psb.profile, sb.secret_name
            """, (project['id'], profile))

            rows = cursor.fetchall()
            results = [dict(row) for row in rows]

            if not results:
                return {
                    "content": [{"type": "text", "text": f"No secrets found for {project_name} (profile: {profile})"}]
                }

            return {
                "content": [{"type": "text", "text": json.dumps(results, indent=2)}]
            }
        except Exception as e:
            logger.error(f"Error listing secrets: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_secret_export(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Export and decrypt secrets for a project"""
        try:
            project_name = args["project"]
            profile = args.get("profile", "default")
            format_type = args.get("format", "shell")

            cmd = ["secret", "export", project_name, "--profile", profile, "--format", format_type]
            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return {
                    "content": [{"type": "text", "text": f"Export failed: {result['stderr']}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result["stdout"]}]
            }
        except Exception as e:
            logger.error(f"Error exporting secrets: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_secret_show_keys(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Show which encryption keys protect a secret"""
        try:
            project_name = args["project"]
            profile = args.get("profile", "default")

            cmd = ["secret", "show-keys", project_name, "--profile", profile]
            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return {
                    "content": [{"type": "text", "text": f"Failed to show keys: {result['stderr']}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result["stdout"]}]
            }
        except Exception as e:
            logger.error(f"Error showing secret keys: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_cathedral_export(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Export a project as a .cathedral package"""
        try:
            project_name = args["project"]
            output_dir = args.get("output_dir", ".")
            compress = args.get("compress", True)
            include_files = args.get("include_files", True)
            include_vcs = args.get("include_vcs", True)

            cmd = ["cathedral", "export", project_name, "--output", output_dir]
            if not compress:
                cmd.append("--no-compress")
            if not include_files:
                cmd.append("--no-files")
            if not include_vcs:
                cmd.append("--no-vcs")

            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return {
                    "content": [{"type": "text", "text": f"Export failed: {result['stderr']}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result["stdout"]}]
            }
        except Exception as e:
            logger.error(f"Error exporting cathedral package: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_cathedral_import(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Import a .cathedral package into TempleDB"""
        try:
            package_path = args["package_path"]
            overwrite = args.get("overwrite", False)
            new_slug = args.get("new_slug")

            cmd = ["cathedral", "import", package_path]
            if overwrite:
                cmd.append("--overwrite")
            if new_slug:
                cmd.extend(["--as-slug", new_slug])

            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return {
                    "content": [{"type": "text", "text": f"Import failed: {result['stderr']}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result["stdout"]}]
            }
        except Exception as e:
            logger.error(f"Error importing cathedral package: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_cathedral_inspect(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Inspect a .cathedral package without importing"""
        try:
            package_path = args["package_path"]

            cmd = ["cathedral", "inspect", package_path]
            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return {
                    "content": [{"type": "text", "text": f"Inspect failed: {result['stderr']}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result["stdout"]}]
            }
        except Exception as e:
            logger.error(f"Error inspecting cathedral package: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    # Fleet deployment tools

    def tool_fleet_network_create(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a fleet deployment network"""
        try:
            project = args["project"]
            network_name = args["network_name"]
            config_file = args.get("config_file")
            flake_uri = args.get("flake_uri")
            description = args.get("description")

            cmd = ["deploy", "fleet", "network", "create", project, network_name]
            if config_file:
                cmd.extend(["--config-file", config_file])
            if flake_uri:
                cmd.extend(["--flake-uri", flake_uri])
            if description:
                cmd.extend(["--description", description])

            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return self._error_response(
                    ErrorCode.INTERNAL_ERROR,
                    f"Failed to create network: {result['stderr']}"
                )

            return self._success_response(result["stdout"], format_json=False)
        except Exception as e:
            logger.error(f"Error creating fleet network: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_fleet_network_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List fleet deployment networks"""
        try:
            cmd = ["deploy", "fleet", "network", "list"]
            if "project" in args and args["project"]:
                cmd.extend(["--project", args["project"]])

            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return self._error_response(
                    ErrorCode.INTERNAL_ERROR,
                    f"Failed to list networks: {result['stderr']}"
                )

            return self._success_response(result["stdout"], format_json=False)
        except Exception as e:
            logger.error(f"Error listing fleet networks: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_fleet_network_info(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Show fleet network info"""
        try:
            project = args["project"]
            network = args["network"]

            result = self._run_templedb_cli(["deploy", "fleet", "network", "info", project, network])

            if result["returncode"] != 0:
                return self._error_response(
                    ErrorCode.INTERNAL_ERROR,
                    f"Failed to get network info: {result['stderr']}"
                )

            return self._success_response(result["stdout"], format_json=False)
        except Exception as e:
            logger.error(f"Error getting fleet network info: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_fleet_machine_add(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Add machine to fleet network"""
        try:
            project = args["project"]
            network = args["network"]
            machine_name = args["machine_name"]
            target_host = args["target_host"]
            target_user = args.get("target_user", "root")
            system_type = args.get("system_type", "nixos")

            cmd = ["deploy", "fleet", "machine", "add", project, network, machine_name,
                   "--host", target_host, "--user", target_user, "--system-type", system_type]

            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return self._error_response(
                    ErrorCode.INTERNAL_ERROR,
                    f"Failed to add machine: {result['stderr']}"
                )

            return self._success_response(result["stdout"], format_json=False)
        except Exception as e:
            logger.error(f"Error adding fleet machine: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_fleet_machine_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List machines in fleet network"""
        try:
            project = args["project"]
            network = args["network"]

            result = self._run_templedb_cli(["deploy", "fleet", "machine", "list", project, network])

            if result["returncode"] != 0:
                return self._error_response(
                    ErrorCode.INTERNAL_ERROR,
                    f"Failed to list machines: {result['stderr']}"
                )

            return self._success_response(result["stdout"], format_json=False)
        except Exception as e:
            logger.error(f"Error listing fleet machines: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_fleet_deploy(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Deploy fleet network with magic rollback"""
        try:
            project = args["project"]
            network = args["network"]
            machines = args.get("machines", [])
            dry_run = args.get("dry_run", False)
            build_only = args.get("build_only", False)
            no_watchdog = args.get("no_watchdog", False)
            watchdog_timeout = args.get("watchdog_timeout", 90)
            on_tags = args.get("on_tags", [])

            cmd = ["deploy", "fleet", "deploy", project, network]
            if machines:
                cmd.extend(["--machines"] + machines)
            if dry_run:
                cmd.append("--dry-run")
            if build_only:
                cmd.append("--build-only")
            if no_watchdog:
                cmd.append("--no-watchdog")
            if watchdog_timeout != 90:
                cmd.extend(["--watchdog-timeout", str(watchdog_timeout)])
            if on_tags:
                cmd.extend(["--on"] + on_tags)

            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return self._error_response(
                    ErrorCode.DEPLOYMENT_FAILED,
                    f"Deployment failed: {result['stderr']}"
                )

            return self._success_response(result["stdout"], format_json=False)
        except Exception as e:
            logger.error(f"Error deploying fleet network: {e}")
            return self._error_response(str(e), ErrorCode.DEPLOYMENT_FAILED)

    def tool_fleet_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Show fleet deployment status"""
        try:
            project = args["project"]
            network = args["network"]
            deployment_uuid = args.get("deployment_uuid")

            cmd = ["deploy", "fleet", "status", project, network]
            if deployment_uuid:
                cmd.extend(["--deployment-uuid", deployment_uuid])

            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return self._error_response(
                    ErrorCode.INTERNAL_ERROR,
                    f"Failed to get status: {result['stderr']}"
                )

            return self._success_response(result["stdout"], format_json=False)
        except Exception as e:
            logger.error(f"Error getting fleet status: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_fleet_check(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Health check fleet machines"""
        try:
            project = args["project"]
            network = args["network"]

            result = self._run_templedb_cli(["deploy", "fleet", "check", project, network])

            if result["returncode"] != 0:
                return self._error_response(
                    ErrorCode.INTERNAL_ERROR,
                    f"Health check failed: {result['stderr']}"
                )

            return self._success_response(result["stdout"], format_json=False)
        except Exception as e:
            logger.error(f"Error checking fleet: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_fleet_diff(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Show what would change if deployed"""
        try:
            project = args["project"]
            network = args["network"]
            machine = args.get("machine")

            cmd = ["deploy", "fleet", "diff", project, network]
            if machine:
                cmd.extend(["--machine", machine])

            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return self._error_response(
                    ErrorCode.INTERNAL_ERROR,
                    f"Diff failed: {result['stderr']}"
                )

            return self._success_response(result["stdout"], format_json=False)
        except Exception as e:
            logger.error(f"Error computing fleet diff: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    # ========================================================================
    # CODE INTELLIGENCE TOOLS (Phase 1.7)
    # ========================================================================

    def tool_code_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Search code using hybrid search (BM25 + graph ranking)"""
        try:
            from services.code_search_service import search_code
            from db_utils import get_project_by_slug

            project_slug = args["project"]
            query = args["query"]
            limit = args.get("limit", 10)
            symbol_type = args.get("symbol_type")

            # Get project
            project = get_project_by_slug(project_slug)
            if not project:
                return self._error_response(
                    f"Project '{project_slug}' not found",
                    ErrorCode.PROJECT_NOT_FOUND
                )

            # Check if search index exists
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM code_search_index csi
                JOIN code_symbols cs ON csi.symbol_id = cs.id
                WHERE cs.project_id = ?
            """, (project['id'],))

            if cursor.fetchone()[0] == 0:
                return self._error_response(
                    f"Search index not found for project '{project_slug}'. Run: templedb code index-search {project_slug}",
                    ErrorCode.NOT_FOUND
                )

            # Perform search
            results = search_code(project['id'], query, limit, symbol_type)

            # Format results
            formatted_results = []
            for r in results:
                formatted_results.append({
                    "qualified_name": r.qualified_name,
                    "symbol_type": r.symbol_type,
                    "file_path": r.file_path,
                    "start_line": r.start_line,
                    "docstring": r.docstring[:200] if r.docstring else None,
                    "score": round(r.final_score, 3),
                    "score_breakdown": {
                        "bm25": round(r.bm25_score, 3),
                        "graph": round(r.graph_score, 3),
                        "semantic": round(r.semantic_score, 3)
                    },
                    "num_dependents": r.num_dependents,
                    "cluster_name": r.cluster_name
                })

            return self._success_response({
                "query": query,
                "results_count": len(formatted_results),
                "results": formatted_results
            })

        except Exception as e:
            logger.error(f"Error in code search: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_code_show_symbol(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Show detailed information about a code symbol"""
        try:
            from db_utils import get_project_by_slug

            project_slug = args["project"]
            symbol_name = args["symbol_name"]

            # Get project
            project = get_project_by_slug(project_slug)
            if not project:
                return self._error_response(
                    f"Project '{project_slug}' not found",
                    ErrorCode.PROJECT_NOT_FOUND
                )

            conn = self._get_db_connection()
            cursor = conn.cursor()

            # Find symbol
            cursor.execute("""
                SELECT
                    cs.id, cs.symbol_type, cs.qualified_name,
                    cs.docstring, cs.start_line, cs.end_line,
                    cs.cyclomatic_complexity, cs.num_dependents,
                    pf.file_path
                FROM code_symbols cs
                JOIN project_files pf ON cs.file_id = pf.id
                WHERE cs.project_id = ?
                AND (cs.symbol_name = ? OR cs.qualified_name = ?)
                LIMIT 1
            """, (project['id'], symbol_name, symbol_name))

            symbol = cursor.fetchone()
            if not symbol:
                return self._error_response(
                    f"Symbol '{symbol_name}' not found in project",
                    ErrorCode.NOT_FOUND
                )

            symbol_id = symbol[0]

            # Get callers (who calls this symbol)
            cursor.execute("""
                SELECT cs.qualified_name, d.call_line, d.confidence_score
                FROM code_symbol_dependencies d
                JOIN code_symbols cs ON d.caller_symbol_id = cs.id
                WHERE d.called_symbol_id = ?
                ORDER BY cs.qualified_name
                LIMIT 20
            """, (symbol_id,))
            callers = [{"name": row[0], "line": row[1], "confidence": round(row[2], 2)}
                      for row in cursor.fetchall()]

            # Get callees (what this symbol calls)
            cursor.execute("""
                SELECT cs.qualified_name, d.call_line, d.confidence_score
                FROM code_symbol_dependencies d
                JOIN code_symbols cs ON d.called_symbol_id = cs.id
                WHERE d.caller_symbol_id = ?
                ORDER BY cs.qualified_name
                LIMIT 20
            """, (symbol_id,))
            callees = [{"name": row[0], "line": row[1], "confidence": round(row[2], 2)}
                      for row in cursor.fetchall()]

            # Get cluster membership
            cursor.execute("""
                SELECT cc.cluster_name, cc.cluster_type, ccm.membership_strength
                FROM code_cluster_members ccm
                JOIN code_clusters cc ON ccm.cluster_id = cc.id
                WHERE ccm.symbol_id = ?
            """, (symbol_id,))
            cluster_row = cursor.fetchone()
            cluster = None
            if cluster_row:
                cluster = {
                    "name": cluster_row[0],
                    "type": cluster_row[1],
                    "strength": round(cluster_row[2], 2)
                }

            return self._success_response({
                "qualified_name": symbol[2],
                "symbol_type": symbol[1],
                "file": f"{symbol[8]}:{symbol[4]}-{symbol[5]}",
                "docstring": symbol[3],
                "complexity": symbol[6],
                "num_dependents": symbol[7],
                "cluster": cluster,
                "called_by": callers,
                "calls": callees
            })

        except Exception as e:
            logger.error(f"Error showing symbol: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_code_show_clusters(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Show code clusters (architectural boundaries) for a project"""
        try:
            from services.community_detection_service import get_clusters_for_project
            from db_utils import get_project_by_slug

            project_slug = args["project"]
            include_members = args.get("include_members", False)
            limit = args.get("limit", 20)

            # Get project
            project = get_project_by_slug(project_slug)
            if not project:
                return self._error_response(
                    f"Project '{project_slug}' not found",
                    ErrorCode.PROJECT_NOT_FOUND
                )

            # Get clusters
            clusters = get_clusters_for_project(project['id'])

            if not clusters:
                return self._error_response(
                    f"No clusters found. Run: templedb code detect-clusters {project_slug}",
                    ErrorCode.NOT_FOUND
                )

            # Format clusters
            formatted_clusters = []
            for cluster in clusters[:limit]:
                cluster_data = {
                    "cluster_name": cluster['cluster_name'],
                    "cluster_type": cluster['cluster_type'],
                    "member_count": cluster['member_count'],
                    "cohesion_score": round(cluster['cohesion_score'], 3) if cluster['cohesion_score'] else None
                }

                # Optionally include member list
                if include_members:
                    conn = self._get_db_connection()
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT cs.qualified_name, cs.symbol_type
                        FROM code_cluster_members ccm
                        JOIN code_symbols cs ON ccm.symbol_id = cs.id
                        WHERE ccm.cluster_id = ?
                        ORDER BY cs.qualified_name
                        LIMIT 50
                    """, (cluster['cluster_id'],))

                    members = [{"name": row[0], "type": row[1]} for row in cursor.fetchall()]
                    cluster_data["members"] = members

                formatted_clusters.append(cluster_data)

            return self._success_response({
                "total_clusters": len(clusters),
                "showing": len(formatted_clusters),
                "clusters": formatted_clusters
            })

        except Exception as e:
            logger.error(f"Error showing clusters: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_code_impact_analysis(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze blast radius (impact) of changing a symbol"""
        try:
            from services.impact_analysis_service import analyze_symbol_impact
            from db_utils import get_project_by_slug

            project_slug = args["project"]
            symbol_name = args["symbol_name"]

            # Get project
            project = get_project_by_slug(project_slug)
            if not project:
                return self._error_response(
                    f"Project '{project_slug}' not found",
                    ErrorCode.PROJECT_NOT_FOUND
                )

            # Find symbol
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id FROM code_symbols
                WHERE project_id = ?
                AND (symbol_name = ? OR qualified_name = ?)
                LIMIT 1
            """, (project['id'], symbol_name, symbol_name))

            symbol_row = cursor.fetchone()
            if not symbol_row:
                return self._error_response(
                    f"Symbol '{symbol_name}' not found",
                    ErrorCode.NOT_FOUND
                )

            # Analyze impact
            analysis = analyze_symbol_impact(symbol_row[0])

            # Format critical paths
            critical_paths_formatted = []
            for path in analysis.critical_paths[:5]:
                critical_paths_formatted.append(" → ".join(path))

            return self._success_response({
                "symbol": {
                    "qualified_name": analysis.qualified_name,
                    "symbol_type": analysis.symbol_name
                },
                "blast_radius": {
                    "total_affected_symbols": analysis.blast_radius_count,
                    "max_depth": analysis.max_depth,
                    "avg_confidence": round(analysis.avg_confidence, 2),
                    "affected_files": len(analysis.affected_files)
                },
                "warnings": {
                    "is_entry_point": analysis.is_entry_point,
                    "is_widely_used": analysis.is_widely_used
                },
                "direct_dependents": [
                    {
                        "name": d['qualified_name'],
                        "confidence": round(d['confidence'], 2)
                    }
                    for d in analysis.direct_dependents[:10]
                ],
                "critical_paths": critical_paths_formatted,
                "affected_files_sample": analysis.affected_files[:10]
            })

        except Exception as e:
            logger.error(f"Error in impact analysis: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_code_extract_symbols(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Extract public symbols from project files (Phase 1.2)"""
        try:
            from services.symbol_extraction_service import extract_symbols_for_project
            from db_utils import get_project_by_slug

            project_slug = args["project"]
            force = args.get("force", False)

            # Get project
            project = get_project_by_slug(project_slug)
            if not project:
                return self._error_response(
                    f"Project '{project_slug}' not found",
                    ErrorCode.PROJECT_NOT_FOUND
                )

            # Extract symbols
            stats = extract_symbols_for_project(project['id'], force=force)

            return self._success_response({
                "project": project_slug,
                "stats": stats
            })

        except Exception as e:
            logger.error(f"Error extracting symbols: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_code_build_graph(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Build dependency graph for project (Phase 1.3)"""
        try:
            from services.dependency_graph_service import build_dependency_graph_for_project
            from db_utils import get_project_by_slug

            project_slug = args["project"]
            force = args.get("force", False)

            # Get project
            project = get_project_by_slug(project_slug)
            if not project:
                return self._error_response(
                    f"Project '{project_slug}' not found",
                    ErrorCode.PROJECT_NOT_FOUND
                )

            # Build graph
            stats = build_dependency_graph_for_project(project['id'], force=force)

            return self._success_response({
                "project": project_slug,
                "stats": stats
            })

        except Exception as e:
            logger.error(f"Error building graph: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_code_detect_clusters(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Detect code clusters using Leiden algorithm (Phase 1.5)"""
        try:
            from services.community_detection_service import detect_communities_for_project
            from db_utils import get_project_by_slug

            project_slug = args["project"]
            resolution = args.get("resolution", 1.0)

            # Get project
            project = get_project_by_slug(project_slug)
            if not project:
                return self._error_response(
                    f"Project '{project_slug}' not found",
                    ErrorCode.PROJECT_NOT_FOUND
                )

            # Detect clusters
            stats = detect_communities_for_project(project['id'], resolution=resolution)

            return self._success_response({
                "project": project_slug,
                "resolution": resolution,
                "stats": stats
            })

        except Exception as e:
            logger.error(f"Error detecting clusters: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_code_index_search(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Index project for hybrid search (Phase 1.6)"""
        try:
            from services.code_search_service import index_project_for_search
            from db_utils import get_project_by_slug

            project_slug = args["project"]

            # Get project
            project = get_project_by_slug(project_slug)
            if not project:
                return self._error_response(
                    f"Project '{project_slug}' not found",
                    ErrorCode.PROJECT_NOT_FOUND
                )

            # Index for search
            stats = index_project_for_search(project['id'])

            return self._success_response({
                "project": project_slug,
                "stats": stats
            })

        except Exception as e:
            logger.error(f"Error indexing for search: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    # ========================================================================
    # WORKFLOW ORCHESTRATION TOOLS (Phase 2.2)
    # ========================================================================

    def tool_workflow_execute(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a workflow with the given variables"""
        try:
            from services.workflow_orchestrator import execute_workflow
            from db_utils import get_project_by_slug

            workflow_name = args["workflow"]
            project_slug = args.get("project")
            variables = args.get("variables", {})
            dry_run = args.get("dry_run", False)

            # Construct workflow path
            workflow_path = self.templedb_root / "workflows" / f"{workflow_name}.yaml"

            if not workflow_path.exists():
                return self._error_response(
                    f"Workflow '{workflow_name}' not found. Available workflows: {self._list_available_workflows()}",
                    ErrorCode.WORKFLOW_NOT_FOUND
                )

            # If project is specified, validate it exists
            if project_slug:
                project = get_project_by_slug(project_slug)
                if not project:
                    return self._error_response(
                        f"Project '{project_slug}' not found",
                        ErrorCode.PROJECT_NOT_FOUND
                    )
                variables['project'] = project_slug

            # Execute workflow
            result = execute_workflow(
                workflow_path=str(workflow_path),
                project_slug=project_slug,
                variables=variables,
                dry_run=dry_run
            )

            # Format duration if present
            duration = result.get('duration')
            duration_str = f"{duration:.2f}s" if duration is not None else "N/A"

            return self._success_response({
                "workflow": workflow_name,
                "project": project_slug,
                "dry_run": dry_run,
                "status": result['status'],
                "duration": duration_str,
                "phases": result.get('phases', {}),
                "error": result.get('error'),
                "details": result.get('details')
            })

        except Exception as e:
            logger.error(f"Error executing workflow: {e}")
            return self._error_response(str(e), ErrorCode.WORKFLOW_EXECUTION_FAILED)

    def tool_workflow_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get status of a running or completed workflow (placeholder for future execution tracking)"""
        try:
            workflow_id = args.get("workflow_id")

            # For now, return a message that this requires execution tracking
            return self._success_response({
                "message": "Workflow execution tracking not yet implemented. Use templedb_workflow_execute with dry_run=false to execute workflows synchronously.",
                "workflow_id": workflow_id
            })

        except Exception as e:
            logger.error(f"Error getting workflow status: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_workflow_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List available workflows"""
        try:
            workflows_dir = self.templedb_root / "workflows"

            if not workflows_dir.exists():
                return self._success_response({
                    "workflows": [],
                    "count": 0
                })

            # Find all .yaml workflow files
            workflow_files = list(workflows_dir.glob("*.yaml"))

            workflows = []
            for workflow_file in workflow_files:
                try:
                    import yaml
                    with open(workflow_file, 'r') as f:
                        workflow_def = yaml.safe_load(f)

                    workflow_info = {
                        "name": workflow_file.stem,
                        "version": workflow_def.get('workflow', {}).get('version', 'unknown'),
                        "description": workflow_def.get('workflow', {}).get('description', ''),
                        "phases": len(workflow_def.get('workflow', {}).get('phases', [])),
                        "file": str(workflow_file.relative_to(self.templedb_root))
                    }
                    workflows.append(workflow_info)
                except Exception as e:
                    logger.warning(f"Error loading workflow {workflow_file}: {e}")
                    continue

            return self._success_response({
                "workflows": workflows,
                "count": len(workflows)
            })

        except Exception as e:
            logger.error(f"Error listing workflows: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_workflow_validate(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a workflow definition"""
        try:
            workflow_name = args["workflow"]

            # Construct workflow path
            workflow_path = self.templedb_root / "workflows" / f"{workflow_name}.yaml"

            if not workflow_path.exists():
                return self._error_response(
                    f"Workflow '{workflow_name}' not found",
                    ErrorCode.WORKFLOW_NOT_FOUND
                )

            # Try to load and validate the workflow
            import yaml

            try:
                with open(workflow_path, 'r') as f:
                    workflow_def = yaml.safe_load(f)
            except yaml.YAMLError as e:
                return self._error_response(
                    f"Invalid YAML syntax: {str(e)}",
                    ErrorCode.WORKFLOW_INVALID
                )

            # Validate workflow structure
            errors = []

            if 'workflow' not in workflow_def:
                errors.append("Missing 'workflow' key at root")
            else:
                workflow = workflow_def['workflow']

                if 'name' not in workflow:
                    errors.append("Missing 'workflow.name'")
                if 'version' not in workflow:
                    errors.append("Missing 'workflow.version'")
                if 'phases' not in workflow:
                    errors.append("Missing 'workflow.phases'")
                elif not isinstance(workflow['phases'], list):
                    errors.append("'workflow.phases' must be a list")
                else:
                    # Validate each phase
                    for i, phase in enumerate(workflow['phases']):
                        if 'name' not in phase:
                            errors.append(f"Phase {i}: missing 'name'")
                        if 'tasks' not in phase:
                            errors.append(f"Phase {i} ({phase.get('name', 'unnamed')}): missing 'tasks'")

            if errors:
                return self._error_response(
                    f"Workflow validation failed",
                    ErrorCode.WORKFLOW_VALIDATION_FAILED,
                    {"errors": errors}
                )

            return self._success_response({
                "workflow": workflow_name,
                "valid": True,
                "name": workflow_def['workflow'].get('name'),
                "version": workflow_def['workflow'].get('version'),
                "phases": len(workflow_def['workflow'].get('phases', []))
            })

        except Exception as e:
            logger.error(f"Error validating workflow: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def _list_available_workflows(self) -> str:
        """Helper to list available workflow names"""
        workflows_dir = self.templedb_root / "workflows"
        if not workflows_dir.exists():
            return "none"
        workflow_files = list(workflows_dir.glob("*.yaml"))
        return ", ".join([f.stem for f in workflow_files]) if workflow_files else "none"

    # Context Management Tools

    def tool_context_set_default(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Set default project context for the session"""
        try:
            project = args.get("project")

            # Handle clearing the context
            if not project or project == "null":
                self._default_project = None
                return self._success_response({
                    "status": "cleared",
                    "message": "Default project context cleared"
                })

            # Validate project exists
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, slug FROM projects
                WHERE name = ? OR slug = ?
            """, (project, project))

            row = cursor.fetchone()
            if not row:
                return self._error_response(
                    f"Project '{project}' not found",
                    ErrorCode.PROJECT_NOT_FOUND,
                    {"project": project}
                )

            # Set the default
            self._default_project = row["slug"]

            return self._success_response({
                "status": "set",
                "project": row["slug"],
                "name": row["name"],
                "message": f"Default project set to '{row['name']}' (slug: {row['slug']})"
            })

        except Exception as e:
            logger.error(f"Error setting default project: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_context_get_default(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get current default project context"""
        try:
            if not self._default_project:
                return self._success_response({
                    "status": "none",
                    "project": None,
                    "message": "No default project set"
                })

            # Get project details
            conn = self._get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, name, slug FROM projects
                WHERE slug = ?
            """, (self._default_project,))

            row = cursor.fetchone()
            if not row:
                # Project was deleted, clear the default
                self._default_project = None
                return self._success_response({
                    "status": "none",
                    "project": None,
                    "message": "Default project was deleted"
                })

            return self._success_response({
                "status": "set",
                "project": row["slug"],
                "name": row["name"],
                "message": f"Default project is '{row['name']}' (slug: {row['slug']})"
            })

        except Exception as e:
            logger.error(f"Error getting default project: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_schema_explore(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Explore database schema with natural language queries"""
        try:
            query = args.get("query", "").lower()
            project = args.get("project") or self._default_project

            conn = self._get_db_connection()
            cursor = conn.cursor()

            # Pattern matching for common queries
            response_data = {}

            # "What tables exist?" or "List tables" or "Show tables"
            if any(phrase in query for phrase in ["what tables", "list tables", "show tables", "available tables"]):
                cursor.execute("""
                    SELECT name, type FROM sqlite_master
                    WHERE type IN ('table', 'view')
                    ORDER BY type, name
                """)
                tables = cursor.fetchall()

                response_data = {
                    "query": query,
                    "tables": [{"name": row["name"], "type": row["type"]} for row in tables],
                    "count": len(tables),
                    "summary": f"Found {len(tables)} tables/views in TempleDB schema"
                }

            # "Show me projects" or "List projects"
            elif any(phrase in query for phrase in ["projects schema", "project table", "show projects", "list projects"]):
                cursor.execute("SELECT COUNT(*) as count FROM projects")
                count = cursor.fetchone()["count"]

                cursor.execute("""
                    SELECT name, slug, created_at
                    FROM projects
                    ORDER BY created_at DESC
                    LIMIT 10
                """)
                projects = cursor.fetchall()

                response_data = {
                    "query": query,
                    "total_projects": count,
                    "recent_projects": [dict(row) for row in projects],
                    "summary": f"Total of {count} projects tracked in TempleDB"
                }

            # "What file types?" or "File extensions"
            elif any(phrase in query for phrase in ["file types", "file extensions", "what extensions"]):
                if project:
                    cursor.execute("""
                        SELECT p.id FROM projects p
                        WHERE p.name = ? OR p.slug = ?
                    """, (project, project))
                    project_row = cursor.fetchone()
                    if not project_row:
                        return self._error_response(
                            f"Project '{project}' not found",
                            ErrorCode.PROJECT_NOT_FOUND
                        )
                    project_id = project_row["id"]

                    # Get file extensions - extract from last occurrence of '.'
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
                        LIMIT 20
                    """, (project_id,))
                else:
                    cursor.execute("""
                        SELECT
                            CASE
                                WHEN INSTR(file_name, '.') > 0
                                THEN SUBSTR(file_name, INSTR(file_name, '.'))
                                ELSE '(no extension)'
                            END as extension,
                            COUNT(*) as count
                        FROM project_files
                        GROUP BY extension
                        ORDER BY count DESC
                        LIMIT 20
                    """)

                file_types = cursor.fetchall()
                total_files = sum(row["count"] for row in file_types)

                response_data = {
                    "query": query,
                    "project": project,
                    "file_types": [{"extension": row["extension"], "count": row["count"]} for row in file_types],
                    "total_files": total_files,
                    "summary": f"Found {len(file_types)} file types across {total_files} files" + (f" in project '{project}'" if project else "")
                }

            # "How many commits?" or "Commit statistics"
            elif any(phrase in query for phrase in ["commits", "commit statistics", "how many commits"]):
                if project:
                    cursor.execute("""
                        SELECT p.id FROM projects p
                        WHERE p.name = ? OR p.slug = ?
                    """, (project, project))
                    project_row = cursor.fetchone()
                    if not project_row:
                        return self._error_response(
                            f"Project '{project}' not found",
                            ErrorCode.PROJECT_NOT_FOUND
                        )
                    project_id = project_row["id"]

                    cursor.execute("""
                        SELECT COUNT(*) as count
                        FROM vcs_commits
                        WHERE project_id = ?
                    """, (project_id,))
                    count = cursor.fetchone()["count"]

                    cursor.execute("""
                        SELECT message, created_at
                        FROM vcs_commits
                        WHERE project_id = ?
                        ORDER BY created_at DESC
                        LIMIT 5
                    """, (project_id,))
                    recent = cursor.fetchall()

                    response_data = {
                        "query": query,
                        "project": project,
                        "total_commits": count,
                        "recent_commits": [dict(row) for row in recent],
                        "summary": f"Project '{project}' has {count} commits"
                    }
                else:
                    cursor.execute("""
                        SELECT
                            p.name,
                            p.slug,
                            COUNT(c.id) as commit_count
                        FROM projects p
                        LEFT JOIN vcs_commits c ON c.project_id = p.id
                        GROUP BY p.id
                        ORDER BY commit_count DESC
                    """)
                    stats = cursor.fetchall()

                    total_commits = sum(row["commit_count"] for row in stats)

                    response_data = {
                        "query": query,
                        "commit_statistics": [dict(row) for row in stats],
                        "total_commits": total_commits,
                        "summary": f"Total of {total_commits} commits across all projects"
                    }

            # Generic schema info
            elif any(phrase in query for phrase in ["schema", "database structure"]):
                cursor.execute("""
                    SELECT name, sql
                    FROM sqlite_master
                    WHERE type = 'table'
                    AND name NOT LIKE 'sqlite_%'
                    ORDER BY name
                """)
                tables = cursor.fetchall()

                response_data = {
                    "query": query,
                    "tables": [{"name": row["name"], "schema": row["sql"]} for row in tables],
                    "count": len(tables),
                    "summary": f"Database contains {len(tables)} tables"
                }

            else:
                # Unknown query - provide helpful suggestions
                response_data = {
                    "query": query,
                    "error": "Query not understood",
                    "suggestions": [
                        "What tables exist?",
                        "Show me projects",
                        "What file types are tracked?",
                        "How many commits?",
                        "Show database schema"
                    ],
                    "summary": "Try one of the suggested queries or be more specific"
                }

            return self._success_response(response_data)

        except Exception as e:
            logger.error(f"Error exploring schema: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

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

    def tool_file_get(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Get file content"""
        try:
            project_name = args["project"]
            file_path = args["file_path"]

            import subprocess
            cmd = ["./templedb", "file", "get", project_name, file_path]
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(self.templedb_root))

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Failed to get file: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout}]
            }
        except Exception as e:
            logger.error(f"Error getting file: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_file_set(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Set file content"""
        try:
            project_name = args["project"]
            file_path = args["file_path"]
            content = args["content"]
            stage = args.get("stage", False)

            import subprocess
            # Use stdin to pass content to templedb file set
            cmd = ["./templedb", "file", "set", project_name, file_path]
            if stage:
                cmd.append("--stage")

            result = subprocess.run(
                cmd,
                input=content,
                capture_output=True,
                text=True,
                cwd=str(self.templedb_root)
            )

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Failed to set file: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout or "File updated successfully"}]
            }
        except Exception as e:
            logger.error(f"Error setting file: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    # ========================================================================
    # README Cross-Reference System Tools
    # ========================================================================

    def tool_readme_scan(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Scan project for README files and register them"""
        try:
            project_slug = args["project"]

            # Run CLI command
            result = self._run_templedb_cli(["readme", "scan", project_slug])

            if result["returncode"] != 0:
                return self._error_response(
                    f"Failed to scan README files: {result['stderr']}",
                    ErrorCode.INTERNAL_ERROR
                )

            return self._success_response(result["stdout"], format_json=False)

        except Exception as e:
            logger.error(f"Error scanning README files: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_readme_create(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new README file with metadata"""
        try:
            project_slug = args["project"]
            file_path = args["file_path"]
            title = args["title"]
            content = args["content"]
            category = args.get("category")
            topics = args.get("topics", [])

            # Build CLI command
            cmd = ["readme", "create", project_slug, file_path,
                   "--title", title]

            if category:
                cmd.extend(["--category", category])

            for topic in topics:
                cmd.extend(["--topic", topic])

            # Use subprocess with stdin for content
            import subprocess
            full_cmd = [str(self.templedb_root / "templedb")] + cmd

            result = subprocess.run(
                full_cmd,
                input=content,
                capture_output=True,
                text=True,
                cwd=str(self.templedb_root)
            )

            if result.returncode != 0:
                return self._error_response(
                    f"Failed to create README: {result.stderr}",
                    ErrorCode.INTERNAL_ERROR
                )

            return self._success_response(result.stdout, format_json=False)

        except Exception as e:
            logger.error(f"Error creating README: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_readme_add_topic(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Add topic tag to a README"""
        try:
            readme_id = args["readme_id"]
            topic = args["topic"]
            relevance = args.get("relevance", 1.0)

            # Insert into database
            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT OR REPLACE INTO readme_topics (readme_id, topic, relevance, source)
                VALUES (?, ?, ?, 'manual')
            """, (readme_id, topic, relevance))
            conn.commit()

            return self._success_response(f"Added topic '{topic}' to README {readme_id}")

        except Exception as e:
            logger.error(f"Error adding topic: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_readme_add_reference(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Add cross-reference between READMEs"""
        try:
            source_id = args["source_readme_id"]
            target_id = args.get("target_readme_id")
            target_url = args.get("target_url")
            link_text = args["link_text"]
            section = args.get("section")

            # Insert into database
            conn = self._get_db_connection()
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO readme_references
                (source_readme_id, target_readme_id, target_external_url, link_text, section)
                VALUES (?, ?, ?, ?, ?)
            """, (source_id, target_id, target_url, link_text, section))
            conn.commit()

            return self._success_response(f"Added reference from README {source_id}")

        except Exception as e:
            logger.error(f"Error adding reference: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_readme_generate_index(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Generate index section for README"""
        try:
            readme_id = args["readme_id"]
            template = args.get("template")

            cmd = ["readme", "generate-index", str(readme_id)]
            if template:
                cmd.extend(["--template", template])

            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return self._error_response(
                    f"Failed to generate index: {result['stderr']}",
                    ErrorCode.INTERNAL_ERROR
                )

            return self._success_response(result["stdout"], format_json=False)

        except Exception as e:
            logger.error(f"Error generating index: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_readme_find_related(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Find related README files"""
        try:
            readme_id = args["readme_id"]
            limit = args.get("limit", 10)

            conn = self._get_db_connection()
            cursor = conn.cursor()

            # Use the related_readmes view
            cursor.execute("""
                SELECT
                    rr.related_readme_id,
                    rf.title,
                    rf.file_path,
                    p.slug as project_slug,
                    rr.shared_topics,
                    rr.relevance_score
                FROM related_readmes rr
                JOIN readme_files rf ON rr.related_readme_id = rf.id
                JOIN projects p ON rf.project_id = p.id
                WHERE rr.readme_id = ?
                ORDER BY rr.relevance_score DESC
                LIMIT ?
            """, (readme_id, limit))

            results = [dict(row) for row in cursor.fetchall()]
            return self._success_response(results)

        except Exception as e:
            logger.error(f"Error finding related READMEs: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_readme_verify_links(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Verify README links and report broken ones"""
        try:
            project_slug = args.get("project")

            cmd = ["readme", "verify-links"]
            if project_slug:
                cmd.append(project_slug)

            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return self._error_response(
                    f"Failed to verify links: {result['stderr']}",
                    ErrorCode.INTERNAL_ERROR
                )

            return self._success_response(result["stdout"], format_json=False)

        except Exception as e:
            logger.error(f"Error verifying links: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_readme_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List README files with metadata"""
        try:
            project_slug = args.get("project")
            category = args.get("category")
            topic = args.get("topic")

            conn = self._get_db_connection()
            cursor = conn.cursor()

            # Build query with optional filters
            query = "SELECT * FROM readme_files_with_topics WHERE 1=1"
            params = []

            if project_slug:
                query += " AND project_slug = ?"
                params.append(project_slug)

            if category:
                query += " AND category = ?"
                params.append(category)

            if topic:
                query += " AND topics LIKE ?"
                params.append(f"%{topic}%")

            query += " ORDER BY index_priority DESC, title"

            cursor.execute(query, params)
            results = [dict(row) for row in cursor.fetchall()]

            return self._success_response(results)

        except Exception as e:
            logger.error(f"Error listing READMEs: {e}")
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    # ── New tools: mount, db, git-export, dotfiles, bootstrap ─────────

    def tool_mount_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Check FUSE mount status"""
        try:
            mounts = []
            with open("/proc/mounts") as f:
                for line in f:
                    if "fuse" in line.lower() and "temple" in line.lower():
                        parts = line.split()
                        mounts.append({"mountpoint": parts[1], "type": parts[2]})
            return self._success_response({
                "mounted": len(mounts) > 0,
                "mounts": mounts,
                "hint": f"Mount with: templedb mount {FUSE_MOUNT_PATH}" if not mounts else None,
            })
        except Exception as e:
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_db_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Show migration status"""
        try:
            from migrator import Migrator
            m = Migrator(DB_PATH)
            status = m.status()
            return self._success_response({
                "applied": sum(1 for s in status if s["applied"]),
                "pending": sum(1 for s in status if not s["applied"]),
                "migrations": status,
            })
        except Exception as e:
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_db_migrate(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Apply pending migrations"""
        try:
            from migrator import Migrator
            dry_run = args.get("dry_run", False)
            m = Migrator(DB_PATH)
            applied, skipped = m.migrate(dry_run=dry_run)
            return self._success_response({
                "applied": applied,
                "skipped": skipped,
                "dry_run": dry_run,
            })
        except Exception as e:
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_git_export(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Export VCS history as git repo"""
        try:
            from git_export import export_to_git
            project = args["project"]
            output_dir = args.get("output_dir", f"/tmp/templedb-git-{project}")
            remote_url = args.get("remote_url")
            result = export_to_git(
                project_slug=project,
                output_dir=output_dir,
                remote_url=remote_url,
            )
            return self._success_response(result)
        except Exception as e:
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_dotfiles_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List dotfile mappings and status"""
        try:
            import json
            from pathlib import Path
            conn = self._get_db_connection()
            row = conn.execute(
                "SELECT value FROM system_config WHERE key = 'nixos.dotfiles'"
            ).fetchone()
            if not row:
                return self._success_response({"dotfiles": [], "count": 0})

            manifest = json.loads(row[0])
            checkouts = Path.home() / ".config/templedb/checkouts"
            result = []
            for entry in manifest:
                src = checkouts / entry["project"] / entry["source"]
                tgt = Path(entry["target"]).expanduser()
                if tgt.is_symlink() and tgt.resolve() == src.resolve():
                    status = "linked"
                elif tgt.exists():
                    status = "conflict"
                elif not src.exists():
                    status = "no_source"
                else:
                    status = "not_linked"
                result.append({**entry, "status": status})
            return self._success_response({"dotfiles": result, "count": len(result)})
        except Exception as e:
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_bootstrap_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Check bootstrap readiness"""
        try:
            import json
            from pathlib import Path
            from migrator import Migrator
            home = Path.home()

            # Age key
            age_paths = [home / ".age/key.txt", home / ".config/sops/age/keys.txt"]
            age_ok = any(p.exists() for p in age_paths)

            # Migrations
            m = Migrator(DB_PATH)
            status = m.status()
            mig_pending = sum(1 for s in status if not s["applied"])

            # Checkouts
            co_dir = home / ".config/templedb/checkouts"
            checkouts = sum(1 for p in co_dir.iterdir() if p.is_dir()) if co_dir.exists() else 0

            # Dotfiles
            conn = self._get_db_connection()
            df_row = conn.execute(
                "SELECT value FROM system_config WHERE key = 'nixos.dotfiles'"
            ).fetchone()
            dotfiles_count = len(json.loads(df_row[0])) if df_row else 0

            # Projects
            proj_count = conn.execute("SELECT COUNT(*) as n FROM projects").fetchone()[0]

            return self._success_response({
                "age_key_found": age_ok,
                "migrations_pending": mig_pending,
                "checkouts": checkouts,
                "projects": proj_count,
                "dotfiles_configured": dotfiles_count,
                "ready": age_ok and mig_pending == 0,
            })
        except Exception as e:
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

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

    def tool_graph_deps(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Project dependency graph."""
        try:
            from knowledge_graph import project_dependencies
            results = project_dependencies(args["project"])
            return self._success_response(results)
        except Exception as e:
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_nixos_host_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List NixOS hosts."""
        try:
            conn = self._get_db_connection()
            hosts = conn.execute(
                "SELECT key, value FROM system_config WHERE key LIKE 'nixos.host.%' ORDER BY key"
            ).fetchall()
            active = conn.execute(
                "SELECT value FROM system_config WHERE key = 'nixos.flake_output'"
            ).fetchone()
            active_host = active[0] if active else None

            result = []
            for h in hosts:
                hostname = h["key"].replace("nixos.host.", "")
                overrides = conn.execute(
                    "SELECT COUNT(*) as n FROM system_config WHERE key LIKE ?",
                    (f"{hostname}.%",)
                ).fetchone()
                result.append({
                    "hostname": hostname,
                    "config_file": h["value"],
                    "overrides": overrides["n"],
                    "active": hostname == active_host,
                })
            return self._success_response({"hosts": result})
        except Exception as e:
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)

    def tool_nixos_generate_all(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Regenerate all NixOS config."""
        try:
            import subprocess, shutil
            host = args.get("host", "")
            cmd_parts = ["nixos", "generate-all"]
            if host:
                cmd_parts.extend(["--host", host])

            templedb = shutil.which("templedb") or str(Path(__file__).parent.parent / "templedb")
            result = subprocess.run(
                [templedb] + cmd_parts,
                capture_output=True, text=True, timeout=120
            )
            return self._success_response({
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            })
        except Exception as e:
            return self._error_response(str(e), ErrorCode.INTERNAL_ERROR)


def main():
    """Entry point for MCP server"""
    server = MCPServer()
    server.run()


if __name__ == "__main__":
    main()
