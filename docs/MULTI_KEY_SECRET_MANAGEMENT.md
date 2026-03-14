# Multi-Key Secret Management

TempleDB supports multi-recipient encryption for secrets, allowing multiple keys to decrypt the same secret. This provides redundancy and flexibility for key management.

## Overview

**Key Features:**
- **Multi-recipient encryption**: Encrypt secrets with multiple keys (filesystem age keys + Yubikeys)
- **Any-of-N decryption**: Any single registered key can decrypt any secret
- **Lazy mode** (default): New keys automatically added to all existing secrets
- **Corpo mode**: Register keys without auto-updating secrets
- **Quorum-based revocation**: Revoke compromised keys with 2-of-N approval

## Architecture

TempleDB uses [age](https://github.com/FiloSottile/age) encryption with:
- **X25519** key agreement
- **ChaCha20-Poly1305** AEAD encryption
- **Multi-recipient support**: Data encrypted once, then encrypted for each recipient
- **Hardware keys**: Yubikey support via [age-plugin-yubikey](https://github.com/str4d/age-plugin-yubikey)

## Quick Start

### 1. List Registered Keys

```bash
./templedb key list
```

Example output:
```
Encryption Keys (4 total)

age-key (filesystem) - ✓ ACTIVE
  Location: filesystem
  Secrets: 4, Projects: 3

sops-key (filesystem) - ✓ ACTIVE
  Location: filesystem
  Secrets: 4, Projects: 3

yubikey-1 (yubikey) - ✓ ACTIVE
  Location: daily-use
  Secrets: 4, Projects: 3
  Serial: 19101846

yubikey-slot2 (yubikey) - ✓ ACTIVE
  Location: daily-use
  Secrets: 4, Projects: 3
  Serial: 19101846
```

### 2. Add a Filesystem Age Key

```bash
# Lazy mode (default) - adds to all existing secrets
./templedb key add filesystem --name backup-key --path ~/.age/backup.txt --location "USB drive"

# Corpo mode - only registers key
./templedb key add filesystem --name backup-key --path ~/.age/backup.txt --no-lazy
```

### 3. Setup a Yubikey

```bash
# Interactive setup - generates age identity on Yubikey
./templedb key setup-yubikey

# Then register it (lazy mode adds to all secrets automatically)
./templedb key add yubikey --name yubikey-primary --location "daily-use"

# Register specific slot
./templedb key add yubikey --name yubikey-backup --location "safe" --slot 2
```

### 4. View Secret Keys

```bash
# See which keys protect a secret
./templedb secret show-keys templedb --profile default
```

Example output:
```
Secret: templedb (profile: default)

Encrypted with 4 keys:

1. age-key (filesystem) - ✓ ACTIVE
   Location: filesystem
   Added: 2026-03-13 15:01:13 by zach

2. sops-key (filesystem) - ✓ ACTIVE
   Location: filesystem
   Added: 2026-03-13 15:01:13 by zach

3. yubikey-slot2 (yubikey) - ✓ ACTIVE
   Location: daily-use
   Added: 2026-03-14 01:32:17 by zach

4. yubikey-1 (yubikey) - ✓ ACTIVE
   Location: daily-use
   Added: 2026-03-14 01:36:43 by zach
```

## Key Management Operations

### Add Keys to Existing Secrets

Manually add a key to specific secrets (useful in corpo mode):

```bash
./templedb secret add-key PROJECT --profile default --key KEY_NAME
```

### Remove Keys from Secrets

```bash
./templedb secret remove-key PROJECT --profile default --key KEY_NAME
```

Note: Cannot remove the last key from a secret.

### Test Key

Verify a key can encrypt/decrypt:

```bash
./templedb key test KEY_NAME
```

### Disable/Enable Keys

Temporarily disable a key without deletion:

```bash
./templedb key disable KEY_NAME
./templedb key enable KEY_NAME
```

### Key Info

Show detailed information about a key:

```bash
./templedb key info KEY_NAME
```

## Modes

### Lazy Mode (Default)

When adding a key in lazy mode, it's automatically added to ALL existing secrets:

```bash
./templedb key add yubikey --name yk-1 --location "daily-use"
```

**What happens:**
1. Yubikey is registered in database
2. All existing secrets are decrypted
3. All secrets re-encrypted with the new key included
4. Immediate redundancy - new key can decrypt everything

**Use when:**
- You want instant backup/redundancy
- Adding a new physical backup key
- Setting up a new Yubikey for daily use
- Personal/small team environments

### Corpo Mode

Only registers the key without modifying secrets:

```bash
./templedb key add yubikey --name yk-2 --location "offsite" --no-lazy
```

**What happens:**
1. Yubikey is registered in database
2. No secrets are modified
3. You manually choose which secrets get this key later

**Use when:**
- Controlled corporate environments
- Explicit approval required for key changes
- Need to audit which secrets use which keys
- Adding keys for specific projects only

**Then manually add to secrets:**
```bash
./templedb secret add-key my-project --key yk-2
```

## Multi-Recipient Secret Initialization

Create a new secret with multiple keys from the start:

```bash
./templedb secret init-multi PROJECT \
  --profile default \
  --keys "key1,key2,key3"
```

## Key Revocation

Revoke a compromised key with quorum approval (requires 2-of-4 keys):

```bash
./templedb key revoke COMPROMISED_KEY --reason "Lost Yubikey"
```

**What happens:**
1. System prompts for approval from 2 different keys
2. Each approver must decrypt a challenge (proves they have the key)
3. Key is marked as REVOKED in database
4. All secrets using this key are re-encrypted WITHOUT it
5. Full audit trail is recorded

**View revoked keys:**
```bash
./templedb key show-revoked
```

## Decryption Behavior

TempleDB automatically tries all available keys when decrypting:

**Key file locations checked:**
1. `$TEMPLEDB_AGE_KEY_FILE`
2. `$SOPS_AGE_KEY_FILE`
3. `~/.config/sops/age/keys.txt`
4. `~/.age/key.txt`
5. `~/.config/age-plugin-yubikey/identities.txt`

**Any-of-N decryption:**
- age tries each identity file until one works
- If using Yubikey, you'll be prompted for PIN + physical touch
- No coordination needed between key holders
- Single key sufficient to decrypt

## Example Workflows

### Setup: 3 Yubikeys + 1 Filesystem Backup

```bash
# 1. Generate age identities on 3 Yubikeys
./templedb key setup-yubikey  # Insert Yubikey 1, follow prompts
./templedb key add yubikey --name yubikey-daily --location "daily-use"

./templedb key setup-yubikey  # Insert Yubikey 2
./templedb key add yubikey --name yubikey-safe --location "home-safe"

./templedb key setup-yubikey  # Insert Yubikey 3
./templedb key add yubikey --name yubikey-offsite --location "bank-deposit-box"

# 2. Add filesystem backup key
age-keygen -o ~/.age/usb-backup.txt
./templedb key add filesystem \
  --name usb-backup \
  --path ~/.age/usb-backup.txt \
  --location "USB drive in safe"

# Result: All 4 keys protect all secrets (lazy mode)
```

### Rotate Compromised Key

```bash
# 1. Revoke compromised key (requires 2-of-4 approval)
./templedb key revoke yubikey-daily --reason "Lost during travel"

# 2. Add replacement key
./templedb key setup-yubikey  # New Yubikey
./templedb key add yubikey --name yubikey-replacement --location "daily-use"

# Result: All secrets now use 4 keys again (3 Yubikeys + 1 filesystem)
```

### Disaster Recovery

**Scenario:** Lost all Yubikeys, only have filesystem backup

```bash
# Filesystem key can decrypt everything
export TEMPLEDB_AGE_KEY_FILE=~/.age/usb-backup.txt

# Access all secrets
./templedb secret export my-project --format yaml

# Setup new Yubikeys
./templedb key setup-yubikey
./templedb key add yubikey --name yubikey-new-1 --location "daily-use"
# Repeat for additional Yubikeys

# Result: Back to full redundancy
```

## Database Schema

### encryption_keys

Stores registered encryption keys:

```sql
CREATE TABLE encryption_keys (
    id INTEGER PRIMARY KEY,
    key_name TEXT UNIQUE NOT NULL,
    key_type TEXT CHECK(key_type IN ('yubikey', 'filesystem')),
    recipient TEXT UNIQUE NOT NULL,  -- age recipient (age1...)
    serial_number TEXT,               -- Yubikey serial
    piv_slot TEXT,                    -- PIV slot (9a, 1, 2, etc)
    location TEXT,                    -- Physical location
    is_active INTEGER DEFAULT 1,
    is_revoked INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP,
    revoked_by TEXT,
    revocation_reason TEXT
);
```

### secret_key_assignments

Tracks which keys protect which secrets:

```sql
CREATE TABLE secret_key_assignments (
    secret_blob_id INTEGER,
    key_id INTEGER,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    added_by TEXT,
    PRIMARY KEY (secret_blob_id, key_id),
    FOREIGN KEY (secret_blob_id) REFERENCES secret_blobs(id),
    FOREIGN KEY (key_id) REFERENCES encryption_keys(id)
);
```

### encryption_key_audit

Comprehensive audit trail:

```sql
CREATE TABLE encryption_key_audit (
    id INTEGER PRIMARY KEY,
    key_id INTEGER,
    action TEXT,  -- add, test, enable, disable, revoke
    actor TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    details TEXT, -- JSON
    success INTEGER DEFAULT 1
);
```

## Security Considerations

### Key Diversity

**Recommended setup:**
- **Daily use**: Yubikey on keychain
- **Home safe**: Yubikey in fireproof safe
- **Offsite**: Yubikey in bank deposit box
- **Emergency backup**: Filesystem key on encrypted USB

### Touch Policy

Yubikeys generated with `age-plugin-yubikey --generate` have:
- **PIN policy**: Once per session
- **Touch policy**: Always (physical touch required for every decryption)

This provides:
- Protection against malware (requires physical presence)
- Audit trail (you know when key is being used)

### Revocation Quorum

2-of-N revocation prevents:
- Single compromised key from revoking others
- Accidental revocation
- Malicious revocation by single party

Requires:
- Access to 2 different keys
- Cryptographic proof (encrypt/decrypt challenge)
- Full audit trail

### Backup Strategy

**DO:**
- Keep filesystem backup in physically separate location
- Test backups regularly (`./templedb key test`)
- Document key locations
- Use quorum revocation for compromised keys

**DON'T:**
- Store all keys in same physical location
- Share private keys over network
- Skip testing backups
- Delay revoking compromised keys

## Troubleshooting

### "No age key files found"

```bash
# Check available keys
ls -la ~/.config/sops/age/keys.txt
ls -la ~/.age/key.txt
ls -la ~/.config/age-plugin-yubikey/identities.txt

# Set explicit key file
export TEMPLEDB_AGE_KEY_FILE=~/.age/key.txt
```

### "age decryption failed"

Possible causes:
1. **Yubikey not inserted** - Insert Yubikey and retry
2. **Wrong PIN** - Yubikey PIN incorrect (default: 123456)
3. **No valid keys** - None of your keys can decrypt this secret
4. **Forgot to touch** - Yubikey requires physical touch

### "Key test failed"

For Yubikeys:
- Make sure Yubikey is inserted
- Enter PIN when prompted
- Touch Yubikey when LED flashes
- Check PIN policy hasn't locked the key

For filesystem keys:
- Verify file exists and is readable
- Check it's a valid age private key
- Ensure it matches the registered recipient

### Multiple Yubikey Slots

If you see "Generated recipients for 2 slots":
```bash
# List all identities on Yubikey
age-plugin-yubikey --list

# Add specific slot
./templedb key add yubikey --name yk-slot1 --slot 1
./templedb key add yubikey --name yk-slot2 --slot 2
```

## Reference

### CLI Commands

```bash
# Key management
./templedb key add {yubikey|filesystem} --name NAME [options]
./templedb key list [--all]
./templedb key info KEY_NAME
./templedb key test KEY_NAME
./templedb key enable KEY_NAME
./templedb key disable KEY_NAME
./templedb key setup-yubikey
./templedb key revoke KEY_NAME [--reason REASON] [--quorum N]
./templedb key show-revoked

# Secret management
./templedb secret init-multi PROJECT --keys "key1,key2,key3"
./templedb secret show-keys PROJECT [--profile PROFILE]
./templedb secret add-key PROJECT --key KEY_NAME [--profile PROFILE]
./templedb secret remove-key PROJECT --key KEY_NAME [--profile PROFILE]
```

### Key Add Flags

```bash
--name NAME              # Required: key name
--location LOCATION      # Physical location (e.g., "daily-use", "safe")
--path PATH             # Required for filesystem keys
--slot SLOT             # Yubikey PIV slot (default: 9a)
--notes NOTES           # Additional notes
--lazy                  # Lazy mode: add to all secrets (default)
--no-lazy               # Corpo mode: only register key
```

## See Also

- [age encryption](https://github.com/FiloSottile/age)
- [age-plugin-yubikey](https://github.com/str4d/age-plugin-yubikey)
- [Secret Management Guide](./SECRET_MANAGEMENT.md)
- [Key Revocation Guide](./KEY_REVOCATION_GUIDE.md)
