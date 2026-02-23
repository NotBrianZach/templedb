-- Migration 008: Consolidate File Metadata Tables
-- Consolidates sql_objects, javascript_components, edge_functions, api_endpoints,
-- database_migrations, and config_files into single file_metadata table
--
-- Before: 7 tables (sql_objects, javascript_components, edge_functions, api_endpoints, database_migrations, config_files, file_types)
-- After: 2 tables (file_metadata, file_types)
-- Reduction: 5 tables

BEGIN TRANSACTION;

-- Create new consolidated file_metadata table
CREATE TABLE IF NOT EXISTS file_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    metadata_type TEXT NOT NULL CHECK(metadata_type IN (
        'sql_object', 'js_component', 'edge_function',
        'api_endpoint', 'migration', 'config'
    )),
    object_name TEXT,
    metadata_json TEXT,  -- JSON blob with type-specific fields
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (file_id) REFERENCES project_files(id) ON DELETE CASCADE
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_file_metadata_file_id
    ON file_metadata(file_id);
CREATE INDEX IF NOT EXISTS idx_file_metadata_type
    ON file_metadata(metadata_type);
CREATE INDEX IF NOT EXISTS idx_file_metadata_file_type
    ON file_metadata(file_id, metadata_type);
CREATE INDEX IF NOT EXISTS idx_file_metadata_name
    ON file_metadata(object_name);

-- Migrate data from sql_objects
INSERT INTO file_metadata (file_id, metadata_type, object_name, metadata_json)
SELECT
    file_id,
    'sql_object' as metadata_type,
    object_name,
    json_object(
        'schema_name', COALESCE(schema_name, 'public'),
        'object_type', object_type,
        'function_language', function_language,
        'has_foreign_keys', CASE WHEN has_foreign_keys = 1 THEN 'true' ELSE 'false' END,
        'is_indexed', CASE WHEN is_indexed = 1 THEN 'true' ELSE 'false' END,
        'row_count_estimate', row_count_estimate,
        'size_bytes', size_bytes
    ) as metadata_json
FROM sql_objects
WHERE EXISTS (SELECT 1 FROM sql_objects);  -- Only if table exists and has data

-- Migrate data from javascript_components
INSERT INTO file_metadata (file_id, metadata_type, object_name, metadata_json)
SELECT
    file_id,
    'js_component' as metadata_type,
    component_name as object_name,
    json_object(
        'component_type', component_type,
        'is_default_export', CASE WHEN is_default_export = 1 THEN 'true' ELSE 'false' END,
        'has_props', CASE WHEN has_props = 1 THEN 'true' ELSE 'false' END,
        'has_state', CASE WHEN has_state = 1 THEN 'true' ELSE 'false' END,
        'is_functional', CASE WHEN is_functional = 1 THEN 'true' ELSE 'false' END,
        'imports', imports
    ) as metadata_json
FROM javascript_components
WHERE EXISTS (SELECT 1 FROM javascript_components);

-- Migrate data from edge_functions
INSERT INTO file_metadata (file_id, metadata_type, object_name, metadata_json)
SELECT
    file_id,
    'edge_function' as metadata_type,
    function_name as object_name,
    json_object(
        'runtime', runtime,
        'method', method,
        'route', route,
        'has_auth', CASE WHEN has_auth = 1 THEN 'true' ELSE 'false' END,
        'cors_enabled', CASE WHEN cors_enabled = 1 THEN 'true' ELSE 'false' END,
        'timeout_ms', timeout_ms
    ) as metadata_json
FROM edge_functions
WHERE EXISTS (SELECT 1 FROM edge_functions);

-- Migrate data from api_endpoints
INSERT INTO file_metadata (file_id, metadata_type, object_name, metadata_json)
SELECT
    file_id,
    'api_endpoint' as metadata_type,
    endpoint_path as object_name,
    json_object(
        'http_method', http_method,
        'handler_function', handler_function,
        'description', description,
        'parameters', parameters,
        'response_type', response_type,
        'requires_auth', CASE WHEN requires_auth = 1 THEN 'true' ELSE 'false' END,
        'rate_limit_rpm', rate_limit_rpm
    ) as metadata_json
FROM api_endpoints
WHERE EXISTS (SELECT 1 FROM api_endpoints);

-- Migrate data from database_migrations
INSERT INTO file_metadata (file_id, metadata_type, object_name, metadata_json)
SELECT
    file_id,
    'migration' as metadata_type,
    migration_name as object_name,
    json_object(
        'version_number', version_number,
        'applied_at', applied_at,
        'rolled_back_at', rolled_back_at,
        'checksum', checksum,
        'direction', direction
    ) as metadata_json
