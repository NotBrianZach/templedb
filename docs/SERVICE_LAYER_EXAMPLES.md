# Service Layer Usage Examples

## Quick Start

The service layer provides clean, testable business logic that can be used from CLI commands, scripts, TUI, or API endpoints.

### Basic Usage

```python
from services.context import ServiceContext

# Create context (singleton-like, lazy-loads dependencies)
ctx = ServiceContext()

# Get service
project_service = ctx.get_project_service()

# Use service methods
project = project_service.get_by_slug('my-project')
all_projects = project_service.get_all()
```

## ProjectService Examples

### Create a New Project

```python
from services.context import ServiceContext
from pathlib import Path

ctx = ServiceContext()
service = ctx.get_project_service()

# Initialize current directory as project
result = service.init_project(
    project_path=Path.cwd(),
    slug='my-awesome-project',
    name='My Awesome Project'
)

print(f"Created project: {result['slug']}")
print(f"Project ID: {result['project_id']}")
print(f"Root: {result['root']}")
```

### Import Existing Project

```python
from services.context import ServiceContext
from pathlib import Path

ctx = ServiceContext()
service = ctx.get_project_service()

# Import from filesystem
stats = service.import_project(
    project_path=Path('/path/to/project'),
    slug='my-project',
    dry_run=False
)

print(f"Files imported: {stats.files_imported}")
print(f"Content stored: {stats.content_stored}")
```

### List All Projects

```python
from services.context import ServiceContext

ctx = ServiceContext()
service = ctx.get_project_service()

projects = service.get_all()

for project in projects:
    print(f"{project['slug']}: {project['file_count']} files")
```

### Get Project with Validation

```python
from services.context import ServiceContext
from error_handler import ResourceNotFoundError

ctx = ServiceContext()
service = ctx.get_project_service()

try:
    # required=True raises exception if not found
    project = service.get_by_slug('my-project', required=True)
    print(f"Found: {project['name']}")
except ResourceNotFoundError as e:
    print(f"Error: {e}")
    print(f"Solution: {e.solution}")
```

### Sync Project from Filesystem

```python
from services.context import ServiceContext

ctx = ServiceContext()
service = ctx.get_project_service()

# Re-import all files
stats = service.sync_project('my-project')
print(f"Synced {stats.files_imported} files")
```

### Delete Project

```python
from services.context import ServiceContext

ctx = ServiceContext()
service = ctx.get_project_service()

# Deletes project and all related data (cascade)
service.delete_project('old-project')
print("Project deleted")
```

## DeploymentService Examples

### Deploy to Production

```python
from services.context import ServiceContext

ctx = ServiceContext()
service = ctx.get_deployment_service()

result = service.deploy(
    project_slug='my-project',
    target='production',
    dry_run=False
)

if result.success:
    print(f"✅ Deployed successfully!")
    print(f"Work dir: {result.work_dir}")
else:
    print(f"❌ Deployment failed: {result.message}")
```

### Dry Run Deployment

```python
from services.context import ServiceContext

ctx = ServiceContext()
service = ctx.get_deployment_service()

# Test deployment without making changes
result = service.deploy(
    project_slug='my-project',
    target='staging',
    dry_run=True
)

print(f"Would deploy to: {result.work_dir}")
```

### Get Deployment Status

```python
from services.context import ServiceContext

ctx = ServiceContext()
service = ctx.get_deployment_service()

status = service.get_deployment_status('my-project')

print(f"Targets: {len(status['targets'])}")
print(f"Deploy scripts: {len(status['deploy_scripts'])}")
print(f"Migrations: {status['migration_count']}")

for target in status['targets']:
    print(f"  - {target['target_name']} ({target['target_type']})")
```

## VCSService Examples

### Stage Files

```python
from services.context import ServiceContext

ctx = ServiceContext()
service = ctx.get_vcs_service()

# Stage all modified files
count = service.stage_files(
    project_slug='my-project',
    stage_all=True
)
print(f"Staged {count} files")

# Or stage specific files
count = service.stage_files(
    project_slug='my-project',
    file_patterns=['src/*.py', 'README.md']
)
```

