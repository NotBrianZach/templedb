#!/usr/bin/env python3
"""
Nix FHS Environment Management for TempleDB Deployments

Creates isolated FHS (Filesystem Hierarchy Standard) environments using Nix
for cleaner, more reproducible deployments instead of deploying to /tmp.
"""

import subprocess
import tempfile
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from logger import get_logger

logger = get_logger(__name__)


@dataclass
class FHSEnvironment:
    """Represents a Nix FHS environment for deployment"""
    name: str
    project_slug: str
    fhs_dir: Path
    work_dir: Path  # The actual working directory inside FHS
    packages: List[str]
    env_vars: Dict[str, str]

    def __str__(self):
        return f"FHSEnvironment({self.name}, work_dir={self.work_dir})"


class FHSDeploymentManager:
    """Manages Nix FHS environments for TempleDB deployments"""

    def __init__(self, base_dir: Optional[Path] = None):
        """
        Initialize FHS deployment manager

        Args:
            base_dir: Base directory for FHS environments (default: ~/.templedb/fhs-deployments)
        """
        if base_dir is None:
            base_dir = Path.home() / ".templedb" / "fhs-deployments"

        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

        logger.debug(f"FHS deployment base: {self.base_dir}")

    def create_fhs_env(
        self,
        project_slug: str,
        packages: Optional[List[str]] = None,
        env_vars: Optional[Dict[str, str]] = None
    ) -> FHSEnvironment:
        """
        Create a Nix FHS environment for a project deployment

        Args:
            project_slug: Project identifier
            packages: List of Nix packages to include (default: common dev tools)
            env_vars: Environment variables to set

        Returns:
            FHSEnvironment object
        """
        if packages is None:
            packages = self._get_default_packages()

        if env_vars is None:
            env_vars = {}

        # Create FHS directory structure
        fhs_dir = self.base_dir / project_slug
        fhs_dir.mkdir(parents=True, exist_ok=True)

        # Create working directory inside FHS
        work_dir = fhs_dir / "workspace"
        work_dir.mkdir(parents=True, exist_ok=True)

        # Create Nix expression for FHS environment
        nix_expr = self._generate_fhs_nix_expr(
            name=f"templedb-{project_slug}",
            packages=packages,
            work_dir=work_dir
        )

        # Write Nix expression
        nix_file = fhs_dir / "fhs-env.nix"
        nix_file.write_text(nix_expr)

        # Create environment info file
        env_info = {
            'project_slug': project_slug,
            'packages': packages,
            'env_vars': env_vars,
            'work_dir': str(work_dir),
            'created_at': self._now()
        }

        info_file = fhs_dir / "env-info.json"
        info_file.write_text(json.dumps(env_info, indent=2))

        logger.info(f"Created FHS environment for {project_slug} at {fhs_dir}")

        return FHSEnvironment(
            name=f"templedb-{project_slug}",
            project_slug=project_slug,
            fhs_dir=fhs_dir,
            work_dir=work_dir,
            packages=packages,
            env_vars=env_vars
        )

    def get_fhs_env(self, project_slug: str) -> Optional[FHSEnvironment]:
        """
        Get existing FHS environment for a project

        Returns None if environment doesn't exist
        """
        fhs_dir = self.base_dir / project_slug
        info_file = fhs_dir / "env-info.json"

        if not info_file.exists():
            return None

        try:
            env_info = json.loads(info_file.read_text())

            return FHSEnvironment(
                name=f"templedb-{project_slug}",
                project_slug=project_slug,
                fhs_dir=fhs_dir,
                work_dir=Path(env_info['work_dir']),
                packages=env_info.get('packages', []),
                env_vars=env_info.get('env_vars', {})
            )
        except Exception as e:
            logger.error(f"Failed to load FHS environment info: {e}")
            return None

    def enter_fhs_env(
        self,
        fhs_env: FHSEnvironment,
        command: Optional[List[str]] = None
    ) -> subprocess.CompletedProcess:
        """
        Enter FHS environment and optionally run a command

        Args:
            fhs_env: FHS environment to enter
            command: Command to run (default: bash shell)

        Returns:
            CompletedProcess result
        """
        nix_file = fhs_env.fhs_dir / "fhs-env.nix"

        if not nix_file.exists():
            raise FileNotFoundError(f"FHS environment not found: {nix_file}")

        # Build command to enter FHS
        if command is None:
            command = ["bash"]

        # Use nix-shell to enter FHS environment
        nix_cmd = [
            "nix-shell",
            str(nix_file),
            "--run",
            " ".join(command)
        ]

        # Set working directory and environment
        env = dict(fhs_env.env_vars)
        env['PWD'] = str(fhs_env.work_dir)

        logger.debug(f"Entering FHS: {' '.join(nix_cmd)}")

        result = subprocess.run(
            nix_cmd,
            cwd=str(fhs_env.work_dir),
            env=env,
            capture_output=True,
            text=True
        )

        return result

    def run_in_fhs(
        self,
        project_slug: str,
        command: List[str],
        env_vars: Optional[Dict[str, str]] = None,
        create_if_missing: bool = True
    ) -> subprocess.CompletedProcess:
        """
        Run a command in the FHS environment for a project

        Convenience method that gets or creates the environment

        Args:
            project_slug: Project to run command for
            command: Command to execute
            env_vars: Additional environment variables
            create_if_missing: Create FHS env if it doesn't exist

        Returns:
            CompletedProcess result
        """
        fhs_env = self.get_fhs_env(project_slug)

        if fhs_env is None:
            if create_if_missing:
                logger.info(f"Creating FHS environment for {project_slug}")
                fhs_env = self.create_fhs_env(project_slug, env_vars=env_vars)
            else:
                raise ValueError(f"FHS environment not found for {project_slug}")

        # Merge env vars
        if env_vars:
            fhs_env.env_vars.update(env_vars)

        return self.enter_fhs_env(fhs_env, command)

    def cleanup_fhs_env(self, project_slug: str) -> bool:
        """
        Remove FHS environment for a project

        Returns:
            True if cleaned up successfully
        """
        fhs_dir = self.base_dir / project_slug

        if not fhs_dir.exists():
            logger.warning(f"FHS environment not found: {project_slug}")
            return False

        try:
            import shutil
            shutil.rmtree(fhs_dir)
            logger.info(f"Cleaned up FHS environment: {project_slug}")
            return True
        except Exception as e:
            logger.error(f"Failed to cleanup FHS environment: {e}")
            return False

    def list_fhs_envs(self) -> List[Dict[str, Any]]:
        """
        List all FHS environments

        Returns:
            List of environment info dicts
        """
        envs = []

        for project_dir in self.base_dir.iterdir():
            if not project_dir.is_dir():
                continue

            info_file = project_dir / "env-info.json"
            if not info_file.exists():
                continue

            try:
                env_info = json.loads(info_file.read_text())
                env_info['fhs_dir'] = str(project_dir)
                envs.append(env_info)
            except Exception as e:
                logger.error(f"Failed to load env info for {project_dir.name}: {e}")

        return envs

    def _generate_fhs_nix_expr(
        self,
        name: str,
        packages: List[str],
        work_dir: Path
    ) -> str:
        """Generate Nix expression for FHS environment"""

        # Build package list
        pkg_list = " ".join(packages)

        nix_expr = f'''# Nix FHS environment for TempleDB deployment
# Auto-generated by TempleDB FHS deployment manager

{{ pkgs ? import <nixpkgs> {{}} }}:

(pkgs.buildFHSUserEnv {{
  name = "{name}";

  # Packages available in the FHS environment
  targetPkgs = pkgs: with pkgs; [
    {pkg_list}
  ];

  # Multi-architecture library support
  multiPkgs = pkgs: with pkgs; [
    # Common libraries for compatibility
  ];

  # Set working directory
  profile = ''
    export PS1="(fhs:{name}) $PS1"
    cd {work_dir}
  '';

  # Additional environment setup
  runScript = "bash";
}}).env
'''

        return nix_expr

    def _get_default_packages(self) -> List[str]:
        """Get default package list for FHS environments"""
        return [
            # Core tools
            "coreutils",
            "findutils",
            "gnused",
            "gnugrep",
            "bash",
            "git",

            # Build tools
            "gcc",
            "gnumake",
            "pkg-config",

            # Common development tools
            "curl",
            "wget",
            "jq",
            "which",

            # Python (common for deployments)
            "python3",
            "python3Packages.pip",
            "python3Packages.virtualenv",

            # Node.js (common for web deployments)
            "nodejs",
            "nodePackages.npm",

            # Database clients
            "postgresql",
            "sqlite",

            # SSL/TLS
            "openssl",
            "cacert",
        ]

    def _now(self) -> str:
        """Get current timestamp as ISO string"""
        from datetime import datetime
        return datetime.now().isoformat()


def main():
    """Test/demo FHS deployment"""
    manager = FHSDeploymentManager()

    # Create test environment
    fhs_env = manager.create_fhs_env(
        project_slug="test-project",
        env_vars={"TEST_VAR": "hello"}
    )

    print(f"Created: {fhs_env}")
    print(f"Work dir: {fhs_env.work_dir}")

    # Run command in environment
    result = manager.run_in_fhs(
        "test-project",
        ["echo", "Hello from FHS: $TEST_VAR"]
    )

    print(f"Output: {result.stdout}")

    # List environments
    envs = manager.list_fhs_envs()
    print(f"\nFHS Environments ({len(envs)}):")
    for env in envs:
        print(f"  - {env['project_slug']}")


if __name__ == "__main__":
    main()
