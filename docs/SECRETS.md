# TempleDB Secrets Management

TempleDB stores secrets as **individual encrypted blobs** with full metadata tracking. Each secret (like `OPENROUTER_API_KEY`) is stored separately, encrypted with age/Yubikey, and can be shared between projects.

## Architecture

### Database Schema

```
secret_blobs                    - Individual encrypted secrets
├─ id
├─ secret_name                  - e.g., "OPENROUTER_API_KEY"
├─ secret_blob                  - Encrypted value (age-encrypted)
├─ content_type                 - "application/text", "application/json", etc.
├─ created_at
└─ updated_at

project_secret_blobs            - Many-to-many join table
├─ project_id                   - References projects(id)
├─ secret_blob_id               - References secret_blobs(id)
└─ profile                      - "default", "production", etc.

secret_key_assignments          - Track which keys encrypt each secret
├─ secret_blob_id
├─ key_id                       - References encryption_keys(id)
└─ added_by
```

### Key Features

- **Individual secrets**: Each secret is its own encrypted blob with metadata
- **Granular sharing**: Share specific secrets between projects via join table
- **Multi-key encryption**: Encrypt with multiple Yubikeys/age keys
- **Audit trail**: Track creation, updates, and access per secret
- **Content types**: Support text, JSON, binary, etc.

## Commands

### Set a Secret

```bash
# Basic usage
templedb env secretset <project> <name> <value> --keys <key1,key2>

# Examples
templedb env secretset woofs_projects OPENROUTER_API_KEY "sk-or-..." --keys sops-key
templedb env secretset myapp DATABASE_URL "postgres://..." --keys yubikey-1,sops-key
templedb env secretset myapp API_SECRET "abc123" --keys yubikey-1 --profile production
```

**Options:**
- `--keys`: Comma-separated list of encryption key names (required)
- `--profile`: Secret profile (default: "default")

### Get a Secret

```bash
# Get secret value only
templedb env secretget <project> <name>

# Get secret with metadata
templedb env secretget <project> <name> --metadata

# Examples
templedb env secretget woofs_projects OPENROUTER_API_KEY
# Output: sk-or-...

templedb env secretget woofs_projects OPENROUTER_API_KEY --metadata
# Output:
# Secret: OPENROUTER_API_KEY
# Project: woofs_projects
# Profile: default
# Created: 2026-03-16 16:15:03
# Updated: 2026-03-16 16:15:03
# Content-Type: application/text
#
# Value:
# sk-or-...
```

**Options:**
- `--metadata`: Show creation time, update time, content type, etc.
- `--profile`: Secret profile (default: "default")

### List Secrets

```bash
# List all secrets for a project
templedb env secretlist <project>

# List with decrypted values (use with caution!)
templedb env secretlist <project> --values

# Examples
templedb env secretlist woofs_projects
# Output:
# Secrets for woofs_projects (profile: default):
# ============================================================
#
# DATABASE_URL
#   Created: 2026-03-16 16:15:07
#   Updated: 2026-03-16 16:15:07
#
# OPENROUTER_API_KEY (shared)
#   Created: 2026-03-16 16:15:03
#   Updated: 2026-03-16 16:15:03
```

**Options:**
- `--values`: Decrypt and show values (WARNING: displays secrets in plaintext)
- `--profile`: Secret profile (default: "default")

**Notes:**
- Shared secrets are marked with "(shared)"
- Use `--values` carefully - it decrypts all secrets

### Share a Secret

```bash
# Share a specific secret from one project to another
templedb env secretshare-key <source-project> <target-project> <secret-name>

# Examples
templedb env secretshare-key woofs_projects bza OPENROUTER_API_KEY
# Output:
# ✓ Shared 'OPENROUTER_API_KEY' from woofs_projects to bza
#   Both projects now have access to the same secret

templedb env secretshare-key system_config myapp DATABASE_URL --profile production
```

**How It Works:**
- Creates a join table entry linking the target project to the same secret blob
- Both projects decrypt the **same encrypted blob**
- Updating the secret in one project updates it for all projects
- No re-encryption needed

**Options:**
- `--profile`: Secret profile (default: "default")

### Delete a Secret

```bash
# Delete a secret from a project
templedb env secretdelete <project> <name>

# Examples
templedb env secretdelete woofs_projects OLD_API_KEY
# Output: ✓ Deleted secret 'OLD_API_KEY' from woofs_projects

templedb env secretdelete bza OPENROUTER_API_KEY
# Output:
# ✓ Removed secret 'OPENROUTER_API_KEY' from bza
#   Secret is still shared with 1 other project(s)
```

**Behavior:**
- If secret is **not shared**: Deletes from join table AND deletes the blob
- If secret **is shared**: Only removes from join table, blob remains for other projects
- Safe to delete - won't break other projects

**Options:**
- `--profile`: Secret profile (default: "default")

### Migrate Legacy Secrets

