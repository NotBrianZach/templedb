#!/usr/bin/env python3
"""
System Service for TempleDB
Manages NixOS system configuration deployments
"""

import os
import subprocess
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
import getpass

from db_utils import query_one, query_all, execute, get_connection

logger = logging.getLogger(__name__)


class SystemServiceError(Exception):
    """Raised when system operations fail"""
    pass


class SystemService:
    """Service for managing NixOS system configurations"""

    def __init__(self):
        self.db_conn = get_connection()

    def get_nixos_config_projects(self) -> List[Dict[str, Any]]:
        """Get all projects marked as nixos-config type"""
        return query_all("""
            SELECT id, slug, name, repo_url, project_type, created_at
            FROM projects
            WHERE project_type = 'nixos-config'
            ORDER BY slug
        """)

    def get_project_checkout_path(self, project_slug: str) -> Optional[Path]:
        """Get the checkout path for a project

        Looks in standard TempleDB checkout locations.
        """
        # Standard checkout locations
        checkout_paths = [
            Path.home() / ".config" / "templedb" / "checkouts" / project_slug,
            Path.home() / "projects" / project_slug,
            Path("/tmp") / f"templedb_checkout_{project_slug}",
        ]

        for path in checkout_paths:
            if path.exists() and (path / "flake.nix").exists():
                return path
            elif path.exists() and (path / "configuration.nix").exists():
                return path

        return None

    def get_config_file_path(self, checkout_path: Path) -> Optional[Path]:
        """Find the main config file (flake.nix or configuration.nix)"""
        flake_path = checkout_path / "flake.nix"
        if flake_path.exists():
            return flake_path

        config_path = checkout_path / "configuration.nix"
        if config_path.exists():
            return config_path

        return None

    def update_system_symlink(self, config_path: Path, dry_run: bool = False) -> bool:
        """Update /etc/nixos symlink to point to config

        Args:
            config_path: Path to flake.nix or configuration.nix
            dry_run: If True, only show what would be done

        Returns:
            True if successful or would be successful
        """
        # Determine symlink target based on config type
        if config_path.name == "flake.nix":
            symlink_path = Path("/etc/nixos/flake.nix")
        else:
            symlink_path = Path("/etc/nixos/configuration.nix")

        if dry_run:
            print(f"Would update symlink:")
            print(f"  {symlink_path} -> {config_path}")
            return True

        try:
            # Create symlink (requires sudo)
            # Don't capture output so user can enter sudo password interactively
            cmd = ["sudo", "ln", "-sf", str(config_path), str(symlink_path)]
            result = subprocess.run(cmd, check=True)
            logger.info(f"Updated symlink: {symlink_path} -> {config_path}")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to update symlink: {e}")
            raise SystemServiceError(f"Failed to update symlink (exit code {e.returncode})")

    def run_nixos_rebuild(
        self,
        command: str,
        flake_path: Optional[Path] = None,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Run nixos-rebuild command

        Args:
            command: One of 'test', 'switch', 'boot', 'build', 'dry-build', 'dry-activate'
            flake_path: Path to flake directory (for flake-based configs)
            dry_run: If True, use 'dry-activate' command instead

        Returns:
            Dict with exit_code, stdout, stderr, and nixos_generation (if applicable)
        """
        # If dry_run is True, use dry-activate command
        if dry_run and command in ['test', 'switch']:
            command = 'dry-activate'
        elif dry_run and command in ['build', 'boot']:
            command = 'dry-build'

        cmd = ["sudo", "nixos-rebuild", command]

        if flake_path:
            cmd.extend(["--flake", str(flake_path)])

        logger.info(f"Running: {' '.join(cmd)}")
        print(f"Running: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10 minute timeout
            )

            # Try to extract generation number from output
            generation = self._extract_generation_number(result.stdout + result.stderr)

            return {
                'exit_code': result.returncode,
                'stdout': result.stdout,
                'stderr': result.stderr,
                'nixos_generation': generation,
                'success': result.returncode == 0
            }
        except subprocess.TimeoutExpired:
            raise SystemServiceError("nixos-rebuild command timed out after 10 minutes")
        except Exception as e:
            raise SystemServiceError(f"Failed to run nixos-rebuild: {e}")

    def _extract_generation_number(self, output: str) -> Optional[int]:
        """Extract NixOS generation number from rebuild output"""
        import re
        # Look for patterns like "building generation 123" or "activating configuration 123"
        patterns = [
            r'building generation (\d+)',
            r'activating configuration (\d+)',
            r'generation (\d+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                return int(match.group(1))

        return None

    def record_deployment(
        self,
        project_slug: str,
        checkout_path: Path,
        config_path: Path,
        command: str,
        result: Dict[str, Any]
    ) -> int:
        """Record system deployment in database

        Args:
            project_slug: Project slug
            checkout_path: Path to project checkout
            config_path: Path to config file used
            command: nixos-rebuild command used
            result: Result dict from run_nixos_rebuild

        Returns:
            Deployment ID
        """
        project = query_one("SELECT id FROM projects WHERE slug = ?", (project_slug,))
        if not project:
            raise SystemServiceError(f"Project not found: {project_slug}")

        deployment_id = execute("""
            INSERT INTO system_deployments (
                project_id,
                checkout_path,
                config_path,
                is_active,
                nixos_generation,
                command,
                exit_code,
                output,
                created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project['id'],
            str(checkout_path),
            str(config_path),
            1 if result['success'] else 0,  # Only mark active if successful
            result.get('nixos_generation'),
            command,
            result['exit_code'],
            result['stdout'] + "\n\n" + result['stderr'],
            getpass.getuser()
        ))

        logger.info(f"Recorded deployment {deployment_id} for {project_slug}")
        return deployment_id

    def get_active_deployment(self) -> Optional[Dict[str, Any]]:
        """Get currently active system deployment"""
        return query_one("""
            SELECT
                sd.id,
                sd.deployed_at,
                sd.checkout_path,
                sd.config_path,
                sd.nixos_generation,
                sd.command,
                p.slug as project_slug,
                p.name as project_name
            FROM system_deployments sd
            JOIN projects p ON sd.project_id = p.id
            WHERE sd.is_active = 1
            ORDER BY sd.deployed_at DESC
            LIMIT 1
        """)

    def get_deployment_history(
        self,
        project_slug: Optional[str] = None,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get deployment history

        Args:
            project_slug: Filter by project (optional)
            limit: Maximum number of records to return
        """
        if project_slug:
            return query_all("""
                SELECT
                    sd.id,
                    sd.deployed_at,
                    sd.checkout_path,
                    sd.config_path,
                    sd.is_active,
                    sd.nixos_generation,
                    sd.command,
                    sd.exit_code,
                    sd.created_by,
                    p.slug as project_slug,
                    p.name as project_name
                FROM system_deployments sd
                JOIN projects p ON sd.project_id = p.id
                WHERE p.slug = ?
                ORDER BY sd.deployed_at DESC
                LIMIT ?
            """, (project_slug, limit))
        else:
            return query_all("""
                SELECT
                    sd.id,
                    sd.deployed_at,
                    sd.checkout_path,
                    sd.config_path,
                    sd.is_active,
                    sd.nixos_generation,
                    sd.command,
                    sd.exit_code,
                    sd.created_by,
                    p.slug as project_slug,
                    p.name as project_name
                FROM system_deployments sd
                JOIN projects p ON sd.project_id = p.id
                ORDER BY sd.deployed_at DESC
                LIMIT ?
            """, (limit,))

    def rollback_to_deployment(self, deployment_id: int) -> Dict[str, Any]:
        """Rollback to a previous deployment

        This updates the symlink to point to the previous deployment's config
        and runs nixos-rebuild switch.
        """
        deployment = query_one("""
            SELECT
                sd.checkout_path,
                sd.config_path,
                sd.nixos_generation,
                p.slug as project_slug
            FROM system_deployments sd
            JOIN projects p ON sd.project_id = p.id
            WHERE sd.id = ?
        """, (deployment_id,))

        if not deployment:
            raise SystemServiceError(f"Deployment {deployment_id} not found")

        config_path = Path(deployment['config_path'])
        if not config_path.exists():
            raise SystemServiceError(f"Config file no longer exists: {config_path}")

        # Update symlink
        self.update_system_symlink(config_path)

        # Rebuild system
        flake_path = config_path.parent if config_path.name == "flake.nix" else None
        result = self.run_nixos_rebuild("switch", flake_path=flake_path)

        if result['success']:
            # Record as new deployment
            self.record_deployment(
                deployment['project_slug'],
                Path(deployment['checkout_path']),
                config_path,
                'switch (rollback)',
                result
            )

        return result

    def test_system(self, project_slug: str, dry_run: bool = False) -> Dict[str, Any]:
        """Test system configuration without activating

        This is the safe way to test changes before committing to them.
        Uses 'nixos-rebuild test' which applies but doesn't add to boot.
        """
        checkout_path = self.get_project_checkout_path(project_slug)
        if not checkout_path:
            raise SystemServiceError(
                f"Could not find checkout for {project_slug}. "
                f"Expected at ~/.config/templedb/checkouts/{project_slug}"
            )

        config_path = self.get_config_file_path(checkout_path)
        if not config_path:
            raise SystemServiceError(
                f"No flake.nix or configuration.nix found in {checkout_path}"
            )

        # Update symlink
        self.update_system_symlink(config_path, dry_run=dry_run)

        # Run test
        flake_path = checkout_path if config_path.name == "flake.nix" else None
        result = self.run_nixos_rebuild("test", flake_path=flake_path, dry_run=dry_run)

        if not dry_run and result['success']:
            self.record_deployment(project_slug, checkout_path, config_path, 'test', result)

        return result

    def switch_system(self, project_slug: str, dry_run: bool = False, with_home_manager: bool = False) -> Dict[str, Any]:
        """Switch to system configuration (permanent)

        This activates the configuration and adds it to boot menu.
        Use test_system() first to verify changes.

        Args:
            project_slug: Project slug
            dry_run: If True, only show what would be done
            with_home_manager: If True, also rebuild home-manager after NixOS

        Returns:
            Dict with rebuild results including home-manager if applicable
        """
        checkout_path = self.get_project_checkout_path(project_slug)
        if not checkout_path:
            raise SystemServiceError(
                f"Could not find checkout for {project_slug}. "
                f"Expected at ~/.config/templedb/checkouts/{project_slug}"
            )

        config_path = self.get_config_file_path(checkout_path)
        if not config_path:
            raise SystemServiceError(
                f"No flake.nix or configuration.nix found in {checkout_path}"
            )

        # Update symlink
        self.update_system_symlink(config_path, dry_run=dry_run)

        # Run switch
        flake_path = checkout_path if config_path.name == "flake.nix" else None
        result = self.run_nixos_rebuild("switch", flake_path=flake_path, dry_run=dry_run)

        # If home-manager rebuild requested and nixos-rebuild succeeded
        if with_home_manager and result['success'] and not dry_run:
            logger.info("Rebuilding home-manager configuration...")
            hm_result = self._rebuild_home_manager(checkout_path)
            result['home_manager'] = hm_result

        if not dry_run and result['success']:
            self.record_deployment(project_slug, checkout_path, config_path, 'switch', result)

        return result

    def _rebuild_home_manager(self, flake_path: Path) -> Dict[str, Any]:
        """Rebuild home-manager configuration from NixOS flake

        Args:
            flake_path: Path to flake directory

        Returns:
            Dict with home-manager rebuild results
        """
        try:
            # Get configuration from database or auto-detect
            flake_output = self.get_system_config('nixos.flake_output')
            if not flake_output:
                import socket
                flake_output = socket.gethostname()
                logger.info(f"Auto-detected flake output from hostname: {flake_output}")

            username = self.get_system_config('nixos.username')
            if not username:
                username = getpass.getuser()
                logger.info(f"Auto-detected username: {username}")

            # Build activation package
            build_path = f"{flake_path}#nixosConfigurations.{flake_output}.config.home-manager.users.{username}.home.activationPackage"

            print(f"  Building home-manager activation package...")
            build_result = subprocess.run(
                ["nix", "build", build_path, "--out-link", "/tmp/hm-activate"],
                capture_output=True,
                text=True,
                timeout=600  # 10 minute timeout
            )

            if build_result.returncode != 0:
                logger.warning(f"home-manager build failed: {build_result.stderr}")
                return {
                    'success': False,
                    'exit_code': build_result.returncode,
                    'stdout': build_result.stdout,
                    'stderr': build_result.stderr,
                    'generation': None
                }

            # Activate the generation
            print(f"  Activating home-manager generation...")
            activate_result = subprocess.run(
                ["/tmp/hm-activate/activate"],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )

            # Extract generation number from activation output
            generation = self._extract_hm_generation(activate_result.stdout)

            success = activate_result.returncode == 0
            if success:
                print(f"  ✅ home-manager activated (generation {generation})")
            else:
                print(f"  ❌ home-manager activation failed")

            return {
                'success': success,
                'exit_code': activate_result.returncode,
                'stdout': activate_result.stdout,
                'stderr': activate_result.stderr,
                'generation': generation
            }

        except subprocess.TimeoutExpired:
            return {
                'success': False,
                'error': 'home-manager rebuild timed out',
                'generation': None
            }
        except Exception as e:
            logger.error(f"home-manager rebuild failed: {e}", exc_info=True)
            return {
                'success': False,
                'error': str(e),
                'generation': None
            }

    def _extract_hm_generation(self, output: str) -> Optional[int]:
        """Extract home-manager generation number from output"""
        import re
        # Look for "Creating new profile generation X" or "generation X"
        patterns = [
            r'profile generation (\d+)',
            r'generation (\d+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                return int(match.group(1))

        return None

    def set_project_type(self, project_slug: str, project_type: str) -> None:
        """Set project type for a project

        Args:
            project_slug: Project slug
            project_type: One of 'regular', 'nixos-config', 'service', 'library'
        """
        valid_types = ['regular', 'nixos-config', 'service', 'library']
        if project_type not in valid_types:
            raise SystemServiceError(
                f"Invalid project type: {project_type}. Must be one of {valid_types}"
            )

        execute("""
            UPDATE projects
            SET project_type = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE slug = ?
        """, (project_type, project_slug))

        logger.info(f"Set project {project_slug} type to {project_type}")

    def get_system_config(self, key: str) -> Optional[str]:
        """Get system configuration value from database

        Args:
            key: Configuration key (e.g., 'nixos.flake_output')

        Returns:
            Configuration value or None if not set/empty
        """
        result = query_one("SELECT value FROM system_config WHERE key = ?", (key,))
        if result and result['value']:
            return result['value']
        return None

    def set_system_config(self, key: str, value: str) -> None:
        """Set system configuration value in database

        Args:
            key: Configuration key
            value: Configuration value
        """
        execute("""
            INSERT OR REPLACE INTO system_config (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
        """, (key, value))
        logger.info(f"Set system config {key} = {value}")

    def list_system_config(self) -> List[Dict[str, Any]]:
        """List all system configuration values"""
        return query_all("""
            SELECT key, value, description, updated_at
            FROM system_config
            ORDER BY key
        """)
