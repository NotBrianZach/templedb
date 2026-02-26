# Backup Yubikey Setup for TempleDB

Complete guide to setting up backup Yubikeys for redundancy and disaster recovery.

---

## Overview

**Yes, backup Yubikeys work perfectly!** You can encrypt secrets to multiple Yubikeys simultaneously, so any one of them can decrypt.

This provides:
- 🔄 **Redundancy** - Multiple keys can decrypt
- 🚨 **Disaster recovery** - Lost primary? Use backup!
- 👥 **Team access** - Different team members have different keys
- ✅ **Zero trust** - Each key is independent

---

## How It Works

### Multiple Recipients in Age

The `age` encryption tool supports **multiple recipients**:

```bash
# Encrypt to 3 different recipients
age -r age1yubikey1abc... \
    -r age1yubikey1def... \
    -r age1qw7ry8g2xyz... \
    file.txt > file.txt.age

# ANY of the 3 can decrypt
age -d -i ~/.config/age-plugin-yubikey/identities.txt file.txt.age
```

### TempleDB Multi-Recipient Support

TempleDB now supports comma-separated recipients:

```bash
# Initialize with multiple recipients
./templedb secret init myproject \
  --age-recipient "age1yubikey1abc...,age1yubikey1def...,age1qw7ry8g2xyz..."
```

**Result:** Secrets encrypted to ALL recipients. Any one can decrypt.

---

## Setup Strategy

### Strategy 1: Primary + Backup Yubikey

**Use case:** Personal use with backup

```bash
# 1. Generate identity on primary Yubikey
age-plugin-yubikey --generate
PRIMARY=$(age-plugin-yubikey --identity | grep age1yubikey)

# 2. Remove primary, insert backup Yubikey
# (Unplug primary, plug in backup)

# 3. Generate identity on backup Yubikey
age-plugin-yubikey --generate
BACKUP=$(age-plugin-yubikey --identity | grep age1yubikey)

# 4. Initialize secrets with BOTH recipients
./templedb secret init myproject \
  --age-recipient "$PRIMARY,$BACKUP"
```

**Result:**
- ✅ Either Yubikey can decrypt
- ✅ If you lose primary, backup works
- ✅ Store backup in safe location

### Strategy 2: Yubikey + File Backup

**Use case:** Hardware security + emergency access

```bash
# 1. Generate Yubikey identity
age-plugin-yubikey --generate
YUBIKEY=$(age-plugin-yubikey --identity | grep age1yubikey)

# 2. Generate backup age key file
age-keygen -o ~/.config/age/backup-key.txt
BACKUP=$(age-keygen -y ~/.config/age/backup-key.txt)

# 3. Initialize with both
./templedb secret init myproject \
  --age-recipient "$YUBIKEY,$BACKUP"

# 4. Store backup key in safe place
#    - Password manager
#    - Encrypted USB drive
#    - Safe deposit box
#    - Printed on paper (not recommended)
```

**Result:**
- ✅ Daily use: Yubikey (hardware security)
- ✅ Emergency: Backup key file
- ⚠️ Backup key is less secure (file can be stolen)

### Strategy 3: Team Access

**Use case:** Multiple team members need access

```bash
# Each team member generates their own Yubikey identity
# Alice:
ALICE=$(age-plugin-yubikey --identity | grep age1yubikey)

# Bob:
BOB=$(age-plugin-yubikey --identity | grep age1yubikey)

# Charlie:
CHARLIE=$(age-plugin-yubikey --identity | grep age1yubikey)

# Initialize with all team members
./templedb secret init prod-db \
  --age-recipient "$ALICE,$BOB,$CHARLIE"
```

**Result:**
- ✅ Alice, Bob, or Charlie can decrypt
- ✅ Each uses their own Yubikey + PIN
- ✅ Can revoke access by re-encrypting without their key

---

## Complete Backup Setup Example

### Step 1: Setup Primary Yubikey

```bash
# Insert primary Yubikey
lsusb | grep -i yubi  # Verify detected

# Generate identity
age-plugin-yubikey --generate

# Set PIN and optional touch policy
# (follow prompts)

# Get recipient
PRIMARY=$(age-plugin-yubikey --identity | grep age1yubikey)
echo "Primary: $PRIMARY"
```

### Step 2: Setup Backup Yubikey

```bash
# Remove primary, insert backup
# Wait for it to be detected

# Generate identity on backup
age-plugin-yubikey --generate

# Set DIFFERENT PIN (recommended)
# Configure same touch policy (optional)

# Get recipient
BACKUP=$(age-plugin-yubikey --identity | grep age1yubikey)
echo "Backup: $BACKUP"
```

### Step 3: Initialize Secrets with Both

