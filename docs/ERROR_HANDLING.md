# Error Handling Guidelines

This document describes the error handling standards and best practices for TempleDB.

## Overview

TempleDB uses a centralized error handling system to provide consistent, user-friendly error messages across all CLI commands. The system is designed to:

1. **Catch errors early** - Validate inputs before operations
2. **Provide context** - Explain what went wrong and why
3. **Suggest solutions** - Give users actionable next steps
4. **Log appropriately** - Use structured logging for debugging
5. **Never fail silently** - Always log non-critical errors

## Architecture

### Error Handler Module

Location: `src/error_handler.py`

The centralized error handler provides:
- Custom exception hierarchy for different error types
- User-friendly error message formatting
- Automatic error-to-exit-code mapping
- Database error translation

### Exception Hierarchy

```python
TempleDBError               # Base application error
├── ValidationError         # Input validation failures
├── ResourceNotFoundError   # Missing resources (projects, files, etc.)
├── ConfigurationError      # Invalid or missing configuration
├── DeploymentError         # Deployment operation failures
└── DatabaseError           # Database operation failures
```

### Exit Codes

- `0` - Success
- `1` - Expected error (user error, missing resource, validation failure)
- `2` - Unexpected error (application bug, system issue)

## Guidelines for Command Development

### 1. Use Logger, Not Print

**Bad:**
```python
print(f"Error: File not found", file=sys.stderr)
```

**Good:**
```python
logger.error("File not found: {file_path}")
logger.info("Use: templedb vcs status <project> to see available files")
```

**Why:** Logger provides:
- Consistent formatting with timestamps and severity levels
- Color-coded output (red for errors, yellow for warnings)
- Configurable via `TEMPLEDB_LOG_LEVEL` environment variable
- Can be redirected to files for debugging
- Supports debug mode with full tracebacks

### 2. Validate Inputs Early

**Bad:**
```python
def add_project(slug: str, name: str):
    conn.execute("INSERT INTO projects(...) VALUES (...)")  # Fails on constraint
```

**Good:**
```python
def add_project(slug: str, name: str):
    if not slug or not slug.strip():
        raise ValidationError("Project slug is required")

    existing = db_utils.query_one("SELECT id FROM projects WHERE slug = ?", (slug,))
    if existing:
        raise ValidationError(f"Project '{slug}' already exists")

    # Now insert...
```

### 3. Provide Error Context and Solutions

**Bad:**
```python
logger.error("Branch not found")
```

**Good:**
```python
logger.error(f"Branch '{branch_name}' not found in project '{project_slug}'")
logger.info(f"Available branches: {', '.join(available_branches)}")
logger.info("Use: templedb vcs branch <project> <name> to create a new branch")
```

### 4. Use Error Handler for Exception Translation

**Bad:**
```python
try:
    # ... operation
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
    return 1
```

**Good:**
```python
from error_handler import ErrorHandler

try:
    # ... operation
except Exception as e:
    return ErrorHandler.handle_command_error(
        e,
        command="project show",
        context={"slug": project_slug}
    )
```

### 5. Never Fail Silently

**Bad:**
```python
try:
    audit_log(action, details)
except Exception:
    pass  # Silent failure!
```

**Good:**
```python
from error_handler import ErrorHandler

try:
    audit_log(action, details)
except Exception as e:
    ErrorHandler.log_non_critical_error("Audit logging", e)
```

### 6. Catch Specific Exceptions

**Bad:**
```python
try:
    conn.execute(sql)
except Exception as e:  # Too broad
    logger.error(f"Error: {e}")
```

**Good:**
```python
try:
    conn.execute(sql)
except sqlite3.IntegrityError as e:
    logger.error(f"Duplicate entry: {e}")
    logger.info("This record already exists")
except sqlite3.OperationalError as e:
    logger.error(f"Database error: {e}")
    logger.info("Check database file permissions")
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    logger.debug("Full traceback:", exc_info=True)
```

### 7. Use Debug Logging for Tracebacks

**Bad:**
```python
import traceback
traceback.print_exc()  # Always shows, clutters output
```

**Good:**
```python
logger.error(f"Operation failed: {e}")
logger.debug("Full traceback:", exc_info=True)  # Only shown in debug mode
```

