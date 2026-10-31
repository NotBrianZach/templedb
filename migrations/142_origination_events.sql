-- Append-only inbox for device-originated events.
--
-- This is the Tier 3 half of the mobile report that survived its own
-- cost analysis (reports/2026-10-27-1952-mobile-agentic-development).
-- The report's finding was that almost everything a participating
-- phone would do -- queue a prompt with no signal, capture a thought
-- walking, approve a pending decision, witness a machine being down --
-- is offline ORIGINATION, not merge: one-way, append-only, no
-- concurrent edits to the same row, nothing to reconcile. That needs a
-- queue, not a CRDT replica.
--
-- Deliberately NOT in the cr-sqlite sync set. Adding it there would
-- buy the merge semantics this table exists to avoid, and would make
-- the phone the first peer a never-exercised replication layer has
-- ever had. The eight shadow tables stay as they are.
--
-- The transport is whatever can reach the mothership; the first one is
-- SSH, which Tier 0 already needs. That matters: it means origination
-- works before the GUI auth question is settled, and adds no listening
-- port.

CREATE TABLE IF NOT EXISTS origination_events (
    id             INTEGER PRIMARY KEY,

    -- Client-generated, and the whole reason a retry is safe. A phone
    -- on bad signal cannot know whether its submit landed, so it
    -- resubmits; submit is INSERT OR IGNORE on this column, so the
    -- second copy is a no-op rather than a duplicate prompt.
    event_uuid     TEXT NOT NULL UNIQUE,

    -- Which device originated it. Not a fleet_machines FK on purpose:
    -- that table's columns (target_host, nixos_version, system_profile,
    -- deployment_status) describe a machine TempleDB deploys NixOS to
    -- over SSH, and a handset is none of that. A row there would have
    -- every interesting column NULL, which the Rust port's README
    -- calls out as worse than an absent row. A free-text device id is
    -- the honest shape until there is something real to reference.
    device_id      TEXT NOT NULL,

    kind           TEXT NOT NULL,
    payload_json   TEXT NOT NULL,

    -- occurred_at is the DEVICE's clock: when the thought happened,
    -- which is the fact offline origination exists to preserve. It is
    -- not validated against the server clock and may be skewed or in
    -- the future -- that is accepted, because a wrong timestamp is
    -- worth more than a lost capture.
    occurred_at    TEXT NOT NULL,
    -- received_at is the server clock, so delivery lag is visible
    -- rather than collapsed into one timestamp.
    received_at    TEXT NOT NULL DEFAULT (datetime('now')),

    -- Apply is a SEPARATE step from submit, and rows are never deleted
    -- by it. A captured thought is not lost because an applier had a
    -- bug: the event stays, applied_at stays NULL, apply_error says
    -- why, and it is retried next sweep. That also makes this table a
    -- durable record of what each device originated and when.
    applied_at     TEXT,
    apply_result   TEXT,
    apply_error    TEXT,
    apply_attempts INTEGER NOT NULL DEFAULT 0
);

-- The sweep's query: unapplied, oldest device-clock first, so events
-- land in the order they were thought of rather than the order they
-- happened to upload.
CREATE INDEX IF NOT EXISTS idx_origination_pending
    ON origination_events(applied_at, occurred_at);

CREATE INDEX IF NOT EXISTS idx_origination_device
    ON origination_events(device_id, occurred_at);
