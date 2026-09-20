-- Long-running agent check-ins: durable notification queue.
--
-- Motivation: autonomous/scheduled agents need a way to reach the user
-- when there's no interactive UI attached. First transport is email
-- (send-only). This table is the queue; a worker (CLI `agent notify
-- drain`, later a scheduler tick) drains rows and dispatches via
-- src/services/email_service.py.
--
-- kind values (informational, not constrained):
--   'progress' — FYI status update; send-only, no ack needed.
--   'error'    — agent hit a stuck state / uncaught exception.
--   'final'    — task complete; closes the loop for a scheduled run.
--   'decision' — agent is about to do something and wants a chance to be
--                stopped. pending_until + decision_default drive the
--                send-only fallback: caller polls this row; if a
--                templedb_ai_agent_decide row lands, honor it; else at
--                pending_until, proceed with decision_default.
--
-- session_id is nullable so scripts/tests can enqueue without an
-- agent session (e.g. `templedb ai agent notify test`).

CREATE TABLE IF NOT EXISTS agent_notifications (
    id INTEGER PRIMARY KEY,
    session_id INTEGER REFERENCES agent_sessions(id),
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    body_md TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),

    -- Send state
    sent_at TEXT,
    send_error TEXT,
    send_attempts INTEGER NOT NULL DEFAULT 0,

    -- Decision-point fields (only meaningful when kind='decision')
    pending_until TEXT,          -- ISO timestamp; NULL = not a wait
    decision_default TEXT,       -- 'approve' | 'deny' — used on timeout
    decided_at TEXT,
    decision TEXT                -- 'approve' | 'deny' | 'timeout'
);

CREATE INDEX IF NOT EXISTS idx_agent_notifications_unsent
    ON agent_notifications(created_at)
    WHERE sent_at IS NULL;

CREATE INDEX IF NOT EXISTS idx_agent_notifications_session
    ON agent_notifications(session_id);

CREATE INDEX IF NOT EXISTS idx_agent_notifications_pending_decision
    ON agent_notifications(pending_until)
    WHERE pending_until IS NOT NULL AND decided_at IS NULL;
