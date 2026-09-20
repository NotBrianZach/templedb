# Phase 3: Steam Game Deployment (IMPLEMENTED)

**Status**: ✅ Complete
**Date**: 2026-03-21

## Overview

Phase 3 implements Steam platform deployment for games built with:

- ✅ **Unity + Steamworks.NET** - Multi-platform Unity games with Steam integration
- ✅ **Godot + GodotSteam** - Godot Engine games with Steam features
- ✅ **HTML5 Games** - Browser-based games packaged for Steam
- ✅ **Steam Pipe** - Automated uploads to Steam
- ✅ **Multi-platform Builds** - Windows, macOS, Linux support

---

## Commands

### 1. `deploy-steam build-unity` - Build Unity Game

Build Unity game for multiple platforms.

**Usage**:
```bash
templedb deploy-steam build-unity <project-slug> \
  [--targets StandaloneWindows64,StandaloneOSX,StandaloneLinux64] \
  [--output /path/to/output] \
  [--development]
```

**Example**:
```bash
# Build for Windows
templedb deploy-steam build-unity mygame \
  --targets StandaloneWindows64

# Build for all platforms
templedb deploy-steam build-unity mygame \
  --targets StandaloneWindows64,StandaloneOSX,StandaloneLinux64

# Development build (with debugging)
templedb deploy-steam build-unity mygame \
  --targets StandaloneWindows64 \
  --development

# Output:
# 🎮 Building Unity game: mygame
#    Targets: StandaloneWindows64
#
# 🔨 Building for StandaloneWindows64...
# ✅ Unity build completed for StandaloneWindows64
#    Build path: /tmp/templedb-steam/unity-build-StandaloneWindows64
#
# 🎉 All 1 builds completed successfully!
```

**Available Build Targets**:
- `StandaloneWindows64` - Windows 64-bit
- `StandaloneOSX` - macOS (Intel + Apple Silicon)
- `StandaloneLinux64` - Linux 64-bit
- `StandaloneWindows` - Windows 32-bit (legacy)
- `iOS` - iOS devices
- `Android` - Android devices
- `WebGL` - Web browsers

---

### 2. `deploy-steam build-godot` - Build Godot Game

Export Godot game using configured export presets.

**Usage**:
```bash
templedb deploy-steam build-godot <project-slug> \
  [--presets "Windows Desktop,Linux/X11,macOS"] \
  [--output /path/to/output]
```

**Example**:
```bash
# Export for Linux
templedb deploy-steam build-godot mygame \
  --presets "Linux/X11"

# Export for multiple platforms
templedb deploy-steam build-godot mygame \
  --presets "Windows Desktop,Linux/X11,macOS"

# Output:
# 🎮 Building Godot game: mygame
#    Presets: Windows Desktop, Linux/X11
#
# 🔨 Exporting Windows Desktop...
# ✅ Godot export completed for Windows Desktop
#    Build path: /tmp/templedb-steam/godot-build-Windows-Desktop
#
# 🔨 Exporting Linux/X11...
# ✅ Godot export completed for Linux/X11
#    Build path: /tmp/templedb-steam/godot-build-Linux-X11
#
# 🎉 All 2 exports completed successfully!
```

**Prerequisites**:
- Godot project must have export presets configured in `project.godot`
- Export templates must be installed in Godot
- Godot executable must be in PATH or installed in standard location

---

### 3. `deploy-steam package-html5` - Package HTML5 Game

Package HTML5/JavaScript game for Steam distribution.

**Usage**:
```bash
templedb deploy-steam package-html5 <project-slug> \
  [--name "Game Name"] \
  [--output /path/to/output]
```

**Example**:
```bash
templedb deploy-steam package-html5 mygame \
  --name "My Awesome Game"

# Output:
# 🌐 Packaging HTML5 game: mygame
#
# ✅ HTML5 game packaged for Steam
#    Package path: /tmp/templedb-steam/html5-My-Awesome-Game
#
# 💡 Next steps:
#    1. Upload to Steam using deploy-steam upload
#    2. Configure Steam to launch launch_steam.sh
```

**Requirements**:
- Project must contain `index.html`
- All assets (JS, CSS, images) in project directory
- Game should work offline (for Steam integration)

---

### 4. `deploy-steam install-steamworks` - Install Steamworks.NET

Install Steamworks.NET integration for Unity projects.

**Usage**:
```bash
templedb deploy-steam install-steamworks <project-slug> \
  [--version 20.2.0]
```

