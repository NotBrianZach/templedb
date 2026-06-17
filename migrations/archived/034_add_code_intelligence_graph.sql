-- Migration 034: Add Code Intelligence Graph (Phase 1 of Agent Dispatch Roadmap)
-- Date: 2026-03-18
-- Purpose: Add symbol-level dependency tracking, impact analysis, and code clustering
--
-- This migration implements the normalized schema from AGENT_DISPATCH_AND_DEPENDENCY_GRAPH_INTEGRATION.md
-- Key principle: Track ONLY public/exported symbols (not local/private) to reduce noise by 90-95%

-- ============================================================================
-- CORE SYMBOL TRACKING (PUBLIC SYMBOLS ONLY)
-- ============================================================================

-- Code symbols (ONLY public/exported symbols for cross-file dependency tracking)
-- Rationale: Local/private symbols don't affect external dependencies or blast radius
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

-- Symbol dependencies (call relationships)
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

-- ============================================================================
-- EXECUTION FLOW TRACKING
-- ============================================================================

-- Execution flows (entry point → exit mappings)
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

-- Execution flow steps (normalized call chain)
CREATE TABLE execution_flow_steps (
    id INTEGER PRIMARY KEY,
    flow_id INTEGER NOT NULL REFERENCES execution_flows(id) ON DELETE CASCADE,
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,

    step_order INTEGER NOT NULL,  -- 0-indexed position in flow
    depth INTEGER NOT NULL,  -- Call stack depth at this step

    UNIQUE(flow_id, step_order)
);

-- ============================================================================
-- IMPACT ANALYSIS (PRECOMPUTED BLAST RADIUS)
-- ============================================================================

-- Transitive dependency cache (precomputed blast radius)
-- NOTE: Direct dependencies are in code_symbol_dependencies table (no duplication)
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

-- Symbol impact on deployments (normalized)
CREATE TABLE symbol_deployment_impact (
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    deployment_target_id INTEGER NOT NULL REFERENCES deployment_targets(id) ON DELETE CASCADE,

    impact_type TEXT NOT NULL,  -- 'direct' (symbol deployed here) or 'transitive' (dependencies deployed)
    confidence_score REAL DEFAULT 1.0,

    computed_at TEXT NOT NULL DEFAULT (datetime('now')),

    PRIMARY KEY (symbol_id, deployment_target_id)
);

-- Symbol impact on API endpoints (normalized)
CREATE TABLE symbol_api_endpoint_impact (
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    endpoint_id INTEGER NOT NULL REFERENCES api_endpoints(id) ON DELETE CASCADE,

    impact_type TEXT NOT NULL,  -- 'implements' (symbol handles endpoint) or 'called_by' (endpoint calls symbol)

    PRIMARY KEY (symbol_id, endpoint_id)
);

-- Blast radius summary cache (aggregated stats per symbol)
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

-- ============================================================================
-- CODE CLUSTERING (COMMUNITY DETECTION)
-- ============================================================================

-- Code clusters (community detection via Leiden algorithm)
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

-- Cluster membership (normalized)
CREATE TABLE code_cluster_members (
    cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,

    membership_strength REAL DEFAULT 1.0,  -- 0.0-1.0, confidence that symbol belongs to cluster

    PRIMARY KEY (cluster_id, symbol_id)
);

-- Cluster file membership (derived from symbol membership)
CREATE TABLE code_cluster_files (
    cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    symbol_count INTEGER DEFAULT 1,  -- How many symbols from this file are in cluster

    PRIMARY KEY (cluster_id, file_id)
);

-- Cluster dependencies (cluster-to-cluster relationships)
CREATE TABLE code_cluster_dependencies (
    cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,
    depends_on_cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,

    dependency_strength REAL,  -- Number of inter-cluster edges / total edges
    edge_count INTEGER DEFAULT 1,  -- Number of symbol dependencies between clusters

    PRIMARY KEY (cluster_id, depends_on_cluster_id),
    CHECK(cluster_id != depends_on_cluster_id)
);

-- ============================================================================
-- HYBRID SEARCH (BM25 + SEMANTIC)
-- ============================================================================

-- Search index for hybrid search (BM25 + semantic)
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

