-- Nix Store Integration: track store paths, closures, generations, and binary cache
-- Unifies NixOS and TempleDB's content-addressed architectures

-- Store paths: every /nix/store/ path we know about
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

CREATE INDEX IF NOT EXISTS idx_nix_store_paths_hash ON nix_store_paths(store_hash);
CREATE INDEX IF NOT EXISTS idx_nix_store_paths_name ON nix_store_paths(name);
CREATE INDEX IF NOT EXISTS idx_nix_store_paths_valid ON nix_store_paths(is_valid);

-- Store path references: dependency graph edges
CREATE TABLE IF NOT EXISTS nix_store_refs (
    id INTEGER PRIMARY KEY,
    path_id INTEGER NOT NULL REFERENCES nix_store_paths(id) ON DELETE CASCADE,
    ref_id INTEGER NOT NULL REFERENCES nix_store_paths(id) ON DELETE CASCADE,
    UNIQUE(path_id, ref_id)
);

CREATE INDEX IF NOT EXISTS idx_nix_store_refs_path ON nix_store_refs(path_id);
CREATE INDEX IF NOT EXISTS idx_nix_store_refs_ref ON nix_store_refs(ref_id);

-- Closures: a named set of store paths (e.g. a system profile)
CREATE TABLE IF NOT EXISTS nix_closures (
    id INTEGER PRIMARY KEY,
    closure_hash TEXT NOT NULL UNIQUE,         -- sha256 of sorted store path list
    toplevel_path TEXT NOT NULL,               -- the top-level store path
    total_paths INTEGER NOT NULL DEFAULT 0,
    total_size INTEGER NOT NULL DEFAULT 0,     -- sum of nar_size of all paths
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Join table: which store paths belong to which closure
CREATE TABLE IF NOT EXISTS nix_closure_paths (
    id INTEGER PRIMARY KEY,
    closure_id INTEGER NOT NULL REFERENCES nix_closures(id) ON DELETE CASCADE,
    path_id INTEGER NOT NULL REFERENCES nix_store_paths(id) ON DELETE CASCADE,
    UNIQUE(closure_id, path_id)
);

CREATE INDEX IF NOT EXISTS idx_nix_closure_paths_closure ON nix_closure_paths(closure_id);
CREATE INDEX IF NOT EXISTS idx_nix_closure_paths_path ON nix_closure_paths(path_id);

-- Generations: links NixOS generations to VCS commits and closures
-- This is the heart of the integration: code change -> build -> generation -> machine state
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

CREATE INDEX IF NOT EXISTS idx_nix_generations_machine ON nix_generations(machine_name);
CREATE INDEX IF NOT EXISTS idx_nix_generations_commit ON nix_generations(commit_id);
CREATE INDEX IF NOT EXISTS idx_nix_generations_closure ON nix_generations(closure_id);
CREATE INDEX IF NOT EXISTS idx_nix_generations_switched ON nix_generations(switched_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_nix_generations_machine_gen
    ON nix_generations(machine_name, generation_number);

-- Nix evaluation cache: avoid re-evaluating unchanged flakes
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

CREATE INDEX IF NOT EXISTS idx_nix_eval_cache_lookup ON nix_eval_cache(flake_uri, flake_attr);

-- Binary cache metadata: what we can serve to other machines
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

-- Project-to-store-path associations: "which projects use this dependency?"
CREATE TABLE IF NOT EXISTS nix_project_paths (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path_id INTEGER NOT NULL REFERENCES nix_store_paths(id) ON DELETE CASCADE,
    association TEXT NOT NULL DEFAULT 'closure', -- closure, devenv, build-input
    discovered_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(project_id, path_id, association)
);

CREATE INDEX IF NOT EXISTS idx_nix_project_paths_project ON nix_project_paths(project_id);
CREATE INDEX IF NOT EXISTS idx_nix_project_paths_path ON nix_project_paths(path_id);

-- Closure diff history: what changed between generations
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

-- Views for common queries

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
