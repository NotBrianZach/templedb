# TempleDB Deployment Quick Reference

**TL;DR**: Fast reference for deploying different project types

---

## 🚀 Quick Deployment Commands

### CLI Tools (like bza)

```bash
# Option 1: Nix package (recommended)
templedb deploy package bza --format nix-closure --output ./dist/
nix-store --export $(nix-store -qR ./dist/bza) > bza-bundle.nar

# Option 2: Standalone binary
templedb deploy package bza --format pyinstaller --output ./dist/
# Creates: dist/bza (single executable)

# Distribution
nix profile install ./dist/bza         # Nix users
./dist/bza                              # Standalone
```

### Web Services (like woofs_projects)

```bash
# Full deployment (database + backend + frontend)
templedb deploy run woofs_projects --target production

# Just backend (Docker)
templedb deploy package woofs_projects --format docker --push
docker compose up -d

# Just frontend (Vercel)
templedb deploy vercel woofs_projects --frontend-only --sync-secrets
```

### Games

```bash
# Client (static hosting)
templedb deploy static mygame --provider netlify

# Multiplayer server
templedb deploy package mygame-server --format docker
```

---

## 🔐 Secret Management Cheat Sheet

### Add Secrets

```bash
# Development (local, unencrypted)
templedb secret set myproject DATABASE_URL sqlite:///dev.db --env development

# Production (encrypted)
templedb secret set myproject DATABASE_URL postgresql://prod.db --env production
templedb secret set myproject OPENROUTER_API_KEY sk-... --env production
```

### Use Secrets in Code

**Python**:
```python
from common.secrets import get_secret

# Fallback chain: TempleDB → env var → .env → config file → error
DATABASE_URL = get_secret('DATABASE_URL', project='myproject')
```

**JavaScript**:
```javascript
import { getSecret } from './lib/secrets.js';

const DATABASE_URL = getSecret('DATABASE_URL', 'myproject');
```

### Inject Secrets at Deployment

```bash
# Docker
templedb deploy run myproject --target production --inject-secrets

# Vercel
templedb deploy vercel myproject --sync-secrets
```

---

## 📦 Cathedral Workflow

### TempleDB → TempleDB Deployment

```bash
# Source system
templedb cathedral export myproject --output /tmp/myproject.cathedral --compress

# Transfer
scp /tmp/myproject.cathedral deploy@target:/opt/cathedral/

# Target system
templedb cathedral import /opt/cathedral/myproject.cathedral
templedb deploy run myproject --target production
```

**Benefits**:
- Content deduplication (shared blobs stored once)
- VCS history preserved
- Deployment cache benefits

---

## 🎯 Deployment Strategy Selection

### Auto-Detect Target Capabilities

```bash
# Automatically choose best strategy
templedb deploy push myproject --target production --auto-detect
```

**Decision Tree**:
- Has TempleDB? → **Cathedral**
- Has Nix? → **Nix Closure**
- Has Docker? → **Docker Image**
- Otherwise → **Standalone Tarball**

### Force Specific Strategy

```bash
templedb deploy push myproject --target production --strategy cathedral
templedb deploy push myproject --target production --strategy docker
templedb deploy push myproject --target production --strategy nix-closure
```

---

## 🗃️ Database Deployment

### Apply Migrations

```bash
# Auto-apply pending migrations
templedb migration apply myproject --target production

# Check migration status
templedb migration status myproject --target production
```

### SQLite → PostgreSQL Migration

```bash
# Generate PostgreSQL schema from SQLite
templedb migration convert myproject --from sqlite --to postgresql

# Migrate data
templedb migration migrate-data myproject --from sqlite:///dev.db --to $DATABASE_URL
```

---

## 🔄 Advanced Deployments

### Blue-Green Deployment

```bash
# Deploy new version alongside old
templedb deploy run myproject --target production --strategy blue-green

# Switch traffic (after testing)
templedb deploy switch myproject --target production --to green

# Rollback if needed
templedb deploy switch myproject --target production --to blue
```

### Rollback

```bash
# Rollback to previous deployment
templedb deploy rollback myproject --target production

# Rollback to specific version
templedb deploy rollback myproject --target production --to-commit abc123
```

---

## 🎨 Project Type Templates

### Initialize Deployment Config

```bash
# CLI tool
templedb deploy init bza --type cli

# Web service
templedb deploy init woofs_projects --type web-service

# Game
templedb deploy init mygame --type game
```

**Generates**:
- Dockerfile (web service, game server)
- Systemd service unit (web service)
- Nix flake (CLI tool)
- CI/CD workflow (GitHub Actions)
- Secret fallback boilerplate

---

## 📊 Deployment Monitoring

### Check Deployment Status

```bash
# List deployments
templedb deploy list myproject

# Show deployment details
templedb deploy show myproject --deployment-id 123

# View logs
templedb deploy logs myproject --target production --tail 100
```

### Deployment History

```bash
# Show deployment timeline
templedb deploy history myproject --target production

# Compare deployments
templedb deploy diff myproject --from deployment-122 --to deployment-123
```

---

## 🌐 Platform-Specific Deployments

### Vercel

```bash
templedb deploy vercel myproject --sync-secrets
```

### Netlify

```bash
templedb deploy netlify myproject --sync-secrets
```

### Cloudflare Workers

```bash
templedb deploy cloudflare-workers myproject
```

### Supabase (Edge Functions)

```bash
templedb deploy supabase myproject --function-name my-function
```

---

## 🆘 Troubleshooting

### Secret Not Found

```
❌ Error: Secret 'DATABASE_URL' not found
```

**Fix**:
```bash
# Set the secret
templedb secret set myproject DATABASE_URL postgresql://...

# Or use environment variable
export DATABASE_URL=postgresql://...

# Or create .env file
echo "DATABASE_URL=postgresql://..." >> .env
```

### Target Not Responding

```
❌ Error: Cannot connect to target 'production'
```

**Fix**:
```bash
# Check target configuration
templedb target show myproject production

# Test SSH connection
ssh $(templedb target show myproject production --field host)

# Update target host
templedb target update myproject production --host new-host.com
```

### Deployment Cache Miss

```
⚠️  Deployment cache miss, building from scratch...
```

**Normal** - happens when:
- First deployment
- Dependencies changed
- Lock file updated

**To warm cache**:
```bash
templedb deploy build myproject --target production --cache-only
```

---

## 📖 See Also

- [Full Deployment Architecture](./DEPLOYMENT_ARCHITECTURE.md) - In-depth architectural review
- [Cathedral Package Format](./CATHEDRAL.md) - Package structure and internals
- [Secret Management](./SECRETS.md) - Advanced secret management strategies
- [CI/CD Integration](./CI_CD.md) - Automated deployment pipelines

---

**Quick Start**:
1. Add deployment target: `templedb target add myproject production --host deploy.example.com`
2. Set secrets: `templedb secret set myproject DATABASE_URL postgresql://...`
3. Deploy: `templedb deploy run myproject --target production`
