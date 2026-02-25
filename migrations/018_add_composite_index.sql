-- ============================================================================
-- Migration 018: Add composite index for (project_id, file_path)
-- ============================================================================
-- Purpose: Add performance-optimized composite index to enforce the pattern
--          WHERE project_id = ? AND file_path = ?
--
-- This index is critical for query performance and documents the requirement
-- that file_path queries MUST always include project_id filtering.
--
-- See: QUERY_BEST_PRACTICES.md for usage guidelines
-- ============================================================================

-- Add composite index on (project_id, file_path)
-- This makes queries filtering by both fields very efficient
CREATE INDEX IF NOT EXISTS idx_project_files_project_path
ON project_files(project_id, file_path);

-- Verify index was created
SELECT
    name,
    sql
FROM sqlite_master
WHERE type = 'index'
  AND tbl_name = 'project_files'
  AND name = 'idx_project_files_project_path';
