# TempleDB TUI - Nix Package

The TUI is now available as a standalone Nix package with all dependencies bundled.

## Quick Start

```bash
# Build the package
nix build .#templedb-tui

# Run it
./result/bin/templedb-tui

# Or install to your profile
nix profile install .#templedb-tui
templedb-tui
```

## What's Included

The Nix package includes:
- Python 3.11 environment
- `textual` - TUI framework
- `rich` - Terminal formatting
- All TempleDB source files
- Wrapper script with proper PYTHONPATH

## Package Structure

```
/nix/store/.../templedb-tui-1.0.0/
├── bin/
│   └── templedb-tui          # Wrapper script (347 bytes)
└── lib/templedb/src/
    ├── tui.py                # Main TUI application
    ├── db_utils.py           # Database utilities
    ├── config.py             # Configuration
    └── ... (all other .py files)
```

## How It Works

The package uses `makeWrapper` to create a small bash script that:

1. Sets `PYTHONPATH` to include the bundled source files
2. Calls the Python environment with all dependencies
3. Runs `tui.py` with any arguments passed

Example wrapper script:
```bash
#!/nix/store/.../bash -e
export PYTHONPATH='/nix/store/.../templedb-tui-1.0.0/lib/templedb/src'
exec "/nix/store/.../python3-3.11.14-env/bin/python3" \
  /nix/store/.../templedb-tui-1.0.0/lib/templedb/src/tui.py "$@"
```

## Advantages Over Zipapp

| Feature | Nix Package | Zipapp |
|---------|-------------|---------|
| **Dependencies** | Bundled | Must install separately |
| **Reproducibility** | ✅ Nix guarantees | ⚠️ Depends on system Python |
| **Build system** | Nix flake | Python zipapp |
| **Installation** | `nix profile install` | Copy file |
| **Updates** | `nix flake update` | Rebuild manually |
| **Size** | ~10MB (with deps) | ~120KB (no deps) |
| **Portability** | Any Nix system | Any Python 3.11+ system |

## Development

To modify the TUI package:

1. Edit `default.nix` - Package definition
2. Edit `flake.nix` - Flake outputs
3. Edit `src/tui.py` - TUI code

```bash
# Test changes
nix build .#templedb-tui
./result/bin/templedb-tui

# Or use in dev shell
nix develop
python3 src/tui.py
```

## Integration with TempleDB

The TUI package is exposed in the flake as:

```nix
{
  packages = {
    templedb-tui = ...;  # TUI package
    default = ...;        # Points to templedb-tui
  };

  devShells.default = {
    # Dev shell includes TUI dependencies
    packages = [ ... python311Packages.textual ... ];
  };
}
```

## Distribution

Users can run the TUI without cloning the repo:

```bash
# Run directly from GitHub
nix run github:yourusername/templedb#templedb-tui

# Install from GitHub
nix profile install github:yourusername/templedb#templedb-tui
```

## Comparison with buildFHSUserEnv

TempleDB uses both packaging strategies:

| Use Case | Technology |
|----------|------------|
| **TUI application** | `stdenv.mkDerivation` + `makeWrapper` |
| **Project environments** | `buildFHSUserEnv` (for FHS compatibility) |
| **Development shell** | `mkShell` |

The TUI doesn't need FHS compatibility because:
- Pure Python code (no compiled binaries expecting /usr/lib)
- All dependencies are Python packages
- No system-level library expectations

FHS environments are used for **project-specific** shells where:
- Projects may expect traditional paths (`/usr/bin`, `/lib`)
- Mix of Python, Node.js, system tools
- Running binaries that weren't built with Nix

## See Also

- [TUI.md](TUI.md) - Full TUI documentation
- [default.nix](default.nix) - Package definition
- [flake.nix](flake.nix) - Flake configuration
- [src/tui.py](src/tui.py) - TUI source code
