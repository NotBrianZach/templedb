-- Migration 100: hygiene_snapshots (import-graph hygiene over time)
--
-- Records per-slug counts derived from the python-ingest graph so
-- drift in code hygiene becomes visible without re-computing the
-- CTE on every check.
--
-- Populated by `templedb hygiene snapshot` (CLI) — called ad-hoc or
-- via the daily systemd timer that already runs reconcile.
--
-- The four counts stored per slug:
--   total_imports       File→imports→File edges in this slug
--   dead_candidates     ... where no Symbol→calls|inherits|uses
--                       edge bridges the two files
--   symbol_defines      Symbols defined in this slug's files
--   inherits_edges      Symbol→inherits→Symbol edges rooted here
--
-- Enables a passive doctor invariant like "dead_candidates for
-- slug X grew by >= 20 in the last week" — flagged as concerning
-- import bloat before it becomes hard to unwind.
--
-- Retention: expected small (few slugs × daily) so no GC needed
-- for years. observations_archive-style retention available later
-- if it grows.

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

CREATE INDEX IF NOT EXISTS idx_hygiene_snapshots_slug_time
    ON hygiene_snapshots(slug, taken_at DESC);
