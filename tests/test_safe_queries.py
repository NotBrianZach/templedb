#!/usr/bin/env python3
"""
Test SafeQueries consolidated API

Validates that all safe query APIs enforce project_id filtering.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from safe_queries import (
    SafeQueries,
    SafeFileQueries,
    SafeDeploymentQueries,
    SafeAPIQueries,
    SafeMigrationQueries,
    SafeEnvironmentQueries,
    SafeBranchQueries,
    QueryValidationError
)
from conftest import test_project, query_one, execute


@pytest.fixture
def safe_queries():
    """Provide SafeQueries instance"""
    return SafeQueries()


@pytest.fixture
def test_project_with_data(test_project):
    """Create a test project with sample data"""
    project_id = test_project['id']

    # Get file type
    file_type = query_one("SELECT id FROM file_types WHERE type_name = 'typescript'")
    if not file_type:
        execute("INSERT INTO file_types (type_name, category) VALUES ('typescript', 'frontend')")
        file_type = query_one("SELECT id FROM file_types WHERE type_name = 'typescript'")

    # Add file
    execute("""
        INSERT INTO project_files (project_id, file_type_id, file_path, file_name, status)
        VALUES (?, ?, 'src/app.ts', 'app.ts', 'active')
    """, (project_id, file_type['id']))

    # Add deployment target
    execute("""
        INSERT INTO deployment_targets (project_id, target_name, target_type, provider)
        VALUES (?, 'production', 'database', 'supabase')
    """, (project_id,))

    # Add API endpoint
    execute("""
        INSERT INTO api_endpoints (project_id, endpoint_path, http_method, requires_auth)
        VALUES (?, '/api/users', 'GET', 1)
    """, (project_id,))

    # Add migration
    execute("""
        INSERT INTO database_migrations (project_id, migration_number, migration_name, status)
        VALUES (?, '001', 'init_schema', 'applied')
    """, (project_id,))

    # Add environment
    execute("""
        INSERT INTO nix_environments (project_id, env_name, nix_packages, is_active)
        VALUES (?, 'dev', '["nodejs"]', 1)
    """, (project_id,))

    # Add branch
    execute("""
        INSERT INTO vcs_branches (project_id, branch_name, is_default)
        VALUES (?, 'main', 1)
    """, (project_id,))

    return test_project


# ============================================================================
# SafeQueries Consolidated API Tests
# ============================================================================

@pytest.mark.unit
def test_safe_queries_has_all_subqueries(safe_queries):
    """Test that SafeQueries provides all sub-query APIs"""
    assert hasattr(safe_queries, 'files')
    assert hasattr(safe_queries, 'targets')
    assert hasattr(safe_queries, 'endpoints')
    assert hasattr(safe_queries, 'migrations')
    assert hasattr(safe_queries, 'environments')
    assert hasattr(safe_queries, 'branches')

    assert isinstance(safe_queries.files, SafeFileQueries)
    assert isinstance(safe_queries.targets, SafeDeploymentQueries)
    assert isinstance(safe_queries.endpoints, SafeAPIQueries)
    assert isinstance(safe_queries.migrations, SafeMigrationQueries)
    assert isinstance(safe_queries.environments, SafeEnvironmentQueries)
    assert isinstance(safe_queries.branches, SafeBranchQueries)


@pytest.mark.integration
def test_safe_files_query(safe_queries, test_project_with_data):
    """Test SafeFileQueries through consolidated API"""
    project_id = test_project_with_data['id']

    file = safe_queries.files.get_by_path('src/app.ts', project_id=project_id)

    assert file is not None
    assert file['file_path'] == 'src/app.ts'


@pytest.mark.integration
def test_safe_targets_query(safe_queries, test_project_with_data):
    """Test SafeDeploymentQueries through consolidated API"""
    project_id = test_project_with_data['id']

    target = safe_queries.targets.get_target('production', project_id=project_id)

    assert target is not None
    assert target['target_name'] == 'production'
    assert target['target_type'] == 'database'


@pytest.mark.integration
def test_safe_endpoints_query(safe_queries, test_project_with_data):
    """Test SafeAPIQueries through consolidated API"""
    project_id = test_project_with_data['id']

    endpoint = safe_queries.endpoints.get_endpoint('/api/users', 'GET', project_id=project_id)

    assert endpoint is not None
    assert endpoint['endpoint_path'] == '/api/users'
    assert endpoint['http_method'] == 'GET'


@pytest.mark.integration
def test_safe_migrations_query(safe_queries, test_project_with_data):
    """Test SafeMigrationQueries through consolidated API"""
    project_id = test_project_with_data['id']

    migration = safe_queries.migrations.get_migration('001', project_id=project_id)

    assert migration is not None
    assert migration['migration_number'] == '001'
    assert migration['migration_name'] == 'init_schema'


@pytest.mark.integration
def test_safe_environments_query(safe_queries, test_project_with_data):
    """Test SafeEnvironmentQueries through consolidated API"""
    project_id = test_project_with_data['id']

    env = safe_queries.environments.get_environment('dev', project_id=project_id)

    assert env is not None
    assert env['env_name'] == 'dev'


@pytest.mark.integration
def test_safe_branches_query(safe_queries, test_project_with_data):
    """Test SafeBranchQueries through consolidated API"""
    project_id = test_project_with_data['id']

    branch = safe_queries.branches.get_branch('main', project_id=project_id)

    assert branch is not None
    assert branch['branch_name'] == 'main'
    assert branch['is_default'] == 1


# ============================================================================
# Project Isolation Tests
# ============================================================================

@pytest.mark.integration
def test_targets_isolate_between_projects(test_project_with_data):
    """Test that deployment targets properly isolate between projects"""
    project1_id = test_project_with_data['id']

    # Create a second project with same target name
    execute("""
        INSERT INTO projects (slug, name, repo_url)
        VALUES ('test_project_2', 'Test Project 2', '/tmp/test2')
    """)
    project2 = query_one("SELECT id FROM projects WHERE slug = 'test_project_2'")
    project2_id = project2['id']

    # Add "production" target to second project
    execute("""
        INSERT INTO deployment_targets (project_id, target_name, target_type, provider)
        VALUES (?, 'production', 'edge_function', 'vercel')
    """, (project2_id,))

    # Query each project
    queries = SafeQueries()

    target1 = queries.targets.get_target('production', project_id=project1_id)
    target2 = queries.targets.get_target('production', project_id=project2_id)

    assert target1 is not None
    assert target2 is not None
    assert target1['id'] != target2['id']
    assert target1['target_type'] == 'database'
    assert target2['target_type'] == 'edge_function'

    # Cleanup
    execute("DELETE FROM deployment_targets WHERE project_id = ?", (project2_id,))
    execute("DELETE FROM projects WHERE id = ?", (project2_id,))


@pytest.mark.integration
def test_endpoints_isolate_between_projects(test_project_with_data):
    """Test that API endpoints properly isolate between projects"""
    project1_id = test_project_with_data['id']

    # Create a second project
    execute("""
        INSERT INTO projects (slug, name, repo_url)
        VALUES ('test_project_2', 'Test Project 2', '/tmp/test2')
    """)
    project2 = query_one("SELECT id FROM projects WHERE slug = 'test_project_2'")
    project2_id = project2['id']

    # Add same endpoint to second project
    execute("""
        INSERT INTO api_endpoints (project_id, endpoint_path, http_method, requires_auth)
        VALUES (?, '/api/users', 'GET', 0)
    """, (project2_id,))

    # Query each project
    queries = SafeQueries()

    endpoint1 = queries.endpoints.get_endpoint('/api/users', 'GET', project_id=project1_id)
    endpoint2 = queries.endpoints.get_endpoint('/api/users', 'GET', project_id=project2_id)

    assert endpoint1 is not None
    assert endpoint2 is not None
    assert endpoint1['id'] != endpoint2['id']
    assert endpoint1['requires_auth'] == 1
    assert endpoint2['requires_auth'] == 0

    # Cleanup
    execute("DELETE FROM api_endpoints WHERE project_id = ?", (project2_id,))
    execute("DELETE FROM projects WHERE id = ?", (project2_id,))


# ============================================================================
# Error Handling Tests
# ============================================================================

@pytest.mark.unit
def test_queries_require_project_context(safe_queries):
    """Test that all query methods require project_id or project_slug"""

    with pytest.raises(ValueError, match="Either project_id or project_slug must be provided"):
        safe_queries.files.get_by_path('README.md')

    with pytest.raises(ValueError, match="Either project_id or project_slug must be provided"):
        safe_queries.targets.get_target('production')

    with pytest.raises(ValueError, match="Either project_id or project_slug must be provided"):
        safe_queries.endpoints.get_endpoint('/api/users', 'GET')

    with pytest.raises(ValueError, match="Either project_id or project_slug must be provided"):
        safe_queries.migrations.get_migration('001')

    with pytest.raises(ValueError, match="Either project_id or project_slug must be provided"):
        safe_queries.environments.get_environment('dev')

    with pytest.raises(ValueError, match="Either project_id or project_slug must be provided"):
        safe_queries.branches.get_branch('main')


@pytest.mark.unit
def test_queries_reject_both_parameters(safe_queries):
    """Test that providing both project_id and project_slug is rejected"""

    with pytest.raises(ValueError, match="Provide either project_id OR project_slug, not both"):
        safe_queries.files.get_by_path('README.md', project_id=1, project_slug='test')


@pytest.mark.integration
def test_invalid_project_slug_raises_error(safe_queries):
    """Test that invalid project_slug raises appropriate error"""

    with pytest.raises(QueryValidationError, match="Project not found"):
        safe_queries.files.get_by_path('README.md', project_slug='nonexistent-project')


# ============================================================================
# List Methods Tests
# ============================================================================

@pytest.mark.integration
def test_list_targets(safe_queries, test_project_with_data):
    """Test listing deployment targets"""
    project_id = test_project_with_data['id']

    targets = safe_queries.targets.list_targets(project_id=project_id)

    assert len(targets) >= 1
    assert all(t['project_id'] == project_id for t in targets)


@pytest.mark.integration
def test_list_endpoints(safe_queries, test_project_with_data):
    """Test listing API endpoints"""
    project_id = test_project_with_data['id']

    endpoints = safe_queries.endpoints.list_endpoints(project_id=project_id)

    assert len(endpoints) >= 1
    assert all(e['project_id'] == project_id for e in endpoints)


@pytest.mark.integration
def test_list_migrations(safe_queries, test_project_with_data):
    """Test listing migrations"""
    project_id = test_project_with_data['id']

    migrations = safe_queries.migrations.list_migrations(project_id=project_id)

    assert len(migrations) >= 1
    assert all(m['project_id'] == project_id for m in migrations)


@pytest.mark.integration
def test_list_environments(safe_queries, test_project_with_data):
    """Test listing environments"""
    project_id = test_project_with_data['id']

    envs = safe_queries.environments.list_environments(project_id=project_id)

    assert len(envs) >= 1
    assert all(e['project_id'] == project_id for e in envs)


@pytest.mark.integration
def test_list_branches(safe_queries, test_project_with_data):
    """Test listing branches"""
    project_id = test_project_with_data['id']

    branches = safe_queries.branches.list_branches(project_id=project_id)

    assert len(branches) >= 1
    assert all(b['project_id'] == project_id for b in branches)


# ============================================================================
# Project Slug Support Tests
# ============================================================================

@pytest.mark.integration
def test_queries_support_project_slug(safe_queries, test_project_with_data):
    """Test that all queries support project_slug parameter"""
    project_slug = test_project_with_data['slug']

    # Should all work with project_slug instead of project_id
    file = safe_queries.files.get_by_path('src/app.ts', project_slug=project_slug)
    target = safe_queries.targets.get_target('production', project_slug=project_slug)
    endpoint = safe_queries.endpoints.get_endpoint('/api/users', 'GET', project_slug=project_slug)
    migration = safe_queries.migrations.get_migration('001', project_slug=project_slug)
    env = safe_queries.environments.get_environment('dev', project_slug=project_slug)
    branch = safe_queries.branches.get_branch('main', project_slug=project_slug)

    assert file is not None
    assert target is not None
    assert endpoint is not None
    assert migration is not None
    assert env is not None
    assert branch is not None
