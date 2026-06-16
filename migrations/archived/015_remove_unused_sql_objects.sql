-- Migration 015: Remove unused sql_objects table and infrastructure
-- Date: 2026-02-23
-- Rationale: sql_objects table was never populated (0 rows) and has been
--            superseded by file_metadata table with metadata_type='sql_object'

-- Drop dependent view first
DROP VIEW IF EXISTS sql_objects_view;

-- Drop trigger
DROP TRIGGER IF EXISTS update_sql_objects_updated_at;

-- Drop indexes
DROP INDEX IF EXISTS idx_sql_objects_file_id;
DROP INDEX IF EXISTS idx_sql_objects_object_name;
DROP INDEX IF EXISTS idx_sql_objects_schema_name;

-- Drop the table itself
DROP TABLE IF EXISTS sql_objects;

-- Note: SQL object data is now stored in file_metadata table:
--   SELECT * FROM file_metadata WHERE metadata_type = 'sql_object';
--
-- Example metadata_json structure:
--   {
--     "object_count": 593,
--     "object_types": ["table", "view", "function", "trigger", ...],
--     "objects": [
--       {"type": "table", "name": "users", "schema": "public", "has_rls": true, ...},
--       ...
--     ]
--   }
