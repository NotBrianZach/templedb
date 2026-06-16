"""
Nix Service Analyzer
====================

Analyzes NixOS modules to extract service/daemon metadata.
"""

import json
import re
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class ServiceMetadata:
    """Metadata extracted from a NixOS service module"""
    service_name: str
    service_description: Optional[str] = None
    module_path: Optional[str] = None  # e.g., 'services.myDaemon'
    config_options: List[Dict[str, str]] = None
    systemd_service_name: Optional[str] = None
    systemd_after: List[str] = None
    systemd_requires: List[str] = None
    needs_user: bool = False
    user_name: Optional[str] = None
    needs_group: bool = False
    group_name: Optional[str] = None
    needs_state_directory: bool = False
    state_directory_path: Optional[str] = None
    opens_ports: List[int] = None
    binds_to_address: Optional[str] = None
    requires_services: List[str] = None
    requires_databases: List[str] = None

    def __post_init__(self):
        if self.config_options is None:
            self.config_options = []
        if self.systemd_after is None:
            self.systemd_after = []
        if self.systemd_requires is None:
            self.systemd_requires = []
        if self.opens_ports is None:
            self.opens_ports = []
        if self.requires_services is None:
            self.requires_services = []
        if self.requires_databases is None:
            self.requires_databases = []


