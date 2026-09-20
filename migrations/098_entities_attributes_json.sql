-- Migration 098: entities.attributes_json column
--
-- The relations table has attributes_json since migration 089 for
-- lightweight edge attributes; entities never got the equivalent
-- because the design deferred to first-class spans. Q4 dual-write
-- (backfill vcs_commit_parents + vcs_commit_metadata onto Commit
-- entities) needs a place to land, though — and general-purpose
-- entity-level attributes are useful beyond that one case.
--
-- Nullable TEXT storing arbitrary JSON. Keep it small (few KB per
-- entity); if a shape grows beyond that, promote to a first-class
-- span table (see docs/ENTITY_GRAPH_DESIGN.md).

ALTER TABLE entities ADD COLUMN attributes_json TEXT;
