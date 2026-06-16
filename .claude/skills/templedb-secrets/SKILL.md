---
name: templedb-secrets
description: |
  Manage secrets, environment variables, and hardware security keys in TempleDB.
  Use for: secrets management, environment variables, missing var prompts, Yubikey/FIDO2 integration, SOPS/age encryption.
  Activate when user mentions: secrets, environment variables, keys, encryption, Yubikey, FIDO, credentials, passwords, tokens, API keys.
allowed-tools:
  - Bash(templedb secret:*)
  - Bash(./templedb secret:*)
  - Bash(templedb env:*)
  - Bash(./templedb env:*)
  - Bash(sqlite3:*)
  - Bash(age-keygen:*)
  - Bash(age:*)
  - Bash(ykman:*)
argument-hint: "[init|edit|export|add|prompt] [options]"
---

# TempleDB Secrets & Environment Management

You are a TempleDB secrets management assistant. Help users manage secrets, environment variables, and hardware security keys securely.

## Core Philosophy

TempleDB uses:
- **SOPS + age encryption** for secrets at rest
- **Database storage** for normalized secret management
- **Hardware key support** for Yubikeys/FIDO2 devices
- **Interactive prompting** for missing environment variables
- **Audit logging** for all secret access

---

## Table of Contents

1. [Secrets Management](#secrets-management)
2. [Environment Variables](#environment-variables)
3. [Interactive Prompting](#interactive-prompting-missing-variables)
4. [Hardware Key Support](#hardware-key-support-yubikeyfido2)
5. [Security Best Practices](#security-best-practices)
6. [Workflows](#common-workflows)

---

## Secrets Management

### Architecture

```
User → age/SOPS encryption → SQLite (secret_blobs table) → Decryption on use
                                ↓
                           Audit log (all access tracked)
```

**Key components:**
- `secret_blobs` table: Encrypted secrets stored as BLOBs
- `environment_variables` table: Variables with `is_secret` flag
- SOPS: Encryption tool
- age: Modern encryption format
- Audit log: Track all secret operations

### 1. Initialize Secrets for Project

```bash
# Generate age key pair (one-time setup)
age-keygen -o ~/.config/sops/age/keys.txt
chmod 400 ~/.config/sops/age/keys.txt

# Get your public key (age recipient)
cat ~/.config/sops/age/keys.txt | grep "# public key:" | cut -d: -f2 | xargs

# Initialize secrets for project
templedb secret init my-project \
  --profile production \
  --age-recipient age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**What this does:**
- Creates encrypted secret blob in database
- Uses age encryption with your public key
- Stores in `secret_blobs` table
- Logs to audit trail

### 2. Edit Secrets

```bash
# Edit secrets in $EDITOR (vim, nano, etc.)
templedb secret edit my-project --profile production
```

**Workflow:**
1. Decrypts blob from database
2. Opens in $EDITOR as YAML:
   ```yaml
   env:
     DATABASE_URL: postgresql://user:pass@localhost/db
     API_KEY: sk-1234567890abcdef
     JWT_SECRET: super-secret-key-here
   meta:
     last_rotated: 2026-02-23
     owner: ops-team
   ```
3. On save: re-encrypts and stores back
4. Logs edit to audit trail

### 3. Export Secrets

```bash
# Export as shell variables
templedb secret export my-project --profile production --format shell
# Output:
# export DATABASE_URL=postgresql://...
# export API_KEY=sk-1234567890abcdef
# export JWT_SECRET=super-secret-key-here

# Export as JSON
templedb secret export my-project --profile production --format json

# Export as .env format
templedb secret export my-project --profile production --format dotenv

# Export as YAML
templedb secret export my-project --profile production --format yaml
```

**Use cases:**
- Load secrets into shell: `eval "$(templedb secret export my-project --format shell)"`
- CI/CD integration: Export as dotenv
- Backup/sharing: Export as YAML (still encrypted in DB)

### 4. View Encrypted Blob

```bash
# View raw SOPS-encrypted YAML (for debugging)
templedb secret print-sops my-project --profile production
```

---

## Environment Variables

TempleDB has a sophisticated environment variable system with scoping and types.

### Variable Scopes

```sql
-- Three scope types:
-- 1. global: Available everywhere
-- 2. project: Scoped to specific project
-- 3. nix_env: Scoped to specific Nix environment
```

### Variable Types

1. **static**: Simple key-value
2. **compound**: Template with substitution (e.g., `${DATABASE_URL}/api`)
3. **secret_ref**: Reference to secret in secret_blobs

### Add Environment Variable

```bash
# Add static variable
templedb env add DATABASE_URL "postgresql://localhost:5432/mydb" \
  --description "Main database connection"

# Add secret variable (marks as secret)
templedb env add API_KEY "sk-secret-key" \
  --description "OpenAI API key" \
  --secret

# Add compound variable (template)
templedb compound add my-project \
  API_ENDPOINT \
  "https://${DOMAIN}/api/v1" \
  --description "Full API endpoint URL"
```

### List Variables

```bash
# List all variables
templedb env ls

# List for specific environment
templedb env ls --environment production

# List as JSON
templedb env ls --json
```

### Query Variables with SQL

```bash
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT
    scope_type,
    var_name,
    CASE
      WHEN is_secret = 1 THEN '[REDACTED]'
      ELSE var_value
    END as value,
    description
  FROM environment_variables
  WHERE scope_type = 'project'
  ORDER BY var_name
"
```

---

## Interactive Prompting (Missing Variables)

When a project requires environment variables that aren't set, TempleDB can prompt for them.

### 1. Define Required Variables

```sql
-- Add required variables to deployment_configs table
INSERT INTO deployment_configs (
  project_id,
  env_vars_required
) VALUES (
  (SELECT id FROM projects WHERE slug = 'my-project'),
  '["DATABASE_URL", "API_KEY", "JWT_SECRET"]'
);
```

### 2. Check for Missing Variables

```bash
# Check what's missing
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT
    dc.env_vars_required,
    (
      SELECT GROUP_CONCAT(var_name)
      FROM environment_variables ev
      WHERE ev.scope_type = 'project'
      AND ev.scope_id = p.id
    ) as existing_vars
  FROM deployment_configs dc
  JOIN projects p ON dc.project_id = p.id
  WHERE p.slug = 'my-project'
"
```

### 3. Interactive Prompt Script

Create a helper script to prompt for missing variables:

```bash
#!/bin/bash
# File: prompt_missing_vars.sh

PROJECT="$1"
PROFILE="${2:-production}"

# Get required variables
REQUIRED=$(sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT env_vars_required FROM deployment_configs
   WHERE project_id = (SELECT id FROM projects WHERE slug = '$PROJECT')" | \
  jq -r '.[]')

# Get existing variables
EXISTING=$(sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT var_name FROM environment_variables
   WHERE scope_type = 'project'
   AND scope_id = (SELECT id FROM projects WHERE slug = '$PROJECT')" | \
  tr '\n' ' ')

echo "🔐 Checking required environment variables for $PROJECT..."
echo ""

for var in $REQUIRED; do
  if ! echo "$EXISTING" | grep -q "$var"; then
    echo "❌ Missing: $var"
    read -p "Enter value for $var: " -s value
    echo ""

    # Prompt if it's a secret
    read -p "Is this a secret? (y/N): " is_secret

    if [[ "$is_secret" =~ ^[Yy]$ ]]; then
      # Add to encrypted secrets
      echo "Adding to encrypted secrets..."
      # TODO: Implement adding to secret blob
      templedb secret edit "$PROJECT" --profile "$PROFILE"
    else
      # Add as regular env var
      templedb env add "$var" "$value" \
        --description "Interactively added on $(date)"
    fi

    echo "✅ Added: $var"
    echo ""
  else
    echo "✅ Already set: $var"
  fi
done

echo "✅ All required variables configured!"
```

### 4. Integration with Nix Environments

When entering a Nix environment, check for missing vars:

```bash
#!/bin/bash
# In your environment enter script

PROJECT="my-project"
ENV="production"

# Check for missing variables
missing=$(./prompt_missing_vars.sh "$PROJECT" "$ENV" --check-only)

if [ -n "$missing" ]; then
  echo "⚠️  Missing required environment variables:"
  echo "$missing"
  read -p "Would you like to set them now? (Y/n): " response

  if [[ ! "$response" =~ ^[Nn]$ ]]; then
    ./prompt_missing_vars.sh "$PROJECT" "$ENV"
  fi
fi

# Continue with environment entry
templedb env enter "$PROJECT" "$ENV"
```

---

## Hardware Key Support (Yubikey/FIDO2)

TempleDB can integrate with hardware security keys for enhanced security.

### Use Cases

1. **Encrypt age keys** with Yubikey PIN
2. **Sign deployments** with FIDO2 attestation
3. **Decrypt secrets** requiring physical key presence
4. **Audit trail** with hardware key serial numbers

### 1. Setup Yubikey for age Encryption

#### Option A: age-plugin-yubikey

```bash
# Install age-plugin-yubikey
# https://github.com/str4d/age-plugin-yubikey

# Generate age identity on Yubikey
age-plugin-yubikey --generate

# Output:
# Generated age identity: age1yubikey1q2w3e4r5t6y7u8i9o0p...
# Recipient: age1yubikey1q2w3e4r5t6y7u8i9o0p...

# Initialize secrets with Yubikey recipient
templedb secret init my-project \
  --profile production \
  --age-recipient age1yubikey1q2w3e4r5t6y7u8i9o0p...
```

**Benefits:**
- Secrets can only be decrypted with physical Yubikey present
- PIN required for each decryption
- Key never leaves hardware device

#### Option B: age + GPG + Yubikey

```bash
# Use GPG key stored on Yubikey
# Generate GPG key on Yubikey (one-time)
ykman openpgp keys generate

# Get GPG key ID
gpg --list-keys

# Use with SOPS
export SOPS_PGP_FP="YOUR_GPG_FINGERPRINT"
# SOPS will use Yubikey for decryption
```

### 2. Yubikey PIN Prompting

When secrets require Yubikey decryption:

```bash
# User runs:
templedb secret export my-project --profile production

# System prompts:
# 🔑 Yubikey required for decryption
# 📍 Please insert Yubikey and touch to confirm
# [User touches Yubikey]
# 🔓 Decrypted successfully
```

### 3. FIDO2 Attestation for Deployments

Use FIDO2 to attest deployments were authorized:

```bash
# Deploy with FIDO2 attestation
templedb deploy my-project production \
  --require-fido2 \
  --fido2-rp "templedb.local"

# Workflow:
# 1. Prompts for Yubikey touch
# 2. Generates FIDO2 assertion
# 3. Stores attestation in deployment_logs table
# 4. Deploys project
```

### 4. Hardware Key Audit Trail

Track hardware key usage:

```sql
-- Add hardware_key_serial to audit_log
ALTER TABLE audit_log ADD COLUMN hardware_key_serial TEXT;

-- Query hardware key usage
SELECT
  ts,
  action,
  project_slug,
  hardware_key_serial
FROM audit_log
WHERE action IN ('decrypt-secret', 'deploy', 'sign')
  AND hardware_key_serial IS NOT NULL
ORDER BY ts DESC;
```

### 5. Multiple Hardware Keys (Team Setup)

```bash
# Generate multiple age recipients (one per team member's Yubikey)
age-plugin-yubikey --generate  # Alice's key: age1yubikey1aaaa...
age-plugin-yubikey --generate  # Bob's key:   age1yubikey1bbbb...
age-plugin-yubikey --generate  # Carol's key: age1yubikey1cccc...

# Initialize with multiple recipients
templedb secret init my-project \
  --profile production \
  --age-recipient age1yubikey1aaaa... \
  --age-recipient age1yubikey1bbbb... \
  --age-recipient age1yubikey1cccc...

# Any of the three team members can decrypt with their Yubikey
```

### 6. Yubikey Management Commands

```bash
# List Yubikeys
ykman list

# Get Yubikey info
ykman info

# Set PIN
ykman openpgp access set-retries 3 3 3

# Require touch for operations
ykman openpgp set-touch sig on
ykman openpgp set-touch dec on

# Reset Yubikey (DESTRUCTIVE)
ykman openpgp reset
```

---

## Security Best Practices

### 1. Key Management

```bash
# ✅ GOOD: Secure age key permissions
chmod 400 ~/.config/sops/age/keys.txt

# ✅ GOOD: Use hardware key for production
age-plugin-yubikey --generate

# ✅ GOOD: Backup age key (encrypted)
age -p -o ~/.config/sops/age/keys.txt.age ~/.config/sops/age/keys.txt

# ❌ BAD: World-readable key
chmod 644 ~/.config/sops/age/keys.txt  # NEVER DO THIS
```

### 2. Secret Rotation

```bash
# Regular rotation schedule
# Edit secrets and add rotation date
templedb secret edit my-project --profile production

# In YAML, add:
# meta:
#   last_rotated: 2026-02-23
#   rotation_schedule: 90_days

# Check for stale secrets
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT
    secret_name,
    updated_at,
    julianday('now') - julianday(updated_at) as days_since_update
  FROM secret_blobs
  WHERE julianday('now') - julianday(updated_at) > 90
"
```

### 3. Principle of Least Privilege

```bash
# Use profiles to separate secret access
templedb secret init my-project --profile dev      # Development secrets
templedb secret init my-project --profile staging  # Staging secrets
templedb secret init my-project --profile prod     # Production secrets

# Only load what's needed
templedb secret export my-project --profile dev     # NOT prod!
```

### 4. Audit Logging

```bash
# Review audit log regularly
sqlite3 ~/.local/share/templedb/templedb.sqlite "
  SELECT
    ts,
    actor,
    action,
    project_slug,
    profile
  FROM audit_log
  WHERE action LIKE '%secret%'
  ORDER BY ts DESC
  LIMIT 20
"

# Alert on suspicious access
# (e.g., prod secrets accessed outside business hours)
```

### 5. Environment Isolation

```bash
# ✅ GOOD: Different age keys per environment
age-keygen -o ~/.config/sops/age/keys-dev.txt
age-keygen -o ~/.config/sops/age/keys-prod.txt

# Use SOPS_AGE_KEY_FILE to specify key
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys-prod.txt
templedb secret export my-project --profile prod
```

---

## Common Workflows

### Workflow 1: New Project Setup

```bash
# 1. Generate age key (if not exists)
if [ ! -f ~/.config/sops/age/keys.txt ]; then
  mkdir -p ~/.config/sops/age
  age-keygen -o ~/.config/sops/age/keys.txt
  chmod 400 ~/.config/sops/age/keys.txt
fi

# 2. Get public key
PUB_KEY=$(grep "public key:" ~/.config/sops/age/keys.txt | cut -d: -f2 | xargs)

# 3. Initialize secrets
templedb secret init my-project --profile production --age-recipient "$PUB_KEY"

# 4. Edit and add secrets
templedb secret edit my-project --profile production

# 5. Verify
templedb secret export my-project --profile production --format yaml
```

### Workflow 2: Team Onboarding

```bash
# New team member:
# 1. Generate their age key
age-keygen -o ~/.config/sops/age/keys.txt
NEW_MEMBER_KEY=$(grep "public key:" ~/.config/sops/age/keys.txt | cut -d: -f2 | xargs)

# 2. Add their key as recipient
# (Re-encrypt secrets with additional recipient)
templedb secret export my-project --profile prod --format yaml > /tmp/secrets.yaml
sops --add-age "$NEW_MEMBER_KEY" /tmp/secrets.yaml
templedb secret init my-project --profile prod --age-recipient "$NEW_MEMBER_KEY"

# 3. They can now decrypt
templedb secret export my-project --profile prod
```

### Workflow 3: Yubikey-Protected Production

```bash
# 1. Setup Yubikey with age
age-plugin-yubikey --generate
YUBIKEY_RECIPIENT=$(age-plugin-yubikey --list | grep "Recipient:" | awk '{print $2}')

# 2. Initialize production secrets with Yubikey
templedb secret init my-project --profile prod --age-recipient "$YUBIKEY_RECIPIENT"

# 3. Edit secrets (will require Yubikey touch)
templedb secret edit my-project --profile prod

# 4. Deploy (requires physical Yubikey)
templedb deploy my-project prod --require-hardware-key
```

### Workflow 4: CI/CD Integration

```bash
# In CI environment:
# 1. Store age key as CI secret (e.g., GitHub Actions secret)
# 2. In CI script:

echo "$SOPS_AGE_KEY" > /tmp/age-key.txt
chmod 400 /tmp/age-key.txt
export SOPS_AGE_KEY_FILE=/tmp/age-key.txt

# 3. Export secrets for deployment
templedb secret export my-project --profile prod --format dotenv > .env

# 4. Deploy application
./deploy.sh

# 5. Clean up
rm /tmp/age-key.txt .env
```

### Workflow 5: Interactive Variable Prompting

```bash
# User runs deployment
./deploy.sh my-project production

# Script checks for missing vars
missing_vars=$(check_missing_vars my-project production)

if [ -n "$missing_vars" ]; then
  echo "⚠️  Missing required variables: $missing_vars"

  for var in $missing_vars; do
    read -p "Enter $var: " -s value
    echo ""

    # Determine if secret
    read -p "Is $var a secret? (y/N): " is_secret

    if [[ "$is_secret" =~ ^[Yy]$ ]]; then
      # Add to encrypted secrets
      add_to_secret_blob my-project production "$var" "$value"
    else
      # Add as env var
      templedb env add "$var" "$value" --description "Deployment variable"
    fi
  done
fi

# Continue with deployment
echo "✅ All variables configured, deploying..."
```

---

## Database Schema Reference

### Tables

```sql
-- Encrypted secrets
CREATE TABLE secret_blobs (
  id INTEGER PRIMARY KEY,
  project_id INTEGER NOT NULL,
  profile TEXT NOT NULL DEFAULT 'default',
  secret_name TEXT NOT NULL,
  secret_blob BLOB NOT NULL,  -- SOPS-encrypted YAML
  content_type TEXT NOT NULL DEFAULT 'application/text',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(project_id, profile)
);

-- Environment variables
CREATE TABLE environment_variables (
  id INTEGER PRIMARY KEY,
  scope_type TEXT NOT NULL CHECK(scope_type IN ('global', 'project', 'nix_env')),
  scope_id INTEGER,
  var_name TEXT NOT NULL,
  var_value TEXT,
  value_type TEXT DEFAULT 'static' CHECK(value_type IN ('static', 'compound', 'secret_ref')),
  template TEXT,
  is_secret BOOLEAN DEFAULT 0,
  is_exported BOOLEAN DEFAULT 1,
  description TEXT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  UNIQUE(scope_type, scope_id, var_name)
);

-- Audit logging
CREATE TABLE audit_log (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,
  actor TEXT,
  action TEXT NOT NULL,
  project_slug TEXT,
  profile TEXT,
  details TEXT,  -- JSON
  hardware_key_serial TEXT  -- For Yubikey tracking
);
```

### Useful Queries

```sql
-- List all secrets (encrypted, can't see content)
SELECT project_id, profile, secret_name, updated_at
FROM secret_blobs;

-- List environment variables (non-secret)
SELECT var_name, var_value, description
FROM environment_variables
WHERE is_secret = 0;

-- Audit trail for specific project
SELECT ts, action, profile
FROM audit_log
WHERE project_slug = 'my-project'
  AND action LIKE '%secret%'
ORDER BY ts DESC;
```

---

## Quick Reference

### Essential Commands

```bash
# Secrets
templedb secret init <project> --age-recipient <key>
templedb secret edit <project> --profile <profile>
templedb secret export <project> --format [shell|json|yaml|dotenv]

# Environment Variables
templedb env add <key> <value> [--secret]
templedb env ls [--environment <env>]
templedb env show <key>

# Compound Variables
templedb compound add <project> <key> <template>

# Yubikey Setup
age-plugin-yubikey --generate
ykman openpgp keys generate

# Audit
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM audit_log WHERE action LIKE '%secret%'"
```

### Environment Variables

```bash
SOPS_AGE_KEY_FILE     # Path to age private key
SOPS_AGE_RECIPIENT    # Age public key for encryption
EDITOR                # Editor for secret editing
```

---

## Integration with Other Skills

- **templedb-projects**: Secrets scoped per project
- **templedb-environments**: Secrets loaded into Nix envs
- **templedb-deploy**: Secrets injected during deployment
- **templedb-vcs**: Secrets never committed to VCS
- **templedb-cathedral**: Secrets excluded from exports

---

## Troubleshooting

### Error: "SOPS_AGE_KEY_FILE not set"

```bash
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt
```

### Error: "Yubikey not found"

```bash
# Check Yubikey is connected
ykman list

# Check age-plugin-yubikey is installed
which age-plugin-yubikey
```

### Error: "Permission denied on age key"

```bash
chmod 400 ~/.config/sops/age/keys.txt
```

### Secrets not loading in environment

```bash
# Check environment variables are exported
templedb env ls --json | jq -r '.[] | select(.is_exported == false)'

# Set is_exported = 1
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "UPDATE environment_variables SET is_exported = 1 WHERE var_name = 'MY_VAR'"
```

---

**TempleDB Secrets - Encrypted, audited, hardware-key protected secret management**
