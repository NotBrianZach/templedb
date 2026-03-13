#!/usr/bin/env bash
#
# Setup multiple Yubikeys for TempleDB secret management
# Registers 3 Yubikeys + 1 filesystem backup key
#
set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║        TempleDB Multi-Yubikey Setup                           ║${NC}"
echo -e "${BLUE}║        3 Yubikeys + 1 Filesystem Backup Key                   ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo

# Check prerequisites
echo "Checking prerequisites..."

if ! command -v age &> /dev/null; then
    echo -e "${RED}✗ age not found${NC}"
    echo "Install: https://github.com/FiloSottile/age/releases"
    exit 1
fi
echo -e "${GREEN}✓ age installed${NC}"

if ! command -v age-plugin-yubikey &> /dev/null; then
    echo -e "${RED}✗ age-plugin-yubikey not found${NC}"
    echo "Install: cargo install age-plugin-yubikey"
    exit 1
fi
echo -e "${GREEN}✓ age-plugin-yubikey installed${NC}"

if ! command -v ykman &> /dev/null; then
    echo -e "${YELLOW}⚠ ykman not found (optional but recommended)${NC}"
    echo "Install: pip install yubikey-manager"
else
    echo -e "${GREEN}✓ ykman installed${NC}"
fi

echo

# Run migration
echo "Running database migration..."
./templedb migrate || true
echo

