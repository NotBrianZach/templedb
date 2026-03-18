# Error Handling Migration Guide

This guide shows how to migrate TempleDB CLI commands to use the standardized error handling system.

## Quick Reference

**New utilities file:** `src/cli/error_handling_utils.py`

**Imports you'll need:**
```python
from cli.error_handling_utils import (
    handle_errors,           # Decorator for automatic error handling
    require_project,         # Decorator to validate project exists
    validate_path_exists,    # Decorator to validate paths
    print_error,            # User-friendly error messages
    print_warning,          # Warning messages
    print_success,          # Success messages
    confirm_action,         # Ask user for confirmation
    ValidationError,        # Exception for invalid input
    ResourceNotFoundError,  # Exception for missing resources
    ConfigurationError,     # Exception for config issues
    DeploymentError,        # Exception for deployment failures
   DatabaseError           # Exception for database errors
)
```

## Migration Patterns

### Pattern 1: Simple Try-Except Block

**Before:**
```python
def some_command(self, args) -> int:
    try:
        # Do work
        result = self.query_one("SELECT * FROM projects WHERE slug = ?", (args.project,))
        print(f"✅ Success!")
        return 0
    except sqlite3.Error as e:
        logger.error(f"Database error: {e}")
        print(f"❌ Error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"❌ Error: {e}")
        return 1
```

**After:**
```python
from cli.error_handling_utils import handle_errors, print_success

@handle_errors("some command")
def some_command(self, args) -> int:
    # Do work
    result = self.query_one("SELECT * FROM projects WHERE slug = ?", (args.project,))
    print_success("Operation completed")
    return 0
```

**Benefit:** 11 lines → 7 lines, automatic error handling, consistent logging

### Pattern 2: Manual Input Validation

**Before:**
```python
def create_project(self, args) -> int:
    if not args.slug:
        print("❌ Error: Project slug is required")
        logger.error("Missing project slug")
        return 1

    if not args.slug.replace('-', '').isalnum():
        print("❌ Error: Slug must contain only letters, numbers, and hyphens")
        logger.error(f"Invalid slug: {args.slug}")
        return 1

    existing = self.query_one("SELECT id FROM projects WHERE slug = ?", (args.slug,))
    if existing:
        print(f"❌ Error: Project '{args.slug}' already exists")
        logger.error(f"Duplicate project: {args.slug}")
        return 1

    try:
        # Create project
        self.execute("INSERT INTO projects (slug, name) VALUES (?, ?)", (args.slug, args.name))
        print("✅ Project created")
        return 0
    except Exception as e:
        logger.error(f"Failed to create project: {e}")
        print(f"❌ Error: {e}")
        return 1
```

**After:**
```python
from cli.error_handling_utils import handle_errors, ValidationError, print_success

@handle_errors("project create")
def create_project(self, args) -> int:
    # Validate inputs
    if not args.slug:
        raise ValidationError("Project slug is required")

    if not args.slug.replace('-', '').isalnum():
        raise ValidationError(
            f"Invalid slug: {args.slug}\n"
            f"Slug must contain only letters, numbers, and hyphens"
        )

    # Check for duplicates
    existing = self.query_one("SELECT id FROM projects WHERE slug = ?", (args.slug,))
    if existing:
        raise ValidationError(
            f"Project '{args.slug}' already exists.\n"
            f"Use './templedb project list' to see existing projects"
        )

    # Create project
    self.execute("INSERT INTO projects (slug, name) VALUES (?, ?)", (args.slug, args.name))
    print_success(f"Created project '{args.slug}'")
    return 0
```

**Benefit:** 27 lines → 21 lines, better error messages, consistent handling

### Pattern 3: Resource Lookup

**Before:**
```python
def show_project(self, args) -> int:
    if not args.project:
        print("❌ Error: Project slug is required")
        return 1

    project = self.query_one("SELECT * FROM projects WHERE slug = ?", (args.project,))

    if not project:
        print(f"❌ Error: Project '{args.project}' not found")
        print(f"Use './templedb project list' to see available projects")
        return 1

    print(f"Project: {project['name']}")
    print(f"Slug: {project['slug']}")
    return 0
```

**After:**
```python
from cli.error_handling_utils import require_project, handle_errors

@require_project
@handle_errors("project show")
def show_project(self, args) -> int:
    # Project guaranteed to exist by @require_project decorator
    project = self.query_one("SELECT * FROM projects WHERE slug = ?", (args.project,))

    print(f"Project: {project['name']}")
    print(f"Slug: {project['slug']}")
    return 0
```

**Benefit:** 15 lines → 10 lines, automatic project validation

### Pattern 4: File Path Validation

**Before:**
```python
def import_file(self, args) -> int:
    from pathlib import Path

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"❌ Error: File not found: {file_path}")
        print("Check that the path is correct and the file exists")
        logger.error(f"File not found: {file_path}")
        return 1

    try:
        # Import file
        with open(file_path) as f:
            content = f.read()
        # Process...
        print("✅ File imported")
        return 0
    except Exception as e:
        logger.error(f"Import failed: {e}")
        print(f"❌ Error: {e}")
        return 1
```

