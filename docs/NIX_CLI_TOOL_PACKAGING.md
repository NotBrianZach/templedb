# Nix Packaging for CLI Tools

**Status**: ✅ Complete
**Date**: 2026-03-21

## Overview

TempleDB now supports deploying CLI tools as **Nix packages and flakes**. This provides:

- ✅ **Nix Flake Generation** - Auto-generate flake.nix for Python, Node.js, and Rust CLI tools
- ✅ **Local Installation** - Install CLI tools to your local Nix profile with `nix profile install`
- ✅ **System Configuration** - Generate snippets for NixOS and home-manager configurations
- ✅ **Reproducible Builds** - Leverage Nix's reproducible build system
- ✅ **Multiple Languages** - Support for Python, Node.js, and Rust projects

---

## Why Nix Packaging?

Nix packaging offers several advantages over traditional app store deployment:

### For Developers
- **Reproducible builds** - Same source = same binary, every time
- **Declarative configuration** - Your system config is code
- **Rollback support** - Easy to revert to previous versions
- **No dependency conflicts** - Each package has its own isolated dependencies

### For Users
- **Easy installation** - `nix profile install` or add to system config
- **No sudo required** - Install to user profile without root access
- **Multiple versions** - Run different versions side-by-side
- **Pure builds** - No hidden system dependencies

### Distribution Reach
- **NixOS users** - ~100K active users (growing rapidly)
- **Nix package manager users** - Available on macOS, Linux, WSL
- **Developer-friendly** - Popular among software engineers and DevOps

---

## Commands

### 1. `deploy-nix generate-flake` - Generate Nix Flake

Generate a flake.nix for your CLI tool that can be installed as a Nix package.

**Usage**:
```bash
templedb deploy-nix generate-flake <project-slug> \
  [--description "Tool description"] \
  [--version 1.0.0]
```

**Example - Python CLI Tool**:
```bash
templedb deploy-nix generate-flake bza \
  --description "AI-powered code generation CLI" \
  --version 1.0.0

# Output:
# 📦 Generating Nix flake for CLI tool: bza
#    Path: /home/user/bza
#
# ✅ CLI flake generated successfully
#
# 📄 Flake location: /home/user/bza/flake.nix
#
# 💡 Next steps:
#    1. Review and customize flake.nix
#    2. Test build: nix build /home/user/bza
#    3. Test run: nix run /home/user/bza
#    4. Install locally: templedb deploy-nix install bza
#    5. Add to system config: templedb deploy-nix add-to-config bza
```

**What It Generates**:

For Python projects (with `requirements.txt` or `pyproject.toml`):
```nix
{
  description = "bza - AI-powered code generation CLI";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        packages.default = pkgs.python3Packages.buildPythonApplication {
          pname = "bza";
          version = "1.0.0";
          src = ./.;

          format = "pyproject";

          propagatedBuildInputs = with pkgs.python3Packages; [
            # Your dependencies here
          ];

          meta = with pkgs.lib; {
            description = "AI-powered code generation CLI";
            homepage = "https://github.com/yourorg/bza";
            license = licenses.mit;
            maintainers = [ ];
          };
        };

        apps.default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/bza";
        };

        devShells.default = pkgs.mkShell {
          buildInputs = with pkgs; [
            python3
            python3Packages.pip
            python3Packages.setuptools
          ];
        };
      }
    );
}
```

For Node.js projects (with `package.json`):
```nix
{
  description = "mytool - Node.js CLI tool";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in
      {
        packages.default = pkgs.buildNpmPackage {
          pname = "mytool";
          version = "1.0.0";
          src = ./.;

          npmDepsHash = "";  # Run nix build to get hash

          meta = with pkgs.lib; {
            description = "Node.js CLI tool";
            license = licenses.mit;
          };
        };

        apps.default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/mytool";
        };
      }
    );
}
```

