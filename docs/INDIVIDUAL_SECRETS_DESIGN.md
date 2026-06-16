# Individual Secrets Architecture Design

## Current Problem

Currently, TempleDB stores all secrets for a project in a single encrypted YAML blob:
```yaml
env:
  OPENROUTER_API_KEY: sk-xxx
  DATABASE_URL: postgres://...
  API_SECRET: abc123
```

This makes it impossible to:
- Share individual secrets between projects
- Query/list secrets efficiently
- Have proper metadata per secret
- Manage secret lifecycle independently

## Proposed Solution

Store each secret as an individual encrypted blob in the database.

### Schema (Already Supported!)

The existing schema already supports this:

```sql
-- Each row = one secret
CREATE TABLE secret_blobs (
  id INTEGER PRIMARY KEY,
  profile TEXT NOT NULL DEFAULT 'default',
  secret_name TEXT NOT NULL,              -- e.g., 'OPENROUTER_API_KEY'
  secret_blob BLOB NOT NULL,              -- encrypted value
  content_type TEXT NOT NULL DEFAULT 'application/text',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Many-to-many: projects can share secrets
CREATE TABLE project_secret_blobs (
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  secret_blob_id INTEGER NOT NULL REFERENCES secret_blobs(id) ON DELETE CASCADE,
  profile TEXT NOT NULL DEFAULT 'default',
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  PRIMARY KEY (project_id, secret_blob_id, profile)
);

-- Track which encryption keys protect each secret
CREATE TABLE secret_key_assignments (
  secret_blob_id INTEGER NOT NULL REFERENCES secret_blobs(id) ON DELETE CASCADE,
  key_id INTEGER NOT NULL REFERENCES encryption_keys(id) ON DELETE CASCADE,
  added_at TEXT NOT NULL DEFAULT (datetime('now')),
  added_by TEXT,
  PRIMARY KEY (secret_blob_id, key_id)
);
```

### New Commands

#### Basic Operations

```bash
# Set an individual secret
templedb secret set <project> <key> <value> [--keys key1,key2]

# Get an individual secret
templedb secret get <project> <key>

# List all secrets for a project
templedb secret list <project>

# Delete a secret from a project
templedb secret delete <project> <key>
```

#### Sharing Secrets

```bash
# Share a specific secret from one project to another
templedb secret share-key <source-project> <target-project> <key>

# Example:
templedb secret share-key woofs_projects bza OPENROUTER_API_KEY
```

#### Bulk Import/Export

```bash
# Import from .env file or YAML
templedb secret import <project> --from-file secrets.env

# Export to various formats
templedb secret export <project> --format dotenv
templedb secret export <project> --format yaml
templedb secret export <project> --format json
templedb secret export <project> --format shell
```

### Migration Strategy

**Phase 1: Add new commands alongside old ones**
- Keep `secret init`, `secret edit` for YAML-based secrets
- Add `secret set`, `secret get`, `secret list` for individual secrets
- Both approaches work simultaneously

**Phase 2: Migration command**
```bash
# Convert YAML blob to individual secrets
templedb secret migrate-to-individual <project>
```

**Phase 3: Deprecate YAML-based commands**
- Mark old commands as deprecated
- Eventually remove them

### Implementation Plan

1. **Add new secret commands** (`src/cli/commands/secret.py`):
   - `secret_set()` - Store individual secret
   - `secret_get()` - Retrieve individual secret
   - `secret_list()` - List all secrets for project
   - `secret_delete()` - Remove secret from project
   - `secret_share_key()` - Share individual secret between projects

2. **Update MCP integration** (`src/cli/commands/mcp.py`):
   - Add MCP tools for individual secret operations
   - Keep backward compatibility with existing tools

3. **Add migration utility**:
   - Convert existing YAML blobs to individual secrets
   - Preserve encryption keys and metadata

4. **Update documentation**:
   - Document new commands
   - Provide migration guide
   - Update examples

### Example Usage

```bash
# Initialize encryption keys (one-time setup)
templedb key add my-yubikey --recipient age1yubikey1...

# Set individual secrets
templedb secret set woofs_projects OPENROUTER_API_KEY "sk-or-..." --keys my-yubikey
templedb secret set woofs_projects DATABASE_URL "postgres://..." --keys my-yubikey

# Share a specific secret with another project
templedb secret share-key woofs_projects bza OPENROUTER_API_KEY

# List secrets (shows which are shared)
templedb secret list bza
# Output:
# OPENROUTER_API_KEY (shared from woofs_projects)

# Get a secret value
templedb secret get bza OPENROUTER_API_KEY
# Output: sk-or-...

# Export all secrets for deployment
templedb secret export bza --format dotenv > .env
```

### Benefits

1. **Granular sharing**: Share individual secrets between projects
2. **Better metadata**: Each secret has its own timestamps, encryption keys
3. **Efficient queries**: List/search secrets without decrypting everything
4. **Simpler UX**: Direct commands instead of editing YAML in $EDITOR
5. **Audit trail**: Track access per secret, not per blob
6. **Future-proof**: Easier to add features like secret rotation, expiry, etc.

### Backward Compatibility

- Existing YAML-based secrets continue to work
- Migration is opt-in
- Both approaches can coexist
- Content type distinguishes them:
  - `application/x-age+yaml` = YAML bundle (old style)
  - `application/text` = individual secret (new style)

### Security Considerations

- Individual secrets encrypted with same age/Yubikey mechanism
- Multi-key encryption supported (re-use existing key assignment system)
- Audit log tracks all secret operations
- Secrets never stored in plaintext in database
- Decryption only happens when explicitly requested

### Database Queries

```sql
-- List all secrets for a project
SELECT sb.secret_name, sb.updated_at, sb.content_type
FROM project_secret_blobs psb
JOIN secret_blobs sb ON psb.secret_blob_id = sb.id
WHERE psb.project_id = ? AND sb.content_type != 'application/x-age+yaml'
ORDER BY sb.secret_name;

-- Find which projects share a secret
SELECT p.name, p.slug
FROM project_secret_blobs psb
JOIN projects p ON psb.project_id = p.id
WHERE psb.secret_blob_id = (
  SELECT sb.id FROM secret_blobs sb
  JOIN project_secret_blobs psb2 ON sb.id = psb2.secret_blob_id
  WHERE psb2.project_id = ? AND sb.secret_name = ?
);

-- Check if a secret is shared vs. owned
SELECT COUNT(DISTINCT psb.project_id) as project_count
FROM project_secret_blobs psb
WHERE psb.secret_blob_id = ?;
```

## Implementation Timeline

- **Day 1**: Implement core commands (set, get, list)
- **Day 2**: Add sharing functionality (share-key)
- **Day 3**: Add import/export from files
- **Day 4**: Implement migration from YAML blobs
- **Day 5**: Update MCP integration and docs

## Next Steps

1. Implement `secret set` command
2. Implement `secret get` command
3. Implement `secret list` command
4. Implement `secret share-key` command
5. Update MCP tools
6. Write documentation and examples
