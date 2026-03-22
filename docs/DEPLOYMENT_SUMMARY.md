# TempleDB Deployment Summary

**Quick Overview**: Production-ready deployment strategies for all project types

---

## 📦 Documents Overview

1. **[DEPLOYMENT_ARCHITECTURE_V2.md](./DEPLOYMENT_ARCHITECTURE_V2.md)** - Complete architectural review
2. **[GAME_ENGINE_DEPLOYMENT.md](./GAME_ENGINE_DEPLOYMENT.md)** - Unity, Godot, HTML5 games
3. **[DEPLOYMENT_QUICK_REFERENCE.md](./DEPLOYMENT_QUICK_REFERENCE.md)** - Command cheat sheet

---

## 🎯 Deployment by Project Type

### CLI Tools (bza archetype)

**Target**: App Stores, Package Managers

```bash
# macOS App Store
templedb deploy macos-app bza --sign --notarize --upload

# Windows Store
templedb deploy windows-msix bza --sign --upload

# Homebrew (easiest for developers)
templedb deploy homebrew bza --create-tap yourorg/tap

# Linux (Snap/Flatpak)
templedb deploy snap bza --upload
templedb deploy flatpak bza --upload
```

**Distribution Channels**:
- ✅ macOS App Store (1B+ devices, 30% cut)
- ✅ Windows Store (1B+ devices, 15% cut)
- ✅ Homebrew (developers, free)
- ✅ Snap Store (Ubuntu users, free)
- ✅ Flathub (universal Linux, free)

---

### Web Services (woofs_projects archetype)

**Target**: VPS with systemd + Nix (no Docker)

```bash
# Full deployment (backend + frontend + database)
templedb deploy run woofs_projects --target production-vps

# Backend only (systemd service)
templedb deploy systemd woofs_projects --target vps

# Frontend only (Vercel)
templedb deploy vercel woofs_projects --frontend-only --sync-secrets

# Database migrations
templedb migration apply woofs_projects --target production
```

**Architecture**:
```
Frontend (Vercel/Netlify)
    ↓ API calls
Backend (systemd + Nix on VPS)
    ↓ SQL queries
Database (PostgreSQL/Supabase)
```

**Why systemd instead of Docker**:
- ✅ Native Linux integration (journald logs)
- ✅ Lower overhead
- ✅ Better for Nix-managed deployments
- ✅ Easier debugging
- ✅ Automatic restarts, resource limits

---

### Games

**Target**: Steam (primary), Itch.io (secondary)

#### Unity Games

```bash
# Initialize Steam integration
templedb steam init my-unity-game --app-id 123456 --engine unity

# Build all platforms
templedb deploy build-matrix my-unity-game \
  --platforms windows,macos,linux,webgl \
  --output ./builds/

# Upload to Steam
templedb deploy steam my-unity-game --branch default

# Upload WebGL to Itch.io
templedb deploy itch my-unity-game --platform webgl
```

**Steamworks.NET Integration**:
- Achievements
- Cloud saves
- Leaderboards
- Steam overlay
- Multiplayer (P2P)

#### Godot Games

```bash
# Initialize Steam integration
templedb steam init my-godot-game --app-id 123456 --engine godot

# Build for Steam
templedb deploy build-matrix my-godot-game \
  --platforms windows,macos,linux \
  --output ./builds/

# Upload to Steam
templedb deploy steam my-godot-game --branch default
```

**GodotSteam Integration**:
- Native GDScript Steam API
- All Steam features supported
- Lightweight and fast

#### HTML5 Games

```bash
# Build for production
templedb deploy build my-html5-game --format html5

# Deploy to Itch.io
templedb deploy itch my-html5-game --type html5

# Or deploy to Netlify/Vercel
templedb deploy netlify my-html5-game
```

**Best For**:
- Browser-based games
- Mobile-friendly games
- Quick prototypes

---

## 🔐 Secret Management

**5-Layer Fallback Chain** (works for all project types):

```
1. TempleDB secrets (production, encrypted)
   ↓
2. Environment variables (CI/CD, systemd)
   ↓
3. .env file (local development)
   ↓
4. Config file (~/.config/app/config.json)
   ↓
5. Platform-specific (Keychain, Credential Manager, Steam Cloud)
   ↓
6. Error with setup instructions
```

