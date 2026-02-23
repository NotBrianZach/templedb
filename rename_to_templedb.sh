#!/usr/bin/env bash
# Rename all references from templeDB/templedb to templeDB/templedb

echo "🔄 Renaming templeDB → templeDB across all files..."
echo ""

cd /home/zach/templeDB

# Update shell scripts
echo "📝 Updating shell scripts..."
for file in *.sh; do
    if [ -f "$file" ]; then
        sed -i 's|/templedb/|/templedb/|g' "$file"
        sed -i 's|templedb\.sqlite|templedb.sqlite|g' "$file"
        sed -i 's|TEMPLEDB_PATH|TEMPLEDB_PATH|g' "$file"
        sed -i 's|templedb|templedb|g' "$file"
        sed -i 's|templeDB|templeDB|g' "$file"
        sed -i 's|~/templeDB|~/templeDB|g' "$file"
        echo "  ✓ $file"
    fi
done

# Update JavaScript files
echo "📝 Updating JavaScript files..."
for file in src/*.cjs; do
    if [ -f "$file" ]; then
        sed -i 's|/templedb/|/templedb/|g' "$file"
        sed -i 's|templedb\.sqlite|templedb.sqlite|g' "$file"
        sed -i 's|TEMPLEDB_PATH|TEMPLEDB_PATH|g' "$file"
        sed -i "s|'templedb'|'templedb'|g" "$file"
        sed -i 's|templeDB|templeDB|g' "$file"
        echo "  ✓ $file"
    fi
done

# Update Python files
echo "📝 Updating Python files..."
for file in src/*.py; do
    if [ -f "$file" ]; then
        sed -i 's|/templedb/|/templedb/|g' "$file"
        sed -i 's|templedb\.sqlite|templedb.sqlite|g' "$file"
        sed -i 's|templedb|templedb|g' "$file"
        sed -i 's|templeDB|templeDB|g' "$file"
        sed -i 's|ProjectDB|TempleDB|g' "$file"
        echo "  ✓ $file"
    fi
done

# Update markdown files
echo "📝 Updating markdown files..."
for file in *.md; do
    if [ -f "$file" ]; then
        sed -i 's|templeDB|templeDB|g' "$file"
        sed -i 's|ProjectDB|TempleDB|g' "$file"
        sed -i 's|templedb|templedb|g' "$file"
        sed -i 's|~/templeDB|~/templeDB|g' "$file"
        echo "  ✓ $file"
    fi
done

# Update launcher script
if [ -f "templedb-tui" ]; then
    sed -i 's|templeDB|templeDB|g' templedb-tui
    sed -i 's|templedb|templedb|g' templedb-tui
    mv templedb-tui templedb-tui
    echo "  ✓ Renamed templedb-tui → templedb-tui"
fi

echo ""
echo "✅ Rename complete!"
echo ""
echo "Next steps:"
echo "  cd ~/templeDB"
echo "  ./templedb-tui  # Launch TUI"
echo "  ./status.sh     # View status"
echo ""
