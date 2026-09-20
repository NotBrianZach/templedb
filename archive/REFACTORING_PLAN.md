# TempleDB Refactoring Plan

**Date**: 2026-02-22
**Goal**: Improve code organization, reduce duplication, increase maintainability

---

## Current Issues Identified

### 1. Configuration Duplication
**Issue**: DB_PATH defined in 3 separate Python files
```python
# Appears in:
- src/llm_context.py:14
- src/nix_env_generator.py:14
- src/templedb_tui.py:31
```

**Impact**: Changes to database path require updates in multiple files

**Solution**: Create `src/config.py` with shared configuration

---

### 2. Database Connection Management
**Issue**: 34 direct `sqlite3.connect()` calls throughout codebase
- No connection pooling
- No automatic cleanup
- Repeated boilerplate
- No transaction management helper

**Impact**:
- Risk of connection leaks
- Verbose code
- Hard to add connection-level features (logging, profiling)

**Solution**: Create database context manager and helper functions

---

### 3. Migration Organization
**Issue**: Migrations scattered across multiple files
```
- migrations/007_add_nix_environments.sql
- database_vcs_schema.sql
- file_tracking_schema.sql
- file_versioning_schema.sql
- views.sql
```

**Impact**:
- Hard to track what migrations have been applied
- No version tracking
- Manual application

**Solution**:
- Consolidate all migrations in `migrations/` directory
- Create migration runner with version tracking
- Number all migrations sequentially

---

### 4. Shell Script Duplication
**Issue**: Common patterns repeated across shell scripts
- Color definitions
- Error handling
- Database path resolution

**Impact**: Updates need to be made in multiple places

**Solution**: Create `scripts/lib/common.sh` with shared functions

---

### 5. Python Module Organization
**Issue**: All Python code in `src/` without clear structure
```
src/
  ├── main.py (legacy?)
  ├── llm_context.py
  ├── nix_env_generator.py
  └── templedb_tui.py
```

**Impact**: Unclear what `main.py` does, no clear module boundaries

**Solution**: Organize into proper package structure

---

## Proposed Refactoring

### Phase 1: Configuration & Database Layer

**1.1 Create `src/config.py`**
```python
"""TempleDB Configuration - Single Source of Truth"""
import os
from pathlib import Path

# Database
DB_PATH = os.environ.get(
    'TEMPLEDB_PATH',
    os.path.expanduser("~/.local/share/templedb/templedb.sqlite")
)
DB_DIR = os.path.dirname(DB_PATH)

# Directories
NIX_ENV_DIR = os.path.join(DB_DIR, "nix-envs")
MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

# Editor
EDITOR = os.environ.get('EDITOR', 'vim')

# Defaults
DEFAULT_BRANCH = 'master'
```

**1.2 Create `src/db.py`**
```python
"""Database Connection Management"""
import sqlite3
from contextlib import contextmanager
from typing import Optional, List, Dict, Any
from .config import DB_PATH

class Database:
    """Database connection manager"""

    @staticmethod
    @contextmanager
    def connect(row_factory=True):
        """Context manager for database connections"""
        conn = sqlite3.connect(DB_PATH)
        if row_factory:
            conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def query(sql: str, params: tuple = (), row_factory=True) -> List[Dict]:
        """Execute query and return results"""
        with Database.connect(row_factory) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def execute(sql: str, params: tuple = ()):
        """Execute statement (INSERT, UPDATE, DELETE)"""
        with Database.connect(False) as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            return cursor.lastrowid
```

---

### Phase 2: Module Organization

**2.1 Restructure to Package**
```
src/templedb/
  ├── __init__.py
  ├── config.py           # Configuration
  ├── db.py              # Database layer
  ├── cli/
  │   ├── __init__.py
  │   ├── main.py        # CLI entry point
  │   ├── llm.py         # LLM context commands
  │   └── nix.py         # Nix environment commands
  ├── tui/
  │   ├── __init__.py
  │   ├── app.py         # Main TUI app
  │   ├── screens/
  │   │   ├── __init__.py
  │   │   ├── projects.py
  │   │   ├── files.py
  │   │   ├── vcs.py
  │   │   ├── deployments.py
  │   │   ├── environments.py
  │   │   ├── llm.py
  │   │   ├── sql_objects.py
  │   │   └── statistics.py
  │   └── widgets/
  │       └── __init__.py
  ├── models/
  │   ├── __init__.py
  │   ├── project.py
  │   ├── file.py
  │   ├── environment.py
  │   └── vcs.py
  └── migrations/
      ├── __init__.py
      └── runner.py
```

