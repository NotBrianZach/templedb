#!/usr/bin/env bash
# TempleDB Installation Script
# Cross-platform installer for TempleDB CLI

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Print colored messages
info() { echo -e "${BLUE}ℹ${NC} $*"; }
success() { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
error() { echo -e "${RED}✗${NC} $*"; }

# Detect platform
detect_platform() {
    case "$(uname -s)" in
        Linux*)     PLATFORM="Linux";;
        Darwin*)    PLATFORM="macOS";;
        CYGWIN*|MINGW*|MSYS*) PLATFORM="Windows";;
        *)          PLATFORM="Unknown";;
    esac
    info "Detected platform: $PLATFORM"
}

# Detect shell and config file
detect_shell() {
    SHELL_NAME=$(basename "$SHELL")
    case "$SHELL_NAME" in
        bash)
            if [[ "$PLATFORM" == "macOS" ]]; then
                SHELL_CONFIG="$HOME/.bash_profile"
            else
                SHELL_CONFIG="$HOME/.bashrc"
            fi
            ;;
        zsh)
            SHELL_CONFIG="$HOME/.zshrc"
            ;;
        fish)
            SHELL_CONFIG="$HOME/.config/fish/config.fish"
            ;;
        *)
            SHELL_CONFIG="$HOME/.profile"
            ;;
    esac
    info "Detected shell: $SHELL_NAME"
    info "Shell config: $SHELL_CONFIG"
}

# Check dependencies
check_dependencies() {
    local missing=()

    if ! command -v python3 &> /dev/null; then
        missing+=("python3")
    else
        PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
        success "Found Python $PYTHON_VERSION"
    fi

    if ! command -v sqlite3 &> /dev/null; then
        missing+=("sqlite3")
    else
        success "Found sqlite3"
    fi

    if ! command -v git &> /dev/null; then
        missing+=("git")
    else
        success "Found git"
    fi

    # Age is optional
    if ! command -v age &> /dev/null; then
        warn "age not found (optional, needed for secret management)"
        warn "Install: https://github.com/FiloSottile/age/releases"
    else
        success "Found age"
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        error "Missing required dependencies: ${missing[*]}"
        echo ""
        echo "Install instructions:"
        if [[ "$PLATFORM" == "Linux" ]]; then
            echo "  Ubuntu/Debian: sudo apt install ${missing[*]}"
            echo "  Fedora/RHEL:   sudo dnf install ${missing[*]}"
            echo "  Arch:          sudo pacman -S ${missing[*]}"
        elif [[ "$PLATFORM" == "macOS" ]]; then
            echo "  brew install ${missing[*]}"
        fi
        exit 1
    fi
}

# Find best install location
find_install_location() {
    # Check for common user bin directories
    if [[ -d "$HOME/.local/bin" ]]; then
        INSTALL_DIR="$HOME/.local/bin"
        INSTALL_TYPE="user"
    elif [[ -d "$HOME/bin" ]]; then
        INSTALL_DIR="$HOME/bin"
        INSTALL_TYPE="user"
    elif [[ -w "/usr/local/bin" ]]; then
        INSTALL_DIR="/usr/local/bin"
        INSTALL_TYPE="system"
    else
        # Create ~/.local/bin if nothing exists
        INSTALL_DIR="$HOME/.local/bin"
        INSTALL_TYPE="user"
        mkdir -p "$INSTALL_DIR"
        info "Created $INSTALL_DIR"
    fi
}

# Check if directory is in PATH
is_in_path() {
    local dir="$1"
    case ":$PATH:" in
        *":$dir:"*) return 0;;
        *) return 1;;
    esac
}

