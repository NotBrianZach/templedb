# TempleDB Deployment Architecture Review (v2)

**Version**: 2.0
**Date**: 2026-03-21
**Status**: Updated for Steam, App Stores, Native Deployment

## Executive Summary

This document presents a comprehensive architectural review of deployment strategies for TempleDB-managed projects, with specific focus on **production deployment targets**:

1. **CLI Tools** (exemplar: `bza`) - **App store distribution** (macOS App Store, Windows Store, Homebrew, Snap)
2. **Web Services** (exemplar: `woofs_projects`) - **Native systemd services** with Nix dependency management
3. **Games** - **Steam distribution** with Steamworks integration, plus Itch.io fallback

The architecture emphasizes **native platform integration**, **intelligent fallback strategies** for dependencies, and **seamless Cathedral package transfers** for TempleDB-to-TempleDB deployments.

---

## Table of Contents

1. [Current State Analysis](#current-state-analysis)
2. [Core Deployment Challenges](#core-deployment-challenges)
3. [Architectural Patterns](#architectural-patterns)
4. [CLI Tools: App Store Deployment](#cli-tools-app-store-deployment)
5. [Web Services: Native Systemd Deployment](#web-services-native-systemd-deployment)
6. [Games: Steam Deployment](#games-steam-deployment)
7. [Secret Management & Fallback Strategies](#secret-management--fallback-strategies)
8. [Cathedral Integration](#cathedral-integration)
9. [Comparison Matrices](#comparison-matrices)
10. [Implementation Roadmap](#implementation-roadmap)

---

## Current State Analysis

### Existing TempleDB Infrastructure

TempleDB currently provides:

#### 1. **Cathedral Package System**
- Export/import projects as `.cathedral` packages
- Content-addressable storage with deduplication
- VCS history preservation
- Compression support (zlib, zstd)

#### 2. **Deployment Targets**
- Multiple target types: `database`, `edge_function`, `static_site`, `native_service`
- Provider tracking: Supabase, Vercel, Steam, App Stores
- VPN requirements, access URLs

#### 3. **Nix Integration**
- FHS (Filesystem Hierarchy Standard) environments
- Reproducible builds
- Isolated execution environments
- **Primary deployment mechanism** (replaces Docker)

---

## Core Deployment Challenges

### 1. **Platform-Specific Packaging**

Different platforms require different packaging formats:

| Platform | Package Format | Signing Required | Distribution |
|----------|---------------|------------------|--------------|
| **macOS App Store** | .app bundle → .pkg | ✅ Apple Developer | App Store |
| **Windows Store** | MSIX | ✅ Microsoft cert | Microsoft Store |
| **Linux Snap** | .snap | Optional | Snapcraft |
| **Linux Flatpak** | .flatpak | Optional | Flathub |
| **Homebrew** | Ruby formula | ❌ | brew install |
| **Steam** | Depot files | ✅ Steam Partner | Steam platform |

**Challenge**: Automate platform-specific builds with code signing and notarization.

### 2. **Steam Integration**

Steam requires:
- **Steamworks SDK** integration for achievements, cloud saves, multiplayer
- **Steam Depot** system for content delivery
- **Steam Pipe** for build uploads
- **Platform-specific builds** (Windows, macOS, Linux)
- **DRM integration** (optional Steam DRM wrapper)

**Challenge**: Seamlessly integrate Steamworks without vendor lock-in for non-Steam builds.

### 3. **Code Signing & Notarization**

Modern platforms require signed executables:

| Platform | Requirement | Cost | Process |
|----------|------------|------|---------|
| macOS | Apple Developer cert | $99/year | Sign → Notarize → Staple |
| Windows | Code signing cert | $100-400/year | Sign with EV cert |
| Steam | Steam Partner account | One-time $100 | Upload builds via Steam Pipe |
| Linux | Optional GPG | Free | GPG sign packages |

**Challenge**: Manage certificates securely, automate signing in CI/CD.

### 4. **Native Service Management**

For web services, prefer **systemd** over containers:

**Benefits of systemd**:
- ✅ Native Linux integration (logs via journald)
- ✅ Automatic restarts, dependency management
- ✅ Resource limits (CPU, memory)
- ✅ Lower overhead than containers
- ✅ Better for Nix-managed deployments

**Challenge**: Generate systemd units that work across distributions.

---

## Architectural Patterns

### Pattern 1: Cathedral-Native Deployment (TempleDB → TempleDB)

**Use Case**: Transfer projects between TempleDB instances

**Flow**:
```
┌─────────────┐
│ Source TDB  │
│             │
│ 1. Export   │──────┐
│    cathedral│      │ .cathedral package
└─────────────┘      │ (deduplicated blobs)
                     │
                     ▼
              ┌─────────────┐
              │ Transfer    │
              │ (scp/rsync/ │
              │  S3)        │
              └─────────────┘
                     │
                     ▼
              ┌─────────────┐
              │ Target TDB  │
              │             │
              │ 2. Import   │
              │    cathedral│
              │             │
              │ 3. Build    │
              │    for      │
              │    platform │
              └─────────────┘
```

**Advantages**:
- ✅ Content deduplication (shared components stored once)
- ✅ VCS history preserved
- ✅ Deployment cache benefits
- ✅ Secrets managed by TempleDB on both ends

**Implementation**:
```bash
# Source system
templedb cathedral export bza --output /tmp/bza.cathedral --compress

# Transfer
scp /tmp/bza.cathedral build-server:/opt/cathedral/

# Build server (with TempleDB)
templedb cathedral import /opt/cathedral/bza.cathedral
templedb deploy build bza --target macos-appstore
templedb deploy build bza --target windows-store
templedb deploy build bza --target homebrew
```

### Pattern 2: Nix-Based Native Deployment

**Use Case**: Web services on Linux VPS

**Flow**:
```
┌─────────────┐
│ TempleDB    │
│             │
│ 1. Build    │
│    Nix      │
│    closure  │
└──────┬──────┘
       │
       │ Nix closure
       │ (all deps)
       │
       ▼
┌──────────────┐
│ Transfer to  │
│ target VPS   │
└──────┬───────┘
       │
       │
       ▼
┌──────────────┐
│ Import Nix   │
│ closure      │
│              │
│ Generate     │
│ systemd unit │
│              │
│ Enable &     │
│ start        │
└──────────────┘
```

**Advantages**:
- ✅ Reproducible (Nix pins all dependencies)
- ✅ No container overhead
- ✅ Native systemd integration
- ✅ Works on any Linux system

**Implementation**:
```bash
# Build Nix closure
templedb deploy package woofs_projects --format nix-closure --output ./dist/

# Transfer
scp -r ./dist/woofs_projects.closure deploy@vps:/opt/deployments/

# On VPS: Import and activate
nix-store --import < /opt/deployments/woofs_projects.closure/store.nar
templedb deploy activate woofs_projects --generate-systemd
```

### Pattern 3: Platform-Specific Build Matrix

**Use Case**: CLI tools for multiple platforms (bza)

**Flow**:
```
┌─────────────┐
│ TempleDB    │
│             │
│ Build       │
│ Matrix      │
└──────┬──────┘
       │
       │ Parallel builds
       │
   ┌───┴────────────────┬──────────────┬────────────┐
   ▼                    ▼              ▼            ▼
┌────────┐       ┌────────┐     ┌────────┐   ┌────────┐
│ macOS  │       │Windows │     │ Linux  │   │Homebrew│
│ .app   │       │ .exe   │     │ AppImg │   │formula │
│        │       │        │     │        │   │        │
│Sign +  │       │Sign    │     │        │   │        │
│Notarize│       │        │     │        │   │        │
└────┬───┘       └────┬───┘     └───┬────┘   └───┬────┘
     │                │             │            │
     │                │             │            │
     ▼                ▼             ▼            ▼
┌─────────┐      ┌─────────┐  ┌────────┐   ┌─────────┐
│App Store│      │MS Store │  │ Snap/  │   │brew tap │
│         │      │         │  │Flatpak │   │         │
└─────────┘      └─────────┘  └────────┘   └─────────┘
```

**Advantages**:
- ✅ Multi-platform support
- ✅ Native app store integration
- ✅ Automated code signing
- ✅ Versioned releases

---

## CLI Tools: App Store Deployment

### Overview

**CLI tools like `bza`** need to be distributed as:
1. **macOS App Store** - sandboxed .app bundle
2. **Windows Store** - MSIX package
3. **Homebrew** - macOS package manager
4. **Snap/Flatpak** - Linux universal packages
5. **Direct downloads** - standalone binaries

### Architecture

```
┌──────────────────────────────────────┐
│ bza CLI Tool                         │
│                                      │
│ - Python application                 │
│ - SQLite database (local state)      │
│ - API integrations (OpenRouter, etc) │
│ - Config management                  │
└──────────────────────────────────────┘
         │
         │ Build for each platform
         │
    ┌────┴──────────────┬──────────────┐
    ▼                   ▼              ▼
┌────────┐         ┌────────┐     ┌────────┐
│ macOS  │         │Windows │     │ Linux  │
└────────┘         └────────┘     └────────┘
```

### 1. macOS App Store Deployment

#### Prerequisites

- **Apple Developer Account** ($99/year)
- **Developer ID Application Certificate**
- **Mac with Xcode** (for code signing)

#### Build Process

**Step 1: Create .app Bundle**

```bash
# Generate .app bundle structure
templedb deploy package bza --format macos-app --output ./dist/

# Structure created:
# bza.app/
# ├── Contents/
# │   ├── Info.plist          # App metadata
# │   ├── MacOS/
# │   │   └── bza             # Executable
# │   ├── Resources/
# │   │   ├── icon.icns       # App icon
# │   │   └── assets/         # Bundled resources
# │   └── Frameworks/         # Python runtime, dependencies
```

**Step 2: Code Signing**

```bash
# Sign the app bundle
codesign --deep --force --verify --verbose \
  --sign "Developer ID Application: Your Name (TEAM_ID)" \
  --options runtime \
  --entitlements bza.entitlements \
  ./dist/bza.app

# bza.entitlements:
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.app-sandbox</key>
    <true/>
    <key>com.apple.security.network.client</key>
    <true/>
    <key>com.apple.security.files.user-selected.read-write</key>
    <true/>
</dict>
</plist>
```

**Step 3: Notarization**

```bash
# Create ZIP for notarization
ditto -c -k --keepParent ./dist/bza.app ./dist/bza.zip

# Submit to Apple for notarization
xcrun notarytool submit ./dist/bza.zip \
  --apple-id "you@example.com" \
  --team-id "TEAM_ID" \
  --password "app-specific-password" \
  --wait

# Staple notarization ticket
xcrun stapler staple ./dist/bza.app
```

**Step 4: Create Installer (.pkg)**

```bash
# Build installer package
productbuild --component ./dist/bza.app /Applications \
  --sign "Developer ID Installer: Your Name (TEAM_ID)" \
  ./dist/bza-installer.pkg
```

**Step 5: Upload to App Store**

```bash
# Use Transporter app or altool
xcrun altool --upload-app \
  --type macos \
  --file ./dist/bza-installer.pkg \
  --apple-id "you@example.com" \
  --password "app-specific-password"
```

#### TempleDB Automation

```bash
# All-in-one command
templedb deploy macos-appstore bza \
  --apple-id "you@example.com" \
  --team-id "TEAM_ID" \
  --certificate "Developer ID Application: Your Name" \
  --upload

# Internally:
# 1. Build .app bundle with Nix
# 2. Sign with codesign
# 3. Notarize with notarytool
# 4. Create .pkg installer
# 5. Upload to App Store
```

### 2. Windows Store Deployment

#### Prerequisites

- **Microsoft Partner Center Account** (Free)
- **Code Signing Certificate** (EV certificate, $100-400/year)

#### Build Process

**Step 1: Create MSIX Package**

```bash
# Generate MSIX package
templedb deploy package bza --format msix --output ./dist/

# Uses Windows SDK's makeappx tool
```

**MSIX Manifest** (`AppxManifest.xml`):
```xml
<?xml version="1.0" encoding="utf-8"?>
<Package xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10">
  <Identity Name="YourCompany.BZA"
            Publisher="CN=Your Name"
            Version="1.0.0.0" />
  <Properties>
    <DisplayName>BZA</DisplayName>
    <PublisherDisplayName>Your Company</PublisherDisplayName>
    <Logo>Assets\StoreLogo.png</Logo>
  </Properties>
  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" />
  </Dependencies>
  <Applications>
    <Application Id="BZA" Executable="bza.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="BZA"
                          Description="AI-powered CLI tool"
                          BackgroundColor="transparent"
                          Square150x150Logo="Assets\Square150x150Logo.png" />
    </Application>
  </Applications>
</Package>
```

**Step 2: Sign MSIX**

```bash
# Sign with EV certificate
signtool sign /fd SHA256 \
  /a /f certificate.pfx \
  /p "password" \
  ./dist/bza.msix
```

**Step 3: Upload to Microsoft Store**

```bash
# Use Partner Center web interface or Store Broker PowerShell
Import-Module StoreBroker
New-SubmissionPackage \
  -AppId "your-app-id" \
  -PackagePath "./dist/bza.msix"
```

#### TempleDB Automation

```bash
# All-in-one
templedb deploy windows-store bza \
  --publisher "CN=Your Name" \
  --certificate certificate.pfx \
  --upload

# Internally:
# 1. Build Windows .exe with Nix (cross-compilation) or PyInstaller
# 2. Create MSIX package
# 3. Sign with signtool
# 4. Upload to Partner Center
```

### 3. Homebrew Distribution

**Simplest distribution method for macOS developers**

#### Create Homebrew Formula

```bash
# Generate formula
templedb deploy package bza --format homebrew --output ./homebrew-bza/

# Creates: homebrew-bza/Formula/bza.rb
```

**Formula** (`bza.rb`):
```ruby
class Bza < Formula
  desc "AI-powered CLI tool for code generation"
  homepage "https://github.com/yourorg/bza"
  url "https://github.com/yourorg/bza/archive/v1.0.0.tar.gz"
  sha256 "abc123..."
  license "MIT"

  depends_on "python@3.11"

  def install
    virtualenv_install_with_resources
  end

  test do
    system "#{bin}/bza", "--version"
  end
end
```

#### Publish to Homebrew

```bash
# Option 1: Create tap (your own Homebrew repository)
templedb deploy homebrew bza --create-tap yourorg/homebrew-tap

# Users install via:
# brew tap yourorg/tap
# brew install bza

# Option 2: Submit to official Homebrew (requires approval)
templedb deploy homebrew bza --submit-official
```

### 4. Linux Distribution (Snap/Flatpak/AppImage)

#### Snap (Ubuntu, Fedora, Arch)

```bash
# Generate snapcraft.yaml
templedb deploy package bza --format snap --output ./snap/

# snapcraft.yaml:
name: bza
version: '1.0.0'
summary: AI-powered CLI tool
description: |
  BZA is an AI-powered CLI tool for code generation.

grade: stable
confinement: strict

apps:
  bza:
    command: bin/bza
    plugs: [home, network]

parts:
  bza:
    plugin: python
    source: .
    python-packages:
      - anthropic
      - requests

# Build and publish
snapcraft
snapcraft upload --release=stable bza_1.0.0_amd64.snap
```

#### Flatpak (Universal Linux)

```bash
# Generate flatpak manifest
templedb deploy package bza --format flatpak --output ./flatpak/

# com.yourorg.BZA.yml:
app-id: com.yourorg.BZA
runtime: org.freedesktop.Platform
runtime-version: '23.08'
sdk: org.freedesktop.Sdk
command: bza

modules:
  - name: bza
    buildsystem: simple
    build-commands:
      - pip3 install --prefix=/app .

# Build and publish
flatpak-builder build-dir com.yourorg.BZA.yml
flatpak build-export repo build-dir
# Submit to Flathub
```

#### AppImage (Self-contained)

```bash
# Generate AppImage
templedb deploy package bza --format appimage --output ./dist/

# Creates: bza-x86_64.AppImage (single-file executable)
chmod +x ./dist/bza-x86_64.AppImage

# Users run directly:
./bza-x86_64.AppImage
```

### Distribution Summary

```bash
# Generate all formats in parallel
templedb deploy build-matrix bza \
  --targets macos-app,windows-msix,homebrew,snap,flatpak,appimage \
  --output ./dist/

# Result:
# dist/
# ├── bza.app (macOS)
# ├── bza.msix (Windows)
# ├── homebrew-bza/ (Homebrew formula)
# ├── bza_1.0.0_amd64.snap (Snap)
# ├── bza.flatpak (Flatpak)
# └── bza-x86_64.AppImage (AppImage)

# Upload to release repositories
templedb deploy publish bza --all-targets
```

---

## Web Services: Native Systemd Deployment

### Overview

**Web services like `woofs_projects`** deploy as:
1. **Backend**: systemd service (FastAPI/Express) with Nix dependencies
2. **Frontend**: Static site on Vercel/Netlify
3. **Database**: PostgreSQL/Supabase

**No Docker** - Use native systemd for better performance and simpler debugging.

### Architecture

```
┌──────────────────────────────────────┐
│ Frontend (Next.js/React)             │
│ - Static generation or SSR           │
│ - Deployed to Vercel/Netlify         │
└─────────────┬────────────────────────┘
              │ API calls
              │
              ▼
┌──────────────────────────────────────┐
│ Backend (FastAPI/Express)            │
│ - systemd service                    │
│ - Nix-managed dependencies           │
│ - Reverse proxy (Caddy/Nginx)        │
└─────────────┬────────────────────────┘
              │ SQL queries
              │
              ▼
┌──────────────────────────────────────┐
│ Database (PostgreSQL/Supabase)       │
│ - Managed service or self-hosted     │
└──────────────────────────────────────┘
```

### Backend Deployment

#### Step 1: Build Nix Closure

**Build with Nix**:
```bash
# Generate Nix closure with all dependencies
templedb deploy package woofs_projects --format nix-closure --output ./dist/

# Nix flake (auto-generated):
{
  description = "Woofs Projects Backend";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }: {
    packages.x86_64-linux.default =
      let pkgs = nixpkgs.legacyPackages.x86_64-linux;
      in pkgs.python311Packages.buildPythonApplication {
        pname = "woofs-backend";
        version = "1.0.0";
        src = ./.;

        propagatedBuildInputs = with pkgs.python311Packages; [
          fastapi
          uvicorn
          sqlalchemy
          psycopg2
        ];
      };
  };
}

# Build
nix build

# Export closure
nix-store --export $(nix-store -qR ./result) > woofs-backend.nar
```

#### Step 2: Transfer to VPS

```bash
# Transfer Nix closure
scp ./dist/woofs-backend.nar deploy@vps:/opt/deployments/

# On VPS: Import
nix-store --import < /opt/deployments/woofs-backend.nar
```

#### Step 3: Generate systemd Unit

**Generated by TempleDB**:
```ini
# /etc/systemd/system/woofs-backend.service
[Unit]
Description=Woofs Projects Backend
After=network.target postgresql.service
Wants=postgresql.service

[Service]
Type=notify
User=woofs
Group=woofs
WorkingDirectory=/opt/woofs-backend

# Load secrets from TempleDB-generated file
EnvironmentFile=/etc/woofs/secrets.env

# Run via Nix (reproducible)
ExecStart=/nix/store/...-woofs-backend/bin/uvicorn main:app --host 0.0.0.0 --port 8000

# Restart policy
Restart=always
RestartSec=10

# Resource limits
MemoryMax=1G
CPUQuota=200%

# Security hardening
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/var/lib/woofs

[Install]
WantedBy=multi-user.target
```

**Activate**:
```bash
# On VPS
sudo systemctl daemon-reload
sudo systemctl enable woofs-backend
sudo systemctl start woofs-backend

# Check logs
journalctl -u woofs-backend -f
```

#### TempleDB Automation

```bash
# Full backend deployment
templedb deploy run woofs_projects --target production-vps

# Internally:
# 1. Build Nix closure
# 2. Transfer via scp
# 3. Import on VPS
# 4. Generate systemd unit
# 5. Inject secrets to /etc/woofs/secrets.env
# 6. Enable and start service
# 7. Run health check (curl http://localhost:8000/health)
```

### Frontend Deployment (Vercel)

```bash
# Deploy frontend to Vercel
templedb deploy vercel woofs_projects --frontend-only --sync-secrets

# Internally:
# 1. cd frontend/
# 2. npm run build
# 3. Sync TempleDB secrets to Vercel environment variables
# 4. vercel deploy --prod
```

### Database Migration

```bash
# Apply migrations on production database
templedb migration apply woofs_projects --target production

# Internally runs:
# 1. Connect to DATABASE_URL (from TempleDB secrets)
# 2. Run pending migrations from migrations/
# 3. Update deployment_targets table with migration status
```

### Reverse Proxy (Caddy - recommended)

**Caddyfile** (auto-generated):
```
woofs.example.com {
    reverse_proxy localhost:8000

    # Automatic HTTPS
    tls {
        protocols tls1.3
    }

    # Logging
    log {
        output file /var/log/caddy/woofs.log
    }
}
```

**Or Nginx**:
```nginx
server {
    listen 443 ssl http2;
    server_name woofs.example.com;

    ssl_certificate /etc/letsencrypt/live/woofs.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/woofs.example.com/privkey.pem;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## Games: Steam Deployment

### Overview

**Games** need to integrate with:
1. **Steamworks SDK** - Achievements, cloud saves, multiplayer, Steam overlay
2. **Steam Depot System** - Content delivery (game files, updates)
3. **Steam Pipe** - Build upload tool
4. **Platform-specific builds** - Windows, macOS, Linux

### Steam Integration Architecture

```
┌──────────────────────────────────────┐
│ Game Client                          │
│                                      │
│ - Game engine (Unity/Godot/Custom)   │
│ - Steamworks API integration         │
│   * Achievements                     │
│   * Cloud saves                      │
│   * Steam friends                    │
│   * Leaderboards                     │
│   * Workshop (mods)                  │
└─────────────┬────────────────────────┘
              │
              │ Steam API calls
              │
              ▼
┌──────────────────────────────────────┐
│ Steamworks SDK                       │
│ - steam_api.dll (Windows)            │
│ - libsteam_api.so (Linux)            │
│ - libsteam_api.dylib (macOS)         │
└─────────────┬────────────────────────┘
              │
              │ Connect to Steam
              │
              ▼
┌──────────────────────────────────────┐
│ Steam Client (on player's PC)       │
│ - Authentication                     │
│ - Cloud storage                      │
│ - Social features                    │
└──────────────────────────────────────┘
```

### Steamworks SDK Integration

#### Prerequisites

1. **Steam Partner Account** ($100 one-time fee)
2. **Steamworks SDK** (download from partner.steamgames.com)
3. **App ID** (assigned by Steam)

#### Step 1: Integrate Steamworks SDK

**For Python/Pygame game**:
```python
# Install steamworks wrapper
# pip install steamworks

from steamworks import STEAMWORKS

# Initialize Steam API
if not STEAMWORKS.initialize():
    print("Failed to initialize Steam API")
    exit(1)

# Get player info
player_name = STEAMWORKS.Users.GetPersonaName()
steam_id = STEAMWORKS.Users.GetSteamID()

# Unlock achievement
STEAMWORKS.UserStats.SetAchievement("FIRST_WIN")
STEAMWORKS.UserStats.StoreStats()

# Save to Steam Cloud
STEAMWORKS.RemoteStorage.FileWrite("save_game.dat", save_data)

# Shutdown when game exits
STEAMWORKS.shutdown()
```

**For JavaScript/Electron game**:
```javascript
// Use greenworks (Steamworks for Node.js)
const greenworks = require('greenworks');

if (!greenworks.init()) {
  console.error('Failed to initialize Steamworks');
  process.exit(1);
}

// Get player info
const steamId = greenworks.getSteamId();
const playerName = greenworks.getSteamId().getPersonaName();

// Unlock achievement
greenworks.activateAchievement('FIRST_WIN', () => {
  console.log('Achievement unlocked!');
});

// Save to Steam Cloud
greenworks.saveTextToFile('save_game.json', JSON.stringify(saveData), () => {
  console.log('Saved to Steam Cloud');
});
```

#### Step 2: Configure steam_appid.txt

**For local development** (bypasses Steam client requirement):
```bash
# Create steam_appid.txt in game directory
echo "480" > steam_appid.txt  # 480 = Spacewar (Steam's test app)

# For your actual game, use your App ID
echo "123456" > steam_appid.txt
```

#### Step 3: Build Platform-Specific Binaries

**Windows Build**:
```bash
# Build Windows .exe
templedb deploy package mygame --platform windows --output ./dist/windows/

# Include Steamworks DLL
cp steamworks/sdk/redistributable_bin/win64/steam_api64.dll ./dist/windows/

# Result: mygame.exe + steam_api64.dll
```

**macOS Build**:
```bash
# Build macOS .app bundle
templedb deploy package mygame --platform macos --output ./dist/macos/

# Include Steamworks dylib
cp steamworks/sdk/redistributable_bin/osx/libsteam_api.dylib \
   ./dist/macos/mygame.app/Contents/Frameworks/

# Code sign (required for macOS)
codesign --deep --force --verify \
  --sign "Developer ID Application: Your Name" \
  ./dist/macos/mygame.app
```

**Linux Build**:
```bash
# Build Linux binary
templedb deploy package mygame --platform linux --output ./dist/linux/

# Include Steamworks .so
cp steamworks/sdk/redistributable_bin/linux64/libsteam_api.so ./dist/linux/

# Result: mygame + libsteam_api.so
```

### Steam Depot Configuration

**Depot structure** (how Steam organizes your game files):

```
depots/
├── 123457/  # Windows depot
│   ├── mygame.exe
│   ├── steam_api64.dll
│   ├── assets/
│   │   ├── textures/
│   │   ├── audio/
│   │   └── models/
│   └── data/
│
├── 123458/  # macOS depot
│   └── mygame.app/
│       └── Contents/
│           ├── MacOS/mygame
│           ├── Frameworks/libsteam_api.dylib
│           └── Resources/assets/
│
└── 123459/  # Linux depot
    ├── mygame
    ├── libsteam_api.so
    └── assets/ (symlink or shared depot)
```

**TempleDB generates depot manifest**:

```vdf
# depot_build_123457.vdf (Windows)
"DepotBuildConfig"
{
  "DepotID" "123457"
  "ContentRoot" "dist/windows"
  "FileMapping"
  {
    "LocalPath" "*"
    "DepotPath" "."
    "recursive" "1"
  }
}
```

### Steam Build Upload (Steam Pipe)

#### app_build.vdf Configuration

**Generated by TempleDB**:
```vdf
"AppBuild"
{
  "AppID" "123456"
  "Desc" "MyGame v1.0.0 - Initial release"
  "BuildOutput" "builds/"
  "ContentRoot" "dist/"
  "SetLive" "default"  # Default branch (public)

  "Depots"
  {
    "123457"  # Windows depot
    {
      "FileMapping"
      {
        "LocalPath" "windows/*"
        "DepotPath" "."
        "recursive" "1"
      }
    }

    "123458"  # macOS depot
    {
      "FileMapping"
      {
        "LocalPath" "macos/*"
        "DepotPath" "."
        "recursive" "1"
      }
    }

    "123459"  # Linux depot
    {
      "FileMapping"
      {
        "LocalPath" "linux/*"
        "DepotPath" "."
        "recursive" "1"
      }
    }
  }
}
```

#### Upload to Steam

```bash
# Login to Steam (one-time)
steamcmd +login yourusername

# Build and upload
templedb deploy steam mygame \
  --app-id 123456 \
  --branch default \
  --description "v1.0.0 - Initial release"

# Internally runs:
# 1. Build Windows, macOS, Linux versions
# 2. Generate depot manifests
# 3. Run steamcmd:
#    steamcmd +login yourusername \
#             +run_app_build app_build_123456.vdf \
#             +quit
```

### Steam Achievements Configuration

**achievements.json** (parsed by TempleDB):
```json
{
  "achievements": [
    {
      "id": "FIRST_WIN",
      "name": "First Victory",
      "description": "Win your first match",
      "icon": "achievements/first_win.png",
      "hidden": false
    },
    {
      "id": "SPEEDRUN",
      "name": "Speed Demon",
      "description": "Complete the game in under 1 hour",
      "icon": "achievements/speedrun.png",
      "hidden": false
    }
  ]
}
```

**Upload to Steamworks**:
```bash
# Generate Steamworks achievement config
templedb steam upload-achievements mygame --from achievements.json

# Manually: Upload via Steamworks Partner portal
# Settings → Stats & Achievements → Configure achievements
```

### Steam Cloud Saves

**Enable in Steamworks**:
```bash
# Configure cloud storage quota (Settings → Cloud)
# Quota: 100 MB per user (default)
```

**In-game integration**:
```python
# Save game state to Steam Cloud
def save_game(player_data):
    import json
    data = json.dumps(player_data)

    # Save locally (fallback)
    with open('save_game.json', 'w') as f:
        f.write(data)

    # Save to Steam Cloud (if available)
    try:
        if STEAMWORKS.RemoteStorage.FileWrite("save_game.json", data.encode()):
            print("Saved to Steam Cloud")
    except:
        print("Steam Cloud save failed, saved locally only")

# Load from Steam Cloud
def load_game():
    try:
        if STEAMWORKS.RemoteStorage.FileExists("save_game.json"):
            data = STEAMWORKS.RemoteStorage.FileRead("save_game.json")
            return json.loads(data.decode())
    except:
        pass

    # Fallback to local save
    if os.path.exists('save_game.json'):
        with open('save_game.json') as f:
            return json.load(f)

    return None
```

### Steam Workshop Support (Mods)

**Enable Workshop in Steamworks**:
```bash
# Settings → Workshop → Enable
```

**In-game integration** (allow players to upload mods):
```python
from steamworks import STEAMWORKS

def upload_mod(mod_directory):
    """Upload mod to Steam Workshop"""

    # Create workshop item
    result = STEAMWORKS.UGC.CreateItem(
        app_id=123456,
        file_type=STEAMWORKS.EWorkshopFileType.k_EWorkshopFileTypeCommunity
    )

    if result:
        item_id = result.m_nPublishedFileId

        # Set mod metadata
        update_handle = STEAMWORKS.UGC.StartItemUpdate(123456, item_id)
        STEAMWORKS.UGC.SetItemTitle(update_handle, "My Custom Mod")
        STEAMWORKS.UGC.SetItemDescription(update_handle, "A cool mod")
        STEAMWORKS.UGC.SetItemContent(update_handle, mod_directory)
        STEAMWORKS.UGC.SetItemPreview(update_handle, "preview.png")
        STEAMWORKS.UGC.SetItemVisibility(update_handle,
            STEAMWORKS.ERemoteStoragePublishedFileVisibility.k_ERemoteStoragePublishedFileVisibilityPublic
        )

        # Submit
        STEAMWORKS.UGC.SubmitItemUpdate(update_handle, "Initial upload")
```

### Complete Steam Deployment Workflow

```bash
# 1. Initialize Steam integration
templedb steam init mygame --app-id 123456

# 2. Add Steamworks SDK to project
# Downloads and integrates steam_api for each platform

# 3. Build all platform versions
templedb deploy build-matrix mygame \
  --platforms windows,macos,linux \
  --output ./dist/

# 4. Test locally (uses Spacewar test app)
templedb steam test mygame

# 5. Upload to Steam (requires Steam Partner account)
templedb deploy steam mygame \
  --branch beta \
  --description "Beta v0.9.0"

# 6. Promote beta to live
templedb steam promote mygame --from beta --to default

# 7. Update achievements
templedb steam upload-achievements mygame --from achievements.json
```

### Fallback: Itch.io Distribution

**For games not yet on Steam or as secondary distribution**:

```bash
# Build Itch.io version (no Steamworks SDK)
templedb deploy package mygame --format itch --output ./itch-build/

# Creates:
# itch-build/
# ├── windows/mygame-windows.zip
# ├── macos/mygame-macos.zip
# └── linux/mygame-linux.tar.gz

# Upload to Itch.io
templedb deploy itch mygame \
  --itch-user yourusername \
  --game mygame \
  --upload

# Uses butler (Itch.io's upload tool):
# butler push ./itch-build/windows yourusername/mygame:windows
# butler push ./itch-build/macos yourusername/mygame:macos
# butler push ./itch-build/linux yourusername/mygame:linux
```

---

## Secret Management & Fallback Strategies

### Multi-Layer Secret Resolution

**Priority chain** (same as v1):

```
1. TempleDB Secrets (production, encrypted with age)
   ↓
2. Environment Variables (CI/CD, systemd)
   ↓
3. .env File (local development)
   ↓
4. Config File (~/.config/app/config.json)
   ↓
5. Interactive Prompt (CLI tools only)
   ↓
6. Error with clear instructions
```

### Implementation

**Python** (`common/secrets.py`):
```python
from pathlib import Path
import os
import json
import subprocess
from typing import Optional

def get_secret(key: str, project: Optional[str] = None, interactive: bool = False) -> str:
    """
    Get secret with fallback chain.

    Args:
        key: Secret key name
        project: Project name (for TempleDB lookup)
        interactive: Allow interactive prompt (CLI tools only)
    """
    # 1. TempleDB
    if project:
        try:
            result = subprocess.run(
                ['templedb', 'secret', 'get', project, key],
                capture_output=True,
                text=True,
                check=True
            )
            if result.stdout.strip():
                return result.stdout.strip()
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    # 2. Environment variable
    if value := os.getenv(key):
        return value

    # 3. .env file
    env_file = Path.cwd() / '.env'
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith(f'{key}='):
                return line.split('=', 1)[1].strip().strip('"\'')

    # 4. Config file
    config_file = Path.home() / '.config' / (project or 'app') / 'config.json'
    if config_file.exists():
        config = json.loads(config_file.read_text())
        if key in config:
            return config[key]

    # 5. Interactive prompt (CLI tools only)
    if interactive:
        import getpass
        value = getpass.getpass(f"Enter {key}: ")
        if value:
            return value

    # 6. Error
    raise ValueError(
        f"Secret '{key}' not found. Set it via:\n"
        f"  • TempleDB: templedb secret set {project or 'PROJECT'} {key} VALUE\n"
        f"  • Environment: export {key}=VALUE\n"
        f"  • File: echo '{key}=VALUE' >> .env\n"
        f"  • Config: ~/.config/{project or 'app'}/config.json"
    )
```

**JavaScript** (`lib/secrets.js`):
```javascript
import { readFileSync, existsSync } from 'fs';
import { homedir } from 'os';
import { join } from 'path';
import { execSync } from 'child_process';
import readline from 'readline';

export async function getSecret(key, project = null, interactive = false) {
  // 1. TempleDB
  if (project) {
    try {
      const result = execSync(
        `templedb secret get ${project} ${key}`,
        { encoding: 'utf-8', stdio: 'pipe' }
      );
      if (result.trim()) return result.trim();
    } catch {}
  }

  // 2. Environment variable
  if (process.env[key]) return process.env[key];

  // 3. .env file
  const envFile = join(process.cwd(), '.env');
  if (existsSync(envFile)) {
    const line = readFileSync(envFile, 'utf-8')
      .split('\n')
      .find(l => l.startsWith(`${key}=`));
    if (line) return line.split('=')[1].trim().replace(/['"]/g, '');
  }

  // 4. Config file
  const configFile = join(homedir(), '.config', project || 'app', 'config.json');
  if (existsSync(configFile)) {
    const config = JSON.parse(readFileSync(configFile, 'utf-8'));
    if (config[key]) return config[key];
  }

  // 5. Interactive prompt
  if (interactive) {
    const rl = readline.createInterface({
      input: process.stdin,
      output: process.stdout
    });

    return new Promise(resolve => {
      rl.question(`Enter ${key}: `, answer => {
        rl.close();
        if (answer) resolve(answer);
        else throw new Error('No value provided');
      });
    });
  }

  // 6. Error
  throw new Error(
    `Secret '${key}' not found. Set it via:\n` +
    `  • TempleDB: templedb secret set ${project || 'PROJECT'} ${key} VALUE\n` +
    `  • Environment: export ${key}=VALUE\n` +
    `  • File: echo '${key}=VALUE' >> .env\n` +
    `  • Config: ~/.config/${project || 'app'}/config.json`
  );
}
```

### Platform-Specific Secret Injection

**macOS App Store** (Keychain):
```python
# Store Steam API key in Keychain
import keyring

def get_steam_api_key():
    # Try Keychain first (macOS App Store requirement)
    if sys.platform == 'darwin':
        try:
            return keyring.get_password('bza', 'steam_api_key')
        except:
            pass

    # Fall back to standard secret chain
    return get_secret('STEAM_API_KEY', project='bza')
```

**Windows Store** (Credential Manager):
```python
# Store API key in Windows Credential Manager
import keyring

def get_api_key():
    if sys.platform == 'win32':
        try:
            return keyring.get_password('bza', 'api_key')
        except:
            pass

    return get_secret('API_KEY', project='bza')
```

**Steam** (Steam Cloud config):
```python
# Store non-sensitive config in Steam Cloud
def get_user_preferences():
    try:
        if STEAMWORKS.RemoteStorage.FileExists("user_prefs.json"):
            data = STEAMWORKS.RemoteStorage.FileRead("user_prefs.json")
            return json.loads(data.decode())
    except:
        pass

    # Default preferences
    return {
        'theme': 'dark',
        'notifications': True
    }
```

---

## Cathedral Integration

### Cathedral Package Format

**Enhanced for platform-specific builds**:

```
myproject.cathedral
├── manifest.json          # Project metadata
├── blobs/                 # Content-addressed blobs
│   ├── a3f5e2... (zlib)
│   └── b8c1d9... (zlib)
├── vcs/                   # VCS history
│   ├── commits.json
│   └── branches.json
├── builds/                # Platform-specific builds (NEW)
│   ├── windows/
│   │   └── metadata.json  # Build hashes, not full binaries
│   ├── macos/
│   └── linux/
├── steamworks/            # Steam integration (NEW)
│   ├── app_id.txt
│   ├── achievements.json
│   └── depots.vdf
└── environments/
    ├── development.json
    └── production.json
```

### Cathedral Workflow for Multi-Platform Builds

```bash
# Export project with build artifacts
templedb cathedral export mygame \
  --include-builds windows,macos,linux \
  --output /tmp/mygame.cathedral

# Transfer to build server (with TempleDB)
scp /tmp/mygame.cathedral build-server:/opt/cathedral/

# Import and rebuild for Steam
templedb cathedral import /opt/cathedral/mygame.cathedral
templedb deploy steam mygame --app-id 123456
```

### Cathedral Benefits

1. **Deduplication**: Shared assets (textures, audio) stored once across builds
2. **VCS Preservation**: Full git history available on build server
3. **Build Metadata**: Track which commits produced which builds
4. **Deployment Cache**: Reuse builds if source code unchanged

---

## Comparison Matrices

### Deployment Strategy Comparison (Updated)

| Strategy | Target Requirements | Artifact Size | Reproducibility | Setup Complexity | Best For |
|----------|-------------------|---------------|-----------------|------------------|----------|
| **Cathedral** | TempleDB | Small (dedup) | ⭐⭐⭐⭐⭐ | Medium | TDB → TDB |
| **Nix Closure** | Nix | Medium | ⭐⭐⭐⭐⭐ | Medium | VPS, systemd |
| **Systemd Service** | systemd + Nix | Small | ⭐⭐⭐⭐⭐ | Medium | Web services |
| **macOS App** | macOS | Medium | ⭐⭐⭐⭐ | High | CLI tools |
| **Windows MSIX** | Windows 10+ | Medium | ⭐⭐⭐⭐ | High | CLI tools |
| **Steam** | Steam client | Large | ⭐⭐⭐⭐ | High | Games |
| **Homebrew** | macOS + brew | Small | ⭐⭐⭐⭐ | Low | CLI tools |
| **Snap/Flatpak** | Linux | Large | ⭐⭐⭐ | Medium | CLI tools |

**Docker removed** from recommendations.

### Project Type Deployment Matrix (Updated)

| Project Type | Primary Deployment | Secondary Options | Distribution Channels |
|-------------|-------------------|-------------------|---------------------|
| **CLI Tools** | Homebrew, Snap | macOS App Store, Windows Store, Nix | brew, snap, App Stores |
| **Web Services** | systemd + Nix | Vercel (frontend), Netlify | VPS, Cloud |
| **Games (single-player)** | Steam | Itch.io, direct download | Steam, Itch.io, website |
| **Games (multiplayer)** | Steam (client) + systemd (server) | Itch.io + VPS | Steam, Itch.io |

### Distribution Channel Comparison

| Channel | Reach | Revenue Split | Review Process | Update Speed | Best For |
|---------|-------|--------------|----------------|--------------|----------|
| **Steam** | 120M+ users | 30% (70% to dev) | Yes (1-5 days) | Instant | Games |
| **macOS App Store** | 1B+ devices | 30% | Yes (1-7 days) | 1-2 days | CLI tools, apps |
| **Windows Store** | 1B+ devices | 15% | Yes (1-3 days) | Instant | CLI tools, apps |
| **Homebrew** | Developers | 0% | Community PR | Instant | CLI tools |
| **Snap Store** | Ubuntu users | 0% | Auto (if classic) | Instant | CLI tools |
| **Itch.io** | Indie gamers | 10% (or 0%) | No | Instant | Indie games |

---

## Implementation Roadmap

### Phase 1: Core Native Deployment (Week 1-2)

**Goal**: systemd + Nix deployment for web services

Tasks:
1. ✅ **Nix Closure Generation**
   - `templedb deploy package <project> --format nix-closure`
   - Export Nix store paths

2. ✅ **systemd Unit Generator**
   - Generate .service files with EnvironmentFile
   - Security hardening (NoNewPrivileges, ProtectSystem)
   - Resource limits (MemoryMax, CPUQuota)

3. ✅ **Deployment Orchestration**
   - Transfer Nix closure to VPS
   - Import and activate
   - Health checks

**Deliverables**:
- [ ] `src/services/nix_deployment_service.py`
- [ ] `templates/systemd.service.jinja2`
- [ ] `templedb deploy run <project> --target vps`

### Phase 2: CLI Tool App Store Distribution (Week 3-4)

**Goal**: Publish `bza` to macOS App Store, Windows Store, Homebrew

Tasks:
1. ✅ **macOS App Bundle**
   - Generate .app structure
   - Code signing automation
   - Notarization pipeline

2. ✅ **Windows MSIX**
   - Generate MSIX package
   - Code signing with EV certificate

3. ✅ **Homebrew Formula**
   - Generate .rb formula
   - Create tap repository

4. ✅ **Snap/Flatpak**
   - Generate snapcraft.yaml
   - Generate Flatpak manifest

**Deliverables**:
- [ ] `templedb deploy macos-app bza --sign --notarize --upload`
- [ ] `templedb deploy windows-msix bza --sign --upload`
- [ ] `templedb deploy homebrew bza --create-tap`
- [ ] `templedb deploy snap bza --upload`

### Phase 3: Steam Integration (Week 5-6)

**Goal**: Deploy games to Steam with Steamworks integration

Tasks:
1. ✅ **Steamworks SDK Integration**
   - Download and integrate steam_api
   - Platform-specific builds (Windows, macOS, Linux)

2. ✅ **Steam Depot Configuration**
   - Generate depot manifests (.vdf)
   - Multi-platform depot management

3. ✅ **Steam Pipe Upload**
   - Automate steamcmd builds
   - Branch management (beta, default)

4. ✅ **Achievement & Cloud Save Config**
   - Parse achievements.json
   - Generate Steamworks config

**Deliverables**:
- [ ] `templedb steam init <game> --app-id <id>`
- [ ] `templedb deploy steam <game> --branch beta`
- [ ] `templedb steam upload-achievements <game>`
- [ ] Steam Workshop integration

### Phase 4: Secret Management Enhancement (Week 7)

**Goal**: Platform-specific secret storage

Tasks:
1. ✅ **macOS Keychain Integration**
   - Store secrets in Keychain (App Store requirement)

2. ✅ **Windows Credential Manager**
   - Store secrets in Credential Manager

3. ✅ **Steam Cloud Config**
   - Store user preferences in Steam Cloud

**Deliverables**:
- [ ] Platform-specific secret storage helpers
- [ ] `get_secret()` with platform detection

### Phase 5: CI/CD & Automation (Week 8+)

**Goal**: Automated builds and deployments

Tasks:
1. ✅ **GitHub Actions Templates**
   - Multi-platform build matrix
   - Code signing in CI
   - Automated Steam uploads

2. ✅ **Build Caching**
   - Cache Nix store paths
   - Cache platform-specific dependencies

3. ✅ **Release Automation**
   - Tag-based releases
   - Changelog generation
   - Multi-channel publishing (Steam, App Stores, Homebrew)

**Deliverables**:
- [ ] `.github/workflows/deploy.yml` template
- [ ] `templedb deploy init-ci <project> --provider github`

---

## Conclusion

This architectural review establishes a **native-first deployment framework** for TempleDB-managed projects:

### Key Principles

1. **Native Platform Integration**: App Stores for CLI tools, Steam for games, systemd for services
2. **No Docker Dependency**: Nix + systemd provides better reproducibility and performance
3. **Comprehensive Secret Management**: 5-layer fallback with platform-specific storage
4. **Cathedral Optimization**: Leverage TempleDB infrastructure when available
5. **Multi-Platform Support**: Automated builds for Windows, macOS, Linux

### Success Metrics

- [ ] Deploy `bza` to macOS App Store
- [ ] Deploy `bza` to Homebrew with `brew install bza`
- [ ] Deploy `woofs_projects` as systemd service with <5 min setup
- [ ] Deploy a game to Steam with achievements and cloud saves
- [ ] 100% secret fallback coverage (no hardcoded credentials)
- [ ] Automated multi-platform builds in CI/CD

---

**Document Status**: Ready for Implementation
**Author**: TempleDB Architecture Team
**Last Updated**: 2026-03-21
