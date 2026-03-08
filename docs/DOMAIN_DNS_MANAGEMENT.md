# Domain and DNS Management in TempleDB

TempleDB provides integrated domain registration, DNS configuration, and automatic environment variable management for deployment targets.

## Overview

The domain management system allows you to:
- Register and track domains for your projects
- Configure DNS records automatically based on deployment targets
- Auto-generate environment variables (DATABASE_URL, PUBLIC_URL, API_URL, etc.)
- Verify DNS propagation
- Integrate seamlessly with deployment workflows

## Quick Start

### 1. Register a Domain

```bash
# Register a domain for your project
./templedb domain register PROJECT_SLUG example.com --registrar "Namecheap"

# Example
./templedb domain register woofs_projects woofs-demo.com --registrar "Namecheap"
```

### 2. Add a Deployment Target (if not already exists)

```bash
# Add a deployment target with provider information
./templedb target add PROJECT_SLUG TARGET_NAME \
  --type database \
  --provider supabase \
  --host db.example.supabase.co \
  --region us-east-1

# Example for staging
./templedb target add woofs_projects staging \
  --type database \
  --provider supabase \
  --host staging.woofs.com
```

### 3. Configure DNS for the Deployment Target

```bash
# Configure DNS automatically
./templedb domain dns configure PROJECT_SLUG DOMAIN --target TARGET_NAME

# Example
./templedb domain dns configure woofs_projects woofs-demo.com --target staging
```