### Create Commit

```python
from services.context import ServiceContext

ctx = ServiceContext()
service = ctx.get_vcs_service()

result = service.commit(
    project_slug='my-project',
    message='Add new feature',
    author='John Doe <john@example.com>'
)

print(f"Commit: {result.commit_hash[:8]}")
print(f"Files: {result.file_count}")
```

### Get Status

```python
from services.context import ServiceContext

ctx = ServiceContext()
service = ctx.get_vcs_service()

status = service.get_status('my-project')

if status['has_branch']:
    print(f"Branch: {status['branch']}")
    print(f"Staged: {len(status['staged'])} files")
    print(f"Modified: {len(status['modified'])} files")
    print(f"Untracked: {len(status['untracked'])} files")
```

### Unstage Files

```python
from services.context import ServiceContext

ctx = ServiceContext()
service = ctx.get_vcs_service()

# Unstage all
count = service.unstage_files(
    project_slug='my-project',
    unstage_all=True
)

# Or unstage specific files
count = service.unstage_files(
    project_slug='my-project',
    file_patterns=['*.log']
)
```

## EnvironmentService Examples

### List Environments

```python
from services.context import ServiceContext

ctx = ServiceContext()
service = ctx.get_environment_service()

# List all environments
all_envs = service.list_environments()

# List for specific project
project_envs = service.list_environments('my-project')

for env in project_envs:
    print(f"{env['env_name']}: {env['package_count']} packages")
```

### Get Environment

```python
from services.context import ServiceContext

ctx = ServiceContext()
service = ctx.get_environment_service()

env = service.get_environment('my-project', 'dev')

if env:
    print(f"Environment: {env['env_name']}")
    print(f"Description: {env['description']}")
```

### Generate Nix Expression

```python
from services.context import ServiceContext

ctx = ServiceContext()
service = ctx.get_environment_service()

nix_file = service.generate_nix_expression(
    project_slug='my-project',
    env_name='dev'
)

print(f"Generated: {nix_file}")
```

### Prepare Environment Session

```python
from services.context import ServiceContext

ctx = ServiceContext()
service = ctx.get_environment_service()

session = service.prepare_environment_session(
    project_slug='my-project',
    env_name='dev'
)

print(f"Session ID: {session.session_id}")
print(f"Nix file: {session.nix_file}")

# ... enter environment ...

# Later, end session
service.end_environment_session(
    session_id=session.session_id,
    exit_code=0
)
```

## Error Handling

All service methods raise typed exceptions that can be caught and handled:

```python
from services.context import ServiceContext
from error_handler import (
    ResourceNotFoundError,
    ValidationError,
    DeploymentError
)

ctx = ServiceContext()
service = ctx.get_project_service()

try:
    project = service.get_by_slug('nonexistent', required=True)
except ResourceNotFoundError as e:
    print(f"Not found: {e}")
    print(f"Solution: {e.solution}")

try:
    service.create_project(slug='Invalid Slug!')
except ValidationError as e:
    print(f"Invalid: {e}")
    print(f"Solution: {e.solution}")
```

## Using in CLI Commands

Pattern for CLI commands using services:

```python
from cli.core import Command
from error_handler import ValidationError, ResourceNotFoundError

class MyCommands(Command):
    def __init__(self):
        super().__init__()
        from services.context import ServiceContext
        self.ctx = ServiceContext()
        self.service = self.ctx.get_project_service()

    def my_command(self, args) -> int:
        """My command handler"""
        try:
            # Call service method
            result = self.service.some_operation(
                slug=args.slug,
                option=args.option
            )

            # Present results to user
            print(f"✅ Success: {result}")
            return 0

        except ValidationError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            if e.solution:
                logger.info(f"💡 {e.solution}")
            return 1

        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            logger.debug("Full traceback:", exc_info=True)
            return 1
```

## Using in Scripts

Services make it easy to write automation scripts:

