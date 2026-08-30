-- Temple Agent: audit trail of user edits to agent-owned state.
--
-- Every time the user removes / marks-done / edits an agent-written
-- entry (findings, todo, open-questions, dynamic:*), we log a row
-- here. On the next message.send, the protocol layer walks the
-- unconsumed rows since the last assistant message and prepends a
-- compact system note to the outbound content so the model knows
-- its state was mutated.
--
-- This closes the human/agent asymmetry: before this table, the
-- agent could write into shared sections but had no visibility
-- when the user edited them back. See reflection report:
-- reports/2026-08-30-reflection-on-the-agent-buffer-bet.html.

CREATE TABLE IF NOT EXISTS agent_user_edits (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES agent_sessions(id),
    -- Section id as seen by Emacs. Matches agent_session_sections.section.
    section TEXT NOT NULL,
    -- The specific entry that was edited, or NULL for section-scope events
    -- (e.g. section-wide clear).
    entry_id TEXT,
    -- One of: 'removed' | 'marked_done' | 'edited' | 'promoted' | 'section_cleared'
    action TEXT NOT NULL,
    -- Snapshot of the entry BEFORE the edit, as JSON. NULL for actions
    -- that don't need before-state (e.g. section-cleared).
    before_json TEXT,
    -- Was this row already surfaced to the agent in a message.send?
    -- NULL = not yet consumed. Timestamp = when it was included in a
    -- system note. Consumed rows stick around for audit.
    consumed_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS agent_user_edits_unconsumed
    ON agent_user_edits(session_id, consumed_at)
    WHERE consumed_at IS NULL;