```bash
# Migrate old YAML-based secrets to individual secrets
templedb env secretmigrate <project> --keys <key1,key2>

# Examples
templedb env secretmigrate woofs_projects --keys sops-key
templedb env secretmigrate myapp --keys yubikey-1,sops-key --profile production
```

**What It Does:**
1. Finds YAML blob with `content_type = 'application/x-age+yaml'`
2. Decrypts YAML and extracts `env` section
3. Creates individual secret blobs for each key-value pair
4. Deletes old YAML blob

**Options:**
- `--keys`: Encryption keys for new individual secrets (required)
- `--profile`: Secret profile (default: "default")

## Encryption Keys

Before using secrets, you need encryption keys registered in TempleDB.

### List Available Keys

```bash
templedb env keylist
```

### Add a New Key

```bash
# Add Yubikey
templedb env keyadd my-yubikey --recipient age1yubikey1q...

# Add filesystem age key
templedb env keyadd my-age-key --recipient age1abc... --location ~/.age/key.txt
```

### Use Multiple Keys

```bash
# Encrypt secret with multiple keys (any one can decrypt)
templedb env secretset myapp API_KEY "secret123" --keys yubikey-1,sops-key,age-key
```

## Common Workflows

### Initial Setup

```bash
# 1. Add encryption keys
templedb env keyadd yubikey-1 --recipient age1yubikey1q...
templedb env keyadd sops-key --recipient age1cv5kqala...

# 2. Set secrets
templedb env secretset myapp DATABASE_URL "postgres://..." --keys yubikey-1
templedb env secretset myapp API_KEY "secret123" --keys yubikey-1,sops-key
```

### Sharing Configuration Between Projects

```bash
# Share database credentials from main project to worker project
templedb env secretshare-key myapp myapp-worker DATABASE_URL

# Verify
templedb env secretlist myapp-worker
# DATABASE_URL (shared)

templedb env secretget myapp-worker DATABASE_URL
# postgres://...
```

### Production Secrets

```bash
# Use profiles for different environments
templedb env secretset myapp DATABASE_URL "postgres://dev" --keys yubikey-1
templedb env secretset myapp DATABASE_URL "postgres://prod" --keys yubikey-1 --profile production

# Get production secret
templedb env secretget myapp DATABASE_URL --profile production
```

### Secret Rotation

```bash
# Update secret (all projects sharing it will see the new value)
templedb env secretset myapp API_KEY "new-key-456" --keys yubikey-1

# Verify it's updated everywhere
templedb env secretget myapp API_KEY
templedb env secretget myapp-worker API_KEY  # If shared
```

### Cleanup

```bash
# Remove secret from one project
templedb env secretdelete myapp-worker API_KEY

# Delete secret entirely
templedb env secretdelete myapp API_KEY
```

## Integration with Deployment

Secrets can be exported for deployment:

```bash
# Export as shell environment variables
templedb env secretexport myapp --format shell > env.sh
source env.sh

# Export as .env file
templedb env secretexport myapp --format dotenv > .env

# Export as YAML
templedb env secretexport myapp --format yaml > secrets.yaml

# Export as JSON
templedb env secretexport myapp --format json > secrets.json
```

## Security Considerations

### Encryption

