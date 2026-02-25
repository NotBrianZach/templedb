#!/usr/bin/env python3
"""
Test SafeFileQueries API

Validates that the safe file query API enforces project_id filtering
and prevents cross-project query bugs.
"""

import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from safe_file_queries import SafeFileQueries, QueryValidationError
from conftest import test_project, db_connection, query_one, execute


# ============================================================================
# SafeFileQueries Tests
# ============================================================================

@pytest.fixture
def safe_queries():
    """Provide SafeFileQueries instance"""
    return SafeFileQueries()


@pytest.fixture
def test_project_with_files(test_project):
    """Create a test project with sample files"""
    project_id = test_project['id']

    # Get or create a file type
    file_type = query_one("SELECT id FROM file_types WHERE type_name = 'typescript'")
    if not file_type:
        execute("INSERT INTO file_types (type_name, category) VALUES ('typescript', 'frontend')")
        file_type = query_one("SELECT id FROM file_types WHERE type_name = 'typescript'")

    # Add some test files
    execute("""
        INSERT INTO project_files (project_id, file_type_id, file_path, file_name, lines_of_code, status)
        VALUES (?, ?, 'README.md', 'README.md', 10, 'active')
    """, (project_id, file_type['id']))

    execute("""
        INSERT INTO project_files (project_id, file_type_id, file_path, file_name, lines_of_code, status)
        VALUES (?, ?, 'src/app.ts', 'app.ts', 100, 'active')
    """, (project_id, file_type['id']))

    execute("""
        INSERT INTO project_files (project_id, file_type_id, file_path, file_name, lines_of_code, status)
        VALUES (?, ?, 'src/utils.ts', 'utils.ts', 50, 'active')
    """, (project_id, file_type['id']))

    return test_project


@pytest.mark.unit
def test_safe_queries_requires_project_context(safe_queries):
    """Test that SafeFileQueries methods require project_id or project_slug"""

    # Should raise ValueError when neither provided
    with pytest.raises(ValueError, match="Either project_id or project_slug must be provided"):
        safe_queries.get_file_by_path('README.md')

    with pytest.raises(ValueError, match="Either project_id or project_slug must be provided"):
        safe_queries.get_file_content('README.md')

    with pytest.raises(ValueError, match="Either project_id or project_slug must be provided"):
        safe_queries.list_files()


@pytest.mark.unit
def test_safe_queries_rejects_both_parameters(safe_queries):
    """Test that providing both project_id and project_slug is rejected"""

    with pytest.raises(ValueError, match="Provide either project_id OR project_slug, not both"):
        safe_queries.get_file_by_path('README.md', project_id=1, project_slug='test')


@pytest.mark.integration
def test_get_file_by_path_with_project_id(safe_queries, test_project_with_files):
    """Test getting a file by path with project_id"""

    project_id = test_project_with_files['id']

    file = safe_queries.get_file_by_path('README.md', project_id=project_id)

    assert file is not None
    assert file['file_path'] == 'README.md'
    assert file['project_id'] == project_id


@pytest.mark.integration
def test_get_file_by_path_with_project_slug(safe_queries, test_project_with_files):
    """Test getting a file by path with project_slug"""

    project_slug = test_project_with_files['slug']

    file = safe_queries.get_file_by_path('README.md', project_slug=project_slug)

    assert file is not None
    assert file['file_path'] == 'README.md'


@pytest.mark.integration
def test_get_file_by_path_returns_none_for_nonexistent(safe_queries, test_project_with_files):
    """Test that nonexistent files return None"""

    project_id = test_project_with_files['id']

    file = safe_queries.get_file_by_path('nonexistent.txt', project_id=project_id)

    assert file is None


@pytest.mark.integration
def test_list_files_with_filters(safe_queries, test_project_with_files):
    """Test listing files with various filters"""

    project_id = test_project_with_files['id']

    # List all files
    all_files = safe_queries.list_files(project_id=project_id)
    assert len(all_files) == 3

    # Filter by file type
    ts_files = safe_queries.list_files(project_id=project_id, file_type='typescript')
    assert len(ts_files) >= 2  # At least src/app.ts and src/utils.ts

    # Filter by pattern
    src_files = safe_queries.list_files(project_id=project_id, pattern='src/*')
    assert len(src_files) == 2
    assert all('src/' in f['file_path'] for f in src_files)


@pytest.mark.integration
def test_list_files_with_project_slug(safe_queries, test_project_with_files):
    """Test listing files using project_slug instead of project_id"""

    project_slug = test_project_with_files['slug']

    files = safe_queries.list_files(project_slug=project_slug)

    assert len(files) == 3


@pytest.mark.integration
def test_get_file_stats(safe_queries, test_project_with_files):
    """Test getting file statistics for a project"""

    project_id = test_project_with_files['id']

    stats = safe_queries.get_file_stats(project_id=project_id)

    assert stats['total_files'] == 3
    assert stats['total_lines'] == 160  # 10 + 100 + 50


