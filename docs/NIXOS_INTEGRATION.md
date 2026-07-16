# TempleDB NixOS Integration

This guide explains how to use TempleDB with NixOS, including:
- Installing TempleDB system-wide
- Generating NixOS modules from TempleDB projects
- Creating self-hosting configurations (TempleDB managing itself)

## Quick Start: Install TempleDB on NixOS

### Option 1: Using the Flake (Recommended)

Add to your `flake.nix`:

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    templedb.url = "github:yourusername/templedb";
  };

  outputs = { self, nixpkgs, templedb, ... }: {
    nixosConfigurations.yourhostname = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        # Option A: System-wide (for all users)
        templedb.nixosModules.default
        {
          services.templedb.enable = true;
        }

        # Option B: Per-user with Home Manager
        home-manager.nixosModules.home-manager
        {
          home-manager.users.youruser = {
            imports = [ templedb.homeManagerModules.default ];
            programs.templedb.enable = true;
          };
        }
      ];
    };
  };
}
```

### Option 2: Direct Package Install

```bash
# Try it out
nix run github:yourusername/templedb

# Install to profile
nix profile install github:yourusername/templedb

# Use in shell
nix shell github:yourusername/templedb
```

## Generating NixOS Modules from Projects

TempleDB can analyze your projects and generate complete NixOS configurations.

### Basic Usage

```bash
# Detect what would be generated
templedb nixos detect myproject

# Generate NixOS + Home Manager modules
templedb nixos generate myproject

# Full export with Cathedral package
templedb nixos export myproject -o /tmp/myproject-nixos
```

### What Gets Generated

1. **NixOS Module** (`myproject-nixos.nix`)
   - System-level packages (compilers, databases)
   - Environment variables
   - Secrets integration (commented out, requires sops-nix)

2. **Home Manager Module** (`myproject-home.nix`)
   - User-level development tools
   - Project-specific shell aliases
   - direnv integration

3. **Cathedral Package** (`myproject.cathedral.tar.zst`)
   - Complete project archive
   - Can be distributed and deployed anywhere

4. **Integration Guide** (`myproject-INTEGRATION.md`)
   - Step-by-step setup instructions
   - Example configurations

### Advanced: Include TempleDB Itself

By default, generated modules include TempleDB as a dependency, creating a self-hosting setup:

```bash
# Include TempleDB (default)
templedb nixos generate myproject --include-templedb

# Exclude TempleDB
templedb nixos generate myproject --no-templedb
```

This means:
- Your NixOS system will have TempleDB CLI available
- You can manage other projects using the same TempleDB instance
- TempleDB can update itself through NixOS

## Self-Hosting Example

Export TempleDB's own configuration:

```bash
# Make sure templedb project is tracked
templedb project list | grep templedb

# Generate NixOS modules for TempleDB itself
templedb nixos export templedb -o /tmp/templedb-self-host
```

This creates a complete NixOS configuration that:
1. Installs TempleDB
2. Includes all its Python dependencies
3. Sets up the database path
4. Configures age for secret management

### Using the Self-Hosted Configuration

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    # Option 1: Use TempleDB git server (requires: tdb gitserver start)
    templedb-config.url = "git+http://localhost:9418/templedb-self-host";
    # Option 2: Use local path (development)
    # templedb-config.url = "path:/tmp/templedb-self-host";
  };

  outputs = { self, nixpkgs, templedb-config, ... }: {
    nixosConfigurations.yourhostname = nixpkgs.lib.nixosSystem {
      modules = [
        ./configuration.nix
        templedb-config.nixosModules.default
      ];
    };
  };
}
```

## Dependency Detection

TempleDB automatically detects dependencies based on file types:

| File Type | Detected Packages |
|-----------|-------------------|
| Python | `python311`, `python311Packages.pip` |
| JavaScript/TypeScript | `nodejs_20`, `nodePackages.typescript` |
| Rust | `rustc`, `cargo` |
| Go | `go` |
| SQL | `sqlite`, `postgresql` (based on context) |
| Docker | `docker` |
| Nix | Recursively includes nix-shell dependencies |

