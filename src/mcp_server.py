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
            "templedb_vcs_edit": self.tool_vcs_edit,
            "templedb_vcs_discard": self.tool_vcs_discard,
            "templedb_vcs_diff": self.tool_vcs_diff,
            "templedb_vcs_branch": self.tool_vcs_branch,
            # File operations
            "templedb_file_get": self.tool_file_get,
            "templedb_file_set": self.tool_file_set,
            # Deployment operations
            "templedb_deploy": self.tool_deploy,
            "templedb_env_get": self.tool_env_get,
            "templedb_env_set": self.tool_env_set,
            "templedb_env_list": self.tool_env_list,
            # System configuration management
            "templedb_config_get": self.tool_config_get,
            "templedb_config_set": self.tool_config_set,
            "templedb_config_list": self.tool_config_list,
            "templedb_config_delete": self.tool_config_delete,
            # Secret management operations
            "templedb_secret_list": self.tool_secret_list,
            "templedb_secret_export": self.tool_secret_export,
            "templedb_secret_show_keys": self.tool_secret_show_keys,
            # Cathedral package operations
            "templedb_cathedral_export": self.tool_cathedral_export,
            "templedb_cathedral_import": self.tool_cathedral_import,
            "templedb_cathedral_inspect": self.tool_cathedral_inspect,
            # NixOps4 deployment orchestration
            "templedb_nixops4_network_create": self.tool_nixops4_network_create,
            "templedb_nixops4_network_list": self.tool_nixops4_network_list,
            "templedb_nixops4_network_info": self.tool_nixops4_network_info,
            "templedb_nixops4_machine_add": self.tool_nixops4_machine_add,
            "templedb_nixops4_machine_list": self.tool_nixops4_machine_list,
            "templedb_nixops4_deploy": self.tool_nixops4_deploy,
            "templedb_nixops4_status": self.tool_nixops4_status,
            # Code Intelligence (Phase 1.7)
            "templedb_code_search": self.tool_code_search,
            "templedb_code_show_symbol": self.tool_code_show_symbol,
            "templedb_code_show_clusters": self.tool_code_show_clusters,
            "templedb_code_impact_analysis": self.tool_code_impact_analysis,
            "templedb_code_extract_symbols": self.tool_code_extract_symbols,
            "templedb_code_build_graph": self.tool_code_build_graph,
            "templedb_code_detect_clusters": self.tool_code_detect_clusters,
            "templedb_code_index_search": self.tool_code_index_search,
            # Workflow Orchestration (Phase 2.2)
            "templedb_workflow_execute": self.tool_workflow_execute,
            "templedb_workflow_status": self.tool_workflow_status,
            "templedb_workflow_list": self.tool_workflow_list,
            "templedb_workflow_validate": self.tool_workflow_validate,
            # Context management
            "templedb_context_set_default": self.tool_context_set_default,
            "templedb_context_get_default": self.tool_context_get_default,
            # Schema exploration
            "templedb_schema_explore": self.tool_schema_explore,
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
                "description": "Show working directory status for a project. This is the database-native equivalent of checking uncommitted changes. Shows staged, modified, and untracked files, as well as checkout mode (read-only or writable edit mode) and edit session information.",
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
                "description": "Create a commit in TempleDB with ACID transaction. This commits staged changes with a message and author. Database-native commit with full transaction safety. Automatically ends any active edit session and returns checkout to read-only mode.",
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
                "name": "templedb_vcs_edit",
                "description": "Enter edit mode for a project checkout. Makes the checkout writable and starts an edit session. Checkouts are read-only by default; use this to enable editing. Use vcs_commit to save changes or vcs_discard to revert.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "reason": {
                            "type": "string",
                            "description": "Optional reason for entering edit mode (for tracking)"
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_vcs_discard",
                "description": "Discard uncommitted changes and return to read-only mode. Reverts the checkout to the last committed state and ends the edit session. Use --force to discard without confirmation.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "force": {
                            "type": "boolean",
                            "description": "Force discard without confirmation (default: false)"
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_file_get",
                "description": "Get file content as string from TempleDB. Returns file content from TempleDB-tracked file. Use this to read files before editing them with file_set.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "file_path": {
                            "type": "string",
                            "description": "Path to file within project"
                        }
                    },
                    "required": ["project", "file_path"]
                }
            },
            {
                "name": "templedb_file_set",
                "description": "Set file content from string. Writes content to file in project working directory. Optionally stages the file after writing. Note: Checkout must be in edit mode (use vcs_edit) to write files.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "file_path": {
                            "type": "string",
                            "description": "Path to file within project"
                        },
                        "content": {
                            "type": "string",
                            "description": "Content to write to file"
                        },
                        "stage": {
                            "type": "boolean",
                            "description": "Whether to stage file after writing (default: false)"
                        }
                    },
                    "required": ["project", "file_path", "content"]
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
                "name": "templedb_config_get",
                "description": "Get a system configuration value (simple key-value store)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Configuration key (e.g., 'nginx.workers', 'woofs.enable', 'nixos.hostname')"
                        }
                    },
                    "required": ["key"]
                }
            },
            {
                "name": "templedb_config_set",
                "description": "Set a system configuration value (simple key-value store)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Configuration key (e.g., 'nixos.hostname', 'nixos.username', 'templedb.executable_path')"
                        },
                        "value": {
                            "type": "string",
                            "description": "Configuration value"
                        },
                        "description": {
                            "type": "string",
                            "description": "Optional description of this config value"
                        }
                    },
                    "required": ["key", "value"]
                }
            },
            {
                "name": "templedb_config_list",
                "description": "List system configuration values with optional key pattern filter",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key_pattern": {
                            "type": "string",
                            "description": "Filter by key pattern (SQL LIKE syntax, e.g., 'nixos%' for all nixos keys)"
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "templedb_config_delete",
                "description": "Delete a system configuration value (simple key-value store)",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "key": {
                            "type": "string",
                            "description": "Configuration key to delete"
                        }
                    },
                    "required": ["key"]
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
            },
            {
                "name": "templedb_nixops4_network_create",
                "description": "Create a new NixOps4 deployment network for declarative infrastructure management.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project slug"
                        },
                        "network_name": {
                            "type": "string",
                            "description": "Network name (e.g., 'production', 'staging')"
                        },
                        "config_file": {
                            "type": "string",
                            "description": "Path to network configuration file (optional)"
                        },
                        "flake_uri": {
                            "type": "string",
                            "description": "Flake URI for network configuration (optional)"
                        },
                        "description": {
                            "type": "string",
                            "description": "Network description (optional)"
                        }
                    },
                    "required": ["project", "network_name"]
                }
            },
            {
                "name": "templedb_nixops4_network_list",
                "description": "List all NixOps4 deployment networks, optionally filtered by project.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Filter by project slug (optional)"
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "templedb_nixops4_network_info",
                "description": "Show detailed information about a NixOps4 network including machines, resources, and deployment history.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project slug"
                        },
                        "network": {
                            "type": "string",
                            "description": "Network name"
                        }
                    },
                    "required": ["project", "network"]
                }
            },
            {
                "name": "templedb_nixops4_machine_add",
                "description": "Add a machine to a NixOps4 network for deployment.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project slug"
                        },
                        "network": {
                            "type": "string",
                            "description": "Network name"
                        },
                        "machine_name": {
                            "type": "string",
                            "description": "Machine name"
                        },
                        "target_host": {
                            "type": "string",
                            "description": "Target hostname or IP address"
                        },
                        "target_user": {
                            "type": "string",
                            "description": "SSH user (default: root)"
                        },
                        "system_type": {
                            "type": "string",
                            "description": "System type: nixos, linux, darwin (default: nixos)"
                        }
                    },
                    "required": ["project", "network", "machine_name", "target_host"]
                }
            },
            {
                "name": "templedb_nixops4_machine_list",
                "description": "List all machines in a NixOps4 network with their deployment status.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project slug"
                        },
                        "network": {
                            "type": "string",
                            "description": "Network name"
                        }
                    },
                    "required": ["project", "network"]
                }
            },
            {
                "name": "templedb_nixops4_deploy",
                "description": "Deploy a NixOps4 network to all machines or specific machines. Executes declarative NixOS deployment.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project slug"
                        },
                        "network": {
                            "type": "string",
                            "description": "Network name"
                        },
                        "machines": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Specific machines to deploy (optional, default: all)"
                        },
                        "dry_run": {
                            "type": "boolean",
                            "description": "Dry run mode (default: false)"
                        },
                        "build_only": {
                            "type": "boolean",
                            "description": "Only build, don't deploy (default: false)"
                        }
                    },
                    "required": ["project", "network"]
                }
            },
            {
                "name": "templedb_nixops4_status",
                "description": "Show deployment status for a NixOps4 network including recent deployments and machine status.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project slug"
                        },
                        "network": {
                            "type": "string",
                            "description": "Network name"
                        },
                        "deployment_uuid": {
                            "type": "string",
                            "description": "Show specific deployment by UUID (optional)"
                        }
                    },
                    "required": ["project", "network"]
                }
            },
            # Code Intelligence Tools (Phase 1.7)
            {
                "name": "templedb_code_search",
                "description": "Search code using hybrid search (BM25 + graph ranking). Searches symbol names, docstrings, and signatures. Returns relevance-ranked results with scoring breakdown. Requires search index (run templedb_code_index_search first).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project slug"
                        },
                        "query": {
                            "type": "string",
                            "description": "Search query (keywords, phrases, or FTS5 expressions)"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of results (default: 10)",
                            "default": 10
                        },
                        "symbol_type": {
                            "type": "string",
                            "description": "Filter by symbol type: function, class, method (optional)",
                            "enum": ["function", "class", "method"]
                        }
                    },
                    "required": ["project", "query"]
                }
            },
            {
                "name": "templedb_code_show_symbol",
                "description": "Show detailed information about a code symbol including callers, callees, complexity, and cluster membership. Provides 360-degree view of a symbol's role in the codebase.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project slug"
                        },
                        "symbol_name": {
                            "type": "string",
                            "description": "Symbol name or qualified name (e.g., 'get_connection' or 'MyClass.method')"
                        }
                    },
                    "required": ["project", "symbol_name"]
                }
            },
            {
                "name": "templedb_code_show_clusters",
                "description": "Show code clusters (architectural boundaries) discovered by community detection. Clusters represent tightly-coupled groups of symbols that form logical modules. High cohesion (>0.7) indicates strong module boundaries.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project slug"
                        },
                        "include_members": {
                            "type": "boolean",
                            "description": "Include list of symbols in each cluster (default: false)",
                            "default": False
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of clusters to return (default: 20)",
                            "default": 20
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_code_impact_analysis",
                "description": "Analyze blast radius (impact) of changing a symbol. Shows all symbols that would be affected by modifying this symbol (direct and transitive dependents). Use this before making changes to understand scope of impact.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project slug"
                        },
                        "symbol_name": {
                            "type": "string",
                            "description": "Symbol to analyze"
                        }
                    },
                    "required": ["project", "symbol_name"]
                }
            },
            {
                "name": "templedb_code_extract_symbols",
                "description": "Extract public/exported symbols from project files (Phase 1.2). Uses tree-sitter to parse code and extract functions, classes, and methods. Run this first before other code intelligence operations.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project slug"
                        },
                        "force": {
                            "type": "boolean",
                            "description": "Force re-extraction even if symbols exist (default: false)",
                            "default": False
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_code_build_graph",
                "description": "Build dependency graph for project (Phase 1.3). Analyzes function/method calls and builds cross-file dependency graph. Required for impact analysis and clustering.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project slug"
                        },
                        "force": {
                            "type": "boolean",
                            "description": "Force rebuild even if graph exists (default: false)",
                            "default": False
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_code_detect_clusters",
                "description": "Detect code clusters using Leiden algorithm (Phase 1.5). Automatically discovers architectural boundaries and module structure. Use lower resolution (0.3-0.5) for fewer, larger clusters; higher (1.5-2.0) for more granular clustering.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project slug"
                        },
                        "resolution": {
                            "type": "number",
                            "description": "Leiden resolution parameter (default: 1.0). Higher = more clusters.",
                            "default": 1.0
                        }
                    },
                    "required": ["project"]
                }
            },
            {
                "name": "templedb_code_index_search",
                "description": "Index project for hybrid code search (Phase 1.6). Builds FTS5 full-text search index for fast keyword search. Run this after extracting symbols or when code changes.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project slug"
                        }
                    },
                    "required": ["project"]
                }
            },
            # Workflow Orchestration Tools (Phase 2.2)
            {
                "name": "templedb_workflow_execute",
                "description": "Execute a workflow with given variables. Workflows are multi-phase orchestration definitions that coordinate code intelligence, testing, deployment, and validation. Use dry_run=true to preview execution without making changes.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workflow": {
                            "type": "string",
                            "description": "Workflow name (without .yaml extension, e.g., 'safe-deployment', 'code-intelligence-bootstrap')"
                        },
                        "project": {
                            "type": "string",
                            "description": "Project slug (optional, required by some workflows)"
                        },
                        "variables": {
                            "type": "object",
                            "description": "Workflow variables as key-value pairs (e.g., {'primary_symbol': 'authenticate_user', 'previous_version': 'v2.1.0'})",
                            "additionalProperties": True
                        },
                        "dry_run": {
                            "type": "boolean",
                            "description": "Preview workflow execution without making changes (default: false)",
                            "default": False
                        }
                    },
                    "required": ["workflow"]
                }
            },
            {
                "name": "templedb_workflow_status",
                "description": "Get status of a running or completed workflow. Note: Async workflow execution tracking not yet implemented - workflows currently run synchronously.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workflow_id": {
                            "type": "string",
                            "description": "Workflow execution ID"
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "templedb_workflow_list",
                "description": "List all available workflow definitions. Workflows are stored in the workflows/ directory as YAML files.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "templedb_workflow_validate",
                "description": "Validate a workflow definition. Checks YAML syntax and required workflow structure (name, version, phases, tasks).",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "workflow": {
                            "type": "string",
                            "description": "Workflow name (without .yaml extension)"
                        }
                    },
                    "required": ["workflow"]
                }
            },
            {
                "name": "templedb_context_set_default",
                "description": "Set a default project context for the session. Once set, tools that require a 'project' parameter can omit it and use the default. Useful for reducing repetition when working with a single project.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug to set as default (use null or empty to clear)"
                        }
                    },
                    "required": []
                }
            },
            {
                "name": "templedb_context_get_default",
                "description": "Get the current default project context (if any is set).",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "templedb_schema_explore",
                "description": "Explore database schema with natural language queries. Answers questions about database structure, table relationships, and statistics. Examples: 'What tables exist?', 'Show me the projects schema', 'What file types are tracked?', 'How many commits per project?'",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Natural language question about the database schema or statistics"
                        },
                        "project": {
                            "type": "string",
                            "description": "Optional project to scope the query to (uses default if not specified)"
                        }
                    },
                    "required": ["query"]
                }
            }
        ]

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
        """Set system config value (simple key-value store)"""
        try:
            key = args["key"]
            value = args["value"]
            description = args.get("description", "")

            conn = self._get_db_connection()
            cursor = conn.cursor()

            # Use INSERT OR REPLACE
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

    # NixOps4 tools

    def tool_nixops4_network_create(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Create a NixOps4 network"""
        try:
            project = args["project"]
            network_name = args["network_name"]
            config_file = args.get("config_file")
            flake_uri = args.get("flake_uri")
            description = args.get("description")

            cmd = ["nixops4", "network", "create", project, network_name]
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
            logger.error(f"Error creating nixops4 network: {e}")
            return self._error_response(ErrorCode.INTERNAL_ERROR, str(e))

    def tool_nixops4_network_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List NixOps4 networks"""
        try:
            cmd = ["nixops4", "network", "list"]
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
            logger.error(f"Error listing nixops4 networks: {e}")
            return self._error_response(ErrorCode.INTERNAL_ERROR, str(e))

    def tool_nixops4_network_info(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Show NixOps4 network info"""
        try:
            project = args["project"]
            network = args["network"]

            result = self._run_templedb_cli(["nixops4", "network", "info", project, network])

            if result["returncode"] != 0:
                return self._error_response(
                    ErrorCode.INTERNAL_ERROR,
                    f"Failed to get network info: {result['stderr']}"
                )

            return self._success_response(result["stdout"], format_json=False)
        except Exception as e:
            logger.error(f"Error getting nixops4 network info: {e}")
            return self._error_response(ErrorCode.INTERNAL_ERROR, str(e))

    def tool_nixops4_machine_add(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Add machine to NixOps4 network"""
        try:
            project = args["project"]
            network = args["network"]
            machine_name = args["machine_name"]
            target_host = args["target_host"]
            target_user = args.get("target_user", "root")
            system_type = args.get("system_type", "nixos")

            cmd = ["nixops4", "machine", "add", project, network, machine_name,
                   "--host", target_host, "--user", target_user, "--system-type", system_type]

            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return self._error_response(
                    ErrorCode.INTERNAL_ERROR,
                    f"Failed to add machine: {result['stderr']}"
                )

            return self._success_response(result["stdout"], format_json=False)
        except Exception as e:
            logger.error(f"Error adding nixops4 machine: {e}")
            return self._error_response(ErrorCode.INTERNAL_ERROR, str(e))

    def tool_nixops4_machine_list(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """List machines in NixOps4 network"""
        try:
            project = args["project"]
            network = args["network"]

            result = self._run_templedb_cli(["nixops4", "machine", "list", project, network])

            if result["returncode"] != 0:
                return self._error_response(
                    ErrorCode.INTERNAL_ERROR,
                    f"Failed to list machines: {result['stderr']}"
                )

            return self._success_response(result["stdout"], format_json=False)
        except Exception as e:
            logger.error(f"Error listing nixops4 machines: {e}")
            return self._error_response(ErrorCode.INTERNAL_ERROR, str(e))

    def tool_nixops4_deploy(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Deploy NixOps4 network"""
        try:
            project = args["project"]
            network = args["network"]
            machines = args.get("machines", [])
            dry_run = args.get("dry_run", False)
            build_only = args.get("build_only", False)

            cmd = ["nixops4", "deploy", project, network]
            if machines:
                cmd.extend(["--machines"] + machines)
            if dry_run:
                cmd.append("--dry-run")
            if build_only:
                cmd.append("--build-only")

            result = self._run_templedb_cli(cmd)

            if result["returncode"] != 0:
                return self._error_response(
                    ErrorCode.DEPLOYMENT_FAILED,
                    f"Deployment failed: {result['stderr']}"
                )

            return self._success_response(result["stdout"], format_json=False)
        except Exception as e:
            logger.error(f"Error deploying nixops4 network: {e}")
            return self._error_response(ErrorCode.DEPLOYMENT_FAILED, str(e))

    def tool_nixops4_status(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Show NixOps4 deployment status"""
        try:
            project = args["project"]
            network = args["network"]
            deployment_uuid = args.get("deployment_uuid")

            cmd = ["nixops4", "status", project, network]
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
            logger.error(f"Error getting nixops4 status: {e}")
            return self._error_response(ErrorCode.INTERNAL_ERROR, str(e))

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

                result = self.read_resource(uri)
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
