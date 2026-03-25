-- ============================================================================
-- TEMPLEDB FILE TRACKING SCHEMA EXTENSION
-- ============================================================================
-- This schema extends the existing templedb SQLite database to track all
-- project files, their dependencies, deployment information, and metadata.
-- ============================================================================

-- File Types Lookup Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS file_types (
    id INTEGER PRIMARY KEY,
    type_name TEXT NOT NULL UNIQUE,  -- e.g., 'sql_table', 'plpgsql_function', 'javascript', 'jsx_component', 'edge_function'
    category TEXT NOT NULL,           -- e.g., 'database', 'frontend', 'backend', 'infrastructure'
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Core Project Files Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS project_files (
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
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(project_id, file_path)
);

-- File Dependencies (Many-to-Many)
-- ============================================================================
CREATE TABLE IF NOT EXISTS file_dependencies (
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

-- SQL Objects Metadata
-- ============================================================================
CREATE TABLE IF NOT EXISTS sql_objects (
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

-- JavaScript/TypeScript Components Metadata
-- ============================================================================
CREATE TABLE IF NOT EXISTS javascript_components (
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

-- Edge Functions (Supabase/Deno) Metadata
-- ============================================================================
CREATE TABLE IF NOT EXISTS edge_functions (
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

-- Deployment Targets
-- ============================================================================
CREATE TABLE IF NOT EXISTS deployment_targets (
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

-- File Deployments (How to deploy each file)
-- ============================================================================
CREATE TABLE IF NOT EXISTS file_deployments (
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

-- File Tags (Flexible categorization)
-- ============================================================================
CREATE TABLE IF NOT EXISTS file_tags (
    id INTEGER PRIMARY KEY,
    tag_name TEXT NOT NULL UNIQUE,
    tag_category TEXT,                -- 'feature', 'tech', 'team', 'priority', 'status'
    color TEXT,                       -- Hex color for UI
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS file_tag_assignments (
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES file_tags(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (file_id, tag_id)
);

-- API Endpoints Registry
-- ============================================================================
CREATE TABLE IF NOT EXISTS api_endpoints (
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

-- Database Migrations Registry
-- ============================================================================
CREATE TABLE IF NOT EXISTS database_migrations (
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

-- Configuration Files
-- ============================================================================
CREATE TABLE IF NOT EXISTS config_files (
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

-- ============================================================================
-- VIEWS FOR COMMON QUERIES
-- ============================================================================

-- Complete file information with type
CREATE VIEW IF NOT EXISTS files_with_types_view AS
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
JOIN projects p ON pf.project_id = p.id;

-- File dependency graph view
CREATE VIEW IF NOT EXISTS file_dependency_graph_view AS
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
JOIN projects p ON parent_file.project_id = p.id;

-- Deployment readiness view
CREATE VIEW IF NOT EXISTS deployment_readiness_view AS
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
LEFT JOIN deployment_targets dt ON fd_deploy.deployment_target_id = dt.id;

-- SQL objects with file info
CREATE VIEW IF NOT EXISTS sql_objects_view AS
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
JOIN projects p ON pf.project_id = p.id;

-- API endpoints with implementation files
CREATE VIEW IF NOT EXISTS api_endpoints_view AS
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
LEFT JOIN project_files pf ON ae.implemented_by_file_id = pf.id;

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_project_files_project_id ON project_files(project_id);
CREATE INDEX IF NOT EXISTS idx_project_files_file_type_id ON project_files(file_type_id);
CREATE INDEX IF NOT EXISTS idx_project_files_component_name ON project_files(component_name);
CREATE INDEX IF NOT EXISTS idx_project_files_status ON project_files(status);
CREATE INDEX IF NOT EXISTS idx_project_files_project_path ON project_files(project_id, file_path);

CREATE INDEX IF NOT EXISTS idx_file_dependencies_parent ON file_dependencies(parent_file_id);
CREATE INDEX IF NOT EXISTS idx_file_dependencies_dependency ON file_dependencies(dependency_file_id);
CREATE INDEX IF NOT EXISTS idx_file_dependencies_type ON file_dependencies(dependency_type);

CREATE INDEX IF NOT EXISTS idx_sql_objects_file_id ON sql_objects(file_id);
CREATE INDEX IF NOT EXISTS idx_sql_objects_object_name ON sql_objects(object_name);
CREATE INDEX IF NOT EXISTS idx_sql_objects_schema_name ON sql_objects(schema_name);

CREATE INDEX IF NOT EXISTS idx_javascript_components_file_id ON javascript_components(file_id);
CREATE INDEX IF NOT EXISTS idx_edge_functions_file_id ON edge_functions(file_id);

CREATE INDEX IF NOT EXISTS idx_file_deployments_file_id ON file_deployments(file_id);
CREATE INDEX IF NOT EXISTS idx_file_deployments_target_id ON file_deployments(deployment_target_id);
CREATE INDEX IF NOT EXISTS idx_file_deployments_order ON file_deployments(deploy_order);

CREATE INDEX IF NOT EXISTS idx_api_endpoints_project_id ON api_endpoints(project_id);
CREATE INDEX IF NOT EXISTS idx_api_endpoints_file_id ON api_endpoints(implemented_by_file_id);

-- ============================================================================
-- INITIAL DATA - Common File Types
-- ============================================================================

INSERT OR IGNORE INTO file_types (type_name, category, description) VALUES
-- Database
('sql_table', 'database', 'PostgreSQL table definition'),
('sql_view', 'database', 'PostgreSQL view'),
('sql_materialized_view', 'database', 'PostgreSQL materialized view'),
('plpgsql_function', 'database', 'PL/pgSQL stored function or procedure'),
('sql_trigger', 'database', 'Database trigger'),
('sql_index', 'database', 'Database index'),
('sql_type', 'database', 'Custom database type or enum'),
('sql_migration', 'database', 'Database migration file'),

-- Frontend
('jsx_component', 'frontend', 'React JSX component'),
('tsx_component', 'frontend', 'React TypeScript component'),
('react_hook', 'frontend', 'React custom hook'),
('javascript', 'frontend', 'JavaScript file'),
('typescript', 'frontend', 'TypeScript file'),
('css', 'frontend', 'CSS stylesheet'),
('scss', 'frontend', 'SCSS stylesheet'),
('html', 'frontend', 'HTML file'),

-- Backend
('edge_function', 'backend', 'Supabase Edge Function (Deno)'),
('api_route', 'backend', 'API route handler'),
('middleware', 'backend', 'Middleware function'),
('service', 'backend', 'Service layer module'),
('utility', 'backend', 'Utility/helper module'),

-- Infrastructure
('docker_file', 'infrastructure', 'Dockerfile'),
('docker_compose', 'infrastructure', 'Docker Compose configuration'),
('kubernetes_manifest', 'infrastructure', 'Kubernetes manifest'),
('terraform', 'infrastructure', 'Terraform configuration'),
('nix_flake', 'infrastructure', 'Nix flake configuration'),
('shell_script', 'infrastructure', 'Shell script'),

-- Configuration
('package_json', 'config', 'NPM package.json'),
('tsconfig', 'config', 'TypeScript configuration'),
('env_file', 'config', 'Environment variables file'),
('config_json', 'config', 'JSON configuration file'),
('config_yaml', 'config', 'YAML configuration file');

-- ============================================================================
-- TRIGGERS FOR UPDATED_AT TIMESTAMPS
-- ============================================================================

CREATE TRIGGER IF NOT EXISTS update_project_files_updated_at
AFTER UPDATE ON project_files
FOR EACH ROW
BEGIN
    UPDATE project_files SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_sql_objects_updated_at
AFTER UPDATE ON sql_objects
FOR EACH ROW
BEGIN
    UPDATE sql_objects SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_javascript_components_updated_at
AFTER UPDATE ON javascript_components
FOR EACH ROW
BEGIN
    UPDATE javascript_components SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_edge_functions_updated_at
AFTER UPDATE ON edge_functions
FOR EACH ROW
BEGIN
    UPDATE edge_functions SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_deployment_targets_updated_at
AFTER UPDATE ON deployment_targets
FOR EACH ROW
BEGIN
    UPDATE deployment_targets SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_file_deployments_updated_at
AFTER UPDATE ON file_deployments
FOR EACH ROW
BEGIN
    UPDATE file_deployments SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_api_endpoints_updated_at
AFTER UPDATE ON api_endpoints
FOR EACH ROW
BEGIN
    UPDATE api_endpoints SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_config_files_updated_at
AFTER UPDATE ON config_files
FOR EACH ROW
BEGIN
    UPDATE config_files SET updated_at = datetime('now') WHERE id = NEW.id;
END;

-- ============================================================================
-- END OF SCHEMA
-- ============================================================================
