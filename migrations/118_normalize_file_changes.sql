-- Migration 118: one table for "what happened to a file in a commit".
--
-- Before this there were two, written by different code paths and each
-- holding something the other lacked:
--
--   vcs_file_states  3870 rows / 636 commits — snapshot. content_hash
--                    plus an INLINE COPY of the bytes, file_size,
--                    line_count. Written by the native commit paths
--                    (cli/commands/commit.py, vcs.py).
--   commit_files     1492 rows / 234 commits — delta. old_content_hash,
--                    new_content_hash, and the file's PATH. Written only
--                    by vcs_repository.record_file_change and the git
--                    importer.
--
-- Any query against one silently missed the history recorded in the
-- other. Measured before writing this (2026-10-01):
--
--   * 1437 of commit_files' 1492 rows overlap vcs_file_states on
--     (commit_id, file_id); only 55 pairs are unique to it.
--   * The two never genuinely disagree on content hash. All 715 apparent
--     conflicts are commit_files storing NULL for a delete while
--     vcs_file_states records the hash — different conventions, not
--     different facts.
--   * commit_files is NOT redundant: all 140 of its rows whose file_id
--     no longer exists in project_files carry the only surviving copy of
--     that file's path, and all 99 equivalent vcs_file_states rows can
--     recover their path only from a commit_files row. project_files is
--     hard-deleted on commit (cli/commands/file.py) so file history
--     deliberately outlives it. Hence file_path below, denormalized, and
--     hence NO foreign key on file_id — an enforced one would reject
--     exactly the history this preserves.
--
-- Content moves out entirely: the inline columns duplicated content_blobs
-- for 2877 rows / ~79 MB. Migration 117 first promoted the 6 rows whose
-- bytes existed ONLY inline (hashes verified before and after). 8 rows
-- remain whose content was already lost before today — no blob, no
-- inline copy. They are kept as tombstones because the hash and
-- change_type are still real history, and source_snapshots already
-- returned NULL content for them.
--
-- Normalized in place rather than under a new name: 14 modules and 5
-- views already read vcs_file_states, so renaming would have churned all
-- of them to no benefit. commit_files becomes a compatibility view.
--
-- 'unmodified' is in the CHECK because 90 existing rows use it;
-- commit_files' old CHECK listed only four values and would have
-- rejected them.

-- Structured to avoid ALTER TABLE ... RENAME. RENAME re-validates every
-- view in the schema, and mid-migration the five views that read
-- vcs_file_states still name the table being dropped, so it fails with
-- "error in view file_version_history_view: no such table". The obvious
-- fix, PRAGMA legacy_alter_table=ON, does NOT work from inside a
-- migration: executescript runs the script in a transaction and that
-- pragma is a documented no-op there — verified, it reads back as 0 and
-- the rename still fails. Setting it on the connection would mean
-- changing the migrator for one migration.
--
-- So: stage the merged rows in a scratch table, drop both originals,
-- recreate vcs_file_states under its own name, and refill. Dropping and
-- recreating a table does not trigger view revalidation (views resolve
-- lazily), so the four views that only read columns kept below never need
-- to be touched.
BEGIN;

CREATE TABLE _vfs_merged (
    id               INTEGER PRIMARY KEY,
    commit_id        INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,

    -- No FK: see header. project_files is hard-deleted on commit and this
    -- row must outlive it.
    file_id          INTEGER NOT NULL,
    file_path        TEXT,

    change_type      TEXT NOT NULL
                       CHECK(change_type IN ('added', 'modified', 'deleted',
                                             'renamed', 'unmodified')),

    -- Content at this commit, by reference only. Nullable: a row whose
    -- content predates content_blobs is a tombstone, not a corruption.
    content_hash     TEXT,
    old_content_hash TEXT,
    previous_path    TEXT,

    file_size        INTEGER,
    line_count       INTEGER,

    UNIQUE(commit_id, file_id)
);

-- Snapshot rows first: they are the richer side (file_size, line_count),
-- and carry the hash convention we keep.
INSERT INTO _vfs_merged
    (commit_id, file_id, file_path, change_type,
     content_hash, old_content_hash, previous_path, file_size, line_count)
SELECT v.commit_id,
       v.file_id,
       COALESCE(
           (SELECT COALESCE(c.old_file_path, c.new_file_path)
              FROM commit_files c
             WHERE c.commit_id = v.commit_id AND c.file_id = v.file_id),
           (SELECT pf.file_path FROM project_files pf WHERE pf.id = v.file_id)
       ),
       v.change_type,
       v.content_hash,
       (SELECT c.old_content_hash
          FROM commit_files c
         WHERE c.commit_id = v.commit_id AND c.file_id = v.file_id),
       v.previous_path,
       v.file_size,
       v.line_count
  FROM vcs_file_states v;

