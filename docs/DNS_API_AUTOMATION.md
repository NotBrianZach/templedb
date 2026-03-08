# Automated DNS Management with Provider APIs

TempleDB supports fully automated DNS record management through integration with popular DNS provider APIs. This eliminates the need for manual DNS configuration at your registrar's control panel.

## Supported Providers

- **Cloudflare** - API token or Global API Key
- **Namecheap** - API key with whitelisted IP
- **AWS Route53** - AWS access keys

## Quick Start

### 1. Add DNS Provider Credentials

```bash
# Interactive setup for Cloudflare
./templedb domain provider add cloudflare

# Interactive setup for Namecheap
./templedb domain provider add namecheap

# Interactive setup for Route53
./templedb domain provider add route53
```

The command will interactively prompt for the required credentials for each provider.

### 2. Configure DNS Records

First, configure what DNS records you want (this stores them in TempleDB):

```bash
./templedb domain dns configure PROJECT_SLUG DOMAIN --target TARGET_NAME
```

### 3. Apply DNS Records via API

Now automatically apply them to your DNS provider:

```bash
# Auto-detect provider from registrar
./templedb domain dns apply PROJECT_SLUG DOMAIN --target TARGET_NAME

# Or specify provider explicitly
./templedb domain dns apply PROJECT_SLUG DOMAIN --target staging --provider cloudflare
```

That's it! The DNS records are now live.

## Complete Workflow Example

```bash
# 1. Register domain in TempleDB
./templedb domain register myapp example.com --registrar "Cloudflare"

# 2. Add deployment target
./templedb target add myapp production \
  --provider supabase \
  --host db.example.supabase.co

# 3. Add Cloudflare API credentials
./templedb domain provider add cloudflare
# Enter API token when prompted

# 4. Configure DNS records (stores in database)
./templedb domain dns configure myapp example.com --target production

# 5. Apply DNS records to Cloudflare (via API)
./templedb domain dns apply myapp example.com --target production

# 6. Verify DNS is live
./templedb domain dns verify myapp example.com

# 7. Deploy your app
./templedb deploy run myapp --target production
```

## Provider Setup Guides

### Cloudflare

**Recommended: API Token (scoped permissions)**

**Required Permissions:**
- Zone → DNS → Edit
- Zone → Zone → Read

**Quick Setup:**
1. Go to https://dash.cloudflare.com/profile/api-tokens
2. Click "Create Token"
3. Use template: "Edit zone DNS"
4. Select the specific zone (domain)
5. Copy the token

```bash
./templedb domain provider add cloudflare
# Choose "Use API Token? Y"
# Paste token when prompted
```

**📖 Detailed Setup Guide:** See [Cloudflare API Token Setup](./CLOUDFLARE_API_TOKEN_SETUP.md) for:
- Step-by-step token creation
- Exact permission configuration
- Security best practices
- Troubleshooting

**Alternative: Global API Key (Not Recommended)**

1. Go to https://dash.cloudflare.com/profile/api-tokens
2. View "Global API Key"
3. Note your email and key

```bash
./templedb domain provider add cloudflare
# Choose "Use API Token? n"
# Enter email and global API key
```

### Namecheap

1. Enable API access: https://ap.www.namecheap.com/settings/tools/apiaccess/
2. Whitelist your server's IP address
3. Copy your API key and username

```bash
./templedb domain provider add namecheap
# Enter API username
# Enter API key
# Enter your whitelisted IP address
```

**Note**: Namecheap requires IP whitelisting. If deploying from multiple servers, you'll need to whitelist all IPs.

### AWS Route53

1. Create IAM user with Route53 permissions:
   - AmazonRoute53FullAccess (or more restrictive policy)
2. Generate access key and secret

```bash
./templedb domain provider add route53
# Enter AWS Access Key ID
# Enter AWS Secret Access Key
# Enter region (default: us-east-1)
```

