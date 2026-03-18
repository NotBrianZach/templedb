# Dynamic System Configuration

**Date**: 2026-03-12
**Status**: ✅ Complete

## Overview

Implemented database-driven system configuration management to decouple NixOS/home-manager deployments from hardcoded hostnames. The system now uses a `system_config` table to store deployment settings with intelligent auto-detection fallbacks.

## Problem Solved

**Before**: The `_rebuild_home_manager()` method in `SystemService` was hardcoded to use `socket.gethostname()` to build the flake path:

```python
hostname = socket.gethostname()  # Always "zMothership2"
build_path = f"{flake_path}#nixosConfigurations.{hostname}.config.home-manager.users.{username}.home.activationPackage"
```

This made it impossible to:
- Test different configurations
- Use multiple machines with the same config
- Override flake output names that differ from hostname

**After**: Configuration is stored in database with auto-detect fallbacks:

```python
flake_output = self.get_system_config('nixos.flake_output')
if not flake_output:
    import socket
    flake_output = socket.gethostname()
```

## Implementation

### 1. Database Schema (Migration 032)

Created `system_config` table:

```sql
CREATE TABLE system_config (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL UNIQUE,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Default keys**:
- `nixos.flake_output` - Flake output name (e.g., "zMothership2")
- `nixos.hostname` - System hostname for builds
- `nixos.username` - Username for home-manager builds

Empty values trigger auto-detection from system.

### 2. SystemService Methods

Added to `src/services/system_service.py`:

```python
def get_system_config(self, key: str) -> Optional[str]:
    """Get config value or None if empty/not set"""

def set_system_config(self, key: str, value: str) -> None:
    """Set config value with timestamp update"""

def list_system_config(self) -> List[Dict[str, Any]]:
    """List all config entries with descriptions"""
```

### 3. CLI Commands

Added to `src/cli/commands/nixos.py`:

```bash
# View configuration
./templedb nixos config-list

# Get specific value
./templedb nixos config-get nixos.flake_output

# Set value
./templedb nixos config-set nixos.flake_output zMothership2

# Clear value (triggers auto-detect)
./templedb nixos config-set nixos.username ""
```

### 4. Updated _rebuild_home_manager()

Modified method to use database config with auto-detect fallbacks:

```python
def _rebuild_home_manager(self, flake_path: Path) -> Dict[str, Any]:
    # Get from database or auto-detect
    flake_output = self.get_system_config('nixos.flake_output')
    if not flake_output:
        import socket
        flake_output = socket.gethostname()
        logger.info(f"Auto-detected flake output: {flake_output}")

    username = self.get_system_config('nixos.username')
    if not username:
        username = getpass.getuser()
        logger.info(f"Auto-detected username: {username}")

    # Build with configured/detected values
    build_path = f"{flake_path}#nixosConfigurations.{flake_output}.config.home-manager.users.{username}.home.activationPackage"
```

## Usage Examples

### First-time Setup

```bash
# Set your machine's flake output name
./templedb nixos config-set nixos.flake_output zMothership2

# Set username if different from current user
./templedb nixos config-set nixos.username zach

# Verify configuration
./templedb nixos config-list
```

### System Rebuild with home-manager

```bash
# Now this uses database config instead of hardcoded hostname
./templedb nixos system-switch system_config --with-home-manager
```

### Testing Different Configurations

```bash
# Switch to test configuration
./templedb nixos config-set nixos.flake_output testMachine

# Test the config
./templedb nixos system-test system_config --dry-run

# Switch back
./templedb nixos config-set nixos.flake_output zMothership2
```

### Auto-detection

```bash
# Clear value to use auto-detect
./templedb nixos config-set nixos.flake_output ""

# Now rebuilds will use socket.gethostname()
./templedb nixos system-switch system_config --with-home-manager
```

## Benefits

1. **Flexibility**: Change deployment target without code changes
2. **Multi-machine**: Same codebase can deploy to different machines
3. **Testing**: Easy to test different configurations
4. **Transparency**: Configuration visible via CLI commands
5. **Backwards Compatible**: Auto-detect ensures existing workflows still work
6. **Database-native**: All config changes are ACID transactions

## Testing

```bash
# Run migration
sqlite3 ~/.local/share/templedb/templedb.sqlite < migrations/032_add_system_config.sql

# Test commands
./templedb nixos config-list
./templedb nixos config-set nixos.flake_output zMothership2
./templedb nixos config-get nixos.flake_output

# Verify in database
sqlite3 ~/.local/share/templedb/templedb.sqlite "SELECT * FROM system_config"
```

## Files Modified

- `migrations/032_add_system_config.sql` - New table and defaults
- `src/services/system_service.py` - Config methods and updated rebuild logic
- `src/cli/commands/nixos.py` - New config-get/set/list commands

## Migration Path

Existing installations work without changes:
1. Run migration 032 to create table
2. Empty config values trigger auto-detection
3. Gradually set explicit values as needed

## Future Enhancements

Potential additions:
- `nixos.flake_url` - Support remote flakes
- `nixos.build_flags` - Custom nix build flags
- `nixos.rebuild_timeout` - Configurable timeouts
- UI in TUI for config management

---

✅ Implementation complete and tested
🎯 Solves the "tightly coupled to zMothership2" issue
📊 All configuration tracked in database
