# Any-of-N Key Decryption

**How TempleDB allows ANY of your keys to decrypt secrets**

---

## Overview

TempleDB implements **any-of-N decryption** where secrets encrypted with multiple recipients can be decrypted by **any single key** that was included during encryption.

```
Secret encrypted with 4 recipients:
├─ Yubikey #1 → ✅ Can decrypt alone
├─ Yubikey #2 → ✅ Can decrypt alone
├─ Yubikey #3 → ✅ Can decrypt alone
└─ USB backup → ✅ Can decrypt alone
```

**No coordination needed** - each key works independently.

---

## How It Works

### Multi-Recipient Encryption

When you initialize secrets with multiple keys:

```bash
./templedb secret init-multi myproject \
  --keys yubikey-1-primary,yubikey-2-backup,yubikey-3-dr,usb-backup
```

TempleDB uses `age` multi-recipient encryption:

1. **Generates random data encryption key (DEK)**
2. **Encrypts secret with DEK** (AES-256)
3. **Encrypts DEK with each recipient's public key** (X25519)
4. **Stores all encrypted DEKs in header** (age armor format)

Result: Secret blob contains 4 copies of the DEK, each encrypted for a different recipient.

### Any-Key Decryption

When you decrypt:

```bash
./templedb secret edit myproject
```

TempleDB passes **all available identity files** to `age`:

```bash
age -d \
  -i ~/.config/sops/age/keys.txt \
  -i ~/.age/key.txt \
  -i ~/.config/age-plugin-yubikey/identities.txt \
  < encrypted_secret
```

`age` tries each identity file:
1. Try first identity → Can't decrypt
2. Try second identity → Can't decrypt
3. Try third identity (Yubikey) → **Success!** Decrypts DEK
4. Use DEK to decrypt secret

**Only one key needs to succeed.**

---

## Automatic Key Discovery

TempleDB automatically discovers and tries keys from these locations:

1. **Environment Variables:**
   - `$TEMPLEDB_AGE_KEY_FILE`
   - `$SOPS_AGE_KEY_FILE`

2. **Standard Locations:**
   - `~/.config/sops/age/keys.txt`
   - `~/.age/key.txt`

3. **Yubikey Plugin:**
   - `~/.config/age-plugin-yubikey/identities.txt`

All existing files are automatically used for decryption attempts.

---

## Usage Examples

### Decrypt with Filesystem Key

```bash
# Your ~/.age/key.txt exists
./templedb secret edit myproject

# age automatically uses ~/.age/key.txt
# No Yubikey needed!
```

### Decrypt with Yubikey

```bash
# Insert Yubikey, enter PIN when prompted
./templedb secret edit myproject

# age tries filesystem keys first, then Yubikey
# Uses whichever works
```

### Decrypt with Specific Key

```bash
# Override to use only one specific key
export TEMPLEDB_AGE_KEY_FILE=/path/to/specific/key.txt
./templedb secret edit myproject
```

### Check Which Keys Will Be Tried

```bash
# Show all available identity files
ls -la ~/.config/sops/age/keys.txt \
       ~/.age/key.txt \
       ~/.config/age-plugin-yubikey/identities.txt
```

---

## Scenarios

### Scenario 1: Daily Use (Filesystem Key Available)

```bash
# You have ~/.age/key.txt
./templedb secret edit myproject

# Decrypts instantly with filesystem key
# No Yubikey needed, no PIN required
```

### Scenario 2: Primary Yubikey Available

```bash
# Yubikey #1 plugged in
./templedb secret edit myproject

# Tries filesystem keys first (if present)
# Falls back to Yubikey if needed
# Prompts for PIN
```

### Scenario 3: Backup Yubikey Only

```bash
# Get Yubikey #2 from safe
# Remove Yubikey #1
./templedb secret edit myproject

# Works with Yubikey #2
# Each Yubikey has independent identity
```

### Scenario 4: Emergency (USB Backup)

