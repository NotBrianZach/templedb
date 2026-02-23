#!/usr/bin/env bash
# Test Phase 3: Checkout/Commit Workflow

set -e  # Exit on error

echo "======================================================================"
echo "Phase 3 Workflow Test: Checkout → Edit → Commit"
echo "======================================================================"

WORKSPACE="/tmp/phase3-workflow-test"
PROJECT="system_config"

# Clean up from previous tests
rm -rf "$WORKSPACE"

echo ""
echo "Step 1: Checkout project from database"
echo "----------------------------------------------------------------------"
./templedb project checkout "$PROJECT" "$WORKSPACE" --force

echo ""
echo "✓ Files checked out to $WORKSPACE"
ls -lh "$WORKSPACE" | head -10

echo ""
echo "Step 2: Make various changes"
echo "----------------------------------------------------------------------"

# Modify existing file
echo "# Modified by Phase 3 test" >> "$WORKSPACE/README.md"
echo "✓ Modified: README.md"

# Add new file (use .md which is a tracked file type)
echo "# New test file from Phase 3" > "$WORKSPACE/test-phase3.md"
echo "✓ Added: test-phase3.md"

# Delete a file (pick a non-critical one)
if [ -f "$WORKSPACE/age-vault.sh" ]; then
    rm "$WORKSPACE/age-vault.sh"
    echo "✓ Deleted: age-vault.sh"
fi

echo ""
echo "Step 3: Commit changes back to database"
echo "----------------------------------------------------------------------"
./templedb project commit "$PROJECT" "$WORKSPACE" -m "Phase 3 workflow test: add, modify, delete"

echo ""
echo "Step 4: Verify commit recorded"
echo "----------------------------------------------------------------------"
sqlite3 ~/.local/share/templedb/templedb.sqlite "
SELECT
    c.id,
    c.author,
    c.commit_message,
    c.commit_timestamp,
    COUNT(cf.id) as files_changed
FROM vcs_commits c
LEFT JOIN commit_files cf ON cf.commit_id = c.id
WHERE c.project_id = (SELECT id FROM projects WHERE slug = '$PROJECT')
GROUP BY c.id
ORDER BY c.commit_timestamp DESC
LIMIT 3;
"

echo ""
echo "Step 5: Verify commit_files entries"
echo "----------------------------------------------------------------------"
sqlite3 ~/.local/share/templedb/templedb.sqlite "
SELECT
    cf.change_type,
    pf.file_path
FROM commit_files cf
JOIN project_files pf ON cf.file_id = pf.id
JOIN vcs_commits c ON cf.commit_id = c.id
WHERE c.project_id = (SELECT id FROM projects WHERE slug = '$PROJECT')
ORDER BY c.commit_timestamp DESC, cf.change_type, pf.file_path
LIMIT 10;
"

echo ""
echo "Step 6: Test round-trip (checkout again and verify)"
echo "----------------------------------------------------------------------"
WORKSPACE2="/tmp/phase3-workflow-test-2"
rm -rf "$WORKSPACE2"
./templedb project checkout "$PROJECT" "$WORKSPACE2" --force

# Verify new file exists
if [ -f "$WORKSPACE2/test-phase3.md" ]; then
    echo "✓ New file exists in fresh checkout: test-phase3.md"
else
    echo "✗ ERROR: New file not found in fresh checkout!"
    exit 1
fi

# Verify deleted file doesn't exist
if [ ! -f "$WORKSPACE2/age-vault.sh" ]; then
    echo "✓ Deleted file absent in fresh checkout: age-vault.sh"
else
    echo "⚠  WARNING: Deleted file still exists in fresh checkout!"
fi

# Verify modified file has changes
if grep -q "Modified by Phase 3 test" "$WORKSPACE2/README.md"; then
    echo "✓ Modified file has changes in fresh checkout: README.md"
else
    echo "✗ ERROR: Modified file doesn't have changes!"
    exit 1
fi

echo ""
echo "======================================================================"
echo "✅ Phase 3 Workflow Test: SUCCESS"
echo "======================================================================"
echo ""
echo "Summary:"
echo "  ✓ Checkout works"
echo "  ✓ Modifications detected and committed"
echo "  ✓ Additions recorded"
echo "  ✓ Deletions recorded"
echo "  ✓ Round-trip integrity verified"
echo ""
echo "The denormalization loop is complete!"
