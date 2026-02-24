# TempleDB TUI - Build Guide

Complete guide to building standalone executables of the TempleDB TUI.

## Overview

The TempleDB TUI can be built as a standalone executable using three different methods:

1. **Nix Package** (Recommended for NixOS) - Clean, reproducible, all dependencies bundled
2. **PyInstaller** - Fully standalone binary, no Python required on target system
3. **Python Zipapp** - Single file, requires Python + dependencies on target

## Quick Start

### Interactive Build Menu

```bash
./build_tui.sh
```

This launches an interactive menu where you can choose your build method.

### Non-Interactive Build

```bash
# Nix package (recommended)
./build_tui.sh nix

# PyInstaller binary
./build_tui.sh pyinstaller

# Python zipapp
./build_tui.sh zipapp

# Try all methods
./build_tui.sh all
```

## Method 1: Nix Package (Recommended)

### Requirements

- Nix package manager installed
- NixOS or any Linux with Nix

### Build

```bash
nix-build default.nix -o result-tui
```

Or use the build script:

```bash
./build_tui.sh nix
```

### Output

- **Location**: `result-tui/bin/templedb-tui`
- **Size**: ~356 bytes (wrapper script + dependencies in /nix/store)
- **Dependencies**: All bundled in /nix/store, isolated from system

### Installation

System-wide:
```bash
sudo cp result-tui/bin/templedb-tui /usr/local/bin/
```

User-local:
```bash
mkdir -p ~/.local/bin
cp result-tui/bin/templedb-tui ~/.local/bin/
```

### Advantages

- ✅ Clean, reproducible builds
- ✅ Dependencies automatically managed
- ✅ Nix store handles transitive dependencies
- ✅ Can be used in NixOS system configuration
- ✅ Easy to share (just the result symlink)

### Disadvantages

- ❌ Requires Nix to be installed
- ❌ Not portable to non-Nix systems

## Method 2: PyInstaller

### Requirements

- Python 3.11+
- PyInstaller
- textual (python311Packages.textual)
- rich (python311Packages.rich)

### Install PyInstaller

With Nix:
```bash
nix-shell -p python311Packages.pyinstaller python311Packages.textual python311Packages.rich
```

With pip:
```bash
pip install --user pyinstaller textual rich
```

### Build

```bash
./build_binary.sh
```

Or:
```bash
./build_tui.sh pyinstaller
```

### Output

- **Location**: `dist/templedb-tui`
- **Size**: ~50-100 MB (fully standalone)
- **Dependencies**: All bundled into single executable

### Installation

System-wide:
```bash
sudo cp dist/templedb-tui /usr/local/bin/
```

User-local:
```bash
mkdir -p ~/.local/bin
cp dist/templedb-tui ~/.local/bin/
```

### Advantages

- ✅ Fully standalone - no Python required on target
- ✅ Single binary file
- ✅ Works on any Linux system
- ✅ No external dependencies

### Disadvantages

- ❌ Large binary size (~50-100 MB)
- ❌ Requires PyInstaller to build
- ❌ May have compatibility issues on different distros

## Method 3: Python Zipapp

### Requirements

- Python 3.11+ (on build and target systems)
- Built-in zipapp module (no extra tools needed)

### Build

```bash
./build_zipapp.sh
```

Or:
```bash
./build_tui.sh zipapp
```

### Output

- **Location**: `dist/templedb-tui`
- **Size**: ~50-100 KB (just the Python code)
- **Dependencies**: Python, textual, rich must be installed on target

### Installation

System-wide:
```bash
sudo cp dist/templedb-tui /usr/local/bin/
```

User-local:
```bash
mkdir -p ~/.local/bin
cp dist/templedb-tui ~/.local/bin/
```

### Running (Target System)

Requires dependencies:
```bash
# With Nix
nix-shell -p python311 python311Packages.textual python311Packages.rich
./templedb-tui

# With pip
pip install --user textual rich
./templedb-tui
```

### Advantages

- ✅ Small file size (~50-100 KB)
- ✅ Easy to build (no extra tools)
- ✅ Easy to distribute (single file)

### Disadvantages

- ❌ Requires Python on target system
- ❌ Requires textual + rich installed on target
- ❌ Not truly standalone

## Build Script Details

### build_tui.sh

Interactive menu for all build methods:

```bash
./build_tui.sh
```

Menu options:
- **1** - Nix Package (best for NixOS)
- **2** - PyInstaller (fully standalone)
- **3** - Python Zipapp (needs Python + deps)
- **4** - All Methods (try everything)
- **q** - Quit

### build_binary.sh

PyInstaller build with optimizations:

```bash
./build_binary.sh
```

Features:
- Dependency checking
- UPX compression
- Excludes unnecessary modules (matplotlib, numpy, pandas, etc.)
- Strip debug symbols
- One-file bundle

### build_zipapp.sh

Simple zipapp builder:

```bash
./build_zipapp.sh
```

Features:
- Creates `__main__.py` entry point
- Compression enabled
- Shebang for direct execution

### default.nix

Nix package definition:

```bash
nix-build default.nix -o result-tui
```

Features:
- Uses `python.withPackages` for dependency management
- `makeWrapper` for clean wrapper script
- All transitive dependencies handled automatically

## Comparison Table

| Method | Size | Dependencies | Portability | Build Time | Recommended For |
|--------|------|--------------|-------------|------------|-----------------|
| **Nix** | ~356 B | Bundled | NixOS only | Fast | NixOS users |
| **PyInstaller** | ~50-100 MB | None | All Linux | Slow | Non-Nix systems |
| **Zipapp** | ~50-100 KB | Requires Python | All Linux | Fast | Development/testing |

