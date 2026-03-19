#!/usr/bin/env python3
"""
Template rendering for TempleDB configuration files

Renders Nix configuration templates by substituting values from system_config table.
Supports hierarchical configuration with scope precedence:
  Machine > Network > Project > System
"""

import re
from pathlib import Path
from typing import Dict, Any, Optional
from db_utils import query_one, query_all


class TemplateRenderer:
    """Renders configuration templates with values from database"""

    def __init__(self):
        pass

    def get_config_value(self, key: str, default: str = "") -> str:
        """Get a value from system_config table"""
        result = query_one(
            "SELECT value FROM system_config WHERE key = ?",
            (key,)
        )
        return result['value'] if result else default

    def get_template_vars(self, template_name: str, machine_name: str = None) -> Dict[str, str]:
        """Get all template variables for a given template

        Args:
            template_name: Name of the template (e.g., 'woofs')
            machine_name: Optional machine name for machine-specific config

        Returns:
            Dict of variable name to value

        Naming convention:
            - machine_name.template.var: Machine-specific value (highest priority)
            - template.var: System-wide default value
        """
        vars_map = {}

        # First, get system-wide defaults for this template
        prefix = f"{template_name}."
        system_configs = query_all(
            "SELECT key, value FROM system_config WHERE key LIKE ? AND key NOT LIKE ?",
            (f"{prefix}%", "%.%.%")  # Exclude machine-specific (has 2+ dots)
        )

        for config in system_configs:
            key = config['key']
            value = config['value']

            # Convert key to template variable name
            # e.g., "woofs.enable" -> "WOOFS_ENABLE"
            var_name = key.replace('.', '_').upper()
            vars_map[var_name] = value

        # If machine_name provided, override with machine-specific values
        if machine_name:
            machine_prefix = f"{machine_name}.{template_name}."
            machine_configs = query_all(
                "SELECT key, value FROM system_config WHERE key LIKE ?",
                (f"{machine_prefix}%",)
            )

            for config in machine_configs:
                key = config['key']
                value = config['value']

                # Strip machine name from key for variable name
                # e.g., "web1.woofs.enable" -> "WOOFS_ENABLE"
                var_key = key[len(machine_name) + 1:]  # Remove "machine_name."
                var_name = var_key.replace('.', '_').upper()
                vars_map[var_name] = value  # Override system-wide default

        return vars_map

    def get_template_vars_scoped(
        self,
        template_name: str,
        machine_id: int = None,
        network_id: int = None,
        project_id: int = None
    ) -> Dict[str, str]:
        """Get template variables using hierarchical scope resolution

        Resolution order (highest to lowest priority):
          1. Machine-specific (scope_type='machine', scope_id=machine_id)
          2. Network-specific (scope_type='network', scope_id=network_id)
          3. Project-specific (scope_type='project', scope_id=project_id)
          4. System-wide (scope_type='system')

        Args:
            template_name: Name of the template (e.g., 'woofs')
            machine_id: Machine ID for machine-specific config
            network_id: Network ID for network-specific config
            project_id: Project ID for project-specific config

        Returns:
            Dict of variable name to value with proper scope precedence
        """
        vars_map = {}
        prefix = f"{template_name}."

        # Build hierarchical query
        # Start with system-wide, then override with more specific scopes
        scopes = []

        # System-wide (lowest priority)
        scopes.append(("system", None))

        # Project-specific
        if project_id:
            scopes.append(("project", project_id))

        # Network-specific
        if network_id:
            scopes.append(("network", network_id))

        # Machine-specific (highest priority)
        if machine_id:
            scopes.append(("machine", machine_id))

        # Query each scope in order, overriding as we go
        for scope_type, scope_id in scopes:
            if scope_id is None:
                configs = query_all("""
                    SELECT key, value
                    FROM system_config
                    WHERE key LIKE ? AND scope_type = ? AND scope_id IS NULL
                """, (f"{prefix}%", scope_type))
            else:
                configs = query_all("""
                    SELECT key, value
                    FROM system_config
                    WHERE key LIKE ? AND scope_type = ? AND scope_id = ?
                """, (f"{prefix}%", scope_type, scope_id))

            for config in configs:
                key = config['key']
                value = config['value']

                # Convert key to template variable name
                # e.g., "woofs.enable" -> "WOOFS_ENABLE"
                var_name = key.replace('.', '_').upper()
                vars_map[var_name] = value  # Override previous values

        return vars_map

    def resolve_config_value(
        self,
        key: str,
        machine_id: int = None,
        network_id: int = None,
        project_id: int = None,
        default: str = ""
    ) -> str:
        """Resolve a single config value using hierarchical scope

        Args:
            key: Config key to resolve
            machine_id: Machine ID for machine-specific config
            network_id: Network ID for network-specific config
            project_id: Project ID for project-specific config
            default: Default value if not found

        Returns:
            Resolved value or default
        """
        # Check in priority order: machine > network > project > system
        scopes = []

        if machine_id:
            scopes.append(("machine", machine_id))
        if network_id:
            scopes.append(("network", network_id))
        if project_id:
            scopes.append(("project", project_id))
        scopes.append(("system", None))

        for scope_type, scope_id in scopes:
            if scope_id is None:
                result = query_one("""
                    SELECT value FROM system_config
                    WHERE key = ? AND scope_type = ? AND scope_id IS NULL
                """, (key, scope_type))
            else:
                result = query_one("""
                    SELECT value FROM system_config
                    WHERE key = ? AND scope_type = ? AND scope_id = ?
                """, (key, scope_type, scope_id))

            if result:
                return result['value']

        return default

    def render_template(
        self,
        template_path: Path,
        output_path: Path,
        extra_vars: Dict[str, str] = None,
        machine_name: str = None,
        machine_id: int = None,
        network_id: int = None,
        project_id: int = None
    ) -> bool:
        """Render a template file with values from database

        Supports two config resolution methods:
          1. Naming convention (legacy): machine_name.template.var
          2. Scoped queries (new): machine_id, network_id, project_id

        Args:
            template_path: Path to template file (*.template)
            output_path: Path to write rendered output
            extra_vars: Additional variables to substitute
            machine_name: Optional machine name for naming convention lookups
            machine_id: Optional machine ID for scoped lookups
            network_id: Optional network ID for scoped lookups
            project_id: Optional project ID for scoped lookups

        Returns:
            True if successful
        """
        # Read template
        template_content = template_path.read_text()

        # Extract template name from path
        # e.g., "woofs/config.nix.template" -> "woofs"
        template_name = template_path.parent.name

        # Get variables from database
        # Prefer scoped lookups if machine_id provided, otherwise use naming convention
        if machine_id or network_id or project_id:
            vars_map = self.get_template_vars_scoped(
                template_name,
                machine_id=machine_id,
                network_id=network_id,
                project_id=project_id
            )
        else:
            # Fall back to naming convention
            vars_map = self.get_template_vars(template_name, machine_name=machine_name)

        # Add extra variables
        if extra_vars:
            vars_map.update(extra_vars)

        # Add computed variables
        vars_map.update(self._get_computed_vars(vars_map))

        # Substitute variables
        rendered = self._substitute_vars(template_content, vars_map)

        # Write output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered)

        return True

    def _get_computed_vars(self, vars_map: Dict[str, str]) -> Dict[str, str]:
        """Get computed variables based on other values

        For example, WOOFS_BACKUP_DIR is computed from WOOFS_SCHEDULE_FILE
        """
        computed = {}

        # Compute backup directory from schedule file
        if 'WOOFS_SCHEDULE_FILE' in vars_map:
            schedule_file = vars_map['WOOFS_SCHEDULE_FILE']
            # Get parent directory and add .woofs-backups
            from pathlib import Path
            parent = str(Path(schedule_file).parent)
            computed['WOOFS_BACKUP_DIR'] = f"{parent}/.woofs-backups"

        return computed

    def _substitute_vars(self, content: str, vars_map: Dict[str, str]) -> str:
        """Substitute {{VAR_NAME}} with values from vars_map

        Args:
            content: Template content with {{VAR}} placeholders
            vars_map: Dict of VAR -> value

        Returns:
            Rendered content
        """
        def replace_var(match):
            var_name = match.group(1)
            return vars_map.get(var_name, match.group(0))  # Keep original if not found

        # Replace {{VAR_NAME}} patterns
        return re.sub(r'\{\{([A-Z_]+)\}\}', replace_var, content)

    def render_project_templates(
        self,
        project_slug: str,
        checkout_path: Path,
        machine_name: str = None,
        machine_id: int = None,
        network_id: int = None,
        project_id: int = None
    ) -> int:
        """Render all templates for a project

        Args:
            project_slug: Project slug (e.g., 'system_config')
            checkout_path: Path to project checkout
            machine_name: Optional machine name for naming convention lookups
            machine_id: Optional machine ID for scoped lookups
            network_id: Optional network ID for scoped lookups
            project_id: Optional project ID for scoped lookups

        Returns:
            Number of templates rendered
        """
        count = 0

        # Find all .template files
        template_files = list(checkout_path.rglob("*.template"))

        for template_path in template_files:
            # Determine output path (remove .template extension)
            output_path = template_path.parent / template_path.stem

            # Build context string for logging
            context_parts = []
            if machine_name:
                context_parts.append(f"machine: {machine_name}")
            if machine_id:
                context_parts.append(f"machine_id: {machine_id}")
            if network_id:
                context_parts.append(f"network_id: {network_id}")
            if project_id:
                context_parts.append(f"project_id: {project_id}")

            context_str = f" ({', '.join(context_parts)})" if context_parts else ""

            print(f"  Rendering: {template_path.relative_to(checkout_path)}{context_str}")
            print(f"         to: {output_path.relative_to(checkout_path)}")

            self.render_template(
                template_path,
                output_path,
                machine_name=machine_name,
                machine_id=machine_id,
                network_id=network_id,
                project_id=project_id
            )
            count += 1

        return count


def main():
    """CLI for testing template rendering"""
    import sys

    if len(sys.argv) < 3:
        print("Usage: python template_renderer.py <template> <output>")
        print("Example: python template_renderer.py woofs/config.nix.template woofs/config.nix")
        return 1

    renderer = TemplateRenderer()
    template_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])

    if renderer.render_template(template_path, output_path):
        print(f"✓ Rendered {template_path} -> {output_path}")
        return 0
    else:
        print(f"✗ Failed to render template")
        return 1


if __name__ == '__main__':
    sys.exit(main())
