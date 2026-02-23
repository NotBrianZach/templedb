# TempleDB Security Best Practices

## Current Security Model

TempleDB uses **age encryption** (https://age-encryption.org) to store secrets encrypted at rest in a SQLite database. When `templedb secret export` is called, secrets are decrypted using your age key and exported as environment variables.

**Key features:**
- Age encryption (modern, simple, secure)
- Per-project + per-profile secrets
- Multiple export formats (shell, JSON, YAML, dotenv)
- Audit logging for all secret operations

## Security Hardening Recommendations

### 1. Secure Secret Loading

Load secrets directly from the database when needed:

```bash
# Load secrets for current project
eval "$(templedb secret export my-project --format shell)"

# Or export to a file with restricted permissions
templedb secret export my-project --format dotenv > .env
chmod 600 .env
```

### 2. Limit Secret Scope

Use profiles to separate secrets by sensitivity:

```bash
# Only load production secrets when explicitly needed
if [ "$TEMPLEDB_ENV" = "production" ]; then
  eval "$(templedb secret export my-project --profile prod --format shell)"
else
  eval "$(templedb secret export my-project --profile dev --format shell)"
fi
```

### 3. Protect SOPS_AGE_KEY_FILE

Ensure your age key has minimal permissions:

```bash
chmod 400 ~/.config/sops/age/keys.txt
```

Consider using a hardware security key or TPM for key storage in production.

### 4. Reload Secrets After Updates

After editing secrets, reload them in your current shell:

```bash
# Edit secrets
templedb secret edit my-project

# Reload in current shell
eval "$(templedb secret export my-project --format shell)"
```

### 5. Audit Secret Access

Enable audit logging and monitor it:

```bash
# View recent secret accesses
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT ts, actor, action, project_slug, profile
   FROM audit_log
   ORDER BY ts DESC
   LIMIT 20;"
```

### 6. Implement Secret Rotation

Track secret age and rotate regularly:

```bash
# Check when secrets were last updated
templedb secret export my-app --format json | \
  jq -r '.meta.last_rotated // "NEVER ROTATED"'
```

## Alternative Approaches

### Option 1: SOPS files directly

Instead of SQLite + templedb, use SOPS files directly:

```bash
eval "$(sops -d secrets.yaml | yq -r '.env | to_entries | .[] | "export \(.key)=\(.value)"')"
```

**Pros**: Simpler, fewer dependencies
**Cons**: Less structured, no audit trail, no project/profile management

### Option 2: pass/gopass

Use password-store for secret management:

```bash
export DATABASE_URL="$(pass show project/database_url)"
export API_KEY="$(pass show project/api_key)"
```

**Pros**: Battle-tested, Git-backed versioning
**Cons**: Secrets loaded individually (slower), less structured

### Option 3: Hashicorp Vault

For team environments:

```bash
export VAULT_ADDR="https://vault.example.com"
eval "$(vault kv get -format=json secret/my-app | jq -r '.data.data | to_entries | .[] | "export \(.key)=\(.value)"')"
```

**Pros**: Centralized, audited, access control, dynamic secrets
**Cons**: Requires infrastructure, complexity, network dependency

### Option 4: Nix + sops-nix/agenix

If you're already using Nix:

```nix
# flake.nix
{
  inputs.sops-nix.url = "github:Mic92/sops-nix";

  # secrets available as /run/secrets/my-secret
}
```

**Pros**: Declarative, integrated with Nix
**Cons**: Nix-specific, steeper learning curve

### Option 5: 1Password CLI

If using 1Password:

```bash
# .envrc
eval "$(op inject -i secrets.env)"
```

**Pros**: UI integration, biometric auth
**Cons**: Proprietary, requires subscription

## Threat Model Considerations

### What Projdb Protects Against:
- ✅ Secrets committed to Git
- ✅ Secrets in plain text on disk
- ✅ Unauthorized access (with proper key management)
- ✅ Accidental exposure via text editor

### What Projdb Does NOT Protect Against:
- ❌ Compromised SOPS_AGE_KEY_FILE
- ❌ Process memory dumps
- ❌ Malicious child processes reading environment
- ❌ Terminal history (if secrets echoed)
- ❌ Core dumps or crash logs

## Best Practices Summary

1. **Keep age keys secure**: 400 permissions, consider hardware keys
2. **Use profiles**: Separate dev/staging/prod secrets
3. **Monitor audit logs**: Regular review of access patterns
4. **Rotate secrets**: Implement regular rotation schedule
5. **Principle of least privilege**: Only load secrets needed for current task
6. **Limit secret lifetime**: Load secrets only when needed, not permanently in shell
7. **Secure exported files**: If exporting to .env files, ensure 600 permissions

## Code Improvements for Projdb

Consider these enhancements to the templedb codebase:

1. **Validate .envrc permissions** before generating output
2. **Add secret age warnings** (warn if >90 days old)
3. **Support hardware security keys** (YubiKey, etc.)
4. **Add `--dry-run` mode** to preview what will be loaded
5. **Implement secret checksums** to detect tampering
6. **Add rate limiting** on secret access to detect abuse
