-- Reports become rows. They were a directory with a naming convention.
--
-- The bytes were always in SQLite -- a report is a tracked project file,
-- so `content_blobs` has held every one of them from the start. What
-- lived in the filesystem was the MODEL, and that is the part that
-- caused the trouble:
--
--   existence   file_path GLOB 'reports/[0-9][0-9][0-9][0-9]-*.html'
--   date        a regex over the filename
--   title       a regex for <title> over the blob
--   lede        a regex for <p class="lede"> over the blob
--   identity    report_implementations.report_path, a path string
--
-- Every awkwardness followed from that and none of them were about
-- reports. A markdown report was invisible, because the glob ends in
-- .html -- two bza reports existed for weeks while /reports?project=bza
-- rendered "No reports". reports/CLAUDE.md has to say "don't rename
-- older files just to add time", because the filename is the primary
-- key and links to it live in commit messages. The title is parsed out
-- of presentation markup, so a report with no <title> is "(untitled)"
-- rather than invalid. And `reports reindex` exists at all because the
-- index is a generated artifact that can disagree with the directory.
--
-- A row fixes those by construction rather than by convention: `format`
-- is a column so markdown renders, `created_at` is a timestamp so the
-- filename carries nothing, and `slug` is a stable id that renaming
-- cannot break.
--
-- ── What this does NOT do ────────────────────────────────────────────
--
-- It does not touch how reports are WRITTEN by hand today. A report is
-- still one self-contained document; `body` holds exactly what the file
-- held. The "one browser tab, no missing dependencies" invariant from
-- reports/CLAUDE.md is a property of the document, not of its storage,
-- and it survives unchanged.

CREATE TABLE IF NOT EXISTS reports (
    id            INTEGER PRIMARY KEY,

    -- Which project the report is ABOUT. A real FK, where the old model
    -- had "whichever project happened to track the file" -- so a report
    -- about bza that someone filed under templedb/reports/ was simply a
    -- templedb report, with nothing to disagree with.
    --
    -- ON DELETE CASCADE because a report about a project that no longer
    -- exists is not a report about anything. Note 141_projects_fk_set_null
    -- went the other way for its table; the difference is that an
    -- orphaned report has no residual meaning, whereas the rows that
    -- migration covers do.
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Stable identity, and the thing a URL and a commit message should
    -- name. Kebab title with no date and no extension:
    -- 'mobile-agentic-development', not
    -- '2026-10-27-1952-mobile-agentic-development.html'.
    --
    -- Unique per project rather than globally: two projects may both
    -- have something to say about 'deploy-pipeline', and forcing them to
    -- disambiguate would be the filename problem again in a column.
    slug          TEXT NOT NULL,

    title         TEXT NOT NULL,

    -- One paragraph, for the index listing. A column because it was a
    -- regex over `<p class="lede">` -- which meant the index summary was
    -- a function of the body's markup, and a report that styled its
    -- opening differently simply had no summary.
    lede          TEXT,

    -- The document. Whole, as authored.
    body          TEXT NOT NULL,

    -- The fix the whole migration is for. Rendering is now a property of
    -- the row, so a markdown report is a report.
    format        TEXT NOT NULL DEFAULT 'markdown'
                    CHECK (format IN ('markdown', 'html')),

    -- A real timestamp. Reports keep arriving several a day and the
    -- filename convention grew an HHMM to cope; this orders them
    -- properly and lets the display decide how much precision to show.
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT NOT NULL DEFAULT (datetime('now')),

    -- Reports supersede each other -- a design pass, then what was built
    -- from it. That relationship was previously prose inside the newer
    -- document, so nothing could follow it. Nullable, self-referential,
    -- SET NULL rather than CASCADE: deleting the newer report must not
    -- delete the history it was describing.
    supersedes_id INTEGER REFERENCES reports(id) ON DELETE SET NULL,

    -- The path this was migrated from, for exactly one purpose: making
    -- the 83 report_implementations rows and the links in old commit
    -- messages resolvable. Nullable, because a report written after this
    -- migration never had a path and should not pretend to.
    --
    -- NOT the identity. `slug` is. This column is a forwarding address
    -- and nothing should start reading it as a key.
    legacy_path   TEXT,

    UNIQUE(project_id, slug)
);

CREATE INDEX IF NOT EXISTS idx_reports_project ON reports(project_id);
CREATE INDEX IF NOT EXISTS idx_reports_created ON reports(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_legacy_path ON reports(legacy_path);

-- The graph side of the span, pointed at a row instead of a string.
--
-- Added alongside `report_path` rather than replacing it, and the old
-- column is deliberately left populated. 83 rows reference 25 paths and
-- some of those paths appear in commit messages that are already
-- published; a reader resolving an old reference needs the string to
-- still mean something. The backfill sets `report_id` for every row it
-- can match, and a null afterwards means "no row found for that path",
-- which is a fact worth being able to see rather than hide.
ALTER TABLE report_implementations ADD COLUMN report_id INTEGER
    REFERENCES reports(id) ON DELETE CASCADE;

CREATE INDEX IF NOT EXISTS idx_report_impl_report
    ON report_implementations(report_id);
