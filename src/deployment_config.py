#!/usr/bin/env python3
"""
Deployment Configuration Parser and Validator

Handles parsing, validation, and management of deployment configs stored in projects table.
"""
import json
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class DeploymentGroup:
    """Represents a deployment group (migrations, build, functions, etc.)"""
    name: str
    order: int
    file_patterns: List[str] = field(default_factory=list)
    pre_deploy: List[str] = field(default_factory=list)
    deploy_command: Optional[str] = None
    build_command: Optional[str] = None
    test_command: Optional[str] = None
    post_deploy: List[str] = field(default_factory=list)
    required_env_vars: List[str] = field(default_factory=list)
    continue_on_failure: bool = False
    # Retry and timeout configuration
    retry_attempts: int = 1  # Number of retry attempts (1 = no retries)
    retry_delay: int = 5     # Seconds to wait between retries
    timeout: Optional[int] = None  # Command timeout in seconds (None = use defaults)
    hook_timeout: int = 30   # Timeout for pre/post hooks in seconds

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'DeploymentGroup':
        """Create DeploymentGroup from dictionary"""
        return cls(
            name=data['name'],
            order=data['order'],
            file_patterns=data.get('file_patterns', []),
            pre_deploy=data.get('pre_deploy', []),
            deploy_command=data.get('deploy_command'),
            build_command=data.get('build_command'),
            test_command=data.get('test_command'),
            post_deploy=data.get('post_deploy', []),
            required_env_vars=data.get('required_env_vars', []),
            continue_on_failure=data.get('continue_on_failure', False),
            retry_attempts=data.get('retry_attempts', 1),
            retry_delay=data.get('retry_delay', 5),
            timeout=data.get('timeout'),
            hook_timeout=data.get('hook_timeout', 30)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        result = {
            'name': self.name,
            'order': self.order,
            'file_patterns': self.file_patterns,
            'pre_deploy': self.pre_deploy,
            'deploy_command': self.deploy_command,
            'build_command': self.build_command,
            'test_command': self.test_command,
            'post_deploy': self.post_deploy,
            'required_env_vars': self.required_env_vars,
            'continue_on_failure': self.continue_on_failure
        }
        # Only include retry/timeout config if non-default
        if self.retry_attempts != 1:
            result['retry_attempts'] = self.retry_attempts
        if self.retry_delay != 5:
            result['retry_delay'] = self.retry_delay
        if self.timeout is not None:
            result['timeout'] = self.timeout
        if self.hook_timeout != 30:
            result['hook_timeout'] = self.hook_timeout
        return result


@dataclass
class HealthCheck:
    """Health check configuration"""
    url: str
    expected_status: int = 200
    timeout_seconds: int = 30
    retry_count: int = 3

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'HealthCheck':
        """Create HealthCheck from dictionary"""
        return cls(
            url=data['url'],
            expected_status=data.get('expected_status', 200),
            timeout_seconds=data.get('timeout_seconds', 30),
            retry_count=data.get('retry_count', 3)
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization"""
        return {
            'url': self.url,
            'expected_status': self.expected_status,
            'timeout_seconds': self.timeout_seconds,
            'retry_count': self.retry_count
        }


@dataclass
class DeploymentConfig:
    """Complete deployment configuration for a project"""
    groups: List[DeploymentGroup] = field(default_factory=list)
    health_check: Optional[HealthCheck] = None

    @classmethod
    def from_json(cls, json_str: str) -> 'DeploymentConfig':
        """Parse deployment config from JSON string"""
        if not json_str:
            return cls()

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in deployment config: {e}")

        groups = [DeploymentGroup.from_dict(g) for g in data.get('groups', [])]
        health_check = None
        if 'health_check' in data:
            health_check = HealthCheck.from_dict(data['health_check'])

        return cls(groups=groups, health_check=health_check)

    def to_json(self) -> str:
        """Serialize to JSON string"""
        data = {
            'groups': [g.to_dict() for g in self.groups]
        }
        if self.health_check:
            data['health_check'] = self.health_check.to_dict()

        return json.dumps(data, indent=2)

    def validate(self) -> List[str]:
        """Validate configuration and return list of errors"""
        errors = []

        if not self.groups:
            errors.append("No deployment groups defined")
            return errors

        # Check for duplicate group names
        group_names = [g.name for g in self.groups]
        if len(group_names) != len(set(group_names)):
            errors.append("Duplicate group names found")

        # Check for duplicate orders
        orders = [g.order for g in self.groups]
        if len(orders) != len(set(orders)):
            errors.append("Duplicate group orders found")

        # Validate each group
        for group in self.groups:
            if not group.name:
                errors.append("Group missing name")

            if group.order < 1:
                errors.append(f"Group '{group.name}' has invalid order: {group.order}")

            if not group.file_patterns and not group.build_command:
                errors.append(f"Group '{group.name}' has no file_patterns or build_command")

            # Check for required commands
            if group.file_patterns and not (group.deploy_command or group.build_command):
                errors.append(f"Group '{group.name}' has file_patterns but no deploy/build command")

        # Validate health check
        if self.health_check:
            if not self.health_check.url:
                errors.append("Health check URL is empty")

            if self.health_check.timeout_seconds < 1:
                errors.append(f"Health check timeout must be >= 1 second")

        return errors

    def get_group(self, name: str) -> Optional[DeploymentGroup]:
        """Get group by name"""
        for group in self.groups:
            if group.name == name:
                return group
        return None

    def get_all_required_env_vars(self) -> List[str]:
        """Get all required environment variables across all groups"""
        all_vars = set()
        for group in self.groups:
            all_vars.update(group.required_env_vars)
        return sorted(list(all_vars))


class DeploymentConfigManager:
    """Manages deployment configs for projects"""

    def __init__(self, db_utils):
        """Initialize with database utilities"""
        self.query_one = db_utils.query_one
        self.execute = db_utils.execute

    def get_config(self, project_id: int) -> DeploymentConfig:
        """Get deployment config for project"""
        result = self.query_one(
            "SELECT deployment_config FROM projects WHERE id = ?",
            (project_id,)
        )

        if not result or not result['deployment_config']:
            return DeploymentConfig()

        return DeploymentConfig.from_json(result['deployment_config'])

    def set_config(self, project_id: int, config: DeploymentConfig) -> None:
        """Save deployment config for project"""
        # Validate before saving
        errors = config.validate()
        if errors:
            raise ValueError(f"Invalid deployment config: {', '.join(errors)}")

        json_str = config.to_json()
        self.execute(
            "UPDATE projects SET deployment_config = ? WHERE id = ?",
            (json_str, project_id)
        )

    def clear_config(self, project_id: int) -> None:
        """Clear deployment config for project"""
        self.execute(
            "UPDATE projects SET deployment_config = NULL WHERE id = ?",
            (project_id,)
        )


def create_default_config() -> DeploymentConfig:
    """Create a default deployment configuration template"""
    return DeploymentConfig(
        groups=[
            DeploymentGroup(
                name="migrations",
                order=1,
                file_patterns=["migrations/*.sql"],
                pre_deploy=["psql --version"],
                deploy_command="psql $DATABASE_URL -f {file}",
                required_env_vars=["DATABASE_URL"]
            ),
            DeploymentGroup(
                name="typescript_build",
                order=2,
                file_patterns=["src/**/*.ts"],
                build_command="npm run build",
                test_command="npm test"
            )
        ]
    )
