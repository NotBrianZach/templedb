#!/usr/bin/env bash
# Build TempleDB TUI as a Python zipapp
# Bundles all Python code into a single executable file
# Still requires Python and dependencies, but much simpler distribution

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="$SCRIPT_DIR/build/zipapp"
OUTPUT="$SCRIPT_DIR/dist/templedb-tui"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${CYAN}$1${NC}"; }
log_success() { echo -e "${GREEN}✓ $1${NC}"; }
log_error() { echo -e "${RED}✗ $1${NC}" >&2; }

# Clean and create build directory
log_info "Preparing build directory..."
rm -rf "$BUILD_DIR" "$SCRIPT_DIR/dist"
mkdir -p "$BUILD_DIR" "$SCRIPT_DIR/dist"

# Copy source files
log_info "Copying source files..."
cp -r src/* "$BUILD_DIR/"

# Create __main__.py entry point
log_info "Creating entry point..."
cat > "$BUILD_DIR/__main__.py" << 'EOF'
#!/usr/bin/env python3
"""TempleDB TUI - Zipapp Entry Point"""
import sys
import os

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

if __name__ == '__main__':
    import templedb_tui
    exit(templedb_tui.main())
EOF

# Build zipapp
log_info "Building zipapp..."
python3 -m zipapp "$BUILD_DIR" \
    --python="/usr/bin/env python3" \
    --output="$OUTPUT" \
    --compress

if [ ! -f "$OUTPUT" ]; then
    log_error "Build failed"
    exit 1
fi

# Make executable
chmod +x "$OUTPUT"

# Get size
SIZE=$(du -h "$OUTPUT" | cut -f1)

log_success "Build complete!"
echo ""
echo "Executable: $OUTPUT"
echo "Size: $SIZE"
echo ""
echo "Requirements:"
echo "  - Python 3.11+"
echo "  - textual (python311Packages.textual)"
echo "  - rich (python311Packages.rich)"
echo ""
echo "To install system-wide:"
echo "  sudo cp $OUTPUT /usr/local/bin/templedb-tui"
echo ""
echo "To run:"
echo "  $OUTPUT"
echo ""