-- Then the 55 pairs only commit_files knows about.
INSERT OR IGNORE INTO _vfs_merged
    (commit_id, file_id, file_path, change_type,
     content_hash, old_content_hash, previous_path, file_size, line_count)
SELECT c.commit_id,
       c.file_id,
       COALESCE(c.old_file_path, c.new_file_path,
                (SELECT pf.file_path FROM project_files pf WHERE pf.id = c.file_id)),
       c.change_type,
       c.new_content_hash,
       c.old_content_hash,
       NULL, NULL, NULL
  FROM commit_files c
 WHERE NOT EXISTS (SELECT 1 FROM vcs_file_states v
                    WHERE v.commit_id = c.commit_id AND v.file_id = c.file_id);

DROP TABLE vcs_file_states;
DROP TABLE commit_files;

CREATE TABLE vcs_file_states (
    id               INTEGER PRIMARY KEY,
    commit_id        INTEGER NOT NULL REFERENCES vcs_commits(id) ON DELETE CASCADE,
    file_id          INTEGER NOT NULL,
    file_path        TEXT,
    change_type      TEXT NOT NULL
                       CHECK(change_type IN ('added', 'modified', 'deleted',
                                             'renamed', 'unmodified')),
    content_hash     TEXT,
    old_content_hash TEXT,
    previous_path    TEXT,
    file_size        INTEGER,
    line_count       INTEGER,
    UNIQUE(commit_id, file_id)
);

INSERT INTO vcs_file_states
    (id, commit_id, file_id, file_path, change_type,
     content_hash, old_content_hash, previous_path, file_size, line_count)
SELECT id, commit_id, file_id, file_path, change_type,
       content_hash, old_content_hash, previous_path, file_size, line_count
  FROM _vfs_merged;

DROP TABLE _vfs_merged;

CREATE INDEX IF NOT EXISTS idx_vcs_file_states_file
    ON vcs_file_states(file_id);
CREATE INDEX IF NOT EXISTS idx_vcs_file_states_hash
    ON vcs_file_states(content_hash);

-- Compatibility view. Reproduces commit_files' original conventions so
-- existing readers (cathedral_export, git_export) keep working: a delete
-- reports NULL new_content_hash, and the path sits in old_file_path for
-- deletes and new_file_path otherwise. The view now covers ALL commits
-- rather than only the 234 that had commit_files rows — those readers
-- were silently missing native commits, which is the bug being fixed.
-- lines_added/lines_removed were present but never populated (every row
-- was 0), so they are reported as 0 rather than preserved.
CREATE VIEW commit_files AS
SELECT v.id                                   AS id,
       v.commit_id                            AS commit_id,
       v.file_id                              AS file_id,
       v.change_type                          AS change_type,
       v.old_content_hash                     AS old_content_hash,
       CASE WHEN v.change_type = 'deleted' THEN NULL
            ELSE v.content_hash END           AS new_content_hash,
       CASE WHEN v.change_type = 'deleted' THEN v.file_path
            ELSE NULL END                     AS old_file_path,
       CASE WHEN v.change_type = 'deleted' THEN NULL
            ELSE v.file_path END              AS new_file_path,
       0                                      AS lines_added,
       0                                      AS lines_removed,
       c.commit_timestamp                     AS created_at
  FROM vcs_file_states v
  JOIN vcs_commits c ON c.id = v.commit_id;

-- source_snapshots read vcs_file_states.content_text/content_blob
-- directly; those columns are gone, so its historical half now resolves
-- content through content_blobs. The inner join to project_files is kept
-- deliberately: it already excluded rows whose file was hard-deleted, and
-- widening that here would change what callers see.
DROP VIEW IF EXISTS source_snapshots;
CREATE VIEW source_snapshots AS
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
        cb.content_text              AS content_text,
        cb.content_blob              AS content_blob,
        cb.content_type              AS content_type,
        vfs.file_size                AS file_size_bytes,
        vfs.line_count               AS line_count,
        c.commit_timestamp           AS observed_at,
        'git'                        AS source_authority
    FROM vcs_file_states vfs
    JOIN vcs_commits c      ON c.id = vfs.commit_id
    JOIN project_files pf   ON pf.id = vfs.file_id
    JOIN projects p         ON p.id = pf.project_id
    LEFT JOIN content_blobs cb ON cb.hash_sha256 = vfs.content_hash;

COMMIT;
