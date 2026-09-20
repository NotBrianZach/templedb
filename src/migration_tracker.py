#!/usr/bin/env python3
"""
Migration Tracking System

Tracks which migrations have been applied to each deployment target to prevent duplicate execution.
"""
import hashlib
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Migration:
    """Represents a migration file"""
    file_path: str  # Relative path from project root
    file_name: str
    checksum: str
    content: str
    lines_of_code: int

    @property
    def display_name(self) -> str:
        """Get display name (filename without extension)"""
        return Path(self.file_path).stem


@dataclass
class MigrationStatus:
    """Status of a migration"""
    migration: Migration
    applied: bool
    applied_at: Optional[str] = None
    applied_by: Optional[str] = None
    execution_time_ms: Optional[int] = None
    status: Optional[str] = None  # 'success', 'failed', 'rolled_back'
    error_message: Optional[str] = None


class MigrationTracker:
    """Tracks migration application status"""

    def __init__(self, db_utils):
        """Initialize with database utilities"""
        self.query_one = db_utils.query_one
        self.query_all = db_utils.query_all
        self.execute = db_utils.execute

    def get_project_migrations(self, project_id: int) -> List[Migration]:
        """Get all migrations for a project, sorted by filename"""
        rows = self.query_all("""
            SELECT
                pf.file_path,
                pf.file_name,
                pf.lines_of_code,
                fc.content_hash,
                cb.content_text
            FROM project_files pf
            JOIN file_types ft ON pf.file_type_id = ft.id
            JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
            JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
            WHERE pf.project_id = ?
              AND ft.type_name = 'sql_migration'
            ORDER BY pf.file_path
        """, (project_id,))

        migrations = []
        for row in rows:
            migrations.append(Migration(
                file_path=row['file_path'],
                file_name=row['file_name'],
                checksum=row['content_hash'],
                content=row['content_text'] or '',
                lines_of_code=row['lines_of_code'] or 0
            ))

        return migrations

    def get_migration_history(
        self,
        project_id: int,
        target_name: str,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """Get migration history for a project/target"""
        query = """
            SELECT
                migration_file,
                migration_checksum,
                applied_at,
                applied_by,
                execution_time_ms,
                status,
                error_message
            FROM migration_history
            WHERE project_id = ? AND target_name = ?
            ORDER BY applied_at DESC
        """

        if limit:
            query += f" LIMIT {limit}"

        return self.query_all(query, (project_id, target_name))

    def is_migration_applied(
        self,
        project_id: int,
        target_name: str,
        migration_file: str
    ) -> bool:
        """Check if a migration has been applied to a target"""
        result = self.query_one("""
            SELECT id FROM migration_history
            WHERE project_id = ?
              AND target_name = ?
              AND migration_file = ?
              AND status = 'success'
        """, (project_id, target_name, migration_file))

        return result is not None

    def get_migration_statuses(
        self,
        project_id: int,
        target_name: str
    ) -> List[MigrationStatus]:
        """Get status of all migrations (applied vs pending)"""
        migrations = self.get_project_migrations(project_id)
        statuses = []

        for migration in migrations:
            # Check if applied
            history = self.query_one("""
                SELECT
                    applied_at,
                    applied_by,
                    execution_time_ms,
                    status,
                    error_message
                FROM migration_history
                WHERE project_id = ?
                  AND target_name = ?
                  AND migration_file = ?
                ORDER BY applied_at DESC
                LIMIT 1
            """, (project_id, target_name, migration.file_path))

            if history and history['status'] == 'success':
                statuses.append(MigrationStatus(
                    migration=migration,
                    applied=True,
                    applied_at=history['applied_at'],
                    applied_by=history['applied_by'],
                    execution_time_ms=history['execution_time_ms'],
                    status=history['status']
                ))
            else:
                statuses.append(MigrationStatus(
                    migration=migration,
                    applied=False
                ))

        return statuses

    def get_pending_migrations(
        self,
        project_id: int,
        target_name: str
    ) -> List[Migration]:
        """Get migrations that haven't been applied yet"""
        statuses = self.get_migration_statuses(project_id, target_name)
        return [s.migration for s in statuses if not s.applied]

    def record_migration_success(
        self,
        project_id: int,
        target_name: str,
        migration_file: str,
        migration_checksum: str,
        execution_time_ms: int,
        applied_by: Optional[str] = None
    ) -> None:
        """Record successful migration application"""
        self.execute("""
            INSERT INTO migration_history (
                project_id,
                target_name,
                migration_file,
                migration_checksum,
                execution_time_ms,
                applied_by,
                status
            ) VALUES (?, ?, ?, ?, ?, ?, 'success')
            ON CONFLICT(project_id, target_name, migration_file)
            DO UPDATE SET
                migration_checksum = excluded.migration_checksum,
                applied_at = datetime('now'),
                applied_by = excluded.applied_by,
                execution_time_ms = excluded.execution_time_ms,
                status = 'success',
                error_message = NULL
        """, (
            project_id,
            target_name,
            migration_file,
            migration_checksum,
            execution_time_ms,
            applied_by or 'templedb'
        ))

    def record_migration_failure(
        self,
        project_id: int,
        target_name: str,
        migration_file: str,
        migration_checksum: str,
        error_message: str,
        execution_time_ms: Optional[int] = None,
        applied_by: Optional[str] = None
    ) -> None:
        """Record failed migration attempt"""
        self.execute("""
            INSERT INTO migration_history (
                project_id,
                target_name,
                migration_file,
                migration_checksum,
                execution_time_ms,
                applied_by,
                status,
                error_message
            ) VALUES (?, ?, ?, ?, ?, ?, 'failed', ?)
            ON CONFLICT(project_id, target_name, migration_file)
            DO UPDATE SET
                migration_checksum = excluded.migration_checksum,
                applied_at = datetime('now'),
                applied_by = excluded.applied_by,
                execution_time_ms = excluded.execution_time_ms,
                status = 'failed',
                error_message = excluded.error_message
        """, (
            project_id,
            target_name,
            migration_file,
            migration_checksum,
            execution_time_ms,
            applied_by or 'templedb',
            error_message
        ))

    def mark_migration_applied(
        self,
        project_id: int,
        target_name: str,
        migration_file: str,
        migration_checksum: str,
        applied_by: Optional[str] = None
    ) -> None:
        """Mark a migration as applied without actually running it"""
        self.execute("""
            INSERT INTO migration_history (
                project_id,
                target_name,
                migration_file,
                migration_checksum,
                applied_by,
                status,
                execution_time_ms
            ) VALUES (?, ?, ?, ?, ?, 'success', 0)
            ON CONFLICT(project_id, target_name, migration_file)
            DO UPDATE SET
                migration_checksum = excluded.migration_checksum,
                applied_at = datetime('now'),
                applied_by = excluded.applied_by,
                status = 'success'
        """, (
            project_id,
            target_name,
            migration_file,
            migration_checksum,
            applied_by or 'templedb'
        ))
