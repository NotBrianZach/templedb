-- TempleDB Schema (auto-generated from live database)
-- Generated: 2026-06-11T07:11:37
-- Source: /home/zach/.local/share/templedb/templedb.sqlite
-- sqlite_sequence is auto-created by SQLite for AUTOINCREMENT columns
-- FTS5 internal tables (*_content, *_docsize, etc.) are auto-created

CREATE TABLE IF NOT EXISTS api_endpoints (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    implemented_by_file_id INTEGER REFERENCES project_files(id) ON DELETE SET NULL,
    endpoint_path TEXT NOT NULL,
    http_method TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS audit_log (
          id INTEGER PRIMARY KEY,
          ts TEXT NOT NULL DEFAULT (datetime('now')),
          actor TEXT,
          action TEXT NOT NULL,
          project_slug TEXT NOT NULL,
          profile TEXT NOT NULL,
          details TEXT
        );

CREATE TABLE IF NOT EXISTS backup_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                backed_up_at TEXT NOT NULL,
                provider TEXT NOT NULL,
                backup_path TEXT NOT NULL,
                size_bytes INTEGER NOT NULL
            );

CREATE TABLE IF NOT EXISTS bookmarks (
  bookmarkId INTEGER PRIMARY KEY AUTOINCREMENT,
  bTitle TEXT NOT NULL,
  tStamp DATETIME NOT NULL,
  parentConvId INTEGER,
  pageNum INTEGER NOT NULL DEFAULT 0,
  rollingSummary TEXT NOT NULL DEFAULT '',
  isQuiz BOOLEAN DEFAULT 0,
  isPrintPage BOOLEAN DEFAULT 0,
  isPrintSliceSummary BOOLEAN DEFAULT 0,
  isPrintRollingSummary BOOLEAN DEFAULT 0,
  sliceSize INTEGER NOT NULL DEFAULT 2,
  maxTokens INTEGER NOT NULL DEFAULT 2,
  synopsis TEXT NOT NULL DEFAULT '',
  narrator TEXT,
  filePath TEXT NOT NULL,
  FOREIGN KEY (filePath) REFERENCES markdown(filePath)
);

CREATE TABLE IF NOT EXISTS character_mentions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  character_id INTEGER NOT NULL,
  page_num INTEGER NOT NULL,
  context TEXT,
  created_at DATETIME DEFAULT (datetime('now')),
  FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS characters (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  filePath TEXT NOT NULL,
  name TEXT NOT NULL,
  type TEXT DEFAULT 'person',
  description TEXT,
  first_page INTEGER,
  last_page INTEGER,
  created_at DATETIME DEFAULT (datetime('now')),
  updated_at DATETIME DEFAULT (datetime('now')),
  FOREIGN KEY (filePath) REFERENCES markdown(filePath)
);

CREATE TABLE IF NOT EXISTS checkout_snapshots (
    id INTEGER PRIMARY KEY,
    checkout_id INTEGER NOT NULL REFERENCES checkouts(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    version INTEGER NOT NULL,
    checked_out_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(checkout_id, file_id)
);

CREATE TABLE IF NOT EXISTS checkouts (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    checkout_path TEXT NOT NULL,
    branch_name TEXT DEFAULT 'main',
    checkout_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_sync_at TEXT,
    is_active BOOLEAN DEFAULT 1,
    UNIQUE(project_id, checkout_path)
);

CREATE TABLE IF NOT EXISTS code_cluster_files (
    cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    symbol_count INTEGER DEFAULT 1,  -- How many symbols from this file are in cluster

    PRIMARY KEY (cluster_id, file_id)
);

CREATE TABLE IF NOT EXISTS code_cluster_members (
    cluster_id INTEGER NOT NULL REFERENCES code_clusters(id) ON DELETE CASCADE,
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,

    membership_strength REAL DEFAULT 1.0,  -- 0.0-1.0, confidence that symbol belongs to cluster

    PRIMARY KEY (cluster_id, symbol_id)
);

CREATE TABLE IF NOT EXISTS code_clusters (
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

CREATE VIRTUAL TABLE IF NOT EXISTS code_search_fts USING fts5(
        symbol_id UNINDEXED,
        search_text
    );

CREATE TABLE IF NOT EXISTS code_search_index (
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

CREATE TABLE IF NOT EXISTS code_symbol_dependencies (
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

CREATE TABLE IF NOT EXISTS code_symbols (
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

CREATE TABLE IF NOT EXISTS commit_files (
    id INTEGER PRIMARY KEY,
    commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,
    change_type TEXT NOT NULL CHECK(change_type IN ('added', 'modified', 'deleted', 'renamed')),
    old_content_hash TEXT REFERENCES content_blobs(hash_sha256) ON DELETE SET NULL,
    new_content_hash TEXT REFERENCES content_blobs(hash_sha256) ON DELETE SET NULL,
    old_file_path TEXT,  -- For renames
    new_file_path TEXT,  -- For renames
    lines_added INTEGER DEFAULT 0,
    lines_removed INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS config_checkouts (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    checkout_dir TEXT NOT NULL UNIQUE,    -- e.g., ~/.config/templedb/checkouts/emacs-config
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(project_id)  -- One checkout per project for config links
);

CREATE TABLE IF NOT EXISTS config_links (
    id INTEGER PRIMARY KEY,
    checkout_id INTEGER NOT NULL REFERENCES config_checkouts(id) ON DELETE CASCADE,

    -- Source file in checkout
    source_path TEXT NOT NULL,            -- Relative path in checkout, e.g., ".spacemacs"
    source_absolute TEXT NOT NULL,        -- Absolute path in checkout

    -- Target symlink location
    target_path TEXT NOT NULL UNIQUE,     -- Absolute path of symlink, e.g., /home/user/.spacemacs

    -- Metadata
    status TEXT DEFAULT 'active',         -- active, broken, removed
    link_type TEXT DEFAULT 'file',        -- file, directory

    -- Backup tracking (in case we need to restore)
    backup_path TEXT,                     -- Path to backup of original file if it existed

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS content_blobs (
    -- Primary key is content hash (content-addressable)
    hash_sha256 TEXT PRIMARY KEY,

    -- Content storage (one of these will be populated)
    content_text TEXT,                -- For text files (UTF-8)
    content_blob BLOB,                -- For binary files

    -- Metadata
    content_type TEXT NOT NULL,       -- 'text' or 'binary'
    encoding TEXT DEFAULT 'utf-8',    -- For text files
    file_size_bytes INTEGER NOT NULL,

    -- Statistics (how many files reference this blob)
    reference_count INTEGER DEFAULT 0,

    -- Timestamps
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
, storage_location TEXT DEFAULT 'inline' CHECK(storage_location IN ('inline', 'external', 'remote')), external_path TEXT, chunk_count INTEGER DEFAULT 1, compression TEXT CHECK(compression IS NULL OR compression IN ('zstd', 'gzip')), remote_url TEXT, fetch_count INTEGER DEFAULT 0, last_fetched_at TEXT);

CREATE TABLE IF NOT EXISTS contexts (
  bTitle TEXT NOT NULL,
  tStamp TEXT NOT NULL,
  ordering INTEGER NOT NULL,
  embedding TEXT,  -- Store as JSON string (SQLite doesn't have native vector type)
  append TEXT NOT NULL DEFAULT '',
  prependSummary TEXT NOT NULL DEFAULT '',
  appendSummary TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(bTitle, tStamp, ordering)
);

CREATE TABLE IF NOT EXISTS conversations (
  bTitle TEXT,
  tStamp DATETIME NOT NULL DEFAULT (datetime('now')),
  conversationTStamp DATETIME NOT NULL DEFAULT (datetime('now')),
  conversation TEXT,
  PRIMARY KEY(bTitle, tStamp, conversationTStamp)
);

CREATE TABLE IF NOT EXISTS deployment_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    target TEXT NOT NULL,

    -- Content addressing
    content_hash TEXT NOT NULL,  -- SHA-256 of project files + dependencies
    files_hash TEXT NOT NULL,    -- Hash of file contents only
    deps_hash TEXT NOT NULL,     -- Hash of package manifests (package.json, requirements.txt, etc.)

    -- Cached artifacts
    cathedral_path TEXT,         -- Path to cached cathedral export
    fhs_env_path TEXT,          -- Path to cached FHS environment (fhs-env.nix)
    work_dir_path TEXT,         -- Path to cached working directory

    -- Cache metadata
    cache_created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT NOT NULL DEFAULT (datetime('now')),
    use_count INTEGER DEFAULT 1,

    -- Size tracking
    total_size_bytes INTEGER,
    file_count INTEGER,

    -- Cache validation
    is_valid BOOLEAN DEFAULT 1,  -- Invalidated on project changes
    invalidated_at TEXT,
    invalidation_reason TEXT,

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, target, content_hash)
);

CREATE TABLE IF NOT EXISTS deployment_cache_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    target TEXT NOT NULL,

    deployed_at TEXT NOT NULL DEFAULT (datetime('now')),
    cache_hit BOOLEAN NOT NULL,  -- Did we use cache?
    content_hash TEXT,           -- Hash for this deployment

    -- Performance metrics
    build_time_seconds REAL,     -- Time to build (0 if cache hit)
    export_time_seconds REAL,    -- Time to export cathedral
    total_time_seconds REAL,     -- Total deployment time

    -- What was cached/skipped
    skipped_cathedral_export BOOLEAN DEFAULT 0,
    skipped_fhs_generation BOOLEAN DEFAULT 0,
    skipped_file_reconstruction BOOLEAN DEFAULT 0,

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS deployment_environment_snapshot (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id INTEGER NOT NULL,
    var_name TEXT NOT NULL,
    var_value TEXT,

    FOREIGN KEY (deployment_id) REFERENCES deployment_history(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS deployment_health_checks (
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

CREATE TABLE IF NOT EXISTS deployment_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    target_name TEXT NOT NULL,
    deployment_type TEXT NOT NULL,  -- 'deploy' or 'rollback'

    -- Version tracking
    commit_hash TEXT,  -- VCS commit that was deployed
    cathedral_checksum TEXT,  -- Cathedral package checksum if used

    -- Status
    status TEXT NOT NULL,  -- 'in_progress', 'success', 'failed', 'rolled_back'
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    duration_ms INTEGER,

    -- Execution details
    deployed_by TEXT,  -- User or system that triggered deployment
    deployment_method TEXT,  -- 'orchestrator', 'manual', 'ci'

    -- Results
    groups_deployed TEXT,  -- JSON array of group names
    files_deployed TEXT,  -- JSON array of file paths
    error_message TEXT,

    -- Snapshot of deployed state
    deployment_snapshot TEXT,  -- JSON snapshot of what was deployed

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS deployment_rollbacks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_deployment_id INTEGER NOT NULL,  -- Deployment being rolled back
    to_deployment_id INTEGER,  -- Target deployment to roll back to (NULL for initial state)
    rollback_deployment_id INTEGER NOT NULL,  -- The rollback deployment record
    rollback_reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (from_deployment_id) REFERENCES deployment_history(id),
    FOREIGN KEY (to_deployment_id) REFERENCES deployment_history(id),
    FOREIGN KEY (rollback_deployment_id) REFERENCES deployment_history(id)
);

CREATE TABLE IF NOT EXISTS deployment_scripts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_slug TEXT NOT NULL UNIQUE,
    script_path TEXT NOT NULL,
    description TEXT,
    enabled BOOLEAN DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
, documentation TEXT);

CREATE TABLE IF NOT EXISTS deployment_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    file_size_bytes INTEGER,

    -- For rollback: store actual content or reference
    content_stored BOOLEAN DEFAULT 0,

    FOREIGN KEY (deployment_id) REFERENCES deployment_history(id) ON DELETE CASCADE,
    UNIQUE(deployment_id, file_path)
);

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
    updated_at TEXT NOT NULL DEFAULT (datetime('now')), connection_string TEXT,

    UNIQUE(project_id, target_name, target_type)
);

CREATE TABLE IF NOT EXISTS dns_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain_id INTEGER NOT NULL,
    record_type TEXT NOT NULL CHECK(record_type IN ('A', 'AAAA', 'CNAME', 'TXT', 'MX', 'NS')),
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    ttl INTEGER DEFAULT 3600,
    priority INTEGER, -- For MX records
    target_name TEXT, -- Associated deployment target (e.g., 'production', 'staging')
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (domain_id) REFERENCES project_domains(id) ON DELETE CASCADE,
    UNIQUE(domain_id, name, record_type)
);

CREATE TABLE IF NOT EXISTS edit_sessions (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Session metadata
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    hostname TEXT,                      -- Machine where edit session started
    pid INTEGER,                        -- Process ID that started edit

    -- Context
    reason TEXT,                        -- Why editing (optional)
    auto_commit BOOLEAN DEFAULT 0,      -- Auto-commit on exit?

    UNIQUE(project_id)                  -- Only one edit session per project
);

CREATE TABLE IF NOT EXISTS embeddings (
  bTitle TEXT NOT NULL,
  tStamp TEXT NOT NULL,
  pageNum INTEGER NOT NULL,
  content TEXT NOT NULL,
  embedding TEXT,  -- Store as JSON array string
  PRIMARY KEY(bTitle, tStamp)
);

CREATE TABLE IF NOT EXISTS encryption_key_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_id INTEGER REFERENCES encryption_keys(id) ON DELETE SET NULL,
    action TEXT NOT NULL,                    -- 'add', 'remove', 'enable', 'disable', 'test', 'rotate'
    actor TEXT NOT NULL,                     -- User performing action
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    details TEXT,                            -- JSON for additional context
    success INTEGER NOT NULL DEFAULT 1       -- 1 for success, 0 for failure
);

CREATE TABLE IF NOT EXISTS encryption_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key_name TEXT NOT NULL UNIQUE,           -- Human-readable name (e.g., "yubikey-1-primary")
    key_type TEXT NOT NULL CHECK(key_type IN ('yubikey', 'filesystem', 'age')),
    recipient TEXT NOT NULL UNIQUE,          -- Age recipient (age1yubikey... or age1...)
    serial_number TEXT,                      -- Yubikey serial number (if applicable)
    piv_slot TEXT CHECK(piv_slot IN ('9a', '9c', '9d', '9e', NULL)), -- PIV slot for Yubikeys
    location TEXT,                           -- Physical location ("daily-use", "safe", "offsite", "usb-backup")
    key_fingerprint TEXT,                    -- Additional identification
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_used_at TEXT,
    last_tested_at TEXT,
    notes TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,   -- Enable/disable without deletion
    is_revoked INTEGER NOT NULL DEFAULT 0,  -- Revoked keys cannot be re-enabled
    revoked_at TEXT,                        -- When key was revoked
    revoked_by TEXT,                        -- Who revoked the key
    revocation_reason TEXT,                 -- Why key was revoked
    metadata TEXT                            -- JSON for additional key metadata
);

CREATE TABLE IF NOT EXISTS env_vars (
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  description TEXT,
  environment TEXT NOT NULL DEFAULT 'default',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(key, environment)
);

CREATE TABLE IF NOT EXISTS environment_variables (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_type TEXT NOT NULL CHECK(scope_type IN ('global', 'project', 'nix_env', 'tag')),
    scope_id INTEGER,
    var_name TEXT NOT NULL,
    var_value TEXT,
    value_type TEXT DEFAULT 'static' CHECK(value_type IN ('static', 'compound', 'secret_ref')),
    template TEXT,
    is_secret BOOLEAN DEFAULT 0,
    is_exported BOOLEAN DEFAULT 1,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, hostname TEXT,
    UNIQUE(scope_type, scope_id, var_name)
);

CREATE TABLE IF NOT EXISTS environment_variables_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_type TEXT NOT NULL CHECK(scope_type IN ('global', 'project', 'nix_env', 'tag')),
    scope_id INTEGER,  -- NULL for global, project_id for project, nix_environment_id for nix_env, tag_id for tag
    var_name TEXT NOT NULL,
    var_value TEXT,
    value_type TEXT DEFAULT 'static' CHECK(value_type IN ('static', 'compound', 'secret_ref')),
    template TEXT,
    is_secret BOOLEAN DEFAULT 0,
    is_exported BOOLEAN DEFAULT 1,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(scope_type, scope_id, var_name)
);

CREATE TABLE IF NOT EXISTS file_contents (
    id INTEGER PRIMARY KEY,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    -- Content reference (instead of storing content directly)
    content_hash TEXT NOT NULL REFERENCES content_blobs(hash_sha256) ON DELETE RESTRICT,

    -- Metadata (copied from blob for convenience)
    file_size_bytes INTEGER NOT NULL,
    line_count INTEGER,               -- For text files

    -- Current version reference
    is_current BOOLEAN DEFAULT 1,

    -- Timestamps
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')), version INTEGER DEFAULT 1,

    UNIQUE(file_id, is_current)       -- Only one current version per file
);

CREATE VIRTUAL TABLE IF NOT EXISTS file_contents_fts USING fts5(
    file_path UNINDEXED,          -- Don't index file path
    content_text,                  -- Index the actual content
    tokenize='porter unicode61 remove_diacritics 1'
);

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

CREATE TABLE IF NOT EXISTS file_types (
    id INTEGER PRIMARY KEY,
    type_name TEXT NOT NULL UNIQUE,  -- e.g., 'sql_table', 'plpgsql_function', 'javascript', 'jsx_component', 'edge_function'
    category TEXT NOT NULL,           -- e.g., 'database', 'frontend', 'backend', 'infrastructure'
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS impact_summary_cache (
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

CREATE TABLE IF NOT EXISTS impact_transitive_cache (
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

CREATE TABLE IF NOT EXISTS markdown (
  filePath TEXT PRIMARY KEY,
  articleType TEXT NOT NULL DEFAULT 'article',
  title TEXT NOT NULL DEFAULT '',
  createdTStamp DATETIME NOT NULL DEFAULT (datetime('now')),
  charPageLength INTEGER NOT NULL DEFAULT 1800,
  readerExe TEXT NOT NULL DEFAULT '',
  readerArgs TEXT,
  readerStateFile TEXT
);

CREATE TABLE IF NOT EXISTS migration_history (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    target_name TEXT NOT NULL,        -- 'production', 'staging', 'local', etc.
    migration_file TEXT NOT NULL,     -- Relative path from project root
    migration_checksum TEXT NOT NULL, -- SHA256 of migration content
    applied_at TEXT NOT NULL DEFAULT (datetime('now')),
    applied_by TEXT,                  -- User or system that ran the migration
    execution_time_ms INTEGER,        -- How long the migration took
    status TEXT NOT NULL DEFAULT 'success',  -- 'success', 'failed', 'rolled_back'
    error_message TEXT,               -- Error details if status='failed'

    -- Prevent duplicate migrations per target
    UNIQUE(project_id, target_name, migration_file)
);

CREATE TABLE IF NOT EXISTS nix_configs (
          id INTEGER PRIMARY KEY,
          project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          profile TEXT NOT NULL DEFAULT 'default',
          nix_text TEXT NOT NULL,
          flake_text TEXT NOT NULL,
          flake_lock TEXT NOT NULL,
          build_command TEXT NOT NULL DEFAULT 'nix build',
          shell_command TEXT NOT NULL DEFAULT 'nix develop',
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now')),
          UNIQUE(project_id, profile)
        );

CREATE TABLE IF NOT EXISTS nix_env_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    environment_id INTEGER NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMP,
    command_run TEXT,
    exit_code INTEGER,

    FOREIGN KEY (environment_id) REFERENCES nix_environments(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS nix_environments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    env_name TEXT NOT NULL,
    description TEXT,

    -- Build configuration
    base_packages TEXT DEFAULT '[]', -- JSON array of base packages
    target_packages TEXT DEFAULT '[]', -- JSON array for targetPkgs
    multi_packages TEXT DEFAULT '[]', -- JSON array for multiPkgs

    -- Environment setup
    profile TEXT, -- Shell profile script
    runScript TEXT DEFAULT 'bash', -- Command to run when entering env

    -- Metadata
    auto_detected BOOLEAN DEFAULT 0, -- If environment was auto-detected from files
    is_active BOOLEAN DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, env_name)
);

CREATE TABLE IF NOT EXISTS nix_flake_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,

    -- Flake inputs (dependencies)
    flake_inputs TEXT,                    -- JSON: {"nixpkgs": {"url": "...", "follows": "..."}}
    nixpkgs_commit TEXT,                  -- Which nixpkgs commit/channel

    -- Flake outputs
    packages TEXT,                        -- JSON: ["default", "templedb", "templedb-tui"]
    apps TEXT,                            -- JSON: ["default", "templedb"]
    devShells TEXT,                       -- JSON: ["default"]
    nixosModules TEXT,                    -- JSON: ["default"]
    homeManagerModules TEXT,              -- JSON: ["default"]
    overlays TEXT,                        -- JSON: available overlays
    nix_outputs_raw TEXT,                 -- Full JSON from 'nix flake show --json'

    -- Build status
    last_build_check TEXT,
    last_build_succeeded BOOLEAN,
    build_error_log TEXT,

    -- Lock file tracking
    flake_lock_hash TEXT,                 -- Hash of flake.lock for change detection
    inputs_updated_at TEXT,

    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS nix_flake_validation_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    validation_timestamp TEXT DEFAULT (datetime('now')),
    validation_type TEXT NOT NULL        -- 'flake-check', 'build', 'build-dry-run'
        CHECK(validation_type IN ('flake-check', 'build', 'build-dry-run', 'module-parse')),

    succeeded BOOLEAN NOT NULL,
    error_message TEXT,
    error_log TEXT,

    -- What was tested
    nixpkgs_version TEXT,
    nix_version TEXT,

    -- Performance
    duration_seconds REAL,

    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS nix_service_metadata (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,

    -- Service identification
    service_name TEXT NOT NULL,           -- e.g., 'templedb-git-server'
    service_description TEXT,

    -- NixOS module details
    module_path TEXT,                     -- 'services.templedb' or 'programs.templedb'
    config_options TEXT,                  -- JSON: list of available options

    -- Systemd configuration
    systemd_service_name TEXT,            -- e.g., 'templedb-git-server.service'
    systemd_wants TEXT,                   -- JSON: ["multi-user.target"]
    systemd_after TEXT,                   -- JSON: ["network.target", "postgresql.service"]
    systemd_requires TEXT,                -- JSON: hard dependencies

    -- Resource management
    needs_user BOOLEAN DEFAULT 0,
    user_name TEXT,
    needs_group BOOLEAN DEFAULT 0,
    group_name TEXT,

    -- State management
    needs_state_directory BOOLEAN DEFAULT 0,
    state_directory_path TEXT,            -- e.g., '/var/lib/templedb'
    needs_runtime_directory BOOLEAN DEFAULT 0,
    runtime_directory_path TEXT,          -- e.g., '/run/templedb'

    -- Network
    opens_ports TEXT,                     -- JSON: [9418, 8080]
    binds_to_address TEXT,                -- '0.0.0.0', '127.0.0.1', etc.

    -- Dependencies
    requires_services TEXT,               -- JSON: ["postgresql", "redis"]
    requires_databases TEXT,              -- JSON: ["postgresql"]

    -- Security
    dynamic_user BOOLEAN DEFAULT 0,
    private_tmp BOOLEAN DEFAULT 1,
    protect_system TEXT,                  -- 'strict', 'full', 'true'

    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS nixops4_deployment_environments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  deployment_id INTEGER NOT NULL REFERENCES nixops4_deployments(id) ON DELETE CASCADE,
  machine_id INTEGER NOT NULL REFERENCES nixops4_machines(id) ON DELETE CASCADE,

  -- Environment snapshot
  fhs_env_path TEXT,                -- Path to FHS environment used
  working_directory TEXT,           -- Deployment working directory
  environment_vars TEXT,            -- JSON snapshot of all env vars
  nix_packages TEXT,                -- JSON array of Nix packages in environment

  -- Service state at deployment time
  active_services TEXT,             -- JSON array of running services
  service_ports TEXT,               -- JSON mapping of service -> port

  -- Process information
  process_id INTEGER,               -- Main process PID (for localhost)
  process_command TEXT,             -- Command that started the process
  process_started_at TIMESTAMP,

  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  UNIQUE(deployment_id, machine_id)
);

CREATE TABLE IF NOT EXISTS nixops4_deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network_id INTEGER NOT NULL REFERENCES nixops4_networks(id) ON DELETE CASCADE,

    -- Deployment identification
    deployment_uuid TEXT NOT NULL UNIQUE,

    -- Operation type
    operation TEXT NOT NULL,              -- 'deploy', 'destroy', 'reboot', 'rebuild', 'modify'
    target_machines TEXT,                 -- JSON array: specific machines deployed (null = all)

    -- Configuration
    config_revision TEXT,                 -- Git commit hash or flake revision
    nixpkgs_revision TEXT,                -- Nixpkgs revision used

    -- Deployment options
    deploy_options TEXT,                  -- JSON: flags like --build-only, --dry-run, --force-reboot

    -- Execution
    started_at TIMESTAMP NOT NULL,
    completed_at TIMESTAMP,
    duration_seconds INTEGER,

    -- Status
    status TEXT DEFAULT 'running',        -- 'running', 'success', 'partial', 'failed', 'cancelled'
    exit_code INTEGER,

    -- Output
    stdout_log TEXT,                      -- Captured stdout
    stderr_log TEXT,                      -- Captured stderr

    -- Changes made
    changes_summary TEXT,                 -- JSON: summary of what changed per machine
    services_restarted TEXT,              -- JSON: services that were restarted

    -- Metadata
    triggered_by TEXT,                    -- User or automation source
    triggered_reason TEXT,                -- Why was this deployment triggered

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS nixops4_local_services (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  network_id INTEGER NOT NULL REFERENCES nixops4_networks(id) ON DELETE CASCADE,
  profile_name TEXT NOT NULL,  -- Which profile uses this service

  -- Service identification
  service_name TEXT NOT NULL,       -- 'postgres', 'redis', 'rabbitmq', 'mock-stripe'
  service_type TEXT NOT NULL,       -- 'database', 'cache', 'queue', 'mock', 'custom'

  -- Container configuration
  container_image TEXT,             -- Nix expression or Docker image
  nix_package TEXT,                 -- Nix package name (e.g., 'postgresql_16')
  port_mapping TEXT,                -- '5432:5432' or JSON: {"5432": "5432", "5433": "5433"}
  environment_vars TEXT,            -- JSON environment variables for the service

  -- Data persistence
  data_volume TEXT,                 -- Path to persistent data directory
  seed_data_path TEXT,              -- Path to SQL/fixture files for seeding
  auto_seed BOOLEAN DEFAULT FALSE,  -- Auto-seed on startup

  -- Dependencies
  depends_on TEXT,                  -- JSON array of service names this depends on
  start_order INTEGER DEFAULT 0,    -- Lower numbers start first (for topological sort)

  -- Health check
  health_check_url TEXT,            -- e.g., 'http://localhost:5432' or 'tcp://localhost:6379'
  health_check_timeout INTEGER DEFAULT 30,  -- Seconds to wait for healthy status

  -- State tracking
  container_id TEXT,                -- Running container identifier (PID or Docker ID)
  status TEXT DEFAULT 'stopped',    -- 'stopped', 'starting', 'running', 'failed', 'unhealthy'
  last_started_at TIMESTAMP,
  last_stopped_at TIMESTAMP,
  failure_reason TEXT,

  -- Metadata
  description TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  UNIQUE(network_id, profile_name, service_name),
  CHECK(service_type IN ('database', 'cache', 'queue', 'mock', 'custom')),
  CHECK(status IN ('stopped', 'starting', 'running', 'failed', 'unhealthy'))
);

CREATE TABLE IF NOT EXISTS nixops4_machine_deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id INTEGER NOT NULL REFERENCES nixops4_deployments(id) ON DELETE CASCADE,
    machine_id INTEGER NOT NULL REFERENCES nixops4_machines(id) ON DELETE CASCADE,

    -- Build information
    build_started_at TIMESTAMP,
    build_completed_at TIMESTAMP,
    build_duration_seconds INTEGER,

    -- Deployment to machine
    deploy_started_at TIMESTAMP,
    deploy_completed_at TIMESTAMP,
    deploy_duration_seconds INTEGER,

    -- Status
    status TEXT DEFAULT 'pending',        -- 'pending', 'building', 'deploying', 'success', 'failed', 'skipped'
    error_message TEXT,

    -- Results
    old_system_profile TEXT,              -- Previous system profile
    new_system_profile TEXT,              -- New system profile
    units_restarted TEXT,                 -- JSON array: systemd units restarted

    -- Activation
    activation_script_ran BOOLEAN DEFAULT 0,
    activation_warnings TEXT,             -- JSON array: warnings during activation

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(deployment_id, machine_id)
);

CREATE TABLE IF NOT EXISTS nixops4_machines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network_id INTEGER NOT NULL REFERENCES nixops4_networks(id) ON DELETE CASCADE,

    -- Machine identification
    machine_name TEXT NOT NULL,           -- Machine name in nixops4 (e.g., 'web1', 'db1')
    machine_uuid TEXT NOT NULL UNIQUE,    -- UUID for machine state

    -- Target information
    target_host TEXT,                     -- Hostname or IP address
    target_user TEXT DEFAULT 'root',      -- SSH user for deployment
    target_port INTEGER DEFAULT 22,       -- SSH port

    -- Machine configuration
    system_type TEXT,                     -- 'nixos', 'linux', 'darwin'
    target_env TEXT,                      -- 'libvirtd', 'ec2', 'gce', 'azure', 'digitalocean', 'none' (existing machine)
    machine_config TEXT,                  -- JSON: machine-specific configuration

    -- Current state
    nixos_version TEXT,                   -- Current NixOS version
    system_profile TEXT,                  -- Current system profile path
    boot_id TEXT,                         -- Boot ID (changes on reboot)

    -- Status
    deployment_status TEXT DEFAULT 'new', -- 'new', 'deploying', 'deployed', 'failed', 'obsolete'
    last_deployed_at TIMESTAMP,
    last_health_check_at TIMESTAMP,
    health_status TEXT,                   -- 'healthy', 'degraded', 'unhealthy', 'unknown'

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, is_local BOOLEAN DEFAULT FALSE, local_port_base INTEGER, local_fhs_env TEXT, local_working_dir TEXT,

    UNIQUE(network_id, machine_name)
);

CREATE TABLE IF NOT EXISTS nixops4_network_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network_id INTEGER NOT NULL REFERENCES nixops4_networks(id) ON DELETE CASCADE,

    -- Topology
    network_topology TEXT,                -- JSON: graph of machine connectivity

    -- Collected at
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Network details
    private_network_cidr TEXT,            -- CIDR for private network
    vpn_type TEXT,                        -- 'wireguard', 'tinc', 'none'
    vpn_config TEXT,                      -- JSON: VPN configuration

    -- DNS
    internal_dns_zone TEXT,               -- Internal DNS zone name
    external_dns_zone TEXT                -- External DNS zone name
);