### Custom Package Mapping

You can customize package detection by editing `src/nixos_generator.py`:

```python
FILE_TYPE_TO_PACKAGE = {
    'my_custom_type': ['custom-package', 'another-package'],
    # ...
}
```

## Environment Variables

Environment variables stored in TempleDB are automatically included:

```bash
# Set environment variable
templedb env set myproject API_KEY "secret-value"

# Generated module will include:
# environment.variables = {
#   API_KEY = "secret-value";
# };
```

**Security Note:** Only non-sensitive environment variables should be stored this way. For secrets, use TempleDB's age-encrypted secret management.

## Secrets Management

TempleDB integrates with sops-nix for secure secret management:

### 1. Store Secrets in TempleDB

```bash
# Initialize secrets
templedb env secret init myproject --age-recipient $(cat ~/.config/sops/age/keys.txt | age-keygen -y)

# Edit secrets (opens $EDITOR)
templedb env secret edit myproject
```

### 2. Generated Modules Include Placeholders

```nix
# In myproject-nixos.nix:
# sops.secrets = {
#   "DATABASE_PASSWORD" = { };
#   "API_KEY" = { };
# };
```

### 3. Set Up sops-nix

```nix
{
  inputs.sops-nix.url = "github:Mic92/sops-nix";

  outputs = { ... }@inputs: {
    nixosConfigurations.yourhostname = nixpkgs.lib.nixosSystem {
      modules = [
        inputs.sops-nix.nixosModules.sops
        {
          sops.defaultSopsFile = ./secrets.yaml;
          sops.age.keyFile = "/home/youruser/.config/sops/age/keys.txt";

          # Uncomment secrets in myproject-nixos.nix
          sops.secrets."DATABASE_PASSWORD" = { };
        }
      ];
    };
  };
}
```

## Complete Example

Here's a complete workflow from project to NixOS system:

```bash
# 1. Import a project
templedb project import https://github.com/user/myapp

# 2. Add environment variables
templedb env set myapp PORT 3000
templedb env set myapp NODE_ENV production

# 3. Add secrets
templedb env secret init myapp
templedb env secret edit myapp  # Add DATABASE_URL, API_KEYS, etc.

# 4. Generate NixOS configuration
templedb nixos export myapp -o ~/nixos-configs/myapp

# 5. Review generated files
cat ~/nixos-configs/myapp/myapp-INTEGRATION.md

# 6. Copy to NixOS config directory
cp ~/nixos-configs/myapp/*.nix /etc/nixos/

# 7. Update flake.nix to import the modules

# 8. Rebuild
sudo nixos-rebuild test

# 9. After confirming it works
sudo nixos-rebuild switch
```

## Deployment Workflow

Combine with TempleDB's deployment features:

```bash
# 1. Deploy project from TempleDB
templedb deploy run myapp

# 2. Navigate to deployed project
cd $(templedb deploy path myapp)

# 3. Work with the deployed project
# All dependencies from NixOS module are available

# 4. Update NixOS config as project evolves
templedb nixos export myapp -o /etc/nixos/modules/
sudo nixos-rebuild switch
```

## Continuous Integration

Use in CI/CD pipelines:

```yaml
# .github/workflows/nix-build.yml
name: Build NixOS Configuration

on: [push]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2

      - name: Install Nix
        uses: cachix/install-nix-action@v20

      - name: Generate NixOS modules
        run: |
          nix run github:yourusername/templedb -- nixos export myproject

      - name: Build NixOS configuration
        run: |
          nixos-rebuild build --flake .#myhost

      - name: Upload artifacts
        uses: actions/upload-artifact@v3
        with:
          name: nixos-config
          path: result
```

## Troubleshooting

### "templedb: command not found"

Make sure TempleDB is in your PATH after NixOS rebuild:

```bash
# Check if installed
which templedb

# If not found, reload your shell
exec $SHELL

# Or re-login to apply system-wide changes
```

### Generated Module Has Wrong Packages

1. Check detected file types:
   ```bash
   templedb nixos detect myproject
   ```

2. Manually edit the generated `.nix` files

3. Customize detection in `src/nixos_generator.py`

### Secrets Not Decrypting

1. Verify age key exists:
   ```bash
   ls -la ~/.config/sops/age/keys.txt
   ```

2. Check sops-nix configuration:
   ```bash
   sudo nixos-rebuild build --show-trace
   ```

3. Ensure secrets are encrypted with correct key:
   ```bash
   templedb env secret export myproject --format yaml
   ```

## Database-Driven NixOS Configuration

TempleDB's most powerful NixOS integration is using the database as the source of truth for your system configuration. Configuration keys live in the `system_config` table and are used to generate nix files at build time.

### Host-Scoped Configuration

Every machine has a host identity (stored as `nixos.flake_output`). Config keys are automatically scoped:

```bash
# Host-scoped (default): stored as <hostname>.key
templedb nixos config-set nixos.pkg.user.vpn.tailscale true

# Global: inherited by all hosts
templedb nixos config-set --global nixos.username zach
templedb nixos config-set --global nixos.flake.input.nixpkgs "github:NixOS/nixpkgs/nixos-25.11"

# Target a specific host
templedb nixos config-set --host zStation videoDriver modesetting

# Query config
templedb nixos config-get nixos.pkg.user.vpn.tailscale
```

When generating nix files, TempleDB merges global keys with host-specific overrides for the active host.

### Multi-Host Management

```bash
templedb nixos host list                          # list all hosts
templedb nixos host clone zMothership2 zStation   # clone config for new machine
templedb nixos config-set --host zStation videoDriver modesetting  # per-host override
templedb nixos host activate zStation             # switch active host

# Generate NixOS files for active host
templedb nixos generate-all system_config
```

### The generate-all Workflow

`templedb nixos generate-all <system_config_slug>` reads all config keys from the database and produces nix files:

- **Packages**: `nixos.pkg.user.*` and `nixos.pkg.system.*` → package lists
- **Services**: `nixos.service.*` → systemd service enables
- **Aliases**: `nixos.alias.*` → shell aliases
- **Firewall**: `nixos.firewall.*` → port rules
- **Flake inputs**: `nixos.flake.input.*` → flake input URLs

```bash
templedb nixos generate-all system_config
templedb nixos rebuild system_config   # nixos-rebuild switch
```

## Auto-Generated Managed Modules

TempleDB generates home-manager and NixOS modules that are imported by your system configuration. These live in the system_config checkout at `~/.config/templedb/checkouts/system_config/modules/`.

### templedb-managed.nix (Home-Manager)

Auto-generated module providing user-level packages and shell aliases. Rebuilt by `templedb nixos generate-all`:

```nix
# AUTO-GENERATED by TempleDB — do not edit manually.
# To update:
#   templedb env var set <key> <value> --nixos
#   templedb nixos generate system_config

{ config, pkgs, lib, bza, templedb, ... }:
{
  home.packages = with pkgs; [
    curl git jq pandoc vim wget
  ] ++ [
    bza.packages.${pkgs.system}.default       # project packages from DB
    templedb.packages.${pkgs.system}.default
  ];

  programs.bash.initExtra = ''
    alias tcd-system_config='cd $(tdb deploy path system_config)'
  '';
}
```

### templedb-managed-system.nix (NixOS)

System-level module for services, firewall rules, and system packages. Initially empty — populated by `generate-all` based on `nixos.pkg.system.*` and `nixos.service.*` keys.

## Automatic Flake Input Generation

The `generate-templedb-inputs.py` script queries the database for all projects marked as Nix projects and auto-generates flake inputs and home-manager module imports.

### How It Works