```bash
# Initialize with comma-separated recipients
./templedb secret init myproject \
  --age-recipient "$PRIMARY,$BACKUP"

# Output:
# Initialized secrets for myproject (profile: default)
```

### Step 4: Test Both Keys

```bash
# Test with primary
# (Insert primary Yubikey)
./templedb secret edit myproject
# Enter PIN for primary
# Edit, save, exit

# Test with backup
# (Remove primary, insert backup)
./templedb secret edit myproject
# Enter PIN for backup
# Should work!
```

### Step 5: Label and Store

```bash
# Label your Yubikeys
# Primary: "TempleDB Primary - Daily Use"
# Backup:  "TempleDB Backup - Safe Storage"

# Store backup in safe location:
# - Safe deposit box
# - Fireproof safe
# - Trusted family member
# - Different physical location
```

---

## Managing Recipients

### View Current Recipients

```bash
# Decrypt secret and check header (shows which keys can decrypt)
./templedb secret export myproject --format yaml | head -3
```

Unfortunately, age doesn't store recipient info in the ciphertext. You'll need to track this separately.

**Recommendation:** Store in project documentation

```yaml
# secrets-config.yml
project: myproject
recipients:
  - name: "Primary Yubikey"
    recipient: "age1yubikey1qw7ry8g2..."
    owner: "Your Name"
    location: "Daily keychain"

  - name: "Backup Yubikey"
    recipient: "age1yubikey1abc123..."
    owner: "Your Name"
    location: "Safe deposit box"

  - name: "Emergency Backup"
    recipient: "age1qw7ry8g2xyz..."
    type: "file"
    location: "Password manager"
```

### Add New Recipient

To add a new Yubikey/recipient to existing secrets:

```bash
# 1. Export current secrets
./templedb secret export myproject --format yaml > /tmp/secrets.yml

# 2. Get new recipient
# (Insert new Yubikey)
age-plugin-yubikey --generate
NEW_RECIPIENT=$(age-plugin-yubikey --identity | grep age1yubikey)

# 3. Re-initialize with OLD + NEW recipients
OLD_RECIPIENTS="age1yubikey1abc...,age1yubikey1def..."
./templedb secret init myproject \
  --age-recipient "$OLD_RECIPIENTS,$NEW_RECIPIENT"

# 4. Re-import secrets
./templedb secret edit myproject
# Paste contents of /tmp/secrets.yml
# Save and exit

# 5. Clean up
shred -u /tmp/secrets.yml
```

### Remove Recipient (Revoke Access)

To revoke a recipient's access:

```bash
# 1. Export secrets with PRIMARY Yubikey
./templedb secret export myproject --format yaml > /tmp/secrets.yml

# 2. Re-initialize with only remaining recipients
REMAINING="age1yubikey1abc...,age1yubikey1xyz..."
./templedb secret init myproject \
  --age-recipient "$REMAINING"

# 3. Re-import secrets
./templedb secret edit myproject
# Paste from /tmp/secrets.yml

# 4. Clean up
shred -u /tmp/secrets.yml
```

**Note:** The revoked Yubikey can still decrypt OLD versions of secrets (in database history). To fully revoke, you'd need to rotate all secret values.

---

## Best Practices

### Physical Security

✅ **DO:**
- Store primary and backup in **different physical locations**
- Use **different PINs** for each Yubikey (in case one is observed)
- Label Yubikeys clearly but discretely
- Keep backup in fireproof/waterproof storage
- Test backup key quarterly

❌ **DON'T:**
- Store both Yubikeys together
- Use the same PIN for all keys
- Leave backup accessible to others
- Forget where backup is stored

### Access Policy

**2 Yubikey Minimum:**
```
Primary → Daily use (on keychain)
Backup  → Safe storage (tested quarterly)
```

**3 Yubikey Recommended:**
```
Primary → Daily use
Backup  → Home safe
Offsite → Safe deposit box / trusted location
```

**Team Access:**
```
Each team member → Their own Yubikey
Team backup      → Secure shared storage
Emergency backup → Key file in vault
```

### Testing Schedule

Test your backup keys regularly:

```bash
# Monthly: Quick test
./templedb secret export myproject --format shell > /dev/null

# Quarterly: Full backup test
# 1. Remove primary
# 2. Use backup to edit secrets
# 3. Verify deployment works
./templedb deploy run myproject --target staging --dry-run
```

---

## Disaster Recovery Scenarios

### Scenario 1: Lost Primary Yubikey

**Impact:** Cannot decrypt secrets with primary

**Recovery:**
1. ✅ Use backup Yubikey immediately
2. ✅ Order replacement Yubikey
3. ✅ Generate new identity on replacement
4. ✅ Add replacement to recipients (remove lost key)
5. ✅ Update documentation

