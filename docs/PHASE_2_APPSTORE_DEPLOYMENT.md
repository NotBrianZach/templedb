# Phase 2: App Store Deployment (IMPLEMENTED)

**Status**: ✅ Complete
**Date**: 2026-03-21

## Overview

Phase 2 implements distribution for CLI tools (bza archetype) to **app stores and package managers**:

- ✅ **Homebrew** - macOS/Linux package manager (easiest, free)
- ✅ **Snap** - Universal Linux packages
- ✅ **macOS App Store** - .app bundles with code signing and notarization
- 🚧 **Windows Store** - MSIX packages (Phase 3)

---

## Commands

### 1. `deploy-appstore homebrew` - Homebrew Formula

Generate a Homebrew formula for your CLI tool.

**Usage**:
```bash
templedb deploy-appstore homebrew <project-slug> \
  --version 1.0.0 \
  --description "AI-powered CLI tool" \
  --homepage https://github.com/yourorg/bza \
  --tarball-url https://github.com/yourorg/bza/archive/v1.0.0.tar.gz \
  --sha256 abc123... \
  --org yourorg \
  [--publish]
```

**Example**:
```bash
# Generate formula (dry run)
templedb deploy-appstore homebrew bza \
  --version 1.0.0 \
  --description "AI-powered code generation CLI" \
  --homepage https://github.com/yourorg/bza \
  --tarball-url https://github.com/yourorg/bza/archive/v1.0.0.tar.gz \
  --sha256 $(sha256sum bza-1.0.0.tar.gz | cut -d' ' -f1) \
  --org yourorg

# Output:
# 🍺 Generating Homebrew formula for bza...
#
# ✅ Homebrew tap created at /tmp/templedb-appstore/yourorg-homebrew-tap
#
# 📦 Tap location: /tmp/templedb-appstore/yourorg-homebrew-tap
#
# 📋 Formula preview:
# ======================================================================
# class Bza < Formula
#   desc "AI-powered code generation CLI"
#   homepage "https://github.com/yourorg/bza"
#   url "https://github.com/yourorg/bza/archive/v1.0.0.tar.gz"
#   sha256 "abc123..."
#   license "MIT"
#
#   def install
#     virtualenv_install_with_resources
#   end
#
#   test do
#     system "#{bin}/bza", "--version"
#   end
# end
# ======================================================================
#
# 💡 Next steps:
#    1. Review the formula
#    2. Create GitHub repo: gh repo create yourorg/homebrew-tap
#    3. Push: cd /tmp/templedb-appstore/yourorg-homebrew-tap && git init && ...
#
#    Or use --publish flag to publish automatically
```

**With --publish flag** (auto-publish to GitHub):
```bash
templedb deploy-appstore homebrew bza \
  --version 1.0.0 \
  --description "AI-powered code generation CLI" \
  --homepage https://github.com/yourorg/bza \
  --tarball-url https://github.com/yourorg/bza/archive/v1.0.0.tar.gz \
  --sha256 abc123... \
  --org yourorg \
  --publish

# Requires: gh (GitHub CLI) installed and authenticated

# Output:
# ✅ Homebrew tap created...
# 🚀 Publishing to GitHub...
# ✅ Tap published to https://github.com/yourorg/homebrew-tap
#
# 🌐 Tap URL: https://github.com/yourorg/homebrew-tap
#
# 📥 Users can install via:
#    brew tap yourorg/tap
#    brew install bza
```

---

### 2. `deploy-appstore snap` - Snap Package (Linux)

Build a Snap package for universal Linux distribution.

**Usage**:
```bash
templedb deploy-appstore snap <project-slug> \
  --version 1.0.0 \
  --summary "AI-powered CLI tool" \
  --description "Detailed description..." \
  [--publish] \
  [--channel stable]
```

**Example**:
```bash
# Build Snap package
templedb deploy-appstore snap bza \
  --version 1.0.0 \
  --summary "AI-powered code generation CLI" \
  --description "Generate code using AI models"

# Output:
# 📦 Building Snap package for bza...
#
# 📋 snapcraft.yaml:
# ======================================================================
# name: bza
# version: '1.0.0'
# summary: AI-powered code generation CLI
# description: |
#   Generate code using AI models
#
# grade: stable
# confinement: strict
# base: core22
#
# apps:
#   bza:
#     command: bin/bza
#     plugs:
#       - home
#       - network
#       - network-bind
#
# parts:
#   bza:
#     plugin: python
#     source: .
#     python-packages:
#
# ======================================================================
#
# 🔨 Building Snap...
# ✅ Snap package built successfully
#
# 📦 Snap package: /path/to/bza_1.0.0_amd64.snap
#
# 💡 To publish:
#    snapcraft login
#    snapcraft upload --release=stable /path/to/bza_1.0.0_amd64.snap
#
#    Or use --publish flag
```

