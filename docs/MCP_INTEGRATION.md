# TempleDB MCP Integration

This document describes the Model Context Protocol (MCP) integration that replaced the previous interactive agent system.

## Overview

TempleDB now integrates directly with Claude Code via MCP, exposing templedb operations as native tools that Claude can invoke seamlessly. This replaces the previous `agent start/chat/send` system with a standard protocol-based approach.

## Architecture

### Components

1. **MCP Server** (`src/mcp_server.py`)
   - Stdio-based JSON-RPC server
   - Implements MCP protocol version 2024-11-05
   - Exposes 10 templedb tools

2. **CLI Command** (`src/cli/commands/mcp.py`)
   - `./templedb mcp serve` - Start MCP server
   - Registered in main CLI

3. **Configuration** (`.mcp.json`)
   - Tells Claude Code how to launch server
   - Sets environment variables
   - Discovered automatically

4. **Skills** (`.claude/skills/`)
   - Updated to recommend MCP tools
   - Serve as fallback when MCP unavailable

### Communication Flow

```
┌─────────────┐          ┌──────────────┐          ┌──────────────┐
│ Claude Code │  stdio   │ MCP Server   │  Python  │  TempleDB    │
│             ├─────────►│              ├─────────►│  Repos/CLI   │
│             │◄─────────┤              │◄─────────┤              │
└─────────────┘ JSON-RPC └──────────────┘          └──────────────┘
```

## Available Tools

**Total: 60+ tools** (extensive coverage across all TempleDB features including code intelligence and workflows)

## Available Resources

**Total: 3+ resources** (read-only data sources for schema and configuration)

### Project Management

**`templedb_project_list`**
- Lists all projects tracked in TempleDB
- Returns: Array of project objects with metadata

**`templedb_project_show`**
- Shows detailed info for a specific project
- Parameters: `project` (name or slug)
- Returns: Project object with stats
- Error codes: `-32010` (PROJECT_NOT_FOUND)

**`templedb_project_import`**
- Imports a git repository into TempleDB
- Parameters: `repo_url`, optional `name`
- Returns: Import success message

**`templedb_project_sync`**
- Syncs project with filesystem
- Parameters: `project` (name or slug)
- Returns: Sync statistics

### Queries and Context

**`templedb_query`**
- Executes SQL against TempleDB
- Parameters: `query`, optional `format` (json/table/csv)
- Returns: Query results
- Uses connection pooling for better performance

**`templedb_context_generate`**
- Generates LLM context for a project
- Parameters: `project`, optional `max_files`
- Returns: Structured context data

**`templedb_search_files`**
- Searches for files by path pattern
- Parameters: `pattern`, optional `project`, `limit`
- Returns: Array of matching files

**`templedb_search_content`**
- Searches file contents across projects
- Parameters: `query`, optional `project`, `file_pattern`, `limit`
- Returns: Search results

### Version Control

**`templedb_vcs_status`**
- Show working directory status
- Parameters: `project`
- Returns: Staged, modified, untracked files

**`templedb_vcs_add`**
- Stage files for commit
- Parameters: `project`, `files` (array)
- Returns: Success message

**`templedb_vcs_reset`**
- Unstage files
- Parameters: `project`, `files` (array)
- Returns: Success message

**`templedb_vcs_commit`**
- Create a commit
- Parameters: `project`, `message`, `author`, optional `all`
- Returns: Commit hash

**`templedb_vcs_log`**
- Show commit history
- Parameters: `project`, optional `limit`
- Returns: Array of commits

**`templedb_vcs_diff`**
- Show differences
- Parameters: `project`, optional `file`
- Returns: Diff output

**`templedb_vcs_branch`**
- List or create branches
- Parameters: `project`, optional `name`
- Returns: Branch list or success message

**`templedb_commit_list`**
- Lists recent commits for a project
- Parameters: `project`, optional `limit`
- Returns: Array of commit objects

**`templedb_commit_create`**
- Records a commit in TempleDB
- Parameters: `project`, `commit_hash`, `message`, optional `session_id`
- Returns: Success message

### Secret Management

**`templedb_secret_list`** (NEW)
- List secrets for a project (metadata only, no decryption)
- Parameters: `project`, optional `profile` (default: "default")
- Returns: Array of secret metadata with key counts
- Error codes: `-32010` (PROJECT_NOT_FOUND), `-32040` (SECRET_NOT_FOUND)

