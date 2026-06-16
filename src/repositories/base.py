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

    def execute(self, sql: str, params: tuple = None, commit: bool = True) -> int:
        """
        Execute a non-query SQL statement (INSERT, UPDATE, DELETE).

        Args:
            sql: SQL statement string
            params: Statement parameters (optional)
            commit: Whether to commit immediately (default: True)

        Returns:
            Row ID for INSERT statements, or number of affected rows

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
            logger.debug(f"Statement affected {result} rows/returned ID")
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