This command will:
- Create appropriate DNS records (CNAME/A records) based on the provider
- Generate and store environment variables:
  - `DATABASE_URL` - PostgreSQL connection string
  - `PUBLIC_URL` - Public-facing URL (https://staging.example.com)
  - `API_URL` - API endpoint URL
- Update the deployment target with the access URL
- Provide instructions for manual DNS configuration

### 4. Update DNS Records at Your Registrar

Follow the instructions provided by the configure command to manually add DNS records at your domain registrar (e.g., Namecheap, GoDaddy, Cloudflare).

### 5. Verify DNS Propagation

```bash
# Verify DNS records are properly configured
./templedb domain dns verify PROJECT_SLUG DOMAIN

# Example
./templedb domain dns verify woofs_projects woofs-demo.com
```

This will check that your DNS records are live and pointing to the correct destinations.

### 6. Deploy Your Project

```bash
# Deploy with automatically configured environment variables
./templedb deploy run PROJECT_SLUG --target TARGET_NAME

# Example
./templedb deploy run woofs_projects --target staging
```

## Command Reference

### Domain Commands

#### Register a Domain
```bash
./templedb domain register PROJECT_SLUG DOMAIN [--registrar NAME]
```
Registers a domain for tracking in TempleDB.

#### List Domains
```bash
# List domains for a specific project
./templedb domain list PROJECT_SLUG

# List all domains across all projects
./templedb domain list
```

#### Update Domain
```bash
./templedb domain update PROJECT_SLUG DOMAIN \
  [--registrar NAME] \
  [--status pending|active|expired] \
  [--primary]
```
Updates domain configuration. Use `--primary` to set as the primary domain for the project.

#### Remove Domain
```bash
./templedb domain remove PROJECT_SLUG DOMAIN --force
```
Removes a domain and all associated DNS records.

### DNS Commands

#### Configure DNS
```bash
./templedb domain dns configure PROJECT_SLUG DOMAIN [--target TARGET_NAME]
```
Configures DNS records and environment variables for a deployment target.

**Provider-Specific Behavior:**

- **Supabase**: Creates CNAME records, generates `DATABASE_URL`, `PUBLIC_URL`, `API_URL`
- **Vercel**: Creates CNAME to vercel-dns.com, generates `PUBLIC_URL`, `VERCEL_URL`
- **Generic**: Creates A or CNAME records based on host format, generates `PUBLIC_URL`

#### List DNS Records
```bash
./templedb domain dns list PROJECT_SLUG DOMAIN
```
Shows all DNS records configured for a domain.

#### Verify DNS Records
```bash
./templedb domain dns verify PROJECT_SLUG DOMAIN
```
Verifies that DNS records are properly configured and propagated. Uses `dig` or `nslookup` to check actual DNS resolution.

## Database Schema

The domain management system uses two main tables:

### `project_domains`
Stores domain registrations for projects.

```sql
CREATE TABLE project_domains (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    domain TEXT NOT NULL,
    registrar TEXT,
    status TEXT CHECK(status IN ('pending', 'active', 'expired')),
    primary_domain INTEGER DEFAULT 0,
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(project_id, domain)
);
```

### `dns_records`
Stores DNS record configurations.

```sql
CREATE TABLE dns_records (
    id INTEGER PRIMARY KEY,
    domain_id INTEGER NOT NULL,
    record_type TEXT CHECK(record_type IN ('A', 'AAAA', 'CNAME', 'TXT', 'MX', 'NS')),
    name TEXT NOT NULL,
    value TEXT NOT NULL,
    ttl INTEGER DEFAULT 3600,
    priority INTEGER,
    target_name TEXT,  -- Associated deployment target
    created_at TEXT,
    updated_at TEXT,
    UNIQUE(domain_id, name, record_type)
);
```

## Workflow Examples

### Example 1: Production and Staging Environments

```bash
# Register domain
./templedb domain register myapp example.com --registrar "Cloudflare"

# Add production target
./templedb target add myapp production \
  --provider supabase \
  --host db.example.supabase.co

# Add staging target
./templedb target add myapp staging \
  --provider supabase \
  --host staging.example.supabase.co

# Configure DNS for production (example.com)
./templedb domain dns configure myapp example.com --target production

# Configure DNS for staging (staging.example.com)
./templedb domain dns configure myapp example.com --target staging

# Verify both environments
./templedb domain dns verify myapp example.com

# Deploy to staging
./templedb deploy run myapp --target staging

# Deploy to production
./templedb deploy run myapp --target production
```

### Example 2: Multi-Project Setup

```bash
# Register domains for different projects
./templedb domain register api api.example.com
./templedb domain register frontend example.com
./templedb domain register admin admin.example.com

# Configure each project's DNS
./templedb domain dns configure api api.example.com --target production
./templedb domain dns configure frontend example.com --target production
./templedb domain dns configure admin admin.example.com --target production

# List all domains
./templedb domain list
```

## Environment Variable Management

Environment variables are stored with target-specific prefixes:

```
{target}:{VAR_NAME} = value
```

For example:
- `staging:DATABASE_URL` = postgresql://staging.woofs.com/postgres
- `staging:PUBLIC_URL` = https://staging.woofs-demo.com
- `production:DATABASE_URL` = postgresql://db.woofs.com/postgres
- `production:PUBLIC_URL` = https://woofs-demo.com

To view environment variables:
```bash
./templedb env vars PROJECT_SLUG
```

To manually set environment variables:
```bash
./templedb env set PROJECT_SLUG VAR_NAME value --target TARGET_NAME
```

## Integration with Deployment

The deployment orchestrator automatically:
1. Loads environment variables for the specified target
2. Substitutes them in deployment scripts and migration files
3. Uses the configured `DATABASE_URL` for migrations
4. Uses `PUBLIC_URL` and `API_URL` for service configuration

## DNS Provider Support

### Supabase
- Uses CNAME records
- Generates full PostgreSQL connection strings
- Sets up API and public URLs

### Vercel
- Uses CNAME to vercel-dns.com
- Generates deployment URLs
- Integrates with Vercel's DNS system

### Custom/Generic
- Supports A and CNAME records
- Flexible configuration for any hosting provider
- Manual DNS record management

## Tips and Best Practices

1. **Always verify DNS before deploying**: DNS propagation can take time. Use `dns verify` before running deployments.

2. **Use subdomain for non-production**: Configure staging as `staging.example.com` and production as `example.com`.

3. **Set primary domain**: Use `--primary` flag to mark your main production domain.

4. **Test with dry-run**: Use `--dry-run` flag on deployments to test configuration without executing.

5. **Backup before DNS changes**: DNS misconfiguration can cause downtime. Keep backups of working DNS records.

6. **Use descriptive target names**: Name targets clearly (`production`, `staging`, `dev`) for easier management.

## Troubleshooting

### DNS verification fails
- **Problem**: `dns verify` shows records not found
- **Solution**: Wait 5-60 minutes for DNS propagation, then try again

### Deployment can't connect to database
- **Problem**: Connection refused to database host
- **Solution**: Verify the actual database connection string is correct, not just the domain name

### Environment variables not found
- **Problem**: Deployment says missing environment variables
- **Solution**: Run `dns configure` again or manually set with `env set`

### Domain already registered error
- **Problem**: Trying to register a domain that exists
- **Solution**: Use `domain update` to modify existing domain, or `domain remove --force` to start over

## Future Enhancements

Potential future features:
- Automatic domain registration via API (Namecheap, GoDaddy APIs)
- Automatic DNS updates via API (Cloudflare, Route53)
- SSL/TLS certificate management
- CDN configuration (Cloudflare, CloudFront)
- Email DNS records (MX, SPF, DKIM)
- DNS health monitoring and alerts

## See Also

- [Deployment Guide](./DEPLOYMENT_EXAMPLE.md)
- [Environment Management](../README.md#environment-variables)
- [Target Management](../README.md#deployment-targets)
