#!/usr/bin/env python3
"""
Full Nix FHS Integration for TempleDB Deployments

Wraps deployment operations in Nix FHS environments with automatically
detected dependencies, providing complete isolation and reproducibility.
"""

import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from fhs_deployment import FHSDeploymentManager, FHSEnvironment
from fhs_package_detector import PackageDetector
from logger import get_logger

logger = get_logger(__name__)


@dataclass
class FHSDeploymentContext:
    """Context for an FHS-wrapped deployment"""
    project_slug: str
    project_dir: Path
    fhs_env: FHSEnvironment
    packages: List[str]
    env_vars: Dict[str, str]


class FHSIntegration:
    """Provides full Nix FHS integration for deployments"""

    def __init__(self, fhs_manager: Optional[FHSDeploymentManager] = None):
        """
        Initialize FHS integration

        Args:
            fhs_manager: FHS deployment manager (creates one if not provided)
        """
        self.fhs_manager = fhs_manager or FHSDeploymentManager()
        self.package_detector = PackageDetector()

    def prepare_fhs_deployment(
        self,
        project_slug: str,
        project_dir: Path,
        env_vars: Optional[Dict[str, str]] = None,
        extra_packages: Optional[List[str]] = None
    ) -> FHSDeploymentContext:
        """
        Prepare FHS environment for deployment

        Automatically detects required packages and creates FHS environment

        Args:
            project_slug: Project identifier
            project_dir: Project working directory
            env_vars: Environment variables to set
            extra_packages: Additional Nix packages to include

        Returns:
            FHSDeploymentContext ready for deployment
        """
        logger.info(f"Preparing FHS environment for {project_slug}")

        # Step 1: Detect required packages
        logger.info("Detecting project dependencies...")
        requirements = self.package_detector.detect(project_dir)

        logger.info(f"Detected {len(requirements.nix_packages)} packages:")
        for line in requirements.explain().split("\n"):
            logger.info(line)

        # Add extra packages if provided
        packages = requirements.to_list()
        if extra_packages:
            packages.extend(extra_packages)
            logger.info(f"Added {len(extra_packages)} extra packages")

        # Step 2: Create or get FHS environment
        logger.info("Creating Nix FHS environment...")
        fhs_env = self.fhs_manager.create_fhs_env(
            project_slug=project_slug,
            packages=packages,
            env_vars=env_vars or {}
        )

        logger.info(f"FHS environment ready at {fhs_env.fhs_dir}")

        return FHSDeploymentContext(
            project_slug=project_slug,
            project_dir=project_dir,
            fhs_env=fhs_env,
            packages=packages,
            env_vars=env_vars or {},
        )

    def run_deployment_in_fhs(
        self,
        context: FHSDeploymentContext,
        deployment_command: List[str]
    ) -> subprocess.CompletedProcess:
        """
        Run deployment command inside FHS environment

        Args:
            context: FHS deployment context
            deployment_command: Command to run (e.g., ["bash", "deploy.sh"])

        Returns:
            CompletedProcess result
        """
        logger.info(f"Running deployment in FHS environment")
        logger.info(f"  Command: {' '.join(deployment_command)}")
        logger.info(f"  FHS: {context.fhs_env.name}")
        logger.info(f"  Working dir: {context.project_dir}")

        # Ensure we're using the project directory, not the FHS workspace
        # We want to run commands in the actual deployed project location
        context.fhs_env.work_dir = context.project_dir

        result = self.fhs_manager.enter_fhs_env(
            context.fhs_env,
            deployment_command
        )

        if result.returncode == 0:
            logger.info("✅ Deployment completed successfully in FHS")
        else:
            logger.error(f"❌ Deployment failed in FHS (exit code: {result.returncode})")

        return result

    def run_in_fhs_shell(
        self,
        context: FHSDeploymentContext,
        command: str
    ) -> subprocess.CompletedProcess:
        """
        Run a shell command in FHS environment

        Convenience method for running shell commands

        Args:
            context: FHS deployment context
            command: Shell command string

        Returns:
            CompletedProcess result
        """
        return self.run_deployment_in_fhs(
            context,
            ["bash", "-c", command]
        )

    def create_fhs_shell_script(
        self,
        context: FHSDeploymentContext,
        output_path: Optional[Path] = None
    ) -> Path:
        """
        Create a shell script that enters the FHS environment

        Useful for manual debugging and exploration

        Args:
            context: FHS deployment context
            output_path: Where to write script (default: project_dir/enter-fhs.sh)

        Returns:
            Path to created script
        """
        if output_path is None:
            output_path = context.project_dir / "enter-fhs.sh"

        nix_file = context.fhs_env.fhs_dir / "fhs-env.nix"

        script_content = f'''#!/usr/bin/env bash
# Enter Nix FHS environment for {context.project_slug}
# Auto-generated by TempleDB

set -e

echo "🔧 Entering FHS environment: {context.fhs_env.name}"
echo "📦 Packages: {len(context.packages)} Nix packages available"
echo "📁 Project: {context.project_dir}"
echo ""

# Set environment variables
{self._generate_env_exports(context.env_vars)}

# Enter FHS environment
cd "{context.project_dir}"
nix-shell "{nix_file}"
'''

        output_path.write_text(script_content)
        output_path.chmod(0o755)

        logger.info(f"Created FHS shell script: {output_path}")
        return output_path

    def _generate_env_exports(self, env_vars: Dict[str, str]) -> str:
        """Generate bash export statements for environment variables"""
        if not env_vars:
            return "# No environment variables"

        lines = []
        for key, value in env_vars.items():
            # Escape single quotes in value
            escaped_value = value.replace("'", "'\"'\"'")
            lines.append(f"export {key}='{escaped_value}'")

        return "\n".join(lines)


