#!/usr/bin/env python3
"""
Unit tests for DeploymentService
"""
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / 'src'))

import pytest


@pytest.fixture
def mock_deployment_context():
    """Create mock context for deployment service"""
    context = Mock()
    context.project_repo = Mock()
    context.base_repo = Mock()
    context.script_dir = Path('/mock/script/dir')
    return context


def test_get_deployment_status_returns_status(mock_deployment_context):
    """Test that get_deployment_status returns deployment information"""
    from services.deployment_service import DeploymentService

    # Setup mock data
    mock_deployment_context.project_repo.get_by_slug.return_value = {
        'id': 1,
        'slug': 'test-project'
    }

    mock_deployment_context.base_repo.query_all.side_effect = [
        [{'target_name': 'production', 'target_type': 'server', 'provider': 'aws', 'host': 'server.com'}],
        [{'file_path': 'deploy.sh'}]
    ]

    mock_deployment_context.base_repo.query_one.return_value = {'count': 5}

    # Create service
    service = DeploymentService(mock_deployment_context)

    # Test
    status = service.get_deployment_status('test-project')

    # Verify
    assert status['project_slug'] == 'test-project'
    assert len(status['targets']) == 1
    assert status['targets'][0]['target_name'] == 'production'
    assert len(status['deploy_scripts']) == 1
    assert status['migration_count'] == 5


def test_get_deployment_status_requires_existing_project(mock_deployment_context):
    """Test that get_deployment_status validates project exists"""
    from services.deployment_service import DeploymentService
    from error_handler import ResourceNotFoundError

    # Setup - project not found
    mock_deployment_context.project_repo.get_by_slug.return_value = None

    # Create service
    service = DeploymentService(mock_deployment_context)

    # Test - should raise exception
    with pytest.raises(ResourceNotFoundError) as exc_info:
        service.get_deployment_status('nonexistent')

    assert 'not found' in str(exc_info.value).lower()


@patch('services.deployment_service.subprocess.run')
def test_deployment_executes_script(mock_run, mock_deployment_context):
    """Test deployment execution with deploy.sh script"""
    from services.deployment_service import DeploymentService

    # Setup
    mock_deployment_context.project_repo.get_by_slug.return_value = {
        'id': 1,
        'slug': 'test-project'
    }

    # Mock successful script execution
    mock_run.return_value = Mock(returncode=0)

    # Mock deployment functions
    with patch('services.deployment_service.DeploymentService._export_project') as mock_export:
        mock_export.return_value = Path('/tmp/test.cathedral')

        with patch('services.deployment_service.DeploymentService._reconstruct_project') as mock_reconstruct:
            mock_reconstruct.return_value = 10  # 10 files reconstructed

            with patch('services.deployment_service.DeploymentService._execute_deployment') as mock_execute:
                from services.deployment_service import DeploymentResult
                mock_execute.return_value = DeploymentResult(
                    success=True,
                    project_slug='test-project',
                    target='production',
                    work_dir=Path('/tmp/work'),
                    message='Success'
                )

                # Create service
                service = DeploymentService(mock_deployment_context)

                # Test
                result = service.deploy('test-project', 'production', dry_run=False)

                # Verify
                assert result.success is True
                assert result.project_slug == 'test-project'
                assert result.target == 'production'


def test_deployment_dry_run_mode(mock_deployment_context):
    """Test that dry_run mode doesn't execute actual deployment"""
    from services.deployment_service import DeploymentService

    # Setup
    mock_deployment_context.project_repo.get_by_slug.return_value = {
        'id': 1,
        'slug': 'test-project'
    }

    # Mock deployment functions to track calls
    with patch('services.deployment_service.DeploymentService._export_project') as mock_export:
        mock_export.return_value = Path('/tmp/test.cathedral')

        with patch('services.deployment_service.DeploymentService._reconstruct_project') as mock_reconstruct:
            mock_reconstruct.return_value = 10

            with patch('services.deployment_service.DeploymentService._execute_deployment') as mock_execute:
                from services.deployment_service import DeploymentResult
                mock_execute.return_value = DeploymentResult(
                    success=True,
                    project_slug='test-project',
                    target='production',
                    work_dir=Path('/tmp/work'),
                    message='Dry run complete'
                )

                # Create service
                service = DeploymentService(mock_deployment_context)

                # Test
                result = service.deploy('test-project', 'production', dry_run=True)

                # Verify
                assert result.success is True
                # In dry run, _execute_deployment should be called with dry_run=True
                assert mock_execute.called


if __name__ == '__main__':
    print("Run these tests with pytest:")
    print("  pytest tests/unit/services/test_deployment_service.py -v")