Users can enable debug mode:
```bash
TEMPLEDB_LOG_LEVEL=DEBUG templedb <command>
```

## Error Message Template

Use this format for error messages:

```python
from error_handler import ErrorHandler

message = ErrorHandler.format_error(
    problem="What went wrong",
    context="Additional context about the situation",
    solution="How to fix it"
)
logger.error(message)
```

Example output:
```
Error: Project slug 'myapp' already exists
  Context: Found existing project with ID 42
  Fix: Use 'templedb project list' to see existing projects
```

## Common Error Patterns

### Database Errors

```python
# The db_utils module automatically logs database errors with context
# Just catch and provide user-friendly message

from error_handler import DatabaseError

try:
    result = db_utils.query_one("SELECT * FROM projects WHERE slug = ?", (slug,))
except sqlite3.OperationalError as e:
    if "no such table" in str(e).lower():
        logger.error("Database not initialized")
        logger.info("Run: templedb init")
    else:
        raise DatabaseError(f"Database error: {e}")
```

### File Not Found

```python
from error_handler import ResourceNotFoundError

file_path = Path(args.path)
if not file_path.exists():
    logger.error(f"File not found: {file_path}")
    logger.info("Check that the path is correct")
    raise ResourceNotFoundError(f"File not found: {file_path}")
```

### Missing Configuration

```python
from error_handler import ConfigurationError

config_value = os.environ.get("REQUIRED_VAR")
if not config_value:
    logger.error("Missing required environment variable: REQUIRED_VAR")
    logger.info("Set it with: export REQUIRED_VAR=value")
    raise ConfigurationError("Missing REQUIRED_VAR")
```

### Validation Failures

```python
from error_handler import ValidationError

if not slug or not slug.strip():
    raise ValidationError("Project slug is required and cannot be empty")

if not slug.replace('-', '').replace('_', '').isalnum():
    raise ValidationError(
        "Project slug must contain only letters, numbers, hyphens, and underscores"
    )
```

## Testing Error Handling

When testing commands, verify:

1. **Error messages are helpful** - Include context and solutions
2. **Exit codes are correct** - 0 for success, 1 for user errors, 2 for bugs
3. **Logging works** - Errors appear in logs with appropriate severity
4. **No silent failures** - All errors are logged or reported
5. **Debug mode works** - Tracebacks appear with `TEMPLEDB_LOG_LEVEL=DEBUG`

### Manual Testing

```bash
# Test with invalid input
templedb project show nonexistent
# Should show: Error with suggestion to list projects

# Test with missing file
templedb vcs diff myproject --file missing.py
# Should show: Error with suggestion to run status

# Test with debug mode
TEMPLEDB_LOG_LEVEL=DEBUG templedb <failing-command>
# Should show: Full traceback and detailed logs
```

## Migration Guide

If you're updating existing code, follow these steps:

### Step 1: Add Logger Import

```python
from logger import get_logger
logger = get_logger(__name__)
```

### Step 2: Replace Print Statements

```python
# Before
print(f"Error: {msg}", file=sys.stderr)

# After
logger.error(msg)
logger.info("How to fix it...")
```

### Step 3: Add Error Context

```python
# Before
logger.error("File not found")

# After
logger.error(f"File not found: {file_path}")
logger.info(f"Use: templedb vcs status {project} to see available files")
```

### Step 4: Fix Silent Failures

```python
# Before
except Exception:
    pass

# After
except Exception as e:
    ErrorHandler.log_non_critical_error("Operation name", e)
```

## Performance Considerations

- **Validate early** - Fail fast before expensive operations
- **Use debug logging** - Don't compute expensive debug info unless DEBUG level is enabled:
  ```python
  if logger.isEnabledFor(logging.DEBUG):
      logger.debug(f"Expensive computation: {expensive_function()}")
  ```
- **Batch validation** - Validate all inputs at once rather than one at a time
- **Cache error messages** - Don't repeatedly query for error context

## References

- Error Handler: `src/error_handler.py`
- Logger Configuration: `src/logger.py`
- Database Utilities: `src/db_utils.py`
- Example Commands: `src/cli/commands/vcs.py`, `src/cli/commands/project.py`

## Questions?

For questions or suggestions about error handling:
- Open an issue: https://github.com/anthropics/templedb/issues
- Check existing error handling patterns in `src/cli/commands/`