For Rust projects (with `Cargo.toml`):
```nix
{
  description = "rustool - Rust CLI tool";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    rust-overlay.url = "github:oxalica/rust-overlay";
  };

  outputs = { self, nixpkgs, flake-utils, rust-overlay }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = import nixpkgs {
          inherit system;
          overlays = [ (import rust-overlay) ];
        };
      in
      {
        packages.default = pkgs.rustPlatform.buildRustPackage {
          pname = "rustool";
          version = "1.0.0";
          src = ./.;

          cargoLock = {
            lockFile = ./Cargo.lock;
          };

          meta = with pkgs.lib; {
            description = "Rust CLI tool";
            license = licenses.mit;
          };
        };

        apps.default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/rustool";
        };
      }
    );
}
```

---

### 2. `deploy-nix install` - Install Locally

Install the CLI tool to your local Nix profile, making it available in PATH.

**Usage**:
```bash
templedb deploy-nix install <project-slug>
```

**Example**:
```bash
templedb deploy-nix install bza

# Output:
# 📥 Installing bza to local Nix profile...
#    This will make 'bza' available in your PATH
#
# ✅ bza installed to local Nix profile
#
# 🎉 Installation complete!
#
# 💡 You can now run: bza
#
# 📋 Manage installed packages:
#    List:   nix profile list
#    Remove: nix profile remove bza
```

**What It Does**:
1. Runs `nix profile install /path/to/project`
2. Builds the Nix package
3. Adds the binary to `~/.nix-profile/bin/`
4. The tool is now available in your PATH

**Managing Installed Packages**:
```bash
# List all installed packages
nix profile list

# Remove a package
nix profile remove bza

# Upgrade a package
cd /path/to/bza && git pull
nix profile upgrade bza
```

---

### 3. `deploy-nix add-to-config` - System Configuration

Generate a Nix configuration snippet to add the CLI tool to your NixOS or home-manager configuration.

**Usage**:
```bash
templedb deploy-nix add-to-config <project-slug>
```

**Example**:
```bash
templedb deploy-nix add-to-config bza

# Output:
# ⚙️  Generating NixOS/home-manager configuration snippet...
#    Project: bza
#
# ✅ System configuration snippet generated at /tmp/templedb-deploy/bza-system-config.nix
#
# 📄 Configuration snippet saved to: /tmp/templedb-deploy/bza-system-config.nix
#
# 💡 To add to your system:
#    1. Copy the snippet from /tmp/templedb-deploy/bza-system-config.nix
#    2. Add to your configuration.nix or home.nix
#    3. Rebuild: sudo nixos-rebuild switch (or home-manager switch)
```

**Generated Snippet**:
```nix
# Add to your configuration.nix or home.nix

{
  inputs = {
    # Option 1: Use TempleDB git server (requires: tdb gitserver start)
    bza.url = "git+http://localhost:9418/bza";
    # Option 2: Use local path (development)
    # bza.url = "path:/home/user/bza";
    # Option 3: Use GitHub
    # bza.url = "github:yourorg/bza";
  };

  outputs = { self, nixpkgs, bza, ... }: {
    # For NixOS system configuration:
    nixosConfigurations.yourhost = nixpkgs.lib.nixosSystem {
      modules = [
        {
          environment.systemPackages = [
            bza.packages.x86_64-linux.default
          ];
        }
      ];
    };

    # For home-manager:
    homeConfigurations.youruser = home-manager.lib.homeManagerConfiguration {
      modules = [
        {
          home.packages = [
            bza.packages.x86_64-linux.default
          ];
        }
      ];
    };
  };
}
```

---

## Complete Workflow Examples

### Python CLI Tool (bza)

```bash
# Step 1: Import project to TempleDB
templedb project import /home/user/bza bza

# Step 2: Generate Nix flake
templedb deploy-nix generate-flake bza \
  --description "AI-powered code generation CLI" \
  --version 1.0.0

# Step 3: Test the build
cd /home/user/bza
nix build

# Step 4: Test run
nix run .

# Step 5a: Install locally (for personal use)
templedb deploy-nix install bza

# Step 5b: Or add to system config (for system-wide availability)
templedb deploy-nix add-to-config bza
# Then copy snippet to configuration.nix and rebuild

# Done! CLI tool is now available
bza --help
```

---

### Node.js CLI Tool

