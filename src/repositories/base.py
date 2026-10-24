"""
Base repository class providing common database operations.
"""

from typing import Optional, List, Dict, Any
from contextlib import contextmanager
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from db_utils import query_one as db_query_one, query_all as db_query_all
from db_utils import execute as db_execute, transaction as db_transaction
from db_utils import execute_rowcount as db_execute_rowcount
from logger import get_logger

logger = get_logger(__name__)


class BaseRepository:
    """
    Base repository providing common database operations.

    All repositories inherit from this class to get standard
    query methods with proper error handling and logging.
    """

    def query_one(self, sql: str, params: tuple = None) -> Optional[Dict[str, Any]]:
        """
        Execute a query and return a single row as a dictionary.

        Args:
            sql: SQL query string
            params: Query parameters (optional)

        Returns:
            Dictionary representing the row, or None if no results

        Example:
            >>> repo = BaseRepository()
            >>> project = repo.query_one("SELECT * FROM projects WHERE slug = ?", ("myproject",))
        """
        try:
            logger.debug(f"Executing query: {sql[:100]}...")
            if params:
                logger.debug(f"Parameters: {params}")
                result = db_query_one(sql, params)
            else:
                result = db_query_one(sql)
            return result
        except Exception as e:
            logger.error(f"Query failed: {e}", exc_info=True)
            raise

    def query_all(self, sql: str, params: tuple = None) -> List[Dict[str, Any]]:
        """
        Execute a query and return all rows as a list of dictionaries.

        Args:
            sql: SQL query string
            params: Query parameters (optional)

        Returns:
            List of dictionaries representing rows

        Example:
            >>> repo = BaseRepository()
            >>> projects = repo.query_all("SELECT * FROM projects")
        """
        try:
            logger.debug(f"Executing query: {sql[:100]}...")
            if params:
                logger.debug(f"Parameters: {params}")
                results = db_query_all(sql, params)
            else:
                results = db_query_all(sql)
            logger.debug(f"Query returned {len(results)} rows")
            return results
        except Exception as e:
            logger.error(f"Query failed: {e}", exc_info=True)
            raise

    def execute(self, sql: str, params: tuple = (), commit: bool = True) -> int:
        """
        Execute a non-query SQL statement and return the new row's id.

        FOR INSERTs. The return value is `cursor.lastrowid`, which
        SQLite defines only after an INSERT — after an UPDATE or DELETE
        it is a leftover from the last INSERT on the connection, not a
        count. **For UPDATE/DELETE use `execute_rowcount`.**

        The docstring said "Row ID for INSERT statements, or number of
        affected rows" and the debug line said "affected N
        rows/returned ID", which is how the trap kept being walked into:
        both read as though the value adapts to the statement, and it
        does not. `db_utils.execute_rowcount` exists because four call
        sites found that out separately; this class did not expose it
        until 2026-10-23, so repository code had no way to ask.

        Args:
            sql: SQL statement string
            params: Statement parameters (optional)
            commit: Whether to commit immediately (default: True)

        Returns:
            Row ID of the inserted row. Meaningless for UPDATE/DELETE.

        Example:
            >>> repo = BaseRepository()
            >>> project_id = repo.execute(
            ...     "INSERT INTO projects (slug, name) VALUES (?, ?)",
            ...     ("myproject", "My Project")
            ... )
        """
        try:
            logger.debug(f"Executing statement: {sql[:100]}... with params: {params}")
            result = db_execute(sql, params, commit=commit)
            logger.debug(f"Statement returned row id {result}")
            return result
        except Exception as e:
            logger.error(f"Execute failed: {e}", exc_info=True)
            raise

    def execute_rowcount(self, sql: str, params: tuple = (), commit: bool = True) -> int:
        """
        Execute an UPDATE or DELETE and return how many rows changed.

        The counterpart to `execute`, and the one to reach for whenever
        the answer is "how many" rather than "which row". See `execute`
        for why the two cannot be one method.

        Args:
            sql: SQL statement string
            params: Statement parameters (optional)
            commit: Whether to commit immediately (default: True)

        Returns:
            Rows modified by the statement (`cursor.rowcount`)

        Example:
            >>> repo = BaseRepository()
            >>> n = repo.execute_rowcount(
            ...     "UPDATE handoff_notes SET project_id = NULL WHERE project_id = ?",
            ...     (project_id,)
            ... )
        """
        try:
            logger.debug(f"Executing statement: {sql[:100]}... with params: {params}")
            result = db_execute_rowcount(sql, params, commit=commit)
            logger.debug(f"Statement affected {result} row(s)")
            return result
        except Exception as e:
            logger.error(f"Execute failed: {e}", exc_info=True)
            raise

    @contextmanager
    def transaction(self):
        """
        Context manager for database transactions.

        Ensures that all operations within the context are committed
        atomically or rolled back on error.

        Example:
            >>> repo = BaseRepository()
            >>> with repo.transaction():
            ...     repo.execute("INSERT INTO projects ...", commit=False)
            ...     repo.execute("INSERT INTO files ...", commit=False)
        """
        with db_transaction():
            yield