**2.2 Split TUI into Separate Screen Files**
Currently `templedb_tui.py` is 1810 lines - split into:
- `tui/app.py` - Main app class and entry point (100 lines)
- `tui/screens/projects.py` - ProjectsScreen (150 lines)
- `tui/screens/files.py` - FilesScreen (500 lines)
- `tui/screens/vcs.py` - VCSScreen (170 lines)
- `tui/screens/deployments.py` - DeploymentScreen (150 lines)
- `tui/screens/environments.py` - EnvironmentsScreen (240 lines)
- `tui/screens/llm.py` - LLMContextScreen (130 lines)
- `tui/screens/sql_objects.py` - SQLObjectsScreen (140 lines)
- `tui/screens/statistics.py` - StatisticsScreen (130 lines)

---

### Phase 3: Migration System

**3.1 Consolidate Migrations**
```
migrations/
  ├── 001_initial_schema.sql
  ├── 002_file_tracking.sql
  ├── 003_file_versioning.sql
  ├── 004_vcs_schema.sql
  ├── 005_views.sql
  ├── 006_deployment_targets.sql
  ├── 007_nix_environments.sql
  └── versions.txt  # Track applied migrations
```

**3.2 Create Migration Runner**
```python
# src/templedb/migrations/runner.py
class MigrationRunner:
    def get_current_version(self) -> int
    def get_pending_migrations(self) -> List[str]
    def apply_migration(self, file: str) -> None
    def migrate_up(self, target: Optional[int] = None) -> None
    def migrate_down(self, target: int) -> None
```

---

### Phase 4: Shell Script Library

**4.1 Create `scripts/lib/common.sh`**
```bash
#!/usr/bin/env bash
# Common shell functions for TempleDB

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# Paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DB_PATH="${TEMPLEDB_PATH:-$HOME/.local/share/templedb/templedb.sqlite}"

# Functions
log_info() { echo -e "${CYAN}$1${NC}"; }
log_success() { echo -e "${GREEN}✓ $1${NC}"; }
log_error() { echo -e "${RED}✗ $1${NC}" >&2; }
log_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }

check_db() {
    if [[ ! -f "$DB_PATH" ]]; then
        log_error "Database not found: $DB_PATH"
        exit 1
    fi
}

run_sql() {
    sqlite3 "$DB_PATH" "$1"
}
```

**4.2 Update Scripts to Use Library**
```bash
#!/usr/bin/env bash
source "$(dirname "$0")/scripts/lib/common.sh"

check_db
log_info "Running operation..."
# ... rest of script
```

---

### Phase 5: Model Layer

**5.1 Create Domain Models**
```python
# src/templedb/models/project.py
class Project:
    def __init__(self, id, slug, name, ...):
        self.id = id
        self.slug = slug
        ...

    @classmethod
    def find(cls, slug: str) -> Optional['Project']:
        """Find project by slug"""

    @classmethod
    def all(cls) -> List['Project']:
        """Get all projects"""

    def save(self) -> None:
        """Save project to database"""

    def files(self) -> List['File']:
        """Get project files"""
```

---

## Benefits of Refactoring

### Code Quality
- **DRY**: Eliminate duplication
- **Separation of Concerns**: Clear module boundaries
- **Testability**: Easier to unit test
- **Maintainability**: Changes in one place

### Performance
- **Connection Pooling**: Reuse connections
- **Transaction Management**: Automatic rollback on error
- **Resource Cleanup**: Context managers ensure cleanup

### Developer Experience
- **Clear Structure**: Easy to find code
- **Shared Configuration**: Single source of truth
- **Migration System**: Safe database upgrades
- **Better Errors**: Centralized error handling

---

## Implementation Priority

### High Priority (Do First)
1. **Configuration Module** - Eliminates duplication immediately
2. **Database Context Manager** - Improves reliability
3. **Migration Consolidation** - Critical for upgrades

### Medium Priority
4. **Shell Script Library** - Reduces duplication
5. **TUI Screen Separation** - Improves maintainability

### Low Priority (Optional)
6. **Package Restructure** - Large change, benefits long-term
7. **Model Layer** - Nice to have, but adds complexity

---

## Backward Compatibility

**Critical**: Maintain backward compatibility during refactoring
- Existing database format unchanged
- CLI interface unchanged
- TUI interface unchanged
- Only internal reorganization

**Strategy**:
- Create new modules alongside old
- Gradually migrate code
- Remove old code once validated
- Keep extensive tests

---

## Testing Strategy

1. **Before Refactoring**: Document current behavior
2. **During Refactoring**:
   - Test each change independently
   - Run TUI and verify all screens work
   - Test CLI commands
3. **After Refactoring**:
   - Full integration test
   - Compare behavior with pre-refactoring

---

## Next Steps

1. Create `src/config.py` ✓ (Quick win)
2. Create `src/db.py` ✓ (High impact)
3. Update all Python files to use shared config
4. Test thoroughly
5. Continue with remaining phases

---

*"Simplicity is prerequisite for reliability."* - Edsger W. Dijkstra

**TempleDB Refactoring - Making the temple more beautiful**
