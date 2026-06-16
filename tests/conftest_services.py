#!/usr/bin/env python3
"""
Pytest fixtures for service layer testing

Provides reusable fixtures for testing services with mocked dependencies.
"""
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pytest


@pytest.fixture
def mock_context():
    """
    Create a mock ServiceContext with mocked repositories.

    Usage:
        def test_my_service(mock_context):
            mock_context.project_repo.get_by_slug.return_value = {'id': 1}
            service = MyService(mock_context)
            result = service.do_something()
    """
    context = Mock()

    # Mock repositories
    context.project_repo = Mock()
    context.file_repo = Mock()
    context.base_repo = Mock()

    # Mock script_dir
    context.script_dir = Path('/mock/script/dir')

    return context


@pytest.fixture
def sample_project():
    """
    Create a sample project dictionary for testing.

    Returns:
        dict: Sample project data
    """
    return {
        'id': 1,
        'slug': 'test-project',
        'name': 'Test Project',
        'repo_url': '/path/to/test-project',
        'git_branch': 'main',
        'created_at': '2024-01-01 00:00:00',
        'updated_at': '2024-01-01 00:00:00'
    }


@pytest.fixture
def sample_projects():
    """
    Create multiple sample projects for testing.

    Returns:
        list: List of sample project dictionaries
    """
    return [
        {
            'id': 1,
            'slug': 'project-one',
            'name': 'Project One',
            'repo_url': '/path/to/project-one',
            'file_count': 10,
            'total_lines': 1000
        },
        {
            'id': 2,
            'slug': 'project-two',
            'name': 'Project Two',
            'repo_url': '/path/to/project-two',
            'file_count': 20,
            'total_lines': 2000
        },
        {
            'id': 3,
            'slug': 'project-three',
            'name': 'Project Three',
            'repo_url': '/path/to/project-three',
            'file_count': 30,
            'total_lines': 3000
        }
    ]


@pytest.fixture
def sample_import_stats():
    """
    Create sample import statistics for testing.

    Returns:
        ImportStats: Sample import statistics
    """
    from services.project_service import ImportStats

    return ImportStats(
        total_files_scanned=100,
        files_imported=95,
        content_stored=90,
        versions_created=95,
        sql_objects_found=10
    )


@pytest.fixture
def sample_deployment_result():
    """
    Create sample deployment result for testing.

    Returns:
        DeploymentResult: Sample deployment result
    """
    from services.deployment_service import DeploymentResult

    return DeploymentResult(
        success=True,
        project_slug='test-project',
        target='production',
        work_dir=Path('/tmp/test-deploy'),
        message='Deployment successful',
        exit_code=0
    )


@pytest.fixture
def sample_commit_result():
    """
    Create sample commit result for testing.

    Returns:
        CommitResult: Sample commit result
    """
    from services.vcs_service import CommitResult

    return CommitResult(
        commit_id=1,
        commit_hash='ABC123DEF456',
        message='Test commit',
        file_count=5,
        author='Test User <test@example.com>'
    )


@pytest.fixture
def sample_environment():
    """
    Create sample environment dictionary for testing.

    Returns:
        dict: Sample environment data
    """
    return {
        'id': 1,
        'project_id': 1,
        'env_name': 'dev',
        'description': 'Development environment',
        'base_packages': 'python,nodejs,postgresql',
        'created_at': '2024-01-01 00:00:00'
    }


@pytest.fixture
def sample_vcs_status():
    """
    Create sample VCS status for testing.

    Returns:
        dict: Sample VCS status
    """
    return {
        'has_branch': True,
        'branch': 'main',
        'staged': ['src/file1.py', 'src/file2.py'],
        'modified': ['README.md'],
        'untracked': ['test.txt']
    }


class MockRepository:
    """
    Base mock repository with common methods.

    Provides default implementations that can be overridden in tests.
    """

    def __init__(self):
        self.data = {}
        self.next_id = 1

    def get_by_slug(self, slug):
        """Get item by slug"""
        return self.data.get(slug)

    def get_all(self):
        """Get all items"""
        return list(self.data.values())

    def create(self, **kwargs):
        """Create new item"""
        item_id = self.next_id
        self.next_id += 1
        item = {'id': item_id, **kwargs}
        if 'slug' in kwargs:
            self.data[kwargs['slug']] = item
        return item_id

    def delete(self, item_id):
        """Delete item by ID"""
        for slug, item in list(self.data.items()):
            if item['id'] == item_id:
                del self.data[slug]
                break

    def query_one(self, sql, params=None):
        """Mock query_one"""
        return None

    def query_all(self, sql, params=None):
        """Mock query_all"""
        return []

    def execute(self, sql, params=None):
        """Mock execute"""
        return self.next_id


@pytest.fixture
def mock_project_repo():
    """Create a mock ProjectRepository with in-memory storage"""
    return MockRepository()


@pytest.fixture
def mock_file_repo():
    """Create a mock FileRepository with in-memory storage"""
    return MockRepository()


@pytest.fixture
def mock_vcs_repo():
    """Create a mock VCSRepository with in-memory storage"""
    return MockRepository()


# Helper functions for tests

def assert_validation_error(func, *args, **kwargs):
    """
    Assert that a function raises ValidationError.

    Usage:
        assert_validation_error(service.create_project, slug='Invalid!')
    """
    from error_handler import ValidationError
    import pytest

    with pytest.raises(ValidationError):
        func(*args, **kwargs)


def assert_resource_not_found(func, *args, **kwargs):
    """
    Assert that a function raises ResourceNotFoundError.

    Usage:
        assert_resource_not_found(service.get_by_slug, 'nonexistent')
    """
    from error_handler import ResourceNotFoundError
    import pytest

    with pytest.raises(ResourceNotFoundError):
        func(*args, **kwargs)


def create_mock_context_with_data(projects=None, files=None):
    """
    Create a mock context pre-populated with test data.

    Args:
        projects: List of project dictionaries to add
        files: List of file dictionaries to add

    Returns:
        Mock context with populated repositories

    Usage:
        context = create_mock_context_with_data(
            projects=[{'slug': 'test', 'name': 'Test Project'}]
        )
        service = ProjectService(context)
    """
    context = Mock()

    # Create mock repos with data
    project_repo = MockRepository()
    if projects:
        for project in projects:
            project_repo.create(**project)

    file_repo = MockRepository()
    if files:
        for file in files:
            file_repo.create(**file)

    context.project_repo = project_repo
    context.file_repo = file_repo
    context.base_repo = Mock()
    context.script_dir = Path('/mock/script/dir')

    return context


# Pytest configuration

def pytest_configure(config):
    """Configure pytest with custom markers"""
    config.addinivalue_line(
        "markers", "unit: mark test as a unit test"
    )
    config.addinivalue_line(
        "markers", "integration: mark test as an integration test"
    )
    config.addinivalue_line(
        "markers", "service: mark test as a service layer test"
    )
    config.addinivalue_line(
        "markers", "slow: mark test as slow running"
    )
