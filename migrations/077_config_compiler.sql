-- Configuration Compiler: AST-based system configuration
-- Stores NixOS/system config as a typed tree of nodes, replacing
-- flat key-value pairs with a proper AST that supports project ownership,
-- host inheritance, and backend-agnostic code generation.
-- See: docs/CONFIG_COMPILER_SPEC.md

-- Host definitions and inheritance
CREATE TABLE IF NOT EXISTS config_hosts (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    parent_id   INTEGER REFERENCES config_hosts(id),
    hw_config   TEXT,           -- relative path to hardware-configuration.nix
    description TEXT
);

-- Every piece of configuration is a node in a tree
CREATE TABLE IF NOT EXISTS config_nodes (
    id          INTEGER PRIMARY KEY,
    parent_id   INTEGER REFERENCES config_nodes(id) ON DELETE CASCADE,
    name        TEXT,           -- child name within parent (NULL for list items)
    sort_order  INTEGER DEFAULT 0,

    node_type   TEXT NOT NULL
                CHECK(node_type IN (
                    'AttrSet', 'List',
                    'Bool', 'Int', 'String', 'Path', 'Package', 'Identifier',
                    'FnCall', 'FnDef', 'LetIn', 'Binding', 'With',
                    'Import', 'Interpolation', 'MultilineString',
                    'Conditional', 'BinOp', 'Inherit',
                    'RawNix'
                )),

    value       TEXT,           -- leaf value (NULL for interior nodes)
    callee      TEXT,           -- for FnCall: function name
    operator    TEXT CHECK(operator IN ('//', '++', '+', '||', '&&', NULL)),

    scope       TEXT CHECK(scope IN ('system', 'home', 'flake', NULL)),
    host_id     INTEGER REFERENCES config_hosts(id) ON DELETE CASCADE,
    enabled     BOOLEAN DEFAULT 1,

    description TEXT,
    category    TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Named children unique per parent+host. NULL names (list items) are
    -- exempt because SQLite treats NULLs as distinct in UNIQUE constraints.
    UNIQUE(parent_id, name, host_id)
);

CREATE INDEX IF NOT EXISTS idx_config_nodes_parent ON config_nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_config_nodes_type ON config_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_config_nodes_host ON config_nodes(host_id);
CREATE INDEX IF NOT EXISTS idx_config_nodes_scope ON config_nodes(scope);

-- Project ownership of config nodes
CREATE TABLE IF NOT EXISTS config_node_owners (
    node_id     INTEGER REFERENCES config_nodes(id) ON DELETE CASCADE,
    project_id  INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    PRIMARY KEY (node_id, project_id)
);

-- Root entry points per scope (generator starts walking here)
CREATE TABLE IF NOT EXISTS config_roots (
    id          INTEGER PRIMARY KEY,
    scope       TEXT NOT NULL UNIQUE
                CHECK(scope IN ('system', 'home', 'flake')),
    node_id     INTEGER NOT NULL REFERENCES config_nodes(id),
    description TEXT
);

-- Seed hosts from existing nixos.host.* keys
INSERT OR IGNORE INTO config_hosts (name, description)
SELECT
    REPLACE(key, 'nixos.host.', ''),
    'Imported from system_config'
FROM system_config
WHERE key LIKE 'nixos.host.%'
  AND key NOT LIKE 'nixos.host.WilliamZacharyAbelTheZeroth';

-- Add WilliamZacharyAbelTheZeroth too if it exists
INSERT OR IGNORE INTO config_hosts (name, description)
SELECT
    REPLACE(key, 'nixos.host.', ''),
    'Imported from system_config'
FROM system_config
WHERE key = 'nixos.host.WilliamZacharyAbelTheZeroth';

-- Create scope root nodes
INSERT INTO config_nodes (id, parent_id, name, node_type, scope) VALUES (1, NULL, NULL, 'AttrSet', 'system');
INSERT INTO config_nodes (id, parent_id, name, node_type, scope) VALUES (2, NULL, NULL, 'AttrSet', 'home');
INSERT INTO config_nodes (id, parent_id, name, node_type, scope) VALUES (3, NULL, NULL, 'AttrSet', 'flake');

INSERT INTO config_roots (scope, node_id, description) VALUES ('system', 1, 'configuration.nix root');
INSERT INTO config_roots (scope, node_id, description) VALUES ('home', 2, 'home.nix root');
INSERT INTO config_roots (scope, node_id, description) VALUES ('flake', 3, 'flake.nix root');