1. Queries `projects` table for rows with `is_nix_project=1` and `flake_check_status='valid'`
2. Generates `templedb-inputs.nix` — flake inputs pointing to each project's path
3. Generates `templedb-hm-modules.nix` — list of `homeManagerModules.default` for projects with `project_category='home-module'`

### Setup

In your system config's `flake.nix`, use managed markers:

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
    templedb.url = "github:NotBrianZach/templedb";

    # === BEGIN templedb-managed (auto-updated by generate-templedb-inputs.py) ===
    bza.url = "path:/home/zach/.config/templedb/checkouts/bza";
    # === END templedb-managed ===
  };
}
```

And import the generated module list:

```nix
# In home-manager config:
imports = [
  templedb.homeManagerModules.default
  ./modules/templedb-managed.nix
] ++ (import ./templedb-hm-modules.nix { inherit inputs; });
```

### Adding a New Project

```bash
# 1. Import the project
templedb project import ~/my-new-project --slug my-new-project

# 2. Mark it as a Nix project with a home-manager module
templedb project set-category my-new-project --nix --category home-module

# 3. Regenerate inputs
cd ~/.config/templedb/checkouts/system_config
python3 generate-templedb-inputs.py

# 4. Rebuild
templedb nixos rebuild system_config
```

## Dynamic Configuration at Build Time

For projects that need to read TempleDB config during the Nix build, you can use `builtins.readFile` with `pkgs.runCommand`:

```nix
# Example: read a TempleDB config key at nix evaluation time
let
  getConfig = key: default:
    let
      result = builtins.readFile (pkgs.runCommand "templedb-${key}" {} ''
        ${templedb.packages.${pkgs.system}.templedb}/bin/templedb nixos config-get ${key} \
          2>/dev/null > $out || echo "${default}" > $out
      '');
    in lib.removeSuffix "\n" result;

  myEnabled = (getConfig "myproject.enable" "false") == "true";
in
lib.mkIf myEnabled {
  # ... conditional configuration based on DB state
}
```

This pattern is used by the woofs project to dynamically configure its NixOS service based on TempleDB keys like `woofs.enable`, `woofs.deployment_target`, etc.

## Direnv Integration

TempleDB provides a direnv helper for automatic environment loading:

```bash
# ~/.config/direnv/direnvrc
use_templedb() {
    eval "$(tdb env direnv "$@")"
}
```

Then in any project's `.envrc`:

```bash
use_templedb
```

This loads the project's environment variables, decrypted secrets, and Nix shell automatically when you `cd` into the directory.

## Bootstrap: New Machine in One Command

```bash
templedb bootstrap --from-gcs my-bucket --username zach --hostname zMothership3
```

This runs 9 steps:
1. Restore database from GCS backup
2. Apply pending migrations
3. Set up age encryption key
4. Materialize system_config checkout
5. Link dotfiles
6. Set machine identity
7. Generate NixOS configuration
8. Mount FUSE filesystem
9. Verify everything works

## Benefits of TempleDB + NixOS

1. **Reproducible Environments**: Same configuration works on any NixOS machine
2. **Database-Driven Config**: Change a key in the DB → regenerate → rebuild
3. **Host Scoping**: Per-machine overrides with global defaults
4. **Auto-Generated Inputs**: New projects automatically wire into your flake
5. **Version Control**: NixOS configs tracked in TempleDB VCS
6. **Secret Management**: Encrypted secrets with age, decrypted at build/deploy time
8. **One-Command Bootstrap**: Restore an entire machine from a GCS backup

## See Also

- [TempleDB README](../README.md) — CLI overview and home-manager module reference
- [Cathedral Package Format](./advanced/CATHEDRAL.md)
- [Secret Management](./SECRETS.md)
- [Machine-to-Machine Sync](./MACHINE_TO_MACHINE_SYNC.md)
- [NixOS Manual](https://nixos.org/manual/nixos/stable/)
- [Home Manager Manual](https://nix-community.github.io/home-manager/)