```bash
# All Yubikeys unavailable
# Get USB drive from secure storage

# Copy backup key to standard location
cp /mnt/usb/backup-key.txt ~/.age/key.txt

./templedb secret edit myproject

# Works with filesystem backup key
```

### Scenario 5: Multiple Keys Present

```bash
# You have:
#   - ~/.age/key.txt
#   - Yubikey #1 plugged in

./templedb secret edit myproject

# age tries both:
#   1. Tries ~/.age/key.txt → Success! (faster, no PIN)
#   2. Doesn't need to try Yubikey

# Uses first working key
```

---

## Security Properties

### 1. No Key Coordination

Each key works **independently**:
- ❌ Don't need multiple keys present
- ❌ Don't need to coordinate between keys
- ✅ Any single key is sufficient

### 2. Graceful Degradation

Lose 3 of 4 keys:
- ✅ Still works with remaining 1 key
- ✅ No coordination needed
- ✅ No key recovery ceremony

### 3. Convenience Hierarchy

```
Fastest ←────────────────────────────────────→ Slowest
Filesystem key      →      Yubikey (with PIN)
(instant)                  (~2 seconds)
```

age tries keys in order you provide:
- Filesystem keys first (fast)
- Yubikey last (needs PIN)

### 4. Fail-Safe

If no keys work:
```
age decryption failed

Tried 3 identity file(s):
  - ~/.config/sops/age/keys.txt
  - ~/.age/key.txt
  - ~/.config/age-plugin-yubikey/identities.txt

Possible reasons:
  1. None of your keys can decrypt this secret
  2. Yubikey not inserted or PIN incorrect
  3. Secret was encrypted with different keys
```

---

## Testing

### Test Multi-Key Decryption

```bash
# Run test script
/tmp/test_multikey_decryption.sh

# Output:
# Testing Multi-Key Decryption
# =============================
#
# 1. Checking available identity files...
#   ✓ Found: ~/.config/sops/age/keys.txt
#   ✓ Found: ~/.age/key.txt
#   ✓ Found: ~/.config/age-plugin-yubikey/identities.txt
#
# Found 3 identity file(s)
#
# 2. Getting public keys (recipients)...
#   - age1cv5kqala4k33u7... (sops)
#   - age1ef546gvcpxcuet... (age)
#   - age1yubikey1qw7ry8g2... (yubikey)
#
# Found 3 recipient(s)
#
# 3. Encrypting test message with 3 recipients...
#   ✓ Encryption successful
#
# 4. Testing decryption with each identity...
#   Testing: ~/.config/sops/age/keys.txt
#     ✓ Decryption successful
#   Testing: ~/.age/key.txt
#     ✓ Decryption successful
#   Testing: ~/.config/age-plugin-yubikey/identities.txt
#     ✓ Decryption successful
#
# =============================
# Results:
#   Identities tested: 3
#   Successful decryptions: 3
#
# ✓ ALL TESTS PASSED
#   Any of your 3 key(s) can decrypt
```

### Manual Test

```bash
# 1. Create test secret
echo "test data" | age -r $(age-keygen -y ~/.age/key.txt) > /tmp/test.age

# 2. Decrypt with key
age -d -i ~/.age/key.txt < /tmp/test.age

# 3. Verify output
# Should show: test data
```

---

## Troubleshooting

### "No age key files found"

**Problem:** No identity files exist

**Solution:**
```bash
# Generate filesystem key
age-keygen -o ~/.age/key.txt

# Or setup Yubikey
age-plugin-yubikey --generate
```

### "age decryption failed"

**Problem:** None of your keys can decrypt

**Possible causes:**

1. **Wrong keys** - Secret encrypted with different keys
   ```bash
   # Check which keys encrypt the secret
   ./templedb secret show-keys myproject
   ```

2. **Yubikey not inserted**
   ```bash
   lsusb | grep -i yubi
   ```

