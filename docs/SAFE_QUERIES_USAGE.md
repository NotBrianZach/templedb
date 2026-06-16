# Safe Queries API Usage Guide

## Overview

TempleDB provides a **consolidated Safe Queries API** that enforces project-scoped filtering for all queries. This prevents cross-project data corruption and incorrect query results.

## The Problem

Many TempleDB tables have fields that are **NOT globally unique** - they're only unique within a project:

- `file_path` in `project_files` - Multiple projects can have `README.md`
- `target_name` in `deployment_targets` - Multiple projects can have `production`
- `endpoint_path` in `api_endpoints` - Multiple projects can have `/api/users`
- `branch_name` in `vcs_branches` - Multiple projects can have `main`
- `env_name` in `nix_environments` - Multiple projects can have `dev`
- `migration_number` in `database_migrations` - Multiple projects can have `001`

**Without proper filtering, queries can return the wrong data or corrupt the wrong project's records.**

## The Solution: SafeQueries API

The `SafeQueries` API **enforces** project context at the function signature level - you literally cannot call these methods without providing `project_id` or `project_slug`.

## Quick Start

```python
from safe_queries import SafeQueries

queries = SafeQueries()

# Files
file = queries.files.get_by_path('README.md', project_id=1)
content = queries.files.get_content('src/app.ts', project_slug='my-project')
files = queries.files.list_files(project_id=1, pattern='src/**/*.ts')

# Deployment Targets
target = queries.targets.get_target('production', project_id=1)
targets = queries.targets.list_targets(project_id=1, target_type='database')

# API Endpoints
endpoint = queries.endpoints.get_endpoint('/api/users', 'GET', project_id=1)
endpoints = queries.endpoints.list_endpoints(project_id=1)

# Database Migrations
migration = queries.migrations.get_migration('001', project_id=1)
migrations = queries.migrations.list_migrations(project_id=1, status='applied')

# Nix Environments
env = queries.environments.get_environment('dev', project_id=1)
envs = queries.environments.list_environments(project_id=1)

# VCS Branches
branch = queries.branches.get_branch('main', project_id=1)
branches = queries.branches.list_branches(project_id=1)
```

## Available Sub-APIs

### 1. `queries.files` - SafeFileQueries

Query project files (from `project_files` table).

**Methods**:
- `get_by_path(file_path, project_id=..., project_slug=...)` - Get file metadata
- `get_content(file_path, project_id=..., project_slug=...)` - Get file content
- `list_files(project_id=..., project_slug=..., pattern=...)` - List files with GLOB pattern

**Example**:
```python
# Get a specific file
file = queries.files.get_by_path('src/app.ts', project_id=1)
print(f"File: {file['file_path']}, Lines: {file['lines_of_code']}")

# Get file content
content = queries.files.get_content('README.md', project_slug='my-project')
print(content['content_text'])

# List TypeScript files
ts_files = queries.files.list_files(project_id=1, pattern='**/*.ts')
```

### 2. `queries.targets` - SafeDeploymentQueries

Query deployment targets (from `deployment_targets` table).

**Methods**:
- `get_target(target_name, target_type=..., project_id=..., project_slug=...)` - Get specific target
- `list_targets(project_id=..., project_slug=..., target_type=...)` - List targets

**Example**:
```python
# Get production database target
prod_db = queries.targets.get_target('production', target_type='database', project_id=1)
print(f"Provider: {prod_db['provider']}, Region: {prod_db['region']}")

# List all targets
targets = queries.targets.list_targets(project_id=1)
for target in targets:
    print(f"{target['target_name']}: {target['target_type']}")
```

### 3. `queries.endpoints` - SafeAPIQueries

Query API endpoints (from `api_endpoints` table).

**Methods**:
- `get_endpoint(endpoint_path, http_method, project_id=..., project_slug=...)` - Get specific endpoint
- `list_endpoints(project_id=..., project_slug=..., http_method=...)` - List endpoints

**Example**:
```python
# Get specific endpoint
users_endpoint = queries.endpoints.get_endpoint('/api/users', 'GET', project_id=1)
print(f"Auth required: {users_endpoint['requires_auth']}")

# List all POST endpoints
post_endpoints = queries.endpoints.list_endpoints(project_id=1, http_method='POST')
```

### 4. `queries.migrations` - SafeMigrationQueries

Query database migrations (from `database_migrations` table).

**Methods**:
- `get_migration(migration_number, project_id=..., project_slug=...)` - Get specific migration
- `list_migrations(project_id=..., project_slug=..., status=...)` - List migrations

**Example**:
```python
# Get specific migration
migration = queries.migrations.get_migration('001', project_id=1)
print(f"Status: {migration['status']}, Applied: {migration['applied_at']}")

# List pending migrations
pending = queries.migrations.list_migrations(project_id=1, status='pending')
```

### 5. `queries.environments` - SafeEnvironmentQueries

