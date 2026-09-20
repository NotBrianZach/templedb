#!/usr/bin/env bash
#
# Setup automated cloud backups for TempleDB
#
# This script helps you set up scheduled backups using cron.
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${BLUE}TempleDB Automated Backup Setup${NC}"
echo "========================================"
echo

# Check if templedb is installed
if [ ! -x "$REPO_DIR/templedb" ]; then
    echo -e "${RED}✗ templedb executable not found${NC}"
    echo "Please ensure TempleDB is properly installed"
    exit 1
fi

TEMPLEDB="$REPO_DIR/templedb"

# Ask for provider
echo "Select backup provider:"
echo "  1) Google Drive"
echo "  2) Local Filesystem"
echo "  3) AWS S3 (not yet implemented)"
echo "  4) Dropbox (not yet implemented)"
echo

read -p "Enter choice [1-4]: " PROVIDER_CHOICE

case $PROVIDER_CHOICE in
    1)
        PROVIDER="gdrive"
        PROVIDER_NAME="Google Drive"
        ;;
    2)
        PROVIDER="local"
        PROVIDER_NAME="Local Filesystem"
        ;;
    3)
        echo -e "${RED}✗ AWS S3 provider not yet implemented${NC}"
        exit 1
        ;;
    4)
        echo -e "${RED}✗ Dropbox provider not yet implemented${NC}"
        exit 1
        ;;
    *)
        echo -e "${RED}✗ Invalid choice${NC}"
        exit 1
        ;;
esac

echo
echo -e "${GREEN}✓ Selected: $PROVIDER_NAME${NC}"
echo

# Test connection
echo "Testing connection to $PROVIDER_NAME..."
if $TEMPLEDB cloud-backup test -p $PROVIDER; then
    echo -e "${GREEN}✓ Connection successful${NC}"
else
    echo -e "${RED}✗ Connection failed${NC}"
    echo "Please run setup first: $TEMPLEDB cloud-backup setup $PROVIDER"
    exit 1
fi

echo

# Ask for schedule
echo "Select backup schedule:"
echo "  1) Daily at 2:00 AM"
echo "  2) Daily at specific time"
echo "  3) Every 6 hours"
echo "  4) Every 12 hours"
echo "  5) Custom cron expression"
echo

read -p "Enter choice [1-5]: " SCHEDULE_CHOICE

case $SCHEDULE_CHOICE in
    1)
        CRON_SCHEDULE="0 2 * * *"
        SCHEDULE_DESC="daily at 2:00 AM"
        ;;
    2)
        read -p "Enter hour (0-23): " HOUR
        CRON_SCHEDULE="0 $HOUR * * *"
        SCHEDULE_DESC="daily at $HOUR:00"
        ;;
    3)
        CRON_SCHEDULE="0 */6 * * *"
        SCHEDULE_DESC="every 6 hours"
        ;;
    4)
        CRON_SCHEDULE="0 */12 * * *"
        SCHEDULE_DESC="every 12 hours"
        ;;
    5)
        read -p "Enter cron expression: " CRON_SCHEDULE
        SCHEDULE_DESC="custom schedule"
        ;;
    *)
        echo -e "${RED}✗ Invalid choice${NC}"
        exit 1
        ;;
esac

echo
echo -e "${GREEN}✓ Schedule: $SCHEDULE_DESC${NC}"
echo

# Create log directory
LOG_DIR="$HOME/.local/share/templedb/logs"
mkdir -p "$LOG_DIR"

# Create cron job
CRON_COMMAND="$TEMPLEDB cloud-backup backup -p $PROVIDER >> $LOG_DIR/backup.log 2>&1"
CRON_LINE="$CRON_SCHEDULE $CRON_COMMAND"

# Check if cron job already exists
if crontab -l 2>/dev/null | grep -F "$TEMPLEDB cloud-backup" > /dev/null; then
    echo -e "${YELLOW}Warning: Existing TempleDB backup cron job found${NC}"
    read -p "Remove existing job and add new one? [y/N]: " REPLACE

    if [[ ! $REPLACE =~ ^[Yy]$ ]]; then
        echo "Cancelled"
        exit 0
    fi

    # Remove existing job
    crontab -l 2>/dev/null | grep -v "$TEMPLEDB cloud-backup" | crontab -
    echo -e "${GREEN}✓ Removed existing cron job${NC}"
fi

# Add new cron job
(crontab -l 2>/dev/null; echo "# TempleDB automated backup ($SCHEDULE_DESC)"; echo "$CRON_LINE") | crontab -

echo
echo -e "${GREEN}✓ Automated backup configured successfully!${NC}"
echo
echo "Details:"
echo "  Provider: $PROVIDER_NAME"
echo "  Schedule: $SCHEDULE_DESC"
echo "  Cron expression: $CRON_SCHEDULE"
echo "  Log file: $LOG_DIR/backup.log"
echo
echo "Commands:"
echo "  View logs: tail -f $LOG_DIR/backup.log"
echo "  List cron jobs: crontab -l"
echo "  Edit cron jobs: crontab -e"
echo "  Remove cron job: crontab -l | grep -v 'TempleDB automated backup' | crontab -"
echo
echo "Test backup manually:"
echo "  $TEMPLEDB cloud-backup backup -p $PROVIDER"
echo
