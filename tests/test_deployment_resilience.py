#!/usr/bin/env python3
"""
Tests for deployment resilience features (retry logic, timeouts, hook handling)
"""
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from deployment_config import DeploymentGroup, DeploymentConfig
from deployment_orchestrator import GroupResult


class TestDeploymentResilience(unittest.TestCase):
    """Test deployment resilience features"""

    def test_deployment_group_retry_defaults(self):
        """Test DeploymentGroup has proper retry defaults"""
        group = DeploymentGroup(
            name="test",
            order=1,
            deploy_command="echo test"
        )

        self.assertEqual(group.retry_attempts, 1)
        self.assertEqual(group.retry_delay, 5)
        self.assertIsNone(group.timeout)
        self.assertEqual(group.hook_timeout, 30)

    def test_deployment_group_retry_custom(self):
        """Test DeploymentGroup with custom retry config"""
        group = DeploymentGroup(
            name="test",
            order=1,
            deploy_command="echo test",
            retry_attempts=3,
            retry_delay=10,
            timeout=600,
            hook_timeout=60
        )

        self.assertEqual(group.retry_attempts, 3)
        self.assertEqual(group.retry_delay, 10)
        self.assertEqual(group.timeout, 600)
        self.assertEqual(group.hook_timeout, 60)

    def test_deployment_group_from_dict_with_retry(self):
        """Test parsing DeploymentGroup from dict with retry config"""
        data = {
            'name': 'migrations',
            'order': 1,
            'deploy_command': 'psql -f {file}',
            'retry_attempts': 3,
            'retry_delay': 10,
            'timeout': 900,
            'hook_timeout': 60
        }

        group = DeploymentGroup.from_dict(data)

        self.assertEqual(group.name, 'migrations')
        self.assertEqual(group.retry_attempts, 3)
        self.assertEqual(group.retry_delay, 10)
        self.assertEqual(group.timeout, 900)
        self.assertEqual(group.hook_timeout, 60)

    def test_deployment_group_to_dict_minimal(self):
        """Test serializing DeploymentGroup with default retry config"""
        group = DeploymentGroup(
            name="test",
            order=1,
            deploy_command="echo test"
        )

        data = group.to_dict()

        # Default values should not be serialized
        self.assertNotIn('retry_attempts', data)
        self.assertNotIn('retry_delay', data)
        self.assertNotIn('timeout', data)
        self.assertNotIn('hook_timeout', data)

    def test_deployment_group_to_dict_custom(self):
        """Test serializing DeploymentGroup with custom retry config"""
        group = DeploymentGroup(
            name="test",
            order=1,
            deploy_command="echo test",
            retry_attempts=3,
            timeout=600
        )

        data = group.to_dict()

        # Custom values should be serialized
        self.assertEqual(data['retry_attempts'], 3)
        self.assertEqual(data['timeout'], 600)
        # Default delay not changed, should not be serialized
        self.assertNotIn('retry_delay', data)

    def test_group_result_hook_distinction(self):
        """Test GroupResult distinguishes deployment vs hook success"""
        # Deployment succeeded, all hooks succeeded
        result = GroupResult(
            group_name="test",
            success=True,
            duration_ms=1000,
            deployment_success=True,
            pre_hook_success=True,
            post_hook_success=True
        )

        self.assertTrue(result.success)
        self.assertFalse(result.has_warnings)
        self.assertFalse(result.is_partial_success)

    def test_group_result_post_hook_warning(self):
        """Test GroupResult with post-hook failure creates warning"""
        # Deployment succeeded, but post-hook failed
        result = GroupResult(
            group_name="test",
            success=False,  # Overall marked as failed
            duration_ms=1000,
            deployment_success=True,  # But deployment itself succeeded
            pre_hook_success=True,
            post_hook_success=False,
            post_hook_errors=["Slack notification failed"]
        )

        self.assertFalse(result.success)  # Overall fails
        self.assertTrue(result.deployment_success)  # But core deployment succeeded
        self.assertTrue(result.has_warnings)  # Has warnings
        self.assertTrue(result.is_partial_success)  # Partial success
        self.assertEqual(len(result.post_hook_errors), 1)

    def test_group_result_pre_hook_failure(self):
        """Test GroupResult with pre-hook failure"""
        # Pre-hook failed, deployment never ran
        result = GroupResult(
            group_name="test",
            success=False,
            duration_ms=100,
            deployment_success=False,
            pre_hook_success=False,
            post_hook_success=True,
            error_message="Pre-deploy hook failed"
        )

        self.assertFalse(result.success)
        self.assertFalse(result.deployment_success)
        self.assertFalse(result.has_warnings)  # Not a warning, actual failure
        self.assertFalse(result.is_partial_success)

    def test_deployment_config_roundtrip_with_retry(self):
        """Test DeploymentConfig serialization/deserialization with retry config"""
        config = DeploymentConfig(
            groups=[
                DeploymentGroup(
                    name="migrations",
                    order=1,
                    file_patterns=["migrations/*.sql"],
                    deploy_command="psql -f {file}",
                    retry_attempts=3,
                    retry_delay=10,
                    timeout=900,
                    hook_timeout=60
                )
            ]
        )

        # Serialize to JSON
        json_str = config.to_json()

        # Deserialize back
        config2 = DeploymentConfig.from_json(json_str)

        # Verify retry config preserved
        self.assertEqual(len(config2.groups), 1)
        group = config2.groups[0]
        self.assertEqual(group.retry_attempts, 3)
        self.assertEqual(group.retry_delay, 10)
        self.assertEqual(group.timeout, 900)
        self.assertEqual(group.hook_timeout, 60)


if __name__ == '__main__':
    unittest.main()
