#!/usr/bin/env bash
#
# Setup Yubikey for age encryption with TempleDB
# Usage: ./setup_yubikey_age.sh [--list|--generate|--init-project <project>]
#

set -euo pipefail

MODE="${1:-}"
PROJECT="${2:-}"

# Check dependencies
check_deps() {
  if ! command -v ykman &> /dev/null; then
    echo "❌ Error: ykman not found" >&2
    echo "Install with: pip install yubikey-manager" >&2
    exit 1
  fi

  if ! command -v age-plugin-yubikey &> /dev/null; then
    echo "❌ Error: age-plugin-yubikey not found" >&2
    echo "Install from: https://github.com/str4d/age-plugin-yubikey" >&2
    exit 1
  fi
}

# List connected Yubikeys
list_yubikeys() {
  echo "🔑 Connected Yubikeys:"
  echo ""
  ykman list
  echo ""

  # Check if age identity exists
  if age-plugin-yubikey --list &> /dev/null; then
    echo "📋 Existing age identities on Yubikey:"
    age-plugin-yubikey --list
  else
    echo "ℹ️  No age identities found on Yubikey"
    echo "   Run: $0 --generate"
  fi
}

# Generate age identity on Yubikey
generate_identity() {
  echo "🔐 Generating age identity on Yubikey..."
  echo ""
  echo "This will:"
  echo "  1. Create a new age identity on your Yubikey"
  echo "  2. Require your Yubikey PIN"
  echo "  3. Store the identity permanently on the device"
  echo ""
  read -p "Continue? (Y/n): " response

  if [[ "$response" =~ ^[Nn]$ ]]; then
    echo "Cancelled."
    exit 0
  fi

  echo ""
  echo "⚠️  You will be prompted for your Yubikey PIN"
  echo ""

  # Generate identity
  age-plugin-yubikey --generate

  echo ""
  echo "✅ Identity generated successfully!"
  echo ""
  echo "Next steps:"
  echo "  1. List identities: $0 --list"
  echo "  2. Initialize project secrets: $0 --init-project <project>"
}

# Initialize project with Yubikey-encrypted secrets
init_project() {
  if [ -z "$PROJECT" ]; then
    echo "Usage: $0 --init-project <project-slug>" >&2
    exit 1
  fi

  echo "🔐 Initializing secrets for project: $PROJECT"
  echo ""

  # Get Yubikey recipient
  echo "📋 Fetching Yubikey age recipient..."
  RECIPIENT=$(age-plugin-yubikey --list 2>&1 | grep "Recipient:" | head -1 | awk '{print $2}')

  if [ -z "$RECIPIENT" ]; then
    echo "❌ Error: No age identity found on Yubikey" >&2
    echo "   Run: $0 --generate" >&2
    exit 1
  fi

  echo "✅ Found recipient: $RECIPIENT"
  echo ""

  # Ask for profile
  read -p "Profile name [production]: " profile
  profile="${profile:-production}"

  echo ""
  echo "Initializing secrets with:"
  echo "  Project: $PROJECT"
  echo "  Profile: $profile"
  echo "  Yubikey Recipient: $RECIPIENT"
  echo ""
  read -p "Continue? (Y/n): " response

  if [[ "$response" =~ ^[Nn]$ ]]; then
    echo "Cancelled."
    exit 0
  fi

  # Initialize secrets
  echo ""
  echo "🔨 Running: templedb secret init $PROJECT --profile $profile --age-recipient $RECIPIENT"
  templedb secret init "$PROJECT" --profile "$profile" --age-recipient "$RECIPIENT"

  echo ""
  echo "✅ Secrets initialized successfully!"
  echo ""
  echo "Next steps:"
  echo "  1. Edit secrets: templedb secret edit $PROJECT --profile $profile"
  echo "     (Will require Yubikey touch)"
  echo "  2. Export secrets: templedb secret export $PROJECT --profile $profile"
  echo "     (Will require Yubikey touch)"
  echo ""
  echo "⚠️  IMPORTANT: All secret operations will now require your Yubikey to be connected!"
}

# Show help
show_help() {
  cat << EOF
Usage: $0 [COMMAND] [OPTIONS]

Setup and manage Yubikey for age encryption with TempleDB.

Commands:
  --list                 List connected Yubikeys and age identities
  --generate             Generate new age identity on Yubikey
  --init-project <slug>  Initialize project secrets with Yubikey encryption
  --help                 Show this help message

Examples:
  # List Yubikeys
  $0 --list

  # Generate age identity
  $0 --generate

  # Initialize project secrets
  $0 --init-project my-project

Requirements:
  - yubikey-manager (ykman): pip install yubikey-manager
  - age-plugin-yubikey: https://github.com/str4d/age-plugin-yubikey

Security Notes:
  - Secrets encrypted with Yubikey can ONLY be decrypted with that Yubikey
  - Each decryption requires Yubikey PIN + physical touch
  - Multiple Yubikeys can be configured as recipients for team access
  - Yubikey identities are permanent (cannot be exported)

Documentation:
  See .claude/skills/templedb-secrets/SKILL.md for complete guide
EOF
}

# Main
check_deps

case "$MODE" in
  --list)
    list_yubikeys
    ;;
  --generate)
    generate_identity
    ;;
  --init-project)
    init_project
    ;;
  --help|"")
    show_help
    ;;
  *)
    echo "Error: Unknown command: $MODE" >&2
    echo ""
    show_help
    exit 1
    ;;
esac