**`templedb_secret_export`** (NEW)
- Export and decrypt secrets in various formats
- Parameters: `project`, optional `profile`, optional `format` (shell/yaml/json/dotenv)
- Returns: Decrypted secrets in requested format
- Requires: Age decryption keys available
- Error codes: `-32041` (SECRET_DECRYPT_FAILED)

**`templedb_secret_show_keys`** (NEW)
- Show which encryption keys protect a secret
- Parameters: `project`, optional `profile`
- Returns: List of encryption keys with status
- Error codes: `-32040` (SECRET_NOT_FOUND)

### Cathedral Package Management

**`templedb_cathedral_export`** (NEW)
- Export a project as a portable .cathedral package
- Parameters: `project`, optional `output_dir`, `compress`, `include_files`, `include_vcs`
- Returns: Package file path and statistics
- Error codes: `-32050` (CATHEDRAL_EXPORT_FAILED)

**`templedb_cathedral_import`** (NEW)
- Import a .cathedral package into TempleDB
- Parameters: `package_path`, optional `overwrite`, `new_slug`
- Returns: Import success message
- Error codes: `-32051` (CATHEDRAL_IMPORT_FAILED), `-32052` (CATHEDRAL_INVALID_PACKAGE)

**`templedb_cathedral_inspect`** (NEW)
- Inspect a .cathedral package without importing
- Parameters: `package_path`
- Returns: Package metadata, file count, compression info
- Error codes: `-32052` (CATHEDRAL_INVALID_PACKAGE)

### Deployment

**`templedb_deploy`**
- Deploy a project to a target
- Parameters: `project`, optional `target`, `dry_run`
- Returns: Deployment log
- Error codes: `-32060` (DEPLOYMENT_FAILED)

**`templedb_env_get`**
- Get an environment variable value
- Parameters: `project`, `key`
- Returns: Variable value
- Error codes: `-32070` (ENV_VAR_NOT_FOUND)

**`templedb_env_set`**
- Set an environment variable
- Parameters: `project`, `key`, `value`, optional `target`
- Returns: Success message

**`templedb_env_list`**
- List all environment variables
- Parameters: `project`, optional `target`
- Returns: Array of variables

### Context Management (NEW - v1.2)

**`templedb_context_set_default`**
- Set a default project context for the session
- Parameters: optional `project` (name or slug, use null/empty to clear)
- Returns: Success message with project details
- Purpose: Reduces repetition by allowing tools to omit `project` parameter

**`templedb_context_get_default`**
- Get the current default project context
- Parameters: none
- Returns: Current default project info or none if not set
- Purpose: Check which project is set as default

### Code Intelligence (NEW - v1.3)

**`templedb_code_extract_symbols`**
- Extract public/exported symbols from project files (Phase 1.2)
- Parameters: `project`, optional `force` (default: false)
- Returns: Symbol count and extraction statistics
- Purpose: Enables code search and impact analysis

**`templedb_code_build_graph`**
- Build dependency graph for project (Phase 1.3)
- Parameters: `project`, optional `force` (default: false)
- Returns: Graph statistics (nodes, edges)
- Purpose: Required for impact analysis and clustering

**`templedb_code_detect_clusters`**
- Detect code clusters using Leiden algorithm (Phase 1.5)
- Parameters: `project`, optional `resolution` (default: 1.0)
- Returns: Cluster count and cohesion metrics
- Purpose: Discover architectural boundaries automatically

**`templedb_code_index_search`**
- Index project for hybrid code search (Phase 1.6)
- Parameters: `project`
- Returns: Search index statistics
- Purpose: Enables fast keyword and semantic search

**`templedb_code_search`**
- Search code using hybrid search (BM25 + graph ranking)
- Parameters: `project`, `query`, optional `limit`, `symbol_type`
- Returns: Relevance-ranked results with scoring breakdown
- Purpose: Find symbols by name, docstrings, and signatures

**`templedb_code_show_symbol`**
- Show detailed information about a code symbol
- Parameters: `project`, `symbol_name`
- Returns: Symbol details, callers, callees, complexity, cluster membership
- Purpose: 360-degree view of a symbol's role

