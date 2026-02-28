#!/usr/bin/env python3
"""
TempleDB MCP Server - Model Context Protocol integration for Claude Code

Exposes templedb operations as native tools that Claude can invoke directly.
Uses stdio transport for local integration.
"""

import sys
import json
import logging
from typing import Any, Dict, List, Optional
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from repositories import ProjectRepository
from repositories.agent_repository import AgentRepository
from llm_context import TempleDBContext
from config import DB_PATH
from logger import get_logger

# Configure logging to stderr so stdout is clean for MCP protocol
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = get_logger(__name__)


class MCPServer:
    """MCP Server implementation for TempleDB"""

    def __init__(self):
        """Initialize MCP server with templedb repositories"""
        self.project_repo = ProjectRepository()
        self.agent_repo = AgentRepository(DB_PATH)
        self.context_gen = TempleDBContext(DB_PATH)

        # MCP protocol version
        self.protocol_version = "2024-11-05"

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
        }

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return MCP tool definitions"""
        return [
            {
                "name": "templedb_project_list",
                "description": "List all projects tracked in TempleDB. Returns project names, IDs, slugs, and git info.",
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
                "description": "Import a git repository into TempleDB. Clones repo and indexes all files.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "repo_url": {
                            "type": "string",
                            "description": "Git repository URL (http/https/ssh)"
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
                "description": "Record a commit in TempleDB. Use after making git commits to track in database.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project": {
                            "type": "string",
                            "description": "Project name or slug"
                        },
                        "commit_hash": {
                            "type": "string",
                            "description": "Git commit SHA"
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
                return {
                    "content": [{"type": "text", "text": f"Project '{project_name}' not found"}],
                    "isError": True
                }

            # Get additional details
            stats = self.project_repo.get_statistics(project['id'])
            if stats:
                project['stats'] = stats

            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(project, indent=2)
                    }
                ]
            }
        except Exception as e:
            logger.error(f"Error showing project: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_project_import(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Import a git repository"""
        try:
            repo_url = args["repo_url"]
            name = args.get("name")

            # Import via CLI command
            import subprocess
            cmd = ["./templedb", "project", "import", repo_url]
            if name:
                cmd.extend(["--name", name])

            result = subprocess.run(cmd, capture_output=True, text=True, cwd="/home/zach/templeDB")

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Import failed: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout}]
            }
        except Exception as e:
            logger.error(f"Error importing project: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_project_sync(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Sync project with filesystem"""
        try:
            project_name = args["project"]

            # Sync via CLI command
            import subprocess
            result = subprocess.run(
                ["./templedb", "project", "sync", project_name],
                capture_output=True, text=True, cwd="/home/zach/templeDB"
            )

            if result.returncode != 0:
                return {
                    "content": [{"type": "text", "text": f"Sync failed: {result.stderr}"}],
                    "isError": True
                }

            return {
                "content": [{"type": "text", "text": result.stdout}]
            }
        except Exception as e:
            logger.error(f"Error syncing project: {e}")
            return {"content": [{"type": "text", "text": f"Error: {str(e)}"}], "isError": True}

    def tool_query(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """Execute SQL query"""
        try:
            query = args["query"]
            format_type = args.get("format", "json")

            import sqlite3
            with sqlite3.connect(DB_PATH) as conn:
                conn.row_factory = sqlite3.Row
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

            result = subprocess.run(cmd, capture_output=True, text=True, cwd="/home/zach/templeDB")

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

            result = subprocess.run(cmd, capture_output=True, text=True, cwd="/home/zach/templeDB")

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
