# Phase 2: Transaction Usage Plan

**Goal**: Wrap all multi-step operations in ACID transactions

---

## Critical Transaction Boundaries Identified

### 1. **Project Import** (`src/importer/__init__.py:import_files()`)

**Current Problem**:
```python
def import_files(self):
    self._import_file_metadata(files)      # executemany() - auto-commits
    self._store_file_contents()            # execute() loop - each auto-commits
    self._analyze_sql_files(sql_files)     # execute() calls - auto-commit
    self._analyze_dependencies(files)       # execute() calls - auto-commit
    self._populate_file_metadata(files)     # execute() calls - auto-commit
```

**Impact**: If step 3 fails, steps 1-2 are already committed. Database left inconsistent.

**Solution**:
```python
def import_files(self):
    with transaction():  # Entire import is atomic
        self._import_file_metadata(files)
        self._store_file_contents()
        self._analyze_sql_files(sql_files)
        self._analyze_dependencies(files)
        self._populate_file_metadata(files)
```

---

### 2. **VCS Operations** (`src/cli/commands/vcs.py`)

Need to check VCS commit operations - likely multi-step without transactions.

---

### 3. **Cathedral Import/Export** (`src/cathedral_import.py`, `src/cathedral_export.py`)

Likely has multi-step operations for importing/exporting projects.

---

### 4. **Content Migration** (`src/complete_migration.py`)

Already has transaction in one place, but should verify all operations wrapped.

---

## Implementation Strategy

### Step 1: Update db_utils.py

Ensure transaction() context manager works correctly:

```python
@contextmanager
def transaction():
    """Context manager for database transactions"""
    conn = get_connection()
    try:
        # Disable autocommit (SQLite doesn't have explicit mode, but we control commits)
        yield conn
        conn.commit()  # Commit on success
    except Exception:
        conn.rollback()  # Rollback on failure
        raise  # Re-raise exception
```

### Step 2: Update execute() and executemany()

**Current Problem**: They auto-commit immediately!

```python
def execute(sql: str, params: tuple = ()) -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    conn.commit()  # ← This auto-commits!
    return cursor.lastrowid
```

**Solution**: Remove auto-commit, rely on transaction() or explicit commit:

```python
def execute(sql: str, params: tuple = (), commit: bool = True) -> int:
    """Execute statement

    Args:
        sql: SQL statement
        params: Parameters
        commit: Whether to auto-commit (default True for backward compat)
                Set to False when using transaction() context manager
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(sql, params)
    if commit:
        conn.commit()
    return cursor.lastrowid
```

### Step 3: Wrap Critical Operations

Update each file:

#### `src/importer/__init__.py`

```python
from db_utils import transaction  # Add import

def import_files(self) -> ImportStats:
    # ... setup code ...

    with transaction():  # ← Wrap entire import
        # Step 2: Import file metadata
        print("\n💾 Importing file metadata...")
        self._import_file_metadata(scanned_files)

        # Step 3: Store file contents
        print("\n📄 Storing file contents...")
        self._store_file_contents()

        # Step 4: Analyze SQL files
        print("\n🔬 Analyzing SQL files...")
        self._analyze_sql_files(sql_files)

        # Step 5: Analyze dependencies
        print("\n🔗 Analyzing dependencies...")
        self._analyze_dependencies(scanned_files)

        # Step 6: Populate metadata
        print("\n📋 Populating file metadata...")
        self._populate_file_metadata(scanned_files)

    # If we get here, transaction committed successfully
    print("✅ Import complete!")
    return self.stats
```

#### Helper methods don't need transactions (they're inside parent transaction)

```python
def _import_file_metadata(self, files):
    # No transaction here - parent provides it
    executemany("""INSERT OR REPLACE ...""", records, commit=False)

def _store_file_contents(self):
    for file in files:
        execute("""INSERT OR REPLACE ...""", params, commit=False)
```

---

## Testing Strategy

