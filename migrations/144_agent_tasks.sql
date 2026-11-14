-- Autonomous agent tasks: a durable work queue for unattended runs.
--
-- Motivation: every piece of machinery needed to run Claude unattended
-- already existed except the one that starts a run. The provider has
-- always launched `claude -p --output-format stream-json` (headless);
-- `agent_sessions`/`agent_runs`/`agent_events` already record the whole
-- turn; `agent_notifications` already reaches the user by email with a
-- decision gate. What was missing is that the ONLY caller of
-- `AgentService.send_message` was the stdio protocol's `message.send`
-- (src/agent/protocol.py), i.e. Emacs. No Emacs, no run.
--
-- This table is the queue that `templedb ai agent tick` drains, so a
-- systemd timer can take Emacs's place as the thing that decides a run
-- should happen now.
--
-- ── Why a table and not a crontab of `templedb ai agent run` lines ───
--
-- Three things a crontab cannot do, all of which cost real incidents in
-- this codebase already:
--
--   1. Claim. Two overlapping timer firings must not drive one
--      conversation concurrently -- `send_message` guards per-session
--      (see its comment on orphaned subprocesses), but nothing stops two
--      ticks from claiming the same *task*. `claimed_at`/`claimed_by`
--      make the claim atomic in the DB, which is the only shared state
--      the two ticks have.
--   2. Remember. `last_status`/`last_error`/`fail_count` make a
--      silently-failing nightly task visible to `agent task list`
--      instead of only to journalctl.
--   3. Carry a policy. `policy` travels with the task into the provider
--      and becomes the PreToolUse deny hook for that run (see
--      src/agent/guard.py). A crontab line would have to re-specify it
--      per invocation and would silently default to whatever the flag
--      default happened to be.
--
-- ── policy values ───────────────────────────────────────────────────
--   'readonly' -- analysis only. No source edits, no commits.
--   'commit'   -- may write file_contents and vcs commit, may NOT
--                 publish, deploy, push, or rebuild. The default,
--                 because it is the line past which an unattended
--                 mistake stops being local to the DB.
--   'publish'  -- may also `publish run` (reaches the public mirror).
--   'trusted'  -- no guard hook at all. Opt-in, never a default.
--
-- ── cadence_sec ─────────────────────────────────────────────────────
-- NULL means one-shot: the task runs once and `enabled` is cleared, so
-- it stays in the table as history rather than vanishing. A number
-- means "reschedule this many seconds after the run FINISHES" (not
-- after it started) -- a 1h cadence on a task that takes 50m should not
-- re-fire 10m after it ends having had no gap to observe anything new.

CREATE TABLE IF NOT EXISTS agent_tasks (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    project_slug TEXT,
    prompt TEXT NOT NULL,
    policy TEXT NOT NULL DEFAULT 'commit',
    model TEXT,
    cadence_sec INTEGER,
    enabled INTEGER NOT NULL DEFAULT 1,

    -- Runaway guards. max_runtime_sec is enforced by the tick wrapper,
    -- not by the provider's IDLE_TIMEOUT_SEC -- that one only fires when
    -- a tool is wedged, and a task can burn hours while making perfectly
    -- healthy forward progress.
    max_runtime_sec INTEGER NOT NULL DEFAULT 3600,

    -- 'never' | 'error' | 'always' -- which outcomes enqueue an
    -- agent_notifications row.
    notify TEXT NOT NULL DEFAULT 'error',

    -- Scheduling state
    next_run_at TEXT,              -- NULL = due now
    claimed_at TEXT,               -- non-NULL = a tick is running it
    claimed_by TEXT,               -- "<host>:<pid>", for stale-claim triage

    -- Last outcome
    last_run_at TEXT,
    last_status TEXT,              -- 'completed' | 'failed' | 'timeout'
    last_error TEXT,
    -- ON DELETE SET NULL, not the default RESTRICT: `ai agent gc` deletes
    -- sessions that hold no findings/todos/notes, and a surviving task row
    -- pointing at one would make that DELETE fail with a FK violation
    -- rather than cleaning up.
    last_session_id INTEGER REFERENCES agent_sessions(id) ON DELETE SET NULL,
    run_count INTEGER NOT NULL DEFAULT 0,
    fail_count INTEGER NOT NULL DEFAULT 0,

    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- The tick's due-task scan: enabled, unclaimed, due.
CREATE INDEX IF NOT EXISTS idx_agent_tasks_due
    ON agent_tasks(next_run_at)
    WHERE enabled = 1 AND claimed_at IS NULL;

-- Stale-claim sweep.
CREATE INDEX IF NOT EXISTS idx_agent_tasks_claimed
    ON agent_tasks(claimed_at)
    WHERE claimed_at IS NOT NULL;
