-- Migration 016: Add Full-Text Search (FTS5)
-- ==================================================
-- Adds FTS5 virtual table for fast content search
-- Includes triggers for automatic index maintenance
-- ==================================================

-- Create FTS5 virtual table for file contents
-- Store content directly in FTS5 (not using external content)
CREATE VIRTUAL TABLE IF NOT EXISTS file_contents_fts USING fts5(
    file_path UNINDEXED,          -- Don't index file path
    content_text,                  -- Index the actual content
    tokenize='porter unicode61 remove_diacritics 1'
);

-- Populate initial data from existing file contents
INSERT INTO file_contents_fts(file_path, content_text)
SELECT
    pf.file_path,
    cb.content_text
FROM content_blobs cb
JOIN file_contents fc ON cb.hash_sha256 = fc.content_hash
JOIN project_files pf ON fc.file_id = pf.id
WHERE cb.content_type = 'text'
  AND cb.content_text IS NOT NULL
  AND fc.is_current = 1;

-- Note: Triggers for auto-maintenance will be added in future if needed
-- For now, FTS5 table is populated once and can be rebuilt with:
-- DELETE FROM file_contents_fts; [run INSERT statement above again]

-- Create view for easy FTS5 searching with project context
CREATE VIEW IF NOT EXISTS file_search_view AS
SELECT
    p.slug AS project_slug,
    p.name AS project_name,
    pf.file_path,
    pf.file_name,
    ft.type_name AS file_type,
    cb.content_text,
    cb.file_size_bytes,
    fc.line_count,
    fc.updated_at
FROM file_contents fc
JOIN project_files pf ON fc.file_id = pf.id
JOIN projects p ON pf.project_id = p.id
JOIN file_types ft ON pf.file_type_id = ft.id
JOIN content_blobs cb ON fc.content_hash = cb.hash_sha256
WHERE fc.is_current = 1 AND cb.content_type = 'text';

-- Migration complete
-- Usage:
--   Basic search: SELECT * FROM file_contents_fts WHERE content_text MATCH 'search term';
--   With context: SELECT fsv.* FROM file_contents_fts fts
--                 JOIN file_search_view fsv ON fts.file_path = fsv.file_path
--                 WHERE fts.content_text MATCH 'search term';
--   Ranked results: Use ORDER BY rank for relevance ranking
--   Snippets: Use snippet(file_contents_fts, 1, '<b>', '</b>', '...', 32) for context
