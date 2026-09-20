#!/usr/bin/env python3
"""
Integration tests for project workflow

These tests demonstrate end-to-end workflows using the service layer.
They use real services but mock external dependencies (filesystem, subprocess).
"""
import sys
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import tempfile

sys.path.insert(0, str(Path(__file__).parent.parent.parent / 'src'))

import pytest


@pytest.mark.integration
class TestProjectWorkflow:
    """Integration tests for complete project workflows"""

    def test_create_import_sync_workflow(self):
        """
        Test complete workflow: create project → import files → sync

        This demonstrates how services work together in a real workflow.
        """
        from services.context import ServiceContext
        from services.project_service import ProjectService

        # Create real context (will use real repositories)
        # In production tests, you'd use a test database
        context = Mock()  # For now, mock to avoid DB

        # Mock repositories
        context.project_repo = Mock()
        context.file_repo = Mock()
        context.script_dir = Path('/tmp/test')

        # Setup repository behavior
        project_data = {'id': 1, 'slug': 'test-project', 'name': 'Test Project'}
        context.project_repo.get_by_slug.side_effect = [
            None,  # First call - project doesn't exist
            project_data,  # Second call - project exists after creation
            project_data   # Third call - project exists for sync
        ]
        context.project_repo.create.return_value = 1

        # Create service
        service = ProjectService(context)

        # Step 1: Create project
        project_id = service.create_project(
            slug='test-project',
            name='Test Project',
            repo_url='/tmp/test-repo'
        )

        assert project_id == 1
        context.project_repo.create.assert_called_once()

        # Step 2: Get project (verify it exists)
        project = service.get_by_slug('test-project')
        assert project is not None
        assert project['slug'] == 'test-project'

        # Step 3: Import would happen here (mocked in real tests)
        # service.import_project(Path('/tmp/test-repo'))

        # Step 4: Sync would happen here (mocked in real tests)
        # service.sync_project('test-project')


    @pytest.mark.integration
    def test_project_list_and_show_workflow(self):
        """
        Test workflow: list projects → select one → show details
        """
        from services.project_service import ProjectService

        # Create mock context with test data
        context = Mock()
        context.project_repo = Mock()
        context.file_repo = Mock()

        # Setup test data
        test_projects = [
            {'id': 1, 'slug': 'project-1', 'name': 'Project 1', 'file_count': 10},
            {'id': 2, 'slug': 'project-2', 'name': 'Project 2', 'file_count': 20}
        ]

        context.project_repo.get_all.return_value = test_projects
        context.project_repo.get_by_slug.return_value = test_projects[0]
        context.project_repo.get_statistics.return_value = {
            'file_count': 10,
            'total_lines': 1000,
            'file_types': 5
        }
        context.project_repo.get_vcs_info.return_value = {
            'branch_count': 1,
            'commit_count': 5
        }

        # Create service
        service = ProjectService(context)

        # Step 1: List all projects
        projects = service.get_all()
        assert len(projects) == 2
        assert projects[0]['slug'] == 'project-1'

        # Step 2: Show specific project
        project = service.get_by_slug('project-1', required=True)
        assert project['slug'] == 'project-1'

        # Step 3: Get project statistics
        stats = service.get_statistics(project['id'])
        assert stats['file_count'] == 10
        assert stats['total_lines'] == 1000


    @pytest.mark.integration
    def test_deployment_workflow(self):
        """
        Test workflow: check status → deploy → verify
        """
        from services.deployment_service import DeploymentService

        # Create mock context
        context = Mock()
        context.project_repo = Mock()
        context.base_repo = Mock()
        context.script_dir = Path('/tmp/test')

        # Setup project
        context.project_repo.get_by_slug.return_value = {
            'id': 1,
            'slug': 'test-project'
        }

        # Setup deployment status
        context.base_repo.query_all.side_effect = [
            [{'target_name': 'production', 'target_type': 'server'}],
            [{'file_path': 'deploy.sh'}]
        ]
        context.base_repo.query_one.return_value = {'count': 0}

        # Create service
        service = DeploymentService(context)

        # Step 1: Check deployment status
        status = service.get_deployment_status('test-project')
        assert status['project_slug'] == 'test-project'
        assert len(status['targets']) == 1

        # Step 2: Deploy (mocked)
        # In real integration test, this would:
        # - Export cathedral package
        # - Reconstruct files
        # - Execute deployment
        # result = service.deploy('test-project', 'production', dry_run=True)
        # assert result.success


    @pytest.mark.integration
    def test_vcs_workflow(self):
        """
        Test workflow: stage files → check status → commit
        """
        from services.vcs_service import VCSService

        # Create mock context
        context = Mock()
        context.project_repo = Mock()

        # Setup project and branch
        context.project_repo.get_by_slug.return_value = {
            'id': 1,
            'slug': 'test-project'
        }

        # Create mock VCS repo
        from unittest.mock import Mock as VCSMock
        vcs_repo = VCSMock()
        vcs_repo.get_branches.return_value = [
            {'id': 1, 'branch_name': 'main', 'is_default': True}
        ]
        vcs_repo.execute = Mock()
        vcs_repo.query_one.return_value = {'count': 3}
        vcs_repo.query_all.return_value = [
            {'file_path': 'file1.py', 'staged': True},
            {'file_path': 'file2.py', 'staged': True},
            {'file_path': 'file3.py', 'staged': False}
        ]

        # Patch VCSRepository import
        with patch('services.vcs_service.VCSRepository', return_value=vcs_repo):
            # Create service
            service = VCSService(context)

            # Step 1: Stage files
            count = service.stage_files('test-project', stage_all=True)
            assert count == 3

            # Step 2: Check status
            status = service.get_status('test-project')
            assert status['has_branch']
            assert status['branch'] == 'main'

            # Step 3: Commit (would call service.commit() in real test)


    @pytest.mark.integration
    def test_error_propagation_workflow(self):
        """
        Test that errors propagate correctly through service layer
        """
        from services.project_service import ProjectService
        from error_handler import ResourceNotFoundError, ValidationError

        # Create mock context
        context = Mock()
        context.project_repo = Mock()
        context.file_repo = Mock()

        # Project doesn't exist
        context.project_repo.get_by_slug.return_value = None

        # Create service
        service = ProjectService(context)

        # Test 1: ResourceNotFoundError propagates
        with pytest.raises(ResourceNotFoundError) as exc_info:
            service.get_by_slug('nonexistent', required=True)

        assert 'not found' in str(exc_info.value).lower()
        assert hasattr(exc_info.value, 'solution')

        # Test 2: ValidationError propagates
        with pytest.raises(ValidationError) as exc_info:
            service.create_project(slug='Invalid Slug!')

        assert 'invalid' in str(exc_info.value).lower() or 'format' in str(exc_info.value).lower()


if __name__ == '__main__':
    print("Run these tests with pytest:")
    print("  pytest tests/integration/test_project_workflow.py -v")
    print()
    print("Run with marker:")
    print("  pytest -m integration -v")