3. **Wrong Yubikey PIN**
   ```bash
   # Check PIN retry counter
   ykman piv info
   ```

4. **Identity file doesn't match recipient**
   ```bash
   # Check your public key
   age-keygen -y ~/.age/key.txt

   # Check secret recipients (requires querying database)
   sqlite3 ~/.local/share/templedb/templedb.sqlite \
     "SELECT recipient FROM encryption_keys"
   ```

### Decryption succeeds but wrong content

**Problem:** Secret decrypts but shows unexpected data

**Causes:**
- Decrypted with wrong key for different secret
- Database corruption
- Secret overwritten

**Solution:**
```bash
# Check secret version history
./templedb vcs log
```

---

## Implementation Details

### Code Location

All three secret command files now support any-of-N decryption:

1. **`src/cli/commands/secret.py`** - Original secret commands
2. **`src/cli/commands/secret_multikey.py`** - Multi-key operations
3. **`src/cli/commands/key_revocation.py`** - Revocation flows

### Key Discovery Logic

```python
def _age_decrypt(self, encrypted: bytes) -> bytes:
    # Collect all available identity files
    key_file_candidates = [
        os.environ.get("TEMPLEDB_AGE_KEY_FILE"),
        os.environ.get("SOPS_AGE_KEY_FILE"),
        os.path.expanduser("~/.config/sops/age/keys.txt"),
        os.path.expanduser("~/.age/key.txt"),
        os.path.expanduser("~/.config/age-plugin-yubikey/identities.txt")
    ]

    # Filter to only existing files
    available_key_files = [kf for kf in key_file_candidates
                           if kf and os.path.exists(kf)]

    # Build age command with ALL available identity files
    age_cmd = ["age", "-d"]
    for key_file in available_key_files:
        age_cmd.extend(["-i", key_file])

    # age tries each identity until one works
    subprocess.run(age_cmd, input=encrypted, ...)
```

### Why Multiple `-i` Flags Work

`age` specification:
> When multiple identity files are provided, age attempts decryption with each identity in order until one succeeds.

This is **standard age behavior**, not TempleDB-specific.

---

## Best Practices

### Development

```bash
# Use fast filesystem key for rapid iteration
export TEMPLEDB_AGE_KEY_FILE=~/.age/dev-key.txt
./templedb secret edit myproject
```

### Production

```bash
# Use Yubikey for production (hardware-protected)
# Filesystem key as backup only
./templedb secret edit myproject
# Will prompt for Yubikey PIN
```

### Emergency Access

```bash
# Keep USB backup in secure location
# Only use when Yubikeys unavailable
cp /secure/location/backup-key.txt ~/.age/emergency-key.txt
export TEMPLEDB_AGE_KEY_FILE=~/.age/emergency-key.txt
./templedb secret edit myproject
```

### Key Hierarchy

Recommended priority order:
1. **Daily use:** Yubikey #1 (on person)
2. **Backup:** Yubikey #2 (safe)
3. **DR:** Yubikey #3 (offsite)
4. **Emergency:** USB filesystem key (vault)

age tries in order you specify via `-i` flags.

---

## Summary

```bash
# Secret encrypted with 4 keys
./templedb secret init-multi myproject \
  --keys key1,key2,key3,key4

# Decrypt with ANY key (automatic discovery)
./templedb secret edit myproject
# ↓
# age -d -i key1 -i key2 -i key3 -i key4
# ↓
# Tries each until one works
# ↓
# ✓ Decryption successful

# No coordination needed
# No quorum required
# Just need ONE key
```

**TempleDB - Decrypt with any key, whenever you need it** 🔑

---

*See also:*
- [Multi-Yubikey Setup](MULTI_YUBIKEY_SETUP.md)
- [Key Management](MULTI_KEY_QUICK_REFERENCE.md)
- [Disaster Recovery](KEY_REVOCATION_GUIDE.md#disaster-recovery)
