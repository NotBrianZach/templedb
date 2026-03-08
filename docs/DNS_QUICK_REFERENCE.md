# DNS Automation Quick Reference

## Essential Commands

### Setup (One Time)

```bash
# Add DNS provider credentials
./templedb domain provider add cloudflare|namecheap|route53

# Register domain
./templedb domain register PROJECT_SLUG DOMAIN --registrar NAME

# Add deployment target
./templedb target add PROJECT_SLUG TARGET --provider PROVIDER --host HOST
```

### DNS Management (Each Deploy)

```bash
# Configure DNS records (database)
./templedb domain dns configure PROJECT_SLUG DOMAIN --target TARGET

# Apply DNS via API (automated!)
./templedb domain dns apply PROJECT_SLUG DOMAIN --target TARGET

# Verify DNS is live
./templedb domain dns verify PROJECT_SLUG DOMAIN
```

## Cloudflare API Token Permissions

**Required:**
- Zone → DNS → Edit
- Zone → Zone → Read

**Create at:** https://dash.cloudflare.com/profile/api-tokens

**Template:** "Edit zone DNS"

## Quick Example

```bash
# Setup
./templedb domain provider add cloudflare
./templedb domain register myapp example.com --registrar "Cloudflare"
./templedb target add myapp production --provider supabase --host db.example.com

# Deploy
./templedb domain dns configure myapp example.com --target production
./templedb domain dns apply myapp example.com --target production
./templedb deploy run myapp --target production
```

## Common Tasks

### List Everything
```bash
./templedb domain provider list        # Show configured providers
./templedb domain list PROJECT         # Show domains for project
./templedb domain dns list PROJECT DOMAIN  # Show DNS records
./templedb env vars PROJECT            # Show environment variables
```

### Update DNS
```bash
# Reconfigure and reapply
./templedb domain dns configure PROJECT DOMAIN --target TARGET
./templedb domain dns apply PROJECT DOMAIN --target TARGET
```

### Troubleshooting
```bash
# Check credentials
./templedb domain provider list

# Test with explicit provider
./templedb domain dns apply PROJECT DOMAIN --target TARGET --provider cloudflare

# Verify DNS
./templedb domain dns verify PROJECT DOMAIN
```

## Files & Documentation

| File | Purpose |
|------|---------|
| `DNS_API_AUTOMATION.md` | Complete guide |
| `CLOUDFLARE_API_TOKEN_SETUP.md` | Cloudflare setup |
| `DNS_WORKFLOW_DIAGRAM.md` | Visual diagrams |
| `DOMAIN_DNS_MANAGEMENT.md` | Domain management |

## Support Matrix

| Provider | Status | Credentials Needed |
|----------|--------|-------------------|
| Cloudflare | ✅ Full support | API token or Global key |
| Namecheap | ✅ Full support | API key + whitelisted IP |
| Route53 | ✅ Full support | AWS access keys |

## Workflow Comparison

**Manual:**
1. Configure → 2. List → 3. Log in to DNS provider → 4. Add records manually → 5. Wait → 6. Verify → 7. Deploy

**Automated:**
1. Configure → 2. Apply ✨ → 3. Deploy

## Security Checklist

- ✅ Use scoped API tokens (not global keys)
- ✅ Limit token to specific zones
- ✅ Enable IP filtering
- ✅ Set token expiration
- ✅ Rotate tokens regularly
- ✅ Monitor API usage

## Dependencies

```bash
# For Cloudflare/Namecheap (already installed)
pip install requests

# For Route53 (optional)
pip install boto3
```

## Getting Help

```bash
./templedb domain --help
./templedb domain provider --help
./templedb domain dns --help
./templedb domain dns apply --help
```

## Pro Tips

💡 **Auto-detect provider** - Omit `--provider` flag, TempleDB detects from registrar

💡 **Multiple environments** - Run `dns apply` for each target (staging, production)

💡 **CI/CD ready** - All commands work in automated pipelines

💡 **Safe testing** - Use `dns configure` + `dns list` to preview without applying

💡 **Global credentials** - One token can manage all your domains

## Common Errors

| Error | Solution |
|-------|----------|
| "No credentials found" | `./templedb domain provider add PROVIDER` |
| "Zone not found" | Check token has zone access |
| "IP not whitelisted" | Add IP in Namecheap settings |
| "Module 'requests' not found" | `pip install requests` |

## Next Steps

1. **Setup:** Add your DNS provider credentials
2. **Test:** Configure and apply DNS for staging
3. **Production:** Apply to production when ready
4. **Automate:** Add to CI/CD pipeline

📖 **Full Guides:**
- [DNS API Automation](./DNS_API_AUTOMATION.md)
- [Cloudflare Setup](./CLOUDFLARE_API_TOKEN_SETUP.md)
- [Workflow Diagrams](./DNS_WORKFLOW_DIAGRAM.md)
