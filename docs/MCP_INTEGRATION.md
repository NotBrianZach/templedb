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

**Total: 27 tools** (10 original + 6 VCS + 4 deployment + 3 secret + 3 cathedral + 1 environment)

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

## Recent Enhancements (v1.1 - 2026-03-16)

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