```bash
# Step 1: Import project
templedb project import /home/user/mytool mytool

# Step 2: Generate flake
templedb deploy-nix generate-flake mytool

# Step 3: Update npmDepsHash
cd /home/user/mytool
nix build 2>&1 | grep "got:" | awk '{print $2}'
# Copy the hash and update flake.nix:
# npmDepsHash = "sha256-xxx...";

# Step 4: Build again
nix build

# Step 5: Install
templedb deploy-nix install mytool

# Done!
mytool --version
```

---

### Rust CLI Tool

```bash
# Step 1: Import project
templedb project import /home/user/rustool rustool

# Step 2: Generate flake
templedb deploy-nix generate-flake rustool

# Step 3: Ensure Cargo.lock exists
cd /home/user/rustool
cargo generate-lockfile  # if needed

# Step 4: Build
nix build

# Step 5: Install
templedb deploy-nix install rustool

# Done!
rustool --help
```

---

## Comparison: Nix vs App Stores

| Feature | Nix Packaging | Homebrew | Snap | macOS App Store |
|---------|--------------|----------|------|-----------------|
| **Setup Time** | Easy (30 min) | Easy (1 hr) | Easy (2 hrs) | Hard (1 week) |
| **Cost** | Free | Free | Free | $99/year |
| **Reach** | 100K+ Nix users | 30M developers | 50M Ubuntu users | 1B+ Mac users |
| **Reproducible** | ✅ Yes (deterministic) | ❌ No | ❌ No | ❌ No |
| **Rollback** | ✅ Built-in | ⚠️ Manual | ⚠️ Via snap revert | ❌ No |
| **Multi-version** | ✅ Yes | ⚠️ Via taps | ❌ No | ❌ No |
| **System Integration** | ✅ NixOS/home-manager | ⚠️ Limited | ⚠️ Limited | ✅ Full |
| **Sandboxing** | ✅ Pure builds | ❌ No | ✅ Strict confinement | ✅ Sandboxed |
| **Update Speed** | ⚡ Instant | ⚡ Instant | ⏱️ Review process | ⏱️ 1-7 day review |

**Recommendation**: Use **Nix for developer tools** (reproducibility matters) and **Homebrew/App Stores for consumer tools** (wider reach).

---

## Advantages of Nix Packaging

### 1. Reproducibility
```bash
# Same source always produces same binary
nix build --rebuild  # Always identical output
```

### 2. Declarative System Configuration
```nix
# Your entire system in one file
{
  environment.systemPackages = [
    bza
    mytool
    rustool
  ];
}
```

### 3. Easy Rollbacks
```bash
# Something broke? Roll back instantly
sudo nixos-rebuild switch --rollback
```

### 4. Development Shells
```bash
# Temporary environment with exact dependencies
nix develop

# Or one-off commands
nix shell nixpkgs#python3 -c python --version
```

### 5. Multiple Versions
```bash
# Install bza version 1.0.0
nix profile install github:yourorg/bza/v1.0.0

# Also install version 2.0.0
nix profile install github:yourorg/bza/v2.0.0

# Run specific version
nix run github:yourorg/bza/v1.0.0
```

---

## Distribution Options

Once you have a flake.nix, you can distribute your CLI tool in multiple ways:

### 1. Local Installation
```bash
# Users clone your repo and install
git clone https://github.com/yourorg/bza
cd bza
nix profile install .
```

### 2. Direct from GitHub
```bash
# Users install directly from GitHub
nix profile install github:yourorg/bza
```