**Usage**:

```python
# Python
from common.secrets import get_secret

DATABASE_URL = get_secret('DATABASE_URL', project='woofs_projects')
STEAM_API_KEY = get_secret('STEAM_API_KEY', project='mygame')
```

```javascript
// JavaScript
import { getSecret } from './lib/secrets.js';

const DATABASE_URL = getSecret('DATABASE_URL', 'woofs_projects');
const STEAM_API_KEY = getSecret('STEAM_API_KEY', 'mygame');
```

**Set Secrets**:

```bash
# Production (encrypted with age)
templedb secret set myproject DATABASE_URL postgresql://... --env production

# Development (unencrypted)
templedb secret set myproject DATABASE_URL sqlite:///dev.db --env development

# Steam API key
templedb secret set mygame STEAM_API_KEY abc123 --env production
```

---

## 📦 Cathedral Packages

**TempleDB → TempleDB Deployment** (best option when both systems have TempleDB):

```bash
# Source system
templedb cathedral export myproject --compress --output /tmp/myproject.cathedral

# Transfer
scp /tmp/myproject.cathedral build-server:/opt/cathedral/

# Build server
templedb cathedral import /opt/cathedral/myproject.cathedral
templedb deploy run myproject --target production
```

**Benefits**:
- ✅ Content deduplication (shared blobs stored once)
- ✅ VCS history preserved
- ✅ Deployment cache reused
- ✅ Much faster for large projects

---

## 🎮 Steam Workflow (Complete)

### 1. Get Steam Partner Account
- Cost: $100 one-time fee
- Sign up: partner.steamgames.com
- Get App ID assigned

### 2. Initialize Project

```bash
templedb steam init mygame --app-id 123456 --engine unity
```

### 3. Integrate Steamworks SDK

**Unity**: Install Steamworks.NET plugin
**Godot**: Install GodotSteam plugin

### 4. Build for All Platforms

```bash
templedb deploy build-matrix mygame \
  --platforms windows,macos,linux \
  --output ./builds/
```

### 5. Upload to Steam

```bash
templedb deploy steam mygame --branch beta

# Test beta build, then promote to live
templedb steam promote mygame --from beta --to default
```

### 6. Configure Achievements

```bash
# Upload achievements from JSON
templedb steam upload-achievements mygame --from achievements.json
```

---

## 🏪 App Store Workflow (CLI Tools)

### macOS App Store

```bash
# Prerequisites: Apple Developer Account ($99/year)

# Build, sign, notarize, and upload
templedb deploy macos-app bza \
  --apple-id "you@example.com" \
  --team-id "TEAM_ID" \
  --certificate "Developer ID Application: Your Name" \
  --upload
```

### Windows Store

```bash
# Prerequisites: Microsoft Partner Center (free), Code signing cert ($100-400/year)

# Build, sign, and upload
templedb deploy windows-msix bza \
  --publisher "CN=Your Name" \
  --certificate certificate.pfx \
  --upload
```

### Homebrew (Easiest)

```bash
# Create Homebrew formula and tap
templedb deploy homebrew bza --create-tap yourorg/tap

# Users install via:
# brew tap yourorg/tap
# brew install bza
```

---

## 🚀 CI/CD Integration

### GitHub Actions

```bash
# Generate workflow
templedb deploy init-ci myproject --provider github

# Creates: .github/workflows/deploy.yml
```

**Example workflow** (auto-generated):

```yaml
name: Deploy
on:
  push:
    tags: ['v*']

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Setup TempleDB
        run: curl -sSL https://install.templedb.dev | sh

      - name: Sync project
        run: templedb project sync .

      - name: Deploy
        env:
          DEPLOYMENT_KEY: ${{ secrets.DEPLOYMENT_KEY }}
        run: |
          templedb deploy run $(basename $PWD) --target production
```

---

## 📊 Comparison Matrix

### Deployment Strategies

| Project Type | Primary Method | Secondary Options | Distribution |
|-------------|---------------|------------------|--------------|
| **CLI Tools** | Homebrew, Snap | App Stores, Nix | brew, snap, App Stores |
| **Web Services** | systemd + Nix | Vercel (frontend) | VPS, Cloud |
| **Unity Games** | Steam | Itch.io | Steam, Itch.io |
| **Godot Games** | Steam | Itch.io | Steam, Itch.io |
| **HTML5 Games** | Itch.io, Netlify | GitHub Pages | Itch.io, web hosting |