Query Nix environments (from `nix_environments` table).

**Methods**:
- `get_environment(env_name, project_id=..., project_slug=...)` - Get specific environment
- `list_environments(project_id=..., project_slug=...)` - List environments

**Example**:
```python
# Get dev environment
dev_env = queries.environments.get_environment('dev', project_id=1)
print(f"Packages: {dev_env['nix_packages']}")

# List all environments
envs = queries.environments.list_environments(project_id=1)
```

### 6. `queries.branches` - SafeBranchQueries

Query VCS branches (from `vcs_branches` table).

**Methods**:
- `get_branch(branch_name, project_id=..., project_slug=...)` - Get specific branch
- `list_branches(project_id=..., project_slug=...)` - List branches

**Example**:
```python
# Get main branch
main = queries.branches.get_branch('main', project_id=1)
print(f"Default: {main['is_default']}")

# List all branches
branches = queries.branches.list_branches(project_id=1)
```

## Project ID vs Project Slug

All methods accept **either** `project_id` OR `project_slug` (but not both):

```python
# Using project_id (direct database ID)
file = queries.files.get_by_path('README.md', project_id=1)

# Using project_slug (human-readable identifier)
file = queries.files.get_by_path('README.md', project_slug='my-project')

# Error: Can't provide both
# file = queries.files.get_by_path('README.md', project_id=1, project_slug='my-project')
```

**When to use which**:
- Use `project_id` when you already have the numeric ID (faster, no lookup)
- Use `project_slug` when working with user input or readable identifiers

## Error Handling

### Missing Project Context

```python
# ❌ ERROR: Missing required project context
try:
    file = queries.files.get_by_path('README.md')  # No project_id or project_slug!
except ValueError as e:
    print(e)  # "Either project_id or project_slug must be provided"
```

### Invalid Project

```python
# ❌ ERROR: Project doesn't exist
from safe_queries import QueryValidationError

try:
    file = queries.files.get_by_path('README.md', project_slug='nonexistent')
except QueryValidationError as e:
    print(e)  # "Project not found: nonexistent"
```

### Not Found

```python
# ✅ Returns None if not found (not an error)
file = queries.files.get_by_path('missing.txt', project_id=1)
if file is None:
    print("File not found")
```

## Integration with Existing Code

### Option 1: Direct Import

```python
from safe_queries import SafeQueries

def my_function(project_id: int):
    queries = SafeQueries()
    files = queries.files.list_files(project_id=project_id)
    return files
```

### Option 2: Use in Repository Classes

```python
from safe_queries import SafeQueries

class MyRepository:
    def __init__(self):
        self.queries = SafeQueries()

    def get_project_data(self, project_id: int):
        files = self.queries.files.list_files(project_id=project_id)
        targets = self.queries.targets.list_targets(project_id=project_id)
        return {'files': files, 'targets': targets}
```

### Option 3: CLI Commands

```python
from safe_queries import SafeQueries

def deploy_command(project_slug: str, target_name: str):
    queries = SafeQueries()

    # Get project
    from repositories import ProjectRepository
    project = ProjectRepository().get_project_by_slug(project_slug)

    # Get deployment target (safely!)
    target = queries.targets.get_target(
        target_name,
        project_slug=project_slug  # Or use project_id=project['id']
    )

    if not target:
        print(f"Target '{target_name}' not found in project '{project_slug}'")
        return

    print(f"Deploying to {target['provider']}...")
```

## Migration from Existing Code

### Before (Unsafe)

```python
# ❌ UNSAFE: Could return file from wrong project
cursor.execute("""
    SELECT * FROM project_files WHERE file_path = ?
""", ('README.md',))
```

### After (Safe)

```python
# ✅ SAFE: Always scoped to project
queries = SafeQueries()
file = queries.files.get_by_path('README.md', project_id=project_id)
```

## Best Practices

1. **Always use SafeQueries for project-scoped tables**
   - Use `SafeQueries` instead of raw SQL for files, targets, endpoints, etc.

2. **Pass project context early**
   - Get `project_id` or `project_slug` at the start of your function
   - Pass it to all SafeQueries calls

3. **Prefer project_id over project_slug when possible**
   - `project_id` is faster (no lookup required)
   - Use `project_slug` only when needed for user-facing code

4. **Handle None returns gracefully**
   - SafeQueries returns `None` when not found (doesn't raise exception)
   - Always check for `None` before using the result

5. **Use list methods for bulk operations**
   - `list_files()`, `list_targets()`, etc. are more efficient than multiple gets

## See Also

- [QUERY_BEST_PRACTICES.md](../QUERY_BEST_PRACTICES.md) - SQL query best practices
- [SAFE_QUERY_ANALYSIS.md](./SAFE_QUERY_ANALYSIS.md) - Technical analysis of the API
- [safe_queries.py](../src/safe_queries.py) - Source code
- [test_safe_queries.py](../tests/test_safe_queries.py) - Test examples
