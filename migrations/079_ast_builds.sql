-- ast_builds: content-addressed record of AST → .nix emissions.
-- Each row corresponds to a build dir under ~/.config/templedb/ast-builds/<output_hash>/
-- Design: docs/AST_DEPLOY_DESIGN.md

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

CREATE INDEX IF NOT EXISTS idx_ast_builds_host ON ast_builds(host_name, generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_ast_builds_hash ON ast_builds(output_hash);
