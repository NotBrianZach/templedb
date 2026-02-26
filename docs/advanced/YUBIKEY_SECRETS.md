# Using Yubikey for TempleDB Secrets

Complete guide to using hardware security keys (Yubikey) with TempleDB's secret management.

---

## Overview

TempleDB supports **hardware-backed encryption** using Yubikey (or other PIV-compatible hardware tokens) via the `age-plugin-yubikey` plugin. This provides:

- 🔐 **Hardware-backed encryption** - Private keys never leave the Yubikey
- 🔑 **PIN protection** - Requires PIN for decryption
- 💪 **Physical security** - Must have Yubikey physically present
- ✅ **FIPS 140-2 compliance** - For regulated environments
- 🚫 **No key files** - No private keys on disk to steal

---

## How It Works

### Standard Age Encryption (Current)
```
Private Key (on disk) → Encrypt/Decrypt → Secrets
   ~/.config/sops/age/keys.txt
```

**Risks:**
- Private key can be stolen from disk
- No physical security requirement
- No PIN protection

### Yubikey Age Encryption (Recommended)
```
Private Key (in Yubikey) → PIN Required → Encrypt/Decrypt → Secrets
   Hardware slot 9a (PIV)
```

**Benefits:**
- Private key is hardware-protected
- Requires physical Yubikey + PIN
- Much harder to compromise

---

## Setup

### 1. Install age-plugin-yubikey

#### Via Cargo (Rust)
```bash
cargo install age-plugin-yubikey
```

#### Via Binary Download
```bash
# Download from GitHub releases
wget https://github.com/str4d/age-plugin-yubikey/releases/latest/download/age-plugin-yubikey-linux-amd64.tar.gz
tar xzf age-plugin-yubikey-linux-amd64.tar.gz
sudo mv age-plugin-yubikey /usr/local/bin/
```

### 2. Verify Installation

```bash
age-plugin-yubikey --version
# Should show: age-plugin-yubikey 0.x.x
```

### 3. Initialize Yubikey for Age

This generates a new age identity on your Yubikey:

```bash
# List available Yubikeys
age-plugin-yubikey --list

# Generate age identity on PIV slot 9a
age-plugin-yubikey --generate

# Follow prompts:
#   - Enter current PIN (default: 123456)
#   - Set new PIN (required, 6-8 digits)
#   - Set PUK (optional, for PIN reset)
```

**Output:**
```
Generated age identity on slot 9a:
  age1yubikey1qw7ry8g2...  (recipient/public key)

Stored in: ~/.config/age-plugin-yubikey/identities.txt
```

### 4. Get Your Yubikey Recipient

```bash
# Show your age recipient (public key)
age-plugin-yubikey --identity

# Example output:
# age1yubikey1qw7ry8g2xy3z4abc123...
```

---

## Using with TempleDB

### Initialize Secrets with Yubikey

```bash
# Get your Yubikey recipient
YUBIKEY_RECIPIENT=$(age-plugin-yubikey --identity | grep age1yubikey)

# Initialize secrets
./templedb secret init myproject --age-recipient $YUBIKEY_RECIPIENT
```

### Edit Secrets (Requires Yubikey + PIN)

```bash
# Make sure Yubikey is plugged in
./templedb secret edit myproject

# When prompted:
#   1. Touch Yubikey if configured
#   2. Enter PIN (the PIN you set during --generate)
#   3. Edit secrets in $EDITOR
#   4. Save and exit
```

### Export Secrets (Requires Yubikey + PIN)

```bash
# Export requires Yubikey to decrypt
./templedb secret export myproject --format shell

# Will prompt for PIN each time
```

### Deployment (Requires Yubikey)

```bash
# Deployment will decrypt secrets using Yubikey
./templedb deploy run myproject --target staging

# Yubikey must be present and you must enter PIN
```

**For complete deployment workflows**, see [DEPLOYMENT_EXAMPLE.md](../DEPLOYMENT_EXAMPLE.md).

---

## Configuration

### Identity File Location

The plugin stores identity references in:
```
~/.config/age-plugin-yubikey/identities.txt
```

