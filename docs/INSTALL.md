# TempleDB Installation Guide

## Quick Install (Recommended)

```bash
git clone https://github.com/yourusername/templedb.git
cd templedb
./install.sh
```

The installer will handle everything automatically.

## One-Line Install (Coming Soon)

```bash
curl -fsSL https://raw.githubusercontent.com/yourusername/templedb/main/install.sh | bash
```

Or with wget:
```bash
wget -qO- https://raw.githubusercontent.com/yourusername/templedb/main/install.sh | bash
```

## What the Installer Does

1. **Platform Detection** - Automatically detects Linux, macOS, or Windows/WSL
2. **Dependency Check** - Verifies Python 3.9+, SQLite 3.35+, git, and age (optional)
3. **PATH Installation** - Installs `templedb` to:
   - `~/.local/bin` (Linux/macOS user install)
   - `~/bin` (alternative user location)
   - `/usr/local/bin` (system-wide install)
4. **Shell Integration** - Automatically adds to PATH in:
   - `.bashrc` or `.bash_profile` (bash)
   - `.zshrc` (zsh)
   - `.config/fish/config.fish` (fish)
5. **Database Setup** - Initializes database at platform-appropriate location:
   - Linux/macOS: `~/.local/share/templedb/templedb.sqlite`
   - Windows: `~/AppData/Local/templedb/templedb.sqlite`
6. **Example Content** - Optionally imports TempleDB itself as an example project

## Installation Options

### Option 1: Automatic Installation (Recommended)

```bash
git clone https://github.com/yourusername/templedb.git
cd templedb
./install.sh
```

**What you get:**
- ✓ `templedb` command available globally
- ✓ Database initialized and ready
- ✓ Optional example project
- ✓ Help README in database directory

### Option 2: User Install (No System Access)

The default installer creates a user installation in `~/.local/bin`. No sudo required.

```bash
./install.sh
# Installs to ~/.local/bin/templedb
```

### Option 3: System-Wide Install

If `/usr/local/bin` is writable, the installer will offer system-wide installation:

```bash
sudo ./install.sh
# Installs to /usr/local/bin/templedb (if writable)
```

### Option 4: Development Mode

Run directly from the repository without installing:

```bash
git clone https://github.com/yourusername/templedb.git
cd templedb
./templedb --help
```

Add to PATH in current session:
```bash
export PATH="$(pwd):$PATH"
templedb --help
```

### Option 5: NixOS/Nix (Coming Soon)

```nix
# flake.nix
{
  inputs.templedb.url = "github:yourusername/templedb";

  environment.systemPackages = [
    inputs.templedb.packages.${system}.default
  ];
}
```

## Platform-Specific Notes

### Linux (Ubuntu/Debian)

```bash
# Install dependencies
sudo apt update
sudo apt install python3 python3-pip sqlite3 git age

# Install TempleDB
git clone https://github.com/yourusername/templedb.git
cd templedb
./install.sh
```

### Linux (Fedora/RHEL)

```bash
# Install dependencies
sudo dnf install python3 sqlite git

# Age needs manual install:
wget https://github.com/FiloSottile/age/releases/download/v1.3.1/age-v1.3.1-linux-amd64.tar.gz
tar xzf age-v1.3.1-linux-amd64.tar.gz
sudo mv age/age age/age-keygen /usr/local/bin/

# Install TempleDB
git clone https://github.com/yourusername/templedb.git
cd templedb
./install.sh
```

### macOS

```bash
# Install dependencies (Homebrew)
brew install python sqlite git age

# Install TempleDB
git clone https://github.com/yourusername/templedb.git
cd templedb
./install.sh
```

### Windows (WSL)

Use the Linux instructions within WSL. TempleDB is fully compatible with WSL2.

## Post-Installation

### Verify Installation

```bash
# Check version
templedb --version

# Check database location
templedb status

# View help
templedb --help
```

### Configure Age Keys (for Secret Management)

```bash
# Generate age key
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt

# Get public key
age-keygen -y ~/.config/sops/age/keys.txt

# Add to shell config
echo 'export TEMPLEDB_AGE_KEY_FILE=~/.config/sops/age/keys.txt' >> ~/.bashrc
echo 'export TEMPLEDB_AGE_RECIPIENT=$(age-keygen -y $TEMPLEDB_AGE_KEY_FILE)' >> ~/.bashrc
source ~/.bashrc
```

