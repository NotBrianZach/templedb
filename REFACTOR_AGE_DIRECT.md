# Refactor: Remove SOPS, Use Age Directly

## Current Architecture

```
User -> templedb -> SOPS (subprocess) -> age (subprocess) -> encryption
```

SOPS is a middleman that:
- Wraps age encryption/decryption
- Adds YAML metadata about encryption keys
- Adds complexity and an extra dependency

## Proposed Architecture

```
User -> templedb -> age (subprocess) -> encryption
```

Direct age usage:
- Simpler dependency chain (just age, not sops + age)
- More control over encryption process
- Cleaner error handling
- Same security model (age provides the crypto)

## Implementation Changes

### 1. Replace SOPS Functions

**Current (main.py:358-369):**
```python
def sops_encrypt_yaml(plaintext_yaml: bytes, age_recipient: str) -> bytes:
    return _run_sops(
        ["--encrypt", "--input-type", "yaml", "--output-type", "yaml",
         "--age", age_recipient, "/dev/stdin"],
        stdin_bytes=plaintext_yaml,
    )

def sops_decrypt_yaml(sops_yaml: bytes) -> bytes:
    return _run_sops(["--decrypt", "/dev/stdin"], stdin_bytes=sops_yaml)
```

**Proposed:**
```python
def age_encrypt(plaintext: bytes, age_recipient: str) -> bytes:
    """Encrypt data using age with the given recipient public key."""
    try:
        proc = subprocess.run(
            ["age", "-r", age_recipient, "-a"],  # -a for ASCII armor
            input=plaintext,
            capture_output=True,
            check=True,
        )
        return proc.stdout
    except FileNotFoundError:
        bail("age not found on PATH. Install: https://github.com/FiloSottile/age")
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode("utf-8", errors="replace")
        bail(f"age encryption failed: {err.strip()}")

def age_decrypt(encrypted: bytes) -> bytes:
    """Decrypt age-encrypted data using SOPS_AGE_KEY_FILE."""
    key_file = os.environ.get("SOPS_AGE_KEY_FILE") or os.path.expanduser(
        "~/.config/sops/age/keys.txt"
    )
    if not os.path.exists(key_file):
        bail(f"Age key file not found: {key_file}")

    try:
        proc = subprocess.run(
            ["age", "-d", "-i", key_file],
            input=encrypted,
            capture_output=True,
            check=True,
        )
        return proc.stdout
    except FileNotFoundError:
        bail("age not found on PATH. Install: https://github.com/FiloSottile/age")
    except subprocess.CalledProcessError as e:
        err = e.stderr.decode("utf-8", errors="replace")
        bail(f"age decryption failed: {err.strip()}")
```

### 2. Update All Callsites

**Files to update:**
- `cmd_secret_init()` - line 700
- `cmd_secret_edit()` - lines 732, 742
- `cmd_secret_export()` - line 762
- `cmd_secret_print_sops()` - rename to `cmd_secret_print_raw()` or remove

**Changes:**
```python
# OLD
encrypted = sops_encrypt_yaml(plaintext_yaml, age_recipient)
plaintext_yaml = sops_decrypt_yaml(row[0])

# NEW
encrypted = age_encrypt(plaintext_yaml, age_recipient)
plaintext_yaml = age_decrypt(row[0])
```

### 3. Database Schema Changes

**Current:** Secrets stored as SOPS-encrypted YAML blobs
**New:** Secrets stored as age-encrypted YAML blobs

**Migration needed?** No! The encrypted blob format is actually the same:
- SOPS calls age under the hood
- The blob in the DB is already age-encrypted
- We just need to strip the SOPS metadata wrapper

**Actually, wait...** SOPS adds metadata to the YAML. Let me check if we need a migration.

**Options:**
1. **Keep compatible:** Detect SOPS-wrapped secrets and handle both formats during transition
2. **Clean break:** Add migration script to re-encrypt all secrets with plain age
3. **Lazy migration:** On first edit, re-encrypt without SOPS wrapper

Recommend: **Option 3 (lazy migration)** - easiest for users

### 4. CLI Changes

**Remove:**
- `templedb secret print-sops` command (or rename to `print-raw`)

**Keep:**
- `templedb secret init`
- `templedb secret edit`
- `templedb secret export`

### 5. Documentation Updates

**Files to update:**
- QUICKSTART.md - remove SOPS references, just say "age encryption"
- SECURITY.md - update security model section
- .claude/skills/templedb-secrets/SKILL.md - update all references
- examples/*/README.md - update setup instructions

**Environment variable:**
- Keep `SOPS_AGE_KEY_FILE` for now (backward compatibility)
- Add `TEMPLEDB_AGE_KEY_FILE` as new name
- Eventually deprecate `SOPS_AGE_KEY_FILE`

### 6. Error Messages

Update error messages to guide users:
```python
# OLD
bail("SOPS_AGE_KEY_FILE not set or file doesn't exist")

# NEW
bail("""Age key file not found.

Set TEMPLEDB_AGE_KEY_FILE or SOPS_AGE_KEY_FILE to your age key path,
or place your key at ~/.config/sops/age/keys.txt

Generate a key: age-keygen -o ~/.config/sops/age/keys.txt
""")
```

## Benefits

1. **Simpler dependency:** Remove SOPS from installation requirements
2. **Clearer errors:** Direct age errors, not wrapped by SOPS
3. **Better control:** We decide how to format/store encrypted data
4. **Faster:** One less subprocess in the chain
5. **More flexible:** Can easily add features like:
   - Multiple recipient keys (age natively supports this)
   - Hardware key support (age plugins)
   - Passphrase-based encryption (age -p)

## Migration Path

### Phase 1: Add age-direct functions
- Implement `age_encrypt()` and `age_decrypt()`
- Add detection for SOPS-wrapped vs plain age-encrypted secrets
- Keep SOPS functions as fallback

### Phase 2: Lazy migration
- On `secret edit`, detect if secret is SOPS-wrapped
- If yes, re-encrypt with plain age on save
- Log migration: "Migrated secret from SOPS to age-direct"

### Phase 3: Remove SOPS
- After all secrets are migrated, remove SOPS functions
- Remove SOPS from dependencies
- Update all documentation

### Phase 4: Optimize
- Add caching for age subprocess calls
- Consider using pyage library if available
- Add support for age features (multiple recipients, ssh keys, etc.)

## Testing Plan

1. Create test project with secrets
2. Encrypt with new age_encrypt()
3. Decrypt with new age_decrypt()
4. Verify round-trip works
5. Test with existing SOPS-encrypted secrets (backward compat)
6. Test migration path
7. Test error cases (missing key, wrong recipient, corrupted blob)

## Timeline

- Phase 1: 1-2 hours (implement functions + tests)
- Phase 2: 30 min (add migration logic)
- Phase 3: 1 hour (remove SOPS, update docs)
- Phase 4: Future enhancement

**Total: ~3 hours of dev work**

## Questions

1. Should we support SOPS format indefinitely or force migration?
   - Recommend: Support both, auto-migrate on edit

2. Should we keep `SOPS_AGE_KEY_FILE` env var name?
   - Recommend: Support both `SOPS_AGE_KEY_FILE` and `TEMPLEDB_AGE_KEY_FILE`

3. Should we add encryption metadata (version, recipient, timestamp)?
   - Recommend: Store in DB columns, not in encrypted blob

4. Should we use a Python age library instead of subprocess?
   - Recommend: Start with subprocess (simpler), consider library later

## Related Issues

- Backward compatibility with existing secrets
- Key rotation mechanism
- Multiple recipient support
- Integration with hardware keys (YubiKey, etc.)
