-- Expand config_nodes to cover the full Nix expression language.
-- SQLite CHECK constraints can't be altered, so we recreate the table.
-- This preserves all existing data.

CREATE TABLE config_nodes_new (
    id          INTEGER PRIMARY KEY,
    parent_id   INTEGER REFERENCES config_nodes_new(id) ON DELETE CASCADE,
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

-- Disable FK checks for the swap
PRAGMA foreign_keys = OFF;

-- Copy existing data
INSERT INTO config_nodes_new SELECT * FROM config_nodes;

-- Drop dependent tables' FK references temporarily by recreating them
-- (config_node_owners and config_roots reference config_nodes)
CREATE TABLE config_node_owners_new (
    node_id     INTEGER REFERENCES config_nodes_new(id) ON DELETE CASCADE,
    project_id  INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    PRIMARY KEY (node_id, project_id)
);
INSERT INTO config_node_owners_new SELECT * FROM config_node_owners;
DROP TABLE config_node_owners;

CREATE TABLE config_roots_new (
    id          INTEGER PRIMARY KEY,
    scope       TEXT NOT NULL UNIQUE
                CHECK(scope IN ('system', 'home', 'flake')),
    node_id     INTEGER NOT NULL REFERENCES config_nodes_new(id),
    description TEXT
);
INSERT INTO config_roots_new SELECT * FROM config_roots;
DROP TABLE config_roots;

-- Drop old table and rename all
DROP TABLE config_nodes;
ALTER TABLE config_nodes_new RENAME TO config_nodes;
ALTER TABLE config_node_owners_new RENAME TO config_node_owners;
ALTER TABLE config_roots_new RENAME TO config_roots;

-- FK checks restored by connection defaults

-- Recreate indexes
CREATE INDEX IF NOT EXISTS idx_config_nodes_parent ON config_nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_config_nodes_type ON config_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_config_nodes_host ON config_nodes(host_id);
CREATE INDEX IF NOT EXISTS idx_config_nodes_scope ON config_nodes(scope);