### First Steps

```bash
# Import a project
cd ~/projects/my-app
templedb project import .

# View projects
templedb project list

# Query database
sqlite3 ~/.local/share/templedb/templedb.sqlite
```

## Uninstallation

```bash
cd /path/to/templedb
./install.sh uninstall
```

Or manually:
```bash
# Remove binary
rm ~/.local/bin/templedb  # or /usr/local/bin/templedb

# Remove database (optional)
rm -rf ~/.local/share/templedb/

# Remove age keys (optional)
rm -rf ~/.config/sops/age/

# Remove PATH entry from shell config
# Edit ~/.bashrc, ~/.zshrc, etc. and remove TempleDB lines
```

## Troubleshooting

### "templedb: command not found"

**After installation:**
```bash
# Reload shell config
source ~/.bashrc  # or ~/.zshrc

# Or restart terminal
```

**Check installation:**
```bash
ls -l ~/.local/bin/templedb
which templedb
echo $PATH | grep -o "[^:]*local/bin[^:]*"
```

### "Permission denied"

```bash
# Make installer executable
chmod +x install.sh

# Make templedb wrapper executable
chmod +x templedb
```

### "Python not found"

```bash
# Ubuntu/Debian
sudo apt install python3

# macOS
brew install python3

# Verify
python3 --version
```

### "age not found"

Age is optional but needed for secret management:

```bash
# Ubuntu 22.04+
sudo apt install age

# macOS
brew install age

# Manual (all platforms)
wget https://github.com/FiloSottile/age/releases/download/v1.3.1/age-v1.3.1-linux-amd64.tar.gz
tar xzf age-v1.3.1-linux-amd64.tar.gz
sudo mv age/age age/age-keygen /usr/local/bin/
```

### Database Initialization Fails

```bash
# Check permissions
ls -la ~/.local/share/templedb/

# Manually initialize
mkdir -p ~/.local/share/templedb
templedb status  # Will initialize database

# Check migrations
cd /path/to/templedb
python3 -c "from src.migration_tracker import get_migration_status; print(get_migration_status())"
```

### Installation Fails on macOS

If you get security warnings:

```bash
# Allow execution
xattr -d com.apple.quarantine templedb
xattr -d com.apple.quarantine install.sh

# Or in System Preferences > Security & Privacy, allow the app
```

## Database Locations

| Platform | Database Path |
|----------|--------------|
| Linux | `~/.local/share/templedb/templedb.sqlite` |
| macOS | `~/.local/share/templedb/templedb.sqlite` |
| Windows | `~/AppData/Local/templedb/templedb.sqlite` |

## Binary Locations

| Install Type | Binary Path |
|--------------|------------|
| User install | `~/.local/bin/templedb` or `~/bin/templedb` |
| System install | `/usr/local/bin/templedb` |
| Development | `./templedb` (in repo directory) |

## Environment Variables

```bash
# Required for secret management
export TEMPLEDB_AGE_KEY_FILE=~/.config/sops/age/keys.txt
export TEMPLEDB_AGE_RECIPIENT=$(age-keygen -y $TEMPLEDB_AGE_KEY_FILE)

# Optional: Custom database location
export TEMPLEDB_DATABASE=~/custom/path/database.sqlite

# Legacy (still supported)
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt
export SOPS_AGE_RECIPIENT=$(age-keygen -y $SOPS_AGE_KEY_FILE)
```

## Updating TempleDB

```bash
cd /path/to/templedb
git pull
./install.sh  # Reinstalls with updates
```

The installer will not overwrite your database or configuration.

## Getting Help

- **Documentation**: [GETTING_STARTED.md](../GETTING_STARTED.md)
- **Issues**: https://github.com/yourusername/templedb/issues
- **Discussions**: https://github.com/yourusername/templedb/discussions

## Next Steps

After installation:

1. **[GETTING_STARTED.md](../GETTING_STARTED.md)** - Beginner-friendly introduction
2. **[QUICKSTART.md](../QUICKSTART.md)** - Common workflows
3. **[README.md](../README.md)** - Complete overview
4. **[SECURITY.md](../SECURITY.md)** - Secret management setup
