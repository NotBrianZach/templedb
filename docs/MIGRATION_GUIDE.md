# Command Migration Guide

Step-by-step guide for migrating remaining commands to use the service layer.

---

## Overview

This guide shows how to migrate command files to use the service layer pattern established in Phases 1 and 2.

**Commands Already Migrated:**
- ✅ `project.py` - Uses ProjectService
- ✅ `deploy.py` - Uses DeploymentService
- ✅ `vcs.py` - Uses VCSService
- ✅ `env.py` - Uses EnvironmentService

**Commands Remaining:**
- `secret.py` - Secret management
- `target.py` - Deployment target configuration
- `migration.py` - Database migrations
- `config.py` - Configuration management
- `cathedral.py` - Cathedral package operations
- Others (lower priority)

---

## Migration Pattern

### Step 1: Create Service Class

First, create a service class in `src/services/`:

```python
#!/usr/bin/env python3
"""
<Domain> Service - Business logic for <domain> operations
"""
from typing import List, Dict, Any
from services.base import BaseService
from error_handler import ResourceNotFoundError, ValidationError


class MyDomainService(BaseService):
    """
    Service layer for <domain> operations.

    Provides business logic for <describe what it does>
    """

    def __init__(self, context):
        super().__init__()
        self.ctx = context
        self.project_repo = context.project_repo
        # Add other repos as needed

    def my_operation(self, param1: str, param2: int) -> Dict[str, Any]:
        """
        Describe what this operation does.

        Args:
            param1: Description
            param2: Description

        Returns:
            Dictionary with result data

        Raises:
            ResourceNotFoundError: If resource not found
            ValidationError: If validation fails
        """
        # Validation
        self._validate_required(param1, 'param1')

        # Business logic here
        # ...

        return {'result': 'data'}
```

### Step 2: Add Service to ServiceContext

Edit `src/services/context.py`:

```python
def get_my_domain_service(self):
    """Get MyDomainService instance"""
    if self._my_domain_service is None:
        from services.my_domain_service import MyDomainService
        self._my_domain_service = MyDomainService(self)
    return self._my_domain_service
```

### Step 3: Update Command Class

Update the command file (`src/cli/commands/my_domain.py`):

```python
class MyDomainCommands(Command):
    """My domain command handlers"""

    def __init__(self):
        super().__init__()
        from services.context import ServiceContext
        self.ctx = ServiceContext()
        self.service = self.ctx.get_my_domain_service()

    @safe_command("my_command")
    def my_command(self, args) -> int:
        """My command description"""
        # Just call service and present results
        result = self.service.my_operation(
            param1=args.param1,
            param2=args.param2
        )

        print(f"✅ Success: {result}")
        return 0
```

### Step 4: Add Tests

Create `tests/unit/services/test_my_domain_service.py`:

```python
def test_my_operation_validates_input():
    """Test that my_operation validates input"""
    from services.my_domain_service import MyDomainService
    from error_handler import ValidationError

    # Create mock context
    mock_context = Mock()
    mock_context.project_repo = Mock()

    # Create service
    service = MyDomainService(mock_context)

    # Test - should raise ValidationError
    with pytest.raises(ValidationError):
        service.my_operation(param1=None, param2=1)
```

---

## Example: Migrating Secret Management

### Current State (`secret.py`)

```python
class SecretCommands(Command):
    def init(self, args) -> int:
        # 50+ lines of mixed logic
        project = self.get_project_or_exit(args.project)
        # AGE encryption setup
        # SOPS configuration
        # File creation
        # Error handling
```

### Step 1: Create SecretService

`src/services/secret_service.py`:

```python
class SecretService(BaseService):
    """Service for secret management operations"""

    def __init__(self, context):
        super().__init__()
        self.ctx = context
        self.project_repo = context.project_repo

    def initialize_secrets(
        self,
        project_slug: str,
        profile: str = 'default',
        age_recipient: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Initialize secrets for a project.

        Args:
            project_slug: Project slug
            profile: Secret profile name
            age_recipient: AGE public key for encryption

        Returns:
            Dictionary with initialization results

        Raises:
            ResourceNotFoundError: If project not found
            ValidationError: If configuration invalid
        """
        # Get project
        project = self.project_repo.get_by_slug(project_slug)
        if not project:
            raise ResourceNotFoundError(
                f"Project '{project_slug}' not found",
                solution="Run 'templedb project list' to see available projects"
            )

        # Validate age_recipient if provided
        if age_recipient:
            self._validate_age_recipient(age_recipient)

        # Initialize secrets (business logic here)
        # ...

        return {
            'project_slug': project_slug,
            'profile': profile,
            'secrets_file': '/path/to/secrets',
            'initialized': True
        }

    def _validate_age_recipient(self, recipient: str):
        """Validate AGE recipient format"""
        if not recipient.startswith('age'):
            raise ValidationError(
                f"Invalid AGE recipient format: {recipient}",
                solution="AGE recipient must start with 'age'"
            )
```

### Step 2: Update SecretCommands

```python
from cli.decorators import safe_command, require_project

class SecretCommands(Command):
    def __init__(self):
        super().__init__()
        from services.context import ServiceContext
        self.ctx = ServiceContext()
        self.service = self.ctx.get_secret_service()

    @safe_command("secret_init")
    @require_project
    def init(self, args) -> int:
        """Initialize secrets for a project"""
        result = self.service.initialize_secrets(
            project_slug=args.project,
            profile=args.profile or 'default',
            age_recipient=args.age_recipient
        )

        print(f"✅ Initialized secrets for {result['project_slug']}")
        print(f"   Profile: {result['profile']}")
        print(f"   Secrets file: {result['secrets_file']}")
        return 0
```

---

## Common Patterns

### Pattern 1: Validating Project Exists

**Before:**
```python
project = self.get_project_or_exit(args.project)
if not project:
    logger.error("Project not found")
    return 1
```

**After:**
```python
# In service:
project = self.project_repo.get_by_slug(project_slug)
if not project:
    raise ResourceNotFoundError(
        f"Project '{project_slug}' not found",
        solution="Run 'templedb project list'"
    )

# In command:
@safe_command("my_command")
def my_command(self, args) -> int:
    # Error handled automatically by decorator
    result = self.service.my_operation(args.project)
```

### Pattern 2: Input Validation

**Before:**
```python
if not args.name:
    logger.error("Name is required")
    return 1

if len(args.name) > 255:
    logger.error("Name too long")
    return 1
```

**After:**
```python
# In service:
def create_something(self, name: str):
    self._validate_required(name, 'name')

    if len(name) > 255:
        raise ValidationError(
            "Name must be <= 255 characters",
            solution="Use a shorter name"
        )
```

### Pattern 3: Database Queries

**Before:**
```python
# In command
results = self.query_all("""
    SELECT * FROM my_table
    WHERE project_id = ?
""", (project['id'],))
```

**After:**
```python
# In service
def get_my_data(self, project_id: int) -> List[Dict]:
    return self.ctx.base_repo.query_all("""
        SELECT * FROM my_table
        WHERE project_id = ?
    """, (project_id,))

# In command
results = self.service.get_my_data(project['id'])
```

### Pattern 4: Error Handling

**Before:**
```python
try:
    # operation
    result = do_something()
    print("Success")
    return 0
except Exception as e:
    logger.error(f"Failed: {e}")
    logger.debug("Full error:", exc_info=True)
    return 1
```

**After:**
```python
# In service (raise typed exceptions)
def do_something(self):
    if error_condition:
        raise ValidationError("What went wrong", solution="How to fix")

# In command (use decorator)
@safe_command("my_command")
def my_command(self, args) -> int:
    # No try-catch needed - decorator handles it
    result = self.service.do_something()
    print("✅ Success")
    return 0
```

---

## Checklist for Migration

When migrating a command file, follow this checklist:

### Service Layer
- [ ] Create service class in `src/services/`
- [ ] Add service to `ServiceContext` in `src/services/context.py`
- [ ] Add service to exports in `src/services/__init__.py`
- [ ] Move business logic from command to service
- [ ] Add validation in service methods
- [ ] Raise typed exceptions (ValidationError, ResourceNotFoundError, etc.)
- [ ] Add docstrings to all public methods
- [ ] Return structured data (dicts, dataclasses)