# Add directory to PATH in shell config
add_to_path() {
    local dir="$1"

    if is_in_path "$dir"; then
        success "$dir is already in PATH"
        return 0
    fi

    info "Adding $dir to PATH in $SHELL_CONFIG"

    # Create config file if it doesn't exist
    touch "$SHELL_CONFIG"

    # Add to PATH based on shell
    if [[ "$SHELL_NAME" == "fish" ]]; then
        echo "" >> "$SHELL_CONFIG"
        echo "# Added by TempleDB installer" >> "$SHELL_CONFIG"
        echo "set -gx PATH $dir \$PATH" >> "$SHELL_CONFIG"
    else
        echo "" >> "$SHELL_CONFIG"
        echo "# Added by TempleDB installer" >> "$SHELL_CONFIG"
        echo "export PATH=\"$dir:\$PATH\"" >> "$SHELL_CONFIG"
    fi

    success "Added $dir to PATH"
    warn "Restart your shell or run: source $SHELL_CONFIG"
}

# Install TempleDB
install_templedb() {
    info "Installing TempleDB to $INSTALL_DIR"

    # Create symlink or copy
    if [[ -L "$INSTALL_DIR/templedb" ]] || [[ -f "$INSTALL_DIR/templedb" ]]; then
        warn "TempleDB already installed at $INSTALL_DIR/templedb"
        read -p "Overwrite? (y/N) " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            info "Skipping installation"
            return 0
        fi
        rm -f "$INSTALL_DIR/templedb"
    fi

    # Create symlink to the wrapper script
    ln -s "$SCRIPT_DIR/templedb" "$INSTALL_DIR/templedb"
    chmod +x "$SCRIPT_DIR/templedb"

    success "Installed TempleDB to $INSTALL_DIR/templedb"
}

# Initialize database
initialize_database() {
    # Determine database location based on platform
    case "$PLATFORM" in
        Linux|macOS)
            DB_DIR="$HOME/.local/share/templedb"
            ;;
        Windows)
            DB_DIR="$HOME/AppData/Local/templedb"
            ;;
        *)
            DB_DIR="$HOME/.templedb"
            ;;
    esac

    DB_PATH="$DB_DIR/templedb.sqlite"

    if [[ -f "$DB_PATH" ]]; then
        success "Database already exists at $DB_PATH"
        return 0
    fi

    info "Initializing database at $DB_PATH"
    mkdir -p "$DB_DIR"

    # Add to current PATH for initialization
    export PATH="$INSTALL_DIR:$PATH"

    # Check if we have migration system
    if [[ -d "$SCRIPT_DIR/migrations" ]]; then
        info "Applying database migrations..."
        cd "$SCRIPT_DIR"
        if python3 -c "from src.migration_tracker import apply_all_migrations; apply_all_migrations('$DB_PATH')" 2>/dev/null; then
            success "Database initialized with migrations"
        else
            warn "Could not apply migrations automatically"
            info "Database will be initialized on first use"
        fi
    else
        info "Database will be initialized on first use"
    fi

    # Set proper permissions
    chmod 600 "$DB_PATH" 2>/dev/null || true

    success "Database location: $DB_PATH"
}

# Create example/starter content
setup_examples() {
    if [[ ! -f "$DB_PATH" ]]; then
        return 0
    fi

    info "Setting up example content..."

    # Ask user if they want examples
    read -p "Import TempleDB itself as an example project? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        info "Importing TempleDB project..."
        cd "$SCRIPT_DIR"
        if templedb project import . --slug templedb 2>&1 | grep -q "mport"; then
            success "Imported TempleDB as example project"
            info "Try: templedb project show templedb"
        else
            warn "Could not import example project"
        fi
    fi

    # Create helpful README in database directory
    cat > "$DB_DIR/README.txt" << 'EOF'
TempleDB Database Directory
===========================

This directory contains your TempleDB database.

Database: templedb.sqlite
Location: ~/.local/share/templedb/

Commands:
- View status:     templedb status
- List projects:   templedb project list
- Query database:  sqlite3 templedb.sqlite

Documentation:
- Getting Started: https://github.com/yourusername/templedb/blob/main/GETTING_STARTED.md
- Quick Start:     https://github.com/yourusername/templedb/blob/main/QUICKSTART.md

IMPORTANT: Back up this file regularly!
  cp templedb.sqlite ~/backups/templedb-$(date +%Y%m%d).sqlite
EOF

    success "Created README at $DB_DIR/README.txt"
}

