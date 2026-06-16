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
templedb secret init myproject --age-recipient $(cat ~/.config/sops/age/keys.txt | age-keygen -y)

# Edit secrets (opens $EDITOR)
templedb secret edit myproject
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
templedb secret init myapp
templedb secret edit myapp  # Add DATABASE_URL, API_KEYS, etc.

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
   templedb secret export myproject --format yaml
   ```

## Benefits of TempleDB + NixOS

1. **Reproducible Environments**: Same configuration works on any NixOS machine
2. **Version Control**: NixOS configs in git, TempleDB tracks project history
3. **Dependency Management**: Automatically detect and install required packages
4. **Secret Management**: Encrypted secrets with age + sops-nix
5. **Self-Hosting**: TempleDB can manage its own NixOS configuration
6. **Deployment**: Deploy from database-backed state to NixOS systems

## See Also

- [TempleDB Project Management](../README.md#project-management)
- [Cathedral Package Format](./CATHEDRAL.md)
- [Deployment Guide](./DEPLOYED_PROJECTS.md)
- [Secret Management](./SECRETS.md)
- [NixOS Manual](https://nixos.org/manual/nixos/stable/)
- [Home Manager Manual](https://nix-community.github.io/home-manager/)
- [sops-nix Documentation](https://github.com/Mic92/sops-nix)
