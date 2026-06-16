#!/usr/bin/env bash
# Wrapper for templedb direnv that ensures it runs in nix environment
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run templedb direnv in the nix environment where cryptography is available
cd "$SCRIPT_DIR"
nix develop --command bash -c "cd '$SCRIPT_DIR' && ./templedb direnv $*" 2>/dev/null || {
    # Fallback: if nix develop fails, just export nothing
    echo "# Warning: templedb direnv failed, no environment loaded" >&2
    true
}
