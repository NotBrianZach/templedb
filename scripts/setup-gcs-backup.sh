#!/bin/bash
set -e

# TempleDB Google Cloud Storage Backup Setup Script
# Makes it easy to configure automatic backups to GCS

echo "=============================================================================="
echo "TempleDB Google Cloud Storage Backup Setup"
echo "=============================================================================="
echo

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}✗${NC} Google Cloud SDK (gcloud) is not installed"
    echo
    echo "Install it with:"
    echo "  # On NixOS:"
    echo "  nix-shell -p google-cloud-sdk"
    echo
    echo "  # On other systems:"
    echo "  curl https://sdk.cloud.google.com | bash"
    echo
    exit 1
fi

echo -e "${GREEN}✓${NC} Google Cloud SDK is installed"

# Check if authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" &> /dev/null; then
    echo -e "${YELLOW}!${NC} Not authenticated with Google Cloud"
    echo
    echo "Authenticating now..."
    gcloud auth login
    gcloud auth application-default login
fi

ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format="value(account)" | head -1)
echo -e "${GREEN}✓${NC} Authenticated as: $ACCOUNT"

# Get or set project
PROJECT_ID=$(gcloud config get-value project 2>/dev/null)

if [ -z "$PROJECT_ID" ]; then
    echo
    echo "Enter your Google Cloud Project ID:"
    read -r PROJECT_ID
    gcloud config set project "$PROJECT_ID"
fi

echo -e "${GREEN}✓${NC} Project: $PROJECT_ID"
echo

# Create bucket name
DEFAULT_BUCKET="templedb-backups-$(whoami)-$(date +%Y)"
echo "Enter GCS bucket name (must be globally unique):"
echo "Default: $DEFAULT_BUCKET"
read -r BUCKET_NAME

if [ -z "$BUCKET_NAME" ]; then
    BUCKET_NAME="$DEFAULT_BUCKET"
fi

# Check if bucket exists
if gsutil ls "gs://$BUCKET_NAME" &> /dev/null; then
    echo -e "${GREEN}✓${NC} Bucket gs://$BUCKET_NAME already exists"
else
    echo
    echo "Creating bucket gs://$BUCKET_NAME..."

    # Choose region
    echo
    echo "Select region for bucket:"
    echo "  1) us-central1 (Iowa, USA)"
    echo "  2) us-east1 (South Carolina, USA)"
    echo "  3) us-west1 (Oregon, USA)"
    echo "  4) europe-west1 (Belgium)"
    echo "  5) europe-west2 (London, UK)"
    echo "  6) asia-east1 (Taiwan)"
    echo "  7) Custom region"

    read -r REGION_CHOICE

    case $REGION_CHOICE in
        1) REGION="us-central1" ;;
        2) REGION="us-east1" ;;
        3) REGION="us-west1" ;;
        4) REGION="europe-west1" ;;
        5) REGION="europe-west2" ;;
        6) REGION="asia-east1" ;;
        7)
            echo "Enter custom region:"
            read -r REGION
            ;;
        *) REGION="us-central1" ;;
    esac

    # Create bucket
    if gsutil mb -p "$PROJECT_ID" -c STANDARD -l "$REGION" "gs://$BUCKET_NAME"; then
        echo -e "${GREEN}✓${NC} Bucket created: gs://$BUCKET_NAME"

        # Enable versioning
        gsutil versioning set on "gs://$BUCKET_NAME"
        echo -e "${GREEN}✓${NC} Versioning enabled"

        # Set lifecycle policy (delete after 90 days)
        cat > /tmp/lifecycle.json << 'EOF'
{
  "lifecycle": {
    "rule": [
      {
        "action": {"type": "Delete"},
        "condition": {
          "age": 90
        }
      }
    ]
  }
}
EOF
        gsutil lifecycle set /tmp/lifecycle.json "gs://$BUCKET_NAME"
        rm /tmp/lifecycle.json
        echo -e "${GREEN}✓${NC} Lifecycle policy set (90-day retention)"
    else
        echo -e "${RED}✗${NC} Failed to create bucket"
        exit 1
    fi
fi

# Create configuration directory
CONFIG_DIR="$HOME/.config/templedb"
mkdir -p "$CONFIG_DIR"

# Create configuration file
CONFIG_FILE="$CONFIG_DIR/backup-gcs.json"

echo
echo "Creating configuration file: $CONFIG_FILE"

cat > "$CONFIG_FILE" << EOF
{
  "provider": "gcs",
  "bucket_name": "$BUCKET_NAME",
  "project_id": "$PROJECT_ID",
  "credentials_path": null,
  "prefix": "templedb/backups/",
  "compression": true,
  "encryption": false,
  "retention_days": 90,
  "enable_versioning": true
}
EOF

