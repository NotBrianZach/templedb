# Logging Migration Guide

## Overview

This guide documents the migration from `print()` calls to Python's `logging` module across the TempleDB codebase.

**Status:** In Progress
**Total print() calls:** 766 across 26 files

## Migration Patterns

### 1. User-Facing Success Messages
```python
# OLD
print("ok")
print(f"✓ Created project '{slug}'")

# NEW
logger.info("Operation completed successfully")
logger.info(f"Created project '{slug}'")
```

### 2. Error Messages
```python
# OLD
print(f"Error: {msg}", file=sys.stderr)
print(f"error: {e}", file=sys.stderr)

# NEW
logger.error(f"Error: {msg}")
logger.error(f"{e}")
```

### 3. Warning Messages
```python
# OLD
print(f"⚠️  Warning: {issue}")
print(f"# Warning: {msg}", file=sys.stderr)

# NEW
logger.warning(f"Warning: {issue}")
logger.warning(msg)
```

### 4. Debug/Diagnostic Messages
```python
# OLD
print(f"Debug: value={value}")
print(f"# Detected git branch: {branch}", file=sys.stderr)

# NEW
logger.debug(f"value={value}")
logger.debug(f"Detected git branch: {branch}")
```

### 5. Data Output (Keep print for now)
```python
# Keep print() for structured data output to stdout
# These are intentional output, not logging
print(json.dumps(data, indent=2))
sys.stdout.write(content)
```

### 6. Progress/Status Messages
```python
# OLD
print(f"Processing file {i}/{total}...")
print("Importing project...")

# NEW
logger.info(f"Processing file {i}/{total}")
logger.info("Importing project")
```

## Migration Strategy

### Phase 1: Core Infrastructure ✅
- [x] Create `src/logger.py` with logging setup
- [x] Update `src/config.py` to initialize logging

### Phase 2: Module-by-Module Conversion

#### High Priority Modules (Start Here)
1. `src/cli/commands/project.py` - Project management
2. `src/cli/commands/commit.py` - Commit operations
3. `src/cli/commands/checkout.py` - Checkout operations
4. `src/importer/__init__.py` - Import logic
5. `src/cli/core.py` - Core CLI functionality

#### Medium Priority Modules
6. `src/cli/commands/vcs.py` - VCS operations
7. `src/cli/commands/env.py` - Environment management
8. `src/cli/commands/secret.py` - Secret management
9. `src/cli/commands/deploy.py` - Deployment
10. `src/deployment_orchestrator.py` - Orchestration

#### Low Priority Modules
11. `src/cli/commands/cathedral.py`
12. `src/cli/commands/migration.py`
13. `src/cli/commands/search.py`
14. `src/cli/commands/target.py`
15. `src/cli/commands/system.py`
16. Other utility scripts

### Phase 3: Testing & Documentation
- Test all log levels (DEBUG, INFO, WARNING, ERROR)
- Verify no regression in CLI output
- Document logging conventions
- Add examples to README

## Logging Levels

Use these guidelines for choosing log levels:

| Level | When to Use | Examples |
|-------|-------------|----------|
| **DEBUG** | Detailed diagnostic info | Variable values, function entry/exit, DB queries |
| **INFO** | Normal operational messages | "Project created", "File imported", progress updates |
| **WARNING** | Unexpected but recoverable issues | Missing optional config, deprecated features |
| **ERROR** | Error conditions that fail operations | File not found, DB constraint violations |
| **CRITICAL** | System-wide failures | DB corruption, out of disk space |

## Import Pattern

Add to top of each Python file:

```python
from src.logger import get_logger

logger = get_logger(__name__)
```

## Special Cases

### 1. Main.py Command Output
The `main.py` file contains many `print()` calls for direct user output (JSON, YAML, shell scripts). These should remain as `print()` since they're intentional output, not logging.

**Keep as print():**
- JSON output: `print(json.dumps(...))`
- YAML output: `sys.stdout.write(yaml.safe_dump(...))`
- Shell export: `print(f"export VAR={value}")`
- Data retrieval: `sys.stdout.write(row["nix_text"])`

**Convert to logging:**
- Success messages: `print("ok")` → `logger.info("Operation completed")`
- Error messages: `print(f"error: {e}", file=sys.stderr)` → `logger.error(f"{e}")`
- Status messages: `print(f"Added project: {slug}")` → `logger.info(f"Added project: {slug}")`

### 2. CLI Commands with Table Output
CLI commands that format and print tables should keep `print()` for the table itself, but use logging for status messages.

### 3. TUI/Interactive Components
TUI components should use logging for diagnostics but keep their own output mechanisms for UI rendering.

## Environment Variables

Users can control logging behavior:

```bash
# Set log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
export TEMPLEDB_LOG_LEVEL=DEBUG

# Enable file logging
export TEMPLEDB_LOG_TO_FILE=true

# Log file location (default: ~/.local/share/templedb/templedb.log)
# Controlled by config.py
```

## Testing

Test each module after migration:

```bash
# Test normal operation
./templedb project list

# Test with DEBUG logging
TEMPLEDB_LOG_LEVEL=DEBUG ./templedb project list

# Test with file logging
TEMPLEDB_LOG_TO_FILE=true ./templedb project list
tail -f ~/.local/share/templedb/templedb.log
```

## Progress Tracking

| Module | Status | Print Count | Notes |
|--------|--------|-------------|-------|
| src/logger.py | ✅ Created | 5 | Infrastructure |
| src/config.py | ✅ Updated | 0 | Logging init |
| src/cli/commands/project.py | 🔄 Next | 35 | High priority |
| src/cli/commands/commit.py | ⏳ Pending | 41 | High priority |
| src/cli/commands/checkout.py | ⏳ Pending | 34 | High priority |
| src/importer/__init__.py | ⏳ Pending | 41 | High priority |
| ... | ... | ... | ... |

**Legend:**
- ✅ Complete
- 🔄 In Progress
- ⏳ Pending
- ❌ Blocked

## Rollback Plan

If issues arise:
1. Git revert the logging changes
2. The logging infrastructure is additive and won't break existing code
3. Partially migrated modules will work (mix of print() and logging is fine temporarily)

## Success Criteria

Migration is complete when:
1. All 766 print() calls reviewed and categorized
2. Non-output print() calls converted to logging
3. All modules tested with different log levels
4. Documentation updated
5. CI/CD updated to capture logs
6. No regression in user-facing behavior
