#!/usr/bin/env bash
#
# Initialize TempleDB with example projects
# Usage: ./init_example_database.sh
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DB_DIR="${TEMPLEDB_PATH:-$HOME/.local/share/templedb}"
DB_PATH="$DB_DIR/templedb.sqlite"

echo "🏛️  TempleDB - Example Database Initialization"
echo ""

# Check if database already exists
if [ -f "$DB_PATH" ]; then
    echo "⚠️  Database already exists at: $DB_PATH"
    read -p "Do you want to REMOVE it and start fresh? (yes/NO): " confirm

    if [ "$confirm" != "yes" ]; then
        echo "❌ Cancelled. Your existing database was not modified."
        exit 0
    fi

    echo "🗑️  Removing existing database..."
    rm -f "$DB_PATH"
    rm -f "${DB_PATH}-journal"
    rm -f "${DB_PATH}-wal"
    rm -f "${DB_PATH}-shm"
fi

# Create database directory
mkdir -p "$DB_DIR"

echo "📦 Creating fresh database..."
echo ""

# Initialize database schema
# The database will be created automatically on first use
# Just verify templedb is available
if ! command -v templedb &> /dev/null; then
    echo "❌ Error: templedb command not found"
    echo "   Make sure templedb is installed and in your PATH"
    exit 1
fi

# Get templedb status to initialize database
templedb status > /dev/null 2>&1 || true

echo "✅ Database initialized at: $DB_PATH"
echo ""

# Import example projects
echo "📁 Importing example projects..."
echo ""

EXAMPLES_DIR="$SCRIPT_DIR/examples"

if [ ! -d "$EXAMPLES_DIR" ]; then
    echo "❌ Error: Examples directory not found: $EXAMPLES_DIR"
    exit 1
fi

# Import each example project
for project_dir in "$EXAMPLES_DIR"/*; do
    if [ -d "$project_dir" ]; then
        project_name=$(basename "$project_dir")
        echo "   📦 Importing: $project_name"

        # Import project
        if templedb project import "$project_dir" "$project_name" 2>&1 | grep -v "^$"; then
            echo "      ✅ Imported successfully"
        else
            echo "      ⚠️  Import completed with warnings"
        fi
    fi
done

echo ""
echo "✅ All example projects imported!"
echo ""

# List imported projects
echo "📋 Imported Projects:"
templedb project list

echo ""
echo "🎯 Next Steps:"
echo ""
echo "1. View project details:"
echo "   templedb project list"
echo ""
echo "2. Check version control:"
echo "   templedb vcs status todo-api"
echo "   templedb vcs log todo-api"
echo ""
echo "3. Setup environment:"
echo "   templedb env detect todo-api"
echo "   templedb env new todo-api dev"
echo "   templedb env enter todo-api dev"
echo ""
echo "4. Query with SQL:"
echo "   sqlite3 $DB_PATH \"SELECT * FROM projects\""
echo ""
echo "5. Launch TUI:"
echo "   templedb tui"
echo ""
echo "📚 Documentation:"
echo "   - README.md - Overview"
echo "   - QUICKSTART.md - Getting started"
echo "   - WORKFLOW.md - Complete workflow guide"
echo "   - examples/*/README.md - Example project guides"
echo ""
echo "✅ TempleDB is ready to use!"
echo ""