**`templedb_code_show_clusters`**
- Show code clusters (architectural boundaries)
- Parameters: `project`, optional `include_members`, `limit`
- Returns: Cluster list with cohesion scores
- Purpose: Understand module structure

**`templedb_code_impact_analysis`**
- Analyze blast radius (impact) of changing a symbol
- Parameters: `project`, `symbol_name`
- Returns: All affected symbols (direct and transitive dependents)
- Purpose: Know what breaks before you change it

### Workflows (NEW - v1.3)

**`templedb_workflow_execute`**
- Execute a workflow with given variables
- Parameters: `workflow`, optional `project`, `variables`, `dry_run`
- Returns: Workflow execution result with phase outcomes
- Purpose: Multi-phase orchestration of code intelligence, testing, deployment

**`templedb_workflow_list`**
- List all available workflow definitions
- Parameters: none
- Returns: Array of workflow names with descriptions
- Purpose: Discover available workflows

**`templedb_workflow_validate`**
- Validate a workflow definition
- Parameters: `workflow` (name without .yaml extension)
- Returns: Validation result with any errors
- Purpose: Check workflow syntax before execution

**`templedb_workflow_status`**
- Get status of a running or completed workflow
- Parameters: optional `workflow_id`
- Returns: Workflow execution status
- Purpose: Monitor long-running workflows (async support coming)

### Schema Exploration (NEW - v1.2)

**`templedb_schema_explore`**
- Explore database schema with natural language queries
- Parameters: `query` (natural language question), optional `project`
- Returns: Structured response with relevant schema information
- Supported queries:
  - "What tables exist?" - Lists all tables and views
  - "Show me projects" - Lists all tracked projects
  - "What file types are tracked?" - Shows file extension distribution
  - "How many commits?" - Shows commit statistics
  - "Show database schema" - Returns full schema DDL

### MCP Resources (NEW - v1.2)

Resources are read-only data sources that clients can subscribe to:

**`templedb://schema`**
- Complete database schema overview
- Returns: All tables, views, and indexes with DDL
- MIME type: application/json

**`templedb://projects`**
- List of all tracked projects with metadata
- Returns: Project list with file counts and commit counts
- MIME type: application/json

**`templedb://config`**
- TempleDB system configuration settings
- Returns: All system_config key-value pairs
- MIME type: application/json

**`templedb://project/{slug}/schema`** (Dynamic)
- Project-specific schema information
- Returns: File types, commit count, project details
- MIME type: application/json

## Usage Examples

### With MCP Tools (Automatic)

Claude invokes tools automatically based on conversation:

```
User: "Show me all my projects"
→ Claude calls templedb_project_list

User: "Import the repo at /path/to/project"
→ Claude calls templedb_project_import

User: "What files contain 'authentication'?"
→ Claude calls templedb_search_content

User: "Generate context for my-project"
→ Claude calls templedb_context_generate

User: "Set templedb as my default project"
→ Claude calls templedb_context_set_default

User: "What file types are in the codebase?"
→ Claude calls templedb_schema_explore

User: "Show me the database schema"
→ Claude reads templedb://schema resource

User: "Bootstrap code intelligence for my-project"
→ Claude calls templedb_workflow_execute with workflow="code_intelligence_bootstrap"

User: "What's the impact of changing the authenticate function?"
→ Claude calls templedb_code_impact_analysis

User: "Search for authentication code"
→ Claude calls templedb_code_search

User: "Deploy to production with safety checks"
→ Claude calls templedb_workflow_execute with workflow="safe_deployment"
```

### Context Switching Workflow (NEW)

Set a default project to reduce repetition:

```bash
# Set default
→ templedb_context_set_default({"project": "my-project"})

# Now other tools can omit project parameter (if implemented)
→ templedb_vcs_status()  # Uses default project
→ templedb_schema_explore({"query": "What file types?"})  # Uses default
```

### Schema Exploration Examples (NEW)

Natural language schema queries:

```bash
# List all tables
→ templedb_schema_explore({"query": "What tables exist?"})

# Get project statistics
→ templedb_schema_explore({"query": "Show me projects"})

# Analyze file types
→ templedb_schema_explore({"query": "What file types are tracked?", "project": "my-project"})

# Commit statistics
→ templedb_schema_explore({"query": "How many commits?", "project": "my-project"})
```

### Code Intelligence Workflow (NEW - v1.3)

