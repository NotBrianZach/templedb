-- Migration: Remove project_id from secret_blobs (use join table instead)
-- This completes the refactoring to pure many-to-many relationships

-- SQLite doesn't support DROP COLUMN, so we need to recreate the table

-- Step 1: Create new table without project_id
CREATE TABLE secret_blobs_new (
  id INTEGER PRIMARY KEY,
  profile TEXT NOT NULL DEFAULT 'default',
  secret_name TEXT NOT NULL,
  secret_blob BLOB NOT NULL,
  content_type TEXT NOT NULL DEFAULT 'application/text',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Step 2: Copy data from old table
INSERT INTO secret_blobs_new (id, profile, secret_name, secret_blob, content_type, created_at, updated_at)
SELECT id, profile, secret_name, secret_blob, content_type, created_at, updated_at
FROM secret_blobs;

-- Step 3: Drop old table
DROP TABLE secret_blobs;

-- Step 4: Rename new table
ALTER TABLE secret_blobs_new RENAME TO secret_blobs;

-- Step 5: Recreate indices if any were lost
-- (none in this case, all indices are on join table)
