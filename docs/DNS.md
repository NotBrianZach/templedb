# DNS Management

Automated DNS via Cloudflare, Namecheap, Route53 APIs. No manual configuration panels.

## Quick Reference

```bash
# Setup provider
templedb domain provider add cloudflare

# Register domain
templedb domain register myapp example.com --registrar cloudflare

# Add deployment target
templedb target add myapp production --provider supabase --host db.example.com

# Configure DNS
templedb domain dns configure myapp example.com --target production
templedb domain dns apply myapp example.com --target production

# Deploy
templedb deploy run myapp --target production
```

## Workflow

1. **Register domain** → `domain register`
2. **Add target** → `target add`
3. **Configure DNS** → `domain dns configure` (generates records, doesn't apply)
4. **Review** → Check generated records in database
5. **Apply** → `domain dns apply` (sends to provider API)
6. **Deploy** → `deploy run` (uses DNS + secrets)

## Provider Setup

### Cloudflare

```bash
templedb domain provider add cloudflare
# Prompts for: API token (recommended) or Global API Key + Email
```

**Get API token:**
1. Login to Cloudflare dashboard
2. My Profile → API Tokens → Create Token
3. Use "Edit zone DNS" template
4. Zone Resources: Include → All zones (or specific zone)
5. Copy token

### Namecheap

```bash
templedb domain provider add namecheap
# Prompts for: API username, API key, Client IP (whitelisted)
```

**Enable API:**
1. Account → Profile → Tools → Namecheap API Access
2. Enable API access
3. Whitelist your server IP
4. Generate API key

### AWS Route53

```bash
templedb domain provider add route53
# Prompts for: AWS Access Key ID, AWS Secret Access Key, Region
```

**Create IAM user:**
```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "route53:ChangeResourceRecordSets",
      "route53:ListResourceRecordSets",
      "route53:GetHostedZone",
      "route53:ListHostedZones"
    ],
    "Resource": "*"
  }]
}
```

## DNS Records

TempleDB auto-generates these records:

**For Supabase projects:**
```
A     example.com              → <supabase-ip>
CNAME www.example.com          → example.com
CNAME api.example.com          → <project-ref>.supabase.co
```

**Custom records:**
```sql
INSERT INTO dns_records (domain_id, record_type, name, value, ttl)
VALUES (1, 'CNAME', 'cdn', 'cdn.cloudflare.net', 3600);
```

Then run `domain dns apply` to push to provider.

## Commands

```bash
# Providers
templedb domain provider list
templedb domain provider add <provider>
templedb domain provider remove <provider>

# Domains
templedb domain register <project> <domain> --registrar <name>
templedb domain list [--project <project>]
templedb domain show <domain>
templedb domain remove <domain>

# DNS Configuration
templedb domain dns configure <project> <domain> --target <target>
templedb domain dns apply <project> <domain> --target <target>
templedb domain dns verify <project> <domain>
templedb domain dns list <project> <domain>

# Query database directly
sqlite3 ~/.local/share/templedb/templedb.sqlite
SELECT * FROM dns_records WHERE domain = 'example.com';
```

## Environment Variables

DNS configuration auto-generates environment variables:

```sql
-- Stored in deployment_env_vars
SELECT key, value FROM deployment_env_vars
WHERE target_id = (SELECT id FROM deployment_targets WHERE name = 'production');
```

**Example variables:**
```
DOMAIN=example.com
API_URL=https://api.example.com
SUPABASE_URL=https://abc123.supabase.co
SUPABASE_ANON_KEY=<key from secrets>
```

Load with: `templedb deploy run myapp --target production`

## Troubleshooting

**"Provider not found"**
```bash
templedb domain provider list
# If missing, add it:
templedb domain provider add cloudflare
```

**"Domain already registered"**
```bash
# Check existing domains
templedb domain list

# Remove if needed
templedb domain remove example.com --force
```

**"DNS apply failed"**
```bash
# Verify provider credentials
templedb domain provider list

# Check DNS records generated
sqlite3 ~/.local/share/templedb/templedb.sqlite
SELECT * FROM dns_records WHERE domain = 'example.com';

# Try manual verification
templedb domain dns verify myapp example.com
```

**"Target not found"**
```bash
# List targets
templedb target list --project myapp

# Add missing target
templedb target add myapp production --provider supabase --host db.example.com
```

## Database Schema

```sql
-- Providers
CREATE TABLE dns_providers (
  id INTEGER PRIMARY KEY,
  name TEXT UNIQUE,              -- cloudflare, namecheap, route53
  api_key_encrypted TEXT,
  credentials_json TEXT
);

-- Domains
CREATE TABLE domains (
  id INTEGER PRIMARY KEY,
  project_id INTEGER,
  domain TEXT UNIQUE,
  registrar TEXT,
  status TEXT
);

-- DNS Records
CREATE TABLE dns_records (
  id INTEGER PRIMARY KEY,
  domain_id INTEGER,
  record_type TEXT,              -- A, AAAA, CNAME, MX, TXT
  name TEXT,
  value TEXT,
  ttl INTEGER,
  applied_at TIMESTAMP
);

-- Check what's configured
SELECT d.domain, r.record_type, r.name, r.value
FROM domains d
JOIN dns_records r ON d.id = r.domain_id
WHERE d.project_id = (SELECT id FROM projects WHERE slug = 'myapp');
```

## Examples

### Complete Setup

```bash
# 1. Add provider
templedb domain provider add cloudflare

# 2. Register domain
templedb domain register myapp example.com --registrar cloudflare

# 3. Add Supabase target
templedb target add myapp production \
  --provider supabase \
  --host db.example.com \
  --project-ref abc123xyz

# 4. Configure DNS (generates records)
templedb domain dns configure myapp example.com --target production

# 5. Review records
sqlite3 ~/.local/share/templedb/templedb.sqlite \
  "SELECT * FROM dns_records WHERE domain = 'example.com'"

# 6. Apply to Cloudflare
templedb domain dns apply myapp example.com --target production

# 7. Verify
templedb domain dns verify myapp example.com

# 8. Deploy
templedb deploy run myapp --target production
```

### Multiple Environments

```bash
# Production
templedb target add myapp production --provider supabase --host prod.db.example.com
templedb domain dns configure myapp example.com --target production

# Staging
templedb target add myapp staging --provider supabase --host staging.db.example.com
templedb domain dns configure myapp staging.example.com --target staging

# Apply both
templedb domain dns apply myapp example.com --target production
templedb domain dns apply myapp staging.example.com --target staging
```

### Custom DNS Records

```bash
# Add custom record via SQL
sqlite3 ~/.local/share/templedb/templedb.sqlite <<SQL
INSERT INTO dns_records (domain_id, record_type, name, value, ttl)
SELECT id, 'CNAME', 'cdn', 'cdn.cloudflare.net', 3600
FROM domains WHERE domain = 'example.com';
SQL

# Apply
templedb domain dns apply myapp example.com --target production
```

## Security

- API keys encrypted with age
- Stored in `dns_providers.api_key_encrypted`
- Decrypted on-demand for API calls
- Never logged or displayed

Check encryption:
```sql
SELECT name, LENGTH(api_key_encrypted) as encrypted_bytes
FROM dns_providers;
```

---

**Next:** [DEPLOYMENT.md](DEPLOYMENT.md) for full deployment automation
