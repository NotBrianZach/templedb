-- 111_fts_track_project_files_changes.sql
--
-- Close two gaps left by migration 110.
--
-- 110 put FTS maintenance on file_contents, which is where *content*
-- currency lives. But two things that change what a search should
-- return never touch file_contents at all:
--
--   1. Rename. `UPDATE project_files SET file_path = ...` left the old
--      path in the index, so results pointed at a file that no longer
--      exists under that name.
--   2. Soft delete. `UPDATE project_files SET status = 'deleted'` left
--      the row indexed, so a deleted file kept answering searches.
--      (Hard DELETE was already handled by 110's file_delete trigger;
--      soft delete is the common path — `templedb file rm` stages, and
--      some flows only flip status.)
--
-- Both verified against a copy of the live DB before writing this.
--
-- The trigger re-derives the row from scratch on any change to
-- file_path or status. The status = 'active' filter in the SELECT does
-- double duty: it removes soft-deleted files and re-adds them if the
-- status is ever flipped back.

CREATE TRIGGER file_contents_fts_file_update
AFTER UPDATE OF file_path, status ON project_files
BEGIN
    DELETE FROM file_contents_fts WHERE rowid = NEW.id;
    INSERT INTO file_contents_fts (rowid, file_path, content_text)
    SELECT pf.id, pf.file_path, cb.content_text
      FROM project_files pf
      JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
      JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
     WHERE pf.id = NEW.id
       AND pf.status = 'active'
       AND cb.content_text IS NOT NULL;
END;
