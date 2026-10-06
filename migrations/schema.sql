-- TempleDB canonical schema
-- Generated from live database, sourced with migrations 001-125 applied.
-- Regenerate after adding any new migration:
--     python3 scripts/regen_schema.py
--
-- FTS5 shadow tables (_data/_idx/_content/_docsize/_config) and cr-sqlite
-- internals are excluded deliberately. CREATE VIRTUAL TABLE generates the
-- former; emitting them directly fails with 'object name reserved for
-- internal use'. The latter is extension state rather than schema.
--
-- Staleness here is SILENT: on a fresh DB the Migrator applies this file and
-- then marks every numbered migration applied via a synthetic 'via-schema.sql'
-- hash, so anything missing simply never runs and the install still succeeds.
-- That failure mode has bitten twice (075-082, then 084-125). Use --check in CI.

-- ======================================================================
-- Tables (132)
-- ======================================================================

CREATE TABLE IF NOT EXISTS agent_events (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES agent_runs(id),
    sequence_number INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    summary TEXT,
    payload_json TEXT,
    raw_payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(run_id, sequence_number)
);

CREATE TABLE IF NOT EXISTS agent_messages (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES agent_sessions(id),
    run_id INTEGER REFERENCES agent_runs(id),
    sequence_number INTEGER NOT NULL,
    role TEXT NOT NULL,
    content_text TEXT NOT NULL DEFAULT '',
    content_format TEXT NOT NULL DEFAULT 'org',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, sequence_number)
);

CREATE TABLE IF NOT EXISTS agent_notifications (
    id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES agent_sessions(id),
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    body_md TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    -- Send state
    sent_at TEXT,
    send_error TEXT,
    send_attempts INTEGER NOT NULL DEFAULT 0,

    -- Decision-point fields (only meaningful when kind='decision')
    pending_until TEXT,          -- ISO timestamp; NULL = not a wait
    decision_default TEXT,       -- 'approve' | 'deny' — used on timeout
    decided_at TEXT,
    decision TEXT                -- 'approve' | 'deny' | 'timeout'
);

CREATE TABLE IF NOT EXISTS agent_pending_asks (
    ask_id TEXT PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES agent_sessions(id),
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    response TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    responded_at TEXT,
    dispatched_at TEXT
);

CREATE TABLE IF NOT EXISTS agent_pending_events (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES agent_sessions(id),
    event_type TEXT NOT NULL,     -- e.g. 'agent.section.finding.add'
    payload_json TEXT NOT NULL,   -- JSON dict, becomes event.data
    summary TEXT,                 -- optional short summary line
    dispatched_at TEXT,           -- NULL until forwarded to Emacs
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_providers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    provider_kind TEXT NOT NULL,
    executable TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    config_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES agent_sessions(id),
    status TEXT NOT NULL,
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at TEXT,
    last_event_sequence INTEGER NOT NULL DEFAULT 0,
    error_text TEXT
);

CREATE TABLE IF NOT EXISTS agent_session_notes (
    session_id INTEGER PRIMARY KEY REFERENCES agent_sessions(id),
    goal_org TEXT,
    notes_org TEXT,
    scratch_org TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_session_sections (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES agent_sessions(id),
    -- Section id as seen by Emacs. One of:
    --   'findings' | 'todo' | 'open-questions'
    --   'dynamic:NAME' for agent-created dynamic sections
    section TEXT NOT NULL,
    entry_id TEXT NOT NULL,
    -- Full entry as JSON dict. Shape depends on section:
    --   findings:       {text, refs?}
    --   todo:           {text, priority?, done?}
    --   open-questions: {text, answered?, answer?}
    --   dynamic:*:      {text}
    entry_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, section, entry_id)
);