**Minimal IAM Policy:**
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "route53:ListHostedZones",
        "route53:GetHostedZone",
        "route53:ListResourceRecordSets",
        "route53:ChangeResourceRecordSets"
      ],
      "Resource": "*"
    }
  ]
}
```

## Credential Scoping

Credentials can be scoped globally or per-domain:

### Global Credentials (recommended for most cases)
```bash
./templedb domain provider add cloudflare
```
Works for all domains managed by this provider.

### Domain-Specific Credentials
```bash
./templedb domain provider add cloudflare --domain example.com
```
Only used for example.com. Useful if different domains use different API keys.

## Command Reference

### Provider Management

#### Add Provider Credentials
```bash
./templedb domain provider add PROVIDER [--domain DOMAIN]
```
Interactive setup for DNS provider credentials.

**Options:**
- `PROVIDER`: cloudflare, namecheap, or route53
- `--domain`: Scope credentials to specific domain (optional)

#### List Configured Providers
```bash
./templedb domain provider list
```
Shows all configured DNS providers and their scope.

### DNS Record Management

#### Apply DNS Records via API
```bash
./templedb domain dns apply PROJECT_SLUG DOMAIN [--target TARGET] [--provider PROVIDER]
```
Automatically create/update DNS records using provider API.

**Options:**
- `--target`: Deployment target (default: production)
- `--provider`: Force specific provider (cloudflare, namecheap, route53)

**How it works:**
1. Loads DNS records from TempleDB for the specified target
2. Retrieves provider credentials
3. Connects to DNS provider API
4. Syncs records (creates new, updates existing)
5. Marks domain as active

#### Configure DNS Records (Database Only)
```bash
./templedb domain dns configure PROJECT_SLUG DOMAIN --target TARGET
```
Generates DNS record configuration and stores in TempleDB. Does NOT apply to DNS provider.

Use this to plan DNS records, then apply them with `dns apply`.

## API vs Manual DNS Management

### API-Based (Automated)
```bash
# Configure + Apply in one step
./templedb domain dns configure myapp example.com --target prod
./templedb domain dns apply myapp example.com --target prod
```

**Pros:**
- Fully automated
- No manual steps
- Can be scripted/automated in CI/CD
- Instant updates

**Cons:**
- Requires API credentials
- Need to whitelist IPs (Namecheap)
- Provider-specific setup

### Manual (Traditional)
```bash
# Configure only
./templedb domain dns configure myapp example.com --target prod
./templedb domain dns list myapp example.com
# Manually add records at your registrar
./templedb domain dns verify myapp example.com
```

**Pros:**
- No API credentials needed
- Works with any DNS provider
- More control

**Cons:**
- Manual steps required
- Slower
- Error-prone
- Can't automate

## Security Best Practices

1. **Use scoped API tokens**: Prefer API tokens with limited permissions over global API keys
2. **Store credentials securely**: TempleDB stores credentials in the database. Ensure database has proper permissions.
3. **Rotate credentials regularly**: Update API tokens/keys periodically
4. **Use domain-specific credentials**: For sensitive domains, use domain-scoped credentials
5. **Audit API usage**: Check your DNS provider's API logs for unauthorized access

## CI/CD Integration

Automate DNS management in your deployment pipeline:

```yaml
# Example GitHub Actions workflow
- name: Configure DNS
  run: |
    ./templedb domain dns configure myapp example.com --target production

- name: Apply DNS via API
  run: |
    ./templedb domain dns apply myapp example.com --target production
  env:
    TEMPLEDB_PATH: ${{ secrets.TEMPLEDB_PATH }}

- name: Verify DNS propagation
  run: |
    ./templedb domain dns verify myapp example.com
```

## Troubleshooting

### "No credentials found for provider"
```bash
# Add provider credentials
./templedb domain provider add PROVIDER_NAME
```

### "Failed to initialize DNS provider: requests library required"
```bash
pip install requests
```

### Cloudflare: "Zone not found"
- Ensure domain is added to your Cloudflare account
- Check API token has access to the zone
- Verify domain spelling

### Namecheap: "IP not whitelisted"
- Whitelist your server IP at: https://ap.www.namecheap.com/settings/tools/apiaccess/
- Ensure IP in credentials matches whitelisted IP

### Route53: "Access denied"
- Check IAM permissions for Route53
- Ensure hosted zone exists for domain
- Verify AWS credentials are correct

### DNS records not applying
```bash
# List configured records
./templedb domain dns list PROJECT DOMAIN

# Check provider credentials
./templedb domain provider list

# Try with explicit provider
./templedb domain dns apply PROJECT DOMAIN --provider cloudflare
```

## Credential Storage Format

Credentials are stored encrypted in the `environment_variables` table:

```sql
scope_type: 'domain' or 'global'
scope_id: domain name or 'dns_providers'
var_name: 'dns_provider:PROVIDER_NAME'
var_value: JSON-encoded credentials
```

### Cloudflare
```json
{
  "api_token": "TOKEN"
}
```
or
```json
{
  "email": "user@example.com",
  "api_key": "KEY"
}
```

### Namecheap
```json
{
  "api_user": "username",
  "api_key": "KEY",
  "client_ip": "1.2.3.4"
}
```

### Route53
```json
{
  "aws_access_key_id": "AKIAIOSFODNN7EXAMPLE",
  "aws_secret_access_key": "SECRET",
  "region": "us-east-1"
}
```

## API Rate Limits

Be aware of provider rate limits:

- **Cloudflare**: 1,200 requests per 5 minutes
- **Namecheap**: ~20 API calls per minute
- **Route53**: 5 requests per second per account

TempleDB batches operations efficiently, but for bulk operations, consider rate limiting.

## Migration from Manual to API-Based

If you've been using manual DNS management:

1. Add provider credentials:
   ```bash
   ./templedb domain provider add PROVIDER
   ```

2. Verify existing records match:
   ```bash
   ./templedb domain dns list PROJECT DOMAIN
   ./templedb domain dns verify PROJECT DOMAIN
   ```

3. Apply via API (will sync/update):
   ```bash
   ./templedb domain dns apply PROJECT DOMAIN --target TARGET
   ```

The `apply` command uses "upsert" logic - it creates records that don't exist and updates those that do.

## See Also

- [Domain Management Guide](./DOMAIN_DNS_MANAGEMENT.md)
- [Deployment Guide](./DEPLOYMENT_EXAMPLE.md)
- [Secret Management](../README.md#secrets)
