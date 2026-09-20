# Game Engine Deployment Guide

**Supported Engines**: Unity, Godot, HTML5/JavaScript

This guide covers deploying games built with different engines to Steam, Itch.io, and other platforms using TempleDB.

---

## Table of Contents

1. [Unity Deployment](#unity-deployment)
2. [Godot Deployment](#godot-deployment)
3. [HTML5 Games](#html5-games)
4. [Multi-Platform Build Matrix](#multi-platform-build-matrix)
5. [Steam Integration by Engine](#steam-integration-by-engine)

---

## Unity Deployment

### Overview

Unity games can be deployed to:
- **Steam** (Windows, macOS, Linux, SteamOS)
- **Itch.io** (all platforms + WebGL)
- **App Stores** (iOS, Android via Unity Cloud Build or local builds)

### Prerequisites

1. **Unity Editor** installed (or Unity Hub)
2. **Steamworks.NET** plugin (for Steam integration)
3. **Build support modules** (Windows, macOS, Linux, WebGL)

### Project Structure

```
my-unity-game/
├── Assets/
│   ├── Scenes/
│   ├── Scripts/
│   ├── Plugins/
│   │   └── Steamworks.NET/  # Steam integration
│   └── StreamingAssets/
├── ProjectSettings/
│   └── ProjectSettings.asset
├── Packages/
│   └── manifest.json
└── .templedb/               # TempleDB metadata
    ├── steam_config.json    # App ID, depot IDs
    └── build_settings.json  # Build configurations
```

### Import into TempleDB

```bash
# Import Unity project
templedb project import ~/projects/my-unity-game

# Initialize Steam configuration
templedb steam init my-unity-game \
  --app-id 123456 \
  --engine unity
```

### Build Configuration

**TempleDB generates** `build_settings.json`:

```json
{
  "engine": "unity",
  "unity_version": "2022.3.10f1",
  "platforms": {
    "windows": {
      "target": "StandaloneWindows64",
      "output_path": "builds/windows/MyGame.exe",
      "scripting_backend": "IL2CPP",
      "enabled": true
    },
    "macos": {
      "target": "StandaloneOSX",
      "output_path": "builds/macos/MyGame.app",
      "scripting_backend": "Mono",
      "enabled": true
    },
    "linux": {
      "target": "StandaloneLinux64",
      "output_path": "builds/linux/MyGame.x86_64",
      "scripting_backend": "IL2CPP",
      "enabled": true
    },
    "webgl": {
      "target": "WebGL",
      "output_path": "builds/webgl",
      "compression_format": "Gzip",
      "enabled": true
    }
  },
  "build_options": {
    "development_build": false,
    "deep_profiling": false,
    "script_debugging": false
  }
}
```

### Headless Build (Command Line)

**Unity command line build**:

```bash
# TempleDB generates build script
templedb deploy build my-unity-game --platform windows

# Internally runs:
/Applications/Unity/Hub/Editor/2022.3.10f1/Unity.app/Contents/MacOS/Unity \
  -quit \
  -batchmode \
  -nographics \
  -projectPath /path/to/my-unity-game \
  -buildTarget StandaloneWindows64 \
  -buildPath builds/windows/MyGame.exe \
  -logFile builds/build-windows.log
```

**Build script** (`build_unity.sh` - auto-generated):

```bash
#!/bin/bash
set -e

PROJECT_PATH="/path/to/my-unity-game"
UNITY="/Applications/Unity/Hub/Editor/2022.3.10f1/Unity.app/Contents/MacOS/Unity"
OUTPUT_DIR="builds"

# Windows build
echo "Building for Windows..."
$UNITY -quit -batchmode -nographics \
  -projectPath "$PROJECT_PATH" \
  -buildTarget StandaloneWindows64 \
  -buildPath "$OUTPUT_DIR/windows/MyGame.exe" \
  -logFile "$OUTPUT_DIR/build-windows.log"

# macOS build
echo "Building for macOS..."
$UNITY -quit -batchmode -nographics \
  -projectPath "$PROJECT_PATH" \
  -buildTarget StandaloneOSX \
  -buildPath "$OUTPUT_DIR/macos/MyGame.app" \
  -logFile "$OUTPUT_DIR/build-macos.log"

# Linux build
echo "Building for Linux..."
$UNITY -quit -batchmode -nographics \
  -projectPath "$PROJECT_PATH" \
  -buildTarget StandaloneLinux64 \
  -buildPath "$OUTPUT_DIR/linux/MyGame.x86_64" \
  -logFile "$OUTPUT_DIR/build-linux.log"

echo "All builds complete!"
```

### Steamworks.NET Integration

**Install Steamworks.NET**:

```bash
# Download from GitHub
# https://github.com/rlabrecque/Steamworks.NET/releases

# Extract to Assets/Plugins/Steamworks.NET/
```

**Initialize Steam** (C# script):

```csharp
// Assets/Scripts/SteamManager.cs
using UnityEngine;
using Steamworks;

public class SteamManager : MonoBehaviour
{
    protected static SteamManager s_instance;
    protected bool m_bInitialized = false;

    public static SteamManager Instance
    {
        get
        {
            if (s_instance == null)
            {
                return new GameObject("SteamManager").AddComponent<SteamManager>();
            }
            return s_instance;
        }
    }

    void Awake()
    {
        if (s_instance != null)
        {
            Destroy(gameObject);
            return;
        }

        s_instance = this;
        DontDestroyOnLoad(gameObject);

        // Initialize Steam API
        try
        {
            m_bInitialized = SteamAPI.Init();
            if (!m_bInitialized)
            {
                Debug.LogError("SteamAPI.Init() failed!");
            }
            else
            {
                Debug.Log("Steam initialized successfully");
                Debug.Log($"Player: {SteamFriends.GetPersonaName()}");
            }
        }
        catch (System.Exception e)
        {
            Debug.LogError($"Steam initialization exception: {e.Message}");
        }
    }

    void Update()
    {
        if (m_bInitialized)
        {
            SteamAPI.RunCallbacks();
        }
    }

    void OnApplicationQuit()
    {
        if (m_bInitialized)
        {
            SteamAPI.Shutdown();
        }
    }
}
```

**Unlock Achievement**:

```csharp
using Steamworks;

public class AchievementManager : MonoBehaviour
{
    public void UnlockAchievement(string achievementID)
    {
        if (SteamManager.Instance != null)
        {
            SteamUserStats.SetAchievement(achievementID);
            SteamUserStats.StoreStats();
            Debug.Log($"Achievement unlocked: {achievementID}");
        }
    }
}
```

**Steam Cloud Save**:

```csharp
using Steamworks;
using System.Text;

public class SaveManager : MonoBehaviour
{
    public void SaveToSteamCloud(string filename, string data)
    {
        byte[] bytes = Encoding.UTF8.GetBytes(data);
        bool success = SteamRemoteStorage.FileWrite(filename, bytes, bytes.Length);

        if (success)
        {
            Debug.Log($"Saved to Steam Cloud: {filename}");
        }
    }

    public string LoadFromSteamCloud(string filename)
    {
        if (SteamRemoteStorage.FileExists(filename))
        {
            int fileSize = SteamRemoteStorage.GetFileSize(filename);
            byte[] bytes = new byte[fileSize];
            SteamRemoteStorage.FileRead(filename, bytes, fileSize);
            return Encoding.UTF8.GetString(bytes);
        }

        return null;
    }
}
```

### Complete Unity → Steam Workflow

```bash
# 1. Import Unity project into TempleDB
templedb project import ~/projects/my-unity-game

# 2. Initialize Steam configuration
templedb steam init my-unity-game --app-id 123456 --engine unity

# 3. Install Steamworks.NET plugin (manual step in Unity Editor)
# Download from: https://github.com/rlabrecque/Steamworks.NET

# 4. Configure steam_appid.txt for local testing
echo "123456" > Assets/StreamingAssets/steam_appid.txt

# 5. Build all platforms
templedb deploy build-matrix my-unity-game \
  --platforms windows,macos,linux \
  --output ./builds/

# 6. Upload to Steam
templedb deploy steam my-unity-game \
  --branch beta \
  --description "Unity build v1.0.0"

# 7. Test Steam integration
# Run builds/windows/MyGame.exe with Steam client running
```

---

## Godot Deployment

### Overview

Godot is an open-source game engine with excellent cross-platform support.

**Advantages**:
- ✅ Free and open source
- ✅ Lightweight (faster builds than Unity)
- ✅ Native GDScript or C# scripting
- ✅ Built-in export templates

### Prerequisites

1. **Godot Engine** (4.x or 3.x)
2. **GodotSteam plugin** (for Steam integration)
3. **Export templates** (Windows, macOS, Linux, HTML5)

### Project Structure

```
my-godot-game/
├── project.godot          # Project configuration
├── scenes/
│   ├── main.tscn
│   └── level1.tscn
├── scripts/
│   ├── player.gd
│   └── steam_manager.gd
├── assets/
│   ├── textures/
│   ├── audio/
│   └── models/
├── addons/
│   └── godotsteam/        # Steam integration
└── .templedb/
    └── steam_config.json
```

### Import into TempleDB

```bash
# Import Godot project
templedb project import ~/projects/my-godot-game

# Initialize Steam
templedb steam init my-godot-game \
  --app-id 123456 \
  --engine godot
```

### Godot Command Line Export

**Export presets** (`export_presets.cfg`):

```ini
[preset.0]
name="Windows Desktop"
platform="Windows Desktop"
runnable=true
custom_features=""
export_filter="all_resources"
include_filter=""
exclude_filter=""
export_path="builds/windows/MyGame.exe"
encryption_include_filters=""
encryption_exclude_filters=""
encrypt_pck=false
encrypt_directory=false

[preset.0.options]
custom_template/debug=""
custom_template/release=""
binary_format/64_bits=true
binary_format/embed_pck=false
texture_format/bptc=false
texture_format/s3tc=true
texture_format/etc=false
texture_format/etc2=false

[preset.1]
name="macOS"
platform="macOS"
runnable=true
export_path="builds/macos/MyGame.zip"

[preset.2]
name="Linux/X11"
platform="Linux/X11"
runnable=true
export_path="builds/linux/MyGame.x86_64"
```

**Export via command line**:

```bash
# TempleDB generates export commands
templedb deploy build my-godot-game --platform windows

# Internally runs:
godot --headless --export-release "Windows Desktop" builds/windows/MyGame.exe

# macOS
godot --headless --export-release "macOS" builds/macos/MyGame.zip

# Linux
godot --headless --export-release "Linux/X11" builds/linux/MyGame.x86_64

# HTML5
godot --headless --export-release "HTML5" builds/html5/index.html
```

### GodotSteam Integration

**Install GodotSteam**:

```bash
# Download pre-compiled GodotSteam from:
# https://github.com/GodotSteam/GodotSteam/releases

# For Godot 4.x, use GodotSteam 4.x
# Extract to addons/godotsteam/
```

**Initialize Steam** (GDScript):

```gdscript
# scripts/steam_manager.gd
extends Node

var steam_initialized = false
var steam_id = 0
var steam_username = ""

func _ready():
    # Initialize Steam
    var initialize_response = Steam.steamInitEx()
    print("Steam init response: ", initialize_response)

    if initialize_response['status'] > 0:
        print("Failed to initialize Steam: ", initialize_response)
        steam_initialized = false
    else:
        steam_initialized = true
        steam_id = Steam.getSteamID()
        steam_username = Steam.getPersonaName()
        print("Steam initialized successfully")
        print("Player: ", steam_username, " (", steam_id, ")")

func _process(_delta):
    if steam_initialized:
        Steam.run_callbacks()

func unlock_achievement(achievement_name: String):
    if steam_initialized:
        Steam.setAchievement(achievement_name)
        Steam.storeStats()
        print("Achievement unlocked: ", achievement_name)

func save_to_cloud(filename: String, data: String):
    if steam_initialized:
        var success = Steam.fileWrite(filename, data.to_utf8_buffer())
        if success:
            print("Saved to Steam Cloud: ", filename)

func load_from_cloud(filename: String) -> String:
    if steam_initialized and Steam.fileExists(filename):
        var file_size = Steam.getFileSize(filename)
        var data = Steam.fileRead(filename, file_size)
        return data.get_string_from_utf8()
    return ""

func _exit_tree():
    if steam_initialized:
        Steam.steamShutdown()
```

**Auto-load Steam manager** (in `project.godot`):

```ini
[autoload]
SteamManager="*res://scripts/steam_manager.gd"
```

**Unlock achievement from any scene**:

```gdscript
# In any script
func _on_level_complete():
    SteamManager.unlock_achievement("LEVEL_1_COMPLETE")
```

### Complete Godot → Steam Workflow

```bash
# 1. Import Godot project
templedb project import ~/projects/my-godot-game

# 2. Initialize Steam
templedb steam init my-godot-game --app-id 123456 --engine godot

# 3. Install GodotSteam plugin (download and extract to addons/)
# https://github.com/GodotSteam/GodotSteam/releases

# 4. Configure steam_appid.txt for local testing
echo "123456" > steam_appid.txt

# 5. Build all platforms
templedb deploy build-matrix my-godot-game \
  --platforms windows,macos,linux,html5 \
  --output ./builds/

# 6. Upload to Steam
templedb deploy steam my-godot-game \
  --branch default \
  --description "Godot build v1.0.0"
```

---

## HTML5 Games

### Overview

HTML5 games built with:
- **Phaser** (JavaScript game framework)
- **PixiJS** (2D WebGL renderer)
- **Three.js** (3D graphics)
- **Unity WebGL** (Unity exported to browser)
- **Godot HTML5** (Godot exported to browser)

### Deployment Targets

1. **Itch.io** (native HTML5 support)
2. **Static hosting** (Netlify, Vercel, GitHub Pages)
3. **Steam** (via Steamworks for Web - experimental)

### Project Structure

```
my-html5-game/
├── src/
│   ├── game.js           # Main game logic
│   ├── scenes/
│   └── entities/
├── assets/
│   ├── sprites/
│   ├── audio/
│   └── fonts/
├── index.html            # Entry point
├── package.json          # Dependencies
├── vite.config.js        # Build configuration
└── .templedb/
    └── deploy_config.json
```

### Build Process

**Using Vite** (modern bundler):

```bash
# Install dependencies
npm install

# Build for production
npm run build

# Output: dist/
# ├── index.html
# ├── assets/
# │   ├── game.js (bundled, minified)
# │   ├── vendor.js (libraries)
# │   └── sprites/
# └── manifest.json
```

**TempleDB automation**:

```bash
# Build HTML5 game
templedb deploy build my-html5-game --format html5 --output ./dist/

# Internally runs:
# 1. npm install (or pnpm, yarn)
# 2. npm run build
# 3. Optimize assets (compress images, minify JS)
# 4. Generate service worker (for offline play)
```

### Deploy to Itch.io

```bash
# Upload to Itch.io
templedb deploy itch my-html5-game \
  --type html5 \
  --itch-user yourusername \
  --game mygame

# Uses butler:
# butler push ./dist/ yourusername/mygame:html5
```

**Itch.io configuration** (auto-generated):

```json
{
  "title": "My HTML5 Game",
  "type": "html",
  "index_file": "index.html",
  "viewport": {
    "width": 1280,
    "height": 720
  },
  "fullscreen": true,
  "mobile_friendly": true
}
```

### Deploy to Static Hosting

```bash
# Netlify
templedb deploy netlify my-html5-game --source ./dist/

# Vercel
templedb deploy vercel my-html5-game --source ./dist/

# GitHub Pages
templedb deploy github-pages my-html5-game --source ./dist/
```

### Service Worker for Offline Play

**TempleDB auto-generates** `sw.js`:

```javascript
// Service worker for offline caching
const CACHE_NAME = 'my-game-v1.0.0';
const ASSETS_TO_CACHE = [
  '/index.html',
  '/assets/game.js',
  '/assets/vendor.js',
  '/assets/sprites/player.png',
  '/assets/audio/music.mp3'
];

self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
});

self.addEventListener('fetch', event => {
  event.respondWith(
    caches.match(event.request).then(response => {
      return response || fetch(event.request);
    })
  );
});
```

**Register in `index.html`**:

```html
<script>
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js')
    .then(() => console.log('Service worker registered'))
    .catch(err => console.error('Service worker registration failed', err));
}
</script>
```

---

## Multi-Platform Build Matrix

### Automated Builds for All Platforms

```bash
# Build for all platforms in parallel
templedb deploy build-matrix my-game \
  --platforms all \
  --engine unity \
  --output ./builds/

# Platforms: windows, macos, linux, webgl, android, ios
```

**Build matrix configuration** (`build_matrix.json`):

```json
{
  "engine": "unity",
  "platforms": [
    {
      "name": "windows",
      "target": "StandaloneWindows64",
      "enabled": true,
      "steam_depot_id": "123457"
    },
    {
      "name": "macos",
      "target": "StandaloneOSX",
      "enabled": true,
      "steam_depot_id": "123458"
    },
    {
      "name": "linux",
      "target": "StandaloneLinux64",
      "enabled": true,
      "steam_depot_id": "123459"
    },
    {
      "name": "webgl",
      "target": "WebGL",
      "enabled": true,
      "deploy_to": "itch"
    }
  ],
  "parallel_builds": 4
}
```

**Output structure**:

```
builds/
├── windows/
│   ├── MyGame.exe
│   └── steam_api64.dll
├── macos/
│   └── MyGame.app/
├── linux/
│   ├── MyGame.x86_64
│   └── libsteam_api.so
└── webgl/
    ├── index.html
    └── Build/
        └── MyGame.data.gz
```

---

## Steam Integration by Engine

### Comparison

| Engine | Steam Plugin | Difficulty | Native Support | Performance |
|--------|-------------|-----------|----------------|-------------|
| **Unity** | Steamworks.NET | Easy | ⭐⭐⭐⭐ | Excellent |
| **Godot** | GodotSteam | Easy | ⭐⭐⭐⭐ | Excellent |
| **HTML5** | Steamworks.js (experimental) | Hard | ⭐⭐ | Good (WebGL) |

### Feature Parity

| Feature | Unity | Godot | HTML5 |
|---------|-------|-------|-------|
| **Achievements** | ✅ | ✅ | ⚠️ Limited |
| **Cloud Saves** | ✅ | ✅ | ⚠️ Limited |
| **Leaderboards** | ✅ | ✅ | ⚠️ Limited |
| **Multiplayer (P2P)** | ✅ | ✅ | ❌ |
| **Workshop** | ✅ | ✅ | ❌ |
| **Overlay** | ✅ | ✅ | ❌ |

---

## Complete Deployment Example

### Unity Game to Steam + Itch.io

```bash
# 1. Import project
templedb project import ~/projects/my-unity-game

# 2. Initialize Steam
templedb steam init my-unity-game --app-id 123456 --engine unity

# 3. Build all platforms
templedb deploy build-matrix my-unity-game \
  --platforms windows,macos,linux,webgl \
  --output ./builds/

# 4. Upload to Steam (Windows, macOS, Linux)
templedb deploy steam my-unity-game \
  --platforms windows,macos,linux \
  --branch default

# 5. Upload WebGL build to Itch.io
templedb deploy itch my-unity-game \
  --platform webgl \
  --itch-user yourusername \
  --game mygame

# Done! Game is live on Steam and Itch.io
```

### Godot Game to Steam

```bash
# 1. Import project
templedb project import ~/projects/my-godot-game

# 2. Initialize Steam
templedb steam init my-godot-game --app-id 123456 --engine godot

# 3. Install GodotSteam (manual)
# Download from: https://github.com/GodotSteam/GodotSteam/releases

# 4. Build for Steam platforms
templedb deploy build-matrix my-godot-game \
  --platforms windows,macos,linux \
  --output ./builds/

# 5. Upload to Steam
templedb deploy steam my-godot-game --branch default

# Done!
```

### HTML5 Game to Itch.io

```bash
# 1. Import project
templedb project import ~/projects/my-html5-game

# 2. Build for production
templedb deploy build my-html5-game --format html5 --output ./dist/

# 3. Upload to Itch.io
templedb deploy itch my-html5-game \
  --type html5 \
  --itch-user yourusername \
  --game mygame

# Done! Game is live on Itch.io
```

---

## Conclusion

TempleDB provides **unified deployment** for games across all major engines:

### Key Benefits

1. **Engine Agnostic**: Unity, Godot, HTML5 all use same CLI
2. **Multi-Platform**: Automated builds for Windows, macOS, Linux, WebGL
3. **Steam Integration**: Achievements, cloud saves, multiplayer
4. **Streamlined Workflow**: Single command to build and deploy

### Next Steps

- [ ] Implement Unity headless builds (`templedb deploy build --engine unity`)
- [ ] Implement Godot command-line export (`templedb deploy build --engine godot`)
- [ ] Steam integration testing with Steamworks.NET and GodotSteam
- [ ] Itch.io butler integration for automated uploads
- [ ] CI/CD templates for GitHub Actions (automated builds on commit)

**Document Status**: Implementation Guide
**Last Updated**: 2026-03-21