CREATE TABLE IF NOT EXISTS nixops4_network_profiles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  network_id INTEGER NOT NULL REFERENCES nixops4_networks(id) ON DELETE CASCADE,

  -- Profile identification
  profile_name TEXT NOT NULL,  -- 'local', 'staging', 'production'

  -- Profile settings
  use_local_services BOOLEAN DEFAULT FALSE,   -- Use Docker/Nix containers for services
  service_port_base INTEGER DEFAULT 5432,     -- Base port for auto-allocating service ports
  enable_mocking BOOLEAN DEFAULT FALSE,       -- Mock external APIs

  -- FHS integration
  use_fhs_environment BOOLEAN DEFAULT TRUE,   -- Deploy in isolated FHS environment
  auto_detect_packages BOOLEAN DEFAULT TRUE,  -- Auto-detect Nix packages from project

  -- Environment variable overrides (JSON)
  env_overrides TEXT,  -- {"DATABASE_URL": "postgresql://localhost:5432/test"}

  -- Deployment behavior
  auto_start_services BOOLEAN DEFAULT TRUE,   -- Auto-start local services before deployment
  auto_health_check BOOLEAN DEFAULT TRUE,     -- Run health checks after deployment
  deployment_timeout INTEGER DEFAULT 300,     -- Timeout in seconds

  -- Metadata
  description TEXT,
  is_default BOOLEAN DEFAULT FALSE,           -- Default profile for this network
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  UNIQUE(network_id, profile_name)
);

CREATE TABLE IF NOT EXISTS nixops4_networks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Network identification
    network_name TEXT NOT NULL,           -- e.g., 'production', 'staging', 'dev-cluster'
    network_uuid TEXT NOT NULL UNIQUE,    -- UUID for nixops4 state tracking

    -- Configuration
    config_file_path TEXT NOT NULL,       -- Path to network.nix or flake.nix
    flake_uri TEXT,                       -- Flake URI if using flakes (e.g., 'github:org/repo#network')
    nix_options TEXT,                     -- JSON: extra nix options (--option key value)

    -- State
    state_file_path TEXT,                 -- Path to nixops4 state file
    is_active BOOLEAN DEFAULT 1,          -- Currently active network

    -- Metadata
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    created_by TEXT,

    UNIQUE(project_id, network_name)
);

CREATE TABLE IF NOT EXISTS nixops4_port_allocations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  network_id INTEGER NOT NULL REFERENCES nixops4_networks(id) ON DELETE CASCADE,
  profile_name TEXT NOT NULL,

  -- Port details
  port_number INTEGER NOT NULL,
  allocated_to TEXT NOT NULL,      -- 'machine:web-server', 'service:postgres', 'health-check'
  purpose TEXT,                    -- 'http', 'health', 'database', 'cache'

  -- State
  is_active BOOLEAN DEFAULT TRUE,
  allocated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

  UNIQUE(network_id, profile_name, port_number)
);

CREATE TABLE IF NOT EXISTS nixops4_resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network_id INTEGER NOT NULL REFERENCES nixops4_networks(id) ON DELETE CASCADE,
    machine_id INTEGER REFERENCES nixops4_machines(id) ON DELETE CASCADE,  -- null for network-level resources

    -- Resource identification
    resource_name TEXT NOT NULL,
    resource_type TEXT NOT NULL,          -- 'dns-record', 'storage-volume', 'ssh-key', 'vpc', 'security-group', etc.
    resource_uuid TEXT NOT NULL UNIQUE,

    -- Resource details
    provider TEXT,                        -- 'route53', 'cloudflare', 'gcs', 'aws', 'azure', etc.
    provider_resource_id TEXT,            -- Provider-specific resource ID
    resource_config TEXT,                 -- JSON: resource configuration

    -- State
    status TEXT DEFAULT 'planned',        -- 'planned', 'creating', 'created', 'updating', 'deleting', 'deleted', 'failed'

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(network_id, resource_name, resource_type)
);

CREATE TABLE IF NOT EXISTS nixos_managed_packages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    package_type TEXT NOT NULL CHECK(package_type IN ('system', 'home', 'user')),
    install_scope TEXT NOT NULL CHECK(install_scope IN ('system', 'user')),
    flake_uri TEXT,  -- URI to the flake (e.g., path:/home/user/project or github:org/repo)
    package_name TEXT,  -- Name of the package (e.g., 'bza')
    version TEXT,  -- Version tag/constraint
    enabled INTEGER DEFAULT 1,  -- Whether this package is currently enabled
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notes TEXT,  -- User notes about this package

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, install_scope)
);

CREATE TABLE IF NOT EXISTS project_domains (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    domain TEXT NOT NULL,
    registrar TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'active', 'expired')),
    primary_domain INTEGER DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, domain)
);

CREATE TABLE IF NOT EXISTS project_env_vars (
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  env_var_id INTEGER NOT NULL REFERENCES env_vars(id) ON DELETE CASCADE,
  profile TEXT NOT NULL DEFAULT 'default',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (project_id, env_var_id, profile)
);

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