**With --publish flag**:
```bash
templedb deploy-appstore snap bza \
  --version 1.0.0 \
  --summary "AI-powered code generation CLI" \
  --publish \
  --channel stable

# Requires: snapcraft login

# Output:
# ✅ Snap package built successfully
# 🚀 Publishing to Snap Store...
# ✅ Snap published to stable channel
#
# 🌐 Store URL: https://snapcraft.io/bza
#
# 📥 Users can install via:
#    snap install bza
```

---

### 3. `deploy-appstore macos` - macOS .app Bundle

Create a macOS .app bundle with optional code signing and notarization.

**Usage**:
```bash
templedb deploy-appstore macos <project-slug> \
  --executable /path/to/bza \
  --version 1.0.0 \
  --name "BZA" \
  [--icon /path/to/icon.icns] \
  [--bundle-id com.yourcompany.bza] \
  [--sign] \
  [--signing-identity "Developer ID Application: Your Name"] \
  [--notarize] \
  [--apple-id you@example.com] \
  [--team-id TEAM_ID] \
  [--password app-specific-password]
```

**Example (Create .app bundle)**:
```bash
# Build executable first (e.g., with PyInstaller)
pyinstaller --onefile bza.py

# Create .app bundle
templedb deploy-appstore macos bza \
  --executable dist/bza \
  --version 1.0.0 \
  --name "BZA" \
  --icon assets/icon.icns \
  --bundle-id com.templedb.bza

# Output:
# 🍎 Creating macOS app bundle for bza...
#
# ✅ macOS app bundle created
#
# 📦 App bundle: /tmp/templedb-appstore/BZA.app
#
# 💡 Next steps:
#    1. Sign: templedb deploy-appstore macos bza --sign --signing-identity 'Developer ID'
#    2. Notarize: Add --notarize --apple-id ... --team-id ... --password ...
#    3. Distribute .app bundle or create installer
```

**Example (with code signing)**:
```bash
templedb deploy-appstore macos bza \
  --executable dist/bza \
  --version 1.0.0 \
  --sign \
  --signing-identity "Developer ID Application: Your Name (TEAM_ID)"

# Output:
# 🍎 Creating macOS app bundle for bza...
# ✅ macOS app bundle created
#
# ✍️  Signing app bundle...
# ✅ App bundle signed successfully
#
# 📦 App bundle: /tmp/templedb-appstore/BZA.app
```

**Example (with notarization)**:
```bash
templedb deploy-appstore macos bza \
  --executable dist/bza \
  --version 1.0.0 \
  --sign \
  --signing-identity "Developer ID Application: Your Name (TEAM_ID)" \
  --notarize \
  --apple-id you@example.com \
  --team-id TEAM_ID \
  --password xxxx-xxxx-xxxx-xxxx

# Requires: Apple Developer Account ($99/year)

# Output:
# 🍎 Creating macOS app bundle for bza...
# ✅ macOS app bundle created
#
# ✍️  Signing app bundle...
# ✅ App bundle signed successfully
#
# 📝 Notarizing app...
# (Waits for Apple notarization service...)
# ✅ App notarized and stapled successfully
#
# 📦 App bundle: /tmp/templedb-appstore/BZA.app
#
# Ready for distribution!
```

---

## Complete Workflow Examples

### Deploy bza to Homebrew

```bash
# Step 1: Create source tarball
cd /path/to/bza
git archive --format=tar.gz --prefix=bza-1.0.0/ v1.0.0 > bza-1.0.0.tar.gz

# Step 2: Upload tarball to GitHub releases
gh release create v1.0.0 bza-1.0.0.tar.gz

# Step 3: Calculate SHA256
sha256sum bza-1.0.0.tar.gz

# Step 4: Generate Homebrew formula and publish
templedb deploy-appstore homebrew bza \
  --version 1.0.0 \
  --description "AI-powered code generation CLI" \
  --homepage https://github.com/yourorg/bza \
  --tarball-url https://github.com/yourorg/bza/releases/download/v1.0.0/bza-1.0.0.tar.gz \
  --sha256 <hash-from-step-3> \
  --org yourorg \
  --publish

# Done! Users can now install via:
# brew tap yourorg/tap
# brew install bza
```

---

### Deploy bza to Snap Store

```bash
# Step 1: Login to Snap Store (one-time)
snapcraft login

# Step 2: Build and publish
templedb deploy-appstore snap bza \
  --version 1.0.0 \
  --summary "AI-powered code generation CLI" \
  --description "Generate code using AI models" \
  --publish \
  --channel stable

# Done! Users can now install via:
# snap install bza
```

---

### Deploy bza to macOS App Store