This file contains:
- Yubikey serial numbers
- Which PIV slot to use (9a, 9c, 9d, 9e)
- NOT the private key (that's in the Yubikey)

### Multiple Yubikeys

You can use multiple Yubikeys:

```bash
# Generate on first Yubikey
age-plugin-yubikey --generate

# Insert second Yubikey
age-plugin-yubikey --generate

# List all configured
age-plugin-yubikey --list
```

Each Yubikey gets its own age recipient.

### Environment Variables

```bash
# Override identity file location
export AGE_PLUGIN_YUBIKEY_IDENTITY_FILE=~/.config/age/yubikey-identities.txt

# Auto-confirm (dangerous, skips PIN prompt)
export AGE_PLUGIN_YUBIKEY_UNSAFE_SKIP_PIN=1  # NOT RECOMMENDED
```

---

## Advanced Usage

### Touch Requirement

Configure Yubikey to require physical touch for decryption:

```bash
# Requires ykman (yubikey-manager)
ykman piv keys set-touch-policy 9a ALWAYS

# Now you must touch Yubikey during decryption
```

### Multiple Recipients

Encrypt to both Yubikey AND a backup key:

```bash
# Get your Yubikey recipient
YUBIKEY=$(age-plugin-yubikey --identity | grep age1yubikey)

# Generate a backup age key
age-keygen -o ~/.config/age/backup-key.txt
BACKUP=$(age-keygen -y ~/.config/age/backup-key.txt)

# Store both in database metadata (future enhancement)
# For now, you'd need to re-encrypt manually
```

### Using Different PIV Slots

Yubikey has 4 PIV slots available:

```bash
# Generate on slot 9c (Digital Signature)
age-plugin-yubikey --generate --slot 9c

# Generate on slot 9d (Key Management)
age-plugin-yubikey --generate --slot 9d

# Generate on slot 9e (Card Authentication)
age-plugin-yubikey --generate --slot 9e
```

**Recommended:** Use slot **9a** (default) for age encryption.

---

## Security Best Practices

### PIN Policy

✅ **DO:**
- Use a strong 8-digit PIN
- Change default PIN (123456) immediately
- Store PUK securely (for PIN reset)
- Enable touch policy for critical secrets

❌ **DON'T:**
- Use weak PINs like 000000 or 123456
- Share your Yubikey
- Leave Yubikey unattended while unlocked
- Disable PIN requirement

### Backup Strategy

Since private key is in hardware:

1. **Multiple Yubikeys** - Generate same identity on backup Yubikey
2. **Backup age key** - Encrypt to both Yubikey + backup key file
3. **Paper backup** - Print recovery codes (age-plugin-yubikey supports this)

### Lost Yubikey

If you lose your Yubikey:

**Without backup:**
- ❌ Secrets are permanently lost
- Must re-initialize all secrets
- Can't decrypt existing secrets

**With backup:**
- ✅ Use backup Yubikey (if configured same slot)
- ✅ Use backup age key file (if multi-recipient)
- ✅ Use printed recovery codes

---

## Comparison: Standard vs Yubikey

| Feature | Standard Age | Age + Yubikey |
|---------|--------------|---------------|
| Key storage | File on disk | Hardware chip |
| PIN protection | ❌ No | ✅ Yes |
| Physical security | ❌ No | ✅ Required |
| Touch requirement | ❌ No | ⚙️ Optional |
| Key theft risk | ⚠️ High | ✅ Very Low |
| FIPS compliance | ❌ No | ✅ Yes (Yubikey 5 FIPS) |
| Backup complexity | ✅ Easy | ⚠️ Moderate |
| Cost | 🆓 Free | 💰 $45-65/key |

---

## Troubleshooting

### "No Yubikey found"

**Problem:** Plugin can't detect Yubikey

**Solutions:**
```bash
# Check Yubikey is detected
lsusb | grep -i yubi

# Check pcscd service (required for PIV)
sudo systemctl status pcscd
sudo systemctl start pcscd

# Re-seat Yubikey (unplug/replug)

# Install pcscd if missing
sudo apt install pcscd  # Debian/Ubuntu
sudo pacman -S pcscd    # Arch Linux
```

### "Incorrect PIN"

**Problem:** Wrong PIN or locked

**Solutions:**
```bash
# Check PIN retry counter
ykman piv info

# Reset PIN with PUK (if you know it)
ykman piv access change-pin --pin <old> --new-pin <new>

# Reset Yubikey PIV (WARNING: DESTROYS ALL PIV DATA)
ykman piv reset
```

### "Permission denied"

**Problem:** User doesn't have access to USB device

**Solutions:**
```bash
# Add user to correct group
sudo usermod -a -G plugdev $USER

# Or use udev rules
sudo wget -O /etc/udev/rules.d/70-yubikey.rules \
  https://raw.githubusercontent.com/Yubico/yubikey-manager/main/70-yubikey.rules

sudo udevadm control --reload-rules
```

### Decryption hangs

**Problem:** Waiting for touch that's not configured

**Solutions:**
```bash
# Check touch policy
ykman piv keys attest 9a

# Remove touch requirement if unintended
ykman piv keys set-touch-policy 9a OFF
```

---

## Migration Guide

### From Standard Age to Yubikey

1. **Generate Yubikey identity:**
   ```bash
   age-plugin-yubikey --generate
   YUBIKEY=$(age-plugin-yubikey --identity | grep age1yubikey)
   ```

2. **Decrypt existing secrets:**
   ```bash
   # Export to temporary file
   ./templedb secret export myproject --format yaml > /tmp/secrets.yml
   ```

3. **Re-initialize with Yubikey:**
   ```bash
   ./templedb secret init myproject --age-recipient $YUBIKEY
   ```

4. **Re-import secrets:**
   ```bash
   # Edit to add old secrets
   ./templedb secret edit myproject
   # Paste contents of /tmp/secrets.yml
   ```

5. **Clean up:**
   ```bash
   shred -u /tmp/secrets.yml  # Securely delete
   ```

### From Yubikey to Standard Age

If you need to migrate back (not recommended):

1. **Generate standard age key:**
   ```bash
   age-keygen -o ~/.config/age/keys.txt
   AGE_KEY=$(age-keygen -y ~/.config/age/keys.txt)
   ```

2. **Export and re-import** (same as above)

---

## CI/CD Considerations

### Problem: CI doesn't have Yubikey

For automated deployments, you have options:

#### Option 1: Separate CI Secrets
```bash
# Initialize separate profile for CI with file-based key
age-keygen -o ~/.config/age/ci-key.txt
CI_KEY=$(age-keygen -y ~/.config/age/ci-key.txt)

./templedb secret init myproject --profile ci --age-recipient $CI_KEY

# Use --profile ci in CI pipelines
./templedb deploy run myproject --profile ci
```

#### Option 2: Encrypted CI Secrets
```bash
# Encrypt the age key file itself with Yubikey
cat ~/.config/age/ci-key.txt | \
  age -r $YUBIKEY_RECIPIENT > ci-key.txt.age

# Store ci-key.txt.age in version control
# Decrypt on-demand with Yubikey locally
```

#### Option 3: Runtime Secret Injection
```bash
# Use CI platform's secret manager
# GitHub Actions, GitLab CI, etc. provide secret injection
# Don't store in TempleDB secrets at all
```

---

## Integration with TempleDB

TempleDB's current implementation **already supports Yubikey** with no code changes needed!

This works because:
1. TempleDB uses `age` command-line tool
2. `age` automatically detects and uses plugins
3. `age-plugin-yubikey` registers as `age` plugin
4. When you use an `age1yubikey...` recipient, age routes to the plugin

### What TempleDB Does

```python
# Encryption (secret.py:37-46)
subprocess.run(["age", "-r", age_recipient, "-a"], ...)
# If recipient starts with "age1yubikey", age uses the plugin

# Decryption (secret.py:73-78)
subprocess.run(["age", "-d", "-i", key_file], ...)
# Plugin identity file is checked automatically
```

**It just works!** 🎉

---

## Future Enhancements

Potential improvements to TempleDB's Yubikey support:

- [ ] Auto-detect Yubikey recipients in `secret init`
- [ ] Show which secrets use Yubikey vs file keys
- [ ] Support multiple recipients (Yubikey + backup)
- [ ] Store Yubikey serial number in metadata
- [ ] Warn before deployment if Yubikey not present
- [ ] TUI integration for PIN entry
- [ ] Touch confirmation feedback

---

## Summary

Using Yubikey with TempleDB:

1. **Install:** `cargo install age-plugin-yubikey`
2. **Generate:** `age-plugin-yubikey --generate`
3. **Get recipient:** `age-plugin-yubikey --identity`
4. **Use with TempleDB:** `./templedb secret init project --age-recipient age1yubikey...`

**Benefits:**
- ✅ Hardware-protected private keys
- ✅ PIN required for decryption
- ✅ Physical security requirement
- ✅ Works with existing TempleDB commands
- ✅ No code changes needed

**Tradeoffs:**
- ⚠️ More complex backup strategy
- ⚠️ Requires Yubikey for every decrypt
- ⚠️ CI/CD needs separate approach
- 💰 Hardware cost ($45-65/key)

---

*"Security is not a product, but a process."* - Bruce Schneier

**TempleDB - Where your secrets stay secret**