-- FTS5 virtual table for full-text search
-- NOTE: Originally configured with content=code_search_index but this caused issues.
-- Fixed in migration 037 to use standalone FTS5 table. Base migration now uses correct config.
CREATE VIRTUAL TABLE code_search_fts USING fts5(
    symbol_id UNINDEXED,
    search_text
);

-- ============================================================================
-- INDEXES FOR PERFORMANCE
-- ============================================================================

-- Code symbols indexes
CREATE INDEX idx_code_symbols_file ON code_symbols(file_id);
CREATE INDEX idx_code_symbols_project ON code_symbols(project_id);
CREATE INDEX idx_code_symbols_scope ON code_symbols(scope);
CREATE INDEX idx_code_symbols_type ON code_symbols(symbol_type);
CREATE INDEX idx_code_symbols_name ON code_symbols(symbol_name);
CREATE INDEX idx_code_symbols_dependents ON code_symbols(num_dependents DESC);

-- Symbol dependencies indexes
CREATE INDEX idx_symbol_deps_caller ON code_symbol_dependencies(caller_symbol_id);
CREATE INDEX idx_symbol_deps_called ON code_symbol_dependencies(called_symbol_id);
CREATE INDEX idx_symbol_deps_type ON code_symbol_dependencies(dependency_type);
CREATE INDEX idx_symbol_deps_confidence ON code_symbol_dependencies(confidence_score DESC);

-- Transitive cache indexes
CREATE INDEX idx_transitive_cache_symbol ON impact_transitive_cache(symbol_id, direction);
CREATE INDEX idx_transitive_cache_affected ON impact_transitive_cache(affected_symbol_id);
CREATE INDEX idx_transitive_cache_depth ON impact_transitive_cache(depth);
CREATE INDEX idx_transitive_cache_direction_depth ON impact_transitive_cache(direction, depth);

-- Deployment impact indexes
CREATE INDEX idx_symbol_deployment_symbol ON symbol_deployment_impact(symbol_id);
CREATE INDEX idx_symbol_deployment_target ON symbol_deployment_impact(deployment_target_id);

-- API endpoint impact indexes
CREATE INDEX idx_symbol_endpoint_symbol ON symbol_api_endpoint_impact(symbol_id);
CREATE INDEX idx_symbol_endpoint ON symbol_api_endpoint_impact(endpoint_id);

-- Cluster indexes
CREATE INDEX idx_cluster_members_cluster ON code_cluster_members(cluster_id);
CREATE INDEX idx_cluster_members_symbol ON code_cluster_members(symbol_id);
CREATE INDEX idx_cluster_files_cluster ON code_cluster_files(cluster_id);
CREATE INDEX idx_cluster_files_file ON code_cluster_files(file_id);
CREATE INDEX idx_cluster_deps_cluster ON code_cluster_dependencies(cluster_id);
CREATE INDEX idx_cluster_deps_depends ON code_cluster_dependencies(depends_on_cluster_id);

-- Execution flow indexes
CREATE INDEX idx_flow_steps_flow ON execution_flow_steps(flow_id);
CREATE INDEX idx_flow_steps_symbol ON execution_flow_steps(symbol_id);
CREATE INDEX idx_flow_steps_order ON execution_flow_steps(flow_id, step_order);

-- ============================================================================
-- VIEWS FOR CONVENIENT QUERYING
-- ============================================================================

-- Complete dependency graph with symbols
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
JOIN projects p ON parent_sym.project_id = p.id;

-- Impact analysis summary (aggregated from normalized tables)
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
LEFT JOIN impact_summary_cache isc ON s.id = isc.symbol_id;

-- Symbol with deployment impact
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
JOIN projects p ON s.project_id = p.id;

-- Symbol with API endpoint impact
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
JOIN projects p ON s.project_id = p.id;

-- Cluster membership view
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
JOIN projects p ON cc.project_id = p.id;

-- Cluster dependency graph
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
JOIN projects p ON parent_cluster.project_id = p.id;

-- Execution flows with steps
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
ORDER BY ef.id, efs.step_order;

-- Transitive dependency view (who depends on me, at what depth)
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
ORDER BY itc.depth, s.qualified_name;

-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================
-- Migration 034: Code Intelligence Graph tables created successfully
-- Next steps:
-- 1. Implement symbol extraction service (Tree-sitter based)
-- 2. Build dependency graph builder
-- 3. Add MCP tools for code intelligence queries