class NixServiceAnalyzer:
    """Analyzes NixOS modules to extract service metadata"""

    def __init__(self, db):
        self.db = db

    def find_module_file(self, project_path: Path) -> Optional[Path]:
        """
        Find the NixOS module file in a project

        Looks for common module file names:
        - module.nix
        - flake.nix (with nixosModules output)
        - nixos-module.nix
        - Files in a nixos/ or modules/ directory
        """
        candidates = [
            project_path / "module.nix",
            project_path / "nixos-module.nix",
            project_path / "nixos" / "module.nix",
            project_path / "modules" / "default.nix",
        ]

        for candidate in candidates:
            if candidate.exists():
                return candidate

        # If no dedicated module file, check if flake.nix has inline module
        flake_path = project_path / "flake.nix"
        if flake_path.exists():
            content = flake_path.read_text()
            if "nixosModules" in content and "systemd.services" in content:
                return flake_path

        return None

    def analyze_service_module(self, project_path: Path, service_name: str) -> Optional[ServiceMetadata]:
        """
        Analyze a NixOS service module to extract metadata

        Args:
            project_path: Path to the project
            service_name: Expected service name (usually project slug)

        Returns:
            ServiceMetadata object or None if analysis fails
        """
        module_file = self.find_module_file(project_path)

        if not module_file:
            logger.warning("Could not find NixOS module file")
            return None

        logger.info(f"Analyzing module: {module_file}")

        try:
            content = module_file.read_text()
            metadata = self._parse_module_content(content, service_name)
            return metadata

        except Exception as e:
            logger.error(f"Failed to analyze service module: {e}")
            return None

    def _parse_module_content(self, content: str, service_name: str) -> ServiceMetadata:
        """
        Parse NixOS module content to extract service metadata

        This is a heuristic-based parser - not perfect but handles common patterns.
        """
        metadata = ServiceMetadata(service_name=service_name)

        # Extract module path (services.X or programs.X)
        module_path_match = re.search(r'(services|programs)\.(\w+)', content)
        if module_path_match:
            prefix = module_path_match.group(1)
            name = module_path_match.group(2)
            metadata.module_path = f"{prefix}.{name}"

        # Extract systemd service name
        systemd_match = re.search(r'systemd\.services\.(\S+)\s*=', content)
        if systemd_match:
            metadata.systemd_service_name = systemd_match.group(1)

        # Extract configuration options
        option_pattern = r'(\w+)\s*=\s*mkOption\s*\{([^}]+)\}'
        for match in re.finditer(option_pattern, content, re.DOTALL):
            option_name = match.group(1)
            option_body = match.group(2)

            # Extract type
            type_match = re.search(r'type\s*=\s*types\.(\w+)', option_body)
            option_type = type_match.group(1) if type_match else "unknown"

            # Extract default
            default_match = re.search(r'default\s*=\s*([^;]+);', option_body)
            default_value = default_match.group(1).strip() if default_match else None

            # Extract description
            desc_match = re.search(r'description\s*=\s*"([^"]+)"', option_body)
            description = desc_match.group(1) if desc_match else ""

            metadata.config_options.append({
                'name': option_name,
                'type': option_type,
                'default': default_value,
                'description': description
            })

        # Extract ports
        port_patterns = [
            r'port\s*=\s*(\d+)',
            r'mkOption.*port.*default\s*=\s*(\d+)',
            r'allowedTCPPorts.*\[([^\]]+)\]',
        ]

        for pattern in port_patterns:
            for match in re.finditer(pattern, content):
                port_str = match.group(1)
                # Extract all numbers from the match
                ports = re.findall(r'\d+', port_str)
                for port in ports:
                    port_num = int(port)
                    if 1 <= port_num <= 65535 and port_num not in metadata.opens_ports:
                        metadata.opens_ports.append(port_num)

        # Check for user creation
        if re.search(r'users\.users\.\$\{', content) or re.search(r'users\.users\.(\w+)\s*=', content):
            metadata.needs_user = True
            user_match = re.search(r'users\.users\.(\w+)', content)
            if user_match:
                metadata.user_name = user_match.group(1)
            # Also check User = in serviceConfig
            user_config_match = re.search(r'User\s*=\s*["\']?(\w+)', content)
            if user_config_match and not metadata.user_name:
                metadata.user_name = user_config_match.group(1)

        # Check for group creation
        if re.search(r'users\.groups\.', content):
            metadata.needs_group = True
            group_match = re.search(r'users\.groups\.(\w+)', content)
            if group_match:
                metadata.group_name = group_match.group(1)

        # Check for state directory
        if re.search(r'StateDirectory|dataDir|stateDir', content):
            metadata.needs_state_directory = True
            state_match = re.search(r'StateDirectory\s*=\s*"([^"]+)"', content)
            if state_match:
                metadata.state_directory_path = f"/var/lib/{state_match.group(1)}"
            else:
                # Look for dataDir default
                datadir_match = re.search(r'dataDir.*default\s*=\s*"([^"]+)"', content)
                if datadir_match:
                    metadata.state_directory_path = datadir_match.group(1)

        # Extract systemd dependencies
        after_match = re.search(r'after\s*=\s*\[([^\]]+)\]', content)
        if after_match:
            after_list = after_match.group(1)
            metadata.systemd_after = [
                s.strip(' "\'') for s in after_list.split()
                if s.strip(' "\',')
            ]

        requires_match = re.search(r'requires\s*=\s*\[([^\]]+)\]', content)
        if requires_match:
            requires_list = requires_match.group(1)
            metadata.systemd_requires = [
                s.strip(' "\'') for s in requires_list.split()
                if s.strip(' "\',')
            ]

        # Detect required databases/services
        if re.search(r'postgresql|postgres', content, re.IGNORECASE):
            if 'postgresql' not in metadata.requires_databases:
                metadata.requires_databases.append('postgresql')
            if 'postgresql.service' not in metadata.requires_services:
                metadata.requires_services.append('postgresql.service')

        if re.search(r'redis', content, re.IGNORECASE):
            if 'redis' not in metadata.requires_databases:
                metadata.requires_databases.append('redis')
            if 'redis.service' not in metadata.requires_services:
                metadata.requires_services.append('redis.service')

        if re.search(r'mysql|mariadb', content, re.IGNORECASE):
            if 'mysql' not in metadata.requires_databases:
                metadata.requires_databases.append('mysql')

        # Extract service description
        desc_match = re.search(r'description\s*=\s*"([^"]+)"', content)
        if desc_match:
            metadata.service_description = desc_match.group(1)

        return metadata

    def store_service_metadata(self, project_id: int, metadata: ServiceMetadata):
        """
        Store service metadata in database

        Args:
            project_id: The project ID
            metadata: ServiceMetadata object to store
        """
        cursor = self.db.cursor()

        try:
            # Check if metadata already exists
            cursor.execute(
                "SELECT id FROM nix_service_metadata WHERE project_id = ?",
                (project_id,)
            )
            existing = cursor.fetchone()

            if existing:
                # Update existing metadata
                cursor.execute("""
                    UPDATE nix_service_metadata
                    SET service_name = ?,
                        service_description = ?,
                        module_path = ?,
                        config_options = ?,
                        systemd_service_name = ?,
                        systemd_after = ?,
                        systemd_requires = ?,
                        needs_user = ?,
                        user_name = ?,
                        needs_group = ?,
                        group_name = ?,
                        needs_state_directory = ?,
                        state_directory_path = ?,
                        opens_ports = ?,
                        requires_services = ?,
                        requires_databases = ?,
                        updated_at = datetime('now')
                    WHERE project_id = ?
                """, (
                    metadata.service_name,
                    metadata.service_description,
                    metadata.module_path,
                    json.dumps(metadata.config_options),
                    metadata.systemd_service_name,
                    json.dumps(metadata.systemd_after),
                    json.dumps(metadata.systemd_requires),
                    metadata.needs_user,
                    metadata.user_name,
                    metadata.needs_group,
                    metadata.group_name,
                    metadata.needs_state_directory,
                    metadata.state_directory_path,
                    json.dumps(metadata.opens_ports),
                    json.dumps(metadata.requires_services),
                    json.dumps(metadata.requires_databases),
                    project_id
                ))
            else:
                # Insert new metadata
                cursor.execute("""
                    INSERT INTO nix_service_metadata
                    (project_id, service_name, service_description, module_path,
                     config_options, systemd_service_name, systemd_after,
                     systemd_requires, needs_user, user_name, needs_group,
                     group_name, needs_state_directory, state_directory_path,
                     opens_ports, requires_services, requires_databases)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    project_id,
                    metadata.service_name,
                    metadata.service_description,
                    metadata.module_path,
                    json.dumps(metadata.config_options),
                    metadata.systemd_service_name,
                    json.dumps(metadata.systemd_after),
                    json.dumps(metadata.systemd_requires),
                    metadata.needs_user,
                    metadata.user_name,
                    metadata.needs_group,
                    metadata.group_name,
                    metadata.needs_state_directory,
                    metadata.state_directory_path,
                    json.dumps(metadata.opens_ports),
                    json.dumps(metadata.requires_services),
                    json.dumps(metadata.requires_databases)
                ))

            self.db.commit()
            logger.info(f"✓ Stored service metadata for project {project_id}")

        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to store service metadata: {e}")
            raise

    def analyze_and_store(self, project_id: int, project_path: Path, service_name: str):
        """
        Analyze service module and store metadata

        Convenience method that combines analysis and storage.
        """
        metadata = self.analyze_service_module(project_path, service_name)

        if metadata:
            self.store_service_metadata(project_id, metadata)
            return metadata
        else:
            logger.warning("Could not extract service metadata")
            return None