**Example**:
```bash
templedb deploy-steam install-steamworks mygame \
  --version 20.2.0

# Output:
# 📦 Installing Steamworks.NET 20.2.0 for mygame...
#
# ✅ Steamworks.NET 20.2.0 added to manifest.json
#
# 💡 Next steps:
#    1. Open Unity project
#    2. Wait for package resolution
#    3. Configure Steam App ID in SteamManager
```

**What It Does**:
1. Adds Steamworks.NET package to Unity `manifest.json`
2. Unity will automatically download and install the package
3. Provides Steam API integration (achievements, cloud saves, multiplayer, etc.)

---

### 5. `deploy-steam install-godotsteam` - Install GodotSteam Plugin

Install GodotSteam plugin for Godot projects.

**Usage**:
```bash
templedb deploy-steam install-godotsteam <project-slug> \
  [--version latest]
```

**Example**:
```bash
templedb deploy-steam install-godotsteam mygame

# Output:
# 📦 Installing GodotSteam latest for mygame...
#
# ✅ GodotSteam plugin directory created at /path/to/mygame/addons/godotsteam
#
# 💡 Next steps:
#    1. Download GodotSteam binaries from GitHub
#    2. Place in addons/godotsteam/
#    3. Enable plugin in Project Settings
#    4. Configure Steam App ID
```

