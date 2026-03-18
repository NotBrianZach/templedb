# Key Revocation Guide

## Overview

TempleDB implements **quorum-based key revocation** requiring 2-of-N keys to approve revocation. This prevents a single compromised key from revoking others.

---

## When to Revoke a Key

### Immediate Revocation Required

⚠️ **REVOKE IMMEDIATELY if:**
- Key is lost or stolen
- Key PIN/passphrase compromised
- Yubikey physically damaged beyond recovery
- Employee with key access terminated
- Key believed to be compromised

### Consider Revocation

⚠️ **CONSIDER REVOCATION if:**
- Key has not been tested in >1 year
- Physical security of key location breached
- Key owner reports suspicious activity
- Regular key rotation schedule (annual)

---

## Revocation Process

### Step 1: Gather Required Keys

Revocation requires **2 out of any 4 keys** to approve (including the key being revoked if you still have access to it).

**Example:** Revoking `yubikey-1-primary` requires 2 of:
- `yubikey-1-primary` (the one being revoked - if you still have it)
- `yubikey-2-backup` (from safe)
- `yubikey-3-dr` (from offsite)
- `usb-backup` (from USB drive)

This allows you to revoke even if you only have access to the compromised key + 1 other key.

### Step 2: Initiate Revocation

```bash
./templedb key revoke yubikey-1-primary \
  --reason "Lost Yubikey, potential compromise" \
  --quorum 2
```

### Step 3: Approve with Keys

The command will prompt you to approve with 2 keys:

```
KEY REVOCATION PROCEDURE
======================================================================

Revoking key: yubikey-1-primary
Reason: Lost Yubikey, potential compromise

This action requires approval from 2 keys (including the one being revoked if available)
Total active keys: 4

======================================================================
COLLECTING APPROVALS
======================================================================

Approval 1/2
Key: yubikey-1-primary
  (This is the key being revoked)

Use this key for approval? [y/n/skip]: y

Approval needed from key: yubikey-1-primary (yubikey)
  Please insert the Yubikey and enter PIN when prompted

✓ Approval granted with yubikey-1-primary

Approval 2/2
Key: yubikey-2-backup

Use this key for approval? [y/n/skip]: y

Approval needed from key: yubikey-2-backup (yubikey)
  Please insert the Yubikey and enter PIN when prompted

✓ Approval granted with yubikey-2-backup

✓ Approval granted with yubikey-2-backup

✓ Received 2/2 approvals

Approving keys:
  - yubikey-1-primary (yubikey)
  - yubikey-2-backup (yubikey)

======================================================================
FINAL CONFIRMATION
======================================================================

Key to revoke: yubikey-1-primary
Reason: Lost Yubikey, potential compromise

This will:
  1. Mark key as REVOKED (cannot be undone)
  2. Remove key from ALL secrets
  3. Re-encrypt all secrets without this key

Proceed with revocation? [yes/no]: yes

Revoking key yubikey-1-primary...

Re-encrypting 5 secrets without revoked key...
  ✓ Re-encrypted myproject (default)
  ✓ Re-encrypted myproject (production)
  ✓ Re-encrypted otherproject (default)
  ✓ Re-encrypted webapp (staging)
  ✓ Re-encrypted api (production)

======================================================================
✓ KEY REVOCATION COMPLETE
======================================================================

Revoked: yubikey-1-primary
Reason: Lost Yubikey, potential compromise
Approved by: yubikey-1-primary, yubikey-2-backup
Secrets re-encrypted: 5
```

### Step 4: Add Replacement Key

After revocation, add a new key to maintain 4-key redundancy:

```bash
# Setup new Yubikey
age-plugin-yubikey --generate

# Register it
./templedb key add yubikey \
  --name "yubikey-4-replacement" \
  --location "daily-use" \
  --notes "Replacement for revoked yubikey-1-primary"

# Add to all secrets
./templedb secret add-key myproject --key yubikey-4-replacement
./templedb secret add-key otherproject --key yubikey-4-replacement
# ... repeat for all projects
```

---

## Security Properties

### Quorum Prevents Single-Key Compromise

**Attack Scenario:** Attacker steals Yubikey #1
- ❌ Cannot revoke other keys (needs 2 keys total, only has 1)
- ❌ Cannot access secrets without PIN
- ✅ You can revoke attacker's key using any 2 of your remaining 3 keys

