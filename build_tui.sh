#!/usr/bin/env bash
# TempleDB TUI Builder - Multiple Build Strategies
# Creates standalone executables using the best available method

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${CYAN}$1${NC}"; }
log_success() { echo -e "${GREEN}✓ $1${NC}"; }
log_error() { echo -e "${RED}✗ $1${NC}" >&2; }
log_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }

# Banner
cat << 'EOF'
╔════════════════════════════════════════════════╗
║   TempleDB TUI Builder                         ║
║   In Honor of Terry Davis                      ║
╚════════════════════════════════════════════════╝
EOF
echo ""

show_menu() {
    echo "Build Methods:"
    echo ""
    echo "  1) Nix Package     - Best for NixOS (recommended)"
    echo "  2) PyInstaller     - Fully standalone binary (no deps)"
    echo "  3) Python Zipapp   - Single file (needs Python + deps)"
    echo "  4) All Methods     - Build all available"
    echo ""
    echo "  q) Quit"
    echo ""
}

build_nix_package() {
    log_info "Building Nix package..."

    if ! command -v nix-build &> /dev/null; then
        log_error "nix-build not found - install Nix first"
        return 1
    fi

    nix-build templedb-tui-binary.nix -o result-tui

    if [ -L "result-tui" ]; then
        log_success "Nix package built: result-tui/bin/templedb-tui"
        echo ""
        echo "To install system-wide:"
        echo "  sudo cp result-tui/bin/templedb-tui /usr/local/bin/"
        echo ""
        return 0
    else
        log_error "Nix build failed"
        return 1
    fi
}

build_pyinstaller() {
    log_info "Building with PyInstaller..."

    if ! command -v pyinstaller &> /dev/null; then
        log_warning "PyInstaller not found"
        echo ""
        echo "Install with:"
        echo "  nix-shell -p python311Packages.pyinstaller"
        echo "  OR"
        echo "  pip install --user pyinstaller"
        echo ""
        return 1
    fi

    ./build_binary.sh

    if [ -f "dist/templedb-tui" ]; then
        log_success "PyInstaller binary built: dist/templedb-tui"
        return 0
    else
        log_error "PyInstaller build failed"
        return 1
    fi
}

build_zipapp() {
    log_info "Building Python zipapp..."

    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 not found"
        return 1
    fi

    ./build_zipapp.sh

    if [ -f "dist/templedb-tui" ]; then
        log_success "Zipapp built: dist/templedb-tui"
        echo ""
        echo "Note: Still requires Python 3 + textual + rich"
        echo ""
        return 0
    else
        log_error "Zipapp build failed"
        return 1
    fi
}

build_all() {
    local success=0
    local failed=0

    echo "Building all available methods..."
    echo ""

    if build_nix_package; then
        ((success++))
    else
        ((failed++))
    fi
    echo ""

    if build_pyinstaller; then
        ((success++))
    else
        ((failed++))
    fi
    echo ""

    if build_zipapp; then
        ((success++))
    else
        ((failed++))
    fi
    echo ""

    log_info "Build Summary:"
    echo "  Successful: $success"
    echo "  Failed: $failed"
}

# Interactive mode if no arguments
if [ $# -eq 0 ]; then
    while true; do
        show_menu
        read -p "Choose build method (1-4, q): " choice

        case $choice in
            1)
                build_nix_package
                echo ""
                read -p "Press Enter to continue..."
                ;;
            2)
                build_pyinstaller
                echo ""
                read -p "Press Enter to continue..."
                ;;
            3)
                build_zipapp
                echo ""
                read -p "Press Enter to continue..."
                ;;
            4)
                build_all
                echo ""
                read -p "Press Enter to continue..."
                ;;
            q|Q)
                log_info "Exiting..."
                exit 0
                ;;
            *)
                log_error "Invalid choice"
                echo ""
                ;;
        esac
    done
else
    # Non-interactive mode with arguments
    case "$1" in
        nix)
            build_nix_package
            ;;
        pyinstaller)
            build_pyinstaller
            ;;
        zipapp)
            build_zipapp
            ;;
        all)
            build_all
            ;;
        *)
            log_error "Unknown build method: $1"
            echo ""
            echo "Usage: $0 [nix|pyinstaller|zipapp|all]"
            exit 1
            ;;
    esac
fi
