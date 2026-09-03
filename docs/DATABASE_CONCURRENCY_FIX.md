# Database Concurrency Fix

## Problem

When running multiple `tdb vibe start` instances, users experienced "database is locked" errors. This occurred because different parts of the codebase were creating database connections with inconsistent settings:

- Some connections enabled WAL (Write-Ahead Logging) mode
- Others used the default DELETE journal mode
- SQLite doesn't handle mixing journal modes well, leading to lock conflicts

## Root Cause

Multiple `get_db_connection()` functions existed throughout the codebase with different configurations:

```python
# ❌ BAD: No WAL mode
def get_db_connection():
    return sqlite3.connect(DB_PATH)

# ✓ GOOD: WAL mode enabled
def get_db_connection(db_path: str):
    conn = sqlite3.connect(db_path, timeout=30.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn
```

## Solution

1. **Centralized connection function** in `src/db_utils.py`:
   - Added `get_simple_connection()` for consistent connection settings
   - All connections now enable WAL mode and proper timeouts

2. **Updated all connection points**:
   - `src/cli/commands/vibe.py`
   - `src/cli/commands/vibe_query.py`
   - `src/cli/commands/vibe_realtime.py`
   - `src/vibe_watcher.py`
   - `src/mcp_server.py`

3. **Key settings for concurrent access**:
   ```python
   PRAGMA journal_mode=WAL           # Enable Write-Ahead Logging
   PRAGMA busy_timeout=30000         # 30 second busy timeout
   PRAGMA synchronous=NORMAL         # Balance safety/performance
   PRAGMA cache_size=-64000          # 64MB cache
   PRAGMA foreign_keys=ON            # Enforce constraints
   ```

## Benefits of WAL Mode

1. **Concurrent readers** - Multiple processes can read simultaneously
2. **Writers don't block readers** - Read operations continue during writes
3. **Better performance** - Reduced I/O, faster commits
4. **Crash safety** - Database remains consistent after crashes

## Testing

Verified with concurrent access tests:
- ✓ 10 concurrent workers performing 500 total operations
- ✓ 5 simulated vibe server instances running simultaneously
- ✓ No "database is locked" errors
- ✓ ~7000 operations/second throughput

## Usage

All code should now use the centralized connection functions:

```python
from db_utils import get_simple_connection

# For simple connections
conn = get_simple_connection()

# With row factory for dict-like access
conn = get_simple_connection(row_factory=True)

# Custom database path
conn = get_simple_connection(db_path="/path/to/db.sqlite")
```

## Files Changed

- `src/db_utils.py` - Added `get_simple_connection()` function
- `src/cli/commands/vibe.py` - Updated to use centralized function
- `src/cli/commands/vibe_query.py` - Updated connection creation
- `src/cli/commands/vibe_realtime.py` - Updated connection creation
- `src/vibe_watcher.py` - Updated connection creation
- `src/mcp_server.py` - Updated `_get_db_connection()` to enable WAL

## References

- SQLite WAL Mode: https://www.sqlite.org/wal.html
- SQLite PRAGMA statements: https://www.sqlite.org/pragma.html
- TempleDB Architecture: docs/ARCHITECTURE.md
