-- Migration 094: tool_calls (Phase 3 extraction from agent_events)
--
-- Promotes tool invocations to a first-class span:
--     AgentRun ← ToolCall → Tool
-- per docs/ENTITY_GRAPH_DESIGN.md. Was flagged by the schema-report
-- (reports/2026-09-03-0843-proposed-schema-*.html) as a Phase 3
-- promotion target.
--
-- Rationale: agent_events currently mixes low-value log lines
-- (assistant.started/completed) with high-value structured events
-- (tool.started/completed). The tool calls carry identity (they can
-- be queried by tool_name, matched against source edits, aggregated
-- per session) and deserve their own table.
--
-- Backfill included: existing tool.started rows in agent_events get
-- one tool_calls row each, status='unknown' since we don't have
-- paired completions for most historical data (993 started vs 4
-- completed in the live DB as of 2026-09-03). Going forward, the
-- agent runtime should write tool_calls directly instead of just
-- agent_events rows — that's a separate change.

CREATE TABLE IF NOT EXISTS tool_calls (
    id                INTEGER PRIMARY KEY,

    -- Provenance to the run + session it happened in
    run_id            INTEGER NOT NULL REFERENCES agent_runs(id)
                        ON DELETE CASCADE,
    session_id        INTEGER,   -- denormalized for direct index

    -- What was called
    tool_name         TEXT NOT NULL,

    -- Lifecycle
    started_at        TEXT NOT NULL,
    finished_at       TEXT,       -- NULL if still running or unknown
    status            TEXT NOT NULL DEFAULT 'unknown'
                        CHECK (status IN
                            ('running', 'completed', 'failed', 'unknown')),

    -- Optional detail: hashes so we can query "same tool + same args"
    -- across sessions once agent runtime records them.
    args_hash         TEXT,
    result_hash       TEXT,

    -- Traceability back to the event that produced this row.
    source_event_id   INTEGER REFERENCES agent_events(id)
                        ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_run
    ON tool_calls(run_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_session
    ON tool_calls(session_id);
CREATE INDEX IF NOT EXISTS idx_tool_calls_tool
    ON tool_calls(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_calls_active
    ON tool_calls(status)
    WHERE status IN ('running', 'unknown');

-- Backfill from existing agent_events. Only tool.started rows —
-- tool.completed rows may or may not correspond, and we don't know
-- from the payload which specific tool.started they close. Since
-- 993:4 is the observed ratio, treating unpaired starts as 'unknown'
-- is the honest thing to do.
INSERT INTO tool_calls
       (run_id, session_id, tool_name, started_at,
        finished_at, status, source_event_id)
SELECT
    ae.run_id,
    ar.session_id,
    COALESCE(json_extract(ae.payload_json, '$.tool_name'), 'unknown'),
    ae.created_at,
    NULL,
    'unknown',
    ae.id
FROM agent_events ae
JOIN agent_runs ar ON ar.id = ae.run_id
WHERE ae.event_type = 'tool.started';