## Troubleshooting

### Nix Build Fails

**Error**: `ModuleNotFoundError: No module named 'typing_extensions'`

**Solution**: The current `default.nix` uses `python.withPackages` which handles all transitive dependencies automatically. If you see this error, you may be using an older version. Use the latest `default.nix`:

```nix
let
  pythonEnv = python.withPackages (ps: with ps; [
    textual
    rich
  ]);
in
pkgs.stdenv.mkDerivation {
  # ...
  installPhase = ''
    makeWrapper ${pythonEnv}/bin/python3 $out/bin/templedb-tui \
      --add-flags "$out/lib/templedb/src/templedb_tui.py"
  '';
}
```

### PyInstaller Not Found

**Error**: `pyinstaller: command not found`

**Solution**: Install PyInstaller:

```bash
# With Nix
nix-shell -p python311Packages.pyinstaller

# With pip
pip install --user pyinstaller
```

### Zipapp Import Errors

**Error**: `ModuleNotFoundError: No module named 'textual'`

**Solution**: Zipapp doesn't bundle dependencies. Install them:

```bash
# With Nix
nix-shell -p python311Packages.textual python311Packages.rich

# With pip
pip install --user textual rich
```

### Binary Size Too Large (PyInstaller)

**Issue**: PyInstaller binary is 100+ MB

**Solutions**:
1. Already excludes matplotlib, numpy, pandas, scipy
2. UPX compression is enabled
3. Strip is enabled

To manually reduce further, edit `build_binary.sh` and add more excludes:

```python
excludes=[
    'matplotlib', 'numpy', 'pandas', 'scipy',
    'PyQt5', 'tkinter',
    # Add more here
],
```

### Build Fails on Non-NixOS

**Issue**: Nix build works but binary doesn't run on target

**Solution**: Use PyInstaller method instead - it creates truly portable binaries:

```bash
./build_tui.sh pyinstaller
```

## Testing the Binary

After building, test the binary:

```bash
# Nix
result-tui/bin/templedb-tui

# PyInstaller or Zipapp
dist/templedb-tui
```

You should see the TempleDB TUI launch with the main screen.

## Distribution

### For NixOS Users

Share the Nix expression:

```bash
# They can build with:
nix-build https://github.com/yourusername/templedb/raw/master/default.nix -o templedb-tui
```

Or add to their system configuration:

```nix
environment.systemPackages = [
  (import /path/to/templedb/default.nix { inherit pkgs; })
];
```

### For Non-NixOS Users

Distribute the PyInstaller binary:

```bash
# Build once
./build_tui.sh pyinstaller

# Share the binary
scp dist/templedb-tui user@remote:/usr/local/bin/
```

### For Developers

Distribute the zipapp:

```bash
# Build
./build_tui.sh zipapp

# Share with instructions to install deps
scp dist/templedb-tui user@remote:~/
echo "Install: pip install --user textual rich"
```

## Build Artifacts

After building, you may have:

```
templeDB/
├── build/              # PyInstaller build artifacts
├── dist/               # PyInstaller and zipapp outputs
│   └── templedb-tui    # Binary or zipapp
├── result-tui/         # Nix build output (symlink)
│   └── bin/
│       └── templedb-tui
└── __pycache__/        # Python cache files
```

Clean build artifacts:

```bash
rm -rf build/ dist/ __pycache__/ result-tui
```

## Advanced Usage

### Custom Python Version (Nix)

Edit `default.nix`:

```nix
let
  python = pkgs.python312;  # Use Python 3.12
  # ...
```

### Custom Install Location (PyInstaller)

Edit `build_binary.sh` and change the spec file:

```python
exe = EXE(
    # ...
    name='my-custom-name',  # Change binary name
)
```

### Include Data Files (All Methods)

For Nix, edit `default.nix`:

```nix
installPhase = ''
  # ...
  cp -r data/ $out/lib/templedb/data/
'';
```

For PyInstaller, edit the spec file in `build_binary.sh`:

```python
datas=[
    ('data/', 'data/'),  # Include data directory
],
```

## Integration with NixOS

### System-wide Installation

Add to `/etc/nixos/configuration.nix`:

```nix
{ config, pkgs, ... }:

let
  templedb-tui = import /path/to/templedb/default.nix { inherit pkgs; };
in
{
  environment.systemPackages = [ templedb-tui ];
}
```

### User Environment

Add to `~/.config/nixpkgs/home.nix`:

```nix
{ pkgs, ... }:

let
  templedb-tui = import /path/to/templedb/default.nix { inherit pkgs; };
in
{
  home.packages = [ templedb-tui ];
}
```

## Performance Considerations

### Nix Build

- **First build**: ~30 seconds (downloads dependencies)
- **Subsequent builds**: ~5 seconds (cached)
- **Startup time**: ~1 second

### PyInstaller Build

- **Build time**: ~2-5 minutes (bundles everything)
- **Startup time**: ~2-3 seconds (extracts to temp)

### Zipapp Build

- **Build time**: ~1 second (just zips files)
- **Startup time**: ~1 second

## Related Documentation

- [NIX_ENVIRONMENTS.md](NIX_ENVIRONMENTS.md) - Using Nix environments feature
- [REFACTORING_PLAN.md](REFACTORING_PLAN.md) - Code quality improvements
- [README.md](README.md) - General TempleDB documentation

## In Honor of Terry Davis

The TempleDB TUI build system demonstrates multiple paths to the same goal, respecting user choice and system diversity. Terry Davis believed in simplicity and user empowerment - these build tools embody that philosophy.

> "An idiot admires complexity, a genius admires simplicity."
> - Terry A. Davis (1969-2018)