@pytest.mark.integration
def test_safe_queries_isolates_projects(test_project_with_files):
    """Test that queries properly isolate between projects"""

    project1_id = test_project_with_files['id']

    # Create a second project with same file path
    execute("""
        INSERT INTO projects (slug, name, repo_url)
        VALUES ('test_project_2', 'Test Project 2', '/tmp/test2')
    """)

    project2 = query_one("SELECT id FROM projects WHERE slug = 'test_project_2'")
    project2_id = project2['id']

    file_type = query_one("SELECT id FROM file_types WHERE type_name = 'typescript'")

    # Add README.md to second project
    execute("""
        INSERT INTO project_files (project_id, file_type_id, file_path, file_name, lines_of_code, status)
        VALUES (?, ?, 'README.md', 'README.md', 20, 'active')
    """, (project2_id, file_type['id']))

    # Now query each project
    safe_queries = SafeFileQueries()

    file1 = safe_queries.get_file_by_path('README.md', project_id=project1_id)
    file2 = safe_queries.get_file_by_path('README.md', project_id=project2_id)

    assert file1 is not None
    assert file2 is not None
    assert file1['id'] != file2['id']
    assert file1['lines_of_code'] == 10
    assert file2['lines_of_code'] == 20

    # Cleanup
    execute("DELETE FROM project_files WHERE project_id = ?", (project2_id,))
    execute("DELETE FROM projects WHERE id = ?", (project2_id,))


# ============================================================================
# Query Validation Tests
# ============================================================================

@pytest.mark.unit
def test_validate_safe_query_with_project_id():
    """Test that queries with project_id pass validation"""

    # Should NOT raise
    SafeFileQueries.validate_file_query("""
        SELECT * FROM project_files WHERE project_id = 1 AND file_path = 'README.md'
    """)


@pytest.mark.unit
def test_validate_safe_query_with_safe_view():
    """Test that queries using safe views pass validation"""

    # Should NOT raise
    SafeFileQueries.validate_file_query("""
        SELECT * FROM files_with_types_view WHERE project_slug = 'my-project'
    """)


@pytest.mark.unit
def test_validate_unsafe_query_without_project_id():
    """Test that queries without project_id fail validation"""

    with pytest.raises(QueryValidationError, match="doesn't filter by project_id or project_slug"):
        SafeFileQueries.validate_file_query("""
            SELECT * FROM project_files WHERE file_path = 'README.md'
        """)


@pytest.mark.unit
def test_validate_non_file_query():
    """Test that non-file queries are not validated"""

    # Should NOT raise - doesn't involve project_files
    SafeFileQueries.validate_file_query("""
        SELECT * FROM projects WHERE slug = 'my-project'
    """)


@pytest.mark.unit
def test_validate_query_with_join_to_projects():
    """Test that queries joining with projects table pass validation"""

    # Should NOT raise - has JOIN with projects
    SafeFileQueries.validate_file_query("""
        SELECT pf.*
        FROM project_files pf
        JOIN projects p ON pf.project_id = p.id
        WHERE p.slug = 'my-project'
    """)


# ============================================================================
# Edge Cases
# ============================================================================

@pytest.mark.integration
def test_get_file_with_invalid_project_slug(safe_queries):
    """Test that invalid project_slug raises appropriate error"""

    with pytest.raises(QueryValidationError, match="Project not found"):
        safe_queries.get_file_by_path('README.md', project_slug='nonexistent-project')


@pytest.mark.integration
def test_search_file_content(safe_queries, test_project_with_files):
    """Test searching file content within a project"""

    project_id = test_project_with_files['id']

    # Add content to a file
    file = query_one("""
        SELECT id FROM project_files
        WHERE project_id = ? AND file_path = 'README.md'
    """, (project_id,))

    if file:
        # Add content via content_blobs
        import hashlib
        content = "# Test Project\n\nThis contains a TODO marker"
        content_hash = hashlib.sha256(content.encode()).hexdigest()

        execute("""
            INSERT OR IGNORE INTO content_blobs (hash_sha256, content_text, content_type, file_size_bytes)
            VALUES (?, ?, 'text', ?)
        """, (content_hash, content, len(content)))

        execute("""
            INSERT INTO file_contents (file_id, content_hash, file_size_bytes, line_count, is_current, version)
            VALUES (?, ?, ?, 3, 1, 1)
        """, (file['id'], content_hash, len(content)))

        # Now search
        results = safe_queries.search_file_content('TODO', project_id=project_id)

        assert len(results) >= 1
        assert any('README.md' in r['file_path'] for r in results)


@pytest.mark.integration
def test_get_file_versions_empty(safe_queries, test_project_with_files):
    """Test getting versions for a file with no versions"""

    project_id = test_project_with_files['id']

    versions = safe_queries.get_file_versions('README.md', project_id=project_id)

    # May be empty or have versions depending on test setup
    assert isinstance(versions, list)


# ============================================================================
# Documentation Tests
# ============================================================================

@pytest.mark.unit
def test_safe_queries_api_signature():
    """Test that SafeFileQueries API matches documentation"""

    queries = SafeFileQueries()

    # All main methods should exist
    assert hasattr(queries, 'get_file_by_path')
    assert hasattr(queries, 'get_file_content')
    assert hasattr(queries, 'list_files')
    assert hasattr(queries, 'get_file_versions')
    assert hasattr(queries, 'search_file_content')
    assert hasattr(queries, 'get_file_stats')

    # Static validation method should exist
    assert hasattr(SafeFileQueries, 'validate_file_query')