chmod 600 "$CONFIG_FILE"
echo -e "${GREEN}✓${NC} Configuration file created"

# Test connection
echo
echo "Testing connection..."
if ./templedb backup cloud test gcs --config "$CONFIG_FILE"; then
    echo -e "${GREEN}✓${NC} Connection test successful!"
else
    echo -e "${RED}✗${NC} Connection test failed"
    exit 1
fi

# Create backup script
BACKUP_SCRIPT="$HOME/bin/templedb-backup.sh"
mkdir -p "$HOME/bin"

echo
echo "Creating backup script: $BACKUP_SCRIPT"

cat > "$BACKUP_SCRIPT" << 'SCRIPT_EOF'
#!/bin/bash

# TempleDB automatic backup to Google Cloud Storage

LOG_FILE="$HOME/.local/share/templedb/backup.log"
CONFIG="$HOME/.config/templedb/backup-gcs.json"
TEMPLEDB="$HOME/templeDB/templedb"

echo "[$(date)] Starting backup..." >> "$LOG_FILE"

if "$TEMPLEDB" backup cloud push gcs --config "$CONFIG" >> "$LOG_FILE" 2>&1; then
    echo "[$(date)] ✅ Backup successful" >> "$LOG_FILE"

    # Cleanup old backups
    "$TEMPLEDB" backup cloud cleanup gcs --days 30 --config "$CONFIG" >> "$LOG_FILE" 2>&1
else
    echo "[$(date)] ❌ Backup failed" >> "$LOG_FILE"
    exit 1
fi
SCRIPT_EOF

chmod +x "$BACKUP_SCRIPT"
echo -e "${GREEN}✓${NC} Backup script created"

# Offer to set up cron
echo
echo "Would you like to set up automatic daily backups via cron? (y/n)"
read -r SETUP_CRON

if [ "$SETUP_CRON" = "y" ] || [ "$SETUP_CRON" = "Y" ]; then
    echo
    echo "Select backup frequency:"
    echo "  1) Daily at 2:00 AM"
    echo "  2) Every 6 hours"
    echo "  3) Every 12 hours"
    echo "  4) Custom schedule"

    read -r CRON_CHOICE

    case $CRON_CHOICE in
        1) CRON_SCHEDULE="0 2 * * *" ;;
        2) CRON_SCHEDULE="0 */6 * * *" ;;
        3) CRON_SCHEDULE="0 */12 * * *" ;;
        4)
            echo "Enter cron schedule (e.g., '0 2 * * *' for daily at 2 AM):"
            read -r CRON_SCHEDULE
            ;;
        *) CRON_SCHEDULE="0 2 * * *" ;;
    esac

    # Add to crontab
    CRON_LINE="$CRON_SCHEDULE $BACKUP_SCRIPT"

    # Check if already in crontab
    if crontab -l 2>/dev/null | grep -q "$BACKUP_SCRIPT"; then
        echo -e "${YELLOW}!${NC} Cron job already exists"
    else
        (crontab -l 2>/dev/null; echo "$CRON_LINE") | crontab -
        echo -e "${GREEN}✓${NC} Cron job added"
    fi

    # Show current crontab
    echo
    echo "Current crontab:"
    crontab -l | grep templedb
fi

# Test backup
echo
echo "Would you like to create a test backup now? (y/n)"
read -r TEST_BACKUP

if [ "$TEST_BACKUP" = "y" ] || [ "$TEST_BACKUP" = "Y" ]; then
    echo
    echo "Creating test backup..."
    if ./templedb backup cloud push gcs --config "$CONFIG_FILE"; then
        echo -e "${GREEN}✓${NC} Test backup successful!"
        echo
        echo "Verifying backup in cloud..."
        ./templedb backup cloud status gcs --config "$CONFIG_FILE"
    else
        echo -e "${RED}✗${NC} Test backup failed"
    fi
fi

echo
echo "=============================================================================="
echo "Setup Complete! 🎉"
echo "=============================================================================="
echo
echo "Configuration file: $CONFIG_FILE"
echo "Backup script:      $BACKUP_SCRIPT"
echo "GCS Bucket:         gs://$BUCKET_NAME"
echo
echo "Manual backup:"
echo "  ./templedb backup cloud push gcs"
echo
echo "List backups:"
echo "  ./templedb backup cloud status gcs"
echo
echo "Restore backup:"
echo "  ./templedb backup cloud pull gcs BACKUP_ID"
echo
echo "View logs:"
echo "  tail -f ~/.local/share/templedb/backup.log"
echo
echo "Documentation:"
echo "  cat docs/BACKUP_GOOGLE_CLOUD.md"
echo