### 3. Via nixpkgs (Official Nix Packages)
Submit a PR to [nixpkgs](https://github.com/NixOS/nixpkgs) to include your package in the official repository:

```bash
# After being merged into nixpkgs
nix profile install nixpkgs#bza
```

### 4. Via Cachix (Binary Cache)
Set up a [Cachix](https://cachix.org) cache for pre-built binaries:

```bash
# Users add your cache
cachix use yourorg

# Then install instantly (no build required)
nix profile install github:yourorg/bza
```

### 5. System Configuration
Users add to their NixOS or home-manager configuration for declarative management.

---

## Prerequisites

### For Developers (Creating Packages)
- **Nix** - Install from [nixos.org](https://nixos.org/download.html)
- **Flakes enabled** - Add to `~/.config/nix/nix.conf`:
  ```
  experimental-features = nix-command flakes
  ```
- **Git** - For version control
- **Project structure** - One of:
  - Python: `requirements.txt` or `pyproject.toml`
  - Node.js: `package.json`
  - Rust: `Cargo.toml`

### For Users (Installing Packages)
- **Nix** - Install from [nixos.org](https://nixos.org/download.html)
- **Flakes enabled** - Same as above
- **That's it!** - No build tools required

---

## Troubleshooting

### Error: "experimental-features not enabled"

**Symptom**:
```
error: experimental Nix feature 'flakes' is disabled
```

**Solution**:
```bash
# Add to ~/.config/nix/nix.conf
echo "experimental-features = nix-command flakes" >> ~/.config/nix/nix.conf

# Or enable system-wide in /etc/nix/nix.conf (NixOS)
```

---

### Error: "hash mismatch" for Node.js packages

**Symptom**:
```
error: hash mismatch in fixed-output derivation
  got:    sha256-abc123...
  wanted: sha256-def456...
```

**Solution**:
1. Copy the "got:" hash from the error
2. Update `npmDepsHash` in flake.nix with the new hash
3. Run `nix build` again

---

### Error: "no Cargo.lock found" for Rust projects

**Symptom**:
```
error: Cargo.lock file not found
```

**Solution**:
```bash
# Generate Cargo.lock
cargo generate-lockfile

# Commit it to git
git add Cargo.lock
git commit -m "Add Cargo.lock"

# Build again
nix build
```

---

### Python dependencies not found

**Symptom**:
```
error: attribute 'somepackage' missing
```

**Solution**:
Check if the package is available in nixpkgs:
```bash
# Search for package
nix search nixpkgs python3Packages.somepackage

# If not found, you may need to:
# 1. Use buildPythonApplication with pip
# 2. Package it yourself
# 3. Use poetry2nix or similar
```

---

## Implementation Details

### Files Modified

1. **`src/services/deployment/nix_deployment_service.py`** (+350 lines)
   - Added `generate_cli_flake()` - Generate flake.nix for CLI tools
   - Added `_generate_cli_python_flake()` - Python-specific flake generation
   - Added `_generate_cli_nodejs_flake()` - Node.js-specific flake generation
   - Added `_generate_cli_rust_flake()` - Rust-specific flake generation
   - Added `install_local()` - Install to local Nix profile
   - Added `add_to_system_config()` - Generate system config snippet
   - Updated `NixDeploymentResult` dataclass with `flake_path` and `package_installed` fields

2. **`src/cli/commands/deploy_nix.py`** (+120 lines)
   - Added `generate_flake()` command handler
   - Added `install_local()` command handler
   - Added `add_to_config()` command handler
   - Registered 3 new commands in CLI

### Technologies Used

- **Nix** - Purely functional package manager
- **Nix Flakes** - Modern Nix interface for hermetic builds
- **flake-utils** - Helper library for multi-platform flakes
- **buildPythonApplication** - Nix builder for Python packages
- **buildNpmPackage** - Nix builder for Node.js packages
- **rustPlatform.buildRustPackage** - Nix builder for Rust packages

---

## What's Next

### Immediate Enhancements
- Auto-detect dependencies from requirements.txt/package.json
- Generate Nix expressions for system dependencies
- Support for more languages (Go, Ruby, etc.)
- Cachix integration for binary caching
- Automatic CI/CD for building and caching

### Future Features
- Nix container images (via `dockerTools.buildImage`)
- Cross-compilation support
- NixOS modules for services
- Automated testing in Nix sandbox
- Integration with hydra (Nix CI)

---

## Conclusion

Nix packaging provides a **modern, reproducible** way to distribute CLI tools. While the reach is smaller than Homebrew or app stores, the **developer experience and reliability** are unmatched.

**Use Nix when**:
- Your users value reproducibility
- You target developers/DevOps engineers
- You want declarative system management
- You need multiple versions simultaneously

**Use App Stores when**:
- You want maximum reach
- You target consumers
- You need code signing/notarization
- You want app store discoverability

**Best of Both Worlds**: Generate Nix packages for developers *and* publish to app stores for consumers!

---

**Document Status**: Implementation Complete
**Date**: 2026-03-21
**Commands Added**: 3 (generate-flake, install, add-to-config)
**Languages Supported**: Python, Node.js, Rust