- All secrets encrypted with [age](https://github.com/FiloSottile/age)
- Support for hardware security keys (Yubikey via age-plugin-yubikey)
- Multi-key encryption: any-of-N decryption (any key can decrypt)
- Secrets never stored in plaintext in database

### Access Control

- Decryption requires access to private key (age key file or Yubikey)
- Yubikey requires physical device + PIN
- Audit log tracks all secret operations (set, get, delete, share)

### Key Management

- Register keys in `encryption_keys` table
- Track which keys protect each secret via `secret_key_assignments`
- Support for key revocation (mark keys as inactive)
- Can add/remove keys from existing secrets (re-encryption)

### Best Practices

1. **Use Yubikeys for production secrets**
   ```bash
   templedb env secretset myapp PROD_API_KEY "..." --keys yubikey-1,yubikey-2
   ```

2. **Don't share secrets unnecessarily**
   - Only share when truly needed between projects
   - Consider using separate secrets instead

3. **Use profiles for different environments**
   ```bash
   --profile default    # Development
   --profile staging
   --profile production
   ```

4. **Rotate secrets regularly**
   ```bash
   # Update existing secret (preserves sharing)
   templedb env secretset myapp API_KEY "new-value" --keys yubikey-1
   ```

5. **Audit secret access**
   ```sql
   SELECT * FROM audit_log WHERE action LIKE '%secret%' ORDER BY ts DESC;
   ```

## Querying Secrets (SQL)

### Find All Secrets for a Project

```sql
SELECT sb.secret_name, sb.updated_at
FROM project_secret_blobs psb
JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
WHERE psb.project_id = (SELECT id FROM projects WHERE slug = 'myapp');
```

### Find Which Projects Share a Secret

```sql
SELECT p.slug, p.name
FROM project_secret_blobs psb
JOIN projects p ON psb.project_id = p.id
WHERE psb.secret_blob_id = (
  SELECT sb.id FROM secret_blobs sb WHERE sb.secret_name = 'OPENROUTER_API_KEY'
);
```

### Check if Secret is Shared

```sql
SELECT COUNT(DISTINCT psb.project_id) as project_count
FROM project_secret_blobs psb
JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
WHERE sb.secret_name = 'API_KEY';
```

### List Secrets with Encryption Keys

```sql
SELECT
  sb.secret_name,
  p.slug as project,
  GROUP_CONCAT(ek.key_name) as keys
FROM secret_blobs sb
JOIN project_secret_blobs psb ON sb.id = psb.secret_blob_id
JOIN projects p ON psb.project_id = p.id
LEFT JOIN secret_key_assignments ska ON sb.id = ska.secret_blob_id
LEFT JOIN encryption_keys ek ON ska.key_id = ek.id
GROUP BY sb.id, p.slug;
```

## Troubleshooting

### "No age key files found"

**Problem:** Can't decrypt secrets.

**Solution:**
```bash
# Check key files exist
ls -la ~/.config/sops/age/keys.txt
ls -la ~/.age/key.txt
ls -la ~/.config/age-plugin-yubikey/identities.txt

# Or set environment variable
export TEMPLEDB_AGE_KEY_FILE=/path/to/key.txt
```

### "age decryption failed"

**Problem:** None of your keys can decrypt this secret.

**Possible causes:**
1. Secret was encrypted with different keys
2. Yubikey not inserted or wrong PIN
3. Key file doesn't match

**Solution:**
```bash
# Check which keys protect this secret
templedb env secretshow-keys myapp

# Add your key to the secret (requires existing key access)
templedb env secretadd-key myapp --key my-yubikey
```

### "Key not found"

**Problem:** Specified key doesn't exist in encryption_keys table.

**Solution:**
```bash
# List available keys
templedb env keylist

# Add the key
templedb env keyadd my-key --recipient age1...
```

### Secret Already Shared

**Problem:** `templedb env secretshare-key` says "already shared".

**Solution:** This is informational - the secret is already accessible to the target project. No action needed.

## Migration from YAML Secrets

If you have old YAML-based secrets (from before this system), migrate them:

```bash
# Find projects with old YAML secrets
sqlite3 ~/.local/share/templedb/templedb.db \
  "SELECT p.slug FROM projects p
   JOIN project_secret_blobs psb ON p.id = psb.project_id
   JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
   WHERE sb.content_type = 'application/x-age+yaml';"

# Migrate each project
templedb env secretmigrate myapp --keys sops-key
templedb env secretmigrate otherapp --keys yubikey-1,sops-key
```

The migration:
1. Decrypts the YAML blob
2. Extracts all key-value pairs from `env:` section
3. Creates individual secrets
4. Deletes the old YAML blob

## API / MCP Integration

TempleDB secrets are exposed via MCP (Model Context Protocol):

```python
# Get secret
mcp__templedb__templedb_secret_get(project="myapp", name="API_KEY")

# List secrets
mcp__templedb__templedb_secret_list(project="myapp")

# Set secret
mcp__templedb__templedb_secret_set(
    project="myapp",
    name="NEW_KEY",
    value="secret123",
    keys=["yubikey-1"]
)
```

See `src/cli/commands/mcp.py` for full API.

## See Also

- [Multi-Yubikey Setup](MULTI_YUBIKEY_SETUP.md) - Configure multiple Yubikeys
- [Key Revocation Guide](KEY_REVOCATION_GUIDE.md) - Revoke compromised keys
- [Security Threat Model](SECURITY_THREAT_MODEL.md) - Security architecture
- [Deployment](DEPLOYMENT.md) - Using secrets in deployments


<!-- AUTO-GENERATED-INDEX:START -->
## Related Documentation

### Other

- **[Backup & Restore](../docs/BACKUP.md)**
- **[Database Types Gap Analysis](../docs/implementation/DATABASE_TYPES_GAP_ANALYSIS.md)**
- **[TempleDB TUI - Nix Package](../docs/implementation/TUI_NIX_PACKAGE.md)**
- **[Vibe Coding Quiz System](../docs/VIBE_CODING.md)**

### Api

- **[TempleDB MCP Tools - Quick Reference](../docs/MCP_QUICK_REFERENCE.md)**

### Architecture

- **[CathedralDB Design Document](../docs/advanced/CATHEDRAL.md)**

### Deployment

- **[TempleDB Deployment Architecture Review (v2)](../docs/DEPLOYMENT_ARCHITECTURE_V2.md)**

### Setup

- **[Schema Consolidation Summary](../docs/fixes/SCHEMA_CONSOLIDATION.md)**

<!-- AUTO-GENERATED-INDEX:END -->
