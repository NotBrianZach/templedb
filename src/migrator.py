#!/usr/bin/env python3
"""
TempleDB Migration Framework

Tracks applied migrations in a schema_version table and applies
pending ones in order. Supports both fresh installs (schema.sql)
and incremental upgrades (numbered migrations).

Usage:
    from migrator import Migrator
    m = Migrator(db_path)
    m.migrate()       # apply all pending
    m.status()        # show current state
"""

import os
import re
import sqlite3
import hashlib
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Tuple, Optional, Dict

logger = logging.getLogger(__name__)

# Migration files live here.
#
# Two candidate layouts:
#   - Dev tree / materialised checkout:
#       src/migrator.py + migrations/*.sql at project root
#     → Path(__file__).parent.parent / "migrations"
#
#   - Nix install: templedb.nix's postInstall copies migrations/ into
#     site-packages/ next to migrator.py:
#       site-packages/migrator.py + site-packages/migrations/*.sql
#     → Path(__file__).parent / "migrations"
#
# Pick the first candidate that actually contains migrations. Falls
# back to the dev-tree location so error messages remain intuitive
# when nothing is found.

def _find_migrations_dir():
    module_dir = Path(__file__).parent
    for candidate in (
        module_dir / "migrations",           # nix install (sibling)
        module_dir.parent / "migrations",    # dev tree (project root)
    ):
        if candidate.exists() and any(candidate.glob("*.sql")):
            return candidate
    return module_dir.parent / "migrations"


MIGRATIONS_DIR = _find_migrations_dir()

# Non-versioned base files applied on fresh installs. schema.sql is the
# consolidated superset for everything up through the last regenerate;
# the *_schema.sql files are pre-migration-framework fragments retained
# for legacy DBs. Order matters (base tables before views).
BASE_FILES = [
    "schema.sql",
    "config_links_schema.sql",
    "database_vcs_schema.sql",
    "file_tracking_schema.sql",
    "file_versioning_schema.sql",
    "vcs_metadata_schema.sql",
    "views.sql",
]

# Numbered migrations are discovered by scanning MIGRATIONS_DIR for files
# matching this pattern. Version comes from the filename prefix; two
# files claiming the same version is a fatal error (see _discover_migrations).
_NUMBERED_MIGRATION_RE = re.compile(r'^(\d+)_.+\.sql$')


def _discover_migrations(applied_filenames: Optional[set] = None) -> List[Tuple[int, str]]:
    """Scan MIGRATIONS_DIR for numbered migration files.

    Returns [(version, filename)] sorted by (version, filename). Filenames
    must match ``<int>_<slug>.sql``; anything else is ignored (base
    files, archived/ subdir, arbitrary .sql fixtures).

    Collision handling:
      * If applied_filenames is None: strict mode -- any two files
        claiming the same version fail loud.
      * If applied_filenames is provided: same-version files are tolerated
        iff every colliding file is already in schema_version. This
        exists for historical drift (e.g. 106_agent_notifications.sql
        and 106_project_files_edit_mode.sql both landed in the
        production DB before this checker existed). Unapplied
        collisions still fail -- ambiguous apply order would diverge
        across installs.
    """
    groups: Dict[int, List[str]] = {}
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        m = _NUMBERED_MIGRATION_RE.match(path.name)
        if not m:
            continue
        version = int(m.group(1))
        groups.setdefault(version, []).append(path.name)

    resolved: List[Tuple[int, str]] = []
    for version, filenames in sorted(groups.items()):
        if len(filenames) == 1:
            resolved.append((version, filenames[0]))
            continue
        # Collision. Tolerate iff every file is already applied.
        if applied_filenames is not None \
                and all(f in applied_filenames for f in filenames):
            logger.warning(
                f"Migration version {version:03d} has {len(filenames)} "
                f"files (historical drift): {filenames}. All already "
                f"applied; skipping re-apply. Rename to distinct versions "
                f"if you plan to touch these again."
            )
            for f in filenames:
                resolved.append((version, f))
            continue
        raise RuntimeError(
            f"Migration version collision at {version:03d}: {filenames}. "
            f"At least one is unapplied. Rename before running -- "
            f"ambiguous order would diverge across installs."
        )
    return resolved


