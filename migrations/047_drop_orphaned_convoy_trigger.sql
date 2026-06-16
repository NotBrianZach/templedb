-- Drop orphaned convoy references that block project deletion
--
-- ISSUE: Migration 040 dropped the work_convoys and convoy_work_items tables
-- but left behind database objects that still referenced them, causing:
--   ERROR: "no such table: main.work_convoys" when executing:
--     templedb project rm <slug>
--
-- ROOT CAUSE: The following objects were orphaned:
--   1. Trigger: update_convoy_on_completion (on work_items table)
--   2. View: convoy_progress_view
--   3. Foreign Key: work_item_notifications.convoy_id -> work_convoys(id)
--
-- FIX: Remove all references to deleted work_convoys table
--
-- NOTE: This migration is only needed for databases created before the
-- schema cleanup. Migration 020 (archived) has been updated to not create
-- these objects in the first place for new databases.

-- 1. Drop orphaned trigger
DROP TRIGGER IF EXISTS update_convoy_on_completion;

-- 2. Drop orphaned view
DROP VIEW IF EXISTS convoy_progress_view;

-- 3. Recreate work_item_notifications without the convoy foreign key
DROP TABLE IF EXISTS work_item_notifications_temp;
CREATE TABLE work_item_notifications_temp (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient TEXT NOT NULL,
    message_type TEXT NOT NULL,
    work_item_id TEXT,
    convoy_id INTEGER,  -- Column retained for backward compatibility, FK removed
    message_content TEXT NOT NULL,
    priority TEXT DEFAULT 'normal',
    status TEXT NOT NULL DEFAULT 'unread',
    delivered_at TEXT DEFAULT (datetime('now')),
    read_at TEXT,
    acknowledged_at TEXT,

    FOREIGN KEY (work_item_id) REFERENCES work_items(id) ON DELETE CASCADE,
    -- Removed: FOREIGN KEY (convoy_id) REFERENCES work_convoys(id) ON DELETE CASCADE

    CHECK (message_type IN ('work_assignment', 'notification', 'coordination_request', 'status_update')),
    CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    CHECK (status IN ('unread', 'read', 'acknowledged', 'completed'))
);

-- Copy existing data
INSERT INTO work_item_notifications_temp
SELECT * FROM work_item_notifications;

-- Replace old table
DROP TABLE work_item_notifications;
ALTER TABLE work_item_notifications_temp RENAME TO work_item_notifications;

-- Verification queries:
-- SELECT name, type FROM sqlite_master WHERE sql LIKE '%work_convoys%';
-- Expected: No critical objects (only possibly column comments)
