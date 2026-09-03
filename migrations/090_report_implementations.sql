-- Migration 090: report_implementations (first-class span)
--
-- Workflow F from reports/2026-09-02-2029-workflow-walkthrough-*.html:
-- "Which of these design reports actually got implemented?"
-- Currently unanswerable at query time (grep commit messages, guess).
-- After this, a graph query: Report ← ReportImpl → Commit.
--
-- Per docs/ENTITY_GRAPH_DESIGN.md, this is a proper span with its own
-- identity, lifecycle, and attributes. Not just a relations-table edge.
--
-- Lifecycle:
--   auto-detected  →  confirmed  →  verified
--                  ↘  rejected
--
-- auto-detected: ingest scanner regex-matched a commit hash prefix in
--                the report HTML and validated against vcs_commits.
-- confirmed:     a human ran `templedb report link` explicitly, or ran
--                `report confirm` on an auto-detected suggestion.
-- verified:      someone ran `report verify` and asserted the linked
--                commit actually implements the report's proposal.
-- rejected:      auto-detection was wrong; a human dismissed it.

CREATE TABLE IF NOT EXISTS report_implementations (
    id                INTEGER PRIMARY KEY,

    -- Report side of the span
    report_path       TEXT NOT NULL,   -- e.g. reports/2026-09-02-1430-…html
    project_slug      TEXT NOT NULL,   -- usually 'templedb'

    -- Commit side of the span
    commit_hash       TEXT NOT NULL,   -- full or prefix; resolved on read

    -- Lifecycle + attribution
    confidence        TEXT NOT NULL DEFAULT 'auto-detected'
                        CHECK (confidence IN
                            ('auto-detected', 'confirmed',
                             'verified', 'rejected')),
    note              TEXT,             -- human explanation, if any
    linked_by         TEXT,             -- author who confirmed/rejected

    -- Timestamps
    linked_at         TEXT NOT NULL DEFAULT (datetime('now')),
    verified_at       TEXT,

    UNIQUE(report_path, commit_hash)
);

CREATE INDEX IF NOT EXISTS idx_report_impls_report
    ON report_implementations(report_path);
CREATE INDEX IF NOT EXISTS idx_report_impls_commit
    ON report_implementations(commit_hash);
CREATE INDEX IF NOT EXISTS idx_report_impls_confidence
    ON report_implementations(confidence);