def _file_hash(path: Path) -> str:
    """SHA-256 of a migration file for integrity tracking."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


class Migrator:
    """Database migration runner with version tracking."""

    SCHEMA_VERSION_DDL = """
    CREATE TABLE IF NOT EXISTS schema_version (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        version     INTEGER NOT NULL,
        filename    TEXT NOT NULL,
        file_hash   TEXT,
        applied_at  TEXT NOT NULL,
        UNIQUE(filename)
    );
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.migrations_dir = MIGRATIONS_DIR

    def _connect(self) -> sqlite3.Connection:
        from db_utils import apply_standard_pragmas
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        # Migrations don't insert into sync-tracked tables; skip crsqlite
        # load so a fresh DB migration doesn't require the extension.
        apply_standard_pragmas(conn, load_crsqlite=False)
        return conn

    def _ensure_version_table(self, conn: sqlite3.Connection):
        conn.executescript(self.SCHEMA_VERSION_DDL)

    def _get_applied(self, conn: sqlite3.Connection) -> Dict[str, dict]:
        """Return {filename: {version, file_hash, applied_at}} for all applied migrations."""
        self._ensure_version_table(conn)
        rows = conn.execute(
            "SELECT filename, version, file_hash, applied_at FROM schema_version ORDER BY version"
        ).fetchall()
        return {r["filename"]: dict(r) for r in rows}

    def _is_fresh_db(self, conn: sqlite3.Connection) -> bool:
        """Check if this is a brand new database with no user tables."""
        tables = conn.execute(
            "SELECT COUNT(*) as c FROM sqlite_master WHERE type='table' "
            "AND name NOT IN ('schema_version', 'sqlite_sequence')"
        ).fetchone()
        return tables["c"] == 0

    def _apply_file(self, conn: sqlite3.Connection, filename: str, version: int) -> bool:
        """Apply a single migration file. Returns True on success."""
        path = self.migrations_dir / filename
        if not path.exists():
            logger.warning(f"Migration file not found: {filename}")
            return False

        sql = path.read_text()
        fhash = _file_hash(path)

        try:
            conn.executescript(sql)
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, filename, file_hash, applied_at) "
                "VALUES (?, ?, ?, datetime('now'))",
                (version, filename, fhash),
            )
            conn.commit()
            return True
        except sqlite3.Error as e:
            logger.error(f"Migration {filename} failed: {e}")
            conn.rollback()
            return False

    # Tables introduced by migrations *after* schema.sql's frozen point.
    # If any are missing after a fresh install, the corresponding migration
    # failed for a real reason (not a "schema.sql already has it" reason)
    # and someone needs to look.
    _POST_SCHEMA_TABLES = (
        "nix_store_paths",      # 075
        "agent_work_log",       # 076
        "config_nodes",         # 077
        "ast_builds",           # 079
        "agent_pending_asks",   # 080
        "graph_query_log",      # 081
        "vcs_sessions",         # 082
    )

    def _verify_critical_tables(self, conn: sqlite3.Connection) -> None:
        """After fresh install: assert every post-schema.sql migration's
        key table exists. Missing tables mean the migration was silently
        swallowed by our error tolerance."""
        missing = []
        for tbl in self._POST_SCHEMA_TABLES:
            row = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (tbl,),
            ).fetchone()
            if not row:
                missing.append(tbl)
        if missing:
            logger.error(
                f"Post-schema.sql tables missing after fresh install: {missing}. "
                "This means a migration failed and its errors were swallowed. "
                "Run `templedb admin db status` and inspect the marker hashes."
            )
            raise RuntimeError(f"Fresh install left tables missing: {missing}")


    def migrate(self, dry_run: bool = False) -> Tuple[int, int]:
        """
        Apply all pending migrations.

        For a fresh DB: applies schema.sql then marks all numbered migrations
        as applied (schema.sql is the consolidated superset).

        For an existing DB: applies only the numbered migrations that haven't
        been recorded yet.

        Returns (applied_count, skipped_count).
        """
        conn = self._connect()
        self._ensure_version_table(conn)
        applied = self._get_applied(conn)
        fresh = self._is_fresh_db(conn)

        applied_count = 0
        skipped_count = 0

        # Discover numbered migrations from the filesystem. Raises on
        # unapplied duplicate version prefixes so we fail loud instead
        # of picking an ambiguous winner (already-applied duplicates
        # are tolerated with a warning -- see _discover_migrations).
        numbered = _discover_migrations(applied_filenames=set(applied.keys()))

        if fresh:
            # Fresh install: schema.sql is the canonical superset. Mark
            # all numbered migrations as applied via 'via-schema.sql' so
            # subsequent non-fresh runs won't try to re-apply them.
            #
            # Correctness depends on schema.sql actually reflecting every
            # migration's endpoint state. If schema.sql drifts (as
            # happened Aug 2026 with migrations 075-082 missing), fresh
            # installs get a broken shape. `_verify_critical_tables`
            # catches that at install time; long-term fix is to
            # regenerate schema.sql after every new migration lands.
            schema_file = "schema.sql"
            if schema_file not in applied:
                if dry_run:
                    print(f"  [DRY RUN] Would apply: {schema_file}")
                    applied_count += 1
                else:
                    print(f"  Applying base schema: {schema_file}")
                    if self._apply_file(conn, schema_file, 0):
                        applied_count += 1
                    else:
                        conn.close()
                        return (0, 0)

                for version, filename in numbered:
                    if filename not in applied:
                        if not dry_run:
                            conn.execute(
                                "INSERT OR IGNORE INTO schema_version (version, filename, file_hash, applied_at) "
                                "VALUES (?, ?, 'via-schema.sql', datetime('now'))",
                                (version, filename),
                            )
                        skipped_count += 1

                if not dry_run:
                    conn.commit()
                    print(f"  Marked {skipped_count} numbered migrations as applied (schema.sql superset)")
                    self._verify_critical_tables(conn)
        else:
            # Existing DB — apply only missing numbered migrations
            for version, filename in numbered:
                if filename in applied:
                    skipped_count += 1
                    continue

                if dry_run:
                    print(f"  [DRY RUN] Would apply: {filename}")
                    applied_count += 1
                else:
                    print(f"  Applying: {filename}")
                    if self._apply_file(conn, filename, version):
                        applied_count += 1
                    else:
                        print(f"  STOPPED at {filename} due to error")
                        break

        conn.close()
        return (applied_count, skipped_count)

    def status(self) -> List[dict]:
        """
        Return migration status: each entry has filename, applied (bool),
        applied_at, and file_hash.
        """
        conn = self._connect()
        self._ensure_version_table(conn)
        applied = self._get_applied(conn)
        conn.close()

        result = []
        # Base schema
        schema_info = applied.get("schema.sql")
        result.append({
            "filename": "schema.sql",
            "applied": schema_info is not None,
            "applied_at": schema_info["applied_at"] if schema_info else None,
            "file_hash": schema_info["file_hash"] if schema_info else None,
        })

        # Numbered migrations (discovered from filesystem). Pass applied
        # set so historical same-version drift shows as a warning
        # rather than raising.
        for _version, filename in _discover_migrations(applied_filenames=set(applied.keys())):
            info = applied.get(filename)
            result.append({
                "filename": filename,
                "applied": info is not None,
                "applied_at": info["applied_at"] if info else None,
                "file_hash": info["file_hash"] if info else None,
            })

        # Base fragments (retained for legacy DBs pre-migration-framework)
        for filename in BASE_FILES[1:]:  # skip schema.sql (already shown)
            info = applied.get(filename)
            result.append({
                "filename": filename,
                "applied": info is not None,
                "applied_at": info["applied_at"] if info else None,
                "file_hash": info["file_hash"] if info else None,
            })

        return result

    def stamp_existing(self) -> int:
        """
        For an existing database that predates the migration framework:
        mark all migrations as applied without running them.
        Returns the number of migrations stamped.
        """
        conn = self._connect()
        self._ensure_version_table(conn)
        applied = self._get_applied(conn)

        stamped = 0

        # Stamp schema.sql
        if "schema.sql" not in applied:
            conn.execute(
                "INSERT OR IGNORE INTO schema_version (version, filename, file_hash, applied_at) "
                "VALUES (0, 'schema.sql', 'pre-existing', datetime('now'))",
            )
            stamped += 1

        # Stamp all numbered migrations. Pass applied set so historical
        # same-version drift is tolerated (all-applied → warning).
        for version, filename in _discover_migrations(applied_filenames=set(applied.keys())):
            if filename not in applied:
                conn.execute(
                    "INSERT OR IGNORE INTO schema_version (version, filename, file_hash, applied_at) "
                    "VALUES (?, ?, 'pre-existing', datetime('now'))",
                    (version, filename),
                )
                stamped += 1

        conn.commit()
        conn.close()
        return stamped
