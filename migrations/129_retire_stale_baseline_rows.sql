-- 129_retire_stale_baseline_rows.sql
--
-- Three unmaintained_columns_baseline rows stopped being true and
-- nothing noticed, which is the failure the new
-- baseline_rows_still_describe_reality invariant exists to catch. It
-- found them on its first run.
--
-- The baseline is a ratchet: a row in it tells
-- no_new_unmaintained_columns to stop reporting that column. That is
-- correct exactly as long as the row stays accurate. When a column
-- starts being written and its row survives, the ratchet goes on
-- suppressing it -- so the one mechanism meant to make dead columns
-- visible is quietly hiding a live one instead, and the baseline
-- becomes evidence for a claim that is no longer true. On 2026-10-06
-- I read the edit_intents.base_revision row and asserted in a written
-- report that the column was dead on all 978 rows; it was dead on 888
-- and alive on 93, because the write path had been fixed the previous
-- day. Migration 127 retired that row. These are the rest.
--
--   relations.attributes_json       all_null -> 143 rows have values
--   sync_relations.attributes_json  constant -> 2 distinct values
--   vcs_commits.git_commit_hash     all_null -> 261 rows have values
--
-- The last one is the most pointed: migration 126 populated
-- git_commit_hash itself, as the whole purpose of separating git SHAs
-- from native commit ids. A migration falsified a baseline row three
-- migrations ago and the ratchet kept suppressing the column it had
-- just brought to life.
--
-- relations.attributes_json is worth a second look rather than just a
-- deletion. The column's own DDL comment sets the policy -- "if a
-- relation grows more than 2-3 attributes or a lifecycle, promote it
-- to a span with its own table" -- and for a long time it was all-NULL,
-- which read as the policy working. 143 populated rows mean something
-- is now using it. That is not necessarily wrong, but it is a
-- deviation from a written rule, and it should be visible rather than
-- suppressed. Retiring the row is what makes it visible again.
--
-- Deleting rather than updating the shape. A baseline row means "this
-- column is accepted as unmaintained"; a column being written is not
-- a different shape of unmaintained, it is maintained, and it should
-- go back to being governed by the ordinary check.

DELETE FROM unmaintained_columns_baseline
 WHERE (table_name = 'relations'      AND column_name = 'attributes_json')
    OR (table_name = 'sync_relations' AND column_name = 'attributes_json')
    OR (table_name = 'vcs_commits'    AND column_name = 'git_commit_hash');
