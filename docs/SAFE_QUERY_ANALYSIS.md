# Safe Query Analysis for TempleDB

## Executive Summary

**SafeFileQueries Integration Status**: ✅ Created but **NOT YET INTEGRATED** into the codebase

**Good News**: The existing codebase already follows safe query patterns! The repositories are well-designed and consistently filter by `project_id`.

## Analysis Results

### 1. Tables with Non-Unique Fields (Requiring Project Context)

Based on UNIQUE constraints, these tables have fields that are NOT globally unique:

| Table | Non-Unique Fields | UNIQUE Constraint | Status |
|-------|------------------|-------------------|---------|
| `project_files` | `file_path` | `(project_id, file_path)` | ✅ **SafeFileQueries created** |
| `deployment_targets` | `target_name`, `target_type` | `(project_id, target_name, target_type)` | ⚠️ **Needs safe API** |
| `api_endpoints` | `endpoint_path`, `http_method` | `(project_id, endpoint_path, http_method)` | ⚠️ **Needs safe API** |
| `database_migrations` | `migration_number` | `(project_id, migration_number)` | ⚠️ **Needs safe API** |
| `vcs_branches` | `branch_name` | `(project_id, branch_name)` | ✅ **VCSRepository already safe** |
| `nix_environments` | `env_name` | `(project_id, env_name)` | ⚠️ **Needs safe API** |
| `checkouts` | `checkout_path` | `(project_id, checkout_path)` | ✅ **CheckoutRepository already safe** |

### 2. Existing Repository Safety Analysis

#### ✅ **FileRepository** (src/repositories/file_repository.py)
- **Status**: SAFE - All methods require `project_id`
- Key methods:
  - `get_files_for_project(project_id)` ✓
  - `get_file_by_path(project_id, file_path)` ✓
  - `count_files(project_id)` ✓
  - `get_file_types_summary(project_id)` ✓

#### ✅ **VCSRepository** (src/repositories/vcs_repository.py)
- **Status**: SAFE - All methods require `project_id`
- Key methods:
  - `get_or_create_branch(project_id, branch_name)` ✓
  - `create_commit(project_id, ...)` ✓
  - `get_commit_history(project_id, ...)` ✓

#### ✅ **CLI Commands** (src/cli/commands/*)
- **Status**: SAFE - All file/branch queries include `project_id`
- Examples:
  - `target.py`: Always filters by `project_id` ✓
  - `env.py`: Always filters by `project_id` ✓
  - `vcs.py`: Always filters by `project_id` ✓
  - `deploy.py`: Always filters by `project_id` ✓

#### ✅ **Importer** (src/importer/__init__.py)
- **Status**: SAFE - All queries use `self.project_id` ✓

### 3. System-Wide Aggregate Queries (Intentionally Cross-Project)

These queries are SAFE because they intentionally query ALL projects:

#### src/tui.py:278-284
```python
# System-wide statistics (intentional)
file_count = query_one("SELECT COUNT(*) as count FROM project_files")['count']
total_loc = query_one("SELECT SUM(lines_of_code) as total FROM project_files")['total']
```
**Status**: ✅ SAFE - These are system-wide aggregates, not specific file lookups

#### src/cli/commands/system.py:116-120
```python
# System status command (intentional)
("Files", query_one("SELECT COUNT(*) as count FROM project_files")['count'])
("Lines of Code", query_one("SELECT SUM(lines_of_code) as total FROM project_files")['total'])
```
**Status**: ✅ SAFE - System status showing totals across all projects

### 4. SafeFileQueries Integration Status

**Current Status**: ❌ NOT INTEGRATED

```bash
# FileRepository usage: 6 files
src/cli/commands/checkout.py
src/cli/commands/search.py
src/cli/commands/project.py
src/cli/commands/config.py
src/cli/commands/commit.py
src/repositories/__init__.py

# SafeFileQueries usage: 0 files (only self-reference)
```

**Why Not a Problem (Yet)**:
- FileRepository already requires `project_id` for all methods
- SafeFileQueries adds extra features (query validation, project_slug support)
- Both are safe, but SafeFileQueries is more feature-rich

## Recommendations

### Priority 1: Expand Safe Query APIs

Create safe wrappers for the remaining non-unique field tables:

1. **SafeDeploymentQueries** for `deployment_targets`
   - `get_target(project_id, target_name, target_type)`
   - `list_targets(project_id)`

2. **SafeAPIQueries** for `api_endpoints`
   - `get_endpoint(project_id, endpoint_path, http_method)`
   - `list_endpoints(project_id)`

3. **SafeMigrationQueries** for `database_migrations`
   - `get_migration(project_id, migration_number)`
   - `list_migrations(project_id)`

4. **SafeEnvironmentQueries** for `nix_environments`
   - `get_environment(project_id, env_name)`
   - `list_environments(project_id)`

### Priority 2: Integrate SafeFileQueries

**Options**:

1. **Option A: Deprecate FileRepository, use SafeFileQueries**
   - Pros: More features (query validation, project_slug support)
   - Cons: Breaking change for existing code

2. **Option B: Make FileRepository extend SafeFileQueries**
   - Pros: Backward compatible, adds features
   - Cons: Requires refactoring

3. **Option C: Keep both, document when to use each**
   - Pros: No breaking changes
   - Cons: Confusing for developers

**Recommendation**: Option B - Make FileRepository extend SafeFileQueries

### Priority 3: Create Consolidated Safe Query API

Create a single `SafeQueries` class that wraps all safe query methods:

```python
from safe_queries import SafeQueries

queries = SafeQueries()

# Files
file = queries.files.get_by_path('README.md', project_id=1)

# Deployments
target = queries.deployments.get_target('production', project_id=1)

# Environments
env = queries.environments.get_environment('dev', project_id=1)
```

### Priority 4: Add Pre-Commit Hook

Add a pre-commit hook that validates queries:

```python
# In pre-commit hook
from safe_file_queries import SafeFileQueries

for query in extract_queries_from_code():
    SafeFileQueries.validate_file_query(query)
```

## Summary

| Aspect | Status | Notes |
|--------|--------|-------|
| Existing Code | ✅ SAFE | Repositories already follow safe patterns |
| SafeFileQueries | ✅ CREATED | Comprehensive API with validation |
| Integration | ❌ NOT DONE | Created but not used anywhere |
| Other Tables | ⚠️ PARTIAL | Need safe wrappers for 4 more tables |

**Bottom Line**: The codebase is already quite safe! SafeFileQueries adds valuable features (validation, project_slug support) but requires integration work. Consider creating a consolidated safe query API for all project-scoped tables.
