-- 139_vcs_merges.sql
--
-- Record merges while they are underway, and what the agent driving one
-- said it was doing.
--
-- `vcs merge` is already a multi-step, resumable operation: on conflict it
-- writes markers into vcs_working_state, prints the file list, and exits 1,
-- leaving the human (or agent) to resolve and commit. But nothing records
-- that a merge is in flight. The only trace is vcs_working_state rows with
-- state='conflict' — and those carry no branch, no base commit, no author,
-- no timestamp and no account of intent. Come back an hour later, or arrive
-- as a different agent, and the situation is unreadable: you can see three
-- files have conflict markers and not what merge produced them, which side
-- was which, which other files were already auto-merged, or why.
--
-- A completed merge is recoverable after the fact from
-- vcs_commits.merge_parent_commit_id. An *interrupted* one is not
-- recoverable from anything, which is exactly when the record matters.
--
-- Two tables:
--
--   vcs_merges        one row per merge attempt, with the plan the agent
--                     wrote before starting. `plan_md` is testimony, not
--                     derived state: it says what this merge is for and how
--                     conflicts are meant to be settled, so another agent
--                     reading it inherits the intent rather than guessing
--                     it from markers.
--
--   vcs_merge_files   one row per file the merge touched, with its
--                     disposition and the reason for it. `reasoning` is
--                     where a per-file judgement goes — the resolver
--                     already computes ai_reasoning/ai_confidence for every
--                     conflict and currently discards both.
--
-- Deliberately NOT a lock. Recording a merge does not prevent a second one;
-- the guard for that is the existing dirty-working-state check. This table
-- answers "what is going on", which is a different question from "may I
-- proceed", and conflating them would make a crashed merge block the fix.

CREATE TABLE IF NOT EXISTS vcs_merges (
    id                INTEGER PRIMARY KEY,
    project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Branch being merged FROM / INTO, by id and by name. The names are
    -- denormalised on purpose: a branch can be deleted after the merge and
    -- the record still has to read sensibly.
    source_branch_id  INTEGER REFERENCES vcs_branches(id),
    source_branch     TEXT NOT NULL,
    target_branch_id  INTEGER REFERENCES vcs_branches(id),
    target_branch     TEXT NOT NULL,

    -- The three points of the three-way merge, as resolved at start.
    base_commit_id    INTEGER REFERENCES vcs_commits(id),
    source_commit_id  INTEGER REFERENCES vcs_commits(id),
    target_commit_id  INTEGER REFERENCES vcs_commits(id),

    strategy          TEXT NOT NULL DEFAULT 'manual',
    squash            INTEGER NOT NULL DEFAULT 0,

    --   in_progress  opened, outcome not yet known
    --   conflicted   stopped with conflicts; markers are in
    --                vcs_working_state and someone must resolve them
    --   completed    merge commit created (see merge_commit_id)
    --   abandoned    given up on deliberately; says so rather than
    --                leaving an in_progress row to rot
    status            TEXT NOT NULL DEFAULT 'in_progress'
                        CHECK (status IN ('in_progress', 'conflicted',
                                          'completed', 'abandoned')),

    -- Agent testimony. Written by whoever starts the merge, for whoever
    -- picks it up: why this merge, and how conflicts should be settled.
    plan_md           TEXT,

    -- Who. author is free text as elsewhere in vcs_*; session_id ties the
    -- merge to the staging session so a parallel agent's work is
    -- attributable.
    author            TEXT,
    session_id        INTEGER REFERENCES vcs_sessions(id),

    merge_commit_id   INTEGER REFERENCES vcs_commits(id),
    conflict_count    INTEGER NOT NULL DEFAULT 0,
    auto_merged_count INTEGER NOT NULL DEFAULT 0,

    started_at        TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at      TEXT,
    outcome_note      TEXT
);

CREATE INDEX IF NOT EXISTS idx_vcs_merges_project_status
    ON vcs_merges(project_id, status);
CREATE INDEX IF NOT EXISTS idx_vcs_merges_started
    ON vcs_merges(started_at DESC);

CREATE TABLE IF NOT EXISTS vcs_merge_files (
    id              INTEGER PRIMARY KEY,
    merge_id        INTEGER NOT NULL REFERENCES vcs_merges(id) ON DELETE CASCADE,

    -- file_id can be NULL: a path present only on the source side may have
    -- no project_files row on this branch yet. The path is the identity
    -- here, which is also why it is NOT NULL.
    file_id         INTEGER,
    file_path       TEXT NOT NULL,

    --   auto_merged   three-way merge succeeded with no human input
    --   fast_forward  unchanged on our side; took theirs wholesale
    --   conflict      needs resolution; markers written
    --   resolved      was a conflict, since settled
    --   taken_ours / taken_theirs   settled by strategy, not by content
    --   skipped       no change on the source side
    disposition     TEXT NOT NULL
                      CHECK (disposition IN ('auto_merged', 'fast_forward',
                                             'conflict', 'resolved',
                                             'taken_ours', 'taken_theirs',
                                             'skipped')),
    conflict_type   TEXT,

    ours_hash       TEXT,
    theirs_hash     TEXT,
    base_hash       TEXT,

    -- Per-file testimony: why this disposition. For a conflict settled by
    -- an agent, the argument for the resolution. `confidence` mirrors the
    -- resolver's high/medium/low and the Prolog strategy rules' third
    -- argument, both of which are currently computed and thrown away.
    reasoning       TEXT,
    confidence      TEXT,
    decided_by      TEXT,          -- 'three-way' | 'strategy:ours' | agent id

    resolved_at     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),

    UNIQUE(merge_id, file_path)
);

CREATE INDEX IF NOT EXISTS idx_vcs_merge_files_merge
    ON vcs_merge_files(merge_id, disposition);
