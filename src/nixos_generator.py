#!/usr/bin/env python3
"""
NixOS Configuration Generator from TempleDB

Generates NixOS modules from TempleDB projects, including:
- Cathedral package imports
- System packages based on detected dependencies
- Environment variables
- Secrets integration (sops-nix)
- Home Manager configurations
"""

import os
import sys
import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from nix_env_generator import NixEnvGenerator


def get_git_server_url(db_path: Optional[str] = None) -> str:
    """Get git server URL from system config"""
    if db_path is None:
        db_path = os.path.expanduser('~/.local/share/templedb/templedb.sqlite')

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    result = conn.execute(
        "SELECT value FROM system_config WHERE key = ?",
        ('git_server.url',)
    ).fetchone()

    conn.close()

    return result['value'] if result else 'http://localhost:9418'


@dataclass
class NixOSConfig:
    """Represents a generated NixOS configuration"""
    project_slug: str
    system_packages: List[str] = field(default_factory=list)
    home_packages: List[str] = field(default_factory=list)
    environment_vars: Dict[str, str] = field(default_factory=dict)
    secrets: List[Dict[str, str]] = field(default_factory=list)
    cathedral_path: Optional[str] = None
    nix_env_name: Optional[str] = None
    managed_packages: List[Dict[str, str]] = field(default_factory=list)


