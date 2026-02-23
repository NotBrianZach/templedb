#!/usr/bin/env bash
# Test that snapshot updates after commit prevent false conflicts
# This tests the fix for Issue #1

set -e

echo "======================================================================"
echo "Test: Snapshot Updates After Commit (Issue #1 Fix)"
echo "======================================================================"

PROJECT="system_config"
WORKSPACE="/tmp/test-snapshot-update"

# Clean up
rm -rf "$WORKSPACE"

echo ""
echo "Step 1: Initial checkout"
echo "----------------------------------------------------------------------"
./templedb project checkout "$PROJECT" "$WORKSPACE" --force

echo ""
echo "Step 2: First commit - modify README"
echo "----------------------------------------------------------------------"
echo "# First change" >> "$WORKSPACE/README.md"
./templedb project commit "$PROJECT" "$WORKSPACE" -m "First commit to README"

echo ""
echo "Step 3: Second commit - modify README AGAIN"
echo "----------------------------------------------------------------------"
echo "# Second change" >> "$WORKSPACE/README.md"

echo ""
echo "Attempting second commit (should NOT show conflict)..."
set +e
./templedb project commit "$PROJECT" "$WORKSPACE" -m "Second commit to README"
EXIT_CODE=$?
set -e

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "✅ TEST PASSED: No false conflict detected!"
    echo "   Snapshots were properly updated after first commit"
else
    echo ""
    echo "❌ TEST FAILED: Commit failed (possible false conflict)"
    echo "   Snapshots may not have been updated"
    exit 1
fi

echo ""
echo "Step 4: Third commit - verify still working"
echo "----------------------------------------------------------------------"
echo "# Third change" >> "$WORKSPACE/README.md"
./templedb project commit "$PROJECT" "$WORKSPACE" -m "Third commit to README"

echo ""
echo "✅ ALL TESTS PASSED"
echo "   Multiple consecutive commits work without false conflicts"

# Cleanup
rm -rf "$WORKSPACE"
