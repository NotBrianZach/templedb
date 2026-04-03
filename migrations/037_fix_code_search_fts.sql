-- Migration 037: Fix Code Search FTS5 Configuration
-- Date: 2026-03-19
-- Purpose: Fix FTS5 virtual table to properly index search content
--
-- NOTE: This migration is only needed for databases created before schema cleanup.
-- Migration 034 has been updated to create code_search_fts correctly from the start.

-- Drop old FTS5 table
DROP TABLE IF EXISTS code_search_fts;

-- Create standalone FTS5 table (not external content)
-- This is simpler and more reliable
CREATE VIRTUAL TABLE code_search_fts USING fts5(
    symbol_id UNINDEXED,
    search_text
);
