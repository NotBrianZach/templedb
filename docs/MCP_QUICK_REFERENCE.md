# TempleDB MCP Tools - Quick Reference

**Total Tools:** 51
**Total Resources:** 3+
**Version:** 1.2 (2026-03-21)

## Tool Categories

### 🗂️ Project Management (4 tools)
- `templedb_project_list` - List all projects
- `templedb_project_show` - Show project details
- `templedb_project_import` - Import git repository
- `templedb_project_sync` - Sync with filesystem

### 🔍 Queries & Search (4 tools)
- `templedb_query` - Execute SQL queries
- `templedb_context_generate` - Generate LLM context
- `templedb_search_files` - Search by file path
- `templedb_search_content` - Search file contents

### 📦 Version Control (9 tools)
- `templedb_vcs_status` - Show working directory status
- `templedb_vcs_add` - Stage files
- `templedb_vcs_reset` - Unstage files
- `templedb_vcs_commit` - Create commit
- `templedb_vcs_log` - Show commit history
- `templedb_vcs_diff` - Show differences
- `templedb_vcs_branch` - List/create branches
- `templedb_commit_list` - List commits (alt)
- `templedb_commit_create` - Record commit

### 🔐 Secret Management (3 tools) *NEW*
- `templedb_secret_list` - List secret metadata
- `templedb_secret_export` - Export decrypted secrets
- `templedb_secret_show_keys` - Show encryption keys

### 📚 Cathedral Packages (3 tools) *NEW*
- `templedb_cathedral_export` - Export as package
- `templedb_cathedral_import` - Import package
- `templedb_cathedral_inspect` - Inspect package

### 🚀 Deployment & Environment (4 tools)
- `templedb_deploy` - Deploy project
- `templedb_env_get` - Get environment variable
- `templedb_env_set` - Set environment variable
- `templedb_env_list` - List environment variables

### 🎯 Context Management (2 tools) *NEW*
- `templedb_context_set_default` - Set default project context
- `templedb_context_get_default` - Get current default project

### 🔎 Schema Exploration (1 tool) *NEW*
- `templedb_schema_explore` - Natural language schema queries

### 📖 MCP Resources (3+ resources) *NEW*
- `templedb://schema` - Complete database schema
- `templedb://projects` - All tracked projects
- `templedb://config` - System configuration
- `templedb://project/{slug}/schema` - Project-specific schema

## Common Use Cases

### List and Show Projects
```javascript
// List all projects
templedb_project_list({})

// Show specific project
templedb_project_show({"project": "my-project"})
```

### Import and Sync
```javascript
// Import from git
templedb_project_import({
  "repo_url": "https://github.com/user/repo.git",
  "name": "my-project"  // optional
})

// Sync with filesystem
templedb_project_sync({"project": "my-project"})
```

### Version Control Workflow
```javascript
// 1. Check status
templedb_vcs_status({"project": "my-project"})

// 2. Stage files
templedb_vcs_add({
  "project": "my-project",
  "files": ["src/file.py", "README.md"]
})

// 3. Commit
templedb_vcs_commit({
  "project": "my-project",
  "message": "Add new feature",
  "author": "Name <email@example.com>"
})

// 4. View history
templedb_vcs_log({"project": "my-project", "limit": 10})
```

### Secret Management
```javascript
// List secrets (metadata only)
templedb_secret_list({
  "project": "my-project",
  "profile": "production"  // optional, default: "default"
})

// Export secrets (requires decryption keys)
templedb_secret_export({
  "project": "my-project",
  "profile": "production",
  "format": "shell"  // or "yaml", "json", "dotenv"
})

// Show encryption keys
templedb_secret_show_keys({
  "project": "my-project",
  "profile": "production"
})
```

### Cathedral Packages
```javascript
// Export project as package
templedb_cathedral_export({
  "project": "my-project",
  "output_dir": "/tmp",
  "compress": true,
  "include_files": true,
  "include_vcs": true
})

// Inspect package
templedb_cathedral_inspect({
  "package_path": "/tmp/my-project.cathedral"
})

// Import package
templedb_cathedral_import({
  "package_path": "/tmp/my-project.cathedral",
  "overwrite": false,
  "new_slug": "imported-project"  // optional
})
```

