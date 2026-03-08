# Cloudflare API Token Setup Guide

This guide shows you exactly how to create a Cloudflare API token with the correct permissions for TempleDB DNS automation.

## Recommended Approach: Scoped API Token

API tokens are more secure than Global API Keys because you can limit their permissions and scope.

## Step-by-Step Setup

### 1. Log into Cloudflare

Go to: https://dash.cloudflare.com/profile/api-tokens

### 2. Create a New Token

Click **"Create Token"**

### 3. Choose a Template

**Option A: Use the "Edit zone DNS" template** (Recommended)
- Click "Use template" next to **"Edit zone DNS"**
- This pre-configures most settings correctly

**Option B: Start from scratch**
- Click "Create Custom Token"

### 4. Configure Token Permissions

You need the following permissions:

#### Required Permissions:

| Permission | Resource | Level |
|------------|----------|-------|
| Zone | DNS | Edit |
| Zone | Zone | Read |

**In the Cloudflare UI:**

1. **Permissions section:**
   - Add permission: `Zone` → `DNS` → `Edit`
   - Add permission: `Zone` → `Zone` → `Read`

2. **Zone Resources:**
   - **Specific zone** (Recommended): Select the domain you want to manage
     - Example: `woofs-demo.com`
   - **All zones**: If you want one token for all your domains

3. **Optional but recommended:**
   - Set IP filtering to your server IPs
   - Set TTL (expiration date) for security

### 5. Token Configuration Details

#### Permissions Explained

**DNS Edit** - Required for:
- Creating new DNS records
- Updating existing DNS records
- Deleting DNS records

**Zone Read** - Required for:
- Listing zones (finding your domain)
- Reading current DNS records
- Getting zone ID

#### Minimum Permissions (Most Secure)

If you want the absolute minimum:
```
Permissions:
  Zone - DNS - Edit
  Zone - Zone - Read

Zone Resources:
  Include - Specific zone - woofs-demo.com

Client IP Address Filtering:
  Is in - 1.2.3.4, 5.6.7.8  (your server IPs)
```

#### Broader Permissions (More Flexible)

For managing multiple domains:
```
Permissions:
  Zone - DNS - Edit
  Zone - Zone - Read

Zone Resources:
  Include - All zones

Client IP Address Filtering:
  (Optional - leave blank if deploying from various IPs)
```

### 6. Create and Copy Token

1. Click **"Continue to summary"**
2. Review the permissions
3. Click **"Create Token"**
4. **IMPORTANT**: Copy the token immediately - you won't be able to see it again!

The token will look like:
```
aBcD3fGhIjKlMnOpQrStUvWxYz1234567890AbCdEf
```

### 7. Add Token to TempleDB

```bash
./templedb domain provider add cloudflare
# Choose "Use API Token? Y"
# Paste your token
```

### 8. Test the Token

```bash
# List providers to verify it was added
./templedb domain provider list

# Try applying DNS (will test API access)
./templedb domain dns apply PROJECT DOMAIN --target staging
```

## Alternative: Global API Key (Not Recommended)

If you must use the Global API Key instead of a token:

### Why Not Recommended:
- Full account access (very broad permissions)
- Can't restrict to specific zones
- Can't set expiration
- Can't limit by IP

### If You Must Use It:

1. Go to: https://dash.cloudflare.com/profile/api-tokens
2. Scroll to "API Keys" section
3. Click "View" next to "Global API Key"
4. Enter your password
5. Copy the key

```bash
./templedb domain provider add cloudflare
# Choose "Use API Token? n"
# Enter your Cloudflare email
# Enter your Global API Key
```

## Troubleshooting

### Error: "Zone not found"

**Problem**: Token doesn't have access to the zone

**Solution**:
1. Go back to API tokens page
2. Edit your token
3. Under "Zone Resources", ensure your domain is included
4. If using "Specific zone", verify the domain name is correct

### Error: "Insufficient permissions"

**Problem**: Token missing required permissions

**Solution**:
1. Edit your token
2. Ensure you have:
   - Zone → DNS → Edit
   - Zone → Zone → Read
3. Save and try again

### Error: "Invalid API token"

**Problem**: Token was copied incorrectly or has expired

**Solution**:
1. Verify token was copied completely (no extra spaces)
2. Check if token has expired
3. Create a new token if needed

### Error: "IP address not allowed"

**Problem**: Your IP is not in the allowed list

**Solution**:
1. Edit token in Cloudflare
2. Either remove IP filtering or add your current IP
3. To check your IP: `curl ifconfig.me`

## Security Best Practices

### 1. Use Scoped Tokens
✅ Create separate tokens for different domains
✅ Limit to specific zones when possible

### 2. Set Expiration
✅ Set TTL to 90 days or 1 year
✅ Rotate tokens before expiration

### 3. Use IP Filtering
✅ Whitelist only your deployment server IPs
✅ Update when server IPs change

### 4. Monitor Usage
✅ Check Cloudflare API logs regularly
✅ Revoke unused tokens

### 5. Principle of Least Privilege
✅ Only grant DNS Edit (not Zone Edit, SSL, etc.)
✅ Don't use Global API Key unless absolutely necessary

## Token Management

### View Active Tokens
https://dash.cloudflare.com/profile/api-tokens

### Edit Token
1. Click on the token name
2. Modify permissions or zones
3. Roll token if compromised

### Revoke Token
1. Find token in list
2. Click "..." menu
3. Click "Revoke"

### Rotate Token
```bash
# 1. Create new token in Cloudflare
# 2. Update in TempleDB
./templedb domain provider add cloudflare
# (Will replace existing token)
# 3. Test new token
./templedb domain dns apply PROJECT DOMAIN --target staging
# 4. Revoke old token in Cloudflare
```

## Example Token Configurations

### Development Environment
```
Name: TempleDB Dev - example.com
Permissions:
  Zone - DNS - Edit
  Zone - Zone - Read
Zone Resources:
  Specific zone - example.com
IP Filtering: None
TTL: 1 year
```

### Production Environment
```
Name: TempleDB Prod - All Zones
Permissions:
  Zone - DNS - Edit
  Zone - Zone - Read
Zone Resources:
  All zones
IP Filtering: 1.2.3.4, 5.6.7.8 (production servers)
TTL: 90 days
```

### CI/CD Environment
```
Name: TempleDB CI/CD
Permissions:
  Zone - DNS - Edit
  Zone - Zone - Read
Zone Resources:
  All zones
IP Filtering: GitHub Actions IP ranges
TTL: 6 months
```

## Quick Reference

| Task | Permission Needed |
|------|-------------------|
| List DNS records | Zone → Zone → Read |
| Create DNS record | Zone → DNS → Edit |
| Update DNS record | Zone → DNS → Edit |
| Delete DNS record | Zone → DNS → Edit |
| Find zone by name | Zone → Zone → Read |
| Get zone ID | Zone → Zone → Read |

## Additional Resources

- [Cloudflare API Token Documentation](https://developers.cloudflare.com/fundamentals/api/get-started/create-token/)
- [Cloudflare API Reference](https://developers.cloudflare.com/api/)
- [API Token Permissions](https://developers.cloudflare.com/fundamentals/api/reference/permissions/)

## Summary

**Minimum required permissions:**
- ✅ Zone → DNS → Edit
- ✅ Zone → Zone → Read

**Recommended setup:**
- Use scoped API token (not Global API Key)
- Limit to specific zones
- Add IP filtering
- Set expiration date
- Monitor usage

Once configured, you can fully automate DNS management:
```bash
./templedb domain dns apply PROJECT DOMAIN --target TARGET
```

No more manual DNS configuration! 🎉
