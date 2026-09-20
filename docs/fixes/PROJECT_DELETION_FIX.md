# Project Deletion Bug Fix

## Issue
The `templedb project rm` command was failing with:
```
Error: no such table: main.work_convoys
```

## Root Cause
Migration `040_safe_cleanup_verified_unused.sql` dropped the `work_convoys` and `convoy_work_items` tables, but left behind several database objects that still referenced them:

1. **Trigger**: `update_convoy_on_completion` - Updated work_convoys when work_items completed
2. **View**: `convoy_progress_view` - Joined work_convoys with work items
3. **Foreign Key**: `work_item_notifications.convoy_id` referenced `work_convoys(id) ON DELETE CASCADE`

When attempting to delete a project, the deletion would cascade to work_items, which would trigger the `update_convoy_on_completion` trigger, which would attempt to UPDATE the non-existent `work_convoys` table, causing the error.

## Solution
Created migration `047_drop_orphaned_convoy_trigger.sql` that:

1. Drops the orphaned trigger `update_convoy_on_completion`
2. Drops the orphaned view `convoy_progress_view`
3. Recreates `work_item_notifications` table without the foreign key to work_convoys
   - Retains the `convoy_id` column for backward compatibility
   - Removes the `FOREIGN KEY (convoy_id) REFERENCES work_convoys(id)` constraint

## Testing
Verified that:
- ✅ Projects can be deleted with `templedb project rm <slug> --force`
- ✅ No error about missing work_convoys table
- ✅ Database integrity check passes
- ✅ All data is properly cleaned up on deletion

## Files Changed
- `/home/zach/templeDB/migrations/047_drop_orphaned_convoy_trigger.sql` (new)

## Lessons Learned
When dropping tables, always check for:
1. Triggers that reference the table
2. Views that join/select from the table
3. Foreign key constraints pointing to the table
4. Test the deletion thoroughly before committing migrations