```bash
# With backup Yubikey inserted
./templedb secret export myproject --format yaml > /tmp/secrets.yml

# Generate on new Yubikey
age-plugin-yubikey --generate
NEW_PRIMARY=$(age-plugin-yubikey --identity | grep age1yubikey)

# Get backup recipient
BACKUP="age1yubikey1abc..."

# Re-initialize
./templedb secret init myproject \
  --age-recipient "$NEW_PRIMARY,$BACKUP"

# Restore secrets
./templedb secret edit myproject
# Import from /tmp/secrets.yml
```

### Scenario 2: Broken/Malfunctioning Yubikey

**Impact:** Yubikey not recognized or not working

**Recovery:**
1. ✅ Try different USB port
2. ✅ Try different computer
3. ✅ Check pcscd service
4. ✅ If truly broken, use backup
5. ✅ RMA broken Yubikey (Yubico has good support)

### Scenario 3: Forgot PIN

**Impact:** Cannot decrypt (3 wrong attempts = locked)

**Recovery:**
1. ⚠️ Use PUK to reset PIN (if you set one)
2. ✅ Use backup Yubikey
3. ❌ If no PUK and no backup: **secrets are lost**

```bash
# Reset PIN with PUK
ykman piv access change-pin --puk <PUK>

# Or use backup Yubikey
# (same as Scenario 1)
```

### Scenario 4: Lost ALL Yubikeys

**Impact:** Cannot decrypt secrets if no backup key file

**Recovery:**
- ✅ If you have file backup: Use it
- ❌ If Yubikey-only: **Secrets are permanently lost**

**Mitigation:**
Always have at least one non-hardware backup:
```bash
age-keygen -o ~/.config/age/emergency-backup.txt
# Store in password manager or vault
```

---

## CI/CD Integration

### Problem: CI doesn't have physical Yubikey

**Solution: Separate CI Profile**

```bash
# Generate file-based key for CI
age-keygen -o ~/.config/age/ci-key.txt
CI_KEY=$(age-keygen -y ~/.config/age/ci-key.txt)

# Initialize separate profile
./templedb secret init myproject \
  --profile ci \
  --age-recipient "$CI_KEY"

# In CI pipeline
export TEMPLEDB_AGE_KEY_FILE=/path/to/ci-key.txt
./templedb deploy run myproject --profile ci --target staging
```

**Team Members use Yubikeys:**
```bash
# Each developer uses their Yubikey
./templedb secret edit myproject --profile default
# Requires their Yubikey + PIN
```

**CI uses file key:**
```bash
# CI uses file-based key
./templedb deploy run myproject --profile ci
# No Yubikey required
```

---

## Cost Analysis

| Setup | Cost | Security | Availability |
|-------|------|----------|--------------|
| Single Yubikey | $50 | ⚠️ Medium | ❌ Single point of failure |
| Primary + Backup | $100 | ✅ High | ✅ Good redundancy |
| Primary + 2 Backups | $150 | ✅ High | ✅ Excellent redundancy |
| Team (3 members) | $150 | ✅ High | ✅ Distributed |
| Yubikey + File backup | $50 | ⚠️ Medium | ✅ Good |

**Recommendation:** Minimum 2 Yubikeys ($100)

---

## Implementation Checklist

Setting up backup Yubikeys:

- [ ] Order backup Yubikey(s)
- [ ] Generate identity on primary
- [ ] Generate identity on backup(s)
- [ ] Document all recipients
- [ ] Initialize secrets with all recipients
- [ ] Test each Yubikey can decrypt
- [ ] Label Yubikeys clearly
- [ ] Store backup(s) in safe location
- [ ] Document storage locations
- [ ] Set calendar reminder for quarterly testing
- [ ] Create disaster recovery runbook
- [ ] Share access with trusted person (optional)

---

## Summary

**Backup Yubikeys with TempleDB:**

✅ **Fully supported** - Use comma-separated recipients
✅ **Easy setup** - Each Yubikey generates independent identity
✅ **Flexible** - Mix Yubikeys and file keys
✅ **Secure** - Each key is protected independently
✅ **Disaster-proof** - Multiple independent recovery paths

**Recommended Setup:**
```bash
# Primary + Backup Yubikeys
PRIMARY=$(age-plugin-yubikey --identity | grep age1yubikey)
# Switch Yubikeys
BACKUP=$(age-plugin-yubikey --identity | grep age1yubikey)

./templedb secret init myproject \
  --age-recipient "$PRIMARY,$BACKUP"
```

**Cost:** ~$100 (2 Yubikeys)
**Security:** High
**Peace of mind:** Priceless 😊

---

*"Hope for the best, plan for the worst."*

**TempleDB - Where your secrets stay secret, even in disaster**