CREATE TABLE IF NOT EXISTS project_prompts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    template_id INTEGER REFERENCES prompt_templates(id),  -- NULL if standalone

    name TEXT NOT NULL,                      -- Scoped to project
    prompt_text TEXT NOT NULL,
    format TEXT DEFAULT 'markdown',

    -- Scope
    scope TEXT DEFAULT 'project',            -- 'project', 'work-item', 'deployment'
    is_active BOOLEAN DEFAULT 1,
    priority INTEGER DEFAULT 0,              -- For ordering multiple prompts

    -- Versioning
    version INTEGER NOT NULL DEFAULT 1,
    parent_version_id INTEGER REFERENCES project_prompts(id),

    -- Metadata
    tags TEXT,
    variables TEXT,
    metadata TEXT,

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),

    UNIQUE(project_id, name, version)
);

CREATE TABLE IF NOT EXISTS project_secret_blobs (
          project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
          secret_blob_id INTEGER NOT NULL REFERENCES secret_blobs(id) ON DELETE CASCADE,
          profile TEXT NOT NULL DEFAULT 'default',
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          PRIMARY KEY (project_id, secret_blob_id, profile)
        );

CREATE TABLE IF NOT EXISTS project_tags (
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project_id, tag_id)
);

CREATE TABLE IF NOT EXISTS projects (
          id INTEGER PRIMARY KEY,
          slug TEXT NOT NULL UNIQUE,
          name TEXT,
          repo_url TEXT,
          git_branch TEXT,
          git_ref TEXT,
          created_at TEXT NOT NULL DEFAULT (datetime('now')),
          updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        , deployment_config TEXT, project_type TEXT DEFAULT 'regular' CHECK(project_type IN ('regular', 'nixos-config', 'service', 'library')), is_nix_project BOOLEAN DEFAULT 0 NOT NULL, project_category TEXT DEFAULT 'package'
    CHECK(project_category IN ('package', 'service', 'desktop-app', 'nixos-module', 'home-module')), flake_validated_at TEXT, flake_check_status TEXT
    CHECK(flake_check_status IN ('valid', 'invalid', 'unknown', NULL)), nix_build_status TEXT
    CHECK(nix_build_status IN ('builds', 'fails', 'untested', NULL)), service_type TEXT
    CHECK(service_type IN ('oneshot', 'simple', 'forking', 'dbus', 'notify', NULL)), active_branch_id INTEGER REFERENCES vcs_branches(id));

CREATE TABLE IF NOT EXISTS prompt_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,              -- e.g., 'project-context', 'debugging', 'code-review'
    description TEXT,
    category TEXT,                           -- 'system', 'project', 'task', 'agent-role'

    -- Content
    prompt_text TEXT NOT NULL,
    format TEXT DEFAULT 'markdown',          -- markdown, json, yaml, plaintext

    -- Versioning
    version INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN DEFAULT 1,
    parent_version_id INTEGER REFERENCES prompt_templates(id),

    -- Metadata
    tags TEXT,                               -- JSON array of tags
    variables TEXT,                          -- JSON object defining template variables
    metadata TEXT,                           -- JSON for extensibility

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    created_by TEXT,                         -- Agent/user identifier

    UNIQUE(name, version)
);

CREATE TABLE IF NOT EXISTS prompt_usage_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt_type TEXT NOT NULL,               -- 'template', 'project'
    prompt_id INTEGER NOT NULL,
    project_id INTEGER REFERENCES projects(id),
    work_item_id TEXT REFERENCES work_items(id),

    -- Usage context
    used_by TEXT,                            -- Agent/user identifier
    usage_context TEXT,                      -- 'agent-launch', 'work-assignment', 'code-review'

    -- Rendered content (with variables substituted)
    rendered_prompt TEXT,
    variables_used TEXT,                     -- JSON of actual variable values

    -- Timestamps
    used_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vibe_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Context
    session_name TEXT NOT NULL,              -- e.g., "Fix auth bug", "Add search feature"
    session_type TEXT DEFAULT 'coding',      -- coding, review, debug, research, general
    related_commit_id INTEGER REFERENCES vcs_commits(id),
    related_work_item_id TEXT REFERENCES work_items(id),

    -- Status
    status TEXT NOT NULL DEFAULT 'active',   -- active, completed, abandoned

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),
    started_at TEXT DEFAULT (datetime('now')),
    completed_at TEXT,

    -- Metadata
    tags TEXT,                               -- JSON array
    metadata TEXT,                           -- JSON for extensibility
    session_token TEXT
);

CREATE TABLE IF NOT EXISTS reading_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  filePath TEXT NOT NULL,
  page_num INTEGER NOT NULL,
  content TEXT NOT NULL,
  tags TEXT,
  character_id INTEGER,
  created_at DATETIME DEFAULT (datetime('now')),
  updated_at DATETIME DEFAULT (datetime('now')),
  FOREIGN KEY (filePath) REFERENCES markdown(filePath),
  FOREIGN KEY (character_id) REFERENCES characters(id)
);

CREATE TABLE IF NOT EXISTS readme_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,                    -- Relative path from project root
    title TEXT,                                 -- Extracted from first heading
    description TEXT,                           -- Extracted from first paragraph

    -- Classification
    category TEXT,                              -- e.g., 'setup', 'api', 'deployment', 'architecture'
    scope TEXT DEFAULT 'project',               -- project, global, feature, module

    -- Metadata
    last_scanned_at TEXT DEFAULT (datetime('now')),
    word_count INTEGER DEFAULT 0,
    section_count INTEGER DEFAULT 0,
    has_toc BOOLEAN DEFAULT 0,                  -- Has table of contents

    -- Auto-generation config
    auto_index BOOLEAN DEFAULT 1,               -- Include in auto-generated indexes
    index_priority INTEGER DEFAULT 0,           -- Higher = appears first in indexes

    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    UNIQUE(project_id, file_path)
);

