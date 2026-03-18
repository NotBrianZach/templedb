# Multi-Yubikey Secret Management for TempleDB

**Complete guide to setting up and managing secrets with 3 Yubikeys + 1 filesystem backup key**

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Setup](#setup)
4. [Usage](#usage)
5. [Key Management](#key-management)
6. [Disaster Recovery](#disaster-recovery)
7. [Best Practices](#best-practices)

---

## Overview

This system provides **multi-recipient encryption** for TempleDB secrets using:

- **3 Yubikeys** (hardware-protected keys requiring PIN + physical presence)
- **1 Filesystem Key** (age key for emergency access, stored on USB)

### Benefits

✅ **No Single Point of Failure** - Any one key can decrypt
✅ **Hardware Security** - Primary keys protected by Yubikey hardware
✅ **Disaster Recovery** - Multiple backup keys in different locations
✅ **Key Rotation** - Add/remove keys without losing access
✅ **Audit Trail** - Track which keys encrypt which secrets

---

## Architecture

### Key Distribution

```
┌─────────────────────────────────────────────────────────────┐
│                  TempleDB Secret (encrypted)                │
│                                                             │
│  Encrypted with 4 recipients (any one can decrypt):        │
│                                                             │
│  1. Yubikey #1 (Primary)     → Daily use, on your person   │
│  2. Yubikey #2 (Backup)      → Office safe                 │
│  3. Yubikey #3 (DR)          → Offsite location            │
│  4. Filesystem Key (USB)     → Emergency backup USB drive  │
└─────────────────────────────────────────────────────────────┘
```

### Database Schema

```sql
encryption_keys               -- Registry of all keys
├── key_name                  -- "yubikey-1-primary"
├── key_type                  -- "yubikey" or "filesystem"
├── recipient                 -- age1yubikey... or age1...
├── serial_number             -- Yubikey serial
├── location                  -- "daily-use", "safe", "offsite"
└── is_active                 -- Enable/disable

secret_key_assignments        -- Which keys encrypt which secrets
├── secret_blob_id
├── key_id
└── added_at

encryption_key_audit          -- Audit log
├── key_id
├── action                    -- "add", "test", "decrypt"
├── timestamp
└── success
```

---

## Setup

### Prerequisites

```bash
# Install age
# https://github.com/FiloSottile/age/releases

# Install age-plugin-yubikey
cargo install age-plugin-yubikey

# Install ykman (optional but recommended)
pip install yubikey-manager

# Install pcscd (required for PIV)
sudo apt install pcscd      # Debian/Ubuntu
sudo pacman -S pcscd        # Arch Linux
```

### Automated Setup

Run the automated setup script:

```bash
cd /path/to/templedb
./scripts/setup_multi_yubikey.sh
```

This will:
1. Run database migration
2. Setup Yubikey #1 (Primary - Daily Use)
3. Setup Yubikey #2 (Backup - Safe Storage)
4. Setup Yubikey #3 (DR - Offsite)
5. Setup Filesystem Backup Key
6. Register all keys in TempleDB

### Manual Setup

If you prefer manual setup:

#### 1. Run Migration

```bash
./templedb migrate
```

#### 2. Setup Yubikey #1 (Primary)

```bash
# Insert Yubikey #1
age-plugin-yubikey --generate

# Register in TempleDB
./templedb key add yubikey \
  --name "yubikey-1-primary" \
  --location "daily-use" \
  --notes "Primary Yubikey for daily operations"
```

#### 3. Setup Yubikey #2 (Backup)

```bash
# Remove Yubikey #1, insert Yubikey #2
age-plugin-yubikey --generate

# Register in TempleDB
./templedb key add yubikey \
  --name "yubikey-2-backup" \
  --location "safe" \
  --notes "Backup Yubikey stored in office safe"
```

#### 4. Setup Yubikey #3 (DR)

```bash
# Remove Yubikey #2, insert Yubikey #3
age-plugin-yubikey --generate

# Register in TempleDB
./templedb key add yubikey \
  --name "yubikey-3-dr" \
  --location "offsite" \
  --notes "Disaster recovery Yubikey stored offsite"
```

#### 5. Setup Filesystem Backup Key

```bash
# Generate age key (or use existing)
age-keygen -o ~/.age/backup-key.txt

# Register in TempleDB
./templedb key add filesystem \
  --name "usb-backup" \
  --path ~/.age/backup-key.txt \
  --location "usb-drive" \
  --notes "Emergency backup key to be stored on USB drive"
```

#### 6. Copy Backup Key to USB

```bash
# Mount USB drive
sudo mount /dev/sdb1 /mnt/usb

# Copy key
cp ~/.age/backup-key.txt /mnt/usb/templedb-backup-key.txt
chmod 600 /mnt/usb/templedb-backup-key.txt

# Unmount and physically store USB in secure location
sudo umount /mnt/usb
```

---

## Usage

### Initialize Secrets with Multi-Key Encryption

```bash
# Encrypt with all 4 keys
./templedb secret init-multi myproject \
  --keys yubikey-1-primary,yubikey-2-backup,yubikey-3-dr,usb-backup

# Encrypt with specific profile
./templedb secret init-multi myproject \
  --profile production \
  --keys yubikey-1-primary,yubikey-2-backup,yubikey-3-dr,usb-backup
```

### Edit Secrets (Requires Any One Key)

```bash
# With Yubikey #1 plugged in (daily use)
./templedb secret edit myproject

# Will prompt for PIN, then open $EDITOR
```

### Export Secrets

```bash
# Shell export format
./templedb secret export myproject --format shell

# JSON format
./templedb secret export myproject --format json

# .env format
./templedb secret export myproject --format dotenv
```

### Show Which Keys Encrypt a Secret

```bash
./templedb secret show-keys myproject

# Output:
# Secret: myproject (profile: default)
# ============================================================
#
# Encrypted with 4 keys:
#
# 1. yubikey-1-primary (yubikey) - ✓ ACTIVE
#    Location: daily-use
#    Added: 2026-03-12 08:00:00 by zach
#
# 2. yubikey-2-backup (yubikey) - ✓ ACTIVE
#    Location: safe
#    Added: 2026-03-12 08:05:00 by zach
#
# 3. yubikey-3-dr (yubikey) - ✓ ACTIVE
#    Location: offsite
#    Added: 2026-03-12 08:10:00 by zach
#
# 4. usb-backup (filesystem) - ✓ ACTIVE
#    Location: usb-drive
#    Added: 2026-03-12 08:15:00 by zach
```

---

## Key Management

### List All Keys

```bash
# Show active keys
./templedb key list

# Show all keys (including disabled)
./templedb key list --all
```

### View Key Details

```bash
./templedb key info yubikey-1-primary

# Output:
# ================================================================
# Key: yubikey-1-primary
# ================================================================
#
# Type: yubikey
# Status: ACTIVE
# Recipient: age1yubikey1qw7ry8g2xy3z4abc123...
# Serial Number: 12345678
# PIV Slot: 9a
# Location: daily-use
# Created: 2026-03-12 08:00:00
# Last Used: 2026-03-12 15:30:00
# Last Tested: 2026-03-12 14:00:00
#
# Secrets encrypted with this key (3):
#   - myproject (default)
#   - myproject (production)
#   - otherproject (default)
#
# Recent Activity:
#   ✓ decrypt - 2026-03-12 15:30:00
#   ✓ test - 2026-03-12 14:00:00
#   ✓ add - 2026-03-12 08:00:00
```

### Test a Key

```bash
# Test if key can encrypt/decrypt
./templedb key test yubikey-1-primary

# Will attempt encryption and decryption test
# For Yubikeys, you'll need to enter PIN
```

### Add Key to Existing Secret

```bash
# Add a new Yubikey to secret
./templedb secret add-key myproject --key yubikey-4-new

# This will:
# 1. Decrypt secret with existing keys
# 2. Re-encrypt with all keys including new one
# 3. Update secret_key_assignments table
```

### Remove Key from Secret

```bash
# Remove a key (requires at least one key to remain)
./templedb secret remove-key myproject --key yubikey-1-primary

# This will:
# 1. Decrypt secret with existing keys
# 2. Re-encrypt with remaining keys only
# 3. Remove from secret_key_assignments table
```

### Disable a Key

```bash
# Disable key without deleting (can re-enable later)
./templedb key disable yubikey-1-primary

# Key will no longer be used for new encryptions
# Existing secrets encrypted with it remain accessible
```

### Enable a Key

```bash
# Re-enable a disabled key
./templedb key enable yubikey-1-primary
```

---

## Disaster Recovery

### Scenario 1: Lost Primary Yubikey

**Problem:** Your daily-use Yubikey (yubikey-1-primary) is lost/stolen

**Solution:**

```bash
# 1. Use backup Yubikey #2 from safe
# Insert Yubikey #2, then edit secrets normally
./templedb secret edit myproject

# 2. Remove compromised key from all secrets
./templedb secret remove-key myproject --key yubikey-1-primary

# 3. Get new Yubikey, set it up
age-plugin-yubikey --generate
./templedb key add yubikey --name "yubikey-4-new" --location "daily-use"

# 4. Add new key to all secrets
./templedb secret add-key myproject --key yubikey-4-new

# 5. Disable old key in registry
./templedb key disable yubikey-1-primary
```

### Scenario 2: All Yubikeys Unavailable

**Problem:** Cannot access any of the 3 Yubikeys

**Solution:**

```bash
# Use USB backup key
# 1. Get USB drive from secure storage
# 2. Copy key to standard location
cp /mnt/usb/templedb-backup-key.txt ~/.age/backup-key.txt

# 3. Set environment variable
export TEMPLEDB_AGE_KEY_FILE=~/.age/backup-key.txt

# 4. Access secrets normally
./templedb secret edit myproject

# Secret will decrypt using filesystem key
```

### Scenario 3: Forgot Yubikey PIN

**Problem:** Forgotten PIN, locked out of Yubikey

**Solution:**

```bash
# Option 1: Reset with PUK (if you know it)
ykman piv access change-pin --pin <puk> --new-pin <new-pin>

# Option 2: Use different Yubikey or USB backup
# (See Scenario 1 or 2)

# Option 3: Factory reset Yubikey (DESTROYS ALL DATA)
ykman piv reset
# Then re-generate and register as new key
```

### Scenario 4: Total Loss (All Keys)

**Problem:** All 4 keys are lost/destroyed

**Status:** ⚠️ **Secrets are permanently lost**

**Prevention:**
- Store Yubikey #3 offsite (bank vault, trusted friend, etc.)
- Store USB backup in separate physical location
- Consider 5th key in cloud HSM for ultra-critical secrets
- Print paper recovery codes (age supports this)

---

## Best Practices

### Physical Security

✅ **DO:**
- Store Yubikey #2 in locked office safe
- Store Yubikey #3 in offsite location (home safe, bank vault)
- Store USB backup separate from Yubikeys
- Use strong PINs (8 digits) for all Yubikeys
- Enable touch requirement for critical secrets

❌ **DON'T:**
- Store all keys in same location
- Leave Yubikeys unattended
- Share PINs or keys
- Store USB backup on network-accessible drive

### Key Hygiene

- **Test keys regularly:** `./templedb key test <key-name>`
- **Update last_tested_at:** Proves keys are still functional
- **Rotate keys annually:** Add new keys, remove old ones
- **Audit key usage:** Review `encryption_key_audit` table

### Operational Procedures

#### Daily Operations
- Use Yubikey #1 (primary) for all daily secret access
- Keep Yubikey #2 and #3 in secure storage
- Never use USB backup unless emergency

#### Monthly Audit
```bash
# Test all keys
./templedb key test yubikey-1-primary
./templedb key test yubikey-2-backup
./templedb key test yubikey-3-dr
./templedb key test usb-backup

# Review key usage
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM encryption_key_stats_view"
```

#### Annual Key Rotation
```bash
# Generate new keys
# Add to all secrets
# Remove old keys
# Update physical storage locations
```

---

## Troubleshooting

### "No Yubikey detected"

```bash
# Check USB connection
lsusb | grep -i yubi

# Check pcscd service
sudo systemctl status pcscd
sudo systemctl restart pcscd

# Re-seat Yubikey
```

### "Decryption failed"

```bash
# Check which keys encrypt the secret
./templedb secret show-keys myproject

# Try each key:
# 1. Insert Yubikey #1, try decrypt
# 2. Insert Yubikey #2, try decrypt
# 3. Use USB backup key

# If all fail, check for corruption:
./templedb secret print-raw myproject
```

### "Key test failed"

```bash
# For Yubikeys: Check PIN
# Try entering PIN via ykman first
ykman piv info

# For filesystem keys: Check file exists and is readable
ls -la ~/.age/backup-key.txt
age-keygen -y ~/.age/backup-key.txt
```

---

## Advanced Topics

### Using Different PIV Slots

By default, age-plugin-yubikey uses slot 9a. You can use other slots:

```bash
# Generate on slot 9c
age-plugin-yubikey --generate --slot 9c

# Register with slot info
./templedb key add yubikey \
  --name "yubikey-1-slot-9c" \
  --slot 9c
```

### Touch Requirement

Require physical touch for decryption:

```bash
# Set touch policy to ALWAYS
ykman piv keys set-touch-policy 9a ALWAYS

# Now you must touch Yubikey LED during decrypt
```

### Multiple Profiles

Use different key sets for different environments:

```bash
# Production: All 4 keys
./templedb secret init-multi myproject \
  --profile production \
  --keys yubikey-1-primary,yubikey-2-backup,yubikey-3-dr,usb-backup

# Development: Only filesystem key
./templedb secret init myproject \
  --profile development \
  --age-recipient $(age-keygen -y ~/.age/dev-key.txt)
```

---

## Summary

```bash
# Setup (one-time)
./scripts/setup_multi_yubikey.sh

# Daily usage
./templedb secret init-multi myproject --keys yubikey-1-primary,yubikey-2-backup,yubikey-3-dr,usb-backup
./templedb secret edit myproject
./templedb secret export myproject --format shell

# Key management
./templedb key list
./templedb key info yubikey-1-primary
./templedb key test yubikey-1-primary

# Disaster recovery
./templedb secret show-keys myproject
./templedb secret remove-key myproject --key compromised-key
./templedb secret add-key myproject --key new-key
```

**TempleDB - Your secrets, multiply protected** 🔐

---

*For more information:*
- [Yubikey Basics](YUBIKEY_SECRETS.md)
- [Secret Management](../docs/BACKUP.md)
- [Deployment with Secrets](../docs/DEPLOYMENT.md)