### Distribution Channels

| Channel | Reach | Revenue Split | Review Time | Best For |
|---------|-------|--------------|-------------|----------|
| **Steam** | 120M+ | 30% | 1-5 days | Games |
| **macOS App Store** | 1B+ | 30% | 1-7 days | CLI tools, apps |
| **Windows Store** | 1B+ | 15% | 1-3 days | CLI tools, apps |
| **Homebrew** | Developers | 0% | Instant (PR merge) | CLI tools |
| **Itch.io** | Indie gamers | 10% (or 0%) | Instant | Indie games |

---

## ⚙️ Implementation Status

### ✅ Completed (Current TempleDB)
- Cathedral package system
- Deployment targets (database schema)
- Environment variable management
- Nix integration
- Deployment cache

### 🚧 In Progress (Roadmap)
- [ ] **Phase 1**: Nix closure deployment for web services
- [ ] **Phase 2**: App store deployment (macOS, Windows, Homebrew)
- [ ] **Phase 3**: Steam integration (Unity, Godot)
- [ ] **Phase 4**: Platform-specific secret storage
- [ ] **Phase 5**: CI/CD templates (GitHub Actions)

### 🎯 Success Metrics
- [ ] Deploy `bza` to macOS App Store
- [ ] Deploy `bza` via `brew install bza`
- [ ] Deploy `woofs_projects` as systemd service in <5 minutes
- [ ] Deploy a Unity game to Steam with achievements
- [ ] Deploy a Godot game to Steam with cloud saves
- [ ] 100% secret fallback coverage

---

## 📖 Quick Command Reference

```bash
# CLI Tools
templedb deploy homebrew bza --create-tap
templedb deploy macos-app bza --sign --upload
templedb deploy windows-msix bza --sign --upload

# Web Services
templedb deploy run woofs_projects --target production-vps
templedb migration apply woofs_projects --target production

# Games (Unity)
templedb steam init mygame --app-id 123456 --engine unity
templedb deploy build-matrix mygame --platforms windows,macos,linux
templedb deploy steam mygame --branch default

# Games (Godot)
templedb steam init mygame --app-id 123456 --engine godot
templedb deploy steam mygame --branch default

# Games (HTML5)
templedb deploy build mygame --format html5
templedb deploy itch mygame --type html5

# Secrets
templedb secret set myproject API_KEY value --env production
templedb secret get myproject API_KEY --env production

# Cathedral
templedb cathedral export myproject --compress
templedb cathedral import myproject.cathedral
```

---

## 🆘 Troubleshooting

### Secret Not Found

```bash
# Set the secret
templedb secret set myproject DATABASE_URL postgresql://...

# Or use environment variable
export DATABASE_URL=postgresql://...

# Or create .env file
echo "DATABASE_URL=postgresql://..." >> .env
```

### Unity Build Fails

```bash
# Check Unity version
/Applications/Unity/Hub/Editor/2022.3.10f1/Unity.app/Contents/MacOS/Unity --version

# Check build log
cat builds/build-windows.log
```

### Steam Upload Fails

```bash
# Login to Steam
steamcmd +login yourusername

# Check App ID
templedb steam status mygame

# Verify depot configuration
cat .templedb/steam_config.json
```

---

## 🎓 Learning Path

### For CLI Tool Developers (bza)
1. Read: [DEPLOYMENT_ARCHITECTURE_V2.md § CLI Tools](#)
2. Try: Deploy to Homebrew first (easiest)
3. Advanced: macOS App Store deployment

### For Web Service Developers (woofs_projects)
1. Read: [DEPLOYMENT_ARCHITECTURE_V2.md § Web Services](#)
2. Try: Deploy backend with systemd + Nix
3. Advanced: Blue-green deployments

### For Game Developers
1. Read: [GAME_ENGINE_DEPLOYMENT.md](#)
2. Choose engine: Unity or Godot
3. Try: Deploy to Itch.io first (no Steam fee)
4. Advanced: Steam integration with achievements

---

**Document Status**: Executive Summary
**Last Updated**: 2026-03-21