# Verify installation
verify_installation() {
    info "Verifying installation..."

    # Add to current PATH for testing
    export PATH="$INSTALL_DIR:$PATH"

    if command -v templedb &> /dev/null; then
        success "templedb is accessible"
        VERSION=$(templedb --version 2>&1 || echo "unknown")
        info "Version: $VERSION"
    else
        error "templedb is not accessible in PATH"
        warn "You may need to restart your shell"
        return 1
    fi
}

# Show post-install message
show_completion_message() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    success "TempleDB installation complete!"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    echo "Installation details:"
    echo "  • Installed to: $INSTALL_DIR/templedb"
    echo "  • Install type: $INSTALL_TYPE"
    echo "  • Platform: $PLATFORM"
    echo "  • Database: $DB_PATH"
    echo ""

    if ! is_in_path "$INSTALL_DIR"; then
        warn "NOTE: $INSTALL_DIR was added to your PATH"
        warn "To use templedb immediately, run:"
        echo ""
        echo "  source $SHELL_CONFIG"
        echo ""
        warn "Or restart your terminal"
    else
        success "templedb is ready to use!"
    fi

    echo ""
    echo "Quick start:"
    echo "  templedb --help                    # Show all commands"
    echo "  templedb project import .          # Import current directory"
    echo "  templedb project list              # List projects"
    echo ""
    echo "Documentation:"
    echo "  • Getting Started: GETTING_STARTED.md"
    echo "  • Quick Start:     QUICKSTART.md"
    echo "  • README:          README.md"
    echo ""
    echo "AI Assistant Integration:"
    echo "  • For Claude Code users:"
    echo "    claude --append-system-prompt-file .claude/project-context.md"
    echo ""
    echo "  • Or create an alias:"
    echo "    alias claude-templedb='claude --append-system-prompt-file .claude/project-context.md'"
    echo ""
    echo "  This provides comprehensive TempleDB context to AI assistants."
    echo ""

    if ! command -v age &> /dev/null; then
        echo "Optional: Install age for secret management"
        echo "  https://github.com/FiloSottile/age/releases"
        echo ""
    fi
}

# Uninstall function
uninstall() {
    info "Uninstalling TempleDB..."

    # Find existing installation
    local found=false
    for dir in "$HOME/.local/bin" "$HOME/bin" "/usr/local/bin"; do
        if [[ -L "$dir/templedb" ]] || [[ -f "$dir/templedb" ]]; then
            info "Removing $dir/templedb"
            rm -f "$dir/templedb"
            success "Removed $dir/templedb"
            found=true
        fi
    done

    if [[ "$found" == "false" ]]; then
        warn "TempleDB not found in common install locations"
        return 1
    fi

    info "Note: Database and configuration remain at:"
    echo "  • Database: ~/.local/share/templedb/templedb.sqlite"
    echo "  • Age keys: ~/.config/sops/age/keys.txt"
    echo ""
    echo "To remove PATH entries, edit your shell config manually:"
    echo "  $SHELL_CONFIG"
    echo ""
    success "TempleDB uninstalled"
}

# Main installation flow
main() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  TempleDB Installer"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""

    # Handle uninstall
    if [[ "$1" == "uninstall" ]] || [[ "$1" == "--uninstall" ]]; then
        uninstall
        exit 0
    fi

    detect_platform
    detect_shell
    check_dependencies
    find_install_location
    install_templedb

    # Add to PATH if needed
    if ! is_in_path "$INSTALL_DIR"; then
        add_to_path "$INSTALL_DIR"
    fi

    verify_installation
    initialize_database
    setup_examples
    show_completion_message
}

# Run installer
main "$@"