```python
#!/usr/bin/env python3
"""Bulk import projects"""
import sys
from pathlib import Path

sys.path.insert(0, 'src')

from services.context import ServiceContext

def main():
    ctx = ServiceContext()
    service = ctx.get_project_service()

    projects_dir = Path('/path/to/projects')

    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue

        try:
            print(f"Importing {project_dir.name}...")
            stats = service.import_project(
                project_path=project_dir,
                slug=project_dir.name
            )
            print(f"  ✓ {stats.files_imported} files imported")

        except Exception as e:
            print(f"  ✗ Failed: {e}")

if __name__ == '__main__':
    main()
```

## Testing Services

Services are designed to be easily testable:

```python
import pytest
from unittest.mock import Mock
from services.project_service import ProjectService
from error_handler import ValidationError

def test_create_project_validates_slug():
    """Test that invalid slugs are rejected"""
    mock_context = Mock()
    mock_context.project_repo.get_by_slug.return_value = None

    service = ProjectService(mock_context)

    # Should raise ValidationError for invalid slug
    with pytest.raises(ValidationError) as exc_info:
        service.create_project(slug='Invalid Slug!')

    assert 'Invalid slug format' in str(exc_info.value)

def test_create_project_checks_duplicates():
    """Test that duplicate slugs are rejected"""
    mock_context = Mock()
    mock_context.project_repo.get_by_slug.return_value = {'id': 1}

    service = ProjectService(mock_context)

    with pytest.raises(ValidationError) as exc_info:
        service.create_project(slug='existing-project')

    assert 'already exists' in str(exc_info.value)
```

## Best Practices

### 1. Always use ServiceContext

```python
# ✅ Good
from services.context import ServiceContext
ctx = ServiceContext()
service = ctx.get_project_service()

# ❌ Bad - don't instantiate services directly
from services.project_service import ProjectService
service = ProjectService(???)  # What context?
```

### 2. Catch typed exceptions

```python
# ✅ Good - specific exception handling
try:
    project = service.get_by_slug('foo', required=True)
except ResourceNotFoundError as e:
    print(f"Not found: {e.solution}")

# ❌ Bad - generic exception swallows details
try:
    project = service.get_by_slug('foo', required=True)
except Exception as e:
    print("Something failed")
```

### 3. Use required=True for validation

```python
# ✅ Good - let service validate
project = service.get_by_slug('my-project', required=True)
# Raises ResourceNotFoundError if not found

# ❌ Bad - manual null checking
project = service.get_by_slug('my-project')
if not project:
    raise Exception("Not found")
```

### 4. Separate presentation from logic

```python
# ✅ Good - service returns data, command presents
def my_command(self, args):
    result = self.service.deploy(args.slug, args.target)
    if result.success:
        print(f"✅ Deployed to {result.target}")
    return 0 if result.success else 1

# ❌ Bad - mixing presentation in service
def deploy(self, slug, target):
    print(f"🚀 Deploying {slug}...")  # Don't print from service!
    # ...
```

## Migration Guide

### Before (Direct Repository Access)

```python
class MyCommands(Command):
    def __init__(self):
        self.project_repo = ProjectRepository()

    def my_command(self, args):
        project = self.project_repo.get_by_slug(args.slug)
        if not project:
            logger.error("Project not found")
            return 1

        # Business logic here
        # More validation here
        # Database operations here

        print("Success")
        return 0
```

### After (Service Layer)

```python
class MyCommands(Command):
    def __init__(self):
        from services.context import ServiceContext
        self.ctx = ServiceContext()
        self.service = self.ctx.get_project_service()

    def my_command(self, args):
        try:
            # Business logic in service
            result = self.service.my_operation(args.slug)

            # Only presentation in command
            print(f"✅ Success: {result}")
            return 0

        except ResourceNotFoundError as e:
            logger.error(f"{e}")
            return 1
```

## Summary

The service layer provides:

- **Clean API**: Simple methods with clear inputs/outputs
- **Type Safety**: Typed exceptions with helpful solutions
- **Reusability**: Use same logic everywhere (CLI, TUI, API, scripts)
- **Testability**: Mock contexts and repositories for unit tests
- **Maintainability**: Business logic separated from presentation

All commands should follow this pattern for consistency and maintainability.
