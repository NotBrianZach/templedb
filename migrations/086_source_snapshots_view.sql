-- Migration 086: source_snapshots view
--
-- Phase 1 of the observer/integrator plan. Reframes file_contents +
-- vcs_file_states as "observations of source at a point in time"
-- rather than "authoritative bytes of source." No table changes; a
-- new view exposes the observation semantics cleanly.
--
-- Design notes:
--
-- 1. UNION over current-state (file_contents.is_current=1) and
--    historical-state (vcs_file_states). Same shape either way.
--
-- 2. The `revision` column: 'current' for the head/is-current row,
--    a real commit_hash for historical rows. Downstream queries
--    can filter WHERE revision = ? or WHERE revision = 'current'.
--
-- 3. `observed_at`: file_contents.updated_at for current; the parent
--    commit's timestamp for historical. Records when TempleDB last
--    observed this state from its authority.
--
-- 4. `source_authority`: currently always 'git' — every project
--    TempleDB tracks originates in git (or at least behaves like it).
--    Column exists so future ingestion algebras (SCIP, upstream
--    packages, etc.) can declare a different authority when the
--    time comes.
--
-- 5. `content_text` / `content_blob` are pulled from content_blobs
--    for the current row (which stores content once, deduplicated)
--    and from vcs_file_states directly for historical rows (which
--    embed content per-commit — pre-dedup design that we live with
--    for now).
--
-- Backward compat: file_contents and vcs_file_states are unchanged.
-- Every existing query keeps working. The view is purely additive.

CREATE VIEW IF NOT EXISTS source_snapshots AS
    -- Current state (is_current = 1 in file_contents)
    SELECT
        p.slug                       AS project_slug,
        pf.file_path                 AS file_path,
        'current'                    AS revision,
        fc.content_hash              AS content_hash,
        cb.content_text              AS content_text,
        cb.content_blob              AS content_blob,
        cb.content_type              AS content_type,
        fc.file_size_bytes           AS file_size_bytes,
        fc.line_count                AS line_count,
        fc.updated_at                AS observed_at,
        'git'                        AS source_authority
    FROM file_contents fc
    JOIN project_files pf   ON pf.id = fc.file_id
    JOIN projects p         ON p.id = pf.project_id
    JOIN content_blobs cb   ON cb.hash_sha256 = fc.content_hash
    WHERE fc.is_current = 1
      AND pf.status = 'active'

    UNION ALL

    -- Historical state (any vcs_file_states row)
    SELECT
        p.slug                       AS project_slug,
        pf.file_path                 AS file_path,
        c.commit_hash                AS revision,
        vfs.content_hash             AS content_hash,
        vfs.content_text             AS content_text,
        vfs.content_blob             AS content_blob,
        CASE
            WHEN vfs.content_text IS NOT NULL THEN 'text'
            WHEN vfs.content_blob IS NOT NULL THEN 'binary'
            ELSE NULL
        END                          AS content_type,
        vfs.file_size                AS file_size_bytes,
        vfs.line_count               AS line_count,
        c.commit_timestamp           AS observed_at,
        'git'                        AS source_authority
    FROM vcs_file_states vfs
    JOIN vcs_commits c      ON c.id = vfs.commit_id
    JOIN project_files pf   ON pf.id = vfs.file_id
    JOIN projects p         ON p.id = pf.project_id;