# Setup Yubikey 1 - Primary (Daily Use)
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 1/4: Setup Yubikey 1 (Primary - Daily Use)${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo
echo "Please insert Yubikey #1 (your primary daily-use key)"
read -p "Press Enter when ready..."

if ! lsusb | grep -qi yubi; then
    echo -e "${RED}✗ No Yubikey detected${NC}"
    exit 1
fi

echo "Generating age identity on Yubikey #1..."
echo "You will be prompted for PIN setup"
echo

if age-plugin-yubikey --generate; then
    YUBIKEY1=$(age-plugin-yubikey --identity 2>/dev/null | grep age1yubikey | head -1)
    SERIAL1=$(ykman list --serials 2>/dev/null | head -1 || echo "unknown")

    echo
    echo -e "${GREEN}✓ Yubikey #1 configured${NC}"
    echo "  Serial: $SERIAL1"
    echo "  Recipient: $YUBIKEY1"
    echo

    # Register in TempleDB
    echo "Registering in TempleDB..."
    ./templedb key add yubikey \
        --name "yubikey-1-primary" \
        --location "daily-use" \
        --notes "Primary Yubikey for daily operations"

    echo -e "${GREEN}✓ Registered as 'yubikey-1-primary'${NC}"
else
    echo -e "${RED}✗ Failed to setup Yubikey #1${NC}"
    exit 1
fi

echo
read -p "Remove Yubikey #1 and press Enter to continue..."
echo

# Setup Yubikey 2 - Backup (Safe)
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 2/4: Setup Yubikey 2 (Backup - Safe Storage)${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo
echo "Please insert Yubikey #2 (backup key for safe storage)"
read -p "Press Enter when ready..."

if ! lsusb | grep -qi yubi; then
    echo -e "${RED}✗ No Yubikey detected${NC}"
    exit 1
fi

echo "Generating age identity on Yubikey #2..."
echo

if age-plugin-yubikey --generate; then
    YUBIKEY2=$(age-plugin-yubikey --identity 2>/dev/null | grep age1yubikey | head -1)
    SERIAL2=$(ykman list --serials 2>/dev/null | head -1 || echo "unknown")

    echo
    echo -e "${GREEN}✓ Yubikey #2 configured${NC}"
    echo "  Serial: $SERIAL2"
    echo "  Recipient: $YUBIKEY2"
    echo

    # Register in TempleDB
    echo "Registering in TempleDB..."
    ./templedb key add yubikey \
        --name "yubikey-2-backup" \
        --location "safe" \
        --notes "Backup Yubikey stored in office safe"

    echo -e "${GREEN}✓ Registered as 'yubikey-2-backup'${NC}"
else
    echo -e "${RED}✗ Failed to setup Yubikey #2${NC}"
    exit 1
fi

echo
read -p "Remove Yubikey #2 and press Enter to continue..."
echo

# Setup Yubikey 3 - Disaster Recovery (Offsite)
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 3/4: Setup Yubikey 3 (Disaster Recovery - Offsite)${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo
echo "Please insert Yubikey #3 (disaster recovery key for offsite storage)"
read -p "Press Enter when ready..."

if ! lsusb | grep -qi yubi; then
    echo -e "${RED}✗ No Yubikey detected${NC}"
    exit 1
fi

echo "Generating age identity on Yubikey #3..."
echo

if age-plugin-yubikey --generate; then
    YUBIKEY3=$(age-plugin-yubikey --identity 2>/dev/null | grep age1yubikey | head -1)
    SERIAL3=$(ykman list --serials 2>/dev/null | head -1 || echo "unknown")

    echo
    echo -e "${GREEN}✓ Yubikey #3 configured${NC}"
    echo "  Serial: $SERIAL3"
    echo "  Recipient: $YUBIKEY3"
    echo

    # Register in TempleDB
    echo "Registering in TempleDB..."
    ./templedb key add yubikey \
        --name "yubikey-3-dr" \
        --location "offsite" \
        --notes "Disaster recovery Yubikey stored offsite"

    echo -e "${GREEN}✓ Registered as 'yubikey-3-dr'${NC}"
else
    echo -e "${RED}✗ Failed to setup Yubikey #3${NC}"
    exit 1
fi

echo
read -p "Remove Yubikey #3 and press Enter to continue..."
echo

# Setup Filesystem Backup Key (USB)
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Step 4/4: Setup Filesystem Backup Key (USB Drive)${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════════════${NC}"
echo

# Check for existing age key
if [ -f ~/.age/key.txt ]; then
    echo "Found existing age key at ~/.age/key.txt"
    read -p "Use this key? [Y/n]: " use_existing
    if [[ ! $use_existing =~ ^[Nn]$ ]]; then
        BACKUP_KEY_PATH=~/.age/key.txt
        echo "Using existing key"
    fi
elif [ -f ~/.config/sops/age/keys.txt ]; then
    echo "Found existing age key at ~/.config/sops/age/keys.txt"
    read -p "Use this key? [Y/n]: " use_existing
    if [[ ! $use_existing =~ ^[Nn]$ ]]; then
        BACKUP_KEY_PATH=~/.config/sops/age/keys.txt
        echo "Using existing key"
    fi
fi

# Generate new key if needed
if [ -z "$BACKUP_KEY_PATH" ]; then
    echo "Generating new age key..."
    mkdir -p ~/.age
    age-keygen -o ~/.age/backup-key.txt
    BACKUP_KEY_PATH=~/.age/backup-key.txt
    echo -e "${GREEN}✓ Generated new key at ~/.age/backup-key.txt${NC}"
fi

# Register in TempleDB
echo "Registering filesystem backup key..."
./templedb key add filesystem \
    --name "usb-backup" \
    --path "$BACKUP_KEY_PATH" \
    --location "usb-drive" \
    --notes "Emergency backup key to be stored on USB drive"

echo -e "${GREEN}✓ Registered as 'usb-backup'${NC}"
echo

# Show summary
echo
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                    Setup Complete!                            ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo

echo "Your encryption keys:"
echo
./templedb key list
echo

echo -e "${BLUE}Next Steps:${NC}"
echo
echo "1. Copy backup key to USB drive:"
echo -e "   ${YELLOW}cp $BACKUP_KEY_PATH /path/to/usb/templedb-backup-key.txt${NC}"
echo -e "   ${YELLOW}chmod 600 /path/to/usb/templedb-backup-key.txt${NC}"
echo
echo "2. Store Yubikey #2 in safe (Serial: $SERIAL2)"
echo
echo "3. Store Yubikey #3 offsite (Serial: $SERIAL3)"
echo
echo "4. Initialize secrets for a project with all 4 keys:"
echo -e "   ${YELLOW}./templedb secret init-multi myproject \\${NC}"
echo -e "   ${YELLOW}    --keys yubikey-1-primary,yubikey-2-backup,yubikey-3-dr,usb-backup${NC}"
echo
echo "5. Test decryption with your primary Yubikey:"
echo -e "   ${YELLOW}./templedb secret edit myproject${NC}"
echo
echo "Documentation: docs/MULTI_YUBIKEY_SETUP.md"
echo
