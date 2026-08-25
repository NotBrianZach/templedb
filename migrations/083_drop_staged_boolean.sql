-- Drop the vcs_working_state.staged BOOLEAN compat mirror.
--
-- Migration 082 introduced staged_by_session_id for session-scoped
-- staging and kept `staged` as a boolean compat mirror maintained by
-- service code so existing readers wouldn't break. All readers and
-- writers have since migrated to staged_by_session_id semantics
-- (commits 4215BE16 and 55D1721E), so the mirror is now dead weight.
--
-- SQLite 3.35+ supports ALTER TABLE DROP COLUMN. The templedb project
-- targets SQLite 3.35+ (build already assumes this).

-- Drop and recreate the view that referenced ws.staged so DROP COLUMN
-- doesn't fail on view-column-reference validation.
DROP VIEW IF EXISTS vcs_current_files_view;

ALTER TABLE vcs_working_state DROP COLUMN staged;

CREATE VIEW vcs_current_files_view AS
SELECT
    ws.project_id,
    p.slug AS project_slug,
    b.branch_name,
    pf.file_path,
    ws.state,
    (ws.staged_by_session_id IS NOT NULL) AS staged,
    ws.staged_by_session_id,
    ws.content_hash,
    ws.last_modified
FROM vcs_working_state ws
JOIN vcs_branches b ON ws.branch_id = b.id
JOIN project_files pf ON ws.file_id = pf.id
JOIN projects p ON ws.project_id = p.id;
