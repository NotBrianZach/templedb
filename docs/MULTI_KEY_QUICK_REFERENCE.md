# Multi-Key Secret Management - Quick Reference

**One-page cheat sheet for TempleDB multi-Yubikey secret management**

---

## Setup (One-Time)

```bash
# Automated setup script
./scripts/setup_multi_yubikey.sh

# Manual setup
./templedb migrate
age-plugin-yubikey --generate  # Repeat for each Yubikey
./templedb key add yubikey --name "yubikey-1-primary" --location "daily-use"
./templedb key add filesystem --name "usb-backup" --path ~/.age/backup-key.txt
```

---

## Daily Operations

### Initialize Secrets (Multi-Key)
```bash
./templedb secret init-multi myproject \
  --keys yubikey-1-primary,yubikey-2-backup,yubikey-3-dr,usb-backup
```

### Edit Secrets
```bash
./templedb secret edit myproject
# Uses any available key (Yubikey #1 if plugged in)
```

### Export Secrets
```bash
./templedb secret export myproject --format shell
./templedb secret export myproject --format json
./templedb secret export myproject --format dotenv
```

### Show Keys for Secret
```bash
./templedb secret show-keys myproject
```

---

## Key Management

### List Keys
```bash
./templedb key list
./templedb key list --all  # Include disabled/revoked
```

### Key Info
```bash
./templedb key info yubikey-1-primary
```

### Test Key
```bash
./templedb key test yubikey-1-primary
```

### Add Key to Secret
```bash
./templedb secret add-key myproject --key new-yubikey
```

### Remove Key from Secret
```bash
./templedb secret remove-key myproject --key old-yubikey
```

---

## Key Revocation

### Revoke Key (Requires 2 Other Keys)
```bash
./templedb key revoke yubikey-1-primary \
  --reason "Lost during travel" \
  --quorum 2
```

### Show Revoked Keys
```bash
./templedb key show-revoked
```

---

## Emergency Procedures

### Lost Primary Yubikey
```bash
# 1. Get backup keys (Yubikey #2 + #3 or USB)
# 2. Revoke compromised key
./templedb key revoke yubikey-1-primary --reason "Lost/stolen"

# 3. Add replacement
age-plugin-yubikey --generate
./templedb key add yubikey --name "yubikey-4-replacement"

# 4. Add to all secrets
./templedb secret add-key myproject --key yubikey-4-replacement
```

### All Yubikeys Unavailable
```bash
# Use USB backup key
export TEMPLEDB_AGE_KEY_FILE=~/.age/backup-key.txt
./templedb secret edit myproject
```

### Forgot Yubikey PIN
```bash
# Option 1: Reset with PUK
ykman piv access change-pin --pin <puk> --new-pin <new-pin>

# Option 2: Use different key (revoke old one later)
# Option 3: Factory reset (DESTROYS DATA)
ykman piv reset
```

---

## Key Locations

### Default Setup
```
┌─────────────────────────────────────────────────────┐
│ Yubikey #1 (Primary)      → On your person          │
│ Yubikey #2 (Backup)       → Office safe             │
│ Yubikey #3 (DR)           → Offsite (home/vault)    │
│ USB Backup Key            → Secure USB drive        │
└─────────────────────────────────────────────────────┘
```

### File Locations
```
~/.config/age-plugin-yubikey/identities.txt  # Yubikey identity refs
~/.age/backup-key.txt                        # Filesystem backup key
~/.local/share/templedb/templedb.sqlite      # Key registry database
```

---

## Database Queries

### List All Keys
```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM encryption_keys"
```

### Key Usage Statistics
```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM encryption_key_stats_view"
```

### Audit Trail
```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM encryption_key_audit ORDER BY timestamp DESC LIMIT 20"
```

### Secrets with Keys
```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM secrets_with_keys_view"
```

---

## Testing & Verification

### Test All Keys
```bash
for key in yubikey-1-primary yubikey-2-backup yubikey-3-dr usb-backup; do
  echo "Testing $key..."
  ./templedb key test $key
done
```

### Verify Secret Access
```bash
# Test decryption works
./templedb secret export myproject --format json > /dev/null && echo "✓ OK"
```

### Check Key Count
```bash
./templedb secret show-keys myproject | grep "Encrypted with"
# Should show: "Encrypted with 4 keys"
```

---

## Security Checklist

### Monthly
- [ ] Test all 4 keys work
- [ ] Review key usage: `./templedb key list`
- [ ] Check audit log for suspicious activity

### Quarterly
- [ ] Verify physical security of stored keys
- [ ] Test disaster recovery procedure
- [ ] Review and update key inventory documentation

### Annually
- [ ] Rotate all keys (planned revocation)
- [ ] Review and update security procedures
- [ ] Test complete loss recovery (with backups)

---

## Common Commands

```bash
# Full workflow: Setup → Initialize → Use
./scripts/setup_multi_yubikey.sh
./templedb secret init-multi myproject --keys yubikey-1-primary,yubikey-2-backup,yubikey-3-dr,usb-backup
./templedb secret edit myproject

# Add new key to existing secret
age-plugin-yubikey --generate
./templedb key add yubikey --name "new-key"
./templedb secret add-key myproject --key new-key

# Revoke compromised key
./templedb key revoke old-key --reason "Compromised"

# Emergency access with USB backup
export TEMPLEDB_AGE_KEY_FILE=/path/to/usb/backup-key.txt
./templedb secret edit myproject
```

---

## Environment Variables

```bash
# Override key file location
export TEMPLEDB_AGE_KEY_FILE=~/.age/backup-key.txt

# Use SOPS-compatible location
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt

# Yubikey plugin identity file
export AGE_PLUGIN_YUBIKEY_IDENTITY_FILE=~/.config/age-plugin-yubikey/identities.txt
```

---

## URLs & Documentation

- **Setup Guide:** [MULTI_YUBIKEY_SETUP.md](MULTI_YUBIKEY_SETUP.md)
- **Revocation Guide:** [KEY_REVOCATION_GUIDE.md](KEY_REVOCATION_GUIDE.md)
- **Yubikey Basics:** [YUBIKEY_SECRETS.md](advanced/YUBIKEY_SECRETS.md)
- **age:** https://github.com/FiloSottile/age
- **age-plugin-yubikey:** https://github.com/str4d/age-plugin-yubikey
- **ykman:** https://github.com/Yubico/yubikey-manager

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| No Yubikey detected | `lsusb \| grep -i yubi`, check pcscd service |
| Incorrect PIN | Try again, check attempts: `ykman piv info` |
| Decryption failed | Verify key in use: `./templedb key test <name>` |
| Key test failed | Check physical connection, PIN, identity file |
| Not enough keys for revocation | Need ≥3 total keys to revoke 1 |

---

## Support

```bash
# Get help
./templedb key --help
./templedb secret --help

# Check version
./templedb --version

# View logs
tail -f ~/.local/share/templedb/templedb.log
```

---

**TempleDB - Your secrets, multiply protected** 🔐

*Last updated: 2026-03-12*
