#!/usr/bin/env bash
# Simple dev server launcher for woofs_projects
# Usage: ./scripts/dev-server.sh [target]

set -e

PROJECT="woofs_projects"
TARGET="${1:-staging}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLEDB_ROOT="$(dirname "$SCRIPT_DIR")"

echo "🚀 Starting $PROJECT development server with $TARGET environment..."
echo

# Export environment variables
cd "$TEMPLEDB_ROOT"
ENV_VARS=$(./templedb env export "$PROJECT" --target "$TARGET" --format shell 2>/dev/null)

if [ $? -ne 0 ]; then
    echo "❌ Failed to load environment variables"
    exit 1
fi

echo "✅ Loaded environment from TempleDB ($TARGET)"
echo

# Navigate to shopUI and start dev server
cd "$TEMPLEDB_ROOT/../projects/$PROJECT/shopUI"

if [ ! -f "package.json" ]; then
    echo "❌ shopUI directory not found"
    exit 1
fi

echo "============================================================"
echo "🏃 Starting webpack dev server..."
echo "   Directory: $(pwd)"
echo "   Target: $TARGET"
echo "============================================================"
echo

# Export environment and start server
eval "$ENV_VARS"
exec npm start