def demo_full_fhs():
    """Demonstrate full FHS integration"""
    print("=" * 70)
    print("Full Nix FHS Integration Demo")
    print("=" * 70)
    print()

    # Create a test project directory
    import tempfile
    import shutil

    test_dir = Path(tempfile.mkdtemp(prefix="fhs_test_"))
    print(f"📁 Test project: {test_dir}")

    # Create some files to trigger detection
    (test_dir / "package.json").write_text('{"name": "test", "dependencies": {"typescript": "^5.0.0"}}')
    (test_dir / "requirements.txt").write_text("flask>=2.0\npsycopg2-binary")
    (test_dir / ".env").write_text("DATABASE_URL=postgres://localhost/mydb")
    (test_dir / "deploy.sh").write_text("#!/bin/bash\necho 'Deploying...'\nnpm run build\npython manage.py migrate")

    print()

    # Initialize FHS integration
    fhs_integration = FHSIntegration()

    # Prepare FHS environment
    print("🔧 Preparing FHS environment...")
    print()
    context = fhs_integration.prepare_fhs_deployment(
        project_slug="test-project",
        project_dir=test_dir,
        env_vars={"NODE_ENV": "production", "PYTHON_ENV": "production"}
    )

    print()
    print("=" * 70)
    print(f"✅ FHS Environment Ready")
    print("=" * 70)
    print(f"  Project: {context.project_slug}")
    print(f"  FHS dir: {context.fhs_env.fhs_dir}")
    print(f"  Packages: {len(context.packages)}")
    print(f"  Env vars: {len(context.env_vars)}")
    print()

    # Create enter script
    enter_script = fhs_integration.create_fhs_shell_script(context)
    print(f"📝 Created entry script: {enter_script}")
    print()
    print("To enter FHS environment manually:")
    print(f"  {enter_script}")
    print()

    # Test running a command
    print("🧪 Testing command in FHS...")
    result = fhs_integration.run_in_fhs_shell(
        context,
        "echo 'Node version:' && node --version && echo 'Python version:' && python3 --version"
    )

    if result.returncode == 0:
        print("✅ FHS command succeeded")
        print()
        print("Output:")
        print(result.stdout)
    else:
        print("❌ FHS command failed")
        print(result.stderr)

    # Cleanup
    print(f"\n🧹 Cleanup: rm -rf {test_dir}")
    shutil.rmtree(test_dir)

    print()
    print("=" * 70)
    print("Demo Complete")
    print("=" * 70)


if __name__ == "__main__":
    demo_full_fhs()
