-- 135_config_nodes_allow_comment.sql
--
-- Let config_nodes store Comment nodes.
--
-- The AST config path has had Comment support in its parser and its
-- emitter since 2026-10-09: nix_ast_parser emits ASTNode('Comment', ...)
-- from five places, config_compiler.emit_nix has a `case 'Comment'` that
-- renders the text verbatim, and _emit_attr_child special-cases it ahead
-- of the name check so a comment does not pick up `= value;` framing.
-- emit_nix even excludes comments from the AttrSet single-child collapse,
-- because counting them would wrap a bare list in an attrset and emit
-- invalid Nix.
--
-- None of that could ever run. node_type's CHECK constraint was never
-- widened, so every INSERT of a Comment fails:
--
--     CHECK constraint failed: node_type IN ('AttrSet', ... 'RawNix')
--
-- So the capability was built on both sides of the database and the
-- database refused to hold it. That is the blocker behind the AST
-- migration stalling: the 2026-10-08 assessment recorded that promoting
-- the current build would delete 316 lines of live config including 86
-- lines of engineering rationale "the emitter cannot represent" — but the
-- emitter can represent it, and has been able to for a day. What it
-- cannot do is store it.
--
-- SQLite cannot ALTER a CHECK constraint, so this is the standard
-- rebuild. Ids are copied explicitly because parent_id is a
-- self-reference and config_roots.node_id / config_node_owners.node_id
-- point at them from outside; renumbering would silently repoint 1254
-- parent links and two dependent tables.
--
-- foreign_keys is toggled off for the swap because DROP TABLE
-- config_nodes momentarily leaves those two dependent tables referencing
-- a table that does not exist. SQLite resolves FK targets by name at DML
-- time, so once the rename restores the name they resolve again; the
-- foreign_key_check at the end is what proves it rather than assumes it.

PRAGMA foreign_keys=OFF;

DROP TABLE IF EXISTS config_nodes_new;

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
                    'RawNix',
                    -- New. Carries its own leading '#' in `value`; has no
                    -- name and takes no trailing semicolon.
                    'Comment'
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

    -- Comments are unnamed, so several under one parent all have
    -- name IS NULL. SQLite treats NULLs as distinct in a UNIQUE index,
    -- so this does not collide — unlike a named binding, which still
    -- cannot be duplicated per (parent, host).
    UNIQUE(parent_id, name, host_id)
);

INSERT INTO config_nodes_new
    (id, parent_id, name, sort_order, node_type, value, callee, operator,
     scope, host_id, enabled, description, category, created_at, updated_at)
SELECT
     id, parent_id, name, sort_order, node_type, value, callee, operator,
     scope, host_id, enabled, description, category, created_at, updated_at
  FROM config_nodes;

DROP TABLE config_nodes;

-- Rewrites the self-reference to the new name as part of the rename.
ALTER TABLE config_nodes_new RENAME TO config_nodes;

CREATE INDEX IF NOT EXISTS idx_config_nodes_parent ON config_nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_config_nodes_type   ON config_nodes(node_type);
CREATE INDEX IF NOT EXISTS idx_config_nodes_host   ON config_nodes(host_id);
CREATE INDEX IF NOT EXISTS idx_config_nodes_scope  ON config_nodes(scope);

PRAGMA foreign_key_check;

PRAGMA foreign_keys=ON;