**After:**
```python
from cli.error_handling_utils import validate_path_exists, handle_errors, print_success

@validate_path_exists('file')
@handle_errors("file import")
def import_file(self, args) -> int:
    from pathlib import Path

    # Path guaranteed to exist by @validate_path_exists decorator
    file_path = Path(args.file)

    with open(file_path) as f:
        content = f.read()
    # Process...

    print_success("File imported successfully")
    return 0
```

**Benefit:** 20 lines → 12 lines, automatic path validation

### Pattern 5: User Confirmation

**Before:**
```python
def delete_project(self, args) -> int:
    project = self.query_one("SELECT * FROM projects WHERE slug = ?", (args.project,))
    if not project:
        print(f"❌ Error: Project '{args.project}' not found")
        return 1

    if not args.force:
        response = input(f"Delete project '{project['name']}' and all its data? [y/N] ")
        if response.lower() not in ('y', 'yes'):
            print("Cancelled")
            return 0

    try:
        self.execute("DELETE FROM projects WHERE id = ?", (project['id'],))
        print(f"✅ Deleted project '{args.project}'")
        return 0
    except Exception as e:
        logger.error(f"Delete failed: {e}")
        print(f"❌ Error: {e}")
        return 1
```

**After:**
```python
from cli.error_handling_utils import (
    require_project,
    handle_errors,
    confirm_action,
    print_success
)

@require_project
@handle_errors("project delete")
def delete_project(self, args) -> int:
    project = self.query_one("SELECT * FROM projects WHERE slug = ?", (args.project,))

    # Confirm destructive action
    if not args.force:
        if not confirm_action(
            f"Delete project '{project['name']}' and all its data?",
            default=False
        ):
            print("Cancelled")
            return 0

    # Delete project
    self.execute("DELETE FROM projects WHERE id = ?", (project['id'],))
    print_success(f"Deleted project '{args.project}'")
    return 0
```

**Benefit:** 22 lines → 20 lines, better UX, keyboard interrupt handling

### Pattern 6: Multiple Error Types

**Before:**
```python
def deploy(self, args) -> int:
    try:
        # Check config exists
        config_file = Path(f"configs/{args.target}.yaml")
        if not config_file.exists():
            print(f"❌ Error: Config file not found: {config_file}")
            print("Create one with: ./templedb deploy init")
            return 1

        # Validate project
        project = self.query_one("SELECT * FROM projects WHERE slug = ?", (args.project,))
        if not project:
            print(f"❌ Error: Project '{args.project}' not found")
            return 1

        # Run deployment
        result = subprocess.run(['./deploy.sh', args.target], check=True)

        print("✅ Deployment completed")
        return 0

    except subprocess.CalledProcessError as e:
        logger.error(f"Deployment failed: {e}")
        print(f"❌ Deployment failed with exit code {e.returncode}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"❌ Error: {e}")
        return 1
```

**After:**
```python
from cli.error_handling_utils import (
    require_project,
    handle_errors,
    ConfigurationError,
    DeploymentError,
    print_success
)
from pathlib import Path
import subprocess

@require_project
@handle_errors("deploy run")
def deploy(self, args) -> int:
    # Check config exists
    config_file = Path(f"configs/{args.target}.yaml")
    if not config_file.exists():
        raise ConfigurationError(
            f"Config file not found: {config_file}\n"
            f"Create one with: ./templedb deploy init {args.target}"
        )

    # Run deployment
    try:
        subprocess.run(['./deploy.sh', args.target], check=True)
    except subprocess.CalledProcessError as e:
        raise DeploymentError(
            f"Deployment failed with exit code {e.returncode}\n"
            f"Check deployment logs for details"
        )

    print_success("Deployment completed")
    return 0
```

**Benefit:** 31 lines → 25 lines, specific exception types, better error messages

## Step-by-Step Migration Process

### Step 1: Analyze Current Error Handling

Review your command file and identify:
1. try-except blocks
2. Input validation
3. Resource lookups
4. Print statements for errors
5. Manual logging

### Step 2: Add Imports

Add the error handling utilities import at the top:

```python
from cli.error_handling_utils import (
    handle_errors,
    ValidationError,
    ResourceNotFoundError,
    print_success,
    print_warning
)
```

### Step 3: Apply @handle_errors Decorator

Add the decorator to each command method:

```python
@handle_errors("command name")
def command_method(self, args) -> int:
    # ...
```

### Step 4: Replace Print Statements

Replace all error/success prints:

```python
# Before
print("✅ Success!")
print(f"❌ Error: {msg}")
print(f"⚠️  Warning: {msg}")

# After
print_success("Operation completed")
raise ValidationError(msg)  # Will be caught by @handle_errors
print_warning(msg)
```

### Step 5: Convert Validation to Exceptions

Replace return statements with exceptions:

```python
# Before
if not args.slug:
    print("❌ Error: Slug required")
    logger.error("Missing slug")
    return 1

# After
if not args.slug:
    raise ValidationError("Slug is required")
```

### Step 6: Use Decorator Utilities

Add decorators for common patterns:

```python
# Before
def command(self, args) -> int:
    project = self.query_one(...)
    if not project:
        print("Error: not found")
        return 1
    # ...

# After
@require_project
def command(self, args) -> int:
    # Project guaranteed to exist
    project = self.query_one(...)
    # ...
```

### Step 7: Test

Run the command with:
- Valid input (should succeed)
- Invalid input (should show helpful error)
- Missing resources (should show helpful error)
- Debug mode: `TEMPLEDB_LOG_LEVEL=DEBUG ./templedb command`

## Common Mistakes to Avoid

### 1. Don't Catch Exceptions Inside @handle_errors

**Bad:**
```python
@handle_errors("command")
def command(self, args) -> int:
    try:
        # work
    except Exception as e:  # Defeats purpose of decorator!
        logger.error(f"Error: {e}")
        return 1
```

**Good:**
```python
@handle_errors("command")
def command(self, args) -> int:
    # work (exceptions will be caught by decorator)
    return 0
```

### 2. Don't Mix print() and raise

**Bad:**
```python
if error:
    print("❌ Error: something wrong")  # User sees this
    raise ValidationError("something wrong")  # Also creates error message
```

**Good:**
```python
if error:
    raise ValidationError("Something wrong")  # Single, clear message
```

### 3. Don't Use Generic Exceptions

**Bad:**
```python
if not config:
    raise Exception("Config not found")  # Generic
```

**Good:**
```python
if not config:
    raise ConfigurationError(
        f"Config file not found: {config_path}\n"
        f"Create one with: ./templedb config init"
    )
```

### 4. Don't Forget return 0

**Bad:**
```python
@handle_errors("command")
def command(self, args) -> int:
    # work
    print_success("Done")
    # Missing return 0!
```

**Good:**
```python
@handle_errors("command")
def command(self, args) -> int:
    # work
    print_success("Done")
    return 0
```

## Testing Your Migration

### Manual Testing

```bash
# Test with valid input
./templedb command valid-input
# Should: succeed with success message

# Test with invalid input
./templedb command ''
# Should: show validation error with helpful message

# Test with missing resource
./templedb command nonexistent
# Should: show resource not found error

# Test in debug mode
TEMPLEDB_LOG_LEVEL=DEBUG ./templedb command failing-input
# Should: show full traceback and detailed logs
```

### Check Exit Codes

```bash
# Success case
./templedb command valid-input
echo $?  # Should be 0

# Error case
./templedb command invalid-input
echo $?  # Should be 1

# Application error case (if bug exists)
./templedb command triggers-bug
echo $?  # Should be 2
```

## Migration Checklist

For each command file:

- [ ] Added error handling utility imports
- [ ] Applied @handle_errors decorator to all command methods
- [ ] Replaced print() error messages with exceptions
- [ ] Replaced manual validation with decorators where possible
- [ ] Used specific exception types (ValidationError, ResourceNotFoundError, etc.)
- [ ] Replaced print() success messages with print_success()
- [ ] Added helpful context to all error messages
- [ ] Removed manual try-except blocks (let decorator handle it)
- [ ] All commands return 0 on success
- [ ] Tested with valid and invalid inputs
- [ ] Tested in debug mode
- [ ] Verified exit codes are correct

## Priority Order for Migration

Based on usage frequency and complexity:

**High Priority (most used commands):**
1. `project.py` - ✅ Already uses ErrorHandler
2. `vcs.py` - ✅ Already uses ErrorHandler
3. `blob.py` - Common, high error potential
4. `secret.py` - Security-critical, many validations
5. `key.py` - Security-critical, complex workflows

**Medium Priority:**
6. `backup.py` - Important but less frequent
7. `deploy.py` - ✅ Already uses ErrorHandler
8. `search.py` - Common lookups
9. `config.py` - Config management
10. `domain.py` - DNS operations

**Low Priority (less common):**
11. `cathedral.py` - Package management
12. `migration.py` - Database migrations
13. `nixos.py` - System deployments
14. `mcp.py` - Server operations
15. Other utility commands

## Getting Help

If you run into issues during migration:

1. Check existing migrated commands for examples:
   - `src/cli/commands/project.py`
   - `src/cli/commands/vcs.py`
   - `src/cli/commands/deploy.py`

2. Review the error handler source:
   - `src/error_handler.py`
   - `src/cli/error_handling_utils.py`

3. Check the documentation:
   - `docs/ERROR_HANDLING.md` - General guidelines
   - This document - Migration patterns

4. Test incrementally:
   - Migrate one method at a time
   - Test after each change
   - Commit working versions

## Summary

**What Changed:**
- Old: Manual try-except blocks everywhere
- New: @handle_errors decorator + raise exceptions

**Benefits:**
- ✅ 30-50% less code
- ✅ Consistent error messages
- ✅ Automatic logging
- ✅ Better error context
- ✅ Easier to maintain
- ✅ Better user experience

**Key Principles:**
1. Use decorators for common patterns
2. Raise specific exception types
3. Provide helpful error messages with context and solutions
4. Let the framework handle error formatting
5. Test with both valid and invalid inputs
