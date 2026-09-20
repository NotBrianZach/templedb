-- Migration 093: handoff_notes (Phase 2.5)
--
-- Cross-session pinboard. Pull-based: sending agents insert, receiving
-- agents check when they feel like it. No daemons, no push. Enables
-- cross-session communication that the observer/integrator plan
-- didn't explicitly name but which multi-agent workflows want.
--
-- Design source: reports/2026-09-03-0826-cross-session-handoff-semantics.html
-- (authored by another session). Schema follows that report exactly.
--
-- Companion to edit_intents (Phase 2, session→file coordination):
-- handoff_notes is session→session, session→topic, or broadcast.
-- Both are first-class junction objects with lifecycle.
--
-- expires_at is display-only, not a hard TTL. Old notes stick around
-- for provenance; queries filter them out by default.

CREATE TABLE IF NOT EXISTS handoff_notes (
    id              INTEGER PRIMARY KEY,

    -- Sender identity. from_session is TEMPLEDB_SESSION_ID or a
    -- fallback derived from (host, ppid) if the env var isn't set.
    from_session    TEXT NOT NULL,
    from_actor      TEXT,   -- 'claude-code', 'vibe', 'human', 'temple-agent'

    -- Destination. Exactly one of to_session / to_topic / (both NULL
    -- = broadcast) is typical. Convention, not enforced, so a note
    -- can address both a session AND a topic if useful.
    to_session      TEXT,
    to_topic        TEXT,   -- 'templedb', 'refactor:foo', ...

    -- Content
    subject         TEXT NOT NULL,
    body            TEXT NOT NULL,
    tags            TEXT,   -- comma-separated

    -- Cross-references into other authoritative objects
    ref_report      TEXT,   -- reports/YYYY-MM-DD-HHMM-slug.html
    ref_commit      TEXT,   -- commit hash prefix or full
    ref_file        TEXT,   -- project_slug:path
    project_id      INTEGER REFERENCES projects(id),

    -- Lifecycle
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    read_at         TEXT,
    acked_at        TEXT,
    expires_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_handoff_notes_to_session
    ON handoff_notes(to_session, acked_at);
CREATE INDEX IF NOT EXISTS idx_handoff_notes_to_topic
    ON handoff_notes(to_topic, acked_at);
CREATE INDEX IF NOT EXISTS idx_handoff_notes_project
    ON handoff_notes(project_id);
CREATE INDEX IF NOT EXISTS idx_handoff_notes_broadcast
    ON handoff_notes(created_at DESC)
    WHERE to_session IS NULL AND to_topic IS NULL;
