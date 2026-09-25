-- 110_fix_fts_content_index.sql
--
-- Repair `templedb search content`, which had been silently returning
-- almost nothing.
--
-- The FTS index was maintained by two triggers on content_blobs, for
-- UPDATE and DELETE. There was no INSERT trigger — and content_blobs is
-- content-addressed, so blobs are INSERTed and never UPDATEd. The update
-- trigger therefore almost never fired and the index simply stopped
-- growing: 3,911 stale rows against 1,845 current files, with
-- `search content "def"` matching 39 files across a 197k-line Python
-- corpus and `apply_standard_pragmas` (present in four files) matching
-- none at all.
--
-- content_blobs was also the wrong table to key on. It holds every
-- historical revision (11,722 text blobs for 1,845 current files), and
-- its file_path lookup resolved through `is_current = 1`, so historical
-- blobs indexed as 'unknown'. Currency is a property of file_contents,
-- so that is where maintenance belongs.
--
-- rowid is project_files.id, which gives each current file exactly one
-- row and makes replacement a plain delete-by-rowid.

DROP TRIGGER IF EXISTS file_contents_fts_update;
DROP TRIGGER IF EXISTS file_contents_fts_delete;

-- Rebuild from the current state of the world.
DELETE FROM file_contents_fts;

INSERT INTO file_contents_fts (rowid, file_path, content_text)
SELECT pf.id, pf.file_path, cb.content_text
  FROM project_files pf
  JOIN file_contents fc ON fc.file_id = pf.id AND fc.is_current = 1
  JOIN content_blobs cb ON cb.hash_sha256 = fc.content_hash
 WHERE pf.status = 'active'
   AND cb.content_text IS NOT NULL;

-- Keep it current. FTS5 has no UPSERT, so each path deletes by rowid
-- first; deleting a missing rowid is a no-op.

CREATE TRIGGER file_contents_fts_insert
AFTER INSERT ON file_contents
WHEN NEW.is_current = 1
BEGIN
    DELETE FROM file_contents_fts WHERE rowid = NEW.file_id;
    INSERT INTO file_contents_fts (rowid, file_path, content_text)
    SELECT pf.id, pf.file_path, cb.content_text
      FROM project_files pf
      JOIN content_blobs cb ON cb.hash_sha256 = NEW.content_hash
     WHERE pf.id = NEW.file_id
       AND pf.status = 'active'
       AND cb.content_text IS NOT NULL;
END;

CREATE TRIGGER file_contents_fts_update
AFTER UPDATE ON file_contents
WHEN NEW.is_current = 1
BEGIN
    DELETE FROM file_contents_fts WHERE rowid = NEW.file_id;
    INSERT INTO file_contents_fts (rowid, file_path, content_text)
    SELECT pf.id, pf.file_path, cb.content_text
      FROM project_files pf
      JOIN content_blobs cb ON cb.hash_sha256 = NEW.content_hash
     WHERE pf.id = NEW.file_id
       AND pf.status = 'active'
       AND cb.content_text IS NOT NULL;
END;

CREATE TRIGGER file_contents_fts_delete
AFTER DELETE ON file_contents
BEGIN
    DELETE FROM file_contents_fts WHERE rowid = OLD.file_id;
END;

-- A file removed from the project must leave the index, or deleted
-- paths keep answering searches.
CREATE TRIGGER file_contents_fts_file_delete
AFTER DELETE ON project_files
BEGIN
    DELETE FROM file_contents_fts WHERE rowid = OLD.id;
END;
