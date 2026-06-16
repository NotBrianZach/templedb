CREATE TABLE IF NOT EXISTS "content_blobs" (
    -- Primary key is content hash (content-addressable, immutable)
    hash_sha256 TEXT PRIMARY KEY,

    -- Content storage (only ONE will be populated)
    content_text TEXT,           -- For text files (UNCOMPRESSED for SQLite FTS)
    content_blob BLOB,           -- For binary files OR compressed text

    -- Content metadata
    content_type TEXT NOT NULL CHECK(content_type IN ('text', 'binary')),
    encoding TEXT DEFAULT 'utf-8',

    -- Size tracking
    file_size_bytes INTEGER NOT NULL,      -- Actual stored size (compressed if applicable)
    original_size_bytes INTEGER NOT NULL,  -- Original uncompressed size

    -- Compression
    compression TEXT DEFAULT 'none' CHECK(compression IN ('none', 'zlib', 'delta')),
    delta_base_hash TEXT,  -- If delta compressed, base blob hash

    -- Statistics
    reference_count INTEGER DEFAULT 0,

    -- Immutability tracking
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    is_deleted BOOLEAN DEFAULT 0,  -- Soft delete (never actually delete)

    -- Foreign key for delta compression
    FOREIGN KEY (delta_base_hash) REFERENCES "content_blobs"(hash_sha256),

    -- Ensure delta compression has base
    CHECK (compression != 'delta' OR delta_base_hash IS NOT NULL)
);
CREATE TABLE shared_file_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Source (the shared file)
    source_project_id INTEGER NOT NULL,
    source_file_id INTEGER NOT NULL,

    -- Consumer (project using the shared file)
    using_project_id INTEGER NOT NULL,

    -- Optional overrides
    alias TEXT,  -- Import as different name
    override_content_hash TEXT,  -- Branch-specific override

    -- Metadata
    linked_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT,

    -- Foreign keys
    FOREIGN KEY (source_project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (source_file_id) REFERENCES project_files(id) ON DELETE CASCADE,
    FOREIGN KEY (using_project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (override_content_hash) REFERENCES "content_blobs"(hash_sha256),

    UNIQUE(source_file_id, using_project_id)
);
CREATE TABLE sqlite_sequence(name,seq);
CREATE INDEX idx_shared_file_refs_source ON shared_file_references(source_file_id);
CREATE INDEX idx_shared_file_refs_using ON shared_file_references(using_project_id);
CREATE INDEX idx_content_blobs_size ON "content_blobs"(file_size_bytes);
CREATE INDEX idx_content_blobs_type ON "content_blobs"(content_type);
CREATE INDEX idx_content_blobs_compression ON "content_blobs"(compression);
CREATE INDEX idx_content_blobs_delta_base ON "content_blobs"(delta_base_hash);
CREATE INDEX idx_content_blobs_deleted ON "content_blobs"(is_deleted);
CREATE TABLE IF NOT EXISTS "file_contents" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,

    -- Content reference (not inline storage!)
    content_hash TEXT NOT NULL,

    -- Cached metadata (from content_blobs)
    content_type TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,

    -- Current version flag
    is_current BOOLEAN DEFAULT 1,

    -- Timestamps
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    -- Foreign keys
    FOREIGN KEY (file_id) REFERENCES project_files(id) ON DELETE CASCADE,
    FOREIGN KEY (content_hash) REFERENCES content_blobs(hash_sha256),

    UNIQUE(file_id, is_current)
);
CREATE INDEX idx_file_contents_file_id ON file_contents(file_id);
CREATE INDEX idx_file_contents_hash ON file_contents(content_hash);
CREATE INDEX idx_file_contents_current ON file_contents(is_current);
CREATE TRIGGER prevent_content_blob_updates
BEFORE UPDATE ON content_blobs
FOR EACH ROW
WHEN NEW.hash_sha256 != OLD.hash_sha256
   OR NEW.content_text != OLD.content_text
   OR NEW.content_blob != OLD.content_blob
BEGIN
    SELECT RAISE(ABORT, 'Content blobs are immutable. Create new blob instead.');
END;
CREATE TRIGGER prevent_content_blob_deletes
BEFORE DELETE ON content_blobs
FOR EACH ROW
BEGIN
    SELECT RAISE(ABORT, 'Content blobs cannot be deleted. Use soft delete (is_deleted=1).');
END;
CREATE TRIGGER update_file_contents_timestamp
AFTER UPDATE ON file_contents
FOR EACH ROW
BEGIN
    UPDATE file_contents
    SET updated_at = datetime('now')
    WHERE id = NEW.id;
END;
CREATE VIEW shared_files AS
SELECT
    pf.id as file_id,
    pf.component_name,
    pf.file_path,
    ft.type_name,
    p.slug as source_project,
    pf.description,
    pf.owner,
    cb.file_size_bytes,
    cb.original_size_bytes,
    cb.compression,
    (SELECT COUNT(*) FROM shared_file_references sfr WHERE sfr.source_file_id = pf.id) as usage_count,
    pf.created_at,
    pf.updated_at
FROM project_files pf
JOIN projects p ON pf.project_id = p.id
JOIN file_types ft ON pf.file_type_id = ft.id
JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
WHERE pf.is_shared = 1
/* shared_files(file_id,component_name,file_path,type_name,source_project,description,owner,file_size_bytes,original_size_bytes,compression,usage_count,created_at,updated_at) */;
CREATE VIEW file_usage AS
SELECT
    source_pf.component_name,
    ft.type_name,
    source_p.slug as source_project,
    source_pf.file_path as source_path,
    using_p.slug as using_project,
    sfr.alias,
    sfr.linked_at,
    sfr.last_used_at
FROM shared_file_references sfr
JOIN project_files source_pf ON sfr.source_file_id = source_pf.id
JOIN projects source_p ON sfr.source_project_id = source_p.id
JOIN projects using_p ON sfr.using_project_id = using_p.id
JOIN file_types ft ON source_pf.file_type_id = ft.id
ORDER BY source_pf.component_name, using_p.slug
/* file_usage(component_name,type_name,source_project,source_path,using_project,alias,linked_at,last_used_at) */;
CREATE VIEW current_file_contents AS
SELECT
    pf.id as file_id,
    pf.file_path,
    pf.file_name,
    pf.component_name,
    fc.content_hash,
    cb.content_text,
    cb.content_type,
    cb.file_size_bytes,
    cb.original_size_bytes,
    cb.compression,
    CASE
        WHEN cb.compression = 'none' THEN 0
        ELSE CAST((cb.original_size_bytes - cb.file_size_bytes) * 100.0 / cb.original_size_bytes AS INTEGER)
    END as compression_ratio_percent,
    p.slug as project_slug