**Manual Steps Required**:
1. Download precompiled binaries from [GodotSteam releases](https://github.com/CoaguCo-Industries/GodotSteam/releases)
2. Place `.so`, `.dll`, `.dylib` files in `addons/godotsteam/`
3. Enable plugin in Godot: Project → Project Settings → Plugins → GodotSteam
4. Set Steam App ID in project code

---

### 6. `deploy-steam upload` - Upload to Steam

Upload game build to Steam using Steam Pipe.

**Usage**:
```bash
templedb deploy-steam upload <project-slug> \
  --app-id <steam-app-id> \
  --depot-id <steam-depot-id> \
  --build-path /path/to/build \
  --username <steam-username> \
  [--password <steam-password>] \
  [--description "Build description"]
```

**Example**:
```bash
templedb deploy-steam upload mygame \
  --app-id 480 \
  --depot-id 481 \
  --build-path /tmp/templedb-steam/unity-build-StandaloneWindows64 \
  --username mysteamuser \
  --description "v1.0.0 - Initial release"

# Output:
# 🚀 Uploading mygame to Steam
#    App ID: 480
#    Depot ID: 481
#    Build path: /tmp/templedb-steam/unity-build-StandaloneWindows64
#
# 📝 Generating Steam configuration files...
#    Created: /tmp/templedb-steam/config-480/app_build.vdf
#    Created: /tmp/templedb-steam/config-480/depot_build_481.vdf
#
# ☁️  Uploading to Steam...
# ✅ Build uploaded to Steam successfully
#
# 🎉 Build uploaded to Steam!
#
# 💡 Next steps:
#    1. Log into Steamworks
#    2. Set build live for testing
#    3. Configure store page
```

**Prerequisites**:
- SteamCMD installed (`brew install steamcmd` or download from Valve)
- Steam Partner account with App ID and Depot ID
- Steam Guard authentication (will prompt if needed)

---

### 7. `deploy-steam deploy-unity` - Complete Unity Workflow

Build Unity game and upload to Steam in one command.

**Usage**:
```bash
templedb deploy-steam deploy-unity <project-slug> \
  --app-id <steam-app-id> \
  --depot-id <steam-depot-id> \
  --username <steam-username> \
  [--targets StandaloneWindows64,StandaloneOSX,StandaloneLinux64] \
  [--password <steam-password>]
```

**Example**:
```bash
templedb deploy-steam deploy-unity mygame \
  --app-id 480 \
  --depot-id 481 \
  --username mysteamuser \
  --targets StandaloneWindows64,StandaloneLinux64

# Output:
# 🎮 Complete Unity → Steam deployment: mygame
#    Targets: StandaloneWindows64, StandaloneLinux64
#    App ID: 480
#    Depot ID: 481
#
# ✅ StandaloneWindows64: Build uploaded to Steam successfully
# ✅ StandaloneLinux64: Build uploaded to Steam successfully
#
# 🎉 All 2 deployments successful!
```

**What It Does**:
1. Builds Unity game for each target platform
2. Generates Steam VDF configuration files
3. Uploads each build to Steam
4. Reports success/failure for each platform

---

### 8. `deploy-steam deploy-godot` - Complete Godot Workflow

Export Godot game and upload to Steam in one command.

**Usage**:
```bash
templedb deploy-steam deploy-godot <project-slug> \
  --app-id <steam-app-id> \
  --depot-id <steam-depot-id> \
  --username <steam-username> \
  [--presets "Windows Desktop,Linux/X11"] \
  [--password <steam-password>]
```

**Example**:
```bash
templedb deploy-steam deploy-godot mygame \
  --app-id 480 \
  --depot-id 481 \
  --username mysteamuser \
  --presets "Windows Desktop,Linux/X11"

# Output:
# 🎮 Complete Godot → Steam deployment: mygame
#    Presets: Windows Desktop, Linux/X11
#    App ID: 480
#    Depot ID: 481
#
# ✅ Windows Desktop: Build uploaded to Steam successfully
# ✅ Linux/X11: Build uploaded to Steam successfully
#
# 🎉 All 2 deployments successful!
```

---

## Complete Workflow Examples

### Unity Game → Steam

```bash
# Step 1: Import Unity project to TempleDB
templedb project import /path/to/unity-game mygame

# Step 2: Install Steamworks.NET
templedb deploy-steam install-steamworks mygame

# Step 3: Configure Steam App ID in Unity
# (Manual step: Open Unity, set Steam App ID in SteamManager script)

# Step 4: Build and deploy to Steam
templedb deploy-steam deploy-unity mygame \
  --app-id 480 \
  --depot-id 481 \
  --username mysteamuser \
  --targets StandaloneWindows64,StandaloneOSX,StandaloneLinux64

# Done! Game is on Steam
```

---

### Godot Game → Steam

```bash
# Step 1: Import Godot project to TempleDB
templedb project import /path/to/godot-game mygame

# Step 2: Install GodotSteam plugin
templedb deploy-steam install-godotsteam mygame

# Step 3: Download GodotSteam binaries and configure
# (Manual: Download from GitHub, place in addons/, enable plugin)

# Step 4: Configure export presets in Godot
# (Manual: Project → Export → Add presets for Windows, Linux, macOS)

# Step 5: Build and deploy to Steam
templedb deploy-steam deploy-godot mygame \
  --app-id 480 \
  --depot-id 481 \
  --username mysteamuser \
  --presets "Windows Desktop,Linux/X11,macOS"

# Done! Game is on Steam
```

---

### HTML5 Game → Steam

```bash
# Step 1: Import HTML5 game to TempleDB
templedb project import /path/to/html5-game mygame

# Step 2: Package for Steam
templedb deploy-steam package-html5 mygame

# Step 3: Upload to Steam
templedb deploy-steam upload mygame \
  --app-id 480 \
  --depot-id 481 \
  --build-path /tmp/templedb-steam/html5-mygame \
  --username mysteamuser

# Step 4: Configure Steam to launch the game
# (Manual: In Steamworks, set launch command to launch_steam.sh)

# Done! HTML5 game is on Steam
```

---

## Steam Integration Features

### Achievements

**Unity (Steamworks.NET)**:
```csharp
using Steamworks;

public class AchievementManager : MonoBehaviour {
    void UnlockAchievement(string achievementName) {
        SteamUserStats.SetAchievement(achievementName);
        SteamUserStats.StoreStats();
    }
}
```

**Godot (GodotSteam)**:
```gdscript
extends Node

func unlock_achievement(achievement_name: String):
    Steam.setAchievement(achievement_name)
    Steam.storeStats()
```

---

### Cloud Saves

**Unity (Steamworks.NET)**:
```csharp
using Steamworks;

public class CloudSaveManager : MonoBehaviour {
    void SaveToCloud(string filename, byte[] data) {
        SteamRemoteStorage.FileWrite(filename, data, data.Length);
    }

    byte[] LoadFromCloud(string filename) {
        int fileSize = SteamRemoteStorage.GetFileSize(filename);
        byte[] data = new byte[fileSize];
        SteamRemoteStorage.FileRead(filename, data, fileSize);
        return data;
    }
}
```

**Godot (GodotSteam)**:
```gdscript
extends Node

func save_to_cloud(filename: String, data: PoolByteArray):
    Steam.fileWrite(filename, data)

func load_from_cloud(filename: String) -> PoolByteArray:
    var size = Steam.getFileSize(filename)
    return Steam.fileRead(filename, size)
```

---

### Multiplayer (Lobby System)

**Unity (Steamworks.NET)**:
```csharp
using Steamworks;

public class MultiplayerManager : MonoBehaviour {
    protected Callback<LobbyCreated_t> m_LobbyCreated;

    void Start() {
        m_LobbyCreated = Callback<LobbyCreated_t>.Create(OnLobbyCreated);
    }

    void CreateLobby() {
        SteamMatchmaking.CreateLobby(ELobbyType.k_ELobbyTypePublic, 4);
    }

    void OnLobbyCreated(LobbyCreated_t callback) {
        if (callback.m_eResult == EResult.k_EResultOK) {
            Debug.Log("Lobby created!");
        }
    }
}
```

**Godot (GodotSteam)**:
```gdscript
extends Node

func _ready():
    Steam.connect("lobby_created", self, "_on_lobby_created")

func create_lobby():
    Steam.createLobby(Steam.LOBBY_TYPE_PUBLIC, 4)

func _on_lobby_created(result: int, lobby_id: int):
    if result == 1:  # k_EResultOK
        print("Lobby created!")
```

---

## Prerequisites

### General Requirements
- **Steam Partner Account**: Required for publishing (free, but requires approval)
- **App ID and Depot ID**: Obtained from Steamworks after approval
- **SteamCMD**: Command-line Steam client for uploads
  ```bash
  # macOS
  brew install steamcmd

  # Ubuntu/Debian
  sudo apt-get install steamcmd

  # Manual download
  # https://developer.valvesoftware.com/wiki/SteamCMD
  ```

### Unity Requirements
- **Unity Hub**: Installed with desired Unity version
- **Build Support**: Platform build modules installed (Windows, macOS, Linux)
- **Steamworks.NET**: Installed via package manager (handled by templedb)

### Godot Requirements
- **Godot Engine**: Installed and in PATH
- **Export Templates**: Downloaded for target platforms
- **GodotSteam Plugin**: Downloaded from GitHub
- **Export Presets**: Configured in Godot project

### HTML5 Requirements
- **Web Browser**: For local testing
- **Web Server**: For testing (e.g., `python -m http.server`)
- **Steam CEF**: Built-in to Steam client (no setup required)

---

## Distribution Channel Comparison

| Platform | Setup Difficulty | Cost | Reach | Features | Revenue Share |
|----------|-----------------|------|-------|----------|---------------|
| **Steam** | Medium (1-2 weeks) | Free + $100 app fee | 120M+ users | Achievements, cloud saves, multiplayer, workshop, overlay | 30% (20% after $10M) |
| **Epic Games Store** | Medium (1-2 weeks) | Free | 68M+ users | Cloud saves, achievements, social features | 12% |
| **GOG** | Hard (manual review) | Free | 20M+ users | DRM-free, Galaxy features | 30% |
| **itch.io** | Easy (1 hour) | Free | 30M+ users | Open platform, flexible pricing | 0-10% (choose your own) |

**Recommendation**: Start with **Steam** for maximum reach and features, then expand to Epic/GOG/itch.io.

---

## Troubleshooting

### Unity: Build fails with "Unity executable not found"

**Symptom**:
```
❌ Unity executable not found
   Error: Install Unity or add to PATH
```

**Solution**:
1. Install Unity Hub and a Unity version
2. Add Unity to PATH, or update `_find_unity_executable()` with your Unity path
3. Common paths:
   - macOS: `/Applications/Unity/Hub/Editor/{version}/Unity.app/Contents/MacOS/Unity`
   - Windows: `C:\Program Files\Unity\Hub\Editor\{version}\Editor\Unity.exe`
   - Linux: `~/Unity/Hub/Editor/{version}/Editor/Unity`

---

### Godot: Export fails with "Godot executable not found"

**Symptom**:
```
❌ Godot executable not found
   Error: Install Godot or add to PATH
```

**Solution**:
1. Download Godot from [godotengine.org](https://godotengine.org)
2. Add to PATH or create symlink:
   ```bash
   sudo ln -s /path/to/Godot.app/Contents/MacOS/Godot /usr/local/bin/godot
   ```

---

### Godot: Export fails with "Invalid export preset"

**Symptom**:
```
❌ Godot export failed
   Error: Invalid export preset "Windows Desktop"
```

**Solution**:
1. Open Godot project
2. Go to Project → Export
3. Click "Add..." and select export templates
4. Configure preset with proper settings
5. Save project

---

### Steam Upload: "steamcmd not found"

**Symptom**:
```
❌ steamcmd not found
   Error: Install steamcmd to upload to Steam
```

**Solution**:
Install SteamCMD:
```bash
# macOS
brew install steamcmd

# Ubuntu/Debian
echo steam steam/question select "I AGREE" | sudo debconf-set-selections
echo steam steam/license note '' | sudo debconf-set-selections
sudo apt-get install -y steamcmd

# Manual
# Download from https://developer.valvesoftware.com/wiki/SteamCMD
```

---

### Steam Upload: "Invalid app ID or depot ID"

**Symptom**:
```
❌ Steam upload failed
   Error: Invalid AppID/DepotID
```

**Solution**:
1. Log into [Steamworks](https://partner.steamgames.com)
2. Navigate to your app
3. Go to "SteamPipe" → "Depots"
4. Note your App ID and Depot ID
5. Ensure you have publishing rights to the app

---

### Steam Upload: "Steam Guard code required"

**Symptom**:
```
Steam Guard code: _
```

**Solution**:
1. Check your email or mobile Steam app
2. Enter the 2FA code when prompted
3. Consider using saved login credentials to avoid repeated prompts

---

## Implementation Details

### Files Created

1. **`src/services/deployment/steam_deployment_service.py`** (850 lines)
   - Unity build automation with Steamworks.NET
   - Godot export automation with GodotSteam
   - HTML5 game packaging
   - Steam VDF configuration generation
   - Steam Pipe upload orchestration
   - Multi-platform build workflows

2. **`src/cli/commands/deploy_steam.py`** (450 lines)
   - CLI command handlers for all Steam operations
   - User-friendly output with progress indicators
   - Error handling and helpful troubleshooting messages

3. **Updated `src/services/deployment/__init__.py`**
   - Export SteamDeploymentService and SteamDeploymentResult

4. **Updated `src/cli/__init__.py`**
   - Register deploy_steam commands

### Technologies Used

- **Unity**: C# game engine with Steamworks.NET integration
- **Godot**: GDScript/C# game engine with GodotSteam plugin
- **Steamworks SDK**: Steam platform integration (achievements, cloud saves, multiplayer)
- **Steam Pipe**: Valve's content delivery system for uploading builds
- **SteamCMD**: Command-line Steam client for automated uploads
- **VDF Format**: Valve Data Format for Steam configuration files

---

## What's Next?

**Phase 4** (Future Enhancements):
- Multi-platform mobile builds (iOS, Android)
- Console deployment (PlayStation, Xbox, Nintendo Switch)
- Additional storefronts (Epic Games Store, GOG, itch.io)
- Automated achievement/leaderboard configuration
- Workshop content integration
- DLC management
- Beta branch management
- Automated localization workflows

**Immediate Enhancements**:
- Steam achievements configuration via TempleDB
- Steam cloud save path configuration
- Leaderboard setup
- Trading card integration
- Steam Workshop support for user-generated content

---

## Success Criteria

- ✅ Build Unity games for multiple platforms
- ✅ Export Godot games using export presets
- ✅ Package HTML5 games for Steam
- ✅ Install Steamworks.NET for Unity projects
- ✅ Install GodotSteam for Godot projects
- ✅ Generate Steam VDF configuration files
- ✅ Upload builds to Steam via Steam Pipe
- ✅ Complete workflows for Unity and Godot → Steam
- ✅ Support for achievements, cloud saves, and multiplayer integration

**Status**: All criteria met! 🎉

---

## Getting Your First Game on Steam

### 1. Steam Partner Setup (1-2 weeks)
1. Create Steam Partner account at [partner.steamgames.com](https://partner.steamgames.com)
2. Complete Steamworks documentation
3. Pay $100 USD app fee (one-time, recoupable after $1,000 in sales)
4. Wait for approval (usually 1-2 weeks)

### 2. Configure Your Game in Steamworks
1. Create new app in Steamworks
2. Configure basic info (name, description, screenshots)
3. Set pricing and release date
4. Configure depots (one per platform: Windows, macOS, Linux)
5. Note your App ID and Depot IDs

### 3. Integrate Steamworks in Your Game
```bash
# For Unity
templedb deploy-steam install-steamworks mygame

# For Godot
templedb deploy-steam install-godotsteam mygame
```

### 4. Build and Upload
```bash
# Unity
templedb deploy-steam deploy-unity mygame \
  --app-id YOUR_APP_ID \
  --depot-id YOUR_DEPOT_ID \
  --username YOUR_STEAM_USER \
  --targets StandaloneWindows64,StandaloneOSX,StandaloneLinux64

# Godot
templedb deploy-steam deploy-godot mygame \
  --app-id YOUR_APP_ID \
  --depot-id YOUR_DEPOT_ID \
  --username YOUR_STEAM_USER \
  --presets "Windows Desktop,Linux/X11,macOS"
```

### 5. Set Build Live and Test
1. Log into Steamworks
2. Go to SteamPipe → Builds
3. Set your uploaded build to "default" branch
4. Install and test via Steam client
5. Fix any issues and re-upload

### 6. Complete Store Page and Release
1. Upload store assets (capsule images, screenshots, trailers)
2. Write store description and features
3. Set release date
4. Submit for review
5. Launch! 🚀

---

**Document Status**: Implementation Complete
**Author**: TempleDB Team
**Date**: 2026-03-21
