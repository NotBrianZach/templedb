#!/usr/bin/env bash
# Build TempleDB TUI as standalone binary
# No dependencies required to run the resulting binary!

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build"
DIST_DIR="$SCRIPT_DIR/dist"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${CYAN}$1${NC}"; }
log_success() { echo -e "${GREEN}✓ $1${NC}"; }
log_error() { echo -e "${RED}✗ $1${NC}" >&2; }

# Check if PyInstaller is available
if ! command -v pyinstaller &> /dev/null; then
    log_error "PyInstaller not found"
    echo ""
    echo "Install with one of:"
    echo "  nix-shell -p python311Packages.pyinstaller"
    echo "  pip install --user pyinstaller"
    exit 1
fi

# Check if dependencies are available
log_info "Checking Python dependencies..."
python3 << 'EOF'
import sys
try:
    import textual
    import rich
    print("✓ All dependencies available")
except ImportError as e:
    print(f"✗ Missing dependency: {e}")
    print("\nInstall with:")
    print("  nix-shell -p python311Packages.textual python311Packages.rich")
    print("  OR")
    print("  pip install --user textual rich")
    sys.exit(1)
EOF

if [ $? -ne 0 ]; then
    exit 1
fi

# Clean previous builds
log_info "Cleaning previous builds..."
rm -rf "$BUILD_DIR" "$DIST_DIR"
mkdir -p "$BUILD_DIR" "$DIST_DIR"

# Create PyInstaller spec file
log_info "Creating PyInstaller specification..."
cat > "$BUILD_DIR/templedb-tui.spec" << 'SPEC_EOF'
# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['../src/templedb_tui.py'],
    pathex=[],
    binaries=[],
    datas=[
        # Include any data files here if needed
    ],
    hiddenimports=[
        'textual',
        'textual.app',
        'textual.binding',
        'textual.containers',
        'textual.widgets',
        'textual.screen',
        'rich',
        'rich.panel',
        'rich.table',
        'rich.text',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Exclude unnecessary modules to reduce size
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PyQt5',
        'tkinter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='templedb-tui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
SPEC_EOF

log_success "Spec file created"

# Build binary
log_info "Building standalone binary..."
log_info "This may take a few minutes..."
cd "$BUILD_DIR"

pyinstaller --clean --noconfirm templedb-tui.spec 2>&1 | \
    grep -v "^[0-9]* INFO:" | \
    grep -v "^[0-9]* WARNING: lib not found:" || true

if [ ! -f "$DIST_DIR/templedb-tui" ]; then
    log_error "Build failed - binary not created"
    exit 1
fi

# Test binary
log_info "Testing binary..."
if timeout 1 "$DIST_DIR/templedb-tui" --help 2>&1 | grep -q "Database not found"; then
    log_success "Binary works!"
else
    log_error "Binary test failed"
    exit 1
fi

# Get binary size
BINARY_SIZE=$(du -h "$DIST_DIR/templedb-tui" | cut -f1)

log_success "Build complete!"
echo ""
echo "Binary location: $DIST_DIR/templedb-tui"
echo "Binary size: $BINARY_SIZE"
echo ""
echo "To install system-wide:"
echo "  sudo cp $DIST_DIR/templedb-tui /usr/local/bin/"
echo ""
echo "To run:"
echo "  $DIST_DIR/templedb-tui"
echo ""
echo "Note: No Python or dependencies required on target system!"
