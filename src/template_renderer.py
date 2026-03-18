#!/usr/bin/env python3
"""
Template rendering for TempleDB configuration files

Renders Nix configuration templates by substituting values from system_config table.
"""

import re
from pathlib import Path
from typing import Dict, Any
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

    def get_template_vars(self, template_name: str) -> Dict[str, str]:
        """Get all template variables for a given template

        Args:
            template_name: Name of the template (e.g., 'woofs')

        Returns:
            Dict of variable name to value
        """
        # Get all config keys for this template
        prefix = f"{template_name}."
        configs = query_all(
            "SELECT key, value FROM system_config WHERE key LIKE ?",
            (f"{prefix}%",)
        )

        # Build variable map
        vars_map = {}

        for config in configs:
            key = config['key']
            value = config['value']

            # Convert key to template variable name
            # e.g., "woofs.enable" -> "WOOFS_ENABLE"
            var_name = key.replace('.', '_').upper()
            vars_map[var_name] = value

        return vars_map

    def render_template(self, template_path: Path, output_path: Path,
                       extra_vars: Dict[str, str] = None) -> bool:
        """Render a template file with values from database

        Args:
            template_path: Path to template file (*.template)
            output_path: Path to write rendered output
            extra_vars: Additional variables to substitute

        Returns:
            True if successful
        """
        # Read template
        template_content = template_path.read_text()

        # Extract template name from path
        # e.g., "woofs/config.nix.template" -> "woofs"
        template_name = template_path.parent.name

        # Get variables from database
        vars_map = self.get_template_vars(template_name)

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

    def render_project_templates(self, project_slug: str, checkout_path: Path) -> int:
        """Render all templates for a project

        Args:
            project_slug: Project slug (e.g., 'system_config')
            checkout_path: Path to project checkout

        Returns:
            Number of templates rendered
        """
        count = 0

        # Find all .template files
        template_files = list(checkout_path.rglob("*.template"))

        for template_path in template_files:
            # Determine output path (remove .template extension)
            output_path = template_path.parent / template_path.stem

            print(f"  Rendering: {template_path.relative_to(checkout_path)}")
            print(f"         to: {output_path.relative_to(checkout_path)}")

            self.render_template(template_path, output_path)
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