Bootstrap code intelligence and analyze impact:

```bash
# Bootstrap code intelligence
→ templedb_workflow_execute({
    "workflow": "code_intelligence_bootstrap",
    "project": "my-project"
  })

# Search for symbols
→ templedb_code_search({
    "project": "my-project",
    "query": "authenticate user",
    "limit": 10
  })

# Analyze impact before refactoring
→ templedb_code_impact_analysis({
    "project": "my-project",
    "symbol_name": "authenticate_user"
  })

# Show architectural boundaries
→ templedb_code_show_clusters({
    "project": "my-project",
    "include_members": true
  })
```

### Deployment Workflow (NEW - v1.3)

Safe deployment with automatic rollback:

```bash
# Deploy with full safety checks
→ templedb_workflow_execute({
    "workflow": "safe_deployment",
    "project": "my-project",
    "variables": {
      "primary_symbol": "deploy",
      "previous_version": "v2.0.0",
      "staging_health_url": "https://staging.example.com/health",
      "production_health_url": "https://production.example.com/health"
    }
  })

# Dry run to preview
→ templedb_workflow_execute({
    "workflow": "safe_deployment",
    "project": "my-project",
    "dry_run": true
  })
```

### Refactoring Workflow (NEW - v1.3)

Impact-aware refactoring with blast radius checks:

```bash
# Refactor with safety checks
→ templedb_workflow_execute({
    "workflow": "impact_aware_refactoring",
    "project": "my-project",
    "variables": {
      "target_symbol": "process_payment",
      "max_blast_radius": "100"
    }
  })
```

### Resource Reading Examples (NEW)

Access read-only resources:

```bash
# List available resources
→ resources/list

# Read schema resource
→ resources/read({"uri": "templedb://schema"})

# Read projects list
→ resources/read({"uri": "templedb://projects"})

# Read project-specific schema
→ resources/read({"uri": "templedb://project/my-project/schema"})

# Read system config
→ resources/read({"uri": "templedb://config"})
```

### Manual Testing

Test the MCP server directly:

```bash
# Initialize
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | ./templedb mcp serve

# List tools
(
  echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
  echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
) | ./templedb mcp serve

# Call a tool
(
  echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
  echo '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"templedb_project_list","arguments":{}}}'
) | ./templedb mcp serve
```

## Configuration

### Project-Level (.mcp.json)

```json
{
  "mcpServers": {
    "templedb": {
      "command": "./templedb",
      "args": ["mcp", "serve"],
      "env": {
        "TEMPLEDB_DB_PATH": "~/.templedb/projdb.db"
      }
    }
  }
}
```

Claude Code automatically reads this from the project root.

### User-Level (~/.claude.json)

You can also configure MCP servers globally:

```json
{
  "mcpServers": {
    "templedb": {
      "command": "/path/to/templedb",
      "args": ["mcp", "serve"],
      "env": {
        "TEMPLEDB_DB_PATH": "~/.templedb/projdb.db"
      }
    }
  }
}
```

## Migration from Interactive Agent

### What Changed

**Removed:**
- `templedb agent start` - Starting agent sessions
- `templedb agent chat` - Interactive chat interface
- `templedb agent send` - Sending messages
- `templedb agent watch` - Watching agent activity
- Database-stored agent sessions and interactions

**Added:**
- `templedb mcp serve` - Start MCP server
- 10 native MCP tools
- `.mcp.json` configuration
- Standard protocol integration

### Benefits

1. **No Session Management** - Claude invokes tools directly, no start/stop
2. **Standard Protocol** - Uses MCP, works with any MCP client
3. **Better UX** - Tools appear natively alongside Bash, Read, Edit, etc.
4. **Simpler Architecture** - Less infrastructure to maintain
5. **Easier Testing** - Standard JSON-RPC protocol

### Backward Compatibility

The old agent commands still exist but are deprecated:
- `templedb agent start/end/list/status/history/context`
- `templedb agent watch/chat/send`

These may be removed in a future version once MCP integration is proven.

## Implementation Details

### MCP Server (src/mcp_server.py)

**Key Classes:**
- `MCPServer` - Main server class
  - `get_tool_definitions()` - Returns tool schemas
  - `tool_*()` methods - Implement each tool
  - `handle_message()` - Process JSON-RPC messages
  - `run()` - Main event loop