### Command Layer
- [ ] Update `__init__` to use ServiceContext
- [ ] Add decorators (`@safe_command`, `@require_project`, etc.)
- [ ] Remove try-catch blocks (let decorator handle)
- [ ] Remove business logic (call service instead)
- [ ] Remove direct repository/database access
- [ ] Keep only presentation logic (print, format)
- [ ] Return simple exit codes (0 for success, 1 for error)

### Testing
- [ ] Create test file in `tests/unit/services/`
- [ ] Add tests for happy path
- [ ] Add tests for error conditions
- [ ] Add tests for validation
- [ ] Mock dependencies (repositories, external calls)
- [ ] Verify exceptions are raised correctly

### Documentation
- [ ] Update command docstrings
- [ ] Add service docstrings
- [ ] Update examples if needed
- [ ] Add migration notes to docs

---

## Benefits Checklist

After migration, your code should have:

- ✅ **Separation of Concerns**: Command only handles presentation
- ✅ **Reusability**: Service works in CLI, TUI, API, scripts
- ✅ **Testability**: Service can be unit tested with mocks
- ✅ **Consistency**: All commands use same patterns
- ✅ **Error Handling**: Automatic via decorators
- ✅ **Validation**: Centralized in service layer
- ✅ **Maintainability**: Easy to find and modify logic

---

## Testing Your Migration

After migrating, verify:

```bash
# 1. Command still works
templedb <your-command> <args>

# 2. Error handling works
templedb <your-command> nonexistent  # Should show friendly error

# 3. Unit tests pass
pytest tests/unit/services/test_your_service.py -v

# 4. Service works programmatically
python3 -c "
from services.context import ServiceContext
ctx = ServiceContext()
service = ctx.get_your_service()
result = service.your_method()
print(result)
"
```

---

## Example Migrations

### Priority 1: Secret Management

**Complexity**: Medium
**Files**: `secret.py` (200 lines)
**Service**: `SecretService`
**Key Operations**:
- `initialize_secrets()` - Init AGE/SOPS
- `edit_secret()` - Edit encrypted secrets
- `export_secrets()` - Export secrets
- `get_secret()` - Retrieve secret value

### Priority 2: Target Management

**Complexity**: Low
**Files**: `target.py` (150 lines)
**Service**: `TargetService`
**Key Operations**:
- `add_target()` - Add deployment target
- `list_targets()` - List targets
- `update_target()` - Update target config
- `remove_target()` - Remove target

### Priority 3: Migration Management

**Complexity**: Medium
**Files**: `migration.py` (200 lines)
**Service**: `MigrationService`
**Key Operations**:
- `list_migrations()` - List available migrations
- `run_migrations()` - Execute migrations
- `get_migration_status()` - Check migration state
- `rollback_migration()` - Rollback migration

---

## Getting Help

If you need help migrating a command:

1. Look at existing migrations:
   - `project.py` - Simple CRUD operations
   - `deploy.py` - Complex orchestration
   - `vcs.py` - Multiple operations
   - `env.py` - External dependencies

2. Check documentation:
   - `docs/SERVICE_LAYER_EXAMPLES.md` - Usage examples
   - `docs/BEFORE_AFTER_COMPARISON.md` - Before/after code
   - `docs/PHASE2_REFACTORING_SUMMARY.md` - Patterns

3. Run existing tests:
   - `pytest tests/unit/services/ -v` - See test patterns
   - `pytest tests/integration/ -v` - See integration patterns

4. Ask questions in code reviews or team discussions

---

## Summary

Migrating to the service layer:

1. **Extracts business logic** → Makes it reusable
2. **Adds validation** → Prevents errors early
3. **Improves testing** → Services can be unit tested
4. **Standardizes errors** → Consistent user experience
5. **Simplifies commands** → Just presentation logic

Follow the established patterns and your migration will be consistent with the rest of the codebase!
