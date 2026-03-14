#!/usr/bin/env bash
# Test script for vterm Claude Code support

set -e

echo "=== TempleDB vterm Claude Code Support Test ==="
echo ""

# Test 1: Verify vterm detection
echo "Test 1: Environment Detection"
echo "------------------------------"
python3 -c "
import sys, os
sys.path.insert(0, 'src')
from cli.tty_utils import is_emacs_vterm, is_tty

print(f'Running in vterm: {is_emacs_vterm()}')
print(f'Is TTY: {is_tty()}')
print(f'INSIDE_EMACS={os.environ.get(\"INSIDE_EMACS\", \"not set\")}')
"
echo ""

# Test 2: Check if script command is available
echo "Test 2: Check 'script' Command Availability"
echo "--------------------------------------------"
if which script > /dev/null 2>&1; then
    echo "✓ script command is available: $(which script)"
    script --version 2>&1 | head -1 || echo "(version info not available)"
else
    echo "✗ script command not found - PTY wrapper won't work"
    exit 1
fi
echo ""

# Test 3: Test script wrapper with simple command
echo "Test 3: Test 'script' Wrapper with Echo"
echo "----------------------------------------"
if script -q -c "echo 'PTY wrapper test successful'" /dev/null 2>&1 | grep -q "successful"; then
    echo "✓ script wrapper works correctly"
else
    echo "✗ script wrapper failed"
    exit 1
fi
echo ""

# Test 4: Check Claude Code availability
echo "Test 4: Check Claude Code Installation"
echo "---------------------------------------"
if which claude > /dev/null 2>&1; then
    echo "✓ claude command found: $(which claude)"
    claude --version 2>&1 | head -1
else
    echo "⚠  claude command not found"
    echo "   Install from: https://github.com/anthropics/claude-code"
    echo "   Skipping actual Claude Code tests"
    SKIP_CLAUDE=1
fi
echo ""

# Test 5: Dry-run test
echo "Test 5: Dry-Run Test (Show What Would Execute)"
echo "-----------------------------------------------"
./templedb claude --dry-run 2>&1
echo ""

# Test 6: Test with claude --version (if available)
if [ -z "$SKIP_CLAUDE" ]; then
    echo "Test 6: Test Wrapper with Claude Code --version"
    echo "------------------------------------------------"
    if timeout 5 script -q -c "claude --version" /dev/null 2>&1 | grep -q "Claude Code"; then
        echo "✓ Claude Code works through script wrapper"
    else
        echo "✗ Claude Code through wrapper failed"
        exit 1
    fi
    echo ""
fi

echo "=== All Tests Passed ==="
echo ""
echo "Ready to use Claude Code in vterm!"
echo ""
echo "Try it now:"
echo "  ./templedb claude"
echo ""
echo "You should see:"
echo "  ⚡ Detected Emacs vterm - using PTY wrapper for Claude Code"
echo "  [Claude Code launches successfully]"