- `ErrorCode` - Error code constants for structured errors

**Key Features (v1.1 - 2026-03-16):**
- ✓ **No hardcoded paths** - Uses `PROJECT_ROOT` from config
- ✓ **Connection pooling** - SQLite connection reused across queries
- ✓ **Standardized errors** - Error codes and structured error responses
- ✓ **Helper methods** - `_run_templedb_cli()`, `_error_response()`, `_success_response()`
- ✓ **Secret management** - 3 new tools for encrypted secrets
- ✓ **Cathedral packages** - 3 new tools for portable project bundles

**Error Handling (Improved):**
- Structured error responses with error codes
- Error codes follow JSON-RPC conventions (-32000 to -32099)
- Error details included in response for debugging
- Tools return `{"isError": true, "content": [{"error_code": -32010, "details": {...}}]}`
- Errors logged to stderr (not stdout to avoid protocol corruption)
- Graceful degradation on repository/CLI errors

**Error Code Ranges:**
- `-32010` to `-32019`: Project errors
- `-32020` to `-32029`: Query errors
- `-32030` to `-32039`: VCS errors
- `-32040` to `-32049`: Secret errors
- `-32050` to `-32059`: Cathedral errors
- `-32060` to `-32069`: Deployment errors
- `-32070` to `-32079`: Environment errors
- `-32000` to `-32009`: Generic errors

**Logging:**
- INFO level to stderr
- Clean JSON-RPC on stdout
- Debug with: `./templedb mcp serve 2>debug.log`

**Performance Optimizations:**
- SQLite connection pooling (reuse across tool calls)
- No hardcoded paths (works for all installations)
- Efficient CLI invocation helper

### Tool Implementation Pattern

Each tool follows this pattern:

```python
def tool_<name>(self, args: Dict[str, Any]) -> Dict[str, Any]:
    """Tool description"""
    try:
        # 1. Extract and validate parameters
        param = args.get("param_name")

        # 2. Call repository or CLI
        result = self.repo.method(param)

        # 3. Format response
        return {
            "content": [{
                "type": "text",
                "text": json.dumps(result, indent=2)
            }]
        }
    except Exception as e:
        logger.error(f"Error: {e}")
        return {
            "content": [{"type": "text", "text": f"Error: {str(e)}"}],
            "isError": True
        }
```

### Protocol Messages

**Initialize:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "initialize",
  "params": {
    "protocolVersion": "2024-11-05",
    "capabilities": {},
    "clientInfo": {"name": "claude", "version": "1.0"}
  }
}
```

**List Tools:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/list",
  "params": {}
}
```

**Call Tool:**
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "templedb_project_list",
    "arguments": {}
  }
}
```

## Development

### Adding New Tools

1. Add tool definition to `get_tool_definitions()`:
```python
{
    "name": "templedb_new_tool",
    "description": "What it does",
    "inputSchema": {
        "type": "object",
        "properties": {
            "param": {"type": "string", "description": "..."}
        },
        "required": ["param"]
    }
}
```

2. Implement handler method:
```python
def tool_new_tool(self, args: Dict[str, Any]) -> Dict[str, Any]:
    # Implementation
    pass
```

3. Register in `__init__`:
```python
self.tools = {
    # ...
    "templedb_new_tool": self.tool_new_tool,
}
```

4. Test:
```bash
echo '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"templedb_new_tool","arguments":{"param":"value"}}}' | ./templedb mcp serve
```

### Testing

**Unit Tests:**
```python
# Test tool directly
server = MCPServer()
result = server.tool_project_list({})
assert "content" in result
```

**Integration Tests:**
```bash
# Test full protocol flow
./test_mcp.sh
```

**Manual Testing:**
```bash
# Interactive testing
./templedb mcp serve
# Then send JSON-RPC messages via stdin
```

### Debugging

**Enable debug logging:**
```bash
# Edit src/mcp_server.py
logging.basicConfig(level=logging.DEBUG, ...)
```

**Capture stderr:**
```bash
./templedb mcp serve 2>mcp.log
tail -f mcp.log
```

**Protocol debugging:**
```bash
# See all JSON-RPC messages
./templedb mcp serve 2>&1 | tee protocol.log
```

## Verification

### Check MCP Server Available

```bash
./templedb --help | grep mcp
# Should show: mcp    Model Context Protocol server
```

### Test Server Starts

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' | timeout 5 ./templedb mcp serve 2>&1 | grep "TempleDB MCP Server"
```