CREATE TABLE IF NOT EXISTS readme_index_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template_name TEXT NOT NULL UNIQUE,

    -- Template config
    heading TEXT NOT NULL,                      -- Heading for generated section
    filter_category TEXT,                       -- Only include READMEs of this category
    filter_topic TEXT,                          -- Only include READMEs with this topic
    filter_project_id INTEGER,                  -- Scope to specific project

    -- Format
    format TEXT DEFAULT 'bullet',               -- bullet, numbered, table, cards
    include_description BOOLEAN DEFAULT 1,
    max_items INTEGER DEFAULT 20,
    sort_by TEXT DEFAULT 'priority',            -- priority, alphabetical, recent

    -- Insertion
    insert_after_heading TEXT,                  -- Insert after this heading (or null for end)
    marker_comment TEXT DEFAULT '<!-- AUTO-GENERATED INDEX -->',

    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (filter_project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS readme_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_readme_id INTEGER NOT NULL,          -- README that contains the link
    target_readme_id INTEGER,                   -- README being referenced
    target_external_url TEXT,                   -- External URL if not another README

    -- Reference metadata
    link_text TEXT,                             -- Text of the link
    context TEXT,                               -- Surrounding text for context
    section TEXT,                               -- Which section contains this reference

    -- Link management
    is_broken BOOLEAN DEFAULT 0,                -- Target doesn't exist
    is_auto_generated BOOLEAN DEFAULT 0,        -- Was this added by auto-indexer
    last_verified_at TEXT,

    created_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (source_readme_id) REFERENCES readme_files(id) ON DELETE CASCADE,
    FOREIGN KEY (target_readme_id) REFERENCES readme_files(id) ON DELETE SET NULL,

    CHECK ((target_readme_id IS NOT NULL AND target_external_url IS NULL) OR
           (target_readme_id IS NULL AND target_external_url IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS readme_sections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    readme_id INTEGER NOT NULL,

    -- Section identification
    heading TEXT NOT NULL,                      -- Section heading text
    level INTEGER NOT NULL,                     -- 1 for #, 2 for ##, etc.
    anchor TEXT,                                -- URL anchor (e.g., #installation)
    line_number INTEGER,                        -- Line where section starts

    -- Content
    content_preview TEXT,                       -- First few lines
    word_count INTEGER DEFAULT 0,

    -- For auto-indexing
    is_indexable BOOLEAN DEFAULT 1,             -- Include in generated indexes

    created_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (readme_id) REFERENCES readme_files(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS readme_topics (
    readme_id INTEGER NOT NULL,
    topic TEXT NOT NULL,                        -- e.g., 'nix', 'deployment', 'vcs', 'api'
    relevance REAL DEFAULT 1.0,                 -- 0.0-1.0, how relevant is this topic

    -- Source of topic
    source TEXT DEFAULT 'manual',               -- manual, extracted, inferred

    created_at TEXT DEFAULT (datetime('now')),

    PRIMARY KEY (readme_id, topic),
    FOREIGN KEY (readme_id) REFERENCES readme_files(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS schema_version (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        version     INTEGER NOT NULL,
        filename    TEXT NOT NULL,
        file_hash   TEXT,
        applied_at  TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(filename)
    );

CREATE TABLE IF NOT EXISTS secret_blobs (
  id INTEGER PRIMARY KEY,
  profile TEXT NOT NULL DEFAULT 'default',
  secret_name TEXT NOT NULL,
  secret_blob BLOB NOT NULL,
  content_type TEXT NOT NULL DEFAULT 'application/text',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS secret_blobs_new (
  id INTEGER PRIMARY KEY,
  profile TEXT NOT NULL DEFAULT 'default',
  secret_name TEXT NOT NULL,
  secret_blob BLOB NOT NULL,
  content_type TEXT NOT NULL DEFAULT 'application/text',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS secret_key_assignments (
    secret_blob_id INTEGER NOT NULL REFERENCES secret_blobs(id) ON DELETE CASCADE,
    key_id INTEGER NOT NULL REFERENCES encryption_keys(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    added_by TEXT,                           -- User who added this assignment
    PRIMARY KEY (secret_blob_id, key_id)
);

CREATE TABLE IF NOT EXISTS subLoops (
  bTitle TEXT NOT NULL,
  tStamp DATETIME NOT NULL,
  ordering INTEGER NOT NULL,
  loopKey TEXT NOT NULL,
  userInputs TEXT NOT NULL DEFAULT '',
  gptOut TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(bTitle, tStamp, loopKey)
);

CREATE TABLE IF NOT EXISTS symbol_api_endpoint_impact (
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    endpoint_id INTEGER NOT NULL REFERENCES api_endpoints(id) ON DELETE CASCADE,

    impact_type TEXT NOT NULL,  -- 'implements' (symbol handles endpoint) or 'called_by' (endpoint calls symbol)

    PRIMARY KEY (symbol_id, endpoint_id)
);

CREATE TABLE IF NOT EXISTS symbol_deployment_impact (
    symbol_id INTEGER NOT NULL REFERENCES code_symbols(id) ON DELETE CASCADE,
    deployment_target_id INTEGER NOT NULL REFERENCES deployment_targets(id) ON DELETE CASCADE,

    impact_type TEXT NOT NULL,  -- 'direct' (symbol deployed here) or 'transitive' (dependencies deployed)
    confidence_score REAL DEFAULT 1.0,

    computed_at TEXT NOT NULL DEFAULT (datetime('now')),

    PRIMARY KEY (symbol_id, deployment_target_id)
);

CREATE TABLE IF NOT EXISTS sync_cache (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_path TEXT NOT NULL,

    -- Hash at checkout/last sync time
    content_hash TEXT NOT NULL,         -- sha256 of file content

    -- Metadata
    cached_at TEXT NOT NULL DEFAULT (datetime('now')),
    file_size INTEGER,

    UNIQUE(project_id, file_path)
);

CREATE TABLE IF NOT EXISTS system_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
, hostname TEXT);

CREATE TABLE IF NOT EXISTS system_deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    deployed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    checkout_path TEXT NOT NULL,  -- Path to checkout used for deployment
    config_path TEXT NOT NULL,    -- Path to flake.nix or configuration.nix
    is_active BOOLEAN DEFAULT 1,  -- Currently active deployment
    nixos_generation INTEGER,     -- NixOS generation number (from nixos-rebuild)
    command TEXT NOT NULL,        -- Command used: 'test', 'switch', 'boot'
    exit_code INTEGER,            -- Exit code from nixos-rebuild
    output TEXT,                  -- Output from nixos-rebuild
    created_by TEXT,              -- User who initiated deployment
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vcs_branches (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    branch_name TEXT NOT NULL,
    parent_branch_id INTEGER REFERENCES vcs_branches(id),

    -- Branch metadata
    is_default BOOLEAN DEFAULT 0,
    is_protected BOOLEAN DEFAULT 0,  -- prevent force updates

    -- Branch state
    head_commit_id INTEGER,  -- references vcs_commits, set after creation

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    created_by TEXT,

    UNIQUE(project_id, branch_name)
);

CREATE TABLE IF NOT EXISTS vcs_commit_metadata (
    id INTEGER PRIMARY KEY,
    commit_id INTEGER NOT NULL UNIQUE REFERENCES vcs_commits(id) ON DELETE CASCADE,

    -- Intent and Purpose
    intent TEXT,                    -- High-level "why" behind the commit
    change_type TEXT,               -- 'feature', 'bugfix', 'refactor', 'docs', 'test', 'chore', 'perf', 'style'
    scope TEXT,                     -- Area of codebase affected (e.g., 'auth', 'api', 'ui')

    -- Breaking Changes
    is_breaking BOOLEAN DEFAULT 0,
    breaking_change_description TEXT,
    migration_notes TEXT,           -- How to migrate from previous version

    -- Related Context
    related_issues TEXT,            -- JSON array of issue IDs/URLs
    related_commits TEXT,           -- JSON array of related commit hashes
    related_prs TEXT,               -- JSON array of PR/MR IDs

    -- Impact Assessment
    impact_level TEXT,              -- 'low', 'medium', 'high', 'critical'
    affected_systems TEXT,          -- JSON array of system components
    risk_level TEXT,                -- 'low', 'medium', 'high'

    -- Development Context
    ai_assisted BOOLEAN DEFAULT 0,  -- Was AI used for these changes?
    ai_tool TEXT,                   -- Which AI tool (e.g., 'Claude', 'GPT-4', 'Copilot')
    confidence_level TEXT,          -- 'low', 'medium', 'high' - developer's confidence

    -- Review and Quality
    review_status TEXT,             -- 'not_reviewed', 'reviewed', 'approved', 'changes_requested'
    reviewed_by TEXT,               -- Reviewer name/email
    reviewed_at TEXT,
    test_coverage_change REAL,      -- Change in test coverage percentage

    -- Technical Details
    refactor_reason TEXT,           -- Why code was refactored
    performance_impact TEXT,        -- Expected performance changes
    security_impact TEXT,           -- Security implications

    -- Tags and Categories (flexible JSON arrays)
    tags TEXT,                      -- JSON array of custom tags
    categories TEXT,                -- JSON array of categories

    -- Metadata timestamps
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vcs_commit_tags (
    id INTEGER PRIMARY KEY,
    commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    tag_name TEXT NOT NULL,
    tag_category TEXT,              -- 'type', 'priority', 'team', 'custom'

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(commit_id, tag_name)
);

CREATE TABLE IF NOT EXISTS vcs_commits (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    branch_id INTEGER NOT NULL REFERENCES vcs_branches(id) ON DELETE CASCADE,

    -- Commit identity
    commit_hash TEXT NOT NULL UNIQUE,  -- SHA-256 of commit content
    parent_commit_id INTEGER REFERENCES vcs_commits(id),
    merge_parent_commit_id INTEGER REFERENCES vcs_commits(id),  -- for merges

    -- Commit metadata
    author TEXT NOT NULL,
    author_email TEXT,
    committer TEXT,
    committer_email TEXT,

    commit_message TEXT NOT NULL,
    commit_timestamp TEXT NOT NULL DEFAULT (datetime('now')),

    -- Statistics
    files_changed INTEGER DEFAULT 0,
    lines_added INTEGER DEFAULT 0,
    lines_removed INTEGER DEFAULT 0,

    -- Git import mapping
    git_commit_hash TEXT,  -- if imported from git
    git_branch TEXT,

    UNIQUE(project_id, commit_hash)
);

CREATE TABLE IF NOT EXISTS vcs_commit_parents (
    commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    parent_commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    parent_order INTEGER NOT NULL DEFAULT 0,  -- 0 = first parent, 1 = merge parent, etc.

    PRIMARY KEY (commit_id, parent_commit_id)
);

CREATE TABLE IF NOT EXISTS vcs_file_change_metadata (
    id INTEGER PRIMARY KEY,
    commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    -- File-specific intent
    change_intent TEXT,             -- Why this specific file was changed
    change_summary TEXT,            -- Brief summary of changes to this file

    -- Technical details
    change_complexity TEXT,         -- 'trivial', 'simple', 'moderate', 'complex'
    requires_testing BOOLEAN DEFAULT 1,
    test_file_path TEXT,            -- Associated test file

    -- Dependencies
    affects_files TEXT,             -- JSON array of file paths this change impacts
    breaking_for_dependents BOOLEAN DEFAULT 0,

    -- Review notes
    review_notes TEXT,
    requires_special_review BOOLEAN DEFAULT 0,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(commit_id, file_id)
);

CREATE TABLE IF NOT EXISTS vcs_file_states (
    id INTEGER PRIMARY KEY,
    commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    -- File content at this commit
    content_text TEXT,
    content_blob BLOB,
    content_hash TEXT NOT NULL,  -- SHA-256

    -- File metadata at this commit
    file_mode TEXT,  -- permissions
    file_size INTEGER NOT NULL,
    line_count INTEGER,

    -- Change type in this commit
    change_type TEXT NOT NULL,  -- 'added', 'modified', 'deleted', 'renamed'
    previous_path TEXT,  -- if renamed

    UNIQUE(commit_id, file_id)
);

CREATE TABLE IF NOT EXISTS vcs_file_states_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    commit_id INTEGER NOT NULL,
    file_id INTEGER NOT NULL,

    -- Content reference (not inline storage)
    content_hash TEXT NOT NULL,

    -- File metadata at this commit
    file_mode TEXT,
    file_size INTEGER NOT NULL,
    line_count INTEGER,

    -- Change type in this commit
    change_type TEXT NOT NULL,  -- 'added', 'modified', 'deleted', 'renamed'
    previous_path TEXT,

    FOREIGN KEY (commit_id) REFERENCES vcs_commits(id) ON DELETE CASCADE,
    FOREIGN KEY (file_id) REFERENCES project_files(id) ON DELETE CASCADE,
    FOREIGN KEY (content_hash) REFERENCES content_blobs(hash_sha256),
    UNIQUE(commit_id, file_id)
);

CREATE TABLE IF NOT EXISTS vcs_tags (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,

    tag_name TEXT NOT NULL,
    tag_type TEXT NOT NULL DEFAULT 'lightweight',  -- 'lightweight', 'annotated'

    -- Annotated tag info
    tagger TEXT,
    tagger_email TEXT,
    tag_message TEXT,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(project_id, tag_name)
);

CREATE TABLE IF NOT EXISTS vcs_working_state (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    branch_id INTEGER NOT NULL REFERENCES vcs_branches(id) ON DELETE CASCADE,
    file_id INTEGER NOT NULL REFERENCES project_files(id) ON DELETE CASCADE,

    -- Current working content (may differ from committed)
    content_text TEXT,
    content_blob BLOB,
    content_hash TEXT,

    -- State tracking
    state TEXT NOT NULL DEFAULT 'unmodified',  -- 'unmodified', 'modified', 'added', 'deleted', 'conflict'
    staged BOOLEAN DEFAULT 0,  -- ready to commit

    last_modified TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(project_id, branch_id, file_id)
);

CREATE TABLE IF NOT EXISTS vibe_claude_interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES vibe_sessions(id) ON DELETE CASCADE,

    -- Interaction metadata
    interaction_sequence INTEGER NOT NULL,  -- Order within session (0, 1, 2, ...)
    interaction_type TEXT NOT NULL,        -- 'user_prompt', 'assistant_response', 'tool_use', 'tool_result'
    role TEXT NOT NULL,                    -- 'user', 'assistant', 'system'

    -- Content
    content TEXT NOT NULL,                 -- The actual text content
    content_type TEXT DEFAULT 'text',      -- 'text', 'markdown', 'code', 'json', 'error'
    content_language TEXT,                 -- Programming language if code

    -- Context about what files/code this relates to
    related_files TEXT,                    -- JSON array of file paths mentioned/modified
    related_change_id INTEGER REFERENCES vibe_session_changes(id),
    related_commit_hash TEXT,

    -- Tool usage (if this is a tool use/result)
    tool_name TEXT,                        -- e.g., 'Read', 'Edit', 'Bash', 'Grep'
    tool_params TEXT,                      -- JSON of tool parameters
    tool_result TEXT,                      -- Result if tool_result type
    tool_success BOOLEAN,                  -- Whether tool succeeded

    -- API metadata
    model_used TEXT,                       -- e.g., 'claude-sonnet-4.5-20250929'
    tokens_input INTEGER,                  -- Tokens in (if available)
    tokens_output INTEGER,                 -- Tokens out (if available)
    latency_ms INTEGER,                    -- Response time in milliseconds
    api_request_id TEXT,                   -- Claude API request ID

    -- Vector embedding for semantic search (future RAG)
    embedding BLOB,                        -- Store sentence transformer embeddings
    embedding_model TEXT,                  -- Model used for embedding

    -- Quality signals
    contains_code BOOLEAN DEFAULT 0,
    contains_error BOOLEAN DEFAULT 0,
    code_blocks_count INTEGER DEFAULT 0,

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),

    -- Extensibility
    metadata TEXT                          -- JSON for additional data
);

CREATE TABLE IF NOT EXISTS vibe_interaction_code_snippets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interaction_id INTEGER NOT NULL REFERENCES vibe_claude_interactions(id) ON DELETE CASCADE,
    session_id INTEGER NOT NULL REFERENCES vibe_sessions(id) ON DELETE CASCADE,

    -- Code details
    language TEXT NOT NULL,
    code_content TEXT NOT NULL,
    snippet_type TEXT,                     -- 'example', 'fix', 'feature', 'refactor'

    -- Context
    file_path TEXT,                        -- If associated with a file
    was_applied BOOLEAN DEFAULT 0,         -- Did this code get used?

    -- Metadata
    line_count INTEGER,
    char_count INTEGER,

    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vibe_interaction_embeddings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interaction_id INTEGER NOT NULL UNIQUE REFERENCES vibe_claude_interactions(id) ON DELETE CASCADE,

    -- Embedding vector (stored as blob)
    embedding BLOB NOT NULL,
    embedding_dim INTEGER NOT NULL,        -- Dimension of embedding (e.g., 384, 768, 1536)
    embedding_model TEXT NOT NULL,         -- e.g., 'all-MiniLM-L6-v2', 'text-embedding-3-small'

    -- For normalized cosine similarity
    embedding_norm REAL,                   -- L2 norm for faster similarity

    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vibe_interaction_pairs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES vibe_sessions(id) ON DELETE CASCADE,
    prompt_interaction_id INTEGER NOT NULL REFERENCES vibe_claude_interactions(id),
    response_interaction_id INTEGER NOT NULL REFERENCES vibe_claude_interactions(id),

    -- Conversation turn metadata
    turn_number INTEGER NOT NULL,

    -- Quality metrics
    user_rating INTEGER,                   -- 1-5 stars (user can rate responses)
    was_helpful BOOLEAN,
    led_to_code_change BOOLEAN DEFAULT 0,
    led_to_commit BOOLEAN DEFAULT 0,
    related_commit_hash TEXT,

    -- Complexity metrics
    tool_calls_count INTEGER DEFAULT 0,
    files_modified_count INTEGER DEFAULT 0,
    lines_changed INTEGER DEFAULT 0,

    -- Timing
    total_duration_ms INTEGER,             -- Time from prompt to response
    thinking_time_ms INTEGER,              -- Time spent "thinking"

    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vibe_interaction_topics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES vibe_sessions(id) ON DELETE CASCADE,

    -- Topic identification
    topic_name TEXT NOT NULL,              -- e.g., 'authentication', 'error-handling', 'database-migration'
    topic_category TEXT,                   -- 'feature', 'bug', 'refactor', 'question', 'debug'
    confidence REAL,                       -- 0.0-1.0 confidence in topic extraction

    -- Related interactions
    first_interaction_id INTEGER REFERENCES vibe_claude_interactions(id),
    last_interaction_id INTEGER REFERENCES vibe_claude_interactions(id),
    interaction_count INTEGER DEFAULT 1,

    -- Keywords for matching
    keywords TEXT,                         -- JSON array of keywords

    created_at TEXT DEFAULT (datetime('now')),

    UNIQUE(session_id, topic_name)
);

CREATE TABLE IF NOT EXISTS vibe_session_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES vibe_sessions(id) ON DELETE CASCADE,

    -- Change tracking
    file_path TEXT NOT NULL,
    change_type TEXT NOT NULL,              -- 'edit', 'create', 'delete'
    diff_content TEXT,

    -- Timestamps
    changed_at TEXT DEFAULT (datetime('now')),

    -- Metadata
    commit_hash TEXT,                        -- If committed
    claude_interaction_id TEXT               -- Link to Claude interaction if available
);

CREATE TABLE IF NOT EXISTS vibe_session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES vibe_sessions(id) ON DELETE CASCADE,

    -- Event details
    event_type TEXT NOT NULL,                -- 'started', 'change', 'claude_response',
                                             -- 'committed', 'ended'
    event_data TEXT,                         -- JSON

    -- Timestamp
    occurred_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS vibe_session_stats (
    session_id INTEGER PRIMARY KEY REFERENCES vibe_sessions(id) ON DELETE CASCADE,

    -- Interaction counts
    total_interactions INTEGER DEFAULT 0,
    user_prompts INTEGER DEFAULT 0,
    assistant_responses INTEGER DEFAULT 0,
    tool_uses INTEGER DEFAULT 0,

    -- Content stats
    total_tokens INTEGER DEFAULT 0,
    total_code_blocks INTEGER DEFAULT 0,
    total_files_mentioned INTEGER DEFAULT 0,
    total_files_modified INTEGER DEFAULT 0,

    -- Quality metrics
    avg_response_latency_ms INTEGER,
    total_errors INTEGER DEFAULT 0,

    -- Topics
    topics_discussed TEXT,                 -- JSON array of topics
    primary_programming_languages TEXT,    -- JSON array of languages

    -- Timestamps
    first_interaction_at TEXT,
    last_interaction_at TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS work_item_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipient TEXT NOT NULL,
            message_type TEXT NOT NULL,
            work_item_id TEXT,
            convoy_id INTEGER,
            message_content TEXT NOT NULL,
            priority TEXT DEFAULT 'normal',
            status TEXT NOT NULL DEFAULT 'unread',
            delivered_at TEXT DEFAULT (datetime('now')),
            read_at TEXT,
            acknowledged_at TEXT,

            FOREIGN KEY (work_item_id) REFERENCES work_items(id) ON DELETE CASCADE,

            CHECK (message_type IN ('work_assignment', 'notification', 'coordination_request', 'status_update')),
            CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
            CHECK (status IN ('unread', 'read', 'acknowledged', 'completed'))
        );

CREATE TABLE IF NOT EXISTS work_item_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_item_id TEXT NOT NULL,
    from_status TEXT NOT NULL,
    to_status TEXT NOT NULL,
    changed_by TEXT,
    reason TEXT,
    transitioned_at TEXT DEFAULT (datetime('now')),

    FOREIGN KEY (work_item_id) REFERENCES work_items(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS "work_items" (
    id TEXT PRIMARY KEY,
    project_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    priority TEXT DEFAULT 'medium',
    item_type TEXT DEFAULT 'task',

    -- Assignment with TEXT identifiers (not foreign keys)
    assigned_to TEXT,
    created_by TEXT,
    parent_item_id TEXT,

    -- Metadata
    estimated_effort TEXT,
    tags TEXT,
    metadata TEXT,

    -- Timestamps
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    assigned_at TEXT,
    started_at TEXT,
    completed_at TEXT,

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (parent_item_id) REFERENCES work_items(id) ON DELETE SET NULL,

    CHECK (status IN ('pending', 'assigned', 'in_progress', 'completed', 'blocked', 'cancelled')),
    CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    CHECK (item_type IN ('task', 'bug', 'feature', 'refactor', 'research', 'documentation'))
);

CREATE INDEX IF NOT EXISTS idx_bookmarks_filepath ON bookmarks(filePath);

CREATE INDEX IF NOT EXISTS idx_bookmarks_title ON bookmarks(bTitle);

CREATE INDEX IF NOT EXISTS idx_cache_stats_hits ON deployment_cache_stats(cache_hit);

CREATE INDEX IF NOT EXISTS idx_cache_stats_project ON deployment_cache_stats(project_id, deployed_at DESC);

CREATE INDEX IF NOT EXISTS idx_character_mentions_char ON character_mentions(character_id);

CREATE INDEX IF NOT EXISTS idx_character_mentions_page ON character_mentions(page_num);

CREATE INDEX IF NOT EXISTS idx_characters_filepath ON characters(filePath);

CREATE INDEX IF NOT EXISTS idx_characters_name ON characters(name);

CREATE INDEX IF NOT EXISTS idx_checkout_snapshots_checkout ON checkout_snapshots(checkout_id);

CREATE INDEX IF NOT EXISTS idx_checkout_snapshots_file ON checkout_snapshots(file_id);

CREATE INDEX IF NOT EXISTS idx_checkout_snapshots_version ON checkout_snapshots(version);

CREATE INDEX IF NOT EXISTS idx_checkouts_active ON checkouts(is_active);

CREATE INDEX IF NOT EXISTS idx_checkouts_project ON checkouts(project_id);

CREATE INDEX IF NOT EXISTS idx_claude_interactions_created
    ON vibe_claude_interactions(created_at);

CREATE INDEX IF NOT EXISTS idx_claude_interactions_files
    ON vibe_claude_interactions(related_files) WHERE related_files IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_claude_interactions_sequence
    ON vibe_claude_interactions(session_id, interaction_sequence);

CREATE INDEX IF NOT EXISTS idx_claude_interactions_session
    ON vibe_claude_interactions(session_id);

CREATE INDEX IF NOT EXISTS idx_claude_interactions_tool
    ON vibe_claude_interactions(tool_name) WHERE tool_name IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_claude_interactions_type
    ON vibe_claude_interactions(interaction_type);

CREATE INDEX IF NOT EXISTS idx_cluster_files_cluster ON code_cluster_files(cluster_id);

CREATE INDEX IF NOT EXISTS idx_cluster_files_file ON code_cluster_files(file_id);

CREATE INDEX IF NOT EXISTS idx_cluster_members_cluster ON code_cluster_members(cluster_id);

CREATE INDEX IF NOT EXISTS idx_cluster_members_symbol ON code_cluster_members(symbol_id);

CREATE INDEX IF NOT EXISTS idx_code_snippets_applied
    ON vibe_interaction_code_snippets(was_applied);

CREATE INDEX IF NOT EXISTS idx_code_snippets_interaction
    ON vibe_interaction_code_snippets(interaction_id);

CREATE INDEX IF NOT EXISTS idx_code_snippets_language
    ON vibe_interaction_code_snippets(language);

CREATE INDEX IF NOT EXISTS idx_code_snippets_session
    ON vibe_interaction_code_snippets(session_id);

CREATE INDEX IF NOT EXISTS idx_code_symbols_dependents ON code_symbols(num_dependents DESC);

CREATE INDEX IF NOT EXISTS idx_code_symbols_file ON code_symbols(file_id);

CREATE INDEX IF NOT EXISTS idx_code_symbols_name ON code_symbols(symbol_name);

CREATE INDEX IF NOT EXISTS idx_code_symbols_project ON code_symbols(project_id);

CREATE INDEX IF NOT EXISTS idx_code_symbols_scope ON code_symbols(scope);

CREATE INDEX IF NOT EXISTS idx_code_symbols_type ON code_symbols(symbol_type);

CREATE INDEX IF NOT EXISTS idx_commit_files_commit ON commit_files(commit_id);

CREATE INDEX IF NOT EXISTS idx_commit_files_file ON commit_files(file_id);

CREATE INDEX IF NOT EXISTS idx_commit_files_type ON commit_files(change_type);

CREATE INDEX IF NOT EXISTS idx_config_checkouts_project ON config_checkouts(project_id);

CREATE INDEX IF NOT EXISTS idx_config_links_checkout ON config_links(checkout_id);

CREATE INDEX IF NOT EXISTS idx_config_links_target ON config_links(target_path);

CREATE INDEX IF NOT EXISTS idx_content_blobs_external_path ON content_blobs(external_path) WHERE external_path IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_content_blobs_fetch_count ON content_blobs(fetch_count);

CREATE INDEX IF NOT EXISTS idx_content_blobs_size ON content_blobs(file_size_bytes);

CREATE INDEX IF NOT EXISTS idx_content_blobs_storage_location ON content_blobs(storage_location);

CREATE INDEX IF NOT EXISTS idx_content_blobs_type ON content_blobs(content_type);

CREATE INDEX IF NOT EXISTS idx_deployment_cache_hash ON deployment_cache(content_hash);

CREATE INDEX IF NOT EXISTS idx_deployment_cache_last_used ON deployment_cache(last_used_at DESC);

CREATE INDEX IF NOT EXISTS idx_deployment_cache_project ON deployment_cache(project_id, target);

CREATE INDEX IF NOT EXISTS idx_deployment_cache_valid ON deployment_cache(is_valid) WHERE is_valid = 1;

CREATE INDEX IF NOT EXISTS idx_deployment_env_snapshot ON deployment_environment_snapshot(deployment_id);

CREATE INDEX IF NOT EXISTS idx_deployment_history_project ON deployment_history(project_id);

CREATE INDEX IF NOT EXISTS idx_deployment_history_project_target
    ON deployment_history(project_id, target_name, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_deployment_history_status
    ON deployment_history(status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_deployment_snapshots_deployment
    ON deployment_snapshots(deployment_id);

CREATE INDEX IF NOT EXISTS idx_dns_records_domain_id ON dns_records(domain_id);

CREATE INDEX IF NOT EXISTS idx_dns_records_target_name ON dns_records(target_name);

CREATE INDEX IF NOT EXISTS idx_edit_sessions_project ON edit_sessions(project_id);

CREATE INDEX IF NOT EXISTS idx_embeddings_interaction
    ON vibe_interaction_embeddings(interaction_id);

CREATE INDEX IF NOT EXISTS idx_encryption_key_audit_key ON encryption_key_audit(key_id);

CREATE INDEX IF NOT EXISTS idx_encryption_key_audit_timestamp ON encryption_key_audit(timestamp);

CREATE INDEX IF NOT EXISTS idx_encryption_keys_active ON encryption_keys(is_active);

CREATE INDEX IF NOT EXISTS idx_encryption_keys_recipient ON encryption_keys(recipient);

CREATE INDEX IF NOT EXISTS idx_encryption_keys_type ON encryption_keys(key_type);

CREATE INDEX IF NOT EXISTS idx_environment_variables_name
    ON environment_variables(var_name);

CREATE INDEX IF NOT EXISTS idx_environment_variables_scope
    ON environment_variables(scope_type, scope_id);

CREATE INDEX IF NOT EXISTS idx_environment_variables_type
    ON environment_variables(value_type);

CREATE INDEX IF NOT EXISTS idx_file_contents_current ON file_contents(is_current);

CREATE INDEX IF NOT EXISTS idx_file_contents_file_id ON file_contents(file_id);

CREATE INDEX IF NOT EXISTS idx_file_contents_hash ON file_contents(content_hash);

CREATE INDEX IF NOT EXISTS idx_file_contents_version ON file_contents(file_id, version);

CREATE INDEX IF NOT EXISTS idx_file_dependencies_dependency ON file_dependencies(dependency_file_id);

CREATE INDEX IF NOT EXISTS idx_file_dependencies_parent ON file_dependencies(parent_file_id);

CREATE INDEX IF NOT EXISTS idx_file_dependencies_type ON file_dependencies(dependency_type);

CREATE INDEX IF NOT EXISTS idx_file_metadata_file_id
    ON file_metadata(file_id);

CREATE INDEX IF NOT EXISTS idx_file_metadata_file_type
    ON file_metadata(file_id, metadata_type);

CREATE INDEX IF NOT EXISTS idx_file_metadata_name
    ON file_metadata(object_name);

CREATE INDEX IF NOT EXISTS idx_file_metadata_type
    ON file_metadata(metadata_type);

CREATE INDEX IF NOT EXISTS idx_flake_metadata_build_status ON nix_flake_metadata(last_build_succeeded);

CREATE INDEX IF NOT EXISTS idx_flake_metadata_project ON nix_flake_metadata(project_id);

CREATE INDEX IF NOT EXISTS idx_flake_metadata_updated ON nix_flake_metadata(updated_at);

CREATE INDEX IF NOT EXISTS idx_health_checks_deployment ON deployment_health_checks(deployment_id);

CREATE INDEX IF NOT EXISTS idx_health_checks_status ON deployment_health_checks(status);

CREATE INDEX IF NOT EXISTS idx_health_checks_type ON deployment_health_checks(check_type);

CREATE INDEX IF NOT EXISTS idx_interaction_pairs_helpful
    ON vibe_interaction_pairs(was_helpful) WHERE was_helpful = 1;

CREATE INDEX IF NOT EXISTS idx_interaction_pairs_prompt
    ON vibe_interaction_pairs(prompt_interaction_id);

CREATE INDEX IF NOT EXISTS idx_interaction_pairs_response
    ON vibe_interaction_pairs(response_interaction_id);

CREATE INDEX IF NOT EXISTS idx_interaction_pairs_session
    ON vibe_interaction_pairs(session_id);

CREATE INDEX IF NOT EXISTS idx_interaction_pairs_turn
    ON vibe_interaction_pairs(session_id, turn_number);

CREATE INDEX IF NOT EXISTS idx_migration_history_applied_at
    ON migration_history(applied_at DESC);

CREATE INDEX IF NOT EXISTS idx_migration_history_project_target
    ON migration_history(project_id, target_name);

CREATE INDEX IF NOT EXISTS idx_migration_history_status
    ON migration_history(status);

CREATE INDEX IF NOT EXISTS idx_nix_env_sessions_env ON nix_env_sessions(environment_id);

CREATE INDEX IF NOT EXISTS idx_nix_env_sessions_time ON nix_env_sessions(started_at);

CREATE INDEX IF NOT EXISTS idx_nix_environments_active ON nix_environments(is_active);

CREATE INDEX IF NOT EXISTS idx_nix_environments_project ON nix_environments(project_id);

CREATE INDEX IF NOT EXISTS idx_nixops4_deployment_environments_machine
  ON nixops4_deployment_environments(machine_id);

CREATE INDEX IF NOT EXISTS idx_nixops4_deployments_network ON nixops4_deployments(network_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_nixops4_deployments_status ON nixops4_deployments(status);

CREATE INDEX IF NOT EXISTS idx_nixops4_local_services_network_profile
  ON nixops4_local_services(network_id, profile_name);

CREATE INDEX IF NOT EXISTS idx_nixops4_local_services_status
  ON nixops4_local_services(status);

CREATE INDEX IF NOT EXISTS idx_nixops4_machine_deployments ON nixops4_machine_deployments(deployment_id);

CREATE INDEX IF NOT EXISTS idx_nixops4_machine_deployments_machine ON nixops4_machine_deployments(machine_id, deploy_completed_at DESC);

CREATE INDEX IF NOT EXISTS idx_nixops4_machines_is_local
  ON nixops4_machines(is_local)
  WHERE is_local = TRUE;

CREATE INDEX IF NOT EXISTS idx_nixops4_machines_network ON nixops4_machines(network_id);

CREATE INDEX IF NOT EXISTS idx_nixops4_machines_status ON nixops4_machines(deployment_status);

CREATE INDEX IF NOT EXISTS idx_nixops4_network_info ON nixops4_network_info(network_id, collected_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_nixops4_network_profiles_default
  ON nixops4_network_profiles(network_id)
  WHERE is_default = TRUE;

CREATE INDEX IF NOT EXISTS idx_nixops4_network_profiles_network
  ON nixops4_network_profiles(network_id);

CREATE INDEX IF NOT EXISTS idx_nixops4_networks_active ON nixops4_networks(project_id, is_active) WHERE is_active = 1;

CREATE INDEX IF NOT EXISTS idx_nixops4_networks_project ON nixops4_networks(project_id);

CREATE INDEX IF NOT EXISTS idx_nixops4_port_allocations_active
  ON nixops4_port_allocations(network_id, profile_name, is_active)
  WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_nixops4_resources_machine ON nixops4_resources(machine_id);

CREATE INDEX IF NOT EXISTS idx_nixops4_resources_network ON nixops4_resources(network_id);

CREATE INDEX IF NOT EXISTS idx_nixops4_resources_type ON nixops4_resources(resource_type);

CREATE INDEX IF NOT EXISTS idx_nixos_managed_packages_enabled ON nixos_managed_packages(enabled);

CREATE INDEX IF NOT EXISTS idx_nixos_managed_packages_project ON nixos_managed_packages(project_id);

CREATE INDEX IF NOT EXISTS idx_nixos_managed_packages_scope ON nixos_managed_packages(install_scope);

CREATE INDEX IF NOT EXISTS idx_notes_character ON reading_notes(character_id);

CREATE INDEX IF NOT EXISTS idx_notes_filepath ON reading_notes(filePath);

CREATE INDEX IF NOT EXISTS idx_notes_page ON reading_notes(page_num);

CREATE INDEX IF NOT EXISTS idx_project_domains_project_id ON project_domains(project_id);

CREATE INDEX IF NOT EXISTS idx_project_domains_status ON project_domains(status);

CREATE INDEX IF NOT EXISTS idx_project_env_vars_env_var
  ON project_env_vars(env_var_id);

CREATE INDEX IF NOT EXISTS idx_project_env_vars_project
  ON project_env_vars(project_id);

CREATE INDEX IF NOT EXISTS idx_project_files_component_name ON project_files(component_name);

CREATE INDEX IF NOT EXISTS idx_project_files_file_type_id ON project_files(file_type_id);

CREATE INDEX IF NOT EXISTS idx_project_files_project_id ON project_files(project_id);

CREATE INDEX IF NOT EXISTS idx_project_files_project_path ON project_files(project_id, file_path);

CREATE INDEX IF NOT EXISTS idx_project_files_status ON project_files(status);

CREATE INDEX IF NOT EXISTS idx_project_prompts_active ON project_prompts(project_id, is_active);

CREATE INDEX IF NOT EXISTS idx_project_prompts_project ON project_prompts(project_id);

CREATE INDEX IF NOT EXISTS idx_project_prompts_template ON project_prompts(template_id);

CREATE INDEX IF NOT EXISTS idx_project_secret_blobs_project
        ON project_secret_blobs(project_id);

CREATE INDEX IF NOT EXISTS idx_project_secret_blobs_secret ON project_secret_blobs(secret_blob_id);

CREATE INDEX IF NOT EXISTS idx_project_secret_blobs_secret_blob
        ON project_secret_blobs(secret_blob_id);

CREATE INDEX IF NOT EXISTS idx_project_tags_project ON project_tags(project_id);

CREATE INDEX IF NOT EXISTS idx_project_tags_tag ON project_tags(tag_id);

CREATE INDEX IF NOT EXISTS idx_projects_build_status ON projects(nix_build_status);

CREATE INDEX IF NOT EXISTS idx_projects_category ON projects(project_category);

CREATE INDEX IF NOT EXISTS idx_projects_nix ON projects(is_nix_project);

CREATE INDEX IF NOT EXISTS idx_projects_type ON projects(project_type);

CREATE INDEX IF NOT EXISTS idx_prompt_templates_active ON prompt_templates(is_active);

CREATE INDEX IF NOT EXISTS idx_prompt_templates_category ON prompt_templates(category);

CREATE INDEX IF NOT EXISTS idx_prompt_templates_name ON prompt_templates(name);

CREATE INDEX IF NOT EXISTS idx_prompt_usage_project ON prompt_usage_log(project_id);

CREATE INDEX IF NOT EXISTS idx_prompt_usage_used_at ON prompt_usage_log(used_at);

CREATE INDEX IF NOT EXISTS idx_prompt_usage_work_item ON prompt_usage_log(work_item_id);

CREATE INDEX IF NOT EXISTS idx_vibe_sessions_project ON vibe_sessions(project_id);

CREATE INDEX IF NOT EXISTS idx_vibe_sessions_status ON vibe_sessions(status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_vibe_sessions_token ON vibe_sessions(session_token) WHERE session_token IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_readme_files_auto_index ON readme_files(auto_index, index_priority DESC);

CREATE INDEX IF NOT EXISTS idx_readme_files_category ON readme_files(category);

CREATE INDEX IF NOT EXISTS idx_readme_files_project ON readme_files(project_id);

CREATE INDEX IF NOT EXISTS idx_readme_refs_broken ON readme_references(is_broken) WHERE is_broken = 1;

CREATE INDEX IF NOT EXISTS idx_readme_refs_source ON readme_references(source_readme_id);

CREATE INDEX IF NOT EXISTS idx_readme_refs_target ON readme_references(target_readme_id);

CREATE INDEX IF NOT EXISTS idx_readme_sections_indexable ON readme_sections(is_indexable);

CREATE INDEX IF NOT EXISTS idx_readme_sections_readme ON readme_sections(readme_id);

CREATE INDEX IF NOT EXISTS idx_readme_topics_topic ON readme_topics(topic, relevance DESC);

CREATE INDEX IF NOT EXISTS idx_secret_key_assignments_key ON secret_key_assignments(key_id);

CREATE INDEX IF NOT EXISTS idx_secret_key_assignments_secret ON secret_key_assignments(secret_blob_id);

CREATE INDEX IF NOT EXISTS idx_service_metadata_project ON nix_service_metadata(project_id);

CREATE INDEX IF NOT EXISTS idx_service_metadata_service_name ON nix_service_metadata(service_name);

CREATE INDEX IF NOT EXISTS idx_symbol_deployment_symbol ON symbol_deployment_impact(symbol_id);

CREATE INDEX IF NOT EXISTS idx_symbol_deployment_target ON symbol_deployment_impact(deployment_target_id);

CREATE INDEX IF NOT EXISTS idx_symbol_deps_called ON code_symbol_dependencies(called_symbol_id);

CREATE INDEX IF NOT EXISTS idx_symbol_deps_caller ON code_symbol_dependencies(caller_symbol_id);

CREATE INDEX IF NOT EXISTS idx_symbol_deps_confidence ON code_symbol_dependencies(confidence_score DESC);

CREATE INDEX IF NOT EXISTS idx_symbol_deps_type ON code_symbol_dependencies(dependency_type);

CREATE INDEX IF NOT EXISTS idx_symbol_endpoint ON symbol_api_endpoint_impact(endpoint_id);

CREATE INDEX IF NOT EXISTS idx_symbol_endpoint_symbol ON symbol_api_endpoint_impact(symbol_id);

CREATE INDEX IF NOT EXISTS idx_sync_cache_lookup ON sync_cache(project_id, file_path);

CREATE INDEX IF NOT EXISTS idx_sync_cache_project ON sync_cache(project_id);

CREATE INDEX IF NOT EXISTS idx_system_config_key ON system_config(key);

CREATE INDEX IF NOT EXISTS idx_system_deployments_active ON system_deployments(project_id, is_active) WHERE is_active = 1;

CREATE INDEX IF NOT EXISTS idx_system_deployments_history ON system_deployments(project_id, deployed_at DESC);

CREATE INDEX IF NOT EXISTS idx_topics_category
    ON vibe_interaction_topics(topic_category);

CREATE INDEX IF NOT EXISTS idx_topics_name
    ON vibe_interaction_topics(topic_name);

CREATE INDEX IF NOT EXISTS idx_topics_session
    ON vibe_interaction_topics(session_id);

CREATE INDEX IF NOT EXISTS idx_transitions_work_item
    ON work_item_transitions(work_item_id, transitioned_at);

CREATE INDEX IF NOT EXISTS idx_transitive_cache_affected ON impact_transitive_cache(affected_symbol_id);

CREATE INDEX IF NOT EXISTS idx_transitive_cache_depth ON impact_transitive_cache(depth);

CREATE INDEX IF NOT EXISTS idx_transitive_cache_direction_depth ON impact_transitive_cache(direction, depth);

CREATE INDEX IF NOT EXISTS idx_transitive_cache_symbol ON impact_transitive_cache(symbol_id, direction);

CREATE INDEX IF NOT EXISTS idx_validation_history_project ON nix_flake_validation_history(project_id);

CREATE INDEX IF NOT EXISTS idx_validation_history_timestamp ON nix_flake_validation_history(validation_timestamp);

CREATE INDEX IF NOT EXISTS idx_validation_history_type ON nix_flake_validation_history(validation_type, succeeded);

CREATE INDEX IF NOT EXISTS idx_vcs_branches_head ON vcs_branches(head_commit_id);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_parents_parent ON vcs_commit_parents(parent_commit_id);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_metadata_ai ON vcs_commit_metadata(ai_assisted);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_metadata_breaking ON vcs_commit_metadata(is_breaking);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_metadata_commit ON vcs_commit_metadata(commit_id);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_metadata_impact ON vcs_commit_metadata(impact_level);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_metadata_type ON vcs_commit_metadata(change_type);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_tags_commit ON vcs_commit_tags(commit_id);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_tags_name ON vcs_commit_tags(tag_name);

CREATE INDEX IF NOT EXISTS idx_vcs_commits_branch ON vcs_commits(branch_id);

CREATE INDEX IF NOT EXISTS idx_vcs_commits_hash ON vcs_commits(commit_hash);

CREATE INDEX IF NOT EXISTS idx_vcs_commits_parent ON vcs_commits(parent_commit_id);

CREATE INDEX IF NOT EXISTS idx_vcs_commits_project ON vcs_commits(project_id);

CREATE INDEX IF NOT EXISTS idx_vcs_commits_timestamp ON vcs_commits(commit_timestamp);

CREATE INDEX IF NOT EXISTS idx_vcs_file_change_metadata_commit ON vcs_file_change_metadata(commit_id);

CREATE INDEX IF NOT EXISTS idx_vcs_file_change_metadata_file ON vcs_file_change_metadata(file_id);

CREATE INDEX IF NOT EXISTS idx_vcs_file_states_commit ON vcs_file_states(commit_id);

CREATE INDEX IF NOT EXISTS idx_vcs_file_states_file ON vcs_file_states(file_id);

CREATE INDEX IF NOT EXISTS idx_vcs_working_state_branch ON vcs_working_state(branch_id);

CREATE INDEX IF NOT EXISTS idx_vcs_working_state_file ON vcs_working_state(file_id);

CREATE INDEX IF NOT EXISTS idx_vcs_working_state_project ON vcs_working_state(project_id);

CREATE INDEX IF NOT EXISTS idx_vcs_working_state_state ON vcs_working_state(state);

CREATE INDEX IF NOT EXISTS idx_vibe_changes_file ON vibe_session_changes(file_path);

CREATE INDEX IF NOT EXISTS idx_vibe_changes_session ON vibe_session_changes(session_id);

CREATE INDEX IF NOT EXISTS idx_vibe_changes_time ON vibe_session_changes(changed_at);

CREATE INDEX IF NOT EXISTS idx_vibe_events_session ON vibe_session_events(session_id);

CREATE INDEX IF NOT EXISTS idx_vibe_events_time ON vibe_session_events(occurred_at);

CREATE INDEX IF NOT EXISTS idx_vibe_events_type ON vibe_session_events(event_type);

CREATE INDEX IF NOT EXISTS idx_work_items_assigned
    ON work_items(assigned_to, status);

CREATE INDEX IF NOT EXISTS idx_work_items_parent
    ON work_items(parent_item_id);

CREATE INDEX IF NOT EXISTS idx_work_items_project_status
    ON work_items(project_id, status);

CREATE INDEX IF NOT EXISTS idx_work_items_status_priority
    ON work_items(status, priority, created_at);

CREATE VIEW IF NOT EXISTS active_project_prompts_view AS
SELECT
    pp.id,
    pp.project_id,
    p.slug as project_slug,
    pp.name,
    COALESCE(pp.prompt_text, pt.prompt_text) as prompt_text,
    pp.format,
    pp.scope,
    pp.priority,
    pt.name as template_name,
    pt.category as template_category,
    pp.tags,
    pp.variables,
    pp.created_at,
    pp.updated_at
FROM project_prompts pp
JOIN projects p ON pp.project_id = p.id
LEFT JOIN prompt_templates pt ON pp.template_id = pt.id
WHERE pp.is_active = 1
ORDER BY pp.priority DESC, pp.created_at DESC;

CREATE VIEW IF NOT EXISTS active_vibe_sessions_view AS
SELECT
    vs.id,
    vs.session_name,
    vs.session_type,
    vs.session_token,
    p.slug as project_slug,
    p.name as project_name,
    COUNT(DISTINCT vsc.id) as total_changes,
    COUNT(DISTINCT ci.id) as total_interactions,
    vss.user_prompts,
    vss.assistant_responses,
    vss.total_tokens,
    vs.started_at,
    vs.status
FROM vibe_sessions vs
JOIN projects p ON vs.project_id = p.id
LEFT JOIN vibe_session_changes vsc ON vsc.session_id = vs.id
LEFT JOIN vibe_claude_interactions ci ON ci.session_id = vs.id
LEFT JOIN vibe_session_stats vss ON vss.session_id = vs.id
WHERE vs.status = 'active'
GROUP BY vs.id;

CREATE VIEW IF NOT EXISTS active_work_items_view AS
SELECT
    wi.id,
    wi.title,
    wi.status,
    wi.priority,
    wi.item_type,
    p.slug as project_slug,
    p.name as project_name,
    wi.assigned_to,
    wi.created_at,
    wi.assigned_at,
    wi.started_at,
    (SELECT COUNT(*) FROM work_items sub WHERE sub.parent_item_id = wi.id) as subtask_count
FROM work_items wi
JOIN projects p ON wi.project_id = p.id
WHERE wi.status IN ('pending', 'assigned', 'in_progress', 'blocked');

CREATE VIEW IF NOT EXISTS assignee_workload_view AS
SELECT
    wi.assigned_to,
    p.slug as project_slug,
    COUNT(wi.id) as assigned_items,
    SUM(CASE WHEN wi.status = 'in_progress' THEN 1 ELSE 0 END) as active_items,
    SUM(CASE WHEN wi.priority IN ('high', 'critical') THEN 1 ELSE 0 END) as high_priority_items,
    (SELECT COUNT(*) FROM work_item_notifications WHERE recipient = wi.assigned_to AND status = 'unread') as unread_messages
FROM work_items wi
JOIN projects p ON wi.project_id = p.id
WHERE wi.assigned_to IS NOT NULL
GROUP BY wi.assigned_to, p.slug;

CREATE VIEW IF NOT EXISTS blob_storage_stats AS
SELECT
    storage_location,
    COUNT(*) as blob_count,
    SUM(file_size_bytes) as total_size_bytes,
    AVG(file_size_bytes) as avg_size_bytes,
    MIN(file_size_bytes) as min_size_bytes,
    MAX(file_size_bytes) as max_size_bytes,
    COUNT(CASE WHEN compression IS NOT NULL THEN 1 END) as compressed_count
FROM content_blobs
GROUP BY storage_location;

CREATE VIEW IF NOT EXISTS broken_readme_links AS
SELECT
    p.slug as project_slug,
    rf.file_path as source_file,
    rr.link_text,
    rr.target_external_url,
    rr.section as source_section,
    rr.last_verified_at
FROM readme_references rr
JOIN readme_files rf ON rr.source_readme_id = rf.id
JOIN projects p ON rf.project_id = p.id
WHERE rr.is_broken = 1
ORDER BY p.slug, rf.file_path;

CREATE VIEW IF NOT EXISTS cluster_dependency_graph_view AS
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

CREATE VIEW IF NOT EXISTS cluster_members_view AS
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

CREATE VIEW IF NOT EXISTS compound_values_view AS
SELECT
    id,
    scope_id as project_id,
    var_name as value_name,
    var_value as value,
    template,
    description
FROM environment_variables
WHERE value_type = 'compound';

CREATE VIEW IF NOT EXISTS current_file_contents_view AS
SELECT
    pf.id AS file_id,
    pf.file_path,
    pf.file_name,
    pf.component_name,
    ft.type_name,
    cb.content_text,
    cb.content_type,
    fc.file_size_bytes,
    fc.line_count,
    cb.hash_sha256,
    fc.updated_at,
    p.slug AS project_slug
FROM file_contents fc
JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
JOIN project_files pf ON fc.file_id = pf.id
JOIN file_types ft ON pf.file_type_id = ft.id
JOIN projects p ON pf.project_id = p.id
WHERE fc.is_current = 1;

CREATE VIEW IF NOT EXISTS current_file_versions_view AS
SELECT
    fc.id,
    fc.file_id,
    pf.file_path,
    pf.project_id,
    p.slug as project_slug,
    (SELECT COUNT(*) FROM vcs_file_states vfs
     JOIN vcs_commits vc2 ON vfs.commit_id = vc2.id
     WHERE vfs.file_id = pf.id) as version_number,
    fc.content_hash as hash_sha256,
    cb.content_text,
    fc.file_size_bytes,
    fc.line_count,
    (SELECT vc.author FROM vcs_file_states vfs
     JOIN vcs_commits vc ON vfs.commit_id = vc.id
     WHERE vfs.file_id = pf.id
     ORDER BY vc.commit_timestamp DESC
     LIMIT 1) as author,
    (SELECT vc.commit_timestamp FROM vcs_file_states vfs
     JOIN vcs_commits vc ON vfs.commit_id = vc.id
     WHERE vfs.file_id = pf.id
     ORDER BY vc.commit_timestamp DESC
     LIMIT 1) as created_at
FROM file_contents fc
JOIN project_files pf ON fc.file_id = pf.id
JOIN projects p ON pf.project_id = p.id
LEFT JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
WHERE fc.is_current = 1;

CREATE VIEW IF NOT EXISTS dependency_graph_with_symbols_view AS
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

CREATE VIEW IF NOT EXISTS deployment_cache_active_view AS
SELECT
    p.slug AS project_slug,
    dc.target,
    dc.content_hash,
    dc.cache_created_at,
    dc.last_used_at,
    dc.use_count,
    dc.file_count,
    ROUND(dc.total_size_bytes / 1024.0 / 1024.0, 2) AS size_mb,
    ROUND((julianday('now') - julianday(dc.last_used_at)) * 24, 1) AS hours_since_use
FROM deployment_cache dc
JOIN projects p ON dc.project_id = p.id
WHERE dc.is_valid = 1
ORDER BY dc.last_used_at DESC;

CREATE VIEW IF NOT EXISTS deployment_cache_efficiency_view AS
SELECT
    p.slug AS project_slug,
    COUNT(*) AS total_deployments,
    SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END) AS cache_hits,
    SUM(CASE WHEN cache_hit = 0 THEN 1 ELSE 0 END) AS cache_misses,
    ROUND(100.0 * SUM(CASE WHEN cache_hit = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) AS hit_rate_percent,
    ROUND(AVG(CASE WHEN cache_hit = 1 THEN total_time_seconds ELSE NULL END), 2) AS avg_cached_time_sec,
    ROUND(AVG(CASE WHEN cache_hit = 0 THEN total_time_seconds ELSE NULL END), 2) AS avg_uncached_time_sec,
    ROUND(AVG(CASE WHEN cache_hit = 0 THEN total_time_seconds ELSE NULL END) -
          AVG(CASE WHEN cache_hit = 1 THEN total_time_seconds ELSE NULL END), 2) AS time_saved_per_hit_sec
FROM deployment_cache_stats dcs
JOIN projects p ON dcs.project_id = p.id
GROUP BY p.id, p.slug;

CREATE VIEW IF NOT EXISTS deployment_stats AS
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
GROUP BY p.id, dh.target;

CREATE VIEW IF NOT EXISTS encryption_key_stats_view AS
SELECT
    ek.id AS key_id,
    ek.key_name,
    ek.key_type,
    ek.location,
    ek.is_active,
    ek.serial_number,
    ek.created_at,
    ek.last_used_at,
    ek.last_tested_at,
    COUNT(DISTINCT ska.secret_blob_id) AS secrets_encrypted,
    COUNT(DISTINCT psb.project_id) AS projects_count,
    (SELECT COUNT(*) FROM encryption_key_audit WHERE key_id = ek.id AND action = 'test') AS test_count,
    (SELECT MAX(timestamp) FROM encryption_key_audit WHERE key_id = ek.id) AS last_audit_entry
FROM encryption_keys ek
LEFT JOIN secret_key_assignments ska ON ek.id = ska.key_id
LEFT JOIN secret_blobs sb ON ska.secret_blob_id = sb.id
LEFT JOIN project_secret_blobs psb ON psb.secret_blob_id = sb.id
GROUP BY ek.id, ek.key_name, ek.key_type, ek.location, ek.is_active,
         ek.serial_number, ek.created_at, ek.last_used_at, ek.last_tested_at;

CREATE VIEW IF NOT EXISTS env_vars_view AS
SELECT
    id,
    var_name,
    var_value,
    is_exported,
    description,
    created_at,
    updated_at
FROM environment_variables
WHERE scope_type = 'global';

CREATE VIEW IF NOT EXISTS environment_variables_full_view AS
SELECT
    ev.id,
    ev.scope_type,
    ev.scope_id,
    ev.var_name,
    ev.var_value,
    ev.value_type,
    ev.template,
    ev.is_secret,
    ev.is_exported,
    ev.description,
    CASE
        WHEN ev.scope_type = 'global' THEN 'Global'
        WHEN ev.scope_type = 'project' THEN p.slug
        WHEN ev.scope_type = 'nix_env' THEN ne.env_name || ' (' || p2.slug || ')'
        ELSE 'Unknown'
    END as scope_display,
    ev.created_at,
    ev.updated_at
FROM environment_variables ev
LEFT JOIN projects p ON ev.scope_type = 'project' AND ev.scope_id = p.id
LEFT JOIN nix_environments ne ON ev.scope_type = 'nix_env' AND ev.scope_id = ne.id
LEFT JOIN projects p2 ON ne.project_id = p2.id;

CREATE VIEW IF NOT EXISTS execution_flows_with_steps_view AS
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

CREATE VIEW IF NOT EXISTS external_blobs_view AS
SELECT
    hash_sha256,
    external_path,
    file_size_bytes,
    compression,
    created_at,
    fetch_count,
    last_fetched_at
FROM content_blobs
WHERE storage_location = 'external';

CREATE VIEW IF NOT EXISTS file_change_stats_view AS
SELECT
    pf.id as file_id,
    pf.file_path,
    pf.component_name,
    COUNT(DISTINCT vfs.id) as total_changes,
    COUNT(DISTINCT vfs.commit_id) as total_versions,
    COUNT(DISTINCT vc.author) as unique_authors,
    MIN(vc.commit_timestamp) as first_change,
    MAX(vc.commit_timestamp) as last_change,
    SUM(vc.lines_added) as total_lines_added,
    SUM(vc.lines_removed) as total_lines_removed,
    p.slug as project_slug
FROM project_files pf
JOIN projects p ON pf.project_id = p.id
LEFT JOIN vcs_file_states vfs ON pf.id = vfs.file_id
LEFT JOIN vcs_commits vc ON vfs.commit_id = vc.id
GROUP BY pf.id;

CREATE VIEW IF NOT EXISTS file_change_timeline_view AS
SELECT
    fv.id as event_id,
    fv.file_id,
    pf.file_path,
    pf.project_id,
    'version_created' as event_type,
    fv.author,
    fv.commit_message as description,
    fv.created_at as event_timestamp,
    json_object(
        'version_number', fv.version_number,
        'version_type', fv.version_type,
        'hash', fv.hash_sha256,
        'size', fv.file_size_bytes
    ) as metadata
FROM file_versions_new fv
JOIN project_files pf ON fv.file_id = pf.id
UNION ALL
SELECT
    vc.id as event_id,
    vfs.file_id,
    pf.file_path,
    vc.project_id,
    'committed' as event_type,
    vc.author,
    vc.commit_message as description,
    vc.commit_timestamp as event_timestamp,
    json_object(
        'commit_hash', vc.commit_hash,
        'branch', vb.branch_name,
        'change_type', vfs.change_type
    ) as metadata
FROM vcs_commits vc
JOIN vcs_file_states vfs ON vc.id = vfs.commit_id
JOIN vcs_branches vb ON vc.branch_id = vb.id
JOIN project_files pf ON vfs.file_id = pf.id
WHERE EXISTS (SELECT 1 FROM vcs_commits)
ORDER BY event_timestamp DESC;

CREATE VIEW IF NOT EXISTS file_contents_with_content AS
SELECT
    fc.id,
    fc.file_id,
    fc.content_hash,
    fc.file_size_bytes,
    fc.line_count,
    fc.is_current,
    fc.created_at,
    fc.updated_at,
    -- Content from blobs
    cb.content_text,
    cb.content_blob,
    cb.content_type,
    cb.encoding,
    cb.hash_sha256
FROM file_contents fc
JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256;

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

CREATE VIEW IF NOT EXISTS file_search_view AS
SELECT
    p.slug AS project_slug,
    p.name AS project_name,
    pf.file_path,
    pf.file_name,
    ft.type_name AS file_type,
    cb.content_text,
    cb.file_size_bytes,
    fc.line_count,
    fc.updated_at
FROM file_contents fc
JOIN project_files pf ON fc.file_id = pf.id
JOIN projects p ON pf.project_id = p.id
JOIN file_types ft ON pf.file_type_id = ft.id
JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
WHERE fc.is_current = 1 AND cb.content_type = 'text';

CREATE VIEW IF NOT EXISTS file_version_history_view AS
SELECT
    vfs.id as version_id,
    vfs.file_id,
    pf.file_path,
    pf.component_name,
    ROW_NUMBER() OVER (PARTITION BY vfs.file_id ORDER BY vc.commit_timestamp) as version_number,
    NULL as version_tag,  -- Tags now in vcs_tags
    vc.author,
    vc.commit_message,
    vfs.content_hash as hash_sha256,
    vfs.file_size as file_size_bytes,
    NULL as lines_added,
    NULL as lines_removed,
    NULL as git_commit_hash,
    NULL as git_branch,
    vc.commit_timestamp as created_at,
    p.slug as project_slug
FROM vcs_file_states vfs
JOIN vcs_commits vc ON vfs.commit_id = vc.id
JOIN project_files pf ON vfs.file_id = pf.id
JOIN projects p ON pf.project_id = p.id
ORDER BY vfs.file_id, vc.commit_timestamp DESC;

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

CREATE VIEW IF NOT EXISTS impact_summary_view AS
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

CREATE VIEW IF NOT EXISTS latest_deployments AS
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
);

CREATE VIEW IF NOT EXISTS latest_file_versions_view AS
SELECT
    pf.id as file_id,
    pf.file_path,
    pf.component_name,
    MAX(ranked.version_number) as latest_version,
    ranked.author as last_author,
    ranked.commit_message as last_commit_message,
    ranked.created_at as last_updated,
    ranked.hash_sha256,
    p.slug as project_slug
FROM project_files pf
JOIN projects p ON pf.project_id = p.id
LEFT JOIN (
    SELECT
        vfs.file_id,
        ROW_NUMBER() OVER (PARTITION BY vfs.file_id ORDER BY vc.commit_timestamp) as version_number,
        vc.author,
        vc.commit_message,
        vc.commit_timestamp as created_at,
        vfs.content_hash as hash_sha256
    FROM vcs_file_states vfs
    JOIN vcs_commits vc ON vfs.commit_id = vc.id
) ranked ON pf.id = ranked.file_id
GROUP BY pf.id;

CREATE VIEW IF NOT EXISTS migratable_inline_blobs AS
SELECT
    hash_sha256,
    file_size_bytes,
    content_type,
    reference_count,
    created_at
FROM content_blobs
WHERE storage_location = 'inline'
  AND file_size_bytes > 10485760  -- 10MB threshold
ORDER BY file_size_bytes DESC;

CREATE VIEW IF NOT EXISTS nix_env_sessions_view AS
SELECT
    nes.id,
    ne.env_name,
    p.slug AS project_slug,
    nes.started_at,
    nes.ended_at,
    CASE
        WHEN nes.ended_at IS NULL THEN 'running'
        ELSE 'completed'
    END AS status,
    nes.command_run,
    nes.exit_code,
    CAST((julianday(COALESCE(nes.ended_at, 'now')) - julianday(nes.started_at)) * 86400 AS INTEGER) AS duration_seconds
FROM nix_env_sessions nes
JOIN nix_environments ne ON nes.environment_id = ne.id
JOIN projects p ON ne.project_id = p.id
ORDER BY nes.started_at DESC;

CREATE VIEW IF NOT EXISTS nix_env_variables_view AS
SELECT
    id,
    scope_id as environment_id,
    var_name,
    var_value,
    created_at
FROM environment_variables
WHERE scope_type = 'nix_env';

CREATE VIEW IF NOT EXISTS nix_env_vars_view AS
SELECT
    nev.id,
    nev.environment_id,
    ne.env_name,
    p.slug AS project_slug,
    nev.var_name,
    nev.var_value,
    nev.description
FROM nix_env_variables nev
JOIN nix_environments ne ON nev.environment_id = ne.id
JOIN projects p ON ne.project_id = p.id
ORDER BY p.slug, ne.env_name, nev.var_name;

CREATE VIEW IF NOT EXISTS nix_environments_view AS
SELECT
    ne.id,
    ne.project_id,
    p.slug AS project_slug,
    p.name AS project_name,
    ne.env_name,
    ne.description,
    ne.base_packages,
    ne.target_packages,
    ne.multi_packages,
    ne.profile,
    ne.runScript,
    ne.auto_detected,
    ne.is_active,
    ne.created_at,
    ne.updated_at,
    (SELECT COUNT(*) FROM nix_env_variables WHERE environment_id = ne.id) AS var_count,
    (SELECT COUNT(*) FROM nix_env_sessions WHERE environment_id = ne.id) AS session_count
FROM nix_environments ne
JOIN projects p ON ne.project_id = p.id
WHERE ne.is_active = 1
ORDER BY p.slug, ne.env_name;

CREATE VIEW IF NOT EXISTS nix_ready_projects AS
SELECT
    p.slug,
    p.name,
    p.project_category,
    p.is_nix_project,
    p.flake_check_status,
    p.nix_build_status,
    nfm.packages,
    nfm.nixosModules,
    nfm.homeManagerModules,
    nfm.last_build_succeeded,
    nfm.last_build_check
FROM projects p
LEFT JOIN nix_flake_metadata nfm ON p.id = nfm.project_id
WHERE p.is_nix_project = 1;

CREATE VIEW IF NOT EXISTS nix_service_projects AS
SELECT
    p.slug,
    p.name,
    p.service_type,
    nsm.service_name,
    nsm.systemd_service_name,
    nsm.opens_ports,
    nsm.requires_services,
    nsm.requires_databases,
    nsm.module_path
FROM projects p
JOIN nix_service_metadata nsm ON p.id = nsm.project_id
WHERE p.project_category = 'service';

CREATE VIEW IF NOT EXISTS nixops4_deployment_history AS
SELECT
    d.id,
    d.deployment_uuid,
    d.network_id,
    n.network_name,
    n.project_id,
    p.slug AS project_slug,
    d.operation,
    d.target_machines,
    d.config_revision,
    d.status,
    d.started_at,
    d.completed_at,
    d.duration_seconds,
    d.triggered_by,
    COUNT(md.id) AS total_machines,
    COUNT(CASE WHEN md.status = 'success' THEN 1 END) AS successful_machines,
    COUNT(CASE WHEN md.status = 'failed' THEN 1 END) AS failed_machines
FROM nixops4_deployments d
JOIN nixops4_networks n ON d.network_id = n.id
JOIN projects p ON n.project_id = p.id
LEFT JOIN nixops4_machine_deployments md ON d.id = md.deployment_id
GROUP BY d.id, d.deployment_uuid, d.network_id, n.network_name, n.project_id,
         p.slug, d.operation, d.target_machines, d.config_revision, d.status,
         d.started_at, d.completed_at, d.duration_seconds, d.triggered_by
ORDER BY d.started_at DESC;

CREATE VIEW IF NOT EXISTS nixops4_local_machines AS
SELECT
  m.id,
  m.machine_name,
  m.target_host,
  m.local_port_base,
  m.local_fhs_env,
  m.local_working_dir,
  m.deployment_status,
  m.health_status,
  n.network_name,
  n.project_id,
  p.slug as project_slug
FROM nixops4_machines m
JOIN nixops4_networks n ON m.network_id = n.id
JOIN projects p ON n.project_id = p.id
WHERE m.is_local = TRUE;

CREATE VIEW IF NOT EXISTS nixops4_machine_health AS
SELECT
    m.id,
    m.machine_name,
    m.network_id,
    n.network_name,
    n.project_id,
    p.slug AS project_slug,
    m.target_host,
    m.deployment_status,
    m.health_status,
    m.last_deployed_at,
    m.last_health_check_at,
    m.nixos_version,
    -- Latest deployment info
    (SELECT started_at
     FROM nixops4_machine_deployments md
     JOIN nixops4_deployments d ON md.deployment_id = d.id
     WHERE md.machine_id = m.id AND md.status = 'success'
     ORDER BY md.deploy_completed_at DESC LIMIT 1) AS last_successful_deployment,
    (SELECT COUNT(*)
     FROM nixops4_machine_deployments md
     WHERE md.machine_id = m.id AND md.status = 'failed') AS failed_deployment_count
FROM nixops4_machines m
JOIN nixops4_networks n ON m.network_id = n.id
JOIN projects p ON n.project_id = p.id
ORDER BY n.network_name, m.machine_name;

CREATE VIEW IF NOT EXISTS nixops4_network_summary AS
SELECT
    n.id,
    n.project_id,
    n.network_name,
    n.network_uuid,
    n.is_active,
    p.slug AS project_slug,
    p.name AS project_name,
    COUNT(DISTINCT m.id) AS machine_count,
    COUNT(DISTINCT CASE WHEN m.deployment_status = 'deployed' THEN m.id END) AS deployed_machines,
    COUNT(DISTINCT r.id) AS resource_count,
    MAX(d.started_at) AS last_deployment_at,
    n.created_at,
    n.updated_at
FROM nixops4_networks n
JOIN projects p ON n.project_id = p.id
LEFT JOIN nixops4_machines m ON n.id = m.network_id
LEFT JOIN nixops4_resources r ON n.id = r.network_id
LEFT JOIN nixops4_deployments d ON n.id = d.network_id
WHERE n.is_active = 1
GROUP BY n.id, n.project_id, n.network_name, n.network_uuid, n.is_active,
         p.slug, p.name, n.created_at, n.updated_at;

CREATE VIEW IF NOT EXISTS nixops4_port_usage AS
SELECT
  pa.port_number,
  pa.allocated_to,
  pa.purpose,
  pa.profile_name,
  n.network_name,
  p.slug as project_slug,
  pa.allocated_at
FROM nixops4_port_allocations pa
JOIN nixops4_networks n ON pa.network_id = n.id
JOIN projects p ON n.project_id = p.id
WHERE pa.is_active = TRUE
ORDER BY pa.port_number;

CREATE VIEW IF NOT EXISTS nixops4_profile_summary AS
SELECT
  np.id,
  np.profile_name,
  np.use_local_services,
  np.enable_mocking,
  n.network_name,
  p.slug as project_slug,
  COUNT(DISTINCT ls.id) as service_count,
  COUNT(DISTINCT CASE WHEN ls.status = 'running' THEN ls.id END) as running_services,
  np.is_default
FROM nixops4_network_profiles np
JOIN nixops4_networks n ON np.network_id = n.id
JOIN projects p ON n.project_id = p.id
LEFT JOIN nixops4_local_services ls ON ls.network_id = np.network_id
  AND ls.profile_name = np.profile_name
GROUP BY np.id, np.profile_name, np.use_local_services, np.enable_mocking,
         n.network_name, p.slug, np.is_default;

CREATE VIEW IF NOT EXISTS nixops4_service_status AS
SELECT
  ls.id,
  ls.service_name,
  ls.service_type,
  ls.status,
  ls.port_mapping,
  ls.container_id,
  ls.last_started_at,
  ls.failure_reason,
  np.profile_name,
  n.network_name,
  p.slug as project_slug
FROM nixops4_local_services ls
JOIN nixops4_networks n ON ls.network_id = n.id
JOIN nixops4_network_profiles np ON np.network_id = n.id
  AND np.profile_name = ls.profile_name
JOIN projects p ON n.project_id = p.id;

CREATE VIEW IF NOT EXISTS nixos_managed_packages_view AS
SELECT
    nmp.id,
    nmp.project_id,
    p.slug as project_slug,
    p.name as project_name,
    p.repo_url as git_path,
    nmp.package_type,
    nmp.install_scope,
    nmp.flake_uri,
    nmp.package_name,
    nmp.version,
    nmp.enabled,
    nmp.added_at,
    nmp.updated_at,
    nmp.notes
FROM nixos_managed_packages nmp
JOIN projects p ON nmp.project_id = p.id;

CREATE VIEW IF NOT EXISTS project_env_vars_view AS
SELECT
    id,
    scope_id as project_id,
    var_name,
    var_value,
    created_at,
    updated_at
FROM environment_variables
WHERE scope_type = 'project';

CREATE VIEW IF NOT EXISTS project_validation_summary AS
SELECT
    p.slug,
    p.project_category,
    COUNT(nvh.id) as total_validations,
    SUM(CASE WHEN nvh.succeeded = 1 THEN 1 ELSE 0 END) as successful_validations,
    SUM(CASE WHEN nvh.succeeded = 0 THEN 1 ELSE 0 END) as failed_validations,
    MAX(nvh.validation_timestamp) as last_validation,
    AVG(nvh.duration_seconds) as avg_duration_seconds
FROM projects p
LEFT JOIN nix_flake_validation_history nvh ON p.id = nvh.project_id
WHERE p.is_nix_project = 1
GROUP BY p.id;

CREATE VIEW IF NOT EXISTS prompt_usage_summary_view AS
SELECT
    prompt_type,
    prompt_id,
    COUNT(*) as usage_count,
    COUNT(DISTINCT used_by) as unique_users,
    COUNT(DISTINCT project_id) as projects_used_in,
    MIN(used_at) as first_used,
    MAX(used_at) as last_used
FROM prompt_usage_log
GROUP BY prompt_type, prompt_id;

CREATE VIEW IF NOT EXISTS readme_files_with_topics AS
SELECT
    rf.id,
    rf.project_id,
    p.slug as project_slug,
    rf.file_path,
    rf.title,
    rf.description,
    rf.category,
    rf.scope,
    GROUP_CONCAT(rt.topic, ', ') as topics,
    rf.auto_index,
    rf.index_priority
FROM readme_files rf
JOIN projects p ON rf.project_id = p.id
LEFT JOIN readme_topics rt ON rf.id = rt.readme_id
GROUP BY rf.id;

CREATE VIEW IF NOT EXISTS readme_reference_graph AS
SELECT
    rf.id as readme_id,
    rf.title,
    p.slug as project_slug,
    rf.file_path,
    COUNT(DISTINCT rr_out.id) as outgoing_refs,
    COUNT(DISTINCT rr_in.id) as incoming_refs,
    COUNT(DISTINCT rr_out.id) + COUNT(DISTINCT rr_in.id) as total_refs
FROM readme_files rf
JOIN projects p ON rf.project_id = p.id
LEFT JOIN readme_references rr_out ON rf.id = rr_out.source_readme_id
LEFT JOIN readme_references rr_in ON rf.id = rr_in.target_readme_id
GROUP BY rf.id;

CREATE VIEW IF NOT EXISTS related_readmes AS
SELECT
    rt1.readme_id as readme_id,
    rt2.readme_id as related_readme_id,
    COUNT(*) as shared_topics,
    AVG(rt1.relevance * rt2.relevance) as relevance_score
FROM readme_topics rt1
JOIN readme_topics rt2 ON rt1.topic = rt2.topic AND rt1.readme_id < rt2.readme_id
GROUP BY rt1.readme_id, rt2.readme_id
HAVING shared_topics >= 2
ORDER BY shared_topics DESC, relevance_score DESC;

CREATE VIEW IF NOT EXISTS secrets_with_keys_view AS
SELECT
    sb.id AS secret_blob_id,
    p.slug AS project_slug,
    p.name AS project_name,
    psb.profile,
    sb.secret_name,
    COUNT(ska.key_id) AS key_count,
    GROUP_CONCAT(ek.key_name, ', ') AS assigned_keys,
    GROUP_CONCAT(ek.key_type, ', ') AS key_types,
    GROUP_CONCAT(ek.location, ', ') AS key_locations,
    sb.updated_at AS secret_updated_at
FROM secret_blobs sb
JOIN project_secret_blobs psb ON psb.secret_blob_id = sb.id
JOIN projects p ON psb.project_id = p.id
LEFT JOIN secret_key_assignments ska ON sb.id = ska.secret_blob_id
LEFT JOIN encryption_keys ek ON ska.key_id = ek.id
GROUP BY sb.id, p.slug, p.name, psb.profile, sb.secret_name, sb.updated_at;

CREATE VIEW IF NOT EXISTS stale_edit_sessions AS
SELECT
    es.id,
    es.project_id,
    p.slug as project_slug,
    es.started_at,
    es.hostname,
    es.pid,
    -- Session is stale if >24 hours old
    (julianday('now') - julianday(es.started_at)) * 24 as hours_old
FROM edit_sessions es
JOIN projects p ON p.id = es.project_id
WHERE (julianday('now') - julianday(es.started_at)) * 24 > 24;

CREATE VIEW IF NOT EXISTS symbol_deployments_view AS
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

CREATE VIEW IF NOT EXISTS symbol_endpoints_view AS
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

CREATE VIEW IF NOT EXISTS transitive_dependents_view AS
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

CREATE VIEW IF NOT EXISTS v_domain_dns_overview AS
SELECT
    p.slug as project_slug,
    p.name as project_name,
    pd.id as domain_id,
    pd.domain,
    pd.registrar,
    pd.status,
    pd.primary_domain,
    COUNT(dr.id) as dns_record_count,
    GROUP_CONCAT(DISTINCT dr.target_name) as deployment_targets,
    pd.created_at as domain_created_at
FROM project_domains pd
JOIN projects p ON pd.project_id = p.id
LEFT JOIN dns_records dr ON pd.id = dr.domain_id
GROUP BY pd.id
ORDER BY p.slug, pd.primary_domain DESC, pd.domain;

CREATE VIEW IF NOT EXISTS vcs_ai_commits_view AS
SELECT
    c.id AS commit_id,
    p.slug AS project_slug,
    b.branch_name,
    c.commit_hash,
    c.author,
    c.commit_message,
    c.commit_timestamp,
    m.ai_tool,
    m.confidence_level,
    m.intent
FROM vcs_commits c
JOIN projects p ON c.project_id = p.id
JOIN vcs_branches b ON c.branch_id = b.id
JOIN vcs_commit_metadata m ON c.id = m.commit_id
WHERE m.ai_assisted = 1
ORDER BY c.commit_timestamp DESC;

CREATE VIEW IF NOT EXISTS vcs_branch_summary_view AS
SELECT
    b.id AS branch_id,
    b.project_id,
    p.slug AS project_slug,
    b.branch_name,
    b.is_default,
    b.is_protected,
    c.commit_hash AS head_commit,
    c.author AS last_author,
    c.commit_message AS last_message,
    c.commit_timestamp AS last_commit_time,
    (SELECT COUNT(*) FROM vcs_commits WHERE branch_id = b.id) AS total_commits
FROM vcs_branches b
JOIN projects p ON b.project_id = p.id
LEFT JOIN vcs_commits c ON b.head_commit_id = c.id;

CREATE VIEW IF NOT EXISTS vcs_breaking_changes_view AS
SELECT
    c.id AS commit_id,
    p.slug AS project_slug,
    b.branch_name,
    c.commit_hash,
    c.author,
    c.commit_message,
    c.commit_timestamp,
    m.breaking_change_description,
    m.migration_notes,
    m.impact_level
FROM vcs_commits c
JOIN projects p ON c.project_id = p.id
JOIN vcs_branches b ON c.branch_id = b.id
JOIN vcs_commit_metadata m ON c.id = m.commit_id
WHERE m.is_breaking = 1
ORDER BY c.commit_timestamp DESC;

CREATE VIEW IF NOT EXISTS vcs_changes_view AS
SELECT
    ws.id,
    ws.project_id,
    p.slug as project_slug,
    ws.branch_id,
    vb.branch_name,
    ws.file_id,
    pf.file_path,
    ws.state,
    ws.staged,
    ws.content_hash,
    ws.file_size_bytes,
    CASE WHEN ws.staged = 1 THEN 'Staged' ELSE 'Not Staged' END as stage_status,
    ws.last_modified,
    ws.staged_at
FROM vcs_working_state_new ws
JOIN projects p ON ws.project_id = p.id
JOIN vcs_branches vb ON ws.branch_id = vb.id
JOIN project_files pf ON ws.file_id = pf.id
WHERE ws.state != 'unmodified'
ORDER BY ws.staged DESC, ws.state, pf.file_path;

CREATE VIEW IF NOT EXISTS vcs_commit_history_view AS
SELECT
    c.id AS commit_id,
    c.project_id,
    p.slug AS project_slug,
    b.branch_name,
    c.commit_hash,
    c.author,
    c.commit_message,
    c.commit_timestamp,
    c.files_changed,
    c.lines_added,
    c.lines_removed,
    c.git_commit_hash
FROM vcs_commits c
JOIN projects p ON c.project_id = p.id
JOIN vcs_branches b ON c.branch_id = b.id
ORDER BY c.commit_timestamp DESC;

CREATE VIEW IF NOT EXISTS vcs_commits_with_metadata_view AS
SELECT
    c.id AS commit_id,
    c.project_id,
    p.slug AS project_slug,
    b.branch_name,
    c.commit_hash,
    c.author,
    c.commit_message,
    c.commit_timestamp,
    c.files_changed,
    c.lines_added,
    c.lines_removed,
    -- Metadata
    m.intent,
    m.change_type,
    m.scope,
    m.is_breaking,
    m.impact_level,
    m.ai_assisted,
    m.confidence_level,
    m.review_status
FROM vcs_commits c
JOIN projects p ON c.project_id = p.id
JOIN vcs_branches b ON c.branch_id = b.id
LEFT JOIN vcs_commit_metadata m ON c.id = m.commit_id
ORDER BY c.commit_timestamp DESC;

CREATE VIEW IF NOT EXISTS vcs_current_files_view AS
SELECT
    ws.project_id,
    p.slug AS project_slug,
    b.branch_name,
    pf.file_path,
    ws.state,
    ws.staged,
    ws.content_hash,
    ws.last_modified
FROM vcs_working_state ws
JOIN vcs_branches b ON ws.branch_id = b.id
JOIN project_files pf ON ws.file_id = pf.id
JOIN projects p ON ws.project_id = p.id;

CREATE VIEW IF NOT EXISTS vcs_file_history_view AS
SELECT
    pf.file_path,
    c.commit_hash,
    c.author,
    c.commit_message,
    c.commit_timestamp,
    fs.change_type,
    fs.file_size,
    fs.line_count,
    b.branch_name,
    p.slug AS project_slug
FROM vcs_file_states fs
JOIN vcs_commits c ON fs.commit_id = c.id
JOIN project_files pf ON fs.file_id = pf.id
JOIN vcs_branches b ON c.branch_id = b.id
JOIN projects p ON c.project_id = p.id
ORDER BY c.commit_timestamp DESC;

CREATE VIEW IF NOT EXISTS vcs_high_impact_changes_view AS
SELECT
    c.id AS commit_id,
    p.slug AS project_slug,
    b.branch_name,
    c.commit_hash,
    c.author,
    c.commit_message,
    c.commit_timestamp,
    m.impact_level,
    m.risk_level,
    m.intent,
    m.review_status
FROM vcs_commits c
JOIN projects p ON c.project_id = p.id
JOIN vcs_branches b ON c.branch_id = b.id
JOIN vcs_commit_metadata m ON c.id = m.commit_id
WHERE m.impact_level IN ('high', 'critical')
ORDER BY c.commit_timestamp DESC;

CREATE VIEW IF NOT EXISTS vcs_staged_changes_view AS
SELECT
    ws.id,
    ws.project_id,
    p.slug as project_slug,
    ws.branch_id,
    vb.branch_name,
    ws.file_id,
    pf.file_path,
    ws.state,
    ws.content_hash,
    ws.file_size_bytes,
    ws.line_count,
    ws.change_type,
    ws.staged_at,
    ws.last_modified
FROM vcs_working_state_new ws
JOIN projects p ON ws.project_id = p.id
JOIN vcs_branches vb ON ws.branch_id = vb.id
JOIN project_files pf ON ws.file_id = pf.id
WHERE ws.staged = 1;

CREATE VIEW IF NOT EXISTS vcs_status_view AS
SELECT
    p.slug as project,
    vb.branch_name as branch,
    (SELECT commit_hash FROM vcs_commits
     WHERE branch_id = ws.branch_id
     ORDER BY commit_timestamp DESC LIMIT 1) as head_commit,
    COUNT(CASE WHEN ws.staged = 1 THEN 1 END) as staged_files,
    COUNT(CASE WHEN ws.staged = 0 AND ws.state != 'unmodified' THEN 1 END) as unstaged_files,
    COUNT(CASE WHEN ws.state = 'added' THEN 1 END) as new_files,
    COUNT(CASE WHEN ws.state = 'modified' THEN 1 END) as modified_files,
    COUNT(CASE WHEN ws.state = 'deleted' THEN 1 END) as deleted_files,
    COUNT(CASE WHEN ws.state = 'conflicted' THEN 1 END) as conflicted_files
FROM vcs_working_state_new ws
JOIN projects p ON ws.project_id = p.id
JOIN vcs_branches vb ON ws.branch_id = vb.id
GROUP BY ws.project_id, ws.branch_id;

CREATE VIEW IF NOT EXISTS vcs_unstaged_changes_view AS
SELECT
    ws.id,
    ws.project_id,
    p.slug as project_slug,
    ws.branch_id,
    vb.branch_name,
    ws.file_id,
    pf.file_path,
    ws.state,
    ws.content_hash,
    ws.file_size_bytes,
    ws.line_count,
    ws.last_modified
FROM vcs_working_state_new ws
JOIN projects p ON ws.project_id = p.id
JOIN vcs_branches vb ON ws.branch_id = vb.id
JOIN project_files pf ON ws.file_id = pf.id
WHERE ws.staged = 0 AND ws.state != 'unmodified';

CREATE VIEW IF NOT EXISTS vibe_code_generation_view AS
SELECT
    cs.session_id,
    vs.session_name,
    p.slug as project_slug,
    cs.language,
    COUNT(*) as snippet_count,
    SUM(cs.line_count) as total_lines,
    SUM(CASE WHEN cs.was_applied = 1 THEN 1 ELSE 0 END) as applied_count,
    SUM(CASE WHEN cs.was_applied = 1 THEN cs.line_count ELSE 0 END) as applied_lines,
    ROUND(100.0 * SUM(CASE WHEN cs.was_applied = 1 THEN 1 ELSE 0 END) / COUNT(*), 2) as application_rate_pct
FROM vibe_interaction_code_snippets cs
JOIN vibe_sessions vs ON cs.session_id = vs.id
JOIN projects p ON vs.project_id = p.id
GROUP BY cs.session_id, cs.language
ORDER BY snippet_count DESC;

CREATE VIEW IF NOT EXISTS vibe_conversation_view AS
SELECT
    ci.id,
    ci.session_id,
    vs.session_name,
    p.slug as project_slug,
    p.name as project_name,
    ci.interaction_sequence,
    ci.interaction_type,
    ci.role,
    ci.content,
    ci.tool_name,
    ci.related_files,
    ci.tokens_input,
    ci.tokens_output,
    ci.latency_ms,
    ci.created_at,
    ip.turn_number,
    ip.was_helpful,
    ip.led_to_commit,
    ip.tool_calls_count
FROM vibe_claude_interactions ci
JOIN vibe_sessions vs ON ci.session_id = vs.id
JOIN projects p ON vs.project_id = p.id
LEFT JOIN vibe_interaction_pairs ip ON (
    ip.prompt_interaction_id = ci.id OR
    ip.response_interaction_id = ci.id
)
ORDER BY ci.session_id, ci.interaction_sequence;

CREATE VIEW IF NOT EXISTS vibe_reusable_patterns_view AS
SELECT
    p.slug as project_slug,
    cs.language,
    cs.snippet_type,
    COUNT(DISTINCT cs.session_id) as sessions_used,
    COUNT(*) as total_occurrences,
    SUM(CASE WHEN cs.was_applied = 1 THEN 1 ELSE 0 END) as times_applied,
    GROUP_CONCAT(DISTINCT t.topic_name) as related_topics,
    cs.code_content as example_code
FROM vibe_interaction_code_snippets cs
JOIN vibe_sessions vs ON cs.session_id = vs.id
JOIN projects p ON vs.project_id = p.id
LEFT JOIN vibe_interaction_topics t ON t.session_id = cs.session_id
WHERE cs.was_applied = 1
GROUP BY p.id, cs.language, cs.snippet_type, cs.code_content
HAVING sessions_used > 1
ORDER BY sessions_used DESC, times_applied DESC;

CREATE VIEW IF NOT EXISTS vibe_session_quality_view AS
SELECT
    vs.id as session_id,
    vs.session_name,
    p.slug as project_slug,
    vss.total_interactions,
    vss.user_prompts,
    vss.assistant_responses,
    vss.tool_uses,
    vss.total_tokens,
    vss.avg_response_latency_ms,
    vss.total_errors,
    COUNT(DISTINCT ip.id) as total_turns,
    SUM(CASE WHEN ip.was_helpful = 1 THEN 1 ELSE 0 END) as helpful_responses,
    SUM(CASE WHEN ip.led_to_commit = 1 THEN 1 ELSE 0 END) as productive_turns,
    ROUND(100.0 * SUM(CASE WHEN ip.was_helpful = 1 THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 2) as helpfulness_pct,
    vss.first_interaction_at,
    vss.last_interaction_at,
    CAST((julianday(vss.last_interaction_at) - julianday(vss.first_interaction_at)) * 24 * 60 AS INTEGER) as session_duration_minutes
FROM vibe_sessions vs
JOIN projects p ON vs.project_id = p.id
LEFT JOIN vibe_session_stats vss ON vss.session_id = vs.id
LEFT JOIN vibe_interaction_pairs ip ON ip.session_id = vs.id
GROUP BY vs.id;

CREATE VIEW IF NOT EXISTS vibe_session_timeline_view AS
SELECT
    vse.id,
    vse.session_id,
    vs.session_name,
    vse.event_type,
    vse.event_data,
    vse.occurred_at,
    CAST((julianday(vse.occurred_at) - julianday(vs.started_at)) * 24 * 60 AS INTEGER) as minutes_since_start
FROM vibe_session_events vse
JOIN vibe_sessions vs ON vse.session_id = vs.id
ORDER BY vse.occurred_at DESC;

CREATE VIEW IF NOT EXISTS vibe_tool_usage_view AS
SELECT
    ci.session_id,
    vs.session_name,
    p.slug as project_slug,
    ci.tool_name,
    COUNT(*) as usage_count,
    AVG(ci.latency_ms) as avg_latency_ms,
    SUM(CASE WHEN ci.tool_success = 1 THEN 1 ELSE 0 END) as success_count,
    SUM(CASE WHEN ci.tool_success = 0 THEN 1 ELSE 0 END) as failure_count,
    MIN(ci.created_at) as first_used,
    MAX(ci.created_at) as last_used
FROM vibe_claude_interactions ci
JOIN vibe_sessions vs ON ci.session_id = vs.id
JOIN projects p ON vs.project_id = p.id
WHERE ci.tool_name IS NOT NULL
GROUP BY ci.session_id, ci.tool_name
ORDER BY usage_count DESC;

CREATE VIEW IF NOT EXISTS vibe_topics_view AS
SELECT
    t.id,
    t.session_id,
    vs.session_name,
    p.slug as project_slug,
    t.topic_name,
    t.topic_category,
    t.confidence,
    t.interaction_count,
    t.keywords,
    t.created_at,
    ci_first.content as first_mention,
    ci_last.content as last_mention
FROM vibe_interaction_topics t
JOIN vibe_sessions vs ON t.session_id = vs.id
JOIN projects p ON vs.project_id = p.id
LEFT JOIN vibe_claude_interactions ci_first ON t.first_interaction_id = ci_first.id
LEFT JOIN vibe_claude_interactions ci_last ON t.last_interaction_id = ci_last.id
ORDER BY t.session_id, t.created_at;

CREATE VIEW IF NOT EXISTS work_item_stats_view AS
SELECT
    p.slug as project_slug,
    p.name as project_name,
    COUNT(*) as total_items,
    SUM(CASE WHEN wi.status = 'pending' THEN 1 ELSE 0 END) as pending_count,
    SUM(CASE WHEN wi.status = 'in_progress' THEN 1 ELSE 0 END) as in_progress_count,
    SUM(CASE WHEN wi.status = 'completed' THEN 1 ELSE 0 END) as completed_count,
    SUM(CASE WHEN wi.status = 'blocked' THEN 1 ELSE 0 END) as blocked_count,
    SUM(CASE WHEN wi.priority = 'critical' THEN 1 ELSE 0 END) as critical_count,
    SUM(CASE WHEN wi.priority = 'high' THEN 1 ELSE 0 END) as high_priority_count
FROM projects p
LEFT JOIN work_items wi ON p.id = wi.project_id
GROUP BY p.id;

CREATE VIEW IF NOT EXISTS work_items_with_prompts_view AS
SELECT
    wi.id as work_item_id,
    wi.title,
    wi.status,
    wi.project_id,
    p.slug as project_slug,
    wip.id as prompt_id,
    COALESCE(wip.custom_prompt, pt.prompt_text) as prompt_text,
    pt.name as template_name,
    wip.variable_overrides,
    wip.priority as prompt_priority,
    wip.created_at as prompt_created_at
FROM work_items wi
JOIN projects p ON wi.project_id = p.id
LEFT JOIN work_item_prompts wip ON wi.id = wip.work_item_id AND wip.is_active = 1
LEFT JOIN prompt_templates pt ON wip.template_id = pt.id
WHERE wi.status IN ('pending', 'assigned', 'in_progress');

CREATE TRIGGER IF NOT EXISTS decrement_blob_reference
AFTER DELETE ON file_contents
FOR EACH ROW
BEGIN
    UPDATE content_blobs
    SET reference_count = reference_count - 1
    WHERE hash_sha256 = OLD.content_hash;
END;

CREATE TRIGGER IF NOT EXISTS encryption_key_used_trigger
AFTER INSERT ON encryption_key_audit
WHEN NEW.action IN ('decrypt', 'export', 'edit') AND NEW.success = 1
BEGIN
    UPDATE encryption_keys
    SET last_used_at = datetime('now')
    WHERE id = NEW.key_id;
END;

CREATE TRIGGER IF NOT EXISTS enforce_single_active_deployment
BEFORE INSERT ON system_deployments
WHEN NEW.is_active = 1
BEGIN
    UPDATE system_deployments
    SET is_active = 0
    WHERE project_id = NEW.project_id AND is_active = 1;
END;

CREATE TRIGGER IF NOT EXISTS file_contents_fts_delete
AFTER DELETE ON content_blobs
BEGIN
    DELETE FROM file_contents_fts WHERE rowid = OLD.rowid;
END;

CREATE TRIGGER IF NOT EXISTS file_contents_fts_update
AFTER UPDATE ON content_blobs
WHEN NEW.content_type = 'text' AND NEW.content_text IS NOT NULL
BEGIN
    -- Update existing FTS entry
    UPDATE file_contents_fts
    SET file_path = (
        SELECT COALESCE(pf.file_path, 'unknown')
        FROM file_contents fc
        LEFT JOIN project_files pf ON fc.file_id = pf.id
        WHERE fc.content_hash = NEW.hash_sha256 AND fc.is_current = 1
        LIMIT 1
    ),
    content_text = NEW.content_text
    WHERE rowid = NEW.rowid;
END;

CREATE TRIGGER IF NOT EXISTS increment_blob_reference
AFTER INSERT ON file_contents
FOR EACH ROW
BEGIN
    UPDATE content_blobs
    SET reference_count = reference_count + 1
    WHERE hash_sha256 = NEW.content_hash;
END;

CREATE TRIGGER IF NOT EXISTS mark_broken_refs_on_delete
AFTER DELETE ON readme_files
BEGIN
    UPDATE readme_references
    SET is_broken = 1,
        last_verified_at = datetime('now')
    WHERE target_readme_id = OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS nix_configs_updated_at
        AFTER UPDATE ON nix_configs
        BEGIN
          UPDATE nix_configs SET updated_at = datetime('now') WHERE id = NEW.id;
        END;

CREATE TRIGGER IF NOT EXISTS nixops4_calculate_deployment_duration
AFTER UPDATE OF completed_at ON nixops4_deployments
WHEN NEW.completed_at IS NOT NULL AND OLD.completed_at IS NULL
BEGIN
    UPDATE nixops4_deployments
    SET duration_seconds = CAST((julianday(NEW.completed_at) - julianday(NEW.started_at)) * 86400 AS INTEGER)
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS nixops4_calculate_machine_build_duration
AFTER UPDATE OF build_completed_at ON nixops4_machine_deployments
WHEN NEW.build_completed_at IS NOT NULL AND OLD.build_completed_at IS NULL
BEGIN
    UPDATE nixops4_machine_deployments
    SET build_duration_seconds = CAST((julianday(NEW.build_completed_at) - julianday(NEW.build_started_at)) * 86400 AS INTEGER)
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS nixops4_calculate_machine_deploy_duration
AFTER UPDATE OF deploy_completed_at ON nixops4_machine_deployments
WHEN NEW.deploy_completed_at IS NOT NULL AND OLD.deploy_completed_at IS NULL
BEGIN
    UPDATE nixops4_machine_deployments
    SET deploy_duration_seconds = CAST((julianday(NEW.deploy_completed_at) - julianday(NEW.deploy_started_at)) * 86400 AS INTEGER)
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS nixops4_local_services_allocate_port
  AFTER INSERT ON nixops4_local_services
  FOR EACH ROW
  WHEN NEW.port_mapping IS NOT NULL
  BEGIN
    -- This will be handled by the service manager in Python
    -- Trigger just logs the event for audit
    SELECT 1; -- Placeholder
  END;

CREATE TRIGGER IF NOT EXISTS nixops4_local_services_updated
  AFTER UPDATE ON nixops4_local_services
  FOR EACH ROW
  BEGIN
    UPDATE nixops4_local_services
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
  END;

CREATE TRIGGER IF NOT EXISTS nixops4_machines_set_local_flag
  AFTER INSERT ON nixops4_machines
  FOR EACH ROW
  WHEN NEW.system_type = 'localhost'
  BEGIN
    UPDATE nixops4_machines
    SET is_local = TRUE
    WHERE id = NEW.id;
  END;

CREATE TRIGGER IF NOT EXISTS nixops4_network_profiles_updated
  AFTER UPDATE ON nixops4_network_profiles
  FOR EACH ROW
  BEGIN
    UPDATE nixops4_network_profiles
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
  END;

CREATE TRIGGER IF NOT EXISTS nixops4_update_machine_timestamp
AFTER UPDATE ON nixops4_machines
FOR EACH ROW
BEGIN
    UPDATE nixops4_machines
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS nixops4_update_network_timestamp
AFTER UPDATE ON nixops4_machines
BEGIN
    UPDATE nixops4_networks
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.network_id;
END;

CREATE TRIGGER IF NOT EXISTS projects_updated_at
        AFTER UPDATE ON projects
        BEGIN
          UPDATE projects SET updated_at = datetime('now') WHERE id = NEW.id;
        END;

CREATE TRIGGER IF NOT EXISTS record_work_item_transition
AFTER UPDATE OF status ON work_items
WHEN OLD.status != NEW.status
BEGIN
    INSERT INTO work_item_transitions (
        work_item_id,
        from_status,
        to_status,
        changed_by,
        transitioned_at
    ) VALUES (
        NEW.id,
        OLD.status,
        NEW.status,
        NEW.assigned_to,
        datetime('now')
    );

    -- Update timestamps based on new status
    UPDATE work_items
    SET
        assigned_at = CASE WHEN NEW.status = 'assigned' THEN datetime('now') ELSE assigned_at END,
        started_at = CASE WHEN NEW.status = 'in_progress' THEN datetime('now') ELSE started_at END,
        completed_at = CASE WHEN NEW.status = 'completed' THEN datetime('now') ELSE completed_at END
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_branch_head_on_commit
AFTER INSERT ON vcs_commits
FOR EACH ROW
BEGIN
    UPDATE vcs_branches
    SET head_commit_id = NEW.id
    WHERE id = NEW.branch_id;
END;

CREATE TRIGGER IF NOT EXISTS update_cache_last_used
AFTER UPDATE ON deployment_cache
WHEN NEW.use_count > OLD.use_count
BEGIN
    UPDATE deployment_cache
    SET last_used_at = datetime('now')
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_commit_metadata_timestamp
AFTER UPDATE ON vcs_commit_metadata
FOR EACH ROW
BEGIN
    UPDATE vcs_commit_metadata
    SET updated_at = datetime('now')
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_deployment_targets_updated_at
AFTER UPDATE ON deployment_targets
FOR EACH ROW
BEGIN
    UPDATE deployment_targets SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_dns_records_updated_at
AFTER UPDATE ON dns_records
BEGIN
    UPDATE dns_records SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_file_metadata_timestamp
AFTER UPDATE ON file_metadata
FOR EACH ROW
BEGIN
    UPDATE file_metadata SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_nixos_managed_packages_timestamp
AFTER UPDATE ON nixos_managed_packages
BEGIN
    UPDATE nixos_managed_packages
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_project_domains_updated_at
AFTER UPDATE ON project_domains
BEGIN
    UPDATE project_domains SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_project_files_updated_at
AFTER UPDATE ON project_files
FOR EACH ROW
BEGIN
    UPDATE project_files SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_readme_files_timestamp
AFTER UPDATE ON readme_files
BEGIN
    UPDATE readme_files SET updated_at = datetime('now') WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_session_stats_on_interaction
AFTER INSERT ON vibe_claude_interactions
BEGIN
    INSERT INTO vibe_session_stats (session_id, updated_at)
    VALUES (NEW.session_id, datetime('now'))
    ON CONFLICT(session_id) DO UPDATE SET
        total_interactions = total_interactions + 1,
        user_prompts = user_prompts + CASE WHEN NEW.role = 'user' THEN 1 ELSE 0 END,
        assistant_responses = assistant_responses + CASE WHEN NEW.role = 'assistant' THEN 1 ELSE 0 END,
        tool_uses = tool_uses + CASE WHEN NEW.tool_name IS NOT NULL THEN 1 ELSE 0 END,
        total_tokens = total_tokens + COALESCE(NEW.tokens_input, 0) + COALESCE(NEW.tokens_output, 0),
        total_code_blocks = total_code_blocks + COALESCE(NEW.code_blocks_count, 0),
        total_errors = total_errors + CASE WHEN NEW.contains_error = 1 THEN 1 ELSE 0 END,
        last_interaction_at = NEW.created_at,
        first_interaction_at = COALESCE(first_interaction_at, NEW.created_at),
        updated_at = datetime('now');
END;

CREATE TRIGGER IF NOT EXISTS update_system_config_timestamp
AFTER UPDATE ON system_config
BEGIN
    UPDATE system_config SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS update_work_item_timestamp
AFTER UPDATE ON work_items
FOR EACH ROW
BEGIN
    UPDATE work_items
    SET updated_at = datetime('now')
    WHERE id = NEW.id;
END;

