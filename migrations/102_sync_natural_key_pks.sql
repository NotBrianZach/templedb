-- Migration 102: switch sync_entities / sync_relations to natural-key PKs
--
-- Fixes the shadow.id collision issue exposed by the two-instance test
-- landed in session recap 9. When two sites make concurrent entity
-- inserts, SQLite's per-DB ROWID counter picks the same value on both,
-- and CRSql's LWW resolution silently drops one of the shadow rows.
-- Result: entity created on site A never reaches site B.
--
-- Fix: drop the INTEGER PRIMARY KEY on shadows, use composite natural
-- keys instead. Entities key on (kind, external_ref); relations key on
-- the 5-tuple of both endpoints' natural keys plus the edge kind.
-- CRSql supports composite PKs, so its clock/pks machinery adapts.
--
-- Safe because sync_entities and sync_relations are empty in prod
-- (created empty by mig 101, `templedb sync init` has not been run
-- there yet). If anyone did run `sync init` between mig 101 and this
-- migration, the DROP TABLE cleans up the CRR companions too.
--
-- See reports/2026-09-05-1808-session-recap-9-crsql-shadows-for-entity-graph.html.

-- ── Drop old shadow tables + triggers + CRSql companions ────────────────────

DROP TRIGGER IF EXISTS entities_sync_fleet_ins;
DROP TRIGGER IF EXISTS entities_sync_fleet_upd;
DROP TRIGGER IF EXISTS entities_sync_unfleet;
DROP TRIGGER IF EXISTS entities_sync_del;
DROP TRIGGER IF EXISTS relations_sync_fleet_ins;
DROP TRIGGER IF EXISTS relations_sync_fleet_upd;
DROP TRIGGER IF EXISTS relations_sync_del;

-- CRR companion tables and their triggers, in case `sync init` ran.
-- SQLite drops the companion triggers with the main table drop, but
-- the companion tables themselves need explicit drops.
DROP TABLE IF EXISTS sync_entities;
DROP TABLE IF EXISTS sync_entities__crsql_clock;
DROP TABLE IF EXISTS sync_entities__crsql_pks;

DROP TABLE IF EXISTS sync_relations;
DROP TABLE IF EXISTS sync_relations__crsql_clock;
DROP TABLE IF EXISTS sync_relations__crsql_pks;

-- ── Recreate with natural-key PKs ───────────────────────────────────────────
-- Both tables use only natural-key columns as identity. No surrogate id;
-- the local main entities.id / relations.id are lookup-only and not
-- carried in the shadow. Reconcile projects back to main by natural key.

CREATE TABLE sync_entities (
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

CREATE TABLE sync_relations (
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

-- ── entities write-through triggers ─────────────────────────────────────────

CREATE TRIGGER entities_sync_fleet_ins
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

CREATE TRIGGER entities_sync_fleet_upd
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

-- Scope transition out of fleet: remove shadow row using OLD natural key.
CREATE TRIGGER entities_sync_unfleet
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

-- Entity delete cascades to any relations via FK, but SQLite fires the
-- child DELETE trigger before we can look up the parent's natural key
-- via the surrogate id (parent may already be gone). Do the cleanup
-- here in the entity trigger where OLD.kind / OLD.external_ref are
-- still available.
CREATE TRIGGER entities_sync_del
AFTER DELETE ON entities
WHEN OLD.external_ref IS NOT NULL
BEGIN
    DELETE FROM sync_entities
     WHERE kind = OLD.kind AND external_ref = OLD.external_ref;
    DELETE FROM sync_relations
     WHERE (from_kind = OLD.kind AND from_external_ref = OLD.external_ref)
        OR (to_kind   = OLD.kind AND to_external_ref   = OLD.external_ref);
END;

-- ── relations write-through triggers ────────────────────────────────────────
-- Source the endpoint natural keys via a JOIN on entities. The subquery
-- returns 0 rows if either endpoint is missing, non-fleet, or has a NULL
-- external_ref — so the INSERT is a no-op in those cases.

CREATE TRIGGER relations_sync_fleet_ins
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

CREATE TRIGGER relations_sync_fleet_upd
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

-- Direct relation delete (not cascaded from entity delete). If either
-- endpoint is already gone the JOIN returns no rows and the DELETE is
-- a no-op — the entities_sync_del trigger already cleaned up in that
-- case.
CREATE TRIGGER relations_sync_del
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
