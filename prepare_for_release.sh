#!/usr/bin/env bash
#
# Prepare TempleDB for GitHub release
# This script sanitizes personal data from documentation
#
# Usage: ./prepare_for_release.sh
#

set -euo pipefail

echo "🧹 TempleDB - Prepare for GitHub Release"
echo ""

# Backup originals
BACKUP_DIR=".release-backup-$(date +%Y%m%d_%H%M%S)"
echo "📦 Creating backup in: $BACKUP_DIR"
mkdir -p "$BACKUP_DIR"

# Files to sanitize
FILES_TO_CLEAN=(
    "README.md"
    "DESIGN_PHILOSOPHY.md"
    "CHANGELOG.md"
    "QUICKSTART.md"
    "EXAMPLES.md"
    "GUIDE.md"
    "ADVANCED.md"
    "FILES.md"
    "MIGRATIONS.md"
    "VERSION_CONSOLIDATION_PLAN.md"
    "SCHEMA_CHANGES.md"
    "CONSOLIDATION_SUMMARY.md"
    "cathedral/README.md"
    "completions/README.md"
)

# Backup files
for file in "${FILES_TO_CLEAN[@]}"; do
    if [ -f "$file" ]; then
        cp "$file" "$BACKUP_DIR/"
        echo "   ✅ Backed up: $file"
    fi
done

echo ""
echo "🔍 Sanitizing documentation..."
echo ""

# Replacements
declare -A REPLACEMENTS=(
    ["/home/zach"]="/home/user"
    ["zach"]="user"
    ["zMothership2"]="hostname"
    ["woofs_projects"]="my-project"
    ["woofsDB"]="example-db"
    ["system_config"]="my-config"
)

# Apply replacements
for file in "${FILES_TO_CLEAN[@]}"; do
    if [ ! -f "$file" ]; then
        continue
    fi

    echo "   🔧 Sanitizing: $file"

    for pattern in "${!REPLACEMENTS[@]}"; do
        replacement="${REPLACEMENTS[$pattern]}"
        sed -i "s|${pattern}|${replacement}|g" "$file"
    done
done

echo ""
echo "✅ Documentation sanitized!"
echo ""
echo "📋 Next Steps:"
echo ""
echo "1. Review changes:"
echo "   git diff"
echo ""
echo "2. If satisfied, continue with release:"
echo "   git add ."
echo "   git commit -m \"Prepare for initial release\""
echo ""
echo "3. If not satisfied, restore from backup:"
echo "   cp $BACKUP_DIR/* ."
echo ""
echo "4. Initialize git repository:"
echo "   git init"
echo "   git add ."
echo "   git commit -m \"Initial commit - TempleDB v1.0.0\""
echo ""
echo "5. Create GitHub repository and push:"
echo "   gh repo create templedb --public --source=. --remote=origin"
echo "   git push -u origin main"
echo ""
echo "⚠️  Backup saved in: $BACKUP_DIR"
echo ""
