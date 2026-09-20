#!/usr/bin/env python3
"""
Unit tests for ProjectService

These tests demonstrate how the service layer can be tested independently
of the CLI layer.
"""
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

# Note: These tests require pytest to run
# Run with: pytest tests/unit/services/test_project_service.py


def test_get_by_slug_returns_project():
    """Test that get_by_slug returns a project when it exists"""
    from services.project_service import ProjectService

    # Create mock context
    mock_context = Mock()
    mock_repo = Mock()
    mock_repo.get_by_slug.return_value = {
        'id': 1,
        'slug': 'test-project',
        'name': 'Test Project'
    }
    mock_context.project_repo = mock_repo
    mock_context.file_repo = Mock()

    # Create service
    service = ProjectService(mock_context)

    # Test
    project = service.get_by_slug('test-project')

    # Verify
    assert project is not None
    assert project['slug'] == 'test-project'
    assert project['name'] == 'Test Project'
    mock_repo.get_by_slug.assert_called_once_with('test-project')


def test_get_by_slug_required_raises_when_not_found():
    """Test that get_by_slug with required=True raises exception"""
    from services.project_service import ProjectService
    from error_handler import ResourceNotFoundError

    # Create mock context
    mock_context = Mock()
    mock_repo = Mock()
    mock_repo.get_by_slug.return_value = None  # Project not found
    mock_context.project_repo = mock_repo
    mock_context.file_repo = Mock()

    # Create service
    service = ProjectService(mock_context)

    # Test - should raise exception
    try:
        service.get_by_slug('nonexistent', required=True)
        assert False, "Should have raised ResourceNotFoundError"
    except ResourceNotFoundError as e:
        assert 'nonexistent' in str(e)
        assert 'not found' in str(e).lower()


def test_create_project_validates_slug():
    """Test that create_project validates slug format"""
    from services.project_service import ProjectService
    from error_handler import ValidationError

    # Create mock context
    mock_context = Mock()
    mock_repo = Mock()
    mock_repo.get_by_slug.return_value = None  # Slug available
    mock_context.project_repo = mock_repo
    mock_context.file_repo = Mock()

    # Create service
    service = ProjectService(mock_context)

    # Test with invalid slug (spaces not allowed)
    try:
        service.create_project(slug='Invalid Slug!')
        assert False, "Should have raised ValidationError"
    except ValidationError as e:
        assert 'slug' in str(e).lower()
        assert 'invalid' in str(e).lower() or 'format' in str(e).lower()


def test_create_project_checks_duplicates():
    """Test that create_project rejects duplicate slugs"""
    from services.project_service import ProjectService
    from error_handler import ValidationError

    # Create mock context
    mock_context = Mock()
    mock_repo = Mock()
    mock_repo.get_by_slug.return_value = {'id': 1}  # Slug already exists
    mock_context.project_repo = mock_repo
    mock_context.file_repo = Mock()

    # Create service
    service = ProjectService(mock_context)

    # Test with duplicate slug
    try:
        service.create_project(slug='existing-project')
        assert False, "Should have raised ValidationError"
    except ValidationError as e:
        assert 'already exists' in str(e).lower()


def test_create_project_calls_repository():
    """Test that create_project calls repository with correct parameters"""
    from services.project_service import ProjectService

    # Create mock context
    mock_context = Mock()
    mock_repo = Mock()
    mock_repo.get_by_slug.return_value = None  # Slug available
    mock_repo.create.return_value = 42  # Mock project ID
    mock_context.project_repo = mock_repo
    mock_context.file_repo = Mock()

    # Create service
    service = ProjectService(mock_context)

    # Test
    project_id = service.create_project(
        slug='new-project',
        name='New Project',
        repo_url='/path/to/repo',
        git_branch='main'
    )

    # Verify
    assert project_id == 42
    mock_repo.create.assert_called_once_with(
        slug='new-project',
        name='New Project',
        repo_url='/path/to/repo',
        git_branch='main'
    )


def test_delete_project_requires_existing_project():
    """Test that delete_project validates project exists"""
    from services.project_service import ProjectService
    from error_handler import ResourceNotFoundError

    # Create mock context
    mock_context = Mock()
    mock_repo = Mock()
    mock_repo.get_by_slug.return_value = None  # Project not found
    mock_context.project_repo = mock_repo
    mock_context.file_repo = Mock()

    # Create service
    service = ProjectService(mock_context)

    # Test
    try:
        service.delete_project('nonexistent')
        assert False, "Should have raised ResourceNotFoundError"
    except ResourceNotFoundError as e:
        assert 'not found' in str(e).lower()


def test_delete_project_calls_repository():
    """Test that delete_project calls repository delete method"""
    from services.project_service import ProjectService

    # Create mock context
    mock_context = Mock()
    mock_repo = Mock()
    mock_repo.get_by_slug.return_value = {'id': 123, 'slug': 'test'}
    mock_context.project_repo = mock_repo
    mock_context.file_repo = Mock()

    # Create service
    service = ProjectService(mock_context)

    # Test
    service.delete_project('test')

    # Verify
    mock_repo.delete.assert_called_once_with(123)


# Example of how to run these tests:
if __name__ == '__main__':
    print("Run these tests with pytest:")
    print("  pytest tests/unit/services/test_project_service.py -v")
    print()
    print("Or run all service tests:")
    print("  pytest tests/unit/services/ -v")
