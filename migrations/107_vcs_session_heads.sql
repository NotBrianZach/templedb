-- Migration 107: per-session branch heads (Phase B of session-scoped VCS)
--
-- Motivation: today `vcs_branches.head_commit_id` is single-valued and
-- only sporadically updated (the workspace-commit path in
-- src/cli/commands/commit.py never advances it; most readers derive
-- HEAD as `ORDER BY commit_timestamp DESC LIMIT 1`). Two parallel
-- sessions committing to the same branch race silently: both commits
-- attach to the branch and "HEAD" is whichever came last.
--
-- Fix: sessions own their commits privately until publish. Each new
-- commit is tagged with its owning session via vcs_commits.session_id.
-- Each (session, branch) pair has at most one row in vcs_session_heads
-- tracking the session's private tip and the shared HEAD it forked
-- from. Publishing a session's tip is a fast-forward-or-fail check
-- against the shared HEAD (Phase B step 2, in service code).
--
-- Views:
--   published view = vcs_commits WHERE session_id IS NULL
--   session view   = vcs_commits WHERE session_id IS NULL OR session_id = ?
--
-- Publish (in service code, not this migration):
--   1. Look up vcs_session_heads(session_id=me, branch_id=b).
--   2. If shared head == session_head.base: fast-forward.
--        UPDATE vcs_branches SET head_commit_id = session_head.head_commit_id
--        UPDATE vcs_commits  SET session_id = NULL WHERE session_id = me AND branch_id = b
--        DELETE FROM vcs_session_heads WHERE id = session_head.id
--   3. Else: fail with 'cannot fast-forward: shared HEAD diverged'.

CREATE TABLE IF NOT EXISTS vcs_session_heads (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES vcs_sessions(id) ON DELETE CASCADE,
    branch_id INTEGER NOT NULL REFERENCES vcs_branches(id) ON DELETE CASCADE,
    head_commit_id INTEGER NOT NULL REFERENCES vcs_commits(id),
    base_commit_id INTEGER REFERENCES vcs_commits(id),  -- NULL = branch was empty at session start
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(session_id, branch_id)
);

CREATE INDEX IF NOT EXISTS idx_vcs_session_heads_session
    ON vcs_session_heads(session_id);
CREATE INDEX IF NOT EXISTS idx_vcs_session_heads_branch
    ON vcs_session_heads(branch_id);

-- vcs_commits.session_id: NULL = published; non-NULL = still owned by
-- that session (not yet fast-forwarded onto shared HEAD).
ALTER TABLE vcs_commits ADD COLUMN session_id INTEGER REFERENCES vcs_sessions(id);

CREATE INDEX IF NOT EXISTS idx_vcs_commits_session
    ON vcs_commits(session_id)
    WHERE session_id IS NOT NULL;