FROM file_contents fc
JOIN project_files pf ON fc.file_id = pf.id
JOIN projects p ON pf.project_id = p.id
JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
WHERE fc.is_current = 1
/* current_file_contents(file_id,file_path,file_name,component_name,content_hash,content_text,content_type,file_size_bytes,original_size_bytes,compression,compression_ratio_percent,project_slug) */;
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    slug TEXT NOT NULL UNIQUE,
    description TEXT,
    repo_url TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE file_types (
    id INTEGER PRIMARY KEY,
    type_name TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE project_files (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_type_id INTEGER NOT NULL REFERENCES file_types(id),

    -- File identification
    file_path TEXT NOT NULL,          -- Relative path from project root
    file_name TEXT NOT NULL,          -- Just the filename
    component_name TEXT,              -- Logical name (e.g., function name, component name, table name)

    -- Metadata
    description TEXT,
    purpose TEXT,                     -- High-level purpose of this file/component
    owner TEXT,                       -- Team or person responsible
    status TEXT DEFAULT 'active',     -- active, deprecated, experimental, archived

    -- Source control
    last_modified TEXT,               -- Timestamp of last modification
    last_commit_hash TEXT,            -- Git commit hash

    -- Documentation
    documentation_url TEXT,           -- Link to external docs
    inline_documentation TEXT,        -- Extracted comments/docstrings

    -- Complexity metrics
    lines_of_code INTEGER,
    complexity_score REAL,            -- Cyclomatic complexity or similar

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')), is_shared BOOLEAN DEFAULT 0,

    UNIQUE(project_id, file_path)
);
CREATE TABLE file_dependencies (
    id INTEGER PRIMARY KEY,
    parent_file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    dependency_file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    dependency_type TEXT NOT NULL,    -- 'imports', 'calls', 'references', 'extends', 'implements', 'uses_table', 'triggers', 'foreign_key'
    is_hard_dependency BOOLEAN NOT NULL DEFAULT 1,  -- 1 = hard (breaks without it), 0 = soft (optional)

    -- Context about the dependency
    usage_context TEXT,               -- Where/how this dependency is used
    notes TEXT,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(parent_file_id, dependency_file_id, dependency_type),
    CHECK(parent_file_id != dependency_file_id)  -- Can't depend on itself
);
CREATE TABLE sql_objects (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    object_type TEXT NOT NULL,        -- 'table', 'view', 'function', 'procedure', 'trigger', 'index', 'type', 'sequence'
    schema_name TEXT NOT NULL DEFAULT 'public',
    object_name TEXT NOT NULL,

    -- Table-specific
    table_type TEXT,                  -- 'base_table', 'view', 'materialized_view', 'temporary', 'external'
    estimated_row_count INTEGER,

    -- Function-specific
    function_language TEXT,           -- 'plpgsql', 'sql', 'plpython', etc.
    return_type TEXT,
    parameters TEXT,                  -- JSON array of parameter definitions

    -- Performance
    is_indexed BOOLEAN DEFAULT 0,
    has_foreign_keys BOOLEAN DEFAULT 0,

    -- RLS and security
    has_rls_enabled BOOLEAN DEFAULT 0,
    rls_policies TEXT,                -- JSON array of policy definitions

    -- Triggers and constraints
    triggers TEXT,                    -- JSON array of triggers
    constraints TEXT,                 -- JSON array of constraints

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(file_id)
);
CREATE TABLE javascript_components (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    component_type TEXT NOT NULL,     -- 'react_component', 'hook', 'utility', 'service', 'model', 'middleware', 'route'
    is_functional BOOLEAN DEFAULT 1,  -- For React: functional vs class component

    -- Module info
    exports TEXT,                     -- JSON array of exported items
    imports TEXT,                     -- JSON array of imported items

    -- React-specific
    uses_hooks TEXT,                  -- JSON array of hooks used
    props_interface TEXT,             -- TypeScript interface definition
    state_management TEXT,            -- 'redux', 'context', 'zustand', 'recoil', 'local', 'none'

    -- API interactions
    api_endpoints_called TEXT,        -- JSON array of endpoints this component calls

    -- Testing
    has_tests BOOLEAN DEFAULT 0,
    test_file_path TEXT,
    test_coverage_percent REAL,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(file_id)
);
CREATE TABLE edge_functions (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    function_name TEXT NOT NULL,
    runtime TEXT NOT NULL DEFAULT 'deno',  -- 'deno', 'node', 'bun'
    runtime_version TEXT,

    -- HTTP info
    http_methods TEXT,                -- JSON array: ['GET', 'POST', 'PUT', 'DELETE']
    endpoint_path TEXT,               -- URL path where function is served

    -- Dependencies
    npm_dependencies TEXT,            -- JSON object of dependencies
    deno_imports TEXT,                -- JSON array of Deno imports

    -- Environment
    required_env_vars TEXT,           -- JSON array of required env variables
    required_secrets TEXT,            -- JSON array of required secrets

    -- Performance
    max_execution_time_ms INTEGER DEFAULT 30000,
    memory_limit_mb INTEGER DEFAULT 128,

    -- Deployment
    region TEXT,                      -- Deployment region
    cors_config TEXT,                 -- JSON CORS configuration

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(file_id)
);
CREATE TABLE deployment_targets (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    target_name TEXT NOT NULL,        -- 'production', 'staging', 'development', 'preview', 'local'
    target_type TEXT NOT NULL,        -- 'database', 'edge_function', 'static_site', 'container', 'serverless'

    -- Target details
    host TEXT,                        -- Hostname or URL
    region TEXT,                      -- Cloud region
    provider TEXT,                    -- 'supabase', 'vercel', 'aws', 'gcp', 'cloudflare', 'local'

    -- Access
    requires_vpn BOOLEAN DEFAULT 0,
    access_url TEXT,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(project_id, target_name, target_type)
);
CREATE TABLE file_deployments (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    deployment_target_id INTEGER NOT NULL REFERENCES deployment_targets(id) ON DELETE CASCADE,

    -- Deployment instructions
    deploy_command TEXT NOT NULL,     -- Command to deploy this file
    build_command TEXT,               -- Command to build before deployment (if any)
    test_command TEXT,                -- Command to run tests before deployment

    -- Pre/post deployment
    pre_deploy_commands TEXT,         -- JSON array of commands to run before deploy
    post_deploy_commands TEXT,        -- JSON array of commands to run after deploy

    -- Deployment configuration
    deploy_order INTEGER DEFAULT 0,   -- Order in which to deploy (lower = earlier)
    requires_manual_approval BOOLEAN DEFAULT 0,

    -- Environment-specific config
    env_vars_required TEXT,           -- JSON array of required environment variables
    config_file_path TEXT,            -- Path to config file for this deployment

    -- Rollback
    rollback_command TEXT,
    supports_blue_green BOOLEAN DEFAULT 0,

    -- Monitoring
    health_check_url TEXT,
    health_check_command TEXT,

    -- Status tracking
    last_deployed_at TEXT,
    last_deployed_by TEXT,
    last_deployment_status TEXT,      -- 'success', 'failed', 'in_progress', 'rolled_back'
    last_deployment_notes TEXT,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(file_id, deployment_target_id)
);
CREATE TABLE file_tags (
    id INTEGER PRIMARY KEY,
    tag_name TEXT NOT NULL UNIQUE,
    tag_category TEXT,                -- 'feature', 'tech', 'team', 'priority', 'status'
    color TEXT,                       -- Hex color for UI
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE file_tag_assignments (
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES file_tags(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (file_id, tag_id)
);
CREATE TABLE api_endpoints (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    implemented_by_file_id INTEGER REFERENCES project_files(id) ON DELETE SET NULL,

    endpoint_path TEXT NOT NULL,      -- e.g., '/api/users/:id'
    http_method TEXT NOT NULL,        -- GET, POST, PUT, DELETE, PATCH, etc.

    description TEXT,
    request_schema TEXT,              -- JSON schema for request body
    response_schema TEXT,             -- JSON schema for response

    -- Authentication
    requires_auth BOOLEAN DEFAULT 1,
    required_permissions TEXT,        -- JSON array of required permissions/roles

    -- Rate limiting
    rate_limit_rpm INTEGER,           -- Requests per minute

    -- Documentation
    openapi_spec TEXT,                -- OpenAPI/Swagger spec
    example_request TEXT,
    example_response TEXT,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(project_id, endpoint_path, http_method)
);
CREATE TABLE database_migrations (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    migration_file_id INTEGER REFERENCES project_files(id) ON DELETE SET NULL,

    migration_number TEXT NOT NULL,   -- e.g., '001', '20240115_001'
    migration_name TEXT NOT NULL,

    -- Migration details
    applies_to_schema TEXT,
    migration_type TEXT,              -- 'ddl', 'dml', 'seed', 'function', 'view'

    -- Status
    status TEXT DEFAULT 'pending',    -- 'pending', 'applied', 'failed', 'rolled_back'
    applied_at TEXT,
    rolled_back_at TEXT,

    -- Rollback
    has_rollback BOOLEAN DEFAULT 0,
    rollback_sql TEXT,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(project_id, migration_number)
);
CREATE TABLE config_files (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_id INTEGER REFERENCES project_files(id) ON DELETE SET NULL,

    config_type TEXT NOT NULL,        -- 'package_json', 'tsconfig', 'env', 'docker', 'kubernetes', 'terraform', 'nix'
    config_name TEXT NOT NULL,        -- e.g., 'package.json', '.env.production', 'tsconfig.json'

    -- Config details
    config_content TEXT,              -- Full content or JSON representation
    parsed_config TEXT,               -- Parsed/normalized JSON

    -- Dependencies declared
    declares_dependencies TEXT,       -- JSON array of dependencies

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE VIEW files_with_types_view AS
SELECT
    pf.id,
    pf.project_id,
    p.slug AS project_slug,
    pf.file_path,
    pf.file_name,
    pf.component_name,
    ft.type_name,
    ft.category AS file_category,
    pf.description,
    pf.purpose,
    pf.owner,
    pf.status,
    pf.last_modified,
    pf.lines_of_code,
    pf.complexity_score,
    pf.created_at,
    pf.updated_at
FROM project_files pf
JOIN file_types ft ON pf.file_type_id = ft.id
JOIN projects p ON pf.project_id = p.id
/* files_with_types_view(id,project_id,project_slug,file_path,file_name,component_name,type_name,file_category,description,purpose,owner,status,last_modified,lines_of_code,complexity_score,created_at,updated_at) */;
CREATE VIEW file_dependency_graph_view AS
SELECT
    fd.id,
    parent_file.file_path AS parent_file_path,
    parent_file.component_name AS parent_component,
    parent_ft.type_name AS parent_type,
    dep_file.file_path AS dependency_file_path,
    dep_file.component_name AS dependency_component,
    dep_ft.type_name AS dependency_type,
    fd.dependency_type,
    fd.is_hard_dependency,
    fd.usage_context,
    p.slug AS project_slug
FROM file_dependencies fd
JOIN project_files parent_file ON fd.parent_file_id = parent_file.id
JOIN project_files dep_file ON fd.dependency_file_id = dep_file.id
JOIN file_types parent_ft ON parent_file.file_type_id = parent_ft.id
JOIN file_types dep_ft ON dep_file.file_type_id = dep_ft.id
JOIN projects p ON parent_file.project_id = p.id
/* file_dependency_graph_view(id,parent_file_path,parent_component,parent_type,dependency_file_path,dependency_component,dependency_type,"dependency_type:1",is_hard_dependency,usage_context,project_slug) */;
CREATE VIEW deployment_readiness_view AS
SELECT
    pf.id AS file_id,
    pf.file_path,
    pf.component_name,
    dt.target_name,
    dt.target_type,
    fd_deploy.deploy_command,
    fd_deploy.last_deployed_at,
    fd_deploy.last_deployment_status,
    CASE
        WHEN fd_deploy.last_deployed_at IS NULL THEN 'never_deployed'
        WHEN datetime(fd_deploy.last_deployed_at) < datetime(pf.last_modified) THEN 'stale'
        ELSE 'up_to_date'
    END AS deployment_freshness,
    p.slug AS project_slug
FROM project_files pf
JOIN projects p ON pf.project_id = p.id
LEFT JOIN file_deployments fd_deploy ON pf.id = fd_deploy.file_id
LEFT JOIN deployment_targets dt ON fd_deploy.deployment_target_id = dt.id
/* deployment_readiness_view(file_id,file_path,component_name,target_name,target_type,deploy_command,last_deployed_at,last_deployment_status,deployment_freshness,project_slug) */;
CREATE VIEW sql_objects_view AS
SELECT
    so.id,
    so.object_type,
    so.schema_name,
    so.object_name,
    so.function_language,
    so.has_rls_enabled,
    pf.file_path,
    pf.component_name,
    pf.description,
    pf.status,
    p.slug AS project_slug
FROM sql_objects so
JOIN project_files pf ON so.file_id = pf.id
JOIN projects p ON pf.project_id = p.id
/* sql_objects_view(id,object_type,schema_name,object_name,function_language,has_rls_enabled,file_path,component_name,description,status,project_slug) */;
CREATE VIEW api_endpoints_view AS
SELECT
    ae.id,
    ae.endpoint_path,
    ae.http_method,
    ae.description,
    ae.requires_auth,
    pf.file_path AS implemented_by,
    pf.component_name,
    p.slug AS project_slug
FROM api_endpoints ae
JOIN projects p ON ae.project_id = p.id
LEFT JOIN project_files pf ON ae.implemented_by_file_id = pf.id
/* api_endpoints_view(id,endpoint_path,http_method,description,requires_auth,implemented_by,component_name,project_slug) */;
CREATE INDEX idx_project_files_project_id ON project_files(project_id);
CREATE INDEX idx_project_files_file_type_id ON project_files(file_type_id);
CREATE INDEX idx_project_files_component_name ON project_files(component_name);
CREATE INDEX idx_project_files_status ON project_files(status);
CREATE INDEX idx_project_files_project_path ON project_files(project_id, file_path);
CREATE INDEX idx_file_dependencies_parent ON file_dependencies(parent_file_id);
CREATE INDEX idx_file_dependencies_dependency ON file_dependencies(dependency_file_id);
CREATE INDEX idx_file_dependencies_type ON file_dependencies(dependency_type);
CREATE INDEX idx_sql_objects_file_id ON sql_objects(file_id);
CREATE INDEX idx_sql_objects_object_name ON sql_objects(object_name);
CREATE INDEX idx_sql_objects_schema_name ON sql_objects(schema_name);
CREATE INDEX idx_javascript_components_file_id ON javascript_components(file_id);
CREATE INDEX idx_edge_functions_file_id ON edge_functions(file_id);
CREATE INDEX idx_file_deployments_file_id ON file_deployments(file_id);
CREATE INDEX idx_file_deployments_target_id ON file_deployments(deployment_target_id);
CREATE INDEX idx_file_deployments_order ON file_deployments(deploy_order);
CREATE INDEX idx_api_endpoints_project_id ON api_endpoints(project_id);
CREATE INDEX idx_api_endpoints_file_id ON api_endpoints(implemented_by_file_id);
CREATE TRIGGER update_project_files_updated_at
AFTER UPDATE ON project_files
FOR EACH ROW
BEGIN
    UPDATE project_files SET updated_at = datetime('now') WHERE id = NEW.id;
END;
CREATE TRIGGER update_sql_objects_updated_at
AFTER UPDATE ON sql_objects
FOR EACH ROW
BEGIN
    UPDATE sql_objects SET updated_at = datetime('now') WHERE id = NEW.id;
END;
CREATE TRIGGER update_javascript_components_updated_at
AFTER UPDATE ON javascript_components
FOR EACH ROW
BEGIN
    UPDATE javascript_components SET updated_at = datetime('now') WHERE id = NEW.id;
END;
CREATE TRIGGER update_edge_functions_updated_at
AFTER UPDATE ON edge_functions
FOR EACH ROW
BEGIN
    UPDATE edge_functions SET updated_at = datetime('now') WHERE id = NEW.id;
END;
CREATE TRIGGER update_deployment_targets_updated_at
AFTER UPDATE ON deployment_targets
FOR EACH ROW
BEGIN
    UPDATE deployment_targets SET updated_at = datetime('now') WHERE id = NEW.id;
END;
CREATE TRIGGER update_file_deployments_updated_at
AFTER UPDATE ON file_deployments
FOR EACH ROW
BEGIN
    UPDATE file_deployments SET updated_at = datetime('now') WHERE id = NEW.id;
END;
CREATE TRIGGER update_api_endpoints_updated_at
AFTER UPDATE ON api_endpoints
FOR EACH ROW
BEGIN
    UPDATE api_endpoints SET updated_at = datetime('now') WHERE id = NEW.id;
END;
CREATE TRIGGER update_config_files_updated_at
AFTER UPDATE ON config_files
FOR EACH ROW
BEGIN
    UPDATE config_files SET updated_at = datetime('now') WHERE id = NEW.id;
END;
CREATE TABLE file_versions (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    -- Version identification
    version_number INTEGER NOT NULL,  -- Auto-incrementing version number
    version_tag TEXT,                 -- Optional tag (e.g., 'v1.0.0', 'release')

    -- Content storage
    content_text TEXT,
    content_blob BLOB,
    content_type TEXT NOT NULL,
    encoding TEXT DEFAULT 'utf-8',

    -- Metadata
    file_size_bytes INTEGER NOT NULL,
    line_count INTEGER,
    hash_sha256 TEXT NOT NULL,

    -- Version control metadata
    author TEXT,                      -- Who made this version
    commit_message TEXT,              -- Description of changes
    parent_version_id INTEGER REFERENCES file_versions(id),  -- Previous version

    -- Git integration (optional)
    git_commit_hash TEXT,             -- Associated git commit
    git_branch TEXT,                  -- Git branch

    -- Change statistics
    lines_added INTEGER,
    lines_removed INTEGER,
    lines_modified INTEGER,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(file_id, version_number),
    CHECK(version_number > 0)
);
CREATE TABLE file_diffs (
    id INTEGER PRIMARY KEY,
    from_version_id INTEGER NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,
    to_version_id INTEGER NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,

    -- Diff format
    diff_format TEXT NOT NULL DEFAULT 'unified',  -- 'unified', 'context', 'ed'
    diff_content TEXT NOT NULL,       -- Actual diff content

    -- Statistics
    chunks_count INTEGER,             -- Number of diff chunks
    lines_added INTEGER,
    lines_removed INTEGER,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(from_version_id, to_version_id)
);
CREATE TABLE file_change_events (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    version_id INTEGER REFERENCES file_versions(id) ON DELETE SET NULL,

    event_type TEXT NOT NULL,         -- 'created', 'modified', 'deleted', 'restored', 'renamed'

    -- Change details
    old_content_hash TEXT,
    new_content_hash TEXT,
    old_file_path TEXT,
    new_file_path TEXT,

    -- Who and when
    author TEXT,
    author_email TEXT,
    event_timestamp TEXT NOT NULL DEFAULT (datetime('now')),

    -- Context
    commit_message TEXT,
    git_commit_hash TEXT,
    git_branch TEXT,

    -- Additional metadata
    metadata TEXT                     -- JSON for additional context
);
CREATE TABLE version_tags (
    id INTEGER PRIMARY KEY,
    version_id INTEGER NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,

    tag_name TEXT NOT NULL,           -- e.g., 'production', 'stable', 'v1.0'
    tag_type TEXT NOT NULL,           -- 'release', 'snapshot', 'milestone', 'backup'
    description TEXT,

    created_by TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(version_id, tag_name)
);
CREATE TABLE file_snapshots (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    snapshot_name TEXT NOT NULL,
    snapshot_reason TEXT,             -- 'daily', 'before-deploy', 'milestone', 'manual'

    -- Snapshot content
    content_text TEXT,
    content_blob BLOB,
    content_type TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    hash_sha256 TEXT NOT NULL,

    -- Reference to version
    version_id INTEGER REFERENCES file_versions(id),

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(file_id, snapshot_name)
);
CREATE VIEW current_file_contents_view AS
SELECT
    pf.id AS file_id,
    pf.file_path,
    pf.file_name,
    pf.component_name,
    ft.type_name,
    fc.content_text,
    fc.content_type,
    fc.file_size_bytes,
    fc.line_count,
    fc.hash_sha256,
    fc.updated_at,
    p.slug AS project_slug
FROM file_contents fc
JOIN project_files pf ON fc.file_id = pf.id
JOIN file_types ft ON pf.file_type_id = ft.id
JOIN projects p ON pf.project_id = p.id
WHERE fc.is_current = 1;
CREATE VIEW file_version_history_view AS
SELECT
    fv.id AS version_id,
    pf.id AS file_id,
    pf.file_path,
    pf.component_name,
    fv.version_number,
    fv.version_tag,
    fv.author,
    fv.commit_message,
    fv.hash_sha256,
    fv.file_size_bytes,
    fv.lines_added,
    fv.lines_removed,
    fv.git_commit_hash,
    fv.git_branch,
    fv.created_at,
    p.slug AS project_slug
FROM file_versions fv
JOIN project_files pf ON fv.file_id = pf.id
JOIN projects p ON pf.project_id = p.id
ORDER BY fv.file_id, fv.version_number DESC
/* file_version_history_view(version_id,file_id,file_path,component_name,version_number,version_tag,author,commit_message,hash_sha256,file_size_bytes,lines_added,lines_removed,git_commit_hash,git_branch,created_at,project_slug) */;
CREATE VIEW file_change_timeline_view AS
SELECT
    fce.id,
    pf.file_path,
    pf.component_name,
    fce.event_type,
    fce.author,
    fce.commit_message,
    fce.event_timestamp,
    fce.git_commit_hash,
    fce.old_content_hash,
    fce.new_content_hash,
    p.slug AS project_slug
FROM file_change_events fce
JOIN project_files pf ON fce.file_id = pf.id
JOIN projects p ON pf.project_id = p.id
ORDER BY fce.event_timestamp DESC
/* file_change_timeline_view(id,file_path,component_name,event_type,author,commit_message,event_timestamp,git_commit_hash,old_content_hash,new_content_hash,project_slug) */;
CREATE VIEW latest_file_versions_view AS
SELECT
    pf.id AS file_id,
    pf.file_path,
    pf.component_name,
    MAX(fv.version_number) AS latest_version,
    fv.author AS last_author,
    fv.commit_message AS last_commit_message,
    fv.created_at AS last_updated,
    fv.hash_sha256,
    p.slug AS project_slug
FROM project_files pf
LEFT JOIN file_versions fv ON pf.id = fv.file_id
JOIN projects p ON pf.project_id = p.id
GROUP BY pf.id
/* latest_file_versions_view(file_id,file_path,component_name,latest_version,last_author,last_commit_message,last_updated,hash_sha256,project_slug) */;
CREATE VIEW file_change_stats_view AS
SELECT
    pf.id AS file_id,
    pf.file_path,
    pf.component_name,
    COUNT(DISTINCT fce.id) AS total_changes,
    COUNT(DISTINCT fv.id) AS total_versions,
    COUNT(DISTINCT fce.author) AS unique_authors,
    MIN(fce.event_timestamp) AS first_change,
    MAX(fce.event_timestamp) AS last_change,
    SUM(fv.lines_added) AS total_lines_added,
    SUM(fv.lines_removed) AS total_lines_removed,
    p.slug AS project_slug
FROM project_files pf
LEFT JOIN file_change_events fce ON pf.id = fce.file_id
LEFT JOIN file_versions fv ON pf.id = fv.file_id
JOIN projects p ON pf.project_id = p.id
GROUP BY pf.id
/* file_change_stats_view(file_id,file_path,component_name,total_changes,total_versions,unique_authors,first_change,last_change,total_lines_added,total_lines_removed,project_slug) */;
CREATE INDEX idx_file_versions_file_id ON file_versions(file_id);
CREATE INDEX idx_file_versions_number ON file_versions(file_id, version_number);
CREATE INDEX idx_file_versions_hash ON file_versions(hash_sha256);
CREATE INDEX idx_file_versions_author ON file_versions(author);
CREATE INDEX idx_file_versions_git_commit ON file_versions(git_commit_hash);
CREATE INDEX idx_file_diffs_versions ON file_diffs(from_version_id, to_version_id);
CREATE INDEX idx_file_change_events_file_id ON file_change_events(file_id);
CREATE INDEX idx_file_change_events_timestamp ON file_change_events(event_timestamp);
CREATE INDEX idx_file_change_events_author ON file_change_events(author);
CREATE INDEX idx_file_change_events_git_commit ON file_change_events(git_commit_hash);
CREATE INDEX idx_version_tags_version_id ON version_tags(version_id);
CREATE INDEX idx_version_tags_name ON version_tags(tag_name);
CREATE INDEX idx_file_snapshots_file_id ON file_snapshots(file_id);
CREATE INDEX idx_file_snapshots_name ON file_snapshots(snapshot_name);
CREATE TRIGGER update_file_contents_updated_at
AFTER UPDATE ON file_contents
FOR EACH ROW
BEGIN
    UPDATE file_contents SET updated_at = datetime('now') WHERE id = NEW.id;
END;
CREATE TRIGGER enforce_single_current_version
BEFORE INSERT ON file_contents
FOR EACH ROW
WHEN NEW.is_current = 1
BEGIN
    UPDATE file_contents SET is_current = 0 WHERE file_id = NEW.file_id AND is_current = 1;
END;
CREATE TRIGGER log_file_version_change
AFTER INSERT ON file_versions
FOR EACH ROW
BEGIN
    INSERT INTO file_change_events (
        file_id, version_id, event_type,
        new_content_hash, author, commit_message,
        git_commit_hash, git_branch
    )
    VALUES (
        NEW.file_id, NEW.id, 'modified',
        NEW.hash_sha256, NEW.author, NEW.commit_message,
        NEW.git_commit_hash, NEW.git_branch
    );
END;
CREATE INDEX idx_project_files_shared ON project_files(is_shared);
CREATE TABLE code_symbols (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Symbol identity
    symbol_type TEXT NOT NULL,  -- 'function', 'class', 'method', 'constant', 'type', 'interface'
    symbol_name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,  -- e.g., 'MyClass.myMethod', 'myModule.myFunction'

    -- Scope (only track symbols that cross file boundaries)
    scope TEXT NOT NULL,  -- 'exported', 'public_api', 'entry_point'
    export_type TEXT,  -- 'default', 'named', 'namespace', 'class_method'

    -- Location
    start_line INTEGER,
    end_line INTEGER,
    start_column INTEGER,
    end_column INTEGER,

    -- Metadata
    docstring TEXT,

    -- Type information (for TypeScript, Python type hints, etc.)
    return_type TEXT,
    parameters TEXT,  -- JSON array: [{"name": "x", "type": "int", "optional": false}, ...]

    -- Complexity metrics (ONLY for exported symbols worth tracking)
    cyclomatic_complexity INTEGER,
    cognitive_complexity INTEGER,
    num_dependents INTEGER DEFAULT 0,  -- Cached count for quick queries

    -- Indexing metadata
    indexed_at TEXT NOT NULL DEFAULT (datetime('now')),
    content_hash TEXT,  -- Hash of symbol content for change detection

    UNIQUE(file_id, qualified_name),

    -- Only track exported/public symbols
    CHECK(scope IN ('exported', 'public_api', 'entry_point'))
);
CREATE TABLE code_symbol_dependencies (
    id INTEGER PRIMARY KEY,
    caller_symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    called_symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,

    dependency_type TEXT NOT NULL,  -- 'calls', 'imports', 'extends', 'implements', 'instantiates'

    -- Call context
    call_line INTEGER,  -- Where in caller the call occurs
    is_conditional BOOLEAN DEFAULT 0,  -- Inside if/loop/try
    call_depth INTEGER DEFAULT 1,  -- Nesting depth

    -- Impact metadata
    is_critical_path BOOLEAN DEFAULT 0,  -- Part of main execution flow
    confidence_score REAL DEFAULT 1.0,  -- 0.0-1.0, lower for dynamic calls

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(caller_symbol_id, called_symbol_id, dependency_type)
);
CREATE TABLE execution_flows (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    entry_symbol_id INTEGER NOT NULL REFERENCES code_symbols(id),
    flow_name TEXT NOT NULL,  -- e.g., 'user_login_flow'

    -- Flow metadata
    flow_type TEXT,  -- 'http_endpoint', 'cli_command', 'background_job', 'event_handler'
    description TEXT,

    -- Summary statistics
    max_depth INTEGER,
    total_symbols INTEGER,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(project_id, flow_name)
);
CREATE TABLE execution_flow_steps (
    id INTEGER PRIMARY KEY,
    flow_id INTEGER NOT NULL REFERENCES execution_flows(id) ON DELETE CASCADE,
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,

    step_order INTEGER NOT NULL,  -- 0-indexed position in flow
    depth INTEGER NOT NULL,  -- Call stack depth at this step

    UNIQUE(flow_id, step_order)
);
CREATE TABLE impact_transitive_cache (
    id INTEGER PRIMARY KEY,
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    affected_symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,

    direction TEXT NOT NULL,  -- 'dependent' (who depends on me) or 'dependency' (what I depend on)
    depth INTEGER NOT NULL,  -- Distance: 1 = direct (but use code_symbol_dependencies), 2+ = transitive
    confidence_score REAL DEFAULT 1.0,  -- Aggregated confidence along path (multiply edge confidences)

    -- Path information (for debugging and explanation)
    path_through TEXT,  -- JSON array: [symbol_id1, symbol_id2, ...] showing traversal path

    computed_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(symbol_id, affected_symbol_id, direction),
    CHECK(depth > 0),
    CHECK(direction IN ('dependent', 'dependency'))
);
CREATE TABLE symbol_deployment_impact (
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    deployment_target_id INTEGER NOT NULL REFERENCES deployment_targets(id) ON DELETE CASCADE,

    impact_type TEXT NOT NULL,  -- 'direct' (symbol deployed here) or 'transitive' (dependencies deployed)
    confidence_score REAL DEFAULT 1.0,

    computed_at TEXT NOT NULL DEFAULT (datetime('now')),

    PRIMARY KEY (symbol_id, deployment_target_id)
);
CREATE TABLE symbol_api_endpoint_impact (
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    endpoint_id INTEGER NOT NULL REFERENCES api_endpoints(id) ON DELETE CASCADE,

    impact_type TEXT NOT NULL,  -- 'implements' (symbol handles endpoint) or 'called_by' (endpoint calls symbol)

    PRIMARY KEY (symbol_id, endpoint_id)
);
CREATE TABLE impact_summary_cache (
    symbol_id INTEGER PRIMARY KEY REFERENCES code_symbols(id) ON DELETE CASCADE,

    -- Aggregate statistics
    total_affected_symbols INTEGER DEFAULT 0,
    total_affected_files INTEGER DEFAULT 0,
    max_impact_depth INTEGER DEFAULT 0,

    num_affected_deployments INTEGER DEFAULT 0,
    num_affected_endpoints INTEGER DEFAULT 0,

    -- Change detection
    last_computed_at TEXT NOT NULL DEFAULT (datetime('now')),
    content_hash TEXT  -- Invalidate cache when symbol changes
);
CREATE TABLE code_clusters (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    cluster_name TEXT NOT NULL,
    cluster_type TEXT,  -- 'feature', 'module', 'layer', 'utility'

    -- Cluster metadata
    description TEXT,
    cohesion_score REAL,  -- 0.0-1.0, higher = tighter coupling within cluster

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(project_id, cluster_name)
);
CREATE TABLE code_cluster_members (
    cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,

    membership_strength REAL DEFAULT 1.0,  -- 0.0-1.0, confidence that symbol belongs to cluster

    PRIMARY KEY (cluster_id, symbol_id)
);
CREATE TABLE code_cluster_files (
    cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    symbol_count INTEGER DEFAULT 1,  -- How many symbols from this file are in cluster

    PRIMARY KEY (cluster_id, file_id)
);
CREATE TABLE code_cluster_dependencies (
    cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,
    depends_on_cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,

    dependency_strength REAL,  -- Number of inter-cluster edges / total edges
    edge_count INTEGER DEFAULT 1,  -- Number of symbol dependencies between clusters

    PRIMARY KEY (cluster_id, depends_on_cluster_id),
    CHECK(cluster_id != depends_on_cluster_id)
);
CREATE TABLE code_search_index (
    id INTEGER PRIMARY KEY,
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,

    -- Searchable content
    search_text TEXT NOT NULL,  -- Symbol name + docstring + signature

    -- Semantic embedding (stored as JSON array of floats - keep as JSON, never queried individually)
    embedding TEXT,  -- JSON: [0.123, -0.456, ...]
    embedding_model TEXT,  -- 'text-embedding-ada-002', 'nomic-embed-text', etc.

    indexed_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(symbol_id)
);
CREATE VIRTUAL TABLE code_search_fts USING fts5(
    symbol_id UNINDEXED,
    qualified_name,
    docstring,
    content=code_search_index,
    content_rowid=symbol_id
)
/* code_search_fts(symbol_id,qualified_name,docstring) */;
CREATE TABLE IF NOT EXISTS 'code_search_fts_data'(id INTEGER PRIMARY KEY, block BLOB);
CREATE TABLE IF NOT EXISTS 'code_search_fts_idx'(segid, term, pgno, PRIMARY KEY(segid, term)) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS 'code_search_fts_docsize'(id INTEGER PRIMARY KEY, sz BLOB);
CREATE TABLE IF NOT EXISTS 'code_search_fts_config'(k PRIMARY KEY, v) WITHOUT ROWID;
CREATE INDEX idx_code_symbols_file ON code_symbols(file_id);
CREATE INDEX idx_code_symbols_project ON code_symbols(project_id);
CREATE INDEX idx_code_symbols_scope ON code_symbols(scope);
CREATE INDEX idx_code_symbols_type ON code_symbols(symbol_type);
CREATE INDEX idx_code_symbols_name ON code_symbols(symbol_name);
CREATE INDEX idx_code_symbols_dependents ON code_symbols(num_dependents DESC);
CREATE INDEX idx_symbol_deps_caller ON code_symbol_dependencies(caller_symbol_id);
CREATE INDEX idx_symbol_deps_called ON code_symbol_dependencies(called_symbol_id);
CREATE INDEX idx_symbol_deps_type ON code_symbol_dependencies(dependency_type);
CREATE INDEX idx_symbol_deps_confidence ON code_symbol_dependencies(confidence_score DESC);
CREATE INDEX idx_transitive_cache_symbol ON impact_transitive_cache(symbol_id, direction);
CREATE INDEX idx_transitive_cache_affected ON impact_transitive_cache(affected_symbol_id);
CREATE INDEX idx_transitive_cache_depth ON impact_transitive_cache(depth);
CREATE INDEX idx_transitive_cache_direction_depth ON impact_transitive_cache(direction, depth);
CREATE INDEX idx_symbol_deployment_symbol ON symbol_deployment_impact(symbol_id);
CREATE INDEX idx_symbol_deployment_target ON symbol_deployment_impact(deployment_target_id);
CREATE INDEX idx_symbol_endpoint_symbol ON symbol_api_endpoint_impact(symbol_id);
CREATE INDEX idx_symbol_endpoint ON symbol_api_endpoint_impact(endpoint_id);
CREATE INDEX idx_cluster_members_cluster ON code_cluster_members(cluster_id);
CREATE INDEX idx_cluster_members_symbol ON code_cluster_members(symbol_id);
CREATE INDEX idx_cluster_files_cluster ON code_cluster_files(cluster_id);
CREATE INDEX idx_cluster_files_file ON code_cluster_files(file_id);
CREATE INDEX idx_cluster_deps_cluster ON code_cluster_dependencies(cluster_id);
CREATE INDEX idx_cluster_deps_depends ON code_cluster_dependencies(depends_on_cluster_id);
CREATE INDEX idx_flow_steps_flow ON execution_flow_steps(flow_id);
CREATE INDEX idx_flow_steps_symbol ON execution_flow_steps(symbol_id);
CREATE INDEX idx_flow_steps_order ON execution_flow_steps(flow_id, step_order);
CREATE VIEW dependency_graph_with_symbols_view AS
SELECT
    parent_sym.qualified_name AS caller,
    parent_sym.symbol_type AS caller_type,
    parent_file.file_path AS caller_file,
    dep_sym.qualified_name AS called,
    dep_sym.symbol_type AS called_type,
    dep_file.file_path AS called_file,
    csd.dependency_type,
    csd.confidence_score,
    csd.is_critical_path,
    p.slug AS project_slug
FROM code_symbol_dependencies csd
JOIN code_symbols parent_sym ON csd.caller_symbol_id = parent_sym.id
JOIN code_symbols dep_sym ON csd.called_symbol_id = dep_sym.id
JOIN project_files parent_file ON parent_sym.file_id = parent_file.id
JOIN project_files dep_file ON dep_sym.file_id = dep_file.id
JOIN projects p ON parent_sym.project_id = p.id
/* dependency_graph_with_symbols_view(caller,caller_type,caller_file,called,called_type,called_file,dependency_type,confidence_score,is_critical_path,project_slug) */;
CREATE VIEW impact_summary_view AS
SELECT
    s.id AS symbol_id,
    s.qualified_name,
    s.symbol_type,
    pf.file_path,
    isc.total_affected_symbols,
    isc.total_affected_files,
    isc.max_impact_depth,
    isc.num_affected_deployments,
    isc.num_affected_endpoints,
    isc.last_computed_at,
    p.slug AS project_slug
FROM code_symbols s
JOIN project_files pf ON s.file_id = pf.id
JOIN projects p ON s.project_id = p.id
LEFT JOIN impact_summary_cache isc ON s.id = isc.symbol_id
/* impact_summary_view(symbol_id,qualified_name,symbol_type,file_path,total_affected_symbols,total_affected_files,max_impact_depth,num_affected_deployments,num_affected_endpoints,last_computed_at,project_slug) */;
CREATE VIEW symbol_deployments_view AS
SELECT
    s.qualified_name,
    s.symbol_type,
    dt.target_name,
    dt.target_type,
    dt.provider,
    sdi.impact_type,
    sdi.confidence_score,
    p.slug AS project_slug
FROM symbol_deployment_impact sdi
JOIN code_symbols s ON sdi.symbol_id = s.id
JOIN deployment_targets dt ON sdi.deployment_target_id = dt.id
JOIN projects p ON s.project_id = p.id
/* symbol_deployments_view(qualified_name,symbol_type,target_name,target_type,provider,impact_type,confidence_score,project_slug) */;
CREATE VIEW symbol_endpoints_view AS
SELECT
    s.qualified_name,
    s.symbol_type,
    ae.endpoint_path,
    ae.http_method,
    saei.impact_type,
    p.slug AS project_slug
FROM symbol_api_endpoint_impact saei
JOIN code_symbols s ON saei.symbol_id = s.id
JOIN api_endpoints ae ON saei.endpoint_id = ae.id
JOIN projects p ON s.project_id = p.id
/* symbol_endpoints_view(qualified_name,symbol_type,endpoint_path,http_method,impact_type,project_slug) */;
CREATE VIEW cluster_members_view AS
SELECT
    cc.cluster_name,
    cc.cluster_type,
    cc.cohesion_score,
    s.qualified_name AS member_symbol,
    s.symbol_type,
    ccm.membership_strength,
    pf.file_path,
    p.slug AS project_slug
FROM code_cluster_members ccm
JOIN code_clusters cc ON ccm.cluster_id = cc.id
JOIN code_symbols s ON ccm.symbol_id = s.id
JOIN project_files pf ON s.file_id = pf.id
JOIN projects p ON cc.project_id = p.id
/* cluster_members_view(cluster_name,cluster_type,cohesion_score,member_symbol,symbol_type,membership_strength,file_path,project_slug) */;
CREATE VIEW cluster_dependency_graph_view AS
SELECT
    parent_cluster.cluster_name AS cluster,
    dep_cluster.cluster_name AS depends_on,
    ccd.dependency_strength,
    ccd.edge_count,
    p.slug AS project_slug
FROM code_cluster_dependencies ccd
JOIN code_clusters parent_cluster ON ccd.cluster_id = parent_cluster.id
JOIN code_clusters dep_cluster ON ccd.depends_on_cluster_id = dep_cluster.id
JOIN projects p ON parent_cluster.project_id = p.id
/* cluster_dependency_graph_view(cluster,depends_on,dependency_strength,edge_count,project_slug) */;
CREATE VIEW execution_flows_with_steps_view AS
SELECT
    ef.flow_name,
    ef.flow_type,
    entry_sym.qualified_name AS entry_point,
    entry_file.file_path AS entry_file,
    efs.step_order,
    efs.depth AS call_depth,
    step_sym.qualified_name AS step_symbol,
    ef.total_symbols,
    p.slug AS project_slug
FROM execution_flows ef
JOIN code_symbols entry_sym ON ef.entry_symbol_id = entry_sym.id
JOIN project_files entry_file ON entry_sym.file_id = entry_file.id
JOIN projects p ON ef.project_id = p.id
LEFT JOIN execution_flow_steps efs ON ef.id = efs.flow_id
LEFT JOIN code_symbols step_sym ON efs.symbol_id = step_sym.id
ORDER BY ef.id, efs.step_order
/* execution_flows_with_steps_view(flow_name,flow_type,entry_point,entry_file,step_order,call_depth,step_symbol,total_symbols,project_slug) */;
CREATE VIEW transitive_dependents_view AS
SELECT
    s.qualified_name AS symbol,
    s.symbol_type,
    affected_sym.qualified_name AS dependent,
    affected_sym.symbol_type AS dependent_type,
    itc.depth,
    itc.confidence_score,
    p.slug AS project_slug
FROM impact_transitive_cache itc
JOIN code_symbols s ON itc.symbol_id = s.id
JOIN code_symbols affected_sym ON itc.affected_symbol_id = affected_sym.id
JOIN projects p ON s.project_id = p.id
WHERE itc.direction = 'dependent'
ORDER BY itc.depth, s.qualified_name
/* transitive_dependents_view(symbol,symbol_type,dependent,dependent_type,depth,confidence_score,project_slug) */;
CREATE TABLE deployment_scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug TEXT NOT NULL,
    script_path TEXT NOT NULL,
    description TEXT,
    enabled BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')), documentation TEXT,
    UNIQUE(project_slug)
);
CREATE INDEX idx_deployment_scripts_project ON deployment_scripts(project_slug);
CREATE INDEX idx_deployment_scripts_enabled ON deployment_scripts(enabled);
CREATE TRIGGER update_deployment_scripts_timestamp
AFTER UPDATE ON deployment_scripts
BEGIN
    UPDATE deployment_scripts SET updated_at = datetime('now') WHERE id = NEW.id;
END;
CREATE TABLE deployment_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    target TEXT NOT NULL,  -- staging, production, etc.
    deployed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    deployed_by TEXT,  -- username or 'system'
    status TEXT NOT NULL CHECK(status IN ('in_progress', 'success', 'failed', 'rolled_back')),
    exit_code INTEGER,
    deployment_hash TEXT,  -- Content hash from cathedral package
    duration_seconds REAL,
    work_dir TEXT,  -- Path to deployment directory
    notes TEXT,  -- Error messages or deployment notes

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE INDEX idx_deployment_history_project ON deployment_history(project_id);
CREATE INDEX idx_deployment_history_target ON deployment_history(target);
CREATE INDEX idx_deployment_history_status ON deployment_history(status);
CREATE INDEX idx_deployment_history_deployed_at ON deployment_history(deployed_at);
CREATE TABLE deployment_health_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id INTEGER NOT NULL,
    check_type TEXT NOT NULL,  -- 'http', 'database', 'edge_function', 'custom'
    check_name TEXT NOT NULL,
    checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL CHECK(status IN ('pass', 'fail', 'skip', 'timeout')),
    response_time_ms INTEGER,
    endpoint TEXT,  -- URL or connection string checked
    status_code INTEGER,  -- HTTP status code if applicable
    error_message TEXT,
    details TEXT,  -- JSON with additional check details

    FOREIGN KEY (deployment_id) REFERENCES deployment_history(id) ON DELETE CASCADE
);
CREATE INDEX idx_health_checks_deployment ON deployment_health_checks(deployment_id);
CREATE INDEX idx_health_checks_type ON deployment_health_checks(check_type);
CREATE INDEX idx_health_checks_status ON deployment_health_checks(status);
CREATE TABLE deployment_environment_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id INTEGER NOT NULL,
    var_name TEXT NOT NULL,
    var_value TEXT,

    FOREIGN KEY (deployment_id) REFERENCES deployment_history(id) ON DELETE CASCADE
);
CREATE INDEX idx_deployment_env_snapshot ON deployment_environment_snapshot(deployment_id);
CREATE VIEW latest_deployments AS
SELECT
    dh.*,
    p.slug as project_slug,
    p.name as project_name
FROM deployment_history dh
JOIN projects p ON dh.project_id = p.id
WHERE dh.id IN (
    SELECT MAX(id)
    FROM deployment_history
    GROUP BY project_id, target
)
/* latest_deployments(id,project_id,target,deployed_at,deployed_by,status,exit_code,deployment_hash,duration_seconds,work_dir,notes,project_slug,project_name) */;
CREATE VIEW deployment_stats AS
SELECT
    p.slug as project_slug,
    dh.target,
    COUNT(*) as total_deployments,
    SUM(CASE WHEN dh.status = 'success' THEN 1 ELSE 0 END) as successful_deployments,
    SUM(CASE WHEN dh.status = 'failed' THEN 1 ELSE 0 END) as failed_deployments,
    AVG(dh.duration_seconds) as avg_duration_seconds,
    MAX(dh.deployed_at) as last_deployed_at
FROM deployment_history dh
JOIN projects p ON dh.project_id = p.id
GROUP BY p.id, dh.target
/* deployment_stats(project_slug,target,total_deployments,successful_deployments,failed_deployments,avg_duration_seconds,last_deployed_at) */;
CREATE INDEX idx_deployment_scripts_has_docs
ON deployment_scripts(project_slug) WHERE documentation IS NOT NULL;
