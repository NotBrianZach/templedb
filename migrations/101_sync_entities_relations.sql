-- Migration 101: sync_entities / sync_relations shadows + write-through triggers
--
-- Completes Q5 (fleet CRDT sync) for the entity graph. Migration 099
-- landed the sync_scope column but deferred the CRSql wiring because
-- the __crsql_clock/__crsql_pks machinery is hard to remove cleanly.
-- This migration lands both:
--   1. The shadow tables (mirror entities/relations without UNIQUE
--      constraints, since CRSql prohibits them on CRRs).
--   2. Write-through triggers so ingest adapter writes to entities/
--      relations propagate into the shadows automatically. Filters
--      by scope: only rows whose endpoints are fleet-scope enter the
--      CRR (~10% of the entity graph today).
--
-- The CRR marking itself (crsql_as_crr) is applied dynamically by
-- `templedb sync init`. That's consistent with how the existing six
-- shadow tables are managed and lets the same DB file be usable on
-- machines that haven't loaded the CRSql extension yet.
--
-- See docs/NEXT_SESSION_PICKUPS.md item 1 and
-- reports/2026-09-05-2230-crsql-prep-notes.html.

-- ── Shadow tables ────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sync_entities (
    id INTEGER PRIMARY KEY NOT NULL,
    kind TEXT DEFAULT '',
    external_ref TEXT DEFAULT '',
    source_authority TEXT DEFAULT '',
    label TEXT DEFAULT '',
    observed_at TEXT DEFAULT '',
    created_at TEXT DEFAULT '',
    attributes_json TEXT DEFAULT '',
    sync_scope TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS sync_relations (
    id INTEGER PRIMARY KEY NOT NULL,
    from_entity_id INTEGER DEFAULT 0,
    kind TEXT DEFAULT '',
    to_entity_id INTEGER DEFAULT 0,
    source_authority TEXT DEFAULT '',
    observed_at TEXT DEFAULT '',
    attributes_json TEXT DEFAULT '',
    sync_scope TEXT DEFAULT ''
);

-- ── entities write-through triggers ─────────────────────────────────────────
-- Fires only when sync_scope='fleet'. Machine-local entities (Symbol,
-- StorePath, ToolCall, etc.) stay out of the CRR entirely.

CREATE TRIGGER IF NOT EXISTS entities_sync_fleet_ins
AFTER INSERT ON entities
WHEN NEW.sync_scope = 'fleet'
BEGIN
    INSERT INTO sync_entities (
        id, kind, external_ref, source_authority, label,
        observed_at, created_at, attributes_json, sync_scope
    ) VALUES (
        NEW.id, NEW.kind, COALESCE(NEW.external_ref, ''),
        NEW.source_authority, COALESCE(NEW.label, ''),
        NEW.observed_at, NEW.created_at,
        COALESCE(NEW.attributes_json, ''), NEW.sync_scope
    )
    ON CONFLICT(id) DO UPDATE SET
        kind             = excluded.kind,
        external_ref     = excluded.external_ref,
        source_authority = excluded.source_authority,
        label            = excluded.label,
        observed_at      = excluded.observed_at,
        created_at       = excluded.created_at,
        attributes_json  = excluded.attributes_json,
        sync_scope       = excluded.sync_scope;
END;

CREATE TRIGGER IF NOT EXISTS entities_sync_fleet_upd
AFTER UPDATE ON entities
WHEN NEW.sync_scope = 'fleet'
BEGIN
    INSERT INTO sync_entities (
        id, kind, external_ref, source_authority, label,
        observed_at, created_at, attributes_json, sync_scope
    ) VALUES (
        NEW.id, NEW.kind, COALESCE(NEW.external_ref, ''),
        NEW.source_authority, COALESCE(NEW.label, ''),
        NEW.observed_at, NEW.created_at,
        COALESCE(NEW.attributes_json, ''), NEW.sync_scope
    )
    ON CONFLICT(id) DO UPDATE SET
        kind             = excluded.kind,
        external_ref     = excluded.external_ref,
        source_authority = excluded.source_authority,
        label            = excluded.label,
        observed_at      = excluded.observed_at,
        created_at       = excluded.created_at,
        attributes_json  = excluded.attributes_json,
        sync_scope       = excluded.sync_scope;
END;

-- Also handle the fleet→non-fleet transition: drop the shadow row so
-- it stops propagating. Symmetric to the INSERT trigger above.
CREATE TRIGGER IF NOT EXISTS entities_sync_unfleet
AFTER UPDATE ON entities
WHEN OLD.sync_scope = 'fleet' AND NEW.sync_scope IS NOT 'fleet'
BEGIN
    DELETE FROM sync_entities WHERE id = OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS entities_sync_del
AFTER DELETE ON entities
BEGIN
    DELETE FROM sync_entities WHERE id = OLD.id;
END;

-- ── relations write-through triggers ────────────────────────────────────────
-- relations.sync_scope is not populated by ingest yet (mig 099 landed
-- the column but no back-fill). Derive fleet-ness from endpoints: a
-- relation is fleet iff both endpoint entities are fleet. The subquery
-- INSERT ... SELECT pattern returns zero rows when the condition
-- fails, so no WHEN clause is needed.

CREATE TRIGGER IF NOT EXISTS relations_sync_fleet_ins
AFTER INSERT ON relations
BEGIN
    INSERT INTO sync_relations (
        id, from_entity_id, kind, to_entity_id, source_authority,
        observed_at, attributes_json, sync_scope
    )
    SELECT NEW.id, NEW.from_entity_id, NEW.kind, NEW.to_entity_id,
           NEW.source_authority, NEW.observed_at,
           COALESCE(NEW.attributes_json, ''), 'fleet'
      FROM entities ef, entities et
     WHERE ef.id = NEW.from_entity_id
       AND et.id = NEW.to_entity_id
       AND ef.sync_scope = 'fleet'
       AND et.sync_scope = 'fleet'
    ON CONFLICT(id) DO UPDATE SET
        from_entity_id   = excluded.from_entity_id,
        kind             = excluded.kind,
        to_entity_id     = excluded.to_entity_id,
        source_authority = excluded.source_authority,
        observed_at      = excluded.observed_at,
        attributes_json  = excluded.attributes_json,
        sync_scope       = excluded.sync_scope;
END;

CREATE TRIGGER IF NOT EXISTS relations_sync_fleet_upd
AFTER UPDATE ON relations
BEGIN
    INSERT INTO sync_relations (
        id, from_entity_id, kind, to_entity_id, source_authority,
        observed_at, attributes_json, sync_scope
    )
    SELECT NEW.id, NEW.from_entity_id, NEW.kind, NEW.to_entity_id,
           NEW.source_authority, NEW.observed_at,
           COALESCE(NEW.attributes_json, ''), 'fleet'
      FROM entities ef, entities et
     WHERE ef.id = NEW.from_entity_id
       AND et.id = NEW.to_entity_id
       AND ef.sync_scope = 'fleet'
       AND et.sync_scope = 'fleet'
    ON CONFLICT(id) DO UPDATE SET
        from_entity_id   = excluded.from_entity_id,
        kind             = excluded.kind,
        to_entity_id     = excluded.to_entity_id,
        source_authority = excluded.source_authority,
        observed_at      = excluded.observed_at,
        attributes_json  = excluded.attributes_json,
        sync_scope       = excluded.sync_scope;
END;

CREATE TRIGGER IF NOT EXISTS relations_sync_del
AFTER DELETE ON relations
BEGIN
    DELETE FROM sync_relations WHERE id = OLD.id;
END;
