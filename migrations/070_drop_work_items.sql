-- Remove work item feature (never used)

-- Drop views
DROP VIEW IF EXISTS work_items_with_prompts_view;
DROP VIEW IF EXISTS work_item_stats_view;
DROP VIEW IF EXISTS active_work_items_view;
DROP VIEW IF EXISTS assignee_workload_view;

-- Drop triggers
DROP TRIGGER IF EXISTS record_work_item_transition;
DROP TRIGGER IF EXISTS update_work_item_timestamp;
DROP TRIGGER IF EXISTS notify_on_assignment;

-- Drop orphaned index on prompt_usage_log
DROP INDEX IF EXISTS idx_prompt_usage_work_item;

-- Drop tables
DROP TABLE IF EXISTS work_item_notifications;
DROP TABLE IF EXISTS work_item_transitions;
DROP TABLE IF EXISTS work_items;
