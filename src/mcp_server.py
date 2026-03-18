#!/usr/bin/env python3
"""
TempleDB MCP Server - Model Context Protocol integration for Claude Code

Exposes templedb operations as native tools that Claude can invoke directly.
Uses stdio transport for local integration.
"""

import sys
import json
import logging
import os
import sqlite3
from typing import Any, Dict, List, Optional
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from repositories import ProjectRepository
from llm_context import TempleDBContext
from config import DB_PATH, PROJECT_ROOT
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

        # Register available tools
        self.tools = {
            "templedb_project_list": self.tool_project_list,
            "templedb_project_show": self.tool_project_show,
            "templedb_project_import": self.tool_project_import,
            "templedb_project_sync": self.tool_project_sync,
            "templedb_query": self.tool_query,
            "templedb_context_generate": self.tool_context_generate,
            "templedb_commit_list": self.tool_commit_list,
            "templedb_commit_create": self.tool_commit_create,
            "templedb_search_files": self.tool_search_files,
            "templedb_search_content": self.tool_search_content,
            # VCS operations
            "templedb_vcs_status": self.tool_vcs_status,
            "templedb_vcs_add": self.tool_vcs_add,
            "templedb_vcs_reset": self.tool_vcs_reset,
            "templedb_vcs_commit": self.tool_vcs_commit,
            "templedb_vcs_log": self.tool_vcs_log,
            "templedb_vcs_diff": self.tool_vcs_diff,
            "templedb_vcs_branch": self.tool_vcs_branch,
            # Deployment operations
            "templedb_deploy": self.tool_deploy,
            "templedb_env_get": self.tool_env_get,
            "templedb_env_set": self.tool_env_set,
            "templedb_env_list": self.tool_env_list,
            # Secret management operations
            "templedb_secret_list": self.tool_secret_list,
            "templedb_secret_export": self.tool_secret_export,
            "templedb_secret_show_keys": self.tool_secret_show_keys,
            # Cathedral package operations
            "templedb_cathedral_export": self.tool_cathedral_export,
            "templedb_cathedral_import": self.tool_cathedral_import,
            "templedb_cathedral_inspect": self.tool_cathedral_inspect,
        }

    def _get_db_connection(self):
        """Get or create database connection (reusable for queries)"""
        if self._db_conn is None:
            self._db_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            self._db_conn.row_factory = sqlite3.Row
        return self._db_conn

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
        """Return MCP tool definitions"""
        return [
            {
                "name": "templedb_project_list",
                "description": "List all projects tracked in TempleDB. Returns project names, IDs, slugs, and repository metadata.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "templedb_project_show",
                "description": "Show detailed information about a specific project including file counts, commits, and metadata.",
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
                "name": "templedb_project_import",
                "description": "Import a repository into TempleDB. Clones the repository and indexes all files for database-native tracking.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "repo_url": {
                            "type": "string",
                            "description": "Repository URL (http/https/ssh format)"
                        },
                        "name": {
                            "type": "string",
                            "description": "Optional project name (defaults to repo name)"
                        }
                    },
                    "required": ["repo_url"]
                }
            },
            {
                "name": "templedb_project_sync",
                "description": "Sync project with filesystem - scan for new/modified/deleted files and update database.",
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
                "name": "templedb_query",
                "description": "Execute SQL query against TempleDB. Use for complex queries across projects, files, commits.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "SQL query to execute"
                        },
                        "format": {
                            "type": "string",
                            "enum": ["json", "table", "csv"],
                            "description": "Output format (default: json)"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "templedb_context_generate",
                "description": "Generate LLM context for a project - includes schema, file tree, and key files.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "max_files": {
                            "type": "integer",
                            "description": "Maximum number of files to include (default: 50)"
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_commit_list",
                "description": "List recent commits for a project with messages and metadata.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of commits to return (default: 20)"
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_commit_create",
                "description": "Record a commit in TempleDB with ACID transaction. This tracks commits in the database for version control. Provide the commit hash from the underlying VCS, commit message, and project. TempleDB uses database-native version control.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "commit_hash": {
                            "type": "string",
                            "description": "VCS commit hash (SHA)"
                        },
                        "message": {
                            "type": "string",
                            "description": "Commit message"
                        },
                        "session_id": {
                            "type": "integer",
                            "description": "Optional agent session ID to associate"
                        }
                    },
                    "required": ["project", "commit_hash", "message"]
                }
            },
            {
                "name": "templedb_search_files",
                "description": "Search for files by path pattern across all projects or specific project.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Search pattern (SQL LIKE syntax, e.g. '%.py' or '%test%')"
                        },
                        "project": {
                            "type": "string",
                            "description": "Optional project to limit search"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum results (default: 50)"
                        }
                    },
                    "required": ["pattern"]
                }
            },
            {
                "name": "templedb_search_content",
                "description": "Search file contents across projects. Uses full-text search if available.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search term or phrase"
                        },
                        "project": {
                            "type": "string",
                            "description": "Optional project to limit search"
                        },
                        "file_pattern": {
                            "type": "string",
                            "description": "Optional file pattern to filter (e.g. '%.py')"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum results (default: 50)"
                        }
                    },
                    "required": ["query"]
                }
            },
            {
                "name": "templedb_vcs_status",
                "description": "Show working directory status for a project. This is the database-native equivalent of checking uncommitted changes. Shows staged, modified, and untracked files.",
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
                "name": "templedb_vcs_add",
                "description": "Stage files for commit in TempleDB. Use this to add files to the staging area before committing. This is database-native staging, not git.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of file paths to stage (use '.' for all)"
                        }
                    },
                    "required": ["project", "files"]
                }
            },
            {
                "name": "templedb_vcs_reset",
                "description": "Unstage files from the staging area. Removes files from staging without discarding changes.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of file paths to unstage (use '.' for all)"
                        }
                    },
                    "required": ["project", "files"]
                }
            },
            {
                "name": "templedb_vcs_commit",
                "description": "Create a commit in TempleDB with ACID transaction. This commits staged changes with a message and author. Database-native commit with full transaction safety.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "message": {
                            "type": "string",
                            "description": "Commit message"
                        },
                        "author": {
                            "type": "string",
                            "description": "Author name and email (e.g. 'Name <email@example.com>')"
                        },
                        "all": {
                            "type": "boolean",
                            "description": "Stage all modified files before committing (default: false)"
                        }
                    },
                    "required": ["project", "message", "author"]
                }
            },
            {
                "name": "templedb_vcs_log",
                "description": "Show commit history for a project. View the version control log with commits, messages, and timestamps.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Number of commits to show (default: 20)"
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_vcs_diff",
                "description": "Show differences between file versions. Compare working directory with staged/committed versions.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "file": {
                            "type": "string",
                            "description": "Optional specific file path to diff"
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_vcs_branch",
                "description": "List or create branches in TempleDB. Manage version control branches with database transactions.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "name": {
                            "type": "string",
                            "description": "Optional branch name to create"
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_deploy",
                "description": "Deploy a project from TempleDB to a deployment target. Executes deployment orchestration including migrations, builds, and environment setup.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "target": {
                            "type": "string",
                            "description": "Deployment target name (e.g., 'production', 'staging')"
                        },
                        "dry_run": {
                            "type": "boolean",
                            "description": "If true, show what would be deployed without executing (default: false)"
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_env_get",
                "description": "Get an environment variable value for a project. Retrieves configuration from TempleDB database.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "key": {
                            "type": "string",
                            "description": "Environment variable name"
                        }
                    },
                    "required": ["project", "key"]
                }
            },
            {
                "name": "templedb_env_set",
                "description": "Set an environment variable for a project. Stores configuration in TempleDB database with optional encryption.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "key": {
                            "type": "string",
                            "description": "Environment variable name"
                        },
                        "value": {
                            "type": "string",
                            "description": "Environment variable value"
                        },
                        "target": {
                            "type": "string",
                            "description": "Optional deployment target (e.g., 'production', 'development')"
                        }
                    },
                    "required": ["project", "key", "value"]
                }
            },
            {
                "name": "templedb_env_list",
                "description": "List all environment variables for a project. Shows configuration stored in TempleDB.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "target": {
                            "type": "string",
                            "description": "Optional filter by deployment target"
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_secret_list",
                "description": "List secrets for a project. Shows which secrets exist and their encryption status. Does not decrypt secret values.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "profile": {
                            "type": "string",
                            "description": "Secret profile (default: 'default')"
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_secret_export",
                "description": "Export and decrypt secrets for a project in various formats (shell, yaml, json, dotenv). Requires decryption keys to be available.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "profile": {
                            "type": "string",
                            "description": "Secret profile (default: 'default')"
                        },
                        "format": {
                            "type": "string",
                            "enum": ["shell", "yaml", "json", "dotenv"],
                            "description": "Output format (default: shell)"
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_secret_show_keys",
                "description": "Show which encryption keys protect a secret. Lists key names, types, and status.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "profile": {
                            "type": "string",
                            "description": "Secret profile (default: 'default')"
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_cathedral_export",
                "description": "Export a project as a .cathedral package (portable bundle with files, VCS history, and metadata).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug to export"
                        },
                        "output_dir": {
                            "type": "string",
                            "description": "Output directory for package (default: current directory)"
                        },
                        "compress": {
                            "type": "boolean",
                            "description": "Compress the package (default: true)"
                        },
                        "include_files": {
                            "type": "boolean",
                            "description": "Include file contents (default: true)"
                        },
                        "include_vcs": {
                            "type": "boolean",
                            "description": "Include VCS history (default: true)"
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_cathedral_import",
                "description": "Import a .cathedral package into TempleDB. Restores project with files, history, and metadata.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "package_path": {
                            "type": "string",
                            "description": "Path to .cathedral package file"
                        },
                        "overwrite": {
                            "type": "boolean",
                            "description": "Overwrite if project already exists (default: false)"
                        },
                        "new_slug": {
                            "type": "string",
                            "description": "Import with a different project slug (optional)"
                        }
                    },
                    "required": ["package_path"]
                }
            },
            {
                "name": "templedb_cathedral_inspect",
                "description": "Inspect a .cathedral package without importing it. Shows package metadata, file count, and structure.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "package_path": {
                            "type": "string",
                            "description": "Path to .cathedral package file"
                        }
                    },
                    "required": ["package_path"]
                }
            }
        ]

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
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT * FROM commits
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
            with sqlite3.connect(DB_PATH) as conn:
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
                        FROM files f
                        JOIN projects p ON f.project_id = p.id
                        WHERE f.project_id = ? AND f.file_path LIKE ?
                        ORDER BY f.file_path
                        LIMIT ?
                    """, (project['id'], pattern, limit))
                else:
                    cursor.execute("""
                        SELECT f.*, p.name as project_name
                        FROM files f
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
            cmd = ["./templedb", "vcs", "commit", "-p", project_name, "-m", message, "-a", author]
            if commit_all:
                cmd.append("--all")

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

            import subprocess
            cmd = ["./templedb", "deploy", "run", project_name]
            if target:
                cmd.extend(["--target", target])
            if dry_run:
                cmd.append("--dry-run")

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
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "templedb",
                            "version": "1.0.0"
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
                result = tool_func(tool_args)

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


def main():
    """Entry point for MCP server"""
    server = MCPServer()
    server.run()


if __name__ == "__main__":
    main()
