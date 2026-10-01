-- Migration 117: move content that exists only in vcs_file_states into content_blobs.
--
-- Prerequisite for the normalization in 118. vcs_file_states carries its
-- own inline content_text/content_blob alongside content_hash, and for a
-- handful of rows that hash is absent from content_blobs — the content
-- exists ONLY in the inline column. Dropping those columns without this
-- step would destroy those file versions.
--
-- Verified 2026-10-01 before writing: 14 such rows existed; the 6 with
-- recoverable content_text all hash correctly (sha256 of the UTF-8 bytes
-- equals the stored content_hash), so promoting them is lossless. The
-- other 8 have content_text AND content_blob NULL with no matching blob
-- — that content is already gone, and has been; source_snapshots already
-- returns NULL for them today. They are deliberately left alone: 118
-- keeps their rows as tombstones, since the hash and change_type are
-- still real history.
--
-- Written as a set-based statement rather than against those 6 ids so it
-- stays correct if more rows land between writing and applying.

INSERT OR IGNORE INTO content_blobs
    (hash_sha256, content_text, content_type, encoding,
     file_size_bytes, reference_count)
SELECT v.content_hash,
       v.content_text,
       'text',
       'utf-8',
       LENGTH(CAST(v.content_text AS BLOB)),   -- bytes, not characters
       0
  FROM vcs_file_states v
 WHERE v.content_text IS NOT NULL
   AND v.content_hash IS NOT NULL
   AND v.content_hash NOT IN (SELECT hash_sha256 FROM content_blobs)
 GROUP BY v.content_hash;

INSERT OR IGNORE INTO content_blobs
    (hash_sha256, content_blob, content_type, encoding,
     file_size_bytes, reference_count)
SELECT v.content_hash,
       v.content_blob,
       'binary',
       NULL,
       LENGTH(v.content_blob),
       0
  FROM vcs_file_states v
 WHERE v.content_blob IS NOT NULL
   AND v.content_hash IS NOT NULL
   AND v.content_hash NOT IN (SELECT hash_sha256 FROM content_blobs)
 GROUP BY v.content_hash;