```bash
# Step 1: Build standalone executable
pyinstaller --onefile --windowed bza.py

# Step 2: Create .app bundle with signing and notarization
templedb deploy-appstore macos bza \
  --executable dist/bza \
  --version 1.0.0 \
  --name "BZA" \
  --icon assets/icon.icns \
  --bundle-id com.yourcompany.bza \
  --sign \
  --signing-identity "Developer ID Application: Your Name (TEAM_ID)" \
  --notarize \
  --apple-id you@example.com \
  --team-id TEAM_ID \
  --password xxxx-xxxx-xxxx-xxxx

# Step 3: Create installer (.pkg)
productbuild --component /tmp/templedb-appstore/BZA.app /Applications \
  --sign "Developer ID Installer: Your Name (TEAM_ID)" \
  bza-installer.pkg

# Step 4: Upload to App Store Connect
# (Manual process via Transporter app or altool)

# Done! App is in review for macOS App Store
```

---

## Prerequisites

### For Homebrew
- **Local machine**: Git, GitHub CLI (`gh`)
- **Users**: Homebrew installed (`brew`)

### For Snap
- **Local machine**: `snapcraft` installed
- **Snap Store account**: snapcraft.io account (free)
- **Users**: `snap` installed (pre-installed on Ubuntu)

### For macOS App Store
- **Apple Developer Account**: $99/year
- **Certificates**:
  - Developer ID Application certificate (for signing)
  - Developer ID Installer certificate (for pkg)
- **Xcode Command Line Tools**: `xcode-select --install`
- **App-specific password**: Generate at appleid.apple.com

---

## Distribution Channels Comparison

| Channel | Setup Difficulty | Cost | Reach | Update Speed | Best For |
|---------|-----------------|------|-------|--------------|----------|
| **Homebrew** | Easy (1 hr) | Free | macOS developers | Instant (on push) | Open source, dev tools |
| **Snap** | Easy (2 hrs) | Free | Ubuntu/Linux users | Instant | Universal Linux apps |
| **macOS App Store** | Hard (1 week) | $99/year | 1B+ Mac users | 1-7 days review | Consumer apps |
| **Windows Store** | Hard (1 week) | Free/$100 cert | 1B+ Windows users | 1-3 days review | Consumer apps |

**Recommendation for bza**: Start with **Homebrew** (easiest, developer-friendly), then add **Snap** for Linux users.

---

## Troubleshooting

### Homebrew: Formula test fails

**Symptom**:
```
Error: bza: failed
```

**Solution**:
The `test do` block in the formula runs `bza --version`. Ensure your CLI tool has a `--version` flag.

---

### Snap: Build fails with "Stage package not found"

**Symptom**:
```
Error: Failed to stage package
```

**Solution**:
The Python packages listed in `snapcraft.yaml` need to be available. Check spelling and package names on PyPI.

---

### macOS: Code signing fails

**Symptom**:
```
Error: no identity found
```

**Solution**:
1. Ensure you have a valid Developer ID certificate in Keychain
2. List available identities: `security find-identity -v -p codesigning`
3. Use exact identity string from output

---

### macOS: Notarization fails

**Symptom**:
```
Error: Invalid credentials
```

**Solution**:
1. Generate an **app-specific password** at appleid.apple.com
2. Don't use your main Apple ID password
3. Ensure your Apple ID is enrolled in Apple Developer Program

---

## Implementation Details

### Files Created

1. **`src/services/deployment/appstore_deployment_service.py`** (650 lines)
   - Homebrew formula generation
   - Snap package building
   - macOS .app bundle creation
   - Code signing and notarization
   - Utility functions (tarball creation, SHA256)

2. **`src/cli/commands/deploy_appstore.py`** (300 lines)
   - CLI command handlers for all app stores
   - User-friendly output with progress indicators

3. **Updated `src/services/deployment/__init__.py`**
   - Export AppStoreDeploymentService

### Technologies Used

- **Homebrew**: Ruby DSL for formula
- **Snap**: YAML configuration, `snapcraft` CLI
- **macOS**: `codesign`, `notarytool`, `productbuild`
- **GitHub**: `gh` CLI for tap publishing

---

## What's Next?

**Phase 3** (Steam Integration for Games):
- Unity + Steamworks.NET integration
- Godot + GodotSteam integration
- Multi-platform game builds (Windows, macOS, Linux)
- Steam Pipe uploads
- Achievements and cloud saves

**Future Enhancements**:
- Windows Store (MSIX) deployment
- Flatpak support (Linux)
- AppImage generation
- Automated version bumping
- Release automation (GitHub Actions integration)

---

## Success Criteria

- ✅ Generate Homebrew formula for bza
- ✅ Publish Homebrew tap to GitHub
- ✅ Build Snap package for Linux
- ✅ Create macOS .app bundle
- ✅ Code sign macOS app
- ✅ Notarize macOS app
- ✅ Users can install via `brew install`, `snap install`

**Status**: All criteria met! 🎉

---

**Document Status**: Implementation Complete
**Author**: TempleDB Team
**Date**: 2026-03-21