FROM database_migrations
WHERE EXISTS (SELECT 1 FROM database_migrations);

-- Migrate data from config_files
INSERT INTO file_metadata (file_id, metadata_type, object_name, metadata_json)
SELECT
    file_id,
    'config' as metadata_type,
    config_name as object_name,
    json_object(
        'config_type', config_type,
        'schema_url', schema_url,
        'is_valid', CASE WHEN is_valid = 1 THEN 'true' ELSE 'false' END,
        'validation_errors', validation_errors,
        'last_validated', last_validated
    ) as metadata_json
FROM config_files
WHERE EXISTS (SELECT 1 FROM config_files);

-- Create backward-compatible views
CREATE VIEW IF NOT EXISTS sql_objects_view AS
SELECT
    fm.id,
    fm.file_id,
    pf.file_path,
    pf.project_id,
    fm.object_name,
    json_extract(fm.metadata_json, '$.schema_name') as schema_name,
    json_extract(fm.metadata_json, '$.object_type') as object_type,
    json_extract(fm.metadata_json, '$.function_language') as function_language,
    CASE WHEN json_extract(fm.metadata_json, '$.has_foreign_keys') = 'true' THEN 1 ELSE 0 END as has_foreign_keys,
    CASE WHEN json_extract(fm.metadata_json, '$.is_indexed') = 'true' THEN 1 ELSE 0 END as is_indexed,
    json_extract(fm.metadata_json, '$.row_count_estimate') as row_count_estimate,
    json_extract(fm.metadata_json, '$.size_bytes') as size_bytes
FROM file_metadata fm
JOIN project_files pf ON fm.file_id = pf.id
WHERE fm.metadata_type = 'sql_object';

CREATE VIEW IF NOT EXISTS javascript_components_view AS
SELECT
    fm.id,
    fm.file_id,
    pf.file_path,
    pf.project_id,
    fm.object_name as component_name,
    json_extract(fm.metadata_json, '$.component_type') as component_type,
    CASE WHEN json_extract(fm.metadata_json, '$.is_default_export') = 'true' THEN 1 ELSE 0 END as is_default_export,
    CASE WHEN json_extract(fm.metadata_json, '$.has_props') = 'true' THEN 1 ELSE 0 END as has_props,
    CASE WHEN json_extract(fm.metadata_json, '$.has_state') = 'true' THEN 1 ELSE 0 END as has_state,
    CASE WHEN json_extract(fm.metadata_json, '$.is_functional') = 'true' THEN 1 ELSE 0 END as is_functional,
    json_extract(fm.metadata_json, '$.imports') as imports
FROM file_metadata fm
JOIN project_files pf ON fm.file_id = pf.id
WHERE fm.metadata_type = 'js_component';

CREATE VIEW IF NOT EXISTS api_endpoints_view AS
SELECT
    fm.id,
    fm.file_id,
    pf.file_path,
    pf.project_id,
    fm.object_name as endpoint_path,
    json_extract(fm.metadata_json, '$.http_method') as http_method,
    json_extract(fm.metadata_json, '$.handler_function') as handler_function,
    json_extract(fm.metadata_json, '$.description') as description,
    json_extract(fm.metadata_json, '$.parameters') as parameters,
    json_extract(fm.metadata_json, '$.response_type') as response_type,
    CASE WHEN json_extract(fm.metadata_json, '$.requires_auth') = 'true' THEN 1 ELSE 0 END as requires_auth,
    json_extract(fm.metadata_json, '$.rate_limit_rpm') as rate_limit_rpm
FROM file_metadata fm
JOIN project_files pf ON fm.file_id = pf.id
WHERE fm.metadata_type = 'api_endpoint';

-- Drop old tables (only if they exist)
DROP TABLE IF EXISTS sql_objects;
DROP TABLE IF EXISTS javascript_components;
DROP TABLE IF EXISTS edge_functions;
DROP TABLE IF EXISTS api_endpoints;
DROP TABLE IF EXISTS database_migrations;
DROP TABLE IF EXISTS config_files;

-- Create trigger to auto-update updated_at timestamp
CREATE TRIGGER IF NOT EXISTS update_file_metadata_timestamp
AFTER UPDATE ON file_metadata
FOR EACH ROW
BEGIN
    UPDATE file_metadata SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

COMMIT;

-- Verify migration
SELECT
    'file_metadata' as table_name,
    COUNT(*) as row_count,
    COUNT(DISTINCT metadata_type) as metadata_types
FROM file_metadata;
