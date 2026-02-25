#!/usr/bin/env bash
#
# Setup Yubikey for TempleDB secret management
#
# This script helps you configure a Yubikey for hardware-backed
# encryption of TempleDB secrets.
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}TempleDB Yubikey Setup${NC}"
echo "========================================"
echo

# Check if age is installed
if ! command -v age &> /dev/null; then
    echo -e "${RED}✗ age not found${NC}"
    echo "Install age first: https://github.com/FiloSottile/age/releases"
    exit 1
fi

echo -e "${GREEN}✓ age installed:${NC} $(age --version)"

# Check if age-plugin-yubikey is installed
if ! command -v age-plugin-yubikey &> /dev/null; then
    echo -e "${YELLOW}✗ age-plugin-yubikey not found${NC}"
    echo
    echo "Install with one of:"
    echo "  1. Cargo: cargo install age-plugin-yubikey"
    echo "  2. Binary: https://github.com/str4d/age-plugin-yubikey/releases"
    echo
    read -p "Continue anyway? [y/N]: " continue_anyway
    if [[ ! $continue_anyway =~ ^[Yy]$ ]]; then
        exit 1
    fi
else
    echo -e "${GREEN}✓ age-plugin-yubikey installed${NC}"
fi

echo

# Check for Yubikey
echo "Checking for Yubikey..."
if lsusb | grep -qi yubi; then
    echo -e "${GREEN}✓ Yubikey detected${NC}"
else
    echo -e "${YELLOW}⚠ No Yubikey detected${NC}"
    echo "Please insert your Yubikey and press Enter"
    read
    if ! lsusb | grep -qi yubi; then
        echo -e "${RED}✗ Still no Yubikey found${NC}"
        exit 1
    fi
    echo -e "${GREEN}✓ Yubikey detected${NC}"
fi

echo

# Check pcscd service (required for PIV)
echo "Checking pcscd service..."
if systemctl is-active --quiet pcscd 2>/dev/null; then
    echo -e "${GREEN}✓ pcscd running${NC}"
elif command -v pcscd &> /dev/null; then
    echo -e "${YELLOW}⚠ pcscd not running, attempting to start${NC}"
    sudo systemctl start pcscd || true
else
    echo -e "${YELLOW}⚠ pcscd not found${NC}"
    echo "Install with:"
    echo "  Ubuntu/Debian: sudo apt install pcscd"
    echo "  Arch: sudo pacman -S pcscd"
fi

echo

# List existing Yubikey identities
echo "Checking for existing age identities on Yubikey..."
if age-plugin-yubikey --list 2>/dev/null | grep -q "slot"; then
    echo -e "${GREEN}✓ Found existing age identity${NC}"
    echo
    age-plugin-yubikey --list
    echo
    read -p "Generate new identity anyway? [y/N]: " generate_new
    if [[ ! $generate_new =~ ^[Yy]$ ]]; then
        echo "Using existing identity"
        YUBIKEY_RECIPIENT=$(age-plugin-yubikey --identity 2>/dev/null | grep age1yubikey | head -1)
        if [ -z "$YUBIKEY_RECIPIENT" ]; then
            echo -e "${RED}✗ Could not get recipient${NC}"
            exit 1
        fi
        echo -e "${GREEN}Recipient:${NC} $YUBIKEY_RECIPIENT"
        echo
        echo "Use this recipient to initialize secrets:"
        echo -e "${BLUE}  ./templedb secret init <project> --age-recipient $YUBIKEY_RECIPIENT${NC}"
        exit 0
    fi
fi

echo

# Generate new age identity
echo -e "${BLUE}Generating new age identity on Yubikey...${NC}"
echo
echo "You will be prompted for:"
echo "  1. Current PIN (default: 123456 if never changed)"
echo "  2. New PIN (6-8 digits, required)"
echo "  3. PUK (optional, for PIN reset)"
echo

read -p "Ready to generate? [y/N]: " ready
if [[ ! $ready =~ ^[Yy]$ ]]; then
    echo "Cancelled"
    exit 0
fi

echo

if age-plugin-yubikey --generate; then
    echo
    echo -e "${GREEN}✓ Successfully generated age identity on Yubikey${NC}"
else
    echo
    echo -e "${RED}✗ Failed to generate identity${NC}"
    exit 1
fi

echo

# Get the recipient
echo "Getting Yubikey recipient..."
YUBIKEY_RECIPIENT=$(age-plugin-yubikey --identity 2>/dev/null | grep age1yubikey | head -1)

if [ -z "$YUBIKEY_RECIPIENT" ]; then
    echo -e "${RED}✗ Could not get recipient${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Recipient:${NC} $YUBIKEY_RECIPIENT"
echo

# Optional: Configure touch policy
echo "Configure touch requirement?"
echo "  ALWAYS - Must touch Yubikey for each decryption (most secure)"
echo "  CACHED - Touch once, cached for 15 seconds"
echo "  OFF    - No touch required (PIN only)"
echo

if command -v ykman &> /dev/null; then
    read -p "Set touch policy? [always/cached/off/skip]: " touch_policy
    case $touch_policy in
        always|ALWAYS)
            ykman piv keys set-touch-policy 9a ALWAYS
            echo -e "${GREEN}✓ Touch policy set to ALWAYS${NC}"
            ;;
        cached|CACHED)
            ykman piv keys set-touch-policy 9a CACHED
            echo -e "${GREEN}✓ Touch policy set to CACHED${NC}"
            ;;
        off|OFF)
            ykman piv keys set-touch-policy 9a OFF
            echo -e "${GREEN}✓ Touch policy set to OFF${NC}"
            ;;
        *)
            echo "Skipping touch policy"
            ;;
    esac
else
    echo -e "${YELLOW}⚠ ykman not found, skipping touch policy${NC}"
    echo "Install: pip install yubikey-manager"
fi

echo

# Show next steps
echo "========================================"
echo -e "${GREEN}Setup Complete!${NC}"
echo "========================================"
echo
echo "Your Yubikey recipient:"
echo -e "${BLUE}$YUBIKEY_RECIPIENT${NC}"
echo
echo "Next steps:"
echo
echo "1. Initialize secrets for a project:"
echo -e "   ${BLUE}./templedb secret init woofs_projects --age-recipient $YUBIKEY_RECIPIENT${NC}"
echo
echo "2. Edit secrets (will prompt for PIN):"
echo -e "   ${BLUE}./templedb secret edit woofs_projects${NC}"
echo
echo "3. Export secrets:"
echo -e "   ${BLUE}./templedb secret export woofs_projects --format shell${NC}"
echo
echo "4. Deploy (requires Yubikey + PIN):"
echo -e "   ${BLUE}./templedb deploy run woofs_projects --target staging${NC}"
echo
echo "Documentation:"
echo "   docs/advanced/YUBIKEY_SECRETS.md"
echo
