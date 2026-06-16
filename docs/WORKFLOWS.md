# TempleDB Workflows

Quick reference for using TempleDB workflows with code intelligence.

## Quick Start

```bash
# List available workflows
templedb mcp serve <<< '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"templedb_workflow_list"}}'

# Validate a workflow
templedb mcp serve <<< '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"templedb_workflow_validate","arguments":{"workflow":"safe_deployment"}}}'

# Execute workflow (dry run)
templedb mcp serve <<< '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"templedb_workflow_execute","arguments":{"workflow":"code_intelligence_bootstrap","project":"myapp","dry_run":true}}}'
```

## Available Workflows

### 1. Code Intelligence Bootstrap

**Purpose:** Initialize code intelligence (symbols, dependencies, clusters)

**Usage:**
```json
{
  "workflow": "code_intelligence_bootstrap",
  "project": "myapp"
}
```

**What it does:**
- Extracts functions, classes, methods from code
- Builds cross-file dependency graph
- Enables impact analysis and code search

### 2. Safe Deployment

**Purpose:** Deploy with impact analysis, tests, and automatic rollback

**Basic usage:**
```json
{
  "workflow": "safe_deployment",
  "project": "myapp",
  "variables": {
    "primary_symbol": "authenticate_user",
    "staging_health_url": "http://staging.myapp.com/health",
    "production_health_url": "https://myapp.com/health",
    "previous_version": "v2.1.0"
  }
}
```

**Key variables:**
- `primary_symbol` - Symbol for impact analysis (required)
- `staging_health_url` - Staging health check URL
- `production_health_url` - Production health check URL
- `previous_version` - Version to rollback to on failure
- `test_command` - Override test command (default: pytest)
- `deploy_backend` - nixops4 or generic (default: generic)

**What it does:**
1. Analyzes blast radius of changes
2. Runs test suite
3. Deploys to staging with health checks
4. Deploys to production (requires approval)
5. Auto-rollback on health check failure

### 3. Impact-Aware Refactoring

**Purpose:** Refactor with blast radius awareness and test validation

**Usage:**
```json
{
  "workflow": "impact_aware_refactoring",
  "project": "myapp",
  "variables": {
    "target_symbol": "process_payment",
    "max_blast_radius": "150",
    "min_coverage": "80"
  }
}
```

**Key variables:**
- `target_symbol` - Symbol to refactor (required)
- `max_blast_radius` - Max affected symbols (default: 100)
- `min_coverage` - Min test coverage % (default: 70)

**What it does:**
1. Discovers symbol and analyzes impact
2. Validates test coverage meets threshold
3. Creates refactoring branch
4. Runs pre/post refactoring tests
5. Verifies architectural integrity

## Common Patterns

### Dry Run First
Always preview before executing:
```json
{"dry_run": true}
```

### NixOps4 Deployment
```json
{
  "variables": {
    "deploy_backend": "nixops4",
    "nixops_network": "production-cluster"
  }
}
```

### Custom Test Commands
```json
{
  "variables": {
    "test_command": "pytest tests/payment/ -v",
    "coverage_command": "pytest --cov=src/payment --cov-report=term tests/"
  }
}
```

## Troubleshooting

### "Workflow not found"
Check available workflows:
```bash
ls workflows/*.yaml
```

### "Project not found"
Import project first:
```bash
templedb project import /path/to/project
```

### "Health check failed"
1. Verify URL is accessible: `curl http://staging.myapp.com/health`
2. Increase retries in workflow variables
3. Check application logs

### "Tests failed"
Run tests manually to debug:
```bash
pytest tests/ -v --tb=short
```

### "Blast radius too large"
Either:
- Break changes into smaller pieces
- Increase `max_blast_radius` variable (if justified)

## Creating Custom Workflows

Minimal workflow example:

```yaml
workflow:
  name: "my-workflow"
  version: "1.0"
  description: "My custom workflow"

  phases:
    - name: "deploy"
      tasks:
        - name: "deploy_app"
          type: "bash"
          command: "deploy.sh"

      validation:
        - type: "health_check"
          target: "production"
```

Save to `workflows/my_workflow.yaml` and use via:
```json
{"workflow": "my_workflow", "project": "myapp"}
```

## MCP Tools

- `templedb_workflow_list` - List workflows
- `templedb_workflow_validate` - Validate workflow YAML
- `templedb_workflow_execute` - Execute workflow
- `templedb_workflow_status` - Check status (placeholder)

## Documentation

- Workflow definitions: `workflows/*.yaml`
- Examples: This file
- Phase design: `PHASE_2_DESIGN.md`
- Code intelligence: `CODE_INTELLIGENCE_STATUS.md`
