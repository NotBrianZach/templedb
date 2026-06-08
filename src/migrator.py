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

# Migration files live here
MIGRATIONS_DIR = Path(__file__).parent.parent / "migrations"

# Ordered list of numbered migrations to apply AFTER schema.sql
# This is the canonical sequence — add new migrations at the end.
MIGRATION_SEQUENCE = [
    "015_add_var_tag_scope.sql",
    "030_vibe_claude_interactions.sql",
    "032_add_encryption_and_system_config.sql",
    "033_remove_secret_blobs_project_id.sql",
    "034_add_deployment_cache.sql",
    "035_add_code_intelligence_graph.sql",
    "035_add_nixops4_integration.sql",
    "039_create_unified_views.sql",
    "042_add_nixos_managed_packages.sql",
    "044_add_checkout_edit_sessions.sql",
    "045_add_git_server_config.sql",
    "046_add_nix_first_support.sql",
    "047_drop_orphaned_convoy_trigger.sql",
    "048_add_readme_cross_reference_system.sql",
    "049_add_deployment_tracking.sql",
    "050_add_deployment_scripts.sql",
    "config_links_schema.sql",
    "database_vcs_schema.sql",
    "file_tracking_schema.sql",
    "file_versioning_schema.sql",
    "vcs_metadata_schema.sql",
    "views.sql",
]


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
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
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

        if fresh:
            # Fresh install — apply schema.sql (the full canonical schema)
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

                # Mark all numbered migrations as applied since schema.sql
                # is the consolidated superset
                for i, filename in enumerate(MIGRATION_SEQUENCE, start=1):
                    if filename not in applied:
                        if not dry_run:
                            conn.execute(
                                "INSERT OR IGNORE INTO schema_version (version, filename, file_hash, applied_at) "
                                "VALUES (?, ?, 'via-schema.sql', datetime('now'))",
                                (i, filename),
                            )
                        skipped_count += 1

                if not dry_run:
                    conn.commit()
                print(f"  Marked {skipped_count} numbered migrations as applied (included in schema.sql)")
        else:
            # Existing DB — apply only missing numbered migrations
            for i, filename in enumerate(MIGRATION_SEQUENCE, start=1):
                if filename in applied:
                    skipped_count += 1
                    continue

                if dry_run:
                    print(f"  [DRY RUN] Would apply: {filename}")
                    applied_count += 1
                else:
                    print(f"  Applying: {filename}")
                    if self._apply_file(conn, filename, i):
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

        # Numbered migrations
        for filename in MIGRATION_SEQUENCE:
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

        # Stamp all numbered migrations
        for i, filename in enumerate(MIGRATION_SEQUENCE, start=1):
            if filename not in applied:
                conn.execute(
                    "INSERT OR IGNORE INTO schema_version (version, filename, file_hash, applied_at) "
                    "VALUES (?, ?, 'pre-existing', datetime('now'))",
                    (i, filename),
                )
                stamped += 1

        conn.commit()
        conn.close()
        return stamped