### Test 1: Rollback on Failure

```python
def test_import_rollback():
    """Test that failed import rolls back all changes"""

    # Count before
    before_count = query_one("SELECT COUNT(*) FROM project_files WHERE project_id = ?", (project_id,))['COUNT(*)']

    # Try import that will fail (inject error in step 3)
    try:
        importer.import_files()  # Will fail at step 3
    except Exception:
        pass

    # Count after - should be same as before (rollback worked)
    after_count = query_one("SELECT COUNT(*) FROM project_files WHERE project_id = ?", (project_id,))['COUNT(*)']

    assert after_count == before_count, "Rollback failed! Partial import persisted"
```

### Test 2: Atomic Commit

```python
def test_import_atomic():
    """Test that successful import commits all changes"""

    before_files = query_one("SELECT COUNT(*) FROM project_files WHERE project_id = ?", (project_id,))['COUNT(*)']
    before_content = query_one("SELECT COUNT(*) FROM file_contents")['COUNT(*)']

    # Import
    stats = importer.import_files()

    # Verify all or nothing
    after_files = query_one("SELECT COUNT(*) FROM project_files WHERE project_id = ?", (project_id,))['COUNT(*)']
    after_content = query_one("SELECT COUNT(*) FROM file_contents")['COUNT(*)']

    assert after_files == before_files + stats.files_imported
    assert after_content == before_content + stats.content_stored
```

### Test 3: Concurrent Operations

```python
def test_concurrent_imports():
    """Test that concurrent imports don't conflict"""
    import threading

    errors = []

    def import_project(slug):
        try:
            importer = ProjectImporter(slug, f"/path/to/{slug}")
            importer.import_files()
        except Exception as e:
            errors.append(e)

    # Run two imports concurrently
    t1 = threading.Thread(target=import_project, args=("project1",))
    t2 = threading.Thread(target=import_project, args=("project2",))

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Both should succeed
    assert len(errors) == 0, f"Concurrent imports failed: {errors}"
```

---

## Rollout Plan

### Phase 2.1: Infrastructure (Day 1)
- ✅ Update `db_utils.py` transaction() context manager
- ✅ Add `commit` parameter to execute() and executemany()
- ✅ Test transaction rollback works

### Phase 2.2: Critical Operations (Day 2-3)
- ✅ Wrap `ProjectImporter.import_files()` in transaction
- ✅ Update all execute() calls in importer to use commit=False
- ✅ Test import rollback on failure

### Phase 2.3: VCS Operations (Day 4)
- ✅ Wrap VCS commit operations in transactions
- ✅ Test VCS rollback

### Phase 2.4: Cathedral Operations (Day 5)
- ✅ Wrap cathedral import/export in transactions
- ✅ Test cathedral rollback

### Phase 2.5: Testing & Validation (Day 6-7)
- ✅ Write rollback tests
- ✅ Write atomic commit tests
- ✅ Write concurrent operation tests
- ✅ Document transaction boundaries

---

## Success Criteria

After Phase 2:
- ✅ All multi-step operations wrapped in transactions
- ✅ No auto-commits in critical code paths
- ✅ Rollback works correctly on failures
- ✅ Tests verify atomicity
- ✅ Documentation explains transaction boundaries

---

## Files to Modify

1. `src/db_utils.py` - Update transaction(), execute(), executemany()
2. `src/importer/__init__.py` - Wrap import_files() in transaction
3. `src/cli/commands/vcs.py` - Wrap VCS operations
4. `src/cathedral_import.py` - Wrap import operations
5. `src/cathedral_export.py` - Verify export operations
6. `tests/test_transactions.py` - NEW: Add transaction tests

---

## Next Steps

1. Start with `db_utils.py` infrastructure
2. Apply to `importer/__init__.py` (highest impact)
3. Test thoroughly before proceeding
4. Roll out to other modules
5. Add comprehensive tests

Ready to begin implementation!
