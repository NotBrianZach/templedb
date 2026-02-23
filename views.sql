-- Database views for projdb
-- These views join foreign key relationships to show names instead of just IDs

-- View for nix_configs with project details
CREATE VIEW IF NOT EXISTS nix_configs_view AS
SELECT
    nc.id,
    nc.project_id,
    p.slug AS project_slug,
    p.name AS project_name,
    p.repo_url,
    p.git_branch,
    p.git_ref,
    nc.profile,
    nc.nix_text,
    nc.flake_text,
    nc.flake_lock,
    nc.build_command,
    nc.shell_command,
    nc.created_at,
    nc.updated_at
FROM nix_configs nc
JOIN projects p ON nc.project_id = p.id;

-- View for secret_blobs with project details
CREATE VIEW IF NOT EXISTS secret_blobs_view AS
SELECT
    sb.id,
    sb.project_id,
    p.slug AS project_slug,
    p.name AS project_name,
    p.repo_url,
    sb.profile,
    sb.secret_name,
    sb.content_type,
    sb.created_at,
    sb.updated_at
FROM secret_blobs sb
JOIN projects p ON sb.project_id = p.id;

-- View for compound_values with project details
CREATE VIEW IF NOT EXISTS compound_values_view AS
SELECT
    cv.id,
    cv.project_id,
    p.slug AS project_slug,
    p.name AS project_name,
    p.repo_url,
    cv.profile,
    cv.key,
    cv.value_template,
    cv.description,
    cv.created_at,
    cv.updated_at
FROM compound_values cv
JOIN projects p ON cv.project_id = p.id;

-- View for project_env_vars with project and env_var details
CREATE VIEW IF NOT EXISTS project_env_vars_view AS
SELECT
    pev.project_id,
    p.slug AS project_slug,
    p.name AS project_name,
    pev.env_var_id,
    ev.key AS env_key,
    ev.value AS env_value,
    ev.description AS env_description,
    ev.environment,
    pev.profile,
    pev.created_at
FROM project_env_vars pev
JOIN projects p ON pev.project_id = p.id
JOIN env_vars ev ON pev.env_var_id = ev.id;

-- View for project_secret_blobs with project and secret_blob details
CREATE VIEW IF NOT EXISTS project_secret_blobs_view AS
SELECT
    psb.project_id,
    p.slug AS project_slug,
    p.name AS project_name,
    psb.secret_blob_id,
    sb.secret_name,
    sb.content_type,
    psb.profile,
    psb.created_at
FROM project_secret_blobs psb
JOIN projects p ON psb.project_id = p.id
JOIN secret_blobs sb ON psb.secret_blob_id = sb.id;

-- View for audit_log with richer project information
CREATE VIEW IF NOT EXISTS audit_log_view AS
SELECT
    al.id,
    al.ts,
    al.actor,
    al.action,
    al.project_slug,
    p.name AS project_name,
    p.repo_url,
    al.profile,
    al.details
FROM audit_log al
LEFT JOIN projects p ON al.project_slug = p.slug;

-- ============================================================================
-- FILE TRACKING VIEWS
-- ============================================================================

-- Complete file information with type
CREATE VIEW IF NOT EXISTS files_with_types_view AS
SELECT
    pf.id,
    pf.project_id,
    p.slug AS project_slug,
    pf.file_path,
    pf.file_name,
    pf.component_name,
    ft.type_name,
    ft.category AS file_category,
    pf.description,
    pf.purpose,
    pf.owner,
    pf.status,
    pf.last_modified,
    pf.lines_of_code,
    pf.complexity_score,
    pf.created_at,
    pf.updated_at
FROM project_files pf
JOIN file_types ft ON pf.file_type_id = ft.id
JOIN projects p ON pf.project_id = p.id;

-- File dependency graph view
CREATE VIEW IF NOT EXISTS file_dependency_graph_view AS
SELECT
    fd.id,
    parent_file.file_path AS parent_file_path,
    parent_file.component_name AS parent_component,
    parent_ft.type_name AS parent_type,
    dep_file.file_path AS dependency_file_path,
    dep_file.component_name AS dependency_component,
    dep_ft.type_name AS dependency_type,
    fd.dependency_type,
    fd.is_hard_dependency,
    fd.usage_context,
    p.slug AS project_slug
FROM file_dependencies fd
JOIN project_files parent_file ON fd.parent_file_id = parent_file.id
JOIN project_files dep_file ON fd.dependency_file_id = dep_file.id
JOIN file_types parent_ft ON parent_file.file_type_id = parent_ft.id
JOIN file_types dep_ft ON dep_file.file_type_id = dep_ft.id
JOIN projects p ON parent_file.project_id = p.id;

-- Deployment readiness view
CREATE VIEW IF NOT EXISTS deployment_readiness_view AS
SELECT
    pf.id AS file_id,
    pf.file_path,
    pf.component_name,
    dt.target_name,
    dt.target_type,
    fd_deploy.deploy_command,
    fd_deploy.last_deployed_at,
    fd_deploy.last_deployment_status,
    CASE
        WHEN fd_deploy.last_deployed_at IS NULL THEN 'never_deployed'
        WHEN datetime(fd_deploy.last_deployed_at) < datetime(pf.last_modified) THEN 'stale'
        ELSE 'up_to_date'
    END AS deployment_freshness,
    p.slug AS project_slug
FROM project_files pf
JOIN projects p ON pf.project_id = p.id
LEFT JOIN file_deployments fd_deploy ON pf.id = fd_deploy.file_id
LEFT JOIN deployment_targets dt ON fd_deploy.deployment_target_id = dt.id;

-- SQL objects with file info
CREATE VIEW IF NOT EXISTS sql_objects_view AS
SELECT
    so.id,
    so.object_type,
    so.schema_name,
    so.object_name,
    so.function_language,
    so.has_rls_enabled,
    pf.file_path,
    pf.component_name,
    pf.description,
    pf.status,
    p.slug AS project_slug
FROM sql_objects so
JOIN project_files pf ON so.file_id = pf.id
JOIN projects p ON pf.project_id = p.id;

-- API endpoints with implementation files
CREATE VIEW IF NOT EXISTS api_endpoints_view AS
SELECT
    ae.id,
    ae.endpoint_path,
    ae.http_method,
    ae.description,
    ae.requires_auth,
    pf.file_path AS implemented_by,
    pf.component_name,
    p.slug AS project_slug
FROM api_endpoints ae
JOIN projects p ON ae.project_id = p.id
LEFT JOIN project_files pf ON ae.implemented_by_file_id = pf.id;
