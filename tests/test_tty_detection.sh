#!/usr/bin/env bash
# Test TTY detection in various scenarios

set -e

echo "=== TempleDB TTY Detection Test Suite ==="
echo ""

# Test 1: Show current environment
echo "Test 1: Current Environment Detection"
echo "--------------------------------------"
python3 -c "
import sys
sys.path.insert(0, 'src')
from cli.tty_utils import get_environment_context

context = get_environment_context()
print('Environment:')
for key, value in context.items():
    print(f'  {key}: {value}')
"
echo ""

# Test 2: Claude command should fail in non-TTY
echo "Test 2: Claude Command in Non-TTY"
echo "----------------------------------"
if python3 -m cli claude 2>&1 | grep -q "requires an interactive terminal"; then
    echo "✓ Claude command correctly detected non-TTY environment"
else
    echo "✗ Claude command did not detect non-TTY"
    exit 1
fi
echo ""

# Test 3: TUI command should fail in non-TTY
echo "Test 3: TUI Command in Non-TTY"
echo "-------------------------------"
if python3 -m cli tui 2>&1 | grep -q "requires an interactive terminal"; then
    echo "✓ TUI command correctly detected non-TTY environment"
else
    echo "✗ TUI command did not detect non-TTY"
    exit 1
fi
echo ""

# Test 4: Force override should bypass check
echo "Test 4: Force Override (TEMPLEDB_FORCE_TTY=1)"
echo "----------------------------------------------"
# This should bypass our check and fail at Claude Code itself
if TEMPLEDB_FORCE_TTY=1 timeout 2 python3 -m cli claude 2>&1 | grep -q "requires an interactive terminal"; then
    echo "✗ Force override did not work"
    exit 1
else
    echo "✓ Force override successfully bypassed TTY check"
fi
echo ""

# Test 5: Help should still work (doesn't need TTY)
echo "Test 5: Help Command (No TTY Required)"
echo "---------------------------------------"
if python3 -m cli claude --help 2>&1 | grep -q "claude_args"; then
    echo "✓ Help command works without TTY"
else
    echo "✗ Help command failed"
    exit 1
fi
echo ""

echo "=== All Tests Passed ==="
echo ""
echo "To use in a real terminal:"
echo "  1. Open Alacritty, gnome-terminal, or kitty"
echo "  2. Run: cd /home/zach/templeDB && ./templedb claude"
echo ""
echo "From Emacs:"
echo "  1. Use M-x ansi-term instead of vterm"
echo "  2. Or exit Emacs and run from shell"