**Attack Scenario:** You lose Yubikey #1 but still have it temporarily
- ✅ You can use the lost key + 1 backup key to revoke it immediately
- Faster response time (don't need to retrieve 2 backup keys)

### Defense in Depth

```
Revocation requires:
┌─────────────────────────────────────────┐
│ Physical possession of 2 keys           │
│          +                              │
│ Knowledge of 2 PINs                     │
│          +                              │
│ Access to TempleDB database             │
└─────────────────────────────────────────┘
```

### Audit Trail

Every revocation is logged with:
- Timestamp
- Revoking user
- Reason
- Approving keys
- All re-encrypted secrets

```bash
# View revocation audit log
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM encryption_key_audit WHERE action = 'revoke'"
```

---

## Emergency Revocation Procedures

### Scenario 1: Lost Primary Yubikey

```bash
# 1. Get backup keys from secure storage
# - Yubikey #2 from safe
# - Yubikey #3 from offsite OR USB backup

# 2. Revoke compromised key with 2-of-3 approval
./templedb key revoke yubikey-1-primary \
  --reason "Lost during travel, potential compromise"

# 3. Add replacement key
age-plugin-yubikey --generate  # On new Yubikey
./templedb key add yubikey --name "yubikey-4-replacement" --location "daily-use"

# 4. Add to all secrets
for project in $(./templedb project list --format json | jq -r '.[].slug'); do
  ./templedb secret add-key $project --key yubikey-4-replacement
done
```

### Scenario 2: Suspected Compromise

```bash
# 1. Immediate revocation
./templedb key revoke yubikey-1-primary \
  --reason "Suspicious activity detected"

# 2. Rotate ALL remaining keys as precaution
# Generate 3 new Yubikeys + new USB key
# Add all new keys to secrets
# Remove all old keys from secrets

# 3. Audit recent access
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM encryption_key_audit
   WHERE timestamp > datetime('now', '-7 days')
   ORDER BY timestamp DESC"
```

### Scenario 3: Employee Departure

```bash
# 1. Revoke their personal key
./templedb key revoke employee-yubikey \
  --reason "Employee departure - access termination"

# 2. Ensure remaining keys are in your possession
./templedb key list

# 3. Test all remaining keys
./templedb key test yubikey-2-backup
./templedb key test yubikey-3-dr
./templedb key test usb-backup
```

---

## Best Practices

### Before Revocation

✅ **DO:**
- Verify you have access to 2 other keys
- Test those keys work: `./templedb key test <key-name>`
- Document reason for revocation
- Have replacement key ready
- Backup database before revocation

❌ **DON'T:**
- Revoke without 2 other working keys
- Revoke last working key
- Revoke without documented reason
- Delay revocation if compromise suspected

### After Revocation

✅ **DO:**
- Add replacement key immediately
- Test all secrets decrypt: `./templedb secret export <project> --format json`
- Store revoked key securely (don't destroy - forensics)
- Update key inventory documentation
- Review audit logs

❌ **DON'T:**
- Reuse revoked key
- Leave <4 active keys
- Forget to update secret inventories
- Skip testing after revocation

### Regular Audits

**Monthly:**
```bash
# Test all keys
for key in $(./templedb key list --format json | jq -r '.[].key_name'); do
  ./templedb key test $key
done

# Review recent usage
./templedb key list
```

**Quarterly:**
```bash
# Review revoked keys
./templedb key show-revoked

# Audit trail review
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM encryption_key_audit
   WHERE timestamp > datetime('now', '-90 days')
   ORDER BY timestamp DESC"
```

**Annually:**
```bash
# Rotate all keys
# This is a planned, non-emergency revocation
# Ensures keys don't become stale
```

---

## Troubleshooting

### "Not enough active keys for 2-of-N revocation"

**Problem:** Trying to revoke but <2 total active keys exist

**Solution:**
```bash
# Check how many active keys you have
./templedb key list

# If you have <2 total active keys, you cannot revoke
# You need at least 2 keys to approve any revocation

# Add more keys first, then revoke
```

### "Failed to approve with this key"

**Problem:** Decryption failed during approval

**Solution:**
```bash
# For Yubikeys: Check PIN, check Yubikey detected
ykman list
ykman piv info

# For filesystem keys: Check file exists
ls -la ~/.age/backup-key.txt

# Test the key independently
./templedb key test <key-name>
```

### "Re-encryption failed for some secrets"

**Problem:** Some secrets couldn't be re-encrypted

**Solution:**
```bash
# Identify which secrets failed
./templedb secret show-keys <project>

# Manually fix each failed secret
# 1. Decrypt with old keys (before revocation completed)
# 2. Re-initialize with new keys
./templedb secret export <project> --format yaml > /tmp/secrets.yml
./templedb secret init-multi <project> --keys key1,key2,key3
./templedb secret edit <project>  # Paste old secrets
```

---

## Advanced Topics

### Custom Quorum Requirements

Default is 2-of-4, but you can change:

```bash
# Require 3-of-4 keys for revocation (higher security)
./templedb key revoke yubikey-1-primary --quorum 3

# Require all 4 keys for revocation (maximum security)
./templedb key revoke yubikey-1-primary --quorum 4

# Require 1-of-4 keys for revocation (lower security, emergency only)
./templedb key revoke yubikey-1-primary --quorum 1
```

### Batch Revocation

Revoke multiple keys at once:

```bash
# If multiple keys compromised
./templedb key revoke yubikey-1-primary --reason "Compromise incident #2026-03"
./templedb key revoke yubikey-2-backup --reason "Compromise incident #2026-03"

# Then add 2 new keys and re-encrypt everything
```

### Programmatic Revocation

```python
#!/usr/bin/env python3
import subprocess

def revoke_key(key_name, reason):
    result = subprocess.run([
        "./templedb", "key", "revoke", key_name,
        "--reason", reason,
        "--quorum", "2"
    ], capture_output=True, text=True)
    return result.returncode == 0

# Example usage
if revoke_key("yubikey-1-primary", "Automated rotation"):
    print("Revocation successful")
```

---

## Summary

```bash
# Revoke key (requires 2 of any 4 keys, including the one being revoked)
./templedb key revoke <key-name> --reason "Lost/compromised"

# View revoked keys
./templedb key show-revoked

# Test remaining keys
./templedb key test <key-name>

# Add replacement
./templedb key add yubikey --name "replacement-key"
./templedb secret add-key <project> --key replacement-key
```

**Key revocation is irreversible** - proceed with caution and proper authorization.

---

*For more information:*
- [Multi-Yubikey Setup](MULTI_YUBIKEY_SETUP.md)
- [Disaster Recovery](MULTI_YUBIKEY_SETUP.md#disaster-recovery)
- [Key Management](MULTI_YUBIKEY_SETUP.md#key-management)