### Test Tool List

```bash
(
  echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
  echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
) | ./templedb mcp serve 2>&1 | grep "templedb_project_list"
```

### Test Tool Call

```bash
(
  echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'
  echo '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"templedb_project_list","arguments":{}}}'
) | ./templedb mcp serve 2>&1 | tail -1 | python3 -m json.tool
```

### Verify in Claude Code

1. Start Claude Code in templedb directory
2. Type `/mcp` to check server status
3. Should see "templedb" server loaded
4. Tools should appear in available tools

## Troubleshooting

### Server Won't Start

**Check command:**
```bash
./templedb mcp serve
# Should not error immediately
```

**Check Python imports:**
```bash
cd src && python3 -c "import mcp_server"
# Should not error
```

### Tools Not Showing

**Verify .mcp.json:**
```bash
cat .mcp.json
# Check syntax is valid
python3 -c "import json; json.load(open('.mcp.json'))"
```

**Check Claude Code config:**
```bash
claude mcp list
# Should show templedb server
```

### Tool Errors

**Check logs:**
```bash
./templedb mcp serve 2>error.log
# Check error.log for details
```

**Test tool directly:**
```bash
cd src && python3
>>> from mcp_server import MCPServer
>>> server = MCPServer()
>>> server.tool_project_list({})
```

### Protocol Errors

**Validate JSON-RPC:**
- All messages must have `jsonrpc`, `id`, `method`
- Responses must match request `id`
- Must be valid JSON

**Check stdout/stderr separation:**
- Protocol messages on stdout only
- Logs on stderr only
- Don't mix them

## Resources

- [MCP Specification](https://spec.modelcontextprotocol.io/)
- [Claude Code MCP Docs](https://code.claude.com/docs/en/mcp)
- [JSON-RPC 2.0 Spec](https://www.jsonrpc.org/specification)
- [TempleDB Skills](.claude/skills/README.md)

## Recent Enhancements

### v1.3 - 2026-03-22

**Completed:**
- [x] Added Code Intelligence tools (8 tools for symbol extraction, dependency graphs, search, impact analysis)
- [x] Implemented Workflow execution system with 3 production-ready workflows
- [x] Added `code_intelligence_bootstrap` workflow for automatic setup
- [x] Added `safe_deployment` workflow with staging, production, and rollback
- [x] Added `impact_aware_refactoring` workflow with blast radius awareness
- [x] Updated MCP documentation with workflow examples
- [x] Updated project context with code intelligence and workflow information

### v1.2 - 2026-03-21

**Completed:**
- [x] Added MCP Resources support (3 core resources + dynamic project resources)
- [x] Implemented context management (set/get default project)
- [x] Added natural language schema exploration tool
- [x] Updated protocol capabilities to include resources
- [x] Enhanced documentation with new feature examples

### v1.1 - 2026-03-16

**Completed:**
- [x] Fixed hardcoded paths - now portable across installations
- [x] Added SQLite connection pooling for better performance
- [x] Implemented structured error codes and responses
- [x] Added `templedb_secret_*` tools (3 tools for secret management)
- [x] Added `templedb_cathedral_*` tools (3 tools for package management)
- [x] Created helper methods for cleaner code

## Future Enhancements

**Potential additions:**
- [ ] `templedb_backup_*` tools for backup/restore
- [ ] `templedb_environment_*` tools for Nix envs
- [ ] `templedb_secret_init` and `templedb_secret_edit` tools (requires interactive input handling)
- [ ] Streaming responses for large datasets
- [ ] Progress updates for long operations
- [ ] Resource templates and prompts
- [ ] Batch operations (e.g., import multiple projects)
- [ ] Async tool execution for long-running operations

## Contributing

To improve MCP integration:

1. Add new tools to `src/mcp_server.py`
2. Update tool definitions with clear schemas
3. Test with manual JSON-RPC messages
4. Update this documentation
5. Update skills to reference new tools

---

**Created:** 2026-02-27
**Protocol Version:** 2024-11-05
**TempleDB Version:** 1.0.0

*Replacing interactive agents with protocol-based tool integration.*
