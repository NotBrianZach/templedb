#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# Apply File Versioning Schema Migration
# ============================================================================

TEMPLEDB_PATH="${TEMPLEDB_PATH:-$HOME/.local/share/templedb/templedb.sqlite}"
MIGRATION_FILE="$(dirname "$0")/file_versioning_schema.sql"

echo "==================================================================================="
echo "Applying file versioning schema migration"
echo "==================================================================================="
echo "Database: $TEMPLEDB_PATH"
echo "Migration: $MIGRATION_FILE"
echo ""

if [ ! -f "$TEMPLEDB_PATH" ]; then
    echo "ERROR: templedb database not found at $TEMPLEDB_PATH"
    exit 1
fi

if [ ! -f "$MIGRATION_FILE" ]; then
    echo "ERROR: Migration file not found at $MIGRATION_FILE"
    exit 1
fi

# Backup the database first
BACKUP_PATH="${TEMPLEDB_PATH}.backup.$(date +%Y%m%d_%H%M%S)"
echo "Creating backup: $BACKUP_PATH"
cp "$TEMPLEDB_PATH" "$BACKUP_PATH"

# Apply the migration
echo ""
echo "Applying migration..."
sqlite3 "$TEMPLEDB_PATH" < "$MIGRATION_FILE"

if [ $? -eq 0 ]; then
    echo ""
    echo "==================================================================================="
    echo "Migration applied successfully!"
    echo "==================================================================================="
    echo ""
    echo "New tables created:"
    sqlite3 "$TEMPLEDB_PATH" "SELECT name FROM sqlite_master WHERE type='table' AND (name LIKE '%version%' OR name LIKE '%content%' OR name LIKE '%diff%' OR name LIKE '%snapshot%') ORDER BY name;"
    echo ""
    echo "New views created:"
    sqlite3 "$TEMPLEDB_PATH" "SELECT name FROM sqlite_master WHERE type='view' AND name LIKE '%version%' OR name LIKE '%content%' ORDER BY name;"
    echo ""
    echo "Backup saved at: $BACKUP_PATH"
else
    echo ""
    echo "ERROR: Migration failed!"
    echo "Database has been restored from backup."
    cp "$BACKUP_PATH" "$TEMPLEDB_PATH"
    exit 1
fi