CREATE TABLE IF NOT EXISTS agent_sessions (
    id INTEGER PRIMARY KEY,
    session_uuid TEXT NOT NULL UNIQUE,
    project_id INTEGER REFERENCES projects(id),
    provider_id INTEGER NOT NULL REFERENCES agent_providers(id),
    external_session_id TEXT,
    title TEXT,
    status TEXT NOT NULL DEFAULT 'created',
    model TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_user_edits (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES agent_sessions(id),
    -- Section id as seen by Emacs. Matches agent_session_sections.section.
    section TEXT NOT NULL,
    -- The specific entry that was edited, or NULL for section-scope events
    -- (e.g. section-wide clear).
    entry_id TEXT,
    -- One of: 'removed' | 'marked_done' | 'edited' | 'promoted' | 'section_cleared'
    action TEXT NOT NULL,
    -- Snapshot of the entry BEFORE the edit, as JSON. NULL for actions
    -- that don't need before-state (e.g. section-cleared).
    before_json TEXT,
    -- Was this row already surfaced to the agent in a message.send?
    -- NULL = not yet consumed. Timestamp = when it was included in a
    -- system note. Consumed rows stick around for audit.
    consumed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS agent_work_log (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES agent_sessions(id),
    run_id INTEGER REFERENCES agent_runs(id),
    project_id INTEGER REFERENCES projects(id),
    -- What was asked
    user_message TEXT,
    -- What was done
    summary TEXT,
    tools_used TEXT,           -- JSON array of tool names
    files_read TEXT,           -- JSON array of file paths
    files_modified TEXT,       -- JSON array of file paths
    commands_run TEXT,         -- JSON array of bash commands
    -- Outcome
    assistant_response_preview TEXT,  -- first 500 chars of response
    status TEXT NOT NULL DEFAULT 'completed',  -- completed, failed, cancelled
    -- Stats
    cost_usd REAL,
    input_tokens INTEGER,
    output_tokens INTEGER,
    duration_ms INTEGER,
    num_turns INTEGER,
    -- Timestamps
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ast_builds (
    id                  INTEGER PRIMARY KEY,
    output_hash         TEXT NOT NULL,
    host_name           TEXT NOT NULL,
    scopes              TEXT NOT NULL,           -- JSON array of emitted scopes
    ast_snapshot_hash   TEXT,                    -- reserved; NULL in phase 1
    output_path         TEXT NOT NULL,
    manifest_json       TEXT NOT NULL,
    nix_buildable       INTEGER,                 -- 1 ok, 0 failed, NULL not attempted
    nix_build_error     TEXT,
    generated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    promoted_at         TIMESTAMP,
    deployment_id       INTEGER,
    UNIQUE(output_hash, host_name)
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

CREATE TABLE IF NOT EXISTS blue_green_state (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    target TEXT NOT NULL,                    -- deployment target name
    active_slot TEXT NOT NULL DEFAULT 'blue', -- 'blue' or 'green'

    -- Per-slot version tracking
    blue_version TEXT,                       -- content hash or commit of blue deploy
    blue_deployed_at TIMESTAMP,
    green_version TEXT,
    green_deployed_at TIMESTAMP,

    -- Swap history
    last_swap_at TIMESTAMP,
    swap_count INTEGER DEFAULT 0,

    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(project_id, target)
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
    is_active BOOLEAN DEFAULT 1, kind TEXT NOT NULL DEFAULT 'scratch', session_id INTEGER REFERENCES vcs_sessions(id),
    UNIQUE(project_id, checkout_path)
);

CREATE TABLE IF NOT EXISTS claim_evidence (
    id              INTEGER PRIMARY KEY,
    claim_id        INTEGER NOT NULL REFERENCES claims(id) ON DELETE CASCADE,

    -- 'TestRun'  -> test_runs.id
    -- 'AstBuild' -> '<host_name>/<output_hash>'  (matches the AstBuild entity ref)
    -- 'WorkLog'  -> agent_work_log.id
    evidence_kind   TEXT NOT NULL,
    evidence_ref    TEXT NOT NULL,

    -- 'undercuts' lets a claim carry its own contrary evidence rather
    -- than the author silently omitting it.
    role            TEXT NOT NULL DEFAULT 'supports'
                      CHECK (role IN ('supports', 'undercuts')),

    -- Fingerprint captured at assertion time. When phase 2 lands, a
    -- mismatch here means the evidence moved under the claim and the
    -- warrant must fail loudly rather than pass against different
    -- bytes than the asserter saw.
    evidence_hash   TEXT,

    observed_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(claim_id, evidence_kind, evidence_ref)
);

CREATE TABLE IF NOT EXISTS claims (
    id              INTEGER PRIMARY KEY,

    -- The proposition, asserted not hedged.
    statement       TEXT NOT NULL,

    -- ---- Scope: what the claim is about --------------------------
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    commit_id       INTEGER NOT NULL REFERENCES vcs_commits(id),
    host_name       TEXT,               -- NULL = host-independent
    inputs_json     TEXT,               -- template values, flags, env

    -- ---- Warrant: names the inference rule, not the conclusion ----
    -- Checkers land in phase 2, keyed by this column. 'asserted' means
    -- there is no predicate and never will be — an agent's say-so,
    -- recorded as such so it is distinguishable from a checked claim.
    warrant_kind    TEXT NOT NULL,
    warrant_gloss   TEXT,

    -- ---- Attribution (optional) ----------------------------------
    -- report_ref is an attribution, NOT a parent. Claims are produced
    -- by work, which happens constantly; reports are authored, which
    -- happens rarely. Requiring a report would throttle claim creation
    -- to human writing speed.
    asserted_by     TEXT NOT NULL,      -- 'test_runner', 'ast_build_service', agent ref
    report_ref      TEXT,               -- entities.external_ref of a Report

    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),

    -- Re-running the same work at the same revision is a re-observation,
    -- not a second claim.
    UNIQUE(project_id, commit_id, statement)
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

CREATE TABLE IF NOT EXISTS config_checkouts (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    checkout_dir TEXT NOT NULL UNIQUE,    -- e.g., ~/.config/templedb/checkouts/emacs-config
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(project_id)  -- One checkout per project for config links
);

CREATE TABLE IF NOT EXISTS config_hosts (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    parent_id   INTEGER REFERENCES config_hosts(id),
    hw_config   TEXT,           -- relative path to hardware-configuration.nix
    description TEXT
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

CREATE TABLE IF NOT EXISTS config_node_owners (
    node_id     INTEGER REFERENCES config_nodes(id) ON DELETE CASCADE,
    project_id  INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    PRIMARY KEY (node_id, project_id)
);

CREATE TABLE IF NOT EXISTS "config_nodes" (
    id          INTEGER PRIMARY KEY,
    parent_id   INTEGER REFERENCES "config_nodes"(id) ON DELETE CASCADE,
    name        TEXT,
    sort_order  INTEGER DEFAULT 0,

    node_type   TEXT NOT NULL
                CHECK(node_type IN (
                    'AttrSet', 'RecAttrSet', 'List',
                    'Bool', 'Int', 'Float', 'String', 'MultilineString',
                    'Path', 'Null',
                    'Package', 'Identifier',
                    'FnCall', 'FnDef', 'LetIn', 'Binding', 'With',
                    'Import', 'Interpolation', 'Conditional', 'Assert',
                    'BinOp', 'UnaryOp', 'Select', 'HasAttr', 'Inherit',
                    'RawNix'
                )),

    value       TEXT,
    callee      TEXT,
    operator    TEXT CHECK(operator IN (
        '//', '++', '+', '-', '*', '/',
        '==', '!=', '<', '<=', '>', '>=',
        '&&', '||', '->',
        '!', NULL
    )),

    scope       TEXT CHECK(scope IN ('system', 'home', 'flake', NULL)),
    host_id     INTEGER REFERENCES config_hosts(id) ON DELETE CASCADE,
    enabled     BOOLEAN DEFAULT 1,

    description TEXT,
    category    TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(parent_id, name, host_id)
);

CREATE TABLE IF NOT EXISTS config_roots (
    id          INTEGER PRIMARY KEY,
    scope       TEXT NOT NULL UNIQUE CHECK(scope IN ('system', 'home', 'flake')),
    node_id     INTEGER NOT NULL REFERENCES config_nodes(id),
    description TEXT
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

CREATE TABLE IF NOT EXISTS deploy_stage_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_kind          TEXT NOT NULL,       -- see enum below
    slug                TEXT NOT NULL,       -- project this run affected
    session_id          INTEGER,             -- REFERENCES vcs_sessions(id), nullable for
                                             -- stages outside a VCS session (e.g. nix_build)
    input_hash          TEXT,                -- 12+ chars; NULL if stage has no input
    output_hash         TEXT,                -- 12+ chars; NULL on hard failure
    prev_stage_run_id   INTEGER REFERENCES deploy_stage_runs(id),  -- chain pointer
    started_at          TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at            TEXT,                -- NULL = in progress
    outcome             TEXT,                -- 'success' | 'noop' | 'failed'
    metadata_json       TEXT                 -- stage-specific detail (file count, etc.)
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
    deployment_snapshot TEXT, branch_name TEXT, triggered_by TEXT DEFAULT 'manual',  -- JSON snapshot of what was deployed

    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS deployment_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,  -- NULL = global
    event TEXT NOT NULL,                -- 'deploy.success', 'deploy.failure', 'deploy.rollback', 'deploy.*'
    notification_type TEXT NOT NULL,    -- 'webhook', 'command'
    config TEXT NOT NULL,               -- JSON: {"url": "..."} or {"command": "..."}
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now'))
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

CREATE TABLE IF NOT EXISTS deployment_triggers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    branch_pattern TEXT NOT NULL,       -- glob pattern: 'main', 'release/*', '*'
    target_name TEXT NOT NULL,          -- deployment target to trigger
    enabled INTEGER NOT NULL DEFAULT 1,
    auto_rollback INTEGER NOT NULL DEFAULT 0,  -- rollback on health check failure
    require_health_check INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_id, branch_pattern, target_name)
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

CREATE TABLE IF NOT EXISTS edge_function_deployments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    target TEXT NOT NULL,                    -- deployment target (staging, production)
    function_name TEXT NOT NULL,             -- e.g. 'chat-with-book', 'stripe-webhook'
    content_hash TEXT NOT NULL,              -- sha256 of function source files
    file_count INTEGER,                     -- number of source files
    status TEXT NOT NULL DEFAULT 'pending',  -- 'success', 'failed', 'pending'
    message TEXT,                            -- stdout/stderr snippet
    duration_seconds REAL,                  -- deploy time
    deployed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- metadata
    deployed_by TEXT DEFAULT 'templedb'
);

CREATE TABLE IF NOT EXISTS edit_intents (
    id                INTEGER PRIMARY KEY,
    session_id        INTEGER REFERENCES vcs_sessions(id),
    project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    file_path         TEXT NOT NULL,

    -- What the intent proposes
    base_revision     TEXT NOT NULL DEFAULT 'current',
    new_content_hash  TEXT NOT NULL,
    patch_summary     TEXT,

    -- Metadata
    author            TEXT,
    description       TEXT,

    -- Lifecycle
    status            TEXT NOT NULL DEFAULT 'proposed'
                        CHECK (status IN ('proposed', 'applied', 'cancelled')),
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    applied_at        TEXT,
    cancelled_at      TEXT,

    -- If applied via templedb VCS, points at the commit that recorded it
    applied_commit_id INTEGER REFERENCES vcs_commits(id)
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

CREATE TABLE IF NOT EXISTS editor_sessions (
    id INTEGER PRIMARY KEY,
    hostname TEXT NOT NULL,
    project_slug TEXT,
    -- Open buffers (JSON array of {file, point, mark, mode})
    open_buffers TEXT,
    -- Window layout (JSON: split config + buffer assignments)
    window_layout TEXT,
    -- Active project context
    active_project TEXT,
    last_branch TEXT,
    -- Metadata
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(hostname)
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

CREATE TABLE IF NOT EXISTS entities (
    id                INTEGER PRIMARY KEY,

    -- What kind of thing this entity is. Values are conventional,
    -- not enforced: 'File', 'Commit', 'AgentSession', 'EditIntent',
    -- 'Machine', 'Deployment', 'StorePath', 'Symbol', 'Report', ...
    kind              TEXT NOT NULL,

    -- Reference to the underlying typed table's identifier when
    -- there is one. For 'File' this is project_files.id serialized;
    -- for 'Commit' it's vcs_commits.id; for 'EditIntent' it's
    -- edit_intents.id; for 'Report' it might be a relative HTML
    -- path. Stored as TEXT so heterogeneous ID types coexist.
    external_ref      TEXT,

    -- Which authority owns this entity's canonical state. See the
    -- design doc for the local-algebras framing. Common values:
    --   'git'           — source content
    --   'nix'           — build artifacts, store paths, closures
    --   'agent-runtime' — sessions, tool calls, edit intents
    --   'author'        — reports, decisions
    --   'templedb'      — projects, machines, config metadata
    --   'machine'       — running-state facts observed via SSH probe
    source_authority  TEXT NOT NULL,

    -- Human-friendly display label. Optional; the CLI falls back
    -- to (kind, external_ref) when null.
    label             TEXT,

    -- Last time TempleDB observed this entity from its authority.
    -- Freshness telemetry per fact — critical for reconcile.
    observed_at       TEXT NOT NULL DEFAULT (datetime('now')),
    created_at        TEXT NOT NULL DEFAULT (datetime('now')), attributes_json TEXT, sync_scope TEXT
    CHECK (sync_scope IN ('fleet', 'machine-local', 'none')),

    UNIQUE(kind, external_ref)
);

CREATE TABLE IF NOT EXISTS entity_deletions (
    id                INTEGER PRIMARY KEY,
    -- The id the entity had. Not a FK, and not unique: ids are reused
    -- by SQLite after deletion, so (entity_id, deleted_at) is what
    -- identifies an event.
    entity_id         INTEGER NOT NULL,
    entity_kind       TEXT    NOT NULL,
    entity_ref        TEXT    NOT NULL,
    label             TEXT,
    source_authority  TEXT    NOT NULL,
    -- Which code path removed it: 'graph_forget' | 'prune_orphans'.
    -- A gap in this table next to a drop in entity counts therefore
    -- means "not deleted through the CLI", which is the single most
    -- useful thing to know when counts move unexpectedly.
    deleted_via       TEXT    NOT NULL,
    reason            TEXT    NOT NULL,
    -- Relations lost to FK CASCADE. Recorded because the relation rows
    -- leave no trace of their own.
    relations_removed INTEGER NOT NULL DEFAULT 0,
    deleted_at        TEXT    NOT NULL DEFAULT (datetime('now'))
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

CREATE TABLE IF NOT EXISTS "fleet_deployments" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network_id INTEGER NOT NULL REFERENCES "fleet_networks"(id) ON DELETE CASCADE,

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

CREATE TABLE IF NOT EXISTS "fleet_local_services" (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  network_id INTEGER NOT NULL REFERENCES "fleet_networks"(id) ON DELETE CASCADE,
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

CREATE TABLE IF NOT EXISTS "fleet_machine_deployments" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    deployment_id INTEGER NOT NULL REFERENCES "fleet_deployments"(id) ON DELETE CASCADE,
    machine_id INTEGER NOT NULL REFERENCES "fleet_machines"(id) ON DELETE CASCADE,

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

CREATE TABLE IF NOT EXISTS "fleet_machines" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network_id INTEGER NOT NULL REFERENCES "fleet_networks"(id) ON DELETE CASCADE,

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

CREATE TABLE IF NOT EXISTS "fleet_networks" (
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

CREATE TABLE IF NOT EXISTS "fleet_resources" (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    network_id INTEGER NOT NULL REFERENCES "fleet_networks"(id) ON DELETE CASCADE,
    machine_id INTEGER REFERENCES "fleet_machines"(id) ON DELETE CASCADE,  -- null for network-level resources

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

CREATE TABLE IF NOT EXISTS graph_query_log (
    id INTEGER PRIMARY KEY,
    command TEXT NOT NULL,          -- e.g. 'graph.who-uses', 'graph.callers'
    target_kind TEXT,               -- 'env_var', 'secret', 'symbol', 'file', 'project'
    target_key TEXT,                -- normalized target value (name / path / slug)
    project_slug TEXT,              -- optional scoping context
    args_json TEXT,                 -- full args snapshot (JSON) for future use
    executed_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS handoff_notes (
    id              INTEGER PRIMARY KEY,

    -- Sender identity. from_session is TEMPLEDB_SESSION_ID or a
    -- fallback derived from (host, ppid) if the env var isn't set.
    from_session    TEXT NOT NULL,
    from_actor      TEXT,   -- 'claude-code', 'vibe', 'human', 'temple-agent'

    -- Destination. Exactly one of to_session / to_topic / (both NULL
    -- = broadcast) is typical. Convention, not enforced, so a note
    -- can address both a session AND a topic if useful.
    to_session      TEXT,
    to_topic        TEXT,   -- 'templedb', 'refactor:foo', ...

    -- Content
    subject         TEXT NOT NULL,
    body            TEXT NOT NULL,
    tags            TEXT,   -- comma-separated

    -- Cross-references into other authoritative objects
    ref_report      TEXT,   -- reports/YYYY-MM-DD-HHMM-slug.html
    ref_commit      TEXT,   -- commit hash prefix or full
    ref_file        TEXT,   -- project_slug:path
    project_id      INTEGER REFERENCES projects(id),

    -- Lifecycle
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    read_at         TEXT,
    acked_at        TEXT,
    expires_at      TEXT
);

CREATE TABLE IF NOT EXISTS hygiene_snapshots (
    id                INTEGER PRIMARY KEY,

    -- Which project's graph is being summarized
    slug              TEXT NOT NULL,

    -- When the snapshot was taken
    taken_at          TEXT NOT NULL DEFAULT (datetime('now')),

    -- Counts (all NULLable so future adapters can partial-populate)
    total_imports     INTEGER,
    dead_candidates   INTEGER,
    symbol_defines    INTEGER,
    inherits_edges    INTEGER,

    -- Version of the python ingest adapter that produced the
    -- underlying edges. Bumps here explain step-changes in
    -- dead_candidates that aren't real code changes (e.g. 1.6→1.7
    -- when __module__ landed and false-positives dropped ~40pp).
    adapter_version   TEXT,

    -- Free-form JSON for future extension without another migration
    extra_json        TEXT
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

CREATE TABLE IF NOT EXISTS ingestion_runs (
    id                INTEGER PRIMARY KEY,

    -- Which adapter ran. Matches the choices in `templedb ingest`
    -- ('git', 'agent', 'intent', 'reports', ...).
    adapter           TEXT NOT NULL,

    -- Lifecycle
    started_at        TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at       TEXT,
    status            TEXT NOT NULL DEFAULT 'running'
                        CHECK (status IN
                            ('running', 'ok', 'partial', 'error')),

    -- Change counters
    entities_added    INTEGER DEFAULT 0,
    entities_refreshed INTEGER DEFAULT 0,
    relations_added   INTEGER DEFAULT 0,
    extra_added       INTEGER DEFAULT 0,   -- span/junction rows

    -- Freeform per-run notes (error message, adapter-specific stats)
    notes             TEXT
, adapter_version TEXT);

CREATE TABLE IF NOT EXISTS invariant_checks (
    id            INTEGER PRIMARY KEY,

    -- Name of the invariant. Matches the strings used in
    -- EntityCommands.doctor_entities checks list:
    --   'edit_intent_applied_to_valid_commit'
    --   'every_edit_intent_has_entity'
    --   'every_commit_has_entity'
    --   'relations_reference_valid_entities'
    --   'report_impls_reference_valid_reports'
    --   'report_impls_reference_valid_commits'
    check_name    TEXT NOT NULL,

    -- When the check ran and how long it took
    ran_at        TEXT NOT NULL DEFAULT (datetime('now')),
    duration_ms   INTEGER,

    -- Result. 'ok' means invariant held. 'violated' means one or more
    -- issues found. 'error' means the check itself failed to run.
    status        TEXT NOT NULL DEFAULT 'ok'
                    CHECK (status IN ('ok', 'violated', 'error')),
    issue_count   INTEGER NOT NULL DEFAULT 0,

    -- Up to first-N issues as JSON for context, without storing
    -- unbounded lists. Freshness > completeness for a history log.
    sample_issues_json TEXT,

    -- Optional link to the ingest run that likely produced the drift.
    ingestion_run_id INTEGER REFERENCES ingestion_runs(id)
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

CREATE TABLE IF NOT EXISTS nix_cache_entries (
    id INTEGER PRIMARY KEY,
    path_id INTEGER NOT NULL UNIQUE REFERENCES nix_store_paths(id) ON DELETE CASCADE,
    narinfo_text TEXT NOT NULL,                -- pre-rendered .narinfo content
    compression TEXT NOT NULL DEFAULT 'zstd',  -- compression used for NAR
    file_hash TEXT NOT NULL,                   -- hash of compressed NAR file
    file_size INTEGER NOT NULL,                -- size of compressed NAR
    served_count INTEGER NOT NULL DEFAULT 0,
    last_served_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS nix_closure_diffs (
    id INTEGER PRIMARY KEY,
    old_closure_id INTEGER REFERENCES nix_closures(id) ON DELETE SET NULL,
    new_closure_id INTEGER REFERENCES nix_closures(id) ON DELETE SET NULL,
    generation_id INTEGER REFERENCES nix_generations(id) ON DELETE SET NULL,
    added_count INTEGER NOT NULL DEFAULT 0,
    removed_count INTEGER NOT NULL DEFAULT 0,
    changed_count INTEGER NOT NULL DEFAULT 0,
    size_delta INTEGER NOT NULL DEFAULT 0,     -- bytes added (negative = shrunk)
    diff_json TEXT,                            -- detailed package-level changes
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS nix_closure_paths (
    id INTEGER PRIMARY KEY,
    closure_id INTEGER NOT NULL REFERENCES nix_closures(id) ON DELETE CASCADE,
    path_id INTEGER NOT NULL REFERENCES nix_store_paths(id) ON DELETE CASCADE,
    UNIQUE(closure_id, path_id)
);

CREATE TABLE IF NOT EXISTS nix_closures (
    id INTEGER PRIMARY KEY,
    closure_hash TEXT NOT NULL UNIQUE,         -- sha256 of sorted store path list
    toplevel_path TEXT NOT NULL,               -- the top-level store path
    total_paths INTEGER NOT NULL DEFAULT 0,
    total_size INTEGER NOT NULL DEFAULT 0,     -- sum of nar_size of all paths
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
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

CREATE TABLE IF NOT EXISTS nix_eval_cache (
    id INTEGER PRIMARY KEY,
    flake_uri TEXT NOT NULL,                   -- e.g. "/home/zach/.config/templedb/checkouts/system_config"
    flake_attr TEXT NOT NULL,                  -- e.g. "nixosConfigurations.zMothership2"
    input_hash TEXT NOT NULL,                  -- hash of flake.lock + relevant source content hashes
    output_drv TEXT,                           -- resulting derivation store path
    output_out TEXT,                           -- resulting output store path
    eval_duration_ms INTEGER,                  -- how long evaluation took
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_hit_at TEXT,
    hit_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(flake_uri, flake_attr, input_hash)
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

CREATE TABLE IF NOT EXISTS nix_generations (
    id INTEGER PRIMARY KEY,
    machine_id INTEGER REFERENCES fleet_machines(id) ON DELETE SET NULL,
    machine_name TEXT NOT NULL,                -- hostname, survives machine deletion
    generation_number INTEGER NOT NULL,        -- NixOS generation number
    closure_id INTEGER REFERENCES nix_closures(id) ON DELETE SET NULL,
    toplevel_path TEXT NOT NULL,               -- /nix/store/...-nixos-system-...
    -- VCS linkage: which code produced this generation
    commit_id INTEGER REFERENCES vcs_commits(id) ON DELETE SET NULL,
    commit_hash TEXT,                          -- denormalized for display
    project_id INTEGER REFERENCES projects(id) ON DELETE SET NULL,
    -- Deploy linkage
    deployment_id INTEGER REFERENCES fleet_deployments(id) ON DELETE SET NULL,
    system_deployment_id INTEGER REFERENCES system_deployments(id) ON DELETE SET NULL,
    -- Metadata
    nixos_version TEXT,                        -- e.g. "24.11pre-git"
    kernel_version TEXT,
    config_revision TEXT,                      -- flake revision
    previous_generation_id INTEGER REFERENCES nix_generations(id) ON DELETE SET NULL,
    switched_at TEXT NOT NULL DEFAULT (datetime('now')),
    switch_action TEXT DEFAULT 'switch',       -- switch, boot, test
    switch_success INTEGER NOT NULL DEFAULT 1,
    boot_id TEXT,                              -- systemd boot ID (detects reboots)
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS nix_project_paths (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path_id INTEGER NOT NULL REFERENCES nix_store_paths(id) ON DELETE CASCADE,
    association TEXT NOT NULL DEFAULT 'closure', -- closure, devenv, build-input
    discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_id, path_id, association)
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

CREATE TABLE IF NOT EXISTS nix_store_paths (
    id INTEGER PRIMARY KEY,
    store_path TEXT NOT NULL UNIQUE,           -- /nix/store/abc123-package-1.0
    store_hash TEXT NOT NULL,                  -- abc123 (the hash part)
    name TEXT NOT NULL,                        -- package-1.0 (the name part)
    nar_size INTEGER,                          -- size of NAR archive in bytes
    nar_hash TEXT,                             -- sha256 of NAR archive (for binary cache)
    closure_size INTEGER,                      -- total closure size in bytes
    num_references INTEGER DEFAULT 0,          -- number of direct references
    deriver TEXT,                              -- store path of the .drv that built this
    is_valid INTEGER NOT NULL DEFAULT 1,       -- still exists in local store
    first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS nix_store_refs (
    id INTEGER PRIMARY KEY,
    path_id INTEGER NOT NULL REFERENCES nix_store_paths(id) ON DELETE CASCADE,
    ref_id INTEGER NOT NULL REFERENCES nix_store_paths(id) ON DELETE CASCADE,
    UNIQUE(path_id, ref_id)
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

CREATE TABLE IF NOT EXISTS observations_archive (
    id                INTEGER PRIMARY KEY,

    -- What was observed
    entity_kind       TEXT NOT NULL,
    entity_ref        TEXT NOT NULL,   -- the entity's external_ref
    label             TEXT,
    source_authority  TEXT,

    -- When
    observed_at       TEXT NOT NULL DEFAULT (datetime('now')),

    -- Who / how
    entity_id         INTEGER,          -- FK-ish (entity may have been deleted)

    -- Prior values (what the row looked like before the update).
    -- Nullable in case the trigger fires from a state we can't fully
    -- capture; the essential fields above are always populated.
    prior_label            TEXT,
    prior_source_authority TEXT
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
    updated_at TEXT NOT NULL DEFAULT (datetime('now')), edit_mode TEXT,

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

CREATE TABLE IF NOT EXISTS project_test_deps (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    nix_package TEXT NOT NULL,       -- e.g. 'chromium', 'nodejs', 'playwright'
    reason TEXT,                     -- e.g. 'Puppeteer browser tests'
    env_var TEXT,                    -- e.g. 'CHROME_PATH' — set to resolved binary path
    binary_name TEXT,                -- e.g. 'chromium' — which bin/ to look for
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project_tests (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    test_type TEXT NOT NULL CHECK(test_type IN ('page', 'post', 'structure_file', 'structure_dir')),
    -- For page/post tests
    path TEXT,                    -- URL path (e.g., /dashboard)
    expected_text TEXT,           -- Text expected in response
    post_data TEXT,               -- JSON-encoded POST data (for post tests)
    -- For structure tests
    file_path TEXT,               -- Relative file/dir path to check
    -- Metadata
    description TEXT,
    enabled INTEGER DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
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
    prompt_type TEXT NOT NULL,
    prompt_id INTEGER NOT NULL,
    project_id INTEGER REFERENCES projects(id),
    used_by TEXT,
    usage_context TEXT,
    rendered_prompt TEXT,
    variables_used TEXT,
    used_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reconcile_runs (
    id                INTEGER PRIMARY KEY,

    -- Which machine was probed
    machine_name      TEXT NOT NULL,

    -- Lifecycle timestamps
    ran_at            TEXT NOT NULL DEFAULT (datetime('now')),
    duration_ms       INTEGER,

    -- Outcome
    status            TEXT NOT NULL DEFAULT 'ok'
                        CHECK (status IN
                            ('ok', 'drift', 'unreachable', 'error')),

    -- SSH exit code if we got one (NULL = SSH didn't run or failed
    -- before returning). Handy for triaging "keys wrong" vs
    -- "host down" vs "unexpected exit".
    ssh_exit_code     INTEGER,

    -- If status='drift', the details as JSON: which of {toplevel,
    -- nixos_version, boot_id} disagreed and what the DB vs machine
    -- values were.
    drift_details_json TEXT,

    -- Who invoked the reconcile — TEMPLEDB_AUTHOR/USER env, or NULL
    -- for scheduled runs.
    ran_by            TEXT
);

CREATE TABLE IF NOT EXISTS relations (
    id                INTEGER PRIMARY KEY,

    from_entity_id    INTEGER NOT NULL REFERENCES entities(id)
                        ON DELETE CASCADE,
    kind              TEXT NOT NULL,
    to_entity_id      INTEGER NOT NULL REFERENCES entities(id)
                        ON DELETE CASCADE,

    source_authority  TEXT NOT NULL,
    observed_at       TEXT NOT NULL DEFAULT (datetime('now')),

    -- Optional JSON payload for edge attributes that don't warrant
    -- a first-class span (e.g. line number of a symbol reference).
    -- Use sparingly — if a relation grows more than 2-3 attributes
    -- or a lifecycle, promote it to a span with its own table.
    attributes_json   TEXT, sync_scope TEXT
    CHECK (sync_scope IN ('fleet', 'machine-local', 'none')),

    UNIQUE(from_entity_id, kind, to_entity_id)
);

CREATE TABLE IF NOT EXISTS report_implementations (
    id                INTEGER PRIMARY KEY,

    -- Report side of the span
    report_path       TEXT NOT NULL,   -- e.g. reports/2026-09-02-1430-…html
    project_slug      TEXT NOT NULL,   -- usually 'templedb'

    -- Commit side of the span
    commit_hash       TEXT NOT NULL,   -- full or prefix; resolved on read

    -- Lifecycle + attribution
    confidence        TEXT NOT NULL DEFAULT 'auto-detected'
                        CHECK (confidence IN
                            ('auto-detected', 'confirmed',
                             'verified', 'rejected')),
    note              TEXT,             -- human explanation, if any
    linked_by         TEXT,             -- author who confirmed/rejected

    -- Timestamps
    linked_at         TEXT NOT NULL DEFAULT (datetime('now')),
    verified_at       TEXT,

    UNIQUE(report_path, commit_hash)
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

CREATE TABLE IF NOT EXISTS secret_key_assignments (
    secret_blob_id INTEGER NOT NULL REFERENCES secret_blobs(id) ON DELETE CASCADE,
    key_id INTEGER NOT NULL REFERENCES encryption_keys(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    added_by TEXT,                           -- User who added this assignment
    PRIMARY KEY (secret_blob_id, key_id)
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

CREATE TABLE IF NOT EXISTS sync_entities (
    kind             TEXT NOT NULL,
    external_ref     TEXT NOT NULL,
    source_authority TEXT NOT NULL DEFAULT '',
    label            TEXT NOT NULL DEFAULT '',
    observed_at      TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL DEFAULT '',
    attributes_json  TEXT NOT NULL DEFAULT '',
    sync_scope       TEXT NOT NULL DEFAULT 'fleet',
    PRIMARY KEY (kind, external_ref)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS sync_environment_variables (
            id INTEGER PRIMARY KEY NOT NULL,
            scope_type TEXT DEFAULT '',
            scope_id INTEGER DEFAULT 0,
            var_name TEXT DEFAULT '',
            var_value TEXT DEFAULT '',
            is_secret INTEGER DEFAULT 0,
            updated_at TEXT DEFAULT ''
        );

CREATE TABLE IF NOT EXISTS sync_nixos_config (
            id INTEGER PRIMARY KEY NOT NULL,
            key TEXT DEFAULT '',
            value TEXT DEFAULT '',
            host TEXT DEFAULT '',
            updated_at TEXT DEFAULT ''
        );

CREATE TABLE IF NOT EXISTS sync_projects (
            id INTEGER PRIMARY KEY NOT NULL,
            slug TEXT DEFAULT '',
            name TEXT DEFAULT '',
            repo_url TEXT DEFAULT '',
            project_type TEXT DEFAULT '',
            is_nix_project INTEGER DEFAULT 0,
            project_category TEXT DEFAULT ''
        );

CREATE TABLE IF NOT EXISTS sync_relations (
    from_kind         TEXT NOT NULL,
    from_external_ref TEXT NOT NULL,
    kind              TEXT NOT NULL,
    to_kind           TEXT NOT NULL,
    to_external_ref   TEXT NOT NULL,
    source_authority  TEXT NOT NULL DEFAULT '',
    observed_at       TEXT NOT NULL DEFAULT '',
    attributes_json   TEXT NOT NULL DEFAULT '',
    sync_scope        TEXT NOT NULL DEFAULT 'fleet',
    PRIMARY KEY (from_kind, from_external_ref, kind, to_kind, to_external_ref)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS sync_system_config (
            id INTEGER PRIMARY KEY NOT NULL,
            key TEXT DEFAULT '',
            value TEXT DEFAULT '',
            updated_at TEXT DEFAULT ''
        );

CREATE TABLE IF NOT EXISTS sync_vcs_branches (
            id INTEGER PRIMARY KEY NOT NULL,
            project_id INTEGER DEFAULT 0,
            branch_name TEXT DEFAULT '',
            is_default INTEGER DEFAULT 0,
            head_commit_id INTEGER DEFAULT 0,
            created_at TEXT DEFAULT ''
        );

CREATE TABLE IF NOT EXISTS sync_vcs_commits (
            id INTEGER PRIMARY KEY NOT NULL,
            project_id INTEGER DEFAULT 0,
            branch_id INTEGER DEFAULT 0,
            commit_hash TEXT DEFAULT '',
            author TEXT DEFAULT '',
            commit_message TEXT DEFAULT '',
            commit_timestamp TEXT DEFAULT ''
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

CREATE TABLE IF NOT EXISTS test_runs (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    total_tests INTEGER NOT NULL DEFAULT 0,
    passed INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    duration_ms INTEGER,
    output TEXT,                  -- Full test output
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
, commit_id INTEGER REFERENCES vcs_commits(id));

CREATE TABLE IF NOT EXISTS tool_calls (
    id                INTEGER PRIMARY KEY,

    -- Provenance to the run + session it happened in
    run_id            INTEGER NOT NULL REFERENCES agent_runs(id)
                        ON DELETE CASCADE,
    session_id        INTEGER,   -- denormalized for direct index

    -- What was called
    tool_name         TEXT NOT NULL,

    -- Lifecycle
    started_at        TEXT NOT NULL,
    finished_at       TEXT,       -- NULL if still running or unknown
    status            TEXT NOT NULL DEFAULT 'unknown'
                        CHECK (status IN
                            ('running', 'completed', 'failed', 'unknown')),

    -- Optional detail: hashes so we can query "same tool + same args"
    -- across sessions once agent runtime records them.
    args_hash         TEXT,
    result_hash       TEXT,

    -- Traceability back to the event that produced this row.
    source_event_id   INTEGER REFERENCES agent_events(id)
                        ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS unmaintained_columns_baseline (
    id                    INTEGER PRIMARY KEY,
    table_name            TEXT NOT NULL,
    column_name           TEXT NOT NULL,
    -- 'all_null' | 'constant' -- recorded so that a column CHANGING
    -- shape (someone starts writing one value where it was NULL) is
    -- still visible rather than matching the baseline on name alone.
    shape                 TEXT NOT NULL,
    row_count_at_baseline INTEGER NOT NULL,
    accepted_at           TEXT NOT NULL DEFAULT (datetime('now')),
    reason                TEXT,
    UNIQUE(table_name, column_name)
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

CREATE TABLE IF NOT EXISTS vcs_commit_parents (
    commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    parent_commit_id INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    parent_order INTEGER NOT NULL DEFAULT 0,

    PRIMARY KEY (commit_id, parent_commit_id)
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
    git_branch TEXT, session_id INTEGER REFERENCES vcs_sessions(id),

    UNIQUE(project_id, commit_hash)
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
    id               INTEGER PRIMARY KEY,
    commit_id        INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    file_id          INTEGER NOT NULL,
    file_path        TEXT,
    change_type      TEXT NOT NULL
                       CHECK(change_type IN ('added', 'modified', 'deleted',
                                             'renamed', 'unmodified')),
    content_hash     TEXT,
    old_content_hash TEXT,
    previous_path    TEXT,
    file_size        INTEGER,
    line_count       INTEGER,
    UNIQUE(commit_id, file_id)
);

CREATE TABLE IF NOT EXISTS vcs_session_heads (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES vcs_sessions(id) ON DELETE CASCADE,
    branch_id INTEGER NOT NULL REFERENCES vcs_branches(id) ON DELETE CASCADE,
    head_commit_id INTEGER NOT NULL REFERENCES vcs_commits(id),
    base_commit_id INTEGER REFERENCES vcs_commits(id),  -- NULL = branch was empty at session start
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, branch_id)
);

CREATE TABLE IF NOT EXISTS vcs_sessions (
    id INTEGER PRIMARY KEY,
    name TEXT,                              -- optional human label
    author TEXT NOT NULL,                   -- resolved from TEMPLEDB_AUTHOR / git config / 'unknown'
    host TEXT,                              -- socket.gethostname() at start
    pid INTEGER,                            -- start pid (debugging)
    started_at TEXT NOT NULL DEFAULT (datetime('now')),
    ended_at TEXT,                          -- NULL = active
    ended_reason TEXT                       -- 'explicit-end' | 'commit-cleanup' | 'stale-timeout' | 'backfill'
, expected_lifetime_seconds INTEGER, reap_policy TEXT);

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
    last_modified TEXT NOT NULL DEFAULT (datetime('now')), staged_by_session_id INTEGER, intent_id INTEGER REFERENCES edit_intents(id),

    UNIQUE(project_id, branch_id, file_id)
);

-- ======================================================================
-- Virtual tables (FTS) (2)
-- ======================================================================

CREATE VIRTUAL TABLE IF NOT EXISTS code_search_fts USING fts5(
        symbol_id UNINDEXED,
        search_text
    );

CREATE VIRTUAL TABLE IF NOT EXISTS file_contents_fts USING fts5(
    file_path UNINDEXED,          -- Don't index file path
    content_text,                  -- Index the actual content
    tokenize='porter unicode61 remove_diacritics 1'
);

-- ======================================================================
-- Views (47)
-- ======================================================================

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

CREATE VIEW IF NOT EXISTS commit_files AS
SELECT v.id                                   AS id,
       v.commit_id                            AS commit_id,
       v.file_id                              AS file_id,
       v.change_type                          AS change_type,
       v.old_content_hash                     AS old_content_hash,
       CASE WHEN v.change_type = 'deleted' THEN NULL
            ELSE v.content_hash END           AS new_content_hash,
       CASE WHEN v.change_type = 'deleted' THEN v.file_path
            ELSE NULL END                     AS old_file_path,
       CASE WHEN v.change_type = 'deleted' THEN NULL
            ELSE v.file_path END              AS new_file_path,
       0                                      AS lines_added,
       0                                      AS lines_removed,
       c.commit_timestamp                     AS created_at
  FROM vcs_file_states v
  JOIN vcs_commits c ON c.id = v.commit_id;

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

CREATE VIEW IF NOT EXISTS deploy_stage_current AS
    SELECT r.*
      FROM deploy_stage_runs r
      JOIN (
        SELECT slug, stage_kind, MAX(started_at) AS latest
          FROM deploy_stage_runs
         WHERE ended_at IS NOT NULL
         GROUP BY slug, stage_kind
      ) mx
        ON r.slug = mx.slug
       AND r.stage_kind = mx.stage_kind
       AND r.started_at = mx.latest;

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

CREATE VIEW IF NOT EXISTS fleet_deployment_history AS
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
FROM fleet_deployments d
JOIN fleet_networks n ON d.network_id = n.id
JOIN projects p ON n.project_id = p.id
LEFT JOIN fleet_machine_deployments md ON d.id = md.deployment_id
GROUP BY d.id, d.deployment_uuid, d.network_id, n.network_name, n.project_id,
         p.slug, d.operation, d.target_machines, d.config_revision, d.status,
         d.started_at, d.completed_at, d.duration_seconds, d.triggered_by
ORDER BY d.started_at DESC;

CREATE VIEW IF NOT EXISTS fleet_local_machines AS
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
FROM fleet_machines m
JOIN fleet_networks n ON m.network_id = n.id
JOIN projects p ON n.project_id = p.id
WHERE m.is_local = TRUE;

CREATE VIEW IF NOT EXISTS fleet_machine_health AS
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
    (SELECT started_at
     FROM fleet_machine_deployments md
     JOIN fleet_deployments d ON md.deployment_id = d.id
     WHERE md.machine_id = m.id AND md.status = 'success'
     ORDER BY md.deploy_completed_at DESC LIMIT 1) AS last_successful_deployment,
    (SELECT COUNT(*)
     FROM fleet_machine_deployments md
     WHERE md.machine_id = m.id AND md.status = 'failed') AS failed_deployment_count
FROM fleet_machines m
JOIN fleet_networks n ON m.network_id = n.id
JOIN projects p ON n.project_id = p.id
ORDER BY n.network_name, m.machine_name;

CREATE VIEW IF NOT EXISTS fleet_network_summary AS
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
FROM fleet_networks n
JOIN projects p ON n.project_id = p.id
LEFT JOIN fleet_machines m ON n.id = m.network_id
LEFT JOIN fleet_resources r ON n.id = r.network_id
LEFT JOIN fleet_deployments d ON n.id = d.network_id
WHERE n.is_active = 1
GROUP BY n.id, n.project_id, n.network_name, n.network_uuid, n.is_active,
         p.slug, p.name, n.created_at, n.updated_at;

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

CREATE VIEW IF NOT EXISTS nix_generation_history AS
SELECT
    g.id,
    g.machine_name,
    g.generation_number,
    g.toplevel_path,
    g.nixos_version,
    g.kernel_version,
    g.switch_action,
    g.switch_success,
    g.switched_at,
    g.boot_id,
    g.commit_hash,
    c.commit_message,
    p.slug as project_slug,
    cl.total_paths as closure_paths,
    cl.total_size as closure_size,
    d.added_count as diff_added,
    d.removed_count as diff_removed,
    d.changed_count as diff_changed,
    d.size_delta as diff_size_delta
FROM nix_generations g
LEFT JOIN vcs_commits c ON g.commit_id = c.id
LEFT JOIN projects p ON g.project_id = p.id
LEFT JOIN nix_closures cl ON g.closure_id = cl.id
LEFT JOIN nix_closure_diffs d ON d.generation_id = g.id
ORDER BY g.switched_at DESC;

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

CREATE VIEW IF NOT EXISTS nix_store_stats AS
SELECT
    COUNT(*) as total_paths,
    SUM(CASE WHEN is_valid = 1 THEN 1 ELSE 0 END) as valid_paths,
    SUM(nar_size) as total_nar_size,
    SUM(closure_size) as total_closure_size,
    COUNT(DISTINCT deriver) as unique_derivers,
    (SELECT COUNT(*) FROM nix_closures) as tracked_closures,
    (SELECT COUNT(*) FROM nix_generations) as tracked_generations,
    (SELECT COUNT(*) FROM nix_cache_entries) as cached_for_serving,
    (SELECT COUNT(*) FROM nix_eval_cache) as eval_cache_entries
FROM nix_store_paths;

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

CREATE VIEW IF NOT EXISTS source_snapshots AS
    -- Current state (is_current = 1 in file_contents)
    SELECT
        p.slug                       AS project_slug,
        pf.file_path                 AS file_path,
        'current'                    AS revision,
        fc.content_hash              AS content_hash,
        cb.content_text              AS content_text,
        cb.content_blob              AS content_blob,
        cb.content_type              AS content_type,
        fc.file_size_bytes           AS file_size_bytes,
        fc.line_count                AS line_count,
        fc.updated_at                AS observed_at,
        'git'                        AS source_authority
    FROM file_contents fc
    JOIN project_files pf   ON pf.id = fc.file_id
    JOIN projects p         ON p.id = pf.project_id
    JOIN content_blobs cb   ON cb.hash_sha256 = fc.content_hash
    WHERE fc.is_current = 1
      AND pf.status = 'active'

    UNION ALL

    -- Historical state (any vcs_file_states row)
    SELECT
        p.slug                       AS project_slug,
        pf.file_path                 AS file_path,
        c.commit_hash                AS revision,
        vfs.content_hash             AS content_hash,
        cb.content_text              AS content_text,
        cb.content_blob              AS content_blob,
        cb.content_type              AS content_type,
        vfs.file_size                AS file_size_bytes,
        vfs.line_count               AS line_count,
        c.commit_timestamp           AS observed_at,
        'git'                        AS source_authority
    FROM vcs_file_states vfs
    JOIN vcs_commits c      ON c.id = vfs.commit_id
    JOIN project_files pf   ON pf.id = vfs.file_id
    JOIN projects p         ON p.id = pf.project_id
    LEFT JOIN content_blobs cb ON cb.hash_sha256 = vfs.content_hash;

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
    (ws.staged_by_session_id IS NOT NULL) AS staged,
    ws.staged_by_session_id,
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

-- ======================================================================
-- Indexes (256)
-- ======================================================================

CREATE INDEX IF NOT EXISTS agent_pending_asks_session_status
    ON agent_pending_asks(session_id, status);

CREATE INDEX IF NOT EXISTS agent_pending_events_undispatched
    ON agent_pending_events(session_id, dispatched_at)
    WHERE dispatched_at IS NULL;

CREATE INDEX IF NOT EXISTS agent_session_sections_by_session
    ON agent_session_sections(session_id);

CREATE INDEX IF NOT EXISTS agent_user_edits_unconsumed
    ON agent_user_edits(session_id, consumed_at)
    WHERE consumed_at IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS checkouts_one_canonical
    ON checkouts(project_id)
 WHERE kind = 'canonical' AND is_active = 1;

CREATE UNIQUE INDEX IF NOT EXISTS checkouts_one_edit_per_session
    ON checkouts(project_id, session_id)
 WHERE kind = 'edit' AND is_active = 1;

CREATE INDEX IF NOT EXISTS idx_agent_events_run ON agent_events(run_id);

CREATE INDEX IF NOT EXISTS idx_agent_events_type ON agent_events(event_type);

CREATE INDEX IF NOT EXISTS idx_agent_messages_session ON agent_messages(session_id);

CREATE INDEX IF NOT EXISTS idx_agent_notifications_pending_decision
    ON agent_notifications(pending_until)
    WHERE pending_until IS NOT NULL AND decided_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_agent_notifications_session
    ON agent_notifications(session_id);

CREATE INDEX IF NOT EXISTS idx_agent_notifications_unsent
    ON agent_notifications(created_at)
    WHERE sent_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_agent_runs_session ON agent_runs(session_id);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_project ON agent_sessions(project_id);

CREATE INDEX IF NOT EXISTS idx_agent_sessions_status ON agent_sessions(status);

CREATE INDEX IF NOT EXISTS idx_agent_work_log_created ON agent_work_log(created_at);

CREATE INDEX IF NOT EXISTS idx_agent_work_log_project ON agent_work_log(project_id);

CREATE INDEX IF NOT EXISTS idx_agent_work_log_session ON agent_work_log(session_id);

CREATE INDEX IF NOT EXISTS idx_ast_builds_hash ON ast_builds(output_hash);

CREATE INDEX IF NOT EXISTS idx_ast_builds_host ON ast_builds(host_name, generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_blue_green_state_lookup
    ON blue_green_state(project_id, target);

CREATE INDEX IF NOT EXISTS idx_cache_stats_hits ON deployment_cache_stats(cache_hit);

CREATE INDEX IF NOT EXISTS idx_cache_stats_project ON deployment_cache_stats(project_id, deployed_at DESC);

CREATE INDEX IF NOT EXISTS idx_checkout_snapshots_checkout ON checkout_snapshots(checkout_id);

CREATE INDEX IF NOT EXISTS idx_checkout_snapshots_file ON checkout_snapshots(file_id);

CREATE INDEX IF NOT EXISTS idx_checkout_snapshots_version ON checkout_snapshots(version);

CREATE INDEX IF NOT EXISTS idx_checkouts_active ON checkouts(is_active);

CREATE INDEX IF NOT EXISTS idx_checkouts_project ON checkouts(project_id);

CREATE INDEX IF NOT EXISTS idx_claim_evidence_claim
    ON claim_evidence(claim_id);

CREATE INDEX IF NOT EXISTS idx_claim_evidence_source
    ON claim_evidence(evidence_kind, evidence_ref);

CREATE INDEX IF NOT EXISTS idx_claims_scope
    ON claims(project_id, commit_id);

CREATE INDEX IF NOT EXISTS idx_claims_warrant
    ON claims(warrant_kind);

CREATE INDEX IF NOT EXISTS idx_cluster_files_cluster ON code_cluster_files(cluster_id);

CREATE INDEX IF NOT EXISTS idx_cluster_files_file ON code_cluster_files(file_id);

CREATE INDEX IF NOT EXISTS idx_cluster_members_cluster ON code_cluster_members(cluster_id);

CREATE INDEX IF NOT EXISTS idx_cluster_members_symbol ON code_cluster_members(symbol_id);

CREATE INDEX IF NOT EXISTS idx_code_symbols_dependents ON code_symbols(num_dependents DESC);

CREATE INDEX IF NOT EXISTS idx_code_symbols_file ON code_symbols(file_id);

CREATE INDEX IF NOT EXISTS idx_code_symbols_name ON code_symbols(symbol_name);

CREATE INDEX IF NOT EXISTS idx_code_symbols_project ON code_symbols(project_id);

CREATE INDEX IF NOT EXISTS idx_code_symbols_scope ON code_symbols(scope);

CREATE INDEX IF NOT EXISTS idx_code_symbols_type ON code_symbols(symbol_type);

CREATE INDEX IF NOT EXISTS idx_config_checkouts_project ON config_checkouts(project_id);

CREATE INDEX IF NOT EXISTS idx_config_links_checkout ON config_links(checkout_id);

CREATE INDEX IF NOT EXISTS idx_config_links_target ON config_links(target_path);

CREATE INDEX IF NOT EXISTS idx_config_nodes_host ON config_nodes(host_id);

CREATE INDEX IF NOT EXISTS idx_config_nodes_parent ON config_nodes(parent_id);

CREATE INDEX IF NOT EXISTS idx_config_nodes_scope ON config_nodes(scope);

CREATE INDEX IF NOT EXISTS idx_config_nodes_type ON config_nodes(node_type);

CREATE INDEX IF NOT EXISTS idx_content_blobs_external_path ON content_blobs(external_path) WHERE external_path IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_content_blobs_fetch_count ON content_blobs(fetch_count);

CREATE INDEX IF NOT EXISTS idx_content_blobs_size ON content_blobs(file_size_bytes);

CREATE INDEX IF NOT EXISTS idx_content_blobs_storage_location ON content_blobs(storage_location);

CREATE INDEX IF NOT EXISTS idx_content_blobs_type ON content_blobs(content_type);

CREATE INDEX IF NOT EXISTS idx_deploy_stage_runs_in_progress
    ON deploy_stage_runs(started_at) WHERE ended_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_deploy_stage_runs_prev
    ON deploy_stage_runs(prev_stage_run_id);

CREATE INDEX IF NOT EXISTS idx_deploy_stage_runs_slug_kind
    ON deploy_stage_runs(slug, stage_kind, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_deployment_cache_hash ON deployment_cache(content_hash);

CREATE INDEX IF NOT EXISTS idx_deployment_cache_last_used ON deployment_cache(last_used_at DESC);

CREATE INDEX IF NOT EXISTS idx_deployment_cache_project ON deployment_cache(project_id, target);

CREATE INDEX IF NOT EXISTS idx_deployment_cache_valid ON deployment_cache(is_valid) WHERE is_valid = 1;

CREATE INDEX IF NOT EXISTS idx_deployment_history_project ON deployment_history(project_id);

CREATE INDEX IF NOT EXISTS idx_deployment_history_project_target
    ON deployment_history(project_id, target_name, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_deployment_history_status
    ON deployment_history(status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_deployment_notifications_event ON deployment_notifications(event);

CREATE INDEX IF NOT EXISTS idx_deployment_notifications_project ON deployment_notifications(project_id);

CREATE INDEX IF NOT EXISTS idx_deployment_scripts_enabled ON deployment_scripts(enabled);

CREATE INDEX IF NOT EXISTS idx_deployment_scripts_has_docs
             ON deployment_scripts(project_slug) WHERE documentation IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_deployment_scripts_project ON deployment_scripts(project_slug);

CREATE INDEX IF NOT EXISTS idx_deployment_snapshots_deployment
    ON deployment_snapshots(deployment_id);

CREATE INDEX IF NOT EXISTS idx_deployment_triggers_project ON deployment_triggers(project_id);

CREATE INDEX IF NOT EXISTS idx_dns_records_domain_id ON dns_records(domain_id);

CREATE INDEX IF NOT EXISTS idx_dns_records_target_name ON dns_records(target_name);

CREATE INDEX IF NOT EXISTS idx_edge_func_deploy_hash
    ON edge_function_deployments(project_id, target, function_name, content_hash);

CREATE INDEX IF NOT EXISTS idx_edge_func_deploy_lookup
    ON edge_function_deployments(project_id, target, function_name, deployed_at DESC);

CREATE INDEX IF NOT EXISTS idx_edit_intents_file
    ON edit_intents(project_id, file_path, status);

CREATE INDEX IF NOT EXISTS idx_edit_intents_project
    ON edit_intents(project_id);

CREATE INDEX IF NOT EXISTS idx_edit_intents_session
    ON edit_intents(session_id);

CREATE INDEX IF NOT EXISTS idx_edit_intents_status
    ON edit_intents(status)
    WHERE status = 'proposed';

CREATE INDEX IF NOT EXISTS idx_edit_sessions_project ON edit_sessions(project_id);

CREATE INDEX IF NOT EXISTS idx_encryption_key_audit_key ON encryption_key_audit(key_id);

CREATE INDEX IF NOT EXISTS idx_encryption_key_audit_timestamp ON encryption_key_audit(timestamp);

CREATE INDEX IF NOT EXISTS idx_encryption_keys_active ON encryption_keys(is_active);

CREATE INDEX IF NOT EXISTS idx_encryption_keys_recipient ON encryption_keys(recipient);

CREATE INDEX IF NOT EXISTS idx_encryption_keys_type ON encryption_keys(key_type);

CREATE INDEX IF NOT EXISTS idx_entities_authority
    ON entities(source_authority);

CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities(kind);

CREATE INDEX IF NOT EXISTS idx_entities_sync_scope
    ON entities(sync_scope, kind);

CREATE INDEX IF NOT EXISTS idx_entity_deletions_at
    ON entity_deletions(deleted_at);

CREATE INDEX IF NOT EXISTS idx_entity_deletions_authority
    ON entity_deletions(source_authority, deleted_at);

CREATE INDEX IF NOT EXISTS idx_entity_deletions_ref
    ON entity_deletions(entity_kind, entity_ref);

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

CREATE INDEX IF NOT EXISTS idx_fleet_deployments_network ON fleet_deployments(network_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_fleet_deployments_status ON fleet_deployments(status);

CREATE INDEX IF NOT EXISTS idx_fleet_local_services_network_profile ON fleet_local_services(network_id, profile_name);

CREATE INDEX IF NOT EXISTS idx_fleet_local_services_status ON fleet_local_services(status);

CREATE INDEX IF NOT EXISTS idx_fleet_machine_deployments ON fleet_machine_deployments(deployment_id);

CREATE INDEX IF NOT EXISTS idx_fleet_machine_deployments_machine ON fleet_machine_deployments(machine_id, deploy_completed_at DESC);

CREATE INDEX IF NOT EXISTS idx_fleet_machines_is_local ON fleet_machines(is_local) WHERE is_local = TRUE;

CREATE INDEX IF NOT EXISTS idx_fleet_machines_network ON fleet_machines(network_id);

CREATE INDEX IF NOT EXISTS idx_fleet_machines_status ON fleet_machines(deployment_status);

CREATE INDEX IF NOT EXISTS idx_fleet_networks_active ON fleet_networks(project_id, is_active) WHERE is_active = 1;

CREATE INDEX IF NOT EXISTS idx_fleet_networks_project ON fleet_networks(project_id);

CREATE INDEX IF NOT EXISTS idx_fleet_resources_machine ON fleet_resources(machine_id);

CREATE INDEX IF NOT EXISTS idx_fleet_resources_network ON fleet_resources(network_id);

CREATE INDEX IF NOT EXISTS idx_fleet_resources_type ON fleet_resources(resource_type);

CREATE INDEX IF NOT EXISTS idx_graph_query_log_lookup
    ON graph_query_log(command, target_kind, target_key);

CREATE INDEX IF NOT EXISTS idx_graph_query_log_project
    ON graph_query_log(project_slug);

CREATE INDEX IF NOT EXISTS idx_graph_query_log_time
    ON graph_query_log(executed_at);

CREATE INDEX IF NOT EXISTS idx_handoff_notes_broadcast
    ON handoff_notes(created_at DESC)
    WHERE to_session IS NULL AND to_topic IS NULL;

CREATE INDEX IF NOT EXISTS idx_handoff_notes_project
    ON handoff_notes(project_id);

CREATE INDEX IF NOT EXISTS idx_handoff_notes_to_session
    ON handoff_notes(to_session, acked_at);

CREATE INDEX IF NOT EXISTS idx_handoff_notes_to_topic
    ON handoff_notes(to_topic, acked_at);

CREATE INDEX IF NOT EXISTS idx_health_checks_deployment ON deployment_health_checks(deployment_id);

CREATE INDEX IF NOT EXISTS idx_health_checks_status ON deployment_health_checks(status);

CREATE INDEX IF NOT EXISTS idx_health_checks_type ON deployment_health_checks(check_type);

CREATE INDEX IF NOT EXISTS idx_hygiene_snapshots_slug_time
    ON hygiene_snapshots(slug, taken_at DESC);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_adapter_started
    ON ingestion_runs(adapter, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_adapter_version
    ON ingestion_runs(adapter, adapter_version, started_at DESC)
    WHERE adapter_version IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ingestion_runs_status
    ON ingestion_runs(status)
    WHERE status IN ('running', 'error');

CREATE INDEX IF NOT EXISTS idx_invariant_checks_name_time
    ON invariant_checks(check_name, ran_at DESC);

CREATE INDEX IF NOT EXISTS idx_invariant_checks_violated
    ON invariant_checks(status, ran_at DESC)
    WHERE status IN ('violated', 'error');

CREATE INDEX IF NOT EXISTS idx_migration_history_applied_at
    ON migration_history(applied_at DESC);

CREATE INDEX IF NOT EXISTS idx_migration_history_project_target
    ON migration_history(project_id, target_name);

CREATE INDEX IF NOT EXISTS idx_migration_history_status
    ON migration_history(status);

CREATE INDEX IF NOT EXISTS idx_nix_closure_paths_closure ON nix_closure_paths(closure_id);

CREATE INDEX IF NOT EXISTS idx_nix_closure_paths_path ON nix_closure_paths(path_id);

CREATE INDEX IF NOT EXISTS idx_nix_env_sessions_env ON nix_env_sessions(environment_id);

CREATE INDEX IF NOT EXISTS idx_nix_env_sessions_time ON nix_env_sessions(started_at);

CREATE INDEX IF NOT EXISTS idx_nix_environments_active ON nix_environments(is_active);

CREATE INDEX IF NOT EXISTS idx_nix_environments_project ON nix_environments(project_id);

CREATE INDEX IF NOT EXISTS idx_nix_eval_cache_lookup ON nix_eval_cache(flake_uri, flake_attr);

CREATE INDEX IF NOT EXISTS idx_nix_generations_closure ON nix_generations(closure_id);

CREATE INDEX IF NOT EXISTS idx_nix_generations_commit ON nix_generations(commit_id);

CREATE INDEX IF NOT EXISTS idx_nix_generations_machine ON nix_generations(machine_name);

CREATE UNIQUE INDEX IF NOT EXISTS idx_nix_generations_machine_gen
    ON nix_generations(machine_name, generation_number);

CREATE INDEX IF NOT EXISTS idx_nix_generations_switched ON nix_generations(switched_at);

CREATE INDEX IF NOT EXISTS idx_nix_project_paths_path ON nix_project_paths(path_id);

CREATE INDEX IF NOT EXISTS idx_nix_project_paths_project ON nix_project_paths(project_id);

CREATE INDEX IF NOT EXISTS idx_nix_store_paths_hash ON nix_store_paths(store_hash);

CREATE INDEX IF NOT EXISTS idx_nix_store_paths_name ON nix_store_paths(name);

CREATE INDEX IF NOT EXISTS idx_nix_store_paths_valid ON nix_store_paths(is_valid);

CREATE INDEX IF NOT EXISTS idx_nix_store_refs_path ON nix_store_refs(path_id);

CREATE INDEX IF NOT EXISTS idx_nix_store_refs_ref ON nix_store_refs(ref_id);

CREATE INDEX IF NOT EXISTS idx_nixos_managed_packages_enabled ON nixos_managed_packages(enabled);

CREATE INDEX IF NOT EXISTS idx_nixos_managed_packages_project ON nixos_managed_packages(project_id);

CREATE INDEX IF NOT EXISTS idx_nixos_managed_packages_scope ON nixos_managed_packages(install_scope);

CREATE INDEX IF NOT EXISTS idx_observations_archive_entity
    ON observations_archive(entity_kind, entity_ref, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_observations_archive_time
    ON observations_archive(observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_project_domains_project_id ON project_domains(project_id);

CREATE INDEX IF NOT EXISTS idx_project_domains_status ON project_domains(status);

CREATE INDEX IF NOT EXISTS idx_project_env_vars_env_var
  ON project_env_vars(env_var_id);

CREATE INDEX IF NOT EXISTS idx_project_env_vars_project
  ON project_env_vars(project_id);

CREATE INDEX IF NOT EXISTS idx_project_files_component_name ON project_files(component_name);

CREATE INDEX IF NOT EXISTS idx_project_files_edit_mode
    ON project_files(project_id, edit_mode)
    WHERE edit_mode IS NOT NULL AND edit_mode != 'immutable';

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

CREATE INDEX IF NOT EXISTS idx_reconcile_runs_machine_time
    ON reconcile_runs(machine_name, ran_at DESC);

CREATE INDEX IF NOT EXISTS idx_reconcile_runs_status
    ON reconcile_runs(status, ran_at DESC)
    WHERE status IN ('drift', 'unreachable', 'error');

CREATE INDEX IF NOT EXISTS idx_relations_from
    ON relations(from_entity_id, kind);

CREATE INDEX IF NOT EXISTS idx_relations_kind
    ON relations(kind);

CREATE INDEX IF NOT EXISTS idx_relations_sync_scope
    ON relations(sync_scope, kind);

CREATE INDEX IF NOT EXISTS idx_relations_to
    ON relations(to_entity_id, kind);

CREATE INDEX IF NOT EXISTS idx_report_impls_commit
    ON report_implementations(commit_hash);

CREATE INDEX IF NOT EXISTS idx_report_impls_confidence
    ON report_implementations(confidence);

CREATE INDEX IF NOT EXISTS idx_report_impls_report
    ON report_implementations(report_path);

CREATE INDEX IF NOT EXISTS idx_secret_key_assignments_key ON secret_key_assignments(key_id);

CREATE INDEX IF NOT EXISTS idx_secret_key_assignments_secret ON secret_key_assignments(secret_blob_id);

CREATE INDEX IF NOT EXISTS idx_service_metadata_project ON nix_service_metadata(project_id);

CREATE INDEX IF NOT EXISTS idx_service_metadata_service_name ON nix_service_metadata(service_name);

CREATE INDEX IF NOT EXISTS idx_symbol_deps_called ON code_symbol_dependencies(called_symbol_id);

CREATE INDEX IF NOT EXISTS idx_symbol_deps_caller ON code_symbol_dependencies(caller_symbol_id);

CREATE INDEX IF NOT EXISTS idx_symbol_deps_confidence ON code_symbol_dependencies(confidence_score DESC);

CREATE INDEX IF NOT EXISTS idx_symbol_deps_type ON code_symbol_dependencies(dependency_type);

CREATE INDEX IF NOT EXISTS idx_sync_cache_lookup ON sync_cache(project_id, file_path);

CREATE INDEX IF NOT EXISTS idx_sync_cache_project ON sync_cache(project_id);

CREATE INDEX IF NOT EXISTS idx_system_config_key ON system_config(key);

CREATE INDEX IF NOT EXISTS idx_system_deployments_active ON system_deployments(project_id, is_active) WHERE is_active = 1;

CREATE INDEX IF NOT EXISTS idx_system_deployments_history ON system_deployments(project_id, deployed_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_test_deps_project_pkg
    ON project_test_deps(project_id, nix_package);

CREATE INDEX IF NOT EXISTS idx_test_runs_commit
    ON test_runs(commit_id);

CREATE INDEX IF NOT EXISTS idx_test_runs_project_created
    ON test_runs(project_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_tool_calls_active
    ON tool_calls(status)
    WHERE status IN ('running', 'unknown');

CREATE INDEX IF NOT EXISTS idx_tool_calls_run
    ON tool_calls(run_id);

CREATE INDEX IF NOT EXISTS idx_tool_calls_session
    ON tool_calls(session_id);

CREATE INDEX IF NOT EXISTS idx_tool_calls_tool
    ON tool_calls(tool_name);

CREATE INDEX IF NOT EXISTS idx_transitive_cache_affected ON impact_transitive_cache(affected_symbol_id);

CREATE INDEX IF NOT EXISTS idx_transitive_cache_depth ON impact_transitive_cache(depth);

CREATE INDEX IF NOT EXISTS idx_transitive_cache_direction_depth ON impact_transitive_cache(direction, depth);

CREATE INDEX IF NOT EXISTS idx_transitive_cache_symbol ON impact_transitive_cache(symbol_id, direction);

CREATE INDEX IF NOT EXISTS idx_validation_history_project ON nix_flake_validation_history(project_id);

CREATE INDEX IF NOT EXISTS idx_validation_history_timestamp ON nix_flake_validation_history(validation_timestamp);

CREATE INDEX IF NOT EXISTS idx_validation_history_type ON nix_flake_validation_history(validation_type, succeeded);

CREATE INDEX IF NOT EXISTS idx_vcs_branches_head ON vcs_branches(head_commit_id);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_metadata_ai ON vcs_commit_metadata(ai_assisted);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_metadata_breaking ON vcs_commit_metadata(is_breaking);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_metadata_commit ON vcs_commit_metadata(commit_id);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_metadata_impact ON vcs_commit_metadata(impact_level);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_metadata_type ON vcs_commit_metadata(change_type);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_parents_parent ON vcs_commit_parents(parent_commit_id);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_tags_commit ON vcs_commit_tags(commit_id);

CREATE INDEX IF NOT EXISTS idx_vcs_commit_tags_name ON vcs_commit_tags(tag_name);

CREATE INDEX IF NOT EXISTS idx_vcs_commits_branch ON vcs_commits(branch_id);

CREATE INDEX IF NOT EXISTS idx_vcs_commits_hash ON vcs_commits(commit_hash);

CREATE INDEX IF NOT EXISTS idx_vcs_commits_parent ON vcs_commits(parent_commit_id);

CREATE INDEX IF NOT EXISTS idx_vcs_commits_project ON vcs_commits(project_id);

CREATE INDEX IF NOT EXISTS idx_vcs_commits_session
    ON vcs_commits(session_id)
    WHERE session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_vcs_commits_timestamp ON vcs_commits(commit_timestamp);

CREATE INDEX IF NOT EXISTS idx_vcs_file_change_metadata_commit ON vcs_file_change_metadata(commit_id);

CREATE INDEX IF NOT EXISTS idx_vcs_file_change_metadata_file ON vcs_file_change_metadata(file_id);

CREATE INDEX IF NOT EXISTS idx_vcs_file_states_file
    ON vcs_file_states(file_id);

CREATE INDEX IF NOT EXISTS idx_vcs_file_states_hash
    ON vcs_file_states(content_hash);

CREATE INDEX IF NOT EXISTS idx_vcs_session_heads_branch
    ON vcs_session_heads(branch_id);

CREATE INDEX IF NOT EXISTS idx_vcs_session_heads_session
    ON vcs_session_heads(session_id);

CREATE INDEX IF NOT EXISTS idx_vcs_sessions_active
    ON vcs_sessions(ended_at) WHERE ended_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_vcs_sessions_name
    ON vcs_sessions(name);

CREATE INDEX IF NOT EXISTS idx_vcs_sessions_name_active
    ON vcs_sessions(author, host, name)
    WHERE ended_at IS NULL AND name IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_vcs_working_state_branch ON vcs_working_state(branch_id);

CREATE INDEX IF NOT EXISTS idx_vcs_working_state_file ON vcs_working_state(file_id);

CREATE INDEX IF NOT EXISTS idx_vcs_working_state_intent
    ON vcs_working_state(intent_id)
    WHERE intent_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_vcs_working_state_project ON vcs_working_state(project_id);

CREATE INDEX IF NOT EXISTS idx_vcs_working_state_staged_session
    ON vcs_working_state(staged_by_session_id)
    WHERE staged_by_session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_vcs_working_state_state ON vcs_working_state(state);

-- ======================================================================
-- Triggers (38)
-- ======================================================================

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

CREATE TRIGGER IF NOT EXISTS entities_sync_del
AFTER DELETE ON entities
WHEN OLD.external_ref IS NOT NULL
BEGIN
    DELETE FROM sync_entities
     WHERE kind = OLD.kind AND external_ref = OLD.external_ref;
    DELETE FROM sync_relations
     WHERE (from_kind = OLD.kind AND from_external_ref = OLD.external_ref)
        OR (to_kind   = OLD.kind AND to_external_ref   = OLD.external_ref);
END;

CREATE TRIGGER IF NOT EXISTS entities_sync_fleet_ins
AFTER INSERT ON entities
WHEN NEW.sync_scope = 'fleet' AND NEW.external_ref IS NOT NULL
BEGIN
    INSERT INTO sync_entities (
        kind, external_ref, source_authority, label,
        observed_at, created_at, attributes_json, sync_scope
    ) VALUES (
        NEW.kind, NEW.external_ref,
        NEW.source_authority, COALESCE(NEW.label, ''),
        NEW.observed_at, NEW.created_at,
        COALESCE(NEW.attributes_json, ''), NEW.sync_scope
    )
    ON CONFLICT(kind, external_ref) DO UPDATE SET
        source_authority = excluded.source_authority,
        label            = excluded.label,
        observed_at      = excluded.observed_at,
        created_at       = excluded.created_at,
        attributes_json  = excluded.attributes_json,
        sync_scope       = excluded.sync_scope;
END;

CREATE TRIGGER IF NOT EXISTS entities_sync_fleet_upd
AFTER UPDATE ON entities
WHEN NEW.sync_scope = 'fleet' AND NEW.external_ref IS NOT NULL
BEGIN
    INSERT INTO sync_entities (
        kind, external_ref, source_authority, label,
        observed_at, created_at, attributes_json, sync_scope
    ) VALUES (
        NEW.kind, NEW.external_ref,
        NEW.source_authority, COALESCE(NEW.label, ''),
        NEW.observed_at, NEW.created_at,
        COALESCE(NEW.attributes_json, ''), NEW.sync_scope
    )
    ON CONFLICT(kind, external_ref) DO UPDATE SET
        source_authority = excluded.source_authority,
        label            = excluded.label,
        observed_at      = excluded.observed_at,
        created_at       = excluded.created_at,
        attributes_json  = excluded.attributes_json,
        sync_scope       = excluded.sync_scope;
END;

CREATE TRIGGER IF NOT EXISTS entities_sync_unfleet
AFTER UPDATE ON entities
WHEN OLD.sync_scope = 'fleet' AND NEW.sync_scope IS NOT 'fleet'
  AND OLD.external_ref IS NOT NULL
BEGIN
    DELETE FROM sync_entities
     WHERE kind = OLD.kind AND external_ref = OLD.external_ref;
    -- Also drop any relations that referenced this entity as either
    -- endpoint — they're no longer fleet-transportable.
    DELETE FROM sync_relations
     WHERE (from_kind = OLD.kind AND from_external_ref = OLD.external_ref)
        OR (to_kind   = OLD.kind AND to_external_ref   = OLD.external_ref);
END;

CREATE TRIGGER IF NOT EXISTS file_contents_fts_delete
AFTER DELETE ON file_contents
BEGIN
    DELETE FROM file_contents_fts WHERE rowid = OLD.file_id;
END;

CREATE TRIGGER IF NOT EXISTS file_contents_fts_file_delete
AFTER DELETE ON project_files
BEGIN
    DELETE FROM file_contents_fts WHERE rowid = OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS file_contents_fts_file_update
AFTER UPDATE OF file_path, status ON project_files
BEGIN
    DELETE FROM file_contents_fts WHERE rowid = NEW.id;
    INSERT INTO file_contents_fts (rowid, file_path, content_text)
    SELECT pf.id, pf.file_path, cb.content_text
      FROM project_files pf
      JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
      JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
     WHERE pf.id = NEW.id
       AND pf.status = 'active'
       AND cb.content_text IS NOT NULL;
END;

CREATE TRIGGER IF NOT EXISTS file_contents_fts_insert
AFTER INSERT ON file_contents
WHEN NEW.is_current = 1
BEGIN
    DELETE FROM file_contents_fts WHERE rowid = NEW.file_id;
    INSERT INTO file_contents_fts (rowid, file_path, content_text)
    SELECT pf.id, pf.file_path, cb.content_text
      FROM project_files pf
      JOIN content_blobs cb ON cb.hash_sha256 = NEW.content_hash
     WHERE pf.id = NEW.file_id
       AND pf.status = 'active'
       AND cb.content_text IS NOT NULL;
END;

CREATE TRIGGER IF NOT EXISTS file_contents_fts_update
AFTER UPDATE ON file_contents
WHEN NEW.is_current = 1
BEGIN
    DELETE FROM file_contents_fts WHERE rowid = NEW.file_id;
    INSERT INTO file_contents_fts (rowid, file_path, content_text)
    SELECT pf.id, pf.file_path, cb.content_text
      FROM project_files pf
      JOIN content_blobs cb ON cb.hash_sha256 = NEW.content_hash
     WHERE pf.id = NEW.file_id
       AND pf.status = 'active'
       AND cb.content_text IS NOT NULL;
END;

CREATE TRIGGER IF NOT EXISTS fleet_calculate_deployment_duration
AFTER UPDATE OF completed_at ON fleet_deployments
WHEN NEW.completed_at IS NOT NULL AND OLD.completed_at IS NULL
BEGIN
    UPDATE fleet_deployments
    SET duration_seconds = CAST((julianday(NEW.completed_at) - julianday(NEW.started_at)) * 86400 AS INTEGER)
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS fleet_calculate_machine_build_duration
AFTER UPDATE OF build_completed_at ON fleet_machine_deployments
WHEN NEW.build_completed_at IS NOT NULL AND OLD.build_completed_at IS NULL
BEGIN
    UPDATE fleet_machine_deployments
    SET build_duration_seconds = CAST((julianday(NEW.build_completed_at) - julianday(NEW.build_started_at)) * 86400 AS INTEGER)
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS fleet_calculate_machine_deploy_duration
AFTER UPDATE OF deploy_completed_at ON fleet_machine_deployments
WHEN NEW.deploy_completed_at IS NOT NULL AND OLD.deploy_completed_at IS NULL
BEGIN
    UPDATE fleet_machine_deployments
    SET deploy_duration_seconds = CAST((julianday(NEW.deploy_completed_at) - julianday(NEW.deploy_started_at)) * 86400 AS INTEGER)
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS fleet_local_services_allocate_port
AFTER INSERT ON fleet_local_services
FOR EACH ROW
WHEN NEW.port_mapping IS NOT NULL
BEGIN
    SELECT 1;
END;

CREATE TRIGGER IF NOT EXISTS fleet_local_services_updated
AFTER UPDATE ON fleet_local_services
FOR EACH ROW
BEGIN
    UPDATE fleet_local_services
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS fleet_machines_set_local_flag
AFTER INSERT ON fleet_machines
FOR EACH ROW
WHEN NEW.system_type = 'localhost'
BEGIN
    UPDATE fleet_machines
    SET is_local = TRUE
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS fleet_update_machine_timestamp
AFTER UPDATE ON fleet_machines
FOR EACH ROW
BEGIN
    UPDATE fleet_machines
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.id;
END;

CREATE TRIGGER IF NOT EXISTS fleet_update_network_timestamp
AFTER UPDATE ON fleet_machines
BEGIN
    UPDATE fleet_networks
    SET updated_at = CURRENT_TIMESTAMP
    WHERE id = NEW.network_id;
END;

CREATE TRIGGER IF NOT EXISTS increment_blob_reference
AFTER INSERT ON file_contents
FOR EACH ROW
BEGIN
    UPDATE content_blobs
    SET reference_count = reference_count + 1
    WHERE hash_sha256 = NEW.content_hash;
END;

CREATE TRIGGER IF NOT EXISTS nix_configs_updated_at
        AFTER UPDATE ON nix_configs
        BEGIN
          UPDATE nix_configs SET updated_at = datetime('now') WHERE id = NEW.id;
        END;

CREATE TRIGGER IF NOT EXISTS projects_updated_at
        AFTER UPDATE ON projects
        BEGIN
          UPDATE projects SET updated_at = datetime('now') WHERE id = NEW.id;
        END;

CREATE TRIGGER IF NOT EXISTS relations_sync_del
AFTER DELETE ON relations
BEGIN
    DELETE FROM sync_relations
     WHERE (from_kind, from_external_ref, kind, to_kind, to_external_ref) IN (
         SELECT ef.kind, ef.external_ref, OLD.kind, et.kind, et.external_ref
           FROM entities ef, entities et
          WHERE ef.id = OLD.from_entity_id
            AND et.id = OLD.to_entity_id
     );
END;

CREATE TRIGGER IF NOT EXISTS relations_sync_fleet_ins
AFTER INSERT ON relations
BEGIN
    INSERT INTO sync_relations (
        from_kind, from_external_ref, kind, to_kind, to_external_ref,
        source_authority, observed_at, attributes_json, sync_scope
    )
    SELECT ef.kind, ef.external_ref, NEW.kind, et.kind, et.external_ref,
           NEW.source_authority, NEW.observed_at,
           COALESCE(NEW.attributes_json, ''), 'fleet'
      FROM entities ef, entities et
     WHERE ef.id = NEW.from_entity_id
       AND et.id = NEW.to_entity_id
       AND ef.sync_scope = 'fleet' AND et.sync_scope = 'fleet'
       AND ef.external_ref IS NOT NULL AND et.external_ref IS NOT NULL
    ON CONFLICT(from_kind, from_external_ref, kind, to_kind, to_external_ref) DO UPDATE SET
        source_authority = excluded.source_authority,
        observed_at      = excluded.observed_at,
        attributes_json  = excluded.attributes_json,
        sync_scope       = excluded.sync_scope;
END;

CREATE TRIGGER IF NOT EXISTS relations_sync_fleet_upd
AFTER UPDATE ON relations
BEGIN
    INSERT INTO sync_relations (
        from_kind, from_external_ref, kind, to_kind, to_external_ref,
        source_authority, observed_at, attributes_json, sync_scope
    )
    SELECT ef.kind, ef.external_ref, NEW.kind, et.kind, et.external_ref,
           NEW.source_authority, NEW.observed_at,
           COALESCE(NEW.attributes_json, ''), 'fleet'
      FROM entities ef, entities et
     WHERE ef.id = NEW.from_entity_id
       AND et.id = NEW.to_entity_id
       AND ef.sync_scope = 'fleet' AND et.sync_scope = 'fleet'
       AND ef.external_ref IS NOT NULL AND et.external_ref IS NOT NULL
    ON CONFLICT(from_kind, from_external_ref, kind, to_kind, to_external_ref) DO UPDATE SET
        source_authority = excluded.source_authority,
        observed_at      = excluded.observed_at,
        attributes_json  = excluded.attributes_json,
        sync_scope       = excluded.sync_scope;
END;

CREATE TRIGGER IF NOT EXISTS trg_entities_archive_on_update
AFTER UPDATE OF label, source_authority ON entities
WHEN OLD.label IS NOT NEW.label
  OR OLD.source_authority IS NOT NEW.source_authority
BEGIN
    INSERT INTO observations_archive
        (entity_kind, entity_ref, label, source_authority,
         entity_id, prior_label, prior_source_authority)
    VALUES
        (NEW.kind, NEW.external_ref, NEW.label, NEW.source_authority,
         NEW.id, OLD.label, OLD.source_authority);
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

CREATE TRIGGER IF NOT EXISTS update_deployment_scripts_timestamp
AFTER UPDATE ON deployment_scripts
BEGIN
    UPDATE deployment_scripts SET updated_at = datetime('now') WHERE id = NEW.id;
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

CREATE TRIGGER IF NOT EXISTS update_system_config_timestamp
AFTER UPDATE ON system_config
BEGIN
    UPDATE system_config SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;