### Queries and Search
```javascript
// Execute SQL
templedb_query({
  "query": "SELECT * FROM projects WHERE name LIKE '%test%'",
  "format": "json"  // or "table", "csv"
})

// Search files by path
templedb_search_files({
  "pattern": "%.py",  // SQL LIKE syntax
  "project": "my-project",  // optional
  "limit": 50
})

// Search file contents
templedb_search_content({
  "query": "TODO",
  "project": "my-project",  // optional
  "file_pattern": "%.py",  // optional
  "limit": 50
})

// Generate LLM context
templedb_context_generate({
  "project": "my-project",
  "max_files": 50
})
```

### Deployment & Environment
```javascript
// Deploy
templedb_deploy({
  "project": "my-project",
  "target": "production",  // optional
  "dry_run": true  // optional
})

// Environment variables
templedb_env_list({
  "project": "my-project",
  "target": "production"  // optional
})

templedb_env_get({
  "project": "my-project",
  "key": "DATABASE_URL"
})

templedb_env_set({
  "project": "my-project",
  "key": "API_KEY",
  "value": "secret123",
  "target": "production"  // optional
})
```

### Context Management (NEW)
```javascript
// Set default project
templedb_context_set_default({
  "project": "my-project"
})

// Get current default
templedb_context_get_default({})

// Clear default
templedb_context_set_default({
  "project": null
})
```

### Schema Exploration (NEW)
```javascript
// Natural language queries
templedb_schema_explore({
  "query": "What tables exist?"
})

templedb_schema_explore({
  "query": "What file types are tracked?",
  "project": "my-project"  // optional, uses default if not specified
})

templedb_schema_explore({
  "query": "How many commits?",
  "project": "my-project"
})

templedb_schema_explore({
  "query": "Show me projects"
})
```

### Resources (NEW)
```javascript
// MCP protocol for reading resources

// List available resources
resources/list

// Read specific resource
resources/read({
  "uri": "templedb://schema"
})

resources/read({
  "uri": "templedb://projects"
})

resources/read({
  "uri": "templedb://config"
})

resources/read({
  "uri": "templedb://project/my-project/schema"
})
```

## Error Codes

All tools return structured errors with codes:

| Code Range | Category | Example Codes |
|------------|----------|---------------|
| -32010 to -32019 | Project | -32010: PROJECT_NOT_FOUND |
| -32020 to -32029 | Query | -32020: QUERY_FAILED |
| -32030 to -32039 | VCS | -32030: VCS_OPERATION_FAILED |
| -32040 to -32049 | Secret | -32040: SECRET_NOT_FOUND<br>-32041: SECRET_DECRYPT_FAILED |
| -32050 to -32059 | Cathedral | -32050: CATHEDRAL_EXPORT_FAILED<br>-32051: CATHEDRAL_IMPORT_FAILED |
| -32060 to -32069 | Deployment | -32060: DEPLOYMENT_FAILED |
| -32070 to -32079 | Environment | -32070: ENV_VAR_NOT_FOUND |
| -32000 to -32009 | Generic | -32000: INTERNAL_ERROR<br>-32001: VALIDATION_ERROR |

## Error Response Format

```json
{
  "content": [{
    "type": "text",
    "text": "Project 'my-project' not found",
    "error_code": -32010,
    "details": {
      "project": "my-project"
    }
  }],
  "isError": true
}
```

## Success Response Format

```json
{
  "content": [{
    "type": "text",
    "text": "{...json data...}"
  }]
}
```

## Tips

1. **Connection Pooling**: Database queries automatically reuse connections for better performance
2. **Error Handling**: Check `error_code` field for programmatic error handling
3. **Secrets**: `secret_export` requires Age decryption keys to be available
4. **Packages**: Cathedral packages are portable - can move between TempleDB instances
5. **Path Patterns**: Use SQL LIKE syntax (%, _) for file searches
6. **Context Switching** (NEW): Set a default project to avoid repeating project parameter
7. **Natural Language** (NEW): Use `schema_explore` for human-friendly database queries
8. **Resources** (NEW): Resources are read-only and can be subscribed to by MCP clients

## Configuration

MCP server reads from `.mcp.json`:

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

## Testing

```bash
# Test server
echo '{"jsonrpc":"2.0","id":1,"method":"initialize",...}' | ./templedb mcp serve

# Verify tools
python3 -c "from src.mcp_server import MCPServer; print(len(MCPServer().tools))"
```

---

**Quick Reference Version:** 1.2
**Last Updated:** 2026-03-21
**New Features:** Context management, schema exploration, MCP resources
