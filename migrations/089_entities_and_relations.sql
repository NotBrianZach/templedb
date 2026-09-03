-- Migration 089: entities + relations (Phase 3 groundwork)
--
-- The knowledge-graph substrate. See docs/ENTITY_GRAPH_DESIGN.md
-- for the framing (spans as first-class relations, commuting-
-- diagram invariants, local charts + transition maps).
--
-- Entities are objects (files, commits, sessions, deployments, ...).
-- Relations are directed typed edges between entities.
--
-- First-class spans (edit_intents, ast_builds, deployments) already
-- have their own tables. They register in `entities` with their kind
-- and can participate in `relations` as both source and target.

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
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(kind, external_ref)
);

CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities(kind);
CREATE INDEX IF NOT EXISTS idx_entities_authority
    ON entities(source_authority);

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
    attributes_json   TEXT,

    UNIQUE(from_entity_id, kind, to_entity_id)
);

CREATE INDEX IF NOT EXISTS idx_relations_from
    ON relations(from_entity_id, kind);
CREATE INDEX IF NOT EXISTS idx_relations_to
    ON relations(to_entity_id, kind);
CREATE INDEX IF NOT EXISTS idx_relations_kind
    ON relations(kind);