class NixOSGenerator:
    """Generate NixOS modules from TempleDB"""

    # Mapping of file types to Nix packages
    FILE_TYPE_TO_PACKAGE = {
        # Languages
        'python': [],
        'python_script': [],
        'javascript': ['nodejs_20'],
        'typescript': ['nodejs_20', 'nodePackages.typescript'],
        'rust': ['rustc', 'cargo'],
        'go': ['go'],
        'c': ['gcc', 'gnumake'],
        'cpp': ['gcc', 'gnumake', 'cmake'],
        'java': ['jdk'],
        'ruby': ['ruby'],
        'php': ['php'],
        'elixir': ['elixir'],
        'haskell': ['ghc'],

        # Build tools
        'makefile': ['gnumake'],
        'cmake': ['cmake'],
        'dockerfile': ['docker'],

        # Config formats
        'yaml': ['yq-go'],
        'json': ['jq'],
        'toml': ['remarshal'],

        # Databases
        'sql': ['sqlite'],
        'sql_migration': ['sqlite'],

        # Web
        'html': [],
        'css': [],
        'markdown': ['pandoc'],
    }

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path.home() / ".local" / "share" / "templedb" / "templedb.sqlite"
        self.conn = None
        self.nix_env_gen = None

    def __enter__(self):
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.nix_env_gen = NixEnvGenerator(str(self.db_path))
        self.nix_env_gen.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.nix_env_gen:
            self.nix_env_gen.__exit__(exc_type, exc_val, exc_tb)
        if self.conn:
            self.conn.close()

    def get_project_file_types(self, project_slug: str) -> Dict[str, int]:
        """Get file type distribution for a project"""
        cursor = self.conn.cursor()

        rows = cursor.execute("""
            SELECT type_name, COUNT(*) as count
            FROM files_with_types_view
            WHERE project_slug = ?
            GROUP BY type_name
            ORDER BY count DESC
        """, (project_slug,)).fetchall()

        return {row['type_name']: row['count'] for row in rows}

    def detect_system_packages(self, file_types: Dict[str, int]) -> Set[str]:
        """Detect required system packages from file types"""
        packages = set()

        # Add packages based on file types
        for file_type, count in file_types.items():
            if file_type in self.FILE_TYPE_TO_PACKAGE:
                packages.update(self.FILE_TYPE_TO_PACKAGE[file_type])

        # Always include common tools
        packages.update(['git', 'curl', 'wget', 'jq', 'vim'])

        return packages

    def get_project_env_vars(self, project_slug: str) -> Dict[str, str]:
        """Get environment variables for a project"""
        cursor = self.conn.cursor()

        # Get project ID
        row = cursor.execute(
            "SELECT id FROM projects WHERE slug = ?",
            (project_slug,)
        ).fetchone()

        if not row:
            return {}

        project_id = row['id']

        # Get environment variables
        rows = cursor.execute("""
            SELECT var_name, var_value
            FROM environment_variables
            WHERE scope_type = 'project' AND scope_id = ?
            ORDER BY var_name
        """, (project_id,)).fetchall()

        return {row['var_name']: row['var_value'] for row in rows}

    def get_project_secrets(self, project_slug: str) -> List[Dict[str, str]]:
        """Get secrets metadata for a project (not the actual secret values)"""
        cursor = self.conn.cursor()

        try:
            rows = cursor.execute("""
                SELECT
                    s.key_name,
                    s.description,
                    s.profile
                FROM secrets s
                JOIN projects p ON s.project_id = p.id
                WHERE p.slug = ? AND s.is_active = 1
                ORDER BY s.key_name
            """, (project_slug,)).fetchall()

            return [dict(row) for row in rows]
        except sqlite3.OperationalError:
            # Secrets table doesn't exist yet
            return []

    def get_managed_packages(self, scope: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Get managed packages that should be included in NixOS configuration.

        Args:
            scope: Filter by install_scope ('system' or 'user'). None returns all.

        Returns:
            List of package dictionaries
        """
        cursor = self.conn.cursor()

        try:
            if scope:
                rows = cursor.execute("""
                    SELECT
                        project_slug,
                        project_name,
                        git_path,
                        package_type,
                        install_scope,
                        flake_uri,
                        package_name,
                        version
                    FROM nixos_managed_packages_view
                    WHERE enabled = 1 AND install_scope = ?
                    ORDER BY package_name
                """, (scope,)).fetchall()
            else:
                rows = cursor.execute("""
                    SELECT
                        project_slug,
                        project_name,
                        git_path,
                        package_type,
                        install_scope,
                        flake_uri,
                        package_name,
                        version
                    FROM nixos_managed_packages_view
                    WHERE enabled = 1
                    ORDER BY install_scope, package_name
                """).fetchall()

            return [dict(row) for row in rows]
        except sqlite3.OperationalError:
            # Table doesn't exist yet
            return []

    def generate_config(self, project_slug: str,
                       cathedral_path: Optional[str] = None,
                       include_home_manager: bool = True,
                       include_templedb: bool = True,
                       include_managed_packages: bool = True) -> NixOSConfig:
        """Generate NixOS configuration for a project"""

        # Get file types for dependency detection
        file_types = self.get_project_file_types(project_slug)

        # Detect required packages
        all_packages = self.detect_system_packages(file_types)

        # Split into system vs user packages
        # System-level: compilers, databases, system services
        system_level = {'postgresql', 'docker', 'gcc', 'rustc', 'go'}
        system_packages = sorted([p for p in all_packages if any(s in p for s in system_level)])

        # User-level: development tools, language packages
        home_packages = sorted([p for p in all_packages if p not in system_packages])

        # Note: TempleDB is added via managed packages if available, not here
        # The old code that added 'templedb' as a regular package is removed
        # because it should come from the flake input instead

        # Add managed packages (CLI tools installed via deploy-nix)
        if include_managed_packages:
            managed_pkgs = self.get_managed_packages()
            for pkg in managed_pkgs:
                # Get flake URI (defaults to local path if not specified)
                flake_uri = pkg.get('flake_uri') or f"path:{pkg['git_path']}"
                pkg_ref = f"inputs.{pkg['package_name']}.packages.${{pkgs.system}}.default"

                if pkg['install_scope'] == 'system':
                    if pkg_ref not in system_packages:
                        system_packages.append(pkg_ref)
                else:  # user scope
                    if pkg_ref not in home_packages:
                        home_packages.append(pkg_ref)

        # Get environment variables
        env_vars = self.get_project_env_vars(project_slug)

        # Get secrets metadata
        secrets = self.get_project_secrets(project_slug)

        # Check for Nix environment
        nix_env = self.nix_env_gen.get_environment(project_slug, 'dev')
        nix_env_name = 'dev' if nix_env else None

        config = NixOSConfig(
            project_slug=project_slug,
            system_packages=system_packages,
            home_packages=home_packages,
            environment_vars=env_vars,
            secrets=secrets,
            cathedral_path=cathedral_path,
            nix_env_name=nix_env_name
        )

        # Store managed package metadata in the config for flake inputs generation
        config.managed_packages = self.get_managed_packages() if include_managed_packages else []

        return config

    def generate_nix_module(self, config: NixOSConfig) -> str:
        """Generate a NixOS module from configuration"""

        module = f'''# NixOS module for {config.project_slug}
# Generated by TempleDB
# This module provides system packages, environment variables, and secrets
# for the {config.project_slug} project

{{ config, pkgs, lib, ... }}:

{{
  config = {{
'''

        # System packages
        if config.system_packages:
            module += f'''    # System-level packages for {config.project_slug}
    environment.systemPackages = with pkgs; [
      {self._format_package_list(config.system_packages, indent=6)}
    ];

'''

        # Environment variables (system-wide)
        if config.environment_vars:
            module += f'''    # System environment variables
    environment.variables = {{
'''
            for key, value in sorted(config.environment_vars.items()):
                # Escape special characters
                escaped_value = value.replace('"', '\\"').replace('$', '\\$')
                module += f'      {key} = "{escaped_value}";\n'

            module += '    };\n\n'

        # Secrets (sops-nix integration)
        if config.secrets:
            module += f'''    # Secrets management (requires sops-nix)
    # You need to:
    # 1. Add sops-nix to your flake inputs
    # 2. Create secrets.yaml with age encryption
    # 3. Configure sops.defaultSopsFile

    # sops.secrets = {{
'''
            for secret in config.secrets:
                key = secret['key_name']
                desc = secret.get('description', '')
                profile = secret.get('profile', 'default')

                comment = f"# {desc}" if desc else ""
                module += f'    #   "{key}" = {{ }}; {comment}\n'

            module += '    # };\n\n'

        # Cathedral package integration
        if config.cathedral_path:
            module += f'''    # Cathedral package deployment
    # The {config.project_slug} project is exported as a Cathedral package
    # You can import it and build a derivation from it

    # Example:
    # let
    #   cathedralPkg = import {config.cathedral_path} {{ inherit pkgs; }};
    # in {{
    #   environment.systemPackages = [ cathedralPkg ];
    # }}

'''

        module += '  };\n}\n'

        return module

    def generate_home_manager_module(self, config: NixOSConfig) -> str:
        """Generate a Home Manager module from configuration"""

        # Separate regular nixpkgs packages from flake input packages
        regular_packages = []
        flake_packages = []
        flake_inputs = set()

        for pkg in config.home_packages:
            if pkg.startswith('inputs.'):
                flake_packages.append(pkg)
                # Extract flake input name (e.g., 'bza' from 'inputs.bza.packages...')
                input_name = pkg.split('.')[1]
                flake_inputs.add(input_name)
            else:
                regular_packages.append(pkg)

        # Build function arguments - include flake inputs
        if flake_inputs:
            args = f"{{ config, pkgs, lib, {', '.join(sorted(flake_inputs))}, ... }}:"
        else:
            args = "{ config, pkgs, lib, ... }:"

        module = f'''# Home Manager module for {config.project_slug}
# Generated by TempleDB
# This module provides user-level packages and configurations

{args}

{{
  # User-level packages for {config.project_slug} development
  home.packages = with pkgs; [
    {self._format_package_list(regular_packages, indent=4)}
  ]'''

        # Add flake packages separately (using the function arguments, not inputs.)
        if flake_packages:
            module += ' ++ [\n'
            module += '    # TempleDB-managed flake packages\n'
            for pkg in flake_packages:
                # Convert inputs.foo.packages.${pkgs.system}.default to foo.packages.${pkgs.system}.default
                pkg_without_inputs = pkg.replace('inputs.', '', 1)
                module += f'    {pkg_without_inputs}\n'
            module += '  ]'

        module += ';\n\n'

        # Environment variables (user-level)
        if config.environment_vars:
            module += f'''  # User environment variables
  home.sessionVariables = {{
'''
            for key, value in sorted(config.environment_vars.items()):
                escaped_value = value.replace('"', '\\"').replace('$', '\\$')
                module += f'    {key} = "{escaped_value}";\n'

            module += '  };\n\n'

        # Project-specific shell initialization
        module += f'''  # Project-specific shell setup
  programs.bash.initExtra = ''
    # {config.project_slug} project shortcuts
    alias tcd-{config.project_slug}='cd $(tdb deploy path {config.project_slug})'
  '';

  programs.zsh.initExtra = ''
    # {config.project_slug} project shortcuts
    alias tcd-{config.project_slug}='cd $(tdb deploy path {config.project_slug})'
  '';
'''

        module += '}\n'

        return module

    def _format_package_list(self, packages: List[str], indent: int = 0) -> str:
        """Format package list with proper indentation"""
        if not packages:
            return ''

        indent_str = ' ' * indent
        return '\n'.join(f'{indent_str}{pkg}' for pkg in packages)

    def export_cathedral_with_nix(self, project_slug: str, output_dir: Path) -> Tuple[Path, Path]:
        """Export project as Cathedral package with NixOS module"""
        from cathedral_export import export_project

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Export Cathedral package
        print(f"📦 Exporting {project_slug} as Cathedral package...")
        success = export_project(
            slug=project_slug,
            output_dir=output_dir,
            compress=True,
            include_files=True,
            include_vcs=True,
            include_environments=True
        )

        if not success:
            raise Exception(f"Failed to export {project_slug}")

        cathedral_path = output_dir / f"{project_slug}.cathedral.tar.zst"

        # Generate NixOS modules
        print(f"🔧 Generating NixOS modules...")
        config = self.generate_config(project_slug, str(cathedral_path))

        # Write NixOS module
        nixos_module_path = output_dir / f"{project_slug}-nixos.nix"
        nixos_module = self.generate_nix_module(config)
        nixos_module_path.write_text(nixos_module)
        print(f"  ✓ NixOS module: {nixos_module_path}")

        # Write Home Manager module
        hm_module_path = output_dir / f"{project_slug}-home.nix"
        hm_module = self.generate_home_manager_module(config)
        hm_module_path.write_text(hm_module)
        print(f"  ✓ Home Manager module: {hm_module_path}")

        # Write integration guide
        guide_path = output_dir / f"{project_slug}-INTEGRATION.md"
        guide = self._generate_integration_guide(config, cathedral_path, nixos_module_path, hm_module_path)
        guide_path.write_text(guide)
        print(f"  ✓ Integration guide: {guide_path}")

        return nixos_module_path, hm_module_path

    def _generate_integration_guide(self, config: NixOSConfig,
                                    cathedral_path: Path,
                                    nixos_module_path: Path,
                                    hm_module_path: Path) -> str:
        """Generate integration guide for NixOS"""

        has_templedb = 'templedb' in config.home_packages
        git_server_url = get_git_server_url()

        templedb_flake_section = f'''
    # TempleDB itself (for CLI access everywhere)
    # Option 1: Use local git server (requires: tdb gitserver start)
    templedb.url = "git+{git_server_url}/templedb";
    # Option 2: Use GitHub release
    # templedb.url = "github:yourusername/templedb";
''' if has_templedb else ''

        templedb_package_section = '''
        # TempleDB is included in the generated modules
        # You can access it system-wide after rebuild
        specialArgs = { inherit inputs; };
''' if has_templedb else ''

        return f'''# Integrating {config.project_slug} with NixOS

This guide shows how to integrate the {config.project_slug} project into your NixOS configuration.

## What Was Generated

1. **Cathedral Package**: `{cathedral_path.name}`
   - Self-contained project archive with all files and metadata
   - Can be distributed and imported on any NixOS system

2. **NixOS Module**: `{nixos_module_path.name}`
   - System-level packages: {len(config.system_packages)} packages
   - Environment variables: {len(config.environment_vars)} variables
   - Secrets: {len(config.secrets)} secret keys (requires sops-nix)

3. **Home Manager Module**: `{hm_module_path.name}`
   - User-level development packages: {len(config.home_packages)} packages{' (includes TempleDB CLI)' if has_templedb else ''}
   - Shell aliases and shortcuts

## Integration Steps

### Step 1: Add to Your Flake

Edit your `flake.nix`:

```nix
{{
  inputs = {{
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    home-manager.url = "github:nix-community/home-manager";
{templedb_flake_section}
    # Optional: sops-nix for secrets
    sops-nix.url = "github:Mic92/sops-nix";
  }};

  outputs = {{ self, nixpkgs, home-manager{', templedb' if has_templedb else ''}, ... }}@inputs: {{
    nixosConfigurations.yourhostname = nixpkgs.lib.nixosSystem {{
      system = "x86_64-linux";{templedb_package_section}
      modules = [
        ./configuration.nix

        # Import {config.project_slug} NixOS module
        ./{nixos_module_path.name}

        # Optional: sops-nix for secrets
        # inputs.sops-nix.nixosModules.sops

        home-manager.nixosModules.home-manager
        {{
          home-manager.users.youruser = {{ config, pkgs, ... }}: {{
            imports = [ ./{hm_module_path.name} ];

            # If using TempleDB from flake:
            {'home.packages = [ inputs.templedb.packages.${pkgs.system}.default ];' if has_templedb else '# home.packages = [];'}
          }};
        }}
      ];
    }};
  }};
}}
```

### Step 2: Copy Files to Your NixOS Config

```bash
# Copy generated modules
cp {nixos_module_path.name} /etc/nixos/
cp {hm_module_path.name} /etc/nixos/

# Optional: Copy Cathedral package for local builds
cp {cathedral_path.name} /etc/nixos/cathedral-packages/
```

### Step 3: Configure Secrets (Optional)

If you're using secrets, set up sops-nix:

```bash
# Install age for encryption
nix-shell -p age

# Generate age key
age-keygen -o ~/.config/sops/age/keys.txt

# Create secrets.yaml
cat > secrets.yaml <<EOF
# Secrets for {config.project_slug}
{chr(10).join(f"{s['key_name']}: ENC[AES256_GCM,data:...,tag:...]" for s in config.secrets[:3])}
EOF

# Encrypt with age
sops -e -i secrets.yaml
```

Add to your NixOS config:

```nix
{{
  sops.defaultSopsFile = ./secrets.yaml;
  sops.age.keyFile = "/home/youruser/.config/sops/age/keys.txt";

  # Uncomment the secrets in {nixos_module_path.name}
}}
```

### Step 4: Rebuild

```bash
# Test the configuration
sudo nixos-rebuild test

# Apply permanently
sudo nixos-rebuild switch
```

### Step 5: Using TempleDB

{'After rebuilding, TempleDB will be available system-wide:' if has_templedb else 'If you want TempleDB available system-wide, add it to your configuration:'}

```bash
{'# TempleDB CLI' if has_templedb else '# Install TempleDB separately if needed'}
{'templedb project list' if has_templedb else '# nix profile install github:yourusername/templedb'}
{'tdb deployed' if has_templedb else ''}

{'# Jump to any deployed project' if has_templedb else ''}
{'cd $(templedb deploy path {config.project_slug})' if has_templedb else ''}
```

## Detected Dependencies

### System Packages ({len(config.system_packages)})
{chr(10).join(f"- {pkg}" for pkg in config.system_packages)}

### Home Packages ({len(config.home_packages)})
{chr(10).join(f"- {pkg}" for pkg in config.home_packages)}

## Environment Variables

{chr(10).join(f"- `{k}`: {v[:50]}..." if len(v) > 50 else f"- `{k}`: {v}" for k, v in list(config.environment_vars.items())[:5])}

## Shell Shortcuts

After integrating, you'll have:

```bash
# Jump to deployed {config.project_slug}
tcd-{config.project_slug}
```

## Next Steps

1. **Test the modules**: Run `nixos-rebuild test` to verify everything works
2. **Customize packages**: Edit the generated .nix files to add/remove packages
3. **Set up secrets**: If using secrets, configure sops-nix
4. **Deploy**: Run `nixos-rebuild switch` to apply

## Troubleshooting

### Packages not found
- Check that you're using nixos-unstable or recent nixpkgs
- Some packages may have different names - search with `nix search`

### Secrets not decrypting
- Verify age key is in the correct location
- Check sops.age.keyFile path in your config
- Ensure secrets.yaml is encrypted with your age public key

### Build Cathedral package
To build a derivation from the Cathedral package:

```nix
let
  cathedralImport = import ./cathedral-import.nix;
  {config.project_slug}Pkg = cathedralImport {{
    src = ./{cathedral_path.name};
    inherit pkgs;
  }};
in {{
  environment.systemPackages = [ {config.project_slug}Pkg ];
}}
```

## More Information

- TempleDB: Database-native development environment manager
- Cathedral: Portable project packaging format
- NixOS: Declarative Linux distribution
- Home Manager: User environment management for Nix

Generated by TempleDB NixOS Generator
'''


def main():
    """CLI for NixOS generator"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Generate NixOS configurations from TempleDB projects'
    )
    parser.add_argument('command', choices=['generate', 'export'],
                       help='generate: Create modules only, export: Create modules + Cathedral package')
    parser.add_argument('project', help='Project slug')
    parser.add_argument('-o', '--output', type=Path, default=Path('/tmp/nixos-gen'),
                       help='Output directory (default: /tmp/nixos-gen)')
    parser.add_argument('--cathedral-path', help='Path to existing Cathedral package')
    parser.add_argument('--no-home-manager', action='store_true',
                       help='Skip Home Manager module generation')

    args = parser.parse_args()

    with NixOSGenerator() as gen:
        if args.command == 'generate':
            # Generate modules only
            config = gen.generate_config(
                args.project,
                cathedral_path=args.cathedral_path,
                include_home_manager=not args.no_home_manager
            )

            args.output.mkdir(parents=True, exist_ok=True)

            # Write modules
            nixos_path = args.output / f"{args.project}-nixos.nix"
            nixos_path.write_text(gen.generate_nix_module(config))
            print(f"✓ Generated NixOS module: {nixos_path}")

            if not args.no_home_manager:
                hm_path = args.output / f"{args.project}-home.nix"
                hm_path.write_text(gen.generate_home_manager_module(config))
                print(f"✓ Generated Home Manager module: {hm_path}")

        elif args.command == 'export':
            # Export Cathedral + generate modules
            nixos_path, hm_path = gen.export_cathedral_with_nix(
                args.project,
                args.output
            )

            print(f"\n✅ Export complete!")
            print(f"\n📁 Output directory: {args.output}")
            print(f"\n🔧 Next steps:")
            print(f"   1. Review the integration guide: {args.output}/{args.project}-INTEGRATION.md")
            print(f"   2. Copy modules to /etc/nixos/")
            print(f"   3. Import in your flake.nix")
            print(f"   4. Run: sudo nixos-rebuild test")


if __name__ == '__main__':
    main()
