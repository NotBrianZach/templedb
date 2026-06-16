# TempleDB Test Suite

Unified pytest-based test suite for TempleDB.

## Quick Start

```bash
# Run all tests
./run_tests.sh

# Run with verbose output
./run_tests.sh -v

# Run specific test file
./run_tests.sh tests/test_workflow.py

# Run specific test
./run_tests.sh -k test_checkout_edit_commit_workflow

# Run tests by marker
./run_tests.sh -m unit          # Only unit tests
./run_tests.sh -m integration   # Only integration tests
./run_tests.sh -m workflow      # Only workflow tests
./run_tests.sh -m concurrent    # Only concurrency tests
./run_tests.sh -m constraints   # Only constraint tests
```

## Test Structure

```
tests/
├── conftest.py              # Shared fixtures and utilities
├── test_workflow.py         # Checkout → Edit → Commit workflow tests
├── test_concurrent.py       # Multi-agent locking and conflict detection
├── test_snapshot.py         # Snapshot update and false conflict prevention
├── test_transactions.py     # Transaction rollback and atomicity
├── test_constraints.py      # Database constraint validation
└── README.md               # This file
```

## Test Categories

### Unit Tests (`-m unit`)
- Test individual components in isolation
- Fast execution
- No database modifications that persist

### Integration Tests (`-m integration`)
- Test complete workflows end-to-end
- May modify database (cleaned up after)
- Test interactions between components

### Workflow Tests (`-m workflow`)
- Test checkout/commit workflows
- Verify round-trip integrity
- Test sequential operations

### Concurrent Tests (`-m concurrent`)
- Test multi-agent scenarios
- Conflict detection
- Version control

### Constraint Tests (`-m constraints`)
- Database constraint enforcement
- Data integrity validation
- Foreign key validation

## Common Fixtures

Available in `conftest.py`:

- `db_path` - Path to database
- `db_connection` - Database connection (auto-rollback)
- `temp_project_dir` - Temporary project with sample files
- `temp_workspace` - Temporary workspace directory
- `test_project` - Full test project setup in database
- `clean_db_session` - Ensures clean database session

## Helper Functions

Available in `conftest.py`:

**CLI Operations:**
- `run_templedb_cmd(args)` - Run CLI command
- `checkout_project(slug, workspace)` - Checkout project
- `commit_project(slug, workspace, message)` - Commit changes

**Database Queries:**
- `get_project_stats(slug)` - Get file/commit counts
- `get_latest_commit(slug)` - Get latest commit info
- `count_table_rows(table)` - Count table rows

**File Operations:**
- `create_file(path, content)` - Create file
- `modify_file(path, append)` - Modify file
- `delete_file(path)` - Delete file

**Assertions:**
- `assert_file_exists(path)` - Assert file exists
- `assert_file_not_exists(path)` - Assert file doesn't exist
- `assert_file_contains(path, text)` - Assert file contains text

## Configuration

Test configuration is in `pytest.ini` at the project root:

- Test discovery paths
- Output formatting
- Markers
- Logging configuration

## Installation

```bash
# Minimum requirements
pip install pytest

# Recommended plugins
pip install pytest-cov      # Coverage reports
pip install pytest-xdist    # Parallel execution (-n auto)
pip install pytest-timeout  # Test timeouts
```

## Coverage Reports

```bash
# Generate coverage report
pytest --cov=src --cov-report=html --cov-report=term

# View HTML report
open htmlcov/index.html
```

## Parallel Execution

```bash
# Run tests in parallel (requires pytest-xdist)
pytest -n auto
```

## Debugging Tests

```bash
# Stop on first failure
pytest -x

# Drop into debugger on failure
pytest --pdb

# Show local variables in traceback
pytest -l

# Show print statements
pytest -s
```

## Writing New Tests

1. Create test file in `tests/test_*.py`
2. Import fixtures from `conftest`
3. Use pytest markers to categorize
4. Follow naming convention: `test_*`

Example:

```python
import pytest
from conftest import temp_workspace, checkout_project

@pytest.mark.workflow
@pytest.mark.integration
def test_my_workflow(temp_workspace):
    """Test description"""

    # Your test code here
    checkout_project("templedb", temp_workspace)

    assert something, "Assertion message"
```

## CI/CD Integration

The test suite is designed for easy CI/CD integration:

```yaml
# Example GitHub Actions
- name: Run tests
  run: |
    pip install pytest
    ./run_tests.sh
```

## Troubleshooting

**Database not found:**
- Set `TEMPLEDB_PATH` environment variable
- Or ensure database exists at `~/.local/share/templedb/templedb.sqlite`

**Import errors:**
- Ensure you're running from project root
- Check that `src/` is in Python path (conftest.py handles this)

**Test failures:**
- Check database state
- Run with `-v` for verbose output
- Check test logs in `tests/test_output.log`

## Test Metrics

Current test coverage:

- **5 test files**
- **30+ individual tests**
- **Coverage areas:**
  - ✅ Workflow operations (checkout, commit)
  - ✅ Concurrency and conflict detection
  - ✅ Transaction atomicity
  - ✅ Database constraints
  - ✅ Data integrity validation

## Migration from Old Tests

All bash test scripts have been converted to pytest:

- `test_phase3_workflow.sh` → `test_workflow.py`
- `test_phase4_concurrent.sh` → `test_concurrent.py`
- `test_snapshot_update.sh` → `test_snapshot.py`
- `test_transactions.py` → Updated with fixtures
- `test_constraints.py` → Updated with fixtures

Old files have been removed from the project root.
